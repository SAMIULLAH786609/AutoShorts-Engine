"""
AutoShorts Engine — APScheduler Daemon.

Runs the pipeline automatically twice a day at the configured times.

Usage
-----
    python run.py --schedule     # recommended
    python autoshorts/scheduler.py   # direct

The upload times are read from .env:
    UPLOAD_TIME_1=10:00
    UPLOAD_TIME_2=18:00
    DAILY_VIDEO_COUNT=2          (videos per trigger)
"""

from __future__ import annotations

import signal
import sys
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import DAILY_VIDEO_COUNT, UPLOAD_TIME_1, UPLOAD_TIME_2
from autoshorts.services.logging_setup import get_logger, log_step

log = get_logger("scheduler")


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute) integers."""
    try:
        hour, minute = time_str.strip().split(":")
        return int(hour), int(minute)
    except Exception:
        log.warning(
            "Invalid time format '%s' — defaulting to 10:00", time_str
        )
        return 10, 0


def scheduled_job() -> None:
    """Called by APScheduler at each configured time."""
    log_step(log, "SCHEDULED RUN", f"Producing {DAILY_VIDEO_COUNT} video(s)…")

    try:
        from autoshorts.pipeline import run_daily_batch
        results = run_daily_batch(count=DAILY_VIDEO_COUNT)
        log.info(
            "Scheduled run complete: %d video(s) uploaded.", len(results)
        )
    except Exception as exc:
        log.error("Scheduled run failed: %s", exc)


def start_scheduler() -> None:
    """Configure and start the blocking scheduler."""
    scheduler = BlockingScheduler(timezone="local")

    h1, m1 = _parse_time(UPLOAD_TIME_1)
    h2, m2 = _parse_time(UPLOAD_TIME_2)

    scheduler.add_job(
        scheduled_job,
        CronTrigger(hour=h1, minute=m1),
        id="upload_slot_1",
        name=f"Daily upload #{1} at {UPLOAD_TIME_1}",
        misfire_grace_time=600,
    )

    scheduler.add_job(
        scheduled_job,
        CronTrigger(hour=h2, minute=m2),
        id="upload_slot_2",
        name=f"Daily upload #{2} at {UPLOAD_TIME_2}",
        misfire_grace_time=600,
    )

    log.info(
        "Scheduler started. Upload times: %s and %s (local time)",
        UPLOAD_TIME_1, UPLOAD_TIME_2,
    )
    log.info("Press Ctrl+C to stop.")

    # Graceful shutdown on SIGTERM (useful in Docker/cloud)
    def _shutdown(signum, frame):
        log.info("Received signal %s — shutting down scheduler…", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Scheduler stopped by user.")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    start_scheduler()
