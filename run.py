"""
AutoShorts Engine — Single command entry point.

Usage
-----
    python run.py             # run one full pipeline cycle now
    python run.py --count 2   # run N videos now
    python run.py --schedule  # start the scheduler (runs forever)

Environment
-----------
All configuration is read from .env (see .env.example).
"""

from __future__ import annotations

import argparse
import sys

from autoshorts.services.logging_setup import configure_logging, log_step

# Configure logging before anything else
log = configure_logging()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AutoShorts Engine — fully automated AI Shorts creator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                # produce today's videos right now
  python run.py --count 1      # produce exactly 1 video
  python run.py --schedule     # start the long-running scheduler daemon
        """,
    )

    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Number of videos to produce (overrides DAILY_VIDEO_COUNT in .env)",
    )

    parser.add_argument(
        "--long",
        action="store_true",
        help="Produce 1 long-form Hindi video (16:9 1080p, worldwide trends)",
    )

    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Start the APScheduler daemon instead of running once",
    )

    args = parser.parse_args()

    if args.long:
        log_step(log, "LONG VIDEO MODE", "Starting 1 long-form Hindi video generation…")
        from autoshorts.long_video_pipeline import run_long_video_pipeline
        result = run_long_video_pipeline()
        if result:
            log.info("\n✅ Long video uploaded successfully: https://youtu.be/%s", result.youtube_video_id)
        else:
            log.warning("\n⚠️ Long video generation was skipped or failed.")
        return

    if args.schedule:
        log_step(log, "SCHEDULER MODE", "Starting APScheduler daemon…")
        from autoshorts.scheduler import start_scheduler
        start_scheduler()
        return

    # One-shot run
    from config import DAILY_VIDEO_COUNT
    from autoshorts.pipeline import run_daily_batch

    count = args.count if args.count is not None else DAILY_VIDEO_COUNT

    log_step(log, "RUN MODE", f"Producing {count} video(s)…")

    try:
        results = run_daily_batch(count=count)
        log.info(
            "\n✅  Done. %d video(s) uploaded successfully.", len(results)
        )

        for r in results:
            log.info(
                "  ▶  %s  →  https://youtu.be/%s",
                r.title, r.youtube_video_id,
            )

    except KeyboardInterrupt:
        log.info("\nCancelled by user.")
        sys.exit(0)

    except Exception as exc:
        log.error("Fatal error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
