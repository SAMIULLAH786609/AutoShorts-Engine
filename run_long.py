"""
AutoShorts Engine — Long-form Hindi Video Runner.
Usage: python run_long.py
"""
from autoshorts.services.logging_setup import configure_logging, log_step
from autoshorts.long_video_pipeline import run_long_video_pipeline

log = configure_logging()

if __name__ == "__main__":
    log_step(log, "RUN LONG VIDEO", "Starting 1 daily long-form Hindi video...")
    res = run_long_video_pipeline()
    if res:
        print(f"\nSUCCESS: https://youtu.be/{res.youtube_video_id}")
    else:
        print("\nFailed or skipped.")

