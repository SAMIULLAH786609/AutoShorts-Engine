"""
AutoShorts Backend — APScheduler (24/7 automated video generation).

Runs in the same process as FastAPI.
Every minute, checks all active users and fires video generation
based on their configured schedule (start_time, end_time, videos_per_day).
Videos are distributed evenly across the day between start_time and end_time.

CRASH-SAFE RETRY:
If the server crashes (OOM) mid-job, any "running" or "pending" jobs that are
stuck (no progress for >10 minutes) are automatically retried. This means even
if Render kills the process, the scheduler will restart the job once the server
recovers — no manual intervention needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger("autoshorts.scheduler")

_scheduler: BackgroundScheduler | None = None

# Jobs stuck longer than this are considered crashed and retried
STUCK_JOB_TIMEOUT_MINUTES = 10

# Max automatic retries for any single day's slot
MAX_AUTO_RETRIES = 3


def _compute_slots(start_time: str, end_time: str, videos_per_day: int) -> list[str]:
    """
    Distribute `videos_per_day` evenly between start_time and end_time.
    Returns a list of HH:MM strings (UTC).
    """
    if videos_per_day <= 0:
        return []

    def parse(t: str):
        h, m = map(int, t.split(":"))
        return h * 60 + m

    start_min = parse(start_time or "09:00")
    end_min   = parse(end_time   or "23:00")

    if start_min > end_min:
        end_min = start_min

    # Bug 6 fixed: if start == end (degenerate range), return a single slot.
    # Previously, step = 0 / (videos_per_day - 1) = 0.0 which produced N identical
    # slots — causing the scheduler to fire multiple jobs at the exact same minute.
    if start_min == end_min or videos_per_day == 1:
        slots_min = [start_min]
    else:
        step = (end_min - start_min) / (videos_per_day - 1)
        slots_min = [int(round(start_min + i * step)) for i in range(videos_per_day)]

    result = []
    for m in slots_min:
        h, mm = divmod(m, 60)
        result.append(f"{h:02d}:{mm:02d}")
    return result


def start_scheduler() -> None:
    """Start the APScheduler background scheduler."""
    global _scheduler

    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")

    # Check every minute: fire jobs and recover crashed ones
    _scheduler.add_job(
        _check_and_fire_scheduled_jobs,
        trigger          = CronTrigger(minute="*"),
        id               = "scheduled_video_check",
        replace_existing = True,
        max_instances    = 1,
    )

    _scheduler.start()
    log.info("APScheduler started — monitoring schedules + auto-recovering crashed jobs every minute")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("APScheduler stopped")


def _fire_new_job(user_id: str, channel_id: str, trigger: str, db, retry_count: int = 0):
    """Create a VideoJob record and start the pipeline thread."""
    import threading
    from backend.models import VideoJob
    from backend.routers.jobs import _run_pipeline_task

    job = VideoJob(
        user_id     = user_id,
        channel_id  = channel_id,
        status      = "pending",
        trigger     = trigger,
        retry_count = retry_count,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    t = threading.Thread(
        target = _run_pipeline_task,
        args   = (job.id, user_id, channel_id),
        daemon = True,
        name   = f"pipeline-{job.id[:8]}",
    )
    t.start()
    return job


def _check_and_fire_scheduled_jobs() -> None:
    """
    Called every minute. Does two things:
    1. CRASH RECOVERY — auto-recovers stuck jobs.
    2. SCHEDULED SHORTS — evenly spaced between start_time and end_time.
    """
    from backend.database import SessionLocal
    from backend.models import User, UserSchedule, YouTubeChannel, VideoJob

    db = SessionLocal()

    try:
        now_utc      = datetime.now(timezone.utc)
        now_time     = now_utc.strftime("%H:%M")
        today_start  = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        stuck_cutoff = now_utc - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)

        # ── PART 1: CRASH RECOVERY ────────────────────────────────────────────
        stuck_jobs = (
            db.query(VideoJob)
            .filter(
                VideoJob.status.in_(["pending", "running"]),
                VideoJob.created_at <= stuck_cutoff,
            )
            .all()
        )

        for stuck in stuck_jobs:
            retry_count = (stuck.retry_count or 0) + 1
            if retry_count > MAX_AUTO_RETRIES:
                stuck.status        = "failed"
                stuck.error_message = f"[Auto] Gave up after {MAX_AUTO_RETRIES} crash recoveries (OOM)"
                stuck.retry_count   = retry_count
                db.commit()
                log.warning("Job %s gave up after %d crash recoveries", stuck.id[:8], MAX_AUTO_RETRIES)
                continue

            channel = (
                db.query(YouTubeChannel)
                .filter(YouTubeChannel.id == stuck.channel_id)
                .first()
            )
            if not channel:
                continue

            stuck.status        = "failed"
            stuck.error_message = f"[Auto-retry {retry_count}/{MAX_AUTO_RETRIES}] Server ran out of memory (OOM). Retrying now..."
            stuck.retry_count   = retry_count
            db.commit()

            new_job = _fire_new_job(
                user_id     = stuck.user_id,
                channel_id  = stuck.channel_id,
                trigger     = "retry",
                db          = db,
                retry_count = retry_count,
            )
            log.info("CRASH RECOVERY: stuck job %s -> new job %s", stuck.id[:8], new_job.id[:8])

        # ── PART 2: SCHEDULED FIRING ─────────────────────────────────────────
        schedules = (
            db.query(UserSchedule)
            .filter(UserSchedule.is_active == True)
            .all()
        )

        for schedule in schedules:
            user: User = schedule.user
            if not user or not user.is_active:
                continue

            max_videos = schedule.videos_per_day or 3
            start = schedule.start_time or schedule.time_slot_1 or "09:00"
            end   = schedule.end_time   or schedule.time_slot_3 or "23:00"
            all_slots = _compute_slots(start, end, max_videos)

            due_slots = [s for s in all_slots if now_time >= s]
            if not due_slots:
                continue

            # Count scheduled jobs already done today
            today_jobs = (
                db.query(VideoJob)
                .filter(
                    VideoJob.user_id    == user.id,
                    VideoJob.trigger    == "scheduled",
                    VideoJob.created_at >= today_start,
                    VideoJob.status.in_(["pending", "running", "complete"]),
                )
                .count()
            )

            if today_jobs >= len(due_slots):
                continue

            # Don't start if something is already running/pending
            running = (
                db.query(VideoJob)
                .filter(
                    VideoJob.user_id == user.id,
                    VideoJob.status.in_(["pending", "running"]),
                )
                .first()
            )
            if running:
                log.info("Skipping schedule for user %s — job already running", user.id)
                continue

            channel = (
                db.query(YouTubeChannel)
                .filter(
                    YouTubeChannel.user_id      == user.id,
                    YouTubeChannel.is_connected == True,
                )
                .first()
            )
            if not channel:
                log.warning("No channel for user %s — skipping schedule", user.email)
                continue

            new_job = _fire_new_job(
                user_id    = user.id,
                channel_id = channel.id,
                trigger    = "scheduled",
                db         = db,
            )
            log.info(
                "Scheduled job fired for user %s | slot %d/%d at %s UTC (job %s)",
                user.email, today_jobs + 1, max_videos, now_time, new_job.id[:8],
            )

    except Exception as exc:
        log.exception("Scheduler check failed: %s", exc)

    finally:
        db.close()
