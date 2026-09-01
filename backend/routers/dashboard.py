"""
AutoShorts Backend — Dashboard + Schedule + Email Routers.
"""

from __future__ import annotations

# ── Dashboard Router ──────────────────────────────────────────

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.auth_service import get_current_user
from backend.database import get_db
from backend.models import User, VideoJob, YouTubeChannel
from backend.schemas import DashboardStats, JobResponse, ScheduleResponse, UpdateScheduleRequest

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@dashboard_router.get("", response_model=DashboardStats)
def get_dashboard(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Return dashboard statistics for the current user."""
    jobs = db.query(VideoJob).filter(VideoJob.user_id == current_user.id)

    total    = jobs.count()
    uploaded = jobs.filter(VideoJob.status == "complete").count()
    failed   = jobs.filter(VideoJob.status == "failed").count()
    pending  = jobs.filter(VideoJob.status.in_(["pending", "running"])).count()

    channel_connected = (
        db.query(YouTubeChannel)
        .filter(YouTubeChannel.user_id == current_user.id, YouTubeChannel.is_connected == True)
        .count()
    ) > 0

    recent = (
        db.query(VideoJob)
        .filter(VideoJob.user_id == current_user.id)
        .order_by(VideoJob.created_at.desc())
        .limit(10)
        .all()
    )

    # Bug 9 fixed: Use actual start_time/end_time and _compute_slots() to compute
    # the real next scheduled run — not the legacy time_slot_1 field.
    schedule = current_user.schedule
    next_scheduled = None
    if schedule and schedule.is_active:
        from backend.scheduler import _compute_slots
        from datetime import datetime, timezone
        now_time = datetime.now(timezone.utc).strftime("%H:%M")
        start = schedule.start_time or schedule.time_slot_1 or "09:00"
        end   = schedule.end_time   or schedule.time_slot_3 or "23:00"
        vpd   = schedule.videos_per_day or 1
        slots = _compute_slots(start, end, vpd)
        # Find the next slot that hasn't passed yet today
        future_slots = [s for s in slots if s > now_time]
        if future_slots:
            next_scheduled = f"Today at {future_slots[0]} UTC"
        else:
            next_scheduled = f"Tomorrow at {slots[0]} UTC" if slots else None

    return DashboardStats(
        total_videos      = total,
        uploaded_videos   = uploaded,
        failed_videos     = failed,
        pending_videos    = pending,
        next_scheduled    = next_scheduled,
        channel_connected = channel_connected,
        recent_jobs       = [JobResponse.model_validate(j) for j in recent],
    )


# ── Schedule Router ───────────────────────────────────────────

from backend.models import UserSchedule

schedule_router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@schedule_router.get("", response_model=ScheduleResponse)
def get_schedule(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    schedule = current_user.schedule
    if not schedule:
        # Create default if missing
        schedule = UserSchedule(
            user_id        = current_user.id,
            videos_per_day = 3,
            time_slot_1    = "09:00",
            time_slot_2    = "15:00",
            time_slot_3    = "21:00",
            start_time     = "09:00",
            end_time       = "23:00",
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

    return schedule


@schedule_router.put("", response_model=ScheduleResponse)
def update_schedule(
    body:         UpdateScheduleRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    schedule = current_user.schedule
    if not schedule:
        schedule = UserSchedule(user_id=current_user.id)
        db.add(schedule)
        db.flush()

    if body.videos_per_day is not None: schedule.videos_per_day = body.videos_per_day
    if body.start_time     is not None: schedule.start_time     = body.start_time
    if body.end_time       is not None: schedule.end_time       = body.end_time
    if body.time_slot_1    is not None: schedule.time_slot_1    = body.time_slot_1
    if body.time_slot_2    is not None: schedule.time_slot_2    = body.time_slot_2
    if body.time_slot_3    is not None: schedule.time_slot_3    = body.time_slot_3
    if body.timezone       is not None: schedule.timezone       = body.timezone
    if body.is_active      is not None: schedule.is_active      = body.is_active

    db.commit()
    db.refresh(schedule)
    return schedule
