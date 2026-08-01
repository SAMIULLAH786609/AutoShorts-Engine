"""
AutoShorts Backend — APScheduler (24/7 automated video generation).

Runs in the same process as FastAPI.
Every minute, checks all active users and fires video generation
based on their configured schedule (start_time, end_time, videos_per_day).
Videos are distributed evenly across the day between start_time and end_time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger("autoshorts.scheduler")

_scheduler: BackgroundScheduler | None = None


def _compute_slots(start_time: str, end_time: str, videos_per_day: int) -> list[str]:
    """
    Distribute `videos_per_day` evenly between start_time and end_time.
    Returns a list of HH:MM strings (UTC).

    Examples:
      start=09:00, end=23:00, count=4  → ["09:00","13:40","18:20","23:00"]
      start=09:00, end=09:00, count=1  → ["09:00"]
    """
    if videos_per_day <= 0:
        return []

    def parse(t: str):
        h, m = map(int, t.split(":"))
        return h * 60 + m

    start_min = parse(start_time or "09:00")
    end_min   = parse(end_time   or "23:00")

    if start_min > end_min:
        end_min = start_min  # safety

    if videos_per_day == 1:
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

    # Check every minute: fire jobs for users whose scheduled time matches
    _scheduler.add_job(
        _check_and_fire_scheduled_jobs,
        trigger    = CronTrigger(minute="*"),  # every minute
        id         = "scheduled_video_check",
        replace_existing = True,
        max_instances    = 1,                  # never run twice at same time
    )

    _scheduler.start()
    log.info("APScheduler started — monitoring user schedules every minute")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("APScheduler stopped")


def _check_and_fire_scheduled_jobs() -> None:
    """
    Called every minute. Checks every active user's schedule.
    Fires video generation for any time slot that is due today and has not yet run.
    Supports unlimited videos_per_day distributed evenly between start_time and end_time.
    """
    from backend.database import SessionLocal
    from backend.models import User, UserSchedule, YouTubeChannel, VideoJob

    db = SessionLocal()

    try:
        now_utc     = datetime.now(timezone.utc)
        now_time    = now_utc.strftime("%H:%M")   # e.g. "09:00"
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        # Get all users with active schedules
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

            # Compute evenly-spaced slots using new start/end time if available
            start = schedule.start_time or schedule.time_slot_1 or "09:00"
            end   = schedule.end_time   or schedule.time_slot_3 or "23:00"
            all_slots = _compute_slots(start, end, max_videos)

            # Find how many slots are due (time has passed or equals) today
            due_slots = [s for s in all_slots if now_time >= s]
            if not due_slots:
                continue

            # Count scheduled jobs already created today for this user
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

            # If we've already fired enough jobs for all due slots, skip
            if today_jobs >= len(due_slots):
                continue

            # Do not start a new job if one is already pending or running
            running = (
                db.query(VideoJob)
                .filter(
                    VideoJob.user_id == user.id,
                    VideoJob.status.in_(["pending", "running"]),
                )
                .first()
            )
            if running:
                log.info(
                    "Skipping schedule for user %s — a job is currently pending/running", user.id
                )
                continue

            # Get first connected channel
            channel = (
                db.query(YouTubeChannel)
                .filter(
                    YouTubeChannel.user_id      == user.id,
                    YouTubeChannel.is_connected == True,
                )
                .first()
            )

            if not channel:
                log.warning("No channel for scheduled user %s — skipping", user.email)
                continue

            # Create the job record
            job = VideoJob(
                user_id    = user.id,
                channel_id = channel.id,
                status     = "pending",
                trigger    = "scheduled",
            )
            db.add(job)
            db.commit()
            db.refresh(job)

            log.info(
                "Scheduled job created for user %s | slot %d/%d at %s UTC (job id: %s)",
                user.email, today_jobs + 1, max_videos, now_time, job.id,
            )

            # Fire the pipeline in a new background thread
            import threading
            from backend.routers.jobs import _run_pipeline_task

            t = threading.Thread(
                target = _run_pipeline_task,
                args   = (job.id, user.id, channel.id),
                daemon = True,
                name   = f"pipeline-{job.id[:8]}",
            )
            t.start()

    except Exception as exc:
        log.exception("Scheduler check failed: %s", exc)

    finally:
        db.close()
