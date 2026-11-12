"""
AutoShorts Backend — Pydantic Schemas (request/response validation).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


def _check_password_strength(v: str) -> str:
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one number")
    # bcrypt only uses the first 72 bytes; newer bcrypt versions reject longer input
    if len(v.encode("utf-8")) > 72:
        raise ValueError("Password is too long (max 72 bytes)")
    return v


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _check_hhmm(v: Optional[str]) -> Optional[str]:
    """Validate HH:MM — a malformed time would crash the scheduler every minute."""
    if v is None:
        return v
    v = v.strip()[:5]   # accept "09:00:00" sent by some browsers
    if not _HHMM_RE.match(v):
        raise ValueError("Time must be in HH:MM (24-hour) format")
    return v


# ─────────────────────────────────────────────────────────────
# Auth Schemas
# ─────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name:     str      = Field(..., min_length=2,  max_length=100)
    email:    EmailStr
    password: str      = Field(..., min_length=8,  max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _check_password_strength(v)


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         "UserResponse"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token:        str
    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _check_password_strength(v)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str = Field(..., min_length=8, max_length=100)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _check_password_strength(v)


# ─────────────────────────────────────────────────────────────
# User Schemas
# ─────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id:               str
    email:            str
    name:             str
    is_active:        bool
    is_verified:      bool
    channel_niche:    Optional[str] = None
    default_language: Optional[str] = "English"
    default_gender:   Optional[str] = "female"
    default_privacy:  Optional[str] = "private"
    videos_per_day:   Optional[int] = 3
    created_at:       datetime

    model_config = {"from_attributes": True}


class UpdateSettingsRequest(BaseModel):
    name:             Optional[str] = Field(None, min_length=2, max_length=100)
    channel_niche:    Optional[str] = Field(None, max_length=255)
    default_language: Optional[str] = Field(None, max_length=20)
    default_gender:   Optional[str] = None
    default_privacy:  Optional[str] = None
    videos_per_day:   Optional[int] = Field(None, ge=1, le=10)

    @field_validator("default_gender")
    @classmethod
    def valid_gender(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("female", "male"):
            raise ValueError("default_gender must be 'female' or 'male'")
        return v

    @field_validator("default_privacy")
    @classmethod
    def valid_privacy(cls, v: Optional[str]) -> Optional[str]:
        # YouTube rejects any other value at upload time, failing every video
        if v is not None and v not in ("private", "unlisted", "public"):
            raise ValueError("default_privacy must be 'private', 'unlisted' or 'public'")
        return v


# ─────────────────────────────────────────────────────────────
# YouTube Channel Schemas
# ─────────────────────────────────────────────────────────────

class ChannelResponse(BaseModel):
    id:            str
    channel_id:    str
    channel_name:  Optional[str]
    channel_url:   Optional[str]
    thumbnail_url: Optional[str]
    is_connected:  bool
    connected_at:  datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────
# Video Job Schemas
# ─────────────────────────────────────────────────────────────

class JobResponse(BaseModel):
    id:               str
    status:           str
    topic:            Optional[str]
    title:            Optional[str]
    style:            Optional[str]
    video_url:        Optional[str]
    thumbnail_url:    Optional[str]
    youtube_video_id: Optional[str]
    youtube_url:      Optional[str]
    error_message:    Optional[str]
    retry_count:      Optional[int] = 0
    duration:         Optional[float] = 0.0
    trigger:          Optional[str] = "manual"
    created_at:       datetime
    started_at:       Optional[datetime]
    completed_at:     Optional[datetime]
    # YouTube live stats
    yt_views:         Optional[int] = 0
    yt_likes:         Optional[int] = 0
    yt_comments:      Optional[int] = 0
    yt_stats_updated: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TriggerJobRequest(BaseModel):
    channel_id: Optional[str] = None   # None = use first connected channel


# ─────────────────────────────────────────────────────────────
# Schedule Schemas
# ─────────────────────────────────────────────────────────────

class ScheduleResponse(BaseModel):
    id:             str
    videos_per_day: int
    time_slot_1:    Optional[str] = None
    time_slot_2:    Optional[str] = None
    time_slot_3:    Optional[str] = None
    start_time:     Optional[str] = "09:00"
    end_time:       Optional[str] = "23:00"
    timezone:       str
    is_active:      bool

    model_config = {"from_attributes": True}


class UpdateScheduleRequest(BaseModel):
    videos_per_day: Optional[int]  = Field(None, ge=1, le=100)
    start_time:     Optional[str]  = None
    end_time:       Optional[str]  = None
    # Legacy slots still accepted
    time_slot_1:    Optional[str]  = None
    time_slot_2:    Optional[str]  = None
    time_slot_3:    Optional[str]  = None
    timezone:       Optional[str]  = None
    is_active:      Optional[bool] = None

    @field_validator("start_time", "end_time", "time_slot_1", "time_slot_2", "time_slot_3")
    @classmethod
    def valid_time(cls, v: Optional[str]) -> Optional[str]:
        return _check_hhmm(v)


# ─────────────────────────────────────────────────────────────
# Dashboard Schemas
# ─────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_videos:     int
    uploaded_videos:  int
    failed_videos:    int
    pending_videos:   int
    next_scheduled:   Optional[str]
    channel_connected: bool
    recent_jobs:      list[JobResponse]
