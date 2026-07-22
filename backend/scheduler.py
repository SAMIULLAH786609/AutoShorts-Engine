"""
AutoShorts Backend — APScheduler (24/7 automated video generation).

Runs in the same process as FastAPI.
Every minute, checks all active users and fires video generation
at their configured time slots.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger("autoshorts.scheduler")

_scheduler: BackgroundScheduler | None = None


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
    Called every minute (or upon server wake-up). Checks every active user's schedule.
    Fires video generation for any time slot that is due today and has not yet run.
    """
    from backend.database import SessionLocal
    from backend.models import User, UserSchedule, YouTubeChannel, VideoJob

    db = SessionLocal()

    try:
        now_utc  = datetime.now(timezone.utc)
        now_time = now_utc.strftime("%H:%M")   # e.g. "09:00"
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
            slots = [schedule.time_slot_1, schedule.time_slot_2, schedule.time_slot_3]
            active_slots = [s for s in slots[:max_videos] if s]

            # Find slots that are due today up to the current time
            due_slots = [s for s in active_slots if now_time >= s]
            if not due_slots:
                continue

            # Check scheduled jobs already created today for this user
            today_jobs = (
                db.query(VideoJob)
                .filter(
                    VideoJob.user_id   == user.id,
                    VideoJob.trigger   == "scheduled",
                    VideoJob.created_at >= today_start,
                    VideoJob.status.in_(["pending", "running", "complete"]),
                )
                .count()
            )

            # If we've already fired jobs for all currently due slots, skip
            if today_jobs >= len(due_slots):
                continue

            # Check if a job is currently pending or running
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
                    YouTubeChannel.user_id    == user.id,
                    YouTubeChannel.is_connected == True,
                )
                .first()
            )

            if not channel:
                log.warning("No channel for scheduled user %s — skipping", user.email)
                continue

            # Create the job
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
                "Scheduled job created for user %s at current time %s for due slots %d (job id: %s)",
                user.email, now_time, len(due_slots), job.id,
            )

            # Fire the pipeline in a new thread to avoid blocking the scheduler
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
