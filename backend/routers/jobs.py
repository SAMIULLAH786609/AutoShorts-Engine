"""
AutoShorts Backend — Jobs Router.

Endpoints:
  GET    /api/jobs         — list user's video jobs (paginated)
  GET    /api/jobs/{id}    — single job details
  POST   /api/jobs/trigger — manually trigger a pipeline run
  DELETE /api/jobs/{id}    — delete a job record
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.auth_service import get_current_user
from backend.database import get_db
from backend.models import User, VideoJob, YouTubeChannel
from backend.schemas import JobResponse, TriggerJobRequest

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


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

    # Check if a job is already running
    running = (
        db.query(VideoJob)
        .filter(
            VideoJob.user_id == current_user.id,
            VideoJob.status  == "running",
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


# ── Delete job ────────────────────────────────────────────────

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

    if job.status == "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a running job",
        )

    db.delete(job)
    db.commit()


# ── Background task ───────────────────────────────────────────

def _run_pipeline_task(job_id: str, user_id: str, channel_id: str) -> None:
    """
    Background function that runs the full pipeline for one user.
    Updates job status in the database throughout.
    """
    from backend.database import SessionLocal
    db = SessionLocal()

    try:
        job  = db.query(VideoJob).filter(VideoJob.id == job_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        channel = db.query(YouTubeChannel).filter(YouTubeChannel.id == channel_id).first()

        if not job or not user or not channel:
            return

        # Mark as running
        job.status     = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        # Run the pipeline
        from backend.pipeline_runner import run_pipeline_for_user
        result = run_pipeline_for_user(user=user, channel=channel, db=db, job_id=job.id)

        # Update job with results
        job.status           = "complete"
        job.completed_at     = datetime.now(timezone.utc)
        job.topic            = result.get("topic", "")
        job.title            = result.get("title", "")
        job.style            = result.get("style", "")
        job.video_url        = result.get("video_url", "")
        job.thumbnail_url    = result.get("thumbnail_url", "")
        job.youtube_video_id = result.get("youtube_video_id", "")
        job.youtube_url      = f"https://youtu.be/{result.get('youtube_video_id', '')}" if result.get("youtube_video_id") else ""
        job.duration         = result.get("duration", 0.0)
        db.commit()

    except Exception as exc:
        # Mark as failed
        try:
            job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
            if job:
                job.status        = "failed"
                job.completed_at  = datetime.now(timezone.utc)
                job.error_message = str(exc)[:2000]
                job.retry_count   = (job.retry_count or 0) + 1
                db.commit()
        except Exception:
            pass

    finally:
        db.close()
