"""
AutoShorts Backend — Jobs Router.

Endpoints:
  GET    /api/jobs         — list user's video jobs (paginated)
  GET    /api/jobs/{id}    — single job details
  POST   /api/jobs/trigger — manually trigger a pipeline run
  DELETE /api/jobs/{id}    — delete a job record
"""

from __future__ import annotations

import gc
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.auth_service import get_current_user
from backend.database import get_db
from backend.models import User, VideoJob, YouTubeChannel
from backend.schemas import JobResponse, TriggerJobRequest

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# ── Pipeline concurrency control ──────────────────────────────
# Strict global mutex — only ONE video can generate at a time system-wide.
_GLOBAL_PIPELINE_LOCK = threading.Lock()

MAX_AUTO_RETRIES = 3      # Maximum automatic retry attempts per failed job
RETRY_DELAY_SEC  = 30     # Seconds to wait before each auto-retry


def is_pipeline_running() -> bool:
    """Return True if a video pipeline is currently executing."""
    locked = _GLOBAL_PIPELINE_LOCK.acquire(blocking=False)
    if locked:
        _GLOBAL_PIPELINE_LOCK.release()
        return False
    return True


# ── List jobs ─────────────────────────────────────────────────

@router.get("", response_model=List[JobResponse])
def list_jobs(
    page:         int          = Query(1, ge=1),
    page_size:    int          = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db:           Session      = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """List all video jobs for the current user, newest first."""
    query = (
        db.query(VideoJob)
        .filter(VideoJob.user_id == current_user.id)
    )

    if status_filter:
        query = query.filter(VideoJob.status == status_filter)

    total = query.count()
    jobs  = (
        query
        .order_by(VideoJob.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return jobs


# ── Single job ────────────────────────────────────────────────

@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id:       str,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    job = (
        db.query(VideoJob)
        .filter(VideoJob.id == job_id, VideoJob.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Trigger a new pipeline run ────────────────────────────────

@router.post("/trigger", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def trigger_job(
    body:             TriggerJobRequest,
    background_tasks: BackgroundTasks,
    db:               Session = Depends(get_db),
    current_user:     User    = Depends(get_current_user),
):
    """
    Manually trigger a video generation pipeline run.
    The job runs in the background — returns the job record immediately.
    """
    # Resolve channel
    channel: Optional[YouTubeChannel] = None

    if body.channel_id:
        channel = (
            db.query(YouTubeChannel)
            .filter(
                YouTubeChannel.id      == body.channel_id,
                YouTubeChannel.user_id == current_user.id,
                YouTubeChannel.is_connected == True,
            )
            .first()
        )
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found or not connected")
    else:
        # Use first connected channel
        channel = (
            db.query(YouTubeChannel)
            .filter(
                YouTubeChannel.user_id    == current_user.id,
                YouTubeChannel.is_connected == True,
            )
            .first()
        )

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No YouTube channel connected. Please connect your channel in Settings first.",
        )

    # Check if a job is already running or about to start
    if is_pipeline_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A video is currently generating. Please wait for it to finish.",
        )

    running = (
        db.query(VideoJob)
        .filter(
            VideoJob.user_id == current_user.id,
            VideoJob.status.in_(["pending", "running", "uploading"]),
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A video is already being generated. Please wait for it to finish.",
        )

    # Create job record
    job = VideoJob(
        user_id    = current_user.id,
        channel_id = channel.id,
        status     = "pending",
        trigger    = "manual",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Run in background
    background_tasks.add_task(_run_pipeline_task, job.id, current_user.id, channel.id)

    return job


# ── Cancel / Stop job ──────────────────────────────────────────

@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id:       str,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Cancel a running or pending video generation job (or reset a stuck one)."""
    job = (
        db.query(VideoJob)
        .filter(VideoJob.id == job_id, VideoJob.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ("running", "pending"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a job with status '{job.status}'",
        )

    # Update database status to failed to unblock the user immediately
    job.status        = "failed"
    job.error_message = "Cancelled by user."
    job.completed_at  = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)

    return job


# ── Refresh YouTube Stats ─────────────────────────────────────

@router.post("/{job_id}/refresh-stats", response_model=JobResponse)
def refresh_yt_stats(
    job_id:       str,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Fetch latest views, likes, comments from YouTube Data API and save them."""
    job = (
        db.query(VideoJob)
        .filter(VideoJob.id == job_id, VideoJob.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.youtube_video_id:
        raise HTTPException(status_code=400, detail="No YouTube video ID for this job")

    # Get the channel that actually uploaded this video, to build OAuth credentials
    channel = (
        db.query(YouTubeChannel)
        .filter(YouTubeChannel.id == job.channel_id, YouTubeChannel.user_id == current_user.id)
        .first()
    )
    if not channel:
        raise HTTPException(status_code=400, detail="No connected YouTube channel")

    try:
        from backend.youtube_stats import fetch_video_stats
        stats = fetch_video_stats(channel=channel, video_id=job.youtube_video_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"YouTube API error: {exc}")

    job.yt_views         = stats.get("views", 0)
    job.yt_likes         = stats.get("likes", 0)
    job.yt_comments      = stats.get("comments", 0)
    job.yt_stats_updated = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)

    return job



@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id:       str,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    job = (
        db.query(VideoJob)
        .filter(VideoJob.id == job_id, VideoJob.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ("pending", "running", "uploading"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a running job",
        )

    db.delete(job)
    db.commit()



def _run_pipeline_task(job_id: str, user_id: str, channel_id: str) -> None:
    """Run a durable job; never restart an upload whose outcome is uncertain."""
    import logging
    from sqlalchemy import text
    from backend.database import SessionLocal, engine

    log = logging.getLogger("autoshorts.jobs")
    if not _GLOBAL_PIPELINE_LOCK.acquire(blocking=False):
        # Leave it pending so the scheduler can dispatch it when capacity is free.
        return
    db = None
    lock_connection = None
    try:
        # Keep a dedicated transaction open so the lock also works behind
        # transaction-pooling database proxies.
        if engine.dialect.name == "postgresql":
            lock_connection = engine.connect()
            acquired = lock_connection.execute(text("SELECT pg_try_advisory_xact_lock(731904211)")).scalar()
            if not acquired:
                return

        db = SessionLocal()
        while True:
            job = db.query(VideoJob).filter(VideoJob.id == job_id).with_for_update().first()
            if not job or job.status != "pending":
                db.rollback()
                return
            user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
            channel = db.query(YouTubeChannel).filter(
                YouTubeChannel.id == channel_id, YouTubeChannel.user_id == user_id,
                YouTubeChannel.is_connected == True,
            ).first()
            if not user or not channel:
                job.status = "failed"
                job.error_message = "Account inactive or YouTube channel disconnected."
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                return
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.completed_at = None
            job.error_message = None
            db.commit()
            try:
                gc.collect()
                from backend.pipeline_runner import run_pipeline_for_user
                result = run_pipeline_for_user(user=user, channel=channel, db=db, job_id=job_id)
                db.refresh(job)
                job.status = "complete"
                job.error_message = None
                job.completed_at = datetime.now(timezone.utc)
                for key in ("topic", "title", "style", "video_url", "thumbnail_url", "youtube_video_id", "duration"):
                    if key in result:
                        setattr(job, key, result[key])
                job.youtube_url = f"https://youtu.be/{job.youtube_video_id}" if job.youtube_video_id else ""
                db.commit()
                return
            except Exception as exc:
                log.exception("Pipeline job %s failed", job_id)
                db.rollback()
                db.expire_all()
                job = db.query(VideoJob).filter(VideoJob.id == job_id).with_for_update().first()
                if not job:
                    return
                if job.youtube_video_id:
                    # Upload is durable even if later bookkeeping failed.
                    job.status = "complete"
                    job.error_message = None
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return
                if job.status == "failed" and "Cancelled" in (job.error_message or ""):
                    return
                if job.status == "uploading":
                    job.status = "failed"
                    job.error_message = (
                        "YouTube upload could not be confirmed. Check your channel before retrying "
                        "to avoid a duplicate. Details: " + str(exc)[:1200]
                    )
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return
                job.retry_count = (job.retry_count or 0) + 1
                job.error_message = f"[Attempt {job.retry_count}] {str(exc)[:1800]}"
                if job.retry_count >= MAX_AUTO_RETRIES:
                    job.status = "failed"
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return
                job.status = "pending"
                db.commit()
                # Same job identity preserves schedule accounting and retry limits.
                time.sleep(RETRY_DELAY_SEC)
    except Exception:
        log.exception("Could not execute job %s", job_id)
        if db is not None:
            db.rollback()
    finally:
        if db is not None:
            db.close()
        if lock_connection is not None:
            try:
                lock_connection.rollback()
            finally:
                lock_connection.close()
        _GLOBAL_PIPELINE_LOCK.release()
        gc.collect()
