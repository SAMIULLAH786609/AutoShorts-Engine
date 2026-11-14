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
        slots_min = sorted(set(int(round(start_min + i * step)) for i in range(videos_per_day)))

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

    # Only explicitly opted-in accounts are eligible for zero-view removal.
    _scheduler.add_job(
        _auto_delete_zero_view_videos,
        trigger=CronTrigger(minute=15, timezone="UTC"),
        id="auto_delete_zero_views", replace_existing=True, max_instances=1,
    )

    # Every hour: pull fresh views/likes/comments for all uploaded Shorts from YouTube API
    _scheduler.add_job(
        _refresh_all_shorts_stats,
        trigger          = CronTrigger(minute=0),   # top of every hour
        id               = "refresh_shorts_stats",
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
    Enforces STRICT SINGLE-JOB concurrency: only 1 video runs across the system.
    """
    from backend.database import SessionLocal
    from backend.models import User, UserSchedule, YouTubeChannel, VideoJob
    from backend.routers.jobs import is_pipeline_running

    if is_pipeline_running():
        log.info("A video is currently generating (lock held). Skipping scheduler tick.")
        return

    db = SessionLocal()

    try:
        # Do not recover a healthy job owned by another server process.
        from backend.database import engine
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            with engine.connect() as conn:
                available = conn.execute(text("SELECT pg_try_advisory_xact_lock(731904211)")).scalar()
                conn.rollback()
                if not available:
                    return
        now_utc      = datetime.now(timezone.utc)
        now_time     = now_utc.strftime("%H:%M")
        today_start  = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        stuck_cutoff = now_utc - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)

        # If a non-stuck job is already active in the DB, do NOT start any new job!
        active_in_db = (
            db.query(VideoJob)
            .filter(
                VideoJob.status.in_(["running", "uploading"]),
                VideoJob.created_at > stuck_cutoff,
            )
            .first()
        )
        if active_in_db:
            log.info("Job %s is currently active in DB. Skipping new triggers.", active_in_db.id[:8])
            return

        # ── PART 1: CRASH RECOVERY ────────────────────────────────────────────
        stuck_jobs = (
            db.query(VideoJob)
            .filter(
                VideoJob.status.in_(["running", "uploading"]),
                VideoJob.created_at <= stuck_cutoff,
            )
            .all()
        )

        for stuck in stuck_jobs:
            if stuck.status == "uploading":
                stuck.status = "complete" if stuck.youtube_video_id else "failed"
                stuck.completed_at = now_utc
                stuck.error_message = None if stuck.youtube_video_id else (
                    "Server stopped during YouTube upload. Check your channel before retrying; "
                    "the upload may already exist."
                )
                db.commit()
                continue
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

            stuck.status        = "pending"
            stuck.error_message = f"[Recovery {retry_count}/{MAX_AUTO_RETRIES}] Interrupted before upload; retrying."
            stuck.retry_count   = retry_count
            db.commit()

        # Dispatch queued/recovered jobs without deleting or replacing their history.
        pending = db.query(VideoJob).filter(VideoJob.status == "pending").order_by(VideoJob.created_at).first()
        if pending:
            import threading
            from backend.routers.jobs import _run_pipeline_task
            threading.Thread(
                target=_run_pipeline_task, args=(pending.id, pending.user_id, pending.channel_id),
                daemon=True, name=f"pipeline-{pending.id[:8]}",
            ).start()
            return

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

            # Count scheduled slots already attempted today. Failed attempts
            # count too: their recovery is handled by the auto-retry logic
            # (trigger="retry"), so re-firing here would create a new video
            # every minute whenever a slot fails.
            today_jobs = (
                db.query(VideoJob)
                .filter(
                    VideoJob.user_id    == user.id,
                    VideoJob.trigger    == "scheduled",
                    VideoJob.created_at >= today_start,
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
                    VideoJob.status.in_(["pending", "running", "uploading"]),
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
            # Strict single-job concurrency: other users wait for the next tick.
            return

    except Exception as exc:
        log.exception("Scheduler check failed: %s", exc)

    finally:
        db.close()


# ── Hourly Auto-Refresh: Shorts Views/Likes/Comments ──────────────────────────

# Only refresh stats for videos uploaded within this many days
STATS_REFRESH_WINDOW_DAYS = 30

# Minimum gap between two refreshes for the same video (minutes)
STATS_REFRESH_MIN_GAP_MINUTES = 50


def _refresh_all_shorts_stats() -> None:
    """
    Hourly job (every :00).

    For all completed VideoJobs with a youtube_video_id uploaded in the last
    STATS_REFRESH_WINDOW_DAYS days, fetch the latest views/likes/comments from
    the YouTube Data API and save them to the DB.

    Skips videos whose stats were refreshed less than
    STATS_REFRESH_MIN_GAP_MINUTES minutes ago to avoid hammering the API.
    """
    from backend.database import SessionLocal
    from backend.models import VideoJob, YouTubeChannel
    from backend.youtube_stats import fetch_video_stats

    log.info("STATS-REFRESH: Starting hourly Shorts stats refresh...")

    db = SessionLocal()
    updated = 0
    skipped = 0
    errors  = 0

    try:
        window_cutoff  = datetime.now(timezone.utc) - timedelta(days=STATS_REFRESH_WINDOW_DAYS)
        stale_cutoff   = datetime.now(timezone.utc) - timedelta(minutes=STATS_REFRESH_MIN_GAP_MINUTES)

        # Fetch all uploaded jobs within the refresh window
        jobs = (
            db.query(VideoJob)
            .filter(
                VideoJob.status           == "complete",
                VideoJob.youtube_video_id != None,
                VideoJob.youtube_video_id != "",
                VideoJob.completed_at     >= window_cutoff,
            )
            .all()
        )

        log.info("STATS-REFRESH: %d uploaded Shorts in window.", len(jobs))

        for job in jobs:
            # Skip if stats are fresh enough
            if job.yt_stats_updated and job.yt_stats_updated > stale_cutoff:
                skipped += 1
                continue

            channel = (
                db.query(YouTubeChannel)
                .filter(YouTubeChannel.id == job.channel_id)
                .first()
            )
            if not channel:
                skipped += 1
                continue

            try:
                stats = fetch_video_stats(channel=channel, video_id=job.youtube_video_id)
                job.yt_views         = stats.get("views",    0)
                job.yt_likes         = stats.get("likes",    0)
                job.yt_comments      = stats.get("comments", 0)
                job.yt_stats_updated = datetime.now(timezone.utc)
                db.commit()
                updated += 1
                log.info(
                    "STATS-REFRESH: video %s → views=%d likes=%d comments=%d",
                    job.youtube_video_id,
                    job.yt_views, job.yt_likes, job.yt_comments,
                )
            except Exception as exc:
                errors += 1
                log.warning(
                    "STATS-REFRESH: Failed to refresh stats for video %s (job %s): %s",
                    job.youtube_video_id, job.id[:8], exc,
                )

    except Exception as exc:
        log.exception("STATS-REFRESH: Unexpected error: %s", exc)

    finally:
        db.close()

    log.info(
        "STATS-REFRESH: Done — updated=%d, skipped=%d, errors=%d.",
        updated, skipped, errors,
    )


# ── Auto-Delete Zero-View Videos ──────────────────────────────────────────────

def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _zero_view_delete_eligible(job, user, channel, stats: dict, now: datetime) -> bool:
    """Require explicit consent, a new upload, and complete fresh public stats."""
    if not user.is_active or not user.auto_delete_zero_views or not user.auto_delete_enabled_at:
        return False
    if job.status != "complete" or not job.youtube_video_id or not job.completed_at:
        return False
    if not channel.is_connected or channel.user_id != user.id or job.user_id != user.id:
        return False
    if stats.get("channel_id") != channel.channel_id:
        return False
    # Missing/unavailable counts are unknown, never zero.
    if stats.get("privacy") != "public" or type(stats.get("views")) is not int or stats["views"] != 0:
        return False
    hours = user.auto_delete_after_hours
    if not isinstance(hours, int) or not 24 <= hours <= 720:
        return False
    cutoff = _utc(now) - timedelta(hours=hours)
    if _utc(job.completed_at) < _utc(user.auto_delete_enabled_at) or _utc(job.completed_at) > cutoff:
        return False
    try:
        published = datetime.fromisoformat(stats["published_at"].replace("Z", "+00:00"))
        if published.tzinfo is None:
            return False
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
    # A video made public recently gets the full waiting period, too.
    return _utc(published) <= cutoff


def _auto_delete_zero_view_videos() -> None:
    """Hourly check of opted-in users; retain an audit row after remote removal."""
    from backend.database import SessionLocal
    from backend.models import User, VideoJob, YouTubeChannel
    from backend.youtube_stats import fetch_video_stats, delete_youtube_video

    db = SessionLocal()
    removed = 0
    try:
        # Only process uploads completed after the user enabled the rule.
        candidates = [row[0] for row in db.query(VideoJob.id).join(User, User.id == VideoJob.user_id).filter(
            User.is_active == True, User.auto_delete_zero_views == True,
            User.auto_delete_enabled_at != None,
            VideoJob.status == "complete", VideoJob.youtube_video_id != None,
            VideoJob.youtube_video_id != "",
            VideoJob.completed_at >= User.auto_delete_enabled_at,
            VideoJob.completed_at <= datetime.now(timezone.utc) - timedelta(hours=24),
        ).order_by(VideoJob.completed_at).all()]
        db.rollback()
        for job_id in candidates:
            try:
                # Independent workers cannot remove the same job concurrently.
                with db.begin():
                    job = db.query(VideoJob).filter(VideoJob.id == job_id).with_for_update(skip_locked=True).first()
                    if not job or job.status != "complete":
                        continue
                    user = db.query(User).filter(User.id == job.user_id).with_for_update().first()
                    channel = db.query(YouTubeChannel).filter(
                        YouTubeChannel.id == job.channel_id,
                        YouTubeChannel.user_id == job.user_id,
                        YouTubeChannel.is_connected == True,
                    ).first()
                    if not user or not channel or not user.auto_delete_zero_views:
                        continue
                    now = datetime.now(timezone.utc)
                    if not user.auto_delete_enabled_at or not job.completed_at:
                        continue
                    if _utc(job.completed_at) > now - timedelta(hours=user.auto_delete_after_hours):
                        continue
                    stats = fetch_video_stats(channel=channel, video_id=job.youtube_video_id)
                    if not _zero_view_delete_eligible(job, user, channel, stats, now):
                        continue
                    if not delete_youtube_video(channel=channel, video_id=job.youtube_video_id):
                        log.warning("Zero-view removal failed for job %s; retained for a later check", job_id)
                        continue
                    job.status = "deleted"
                    job.youtube_deleted_at = now
                    job.deletion_reason = f"Automatically removed: 0 views after {user.auto_delete_after_hours} hours."
                    job.yt_views = 0
                    job.yt_stats_updated = now
                    job.error_message = None
                    removed += 1
                    log.info("YouTube confirmed zero-view removal for job %s", job_id)
            except Exception:
                db.rollback()
                log.exception("Zero-view check failed for job %s; no further action this tick", job_id)
    except Exception:
        db.rollback()
        log.exception("Zero-view cleanup check failed")
    finally:
        db.close()
    log.info("Zero-view check finished: %d videos removed", removed)
