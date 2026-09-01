"""
AutoShorts Backend — Pydantic Schemas (request/response validation).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


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
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number")
        return v


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


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str = Field(..., min_length=8)


# ─────────────────────────────────────────────────────────────
# User Schemas
# ─────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id:               str
    email:            str
    name:             str
    is_active:        bool
    is_verified:      bool
    channel_niche:    str
    default_language: str
    default_gender:   str
    default_privacy:  str
    videos_per_day:   int
    created_at:       datetime

    model_config = {"from_attributes": True}


class UpdateSettingsRequest(BaseModel):
    name:             Optional[str] = None
    channel_niche:    Optional[str] = None
    default_language: Optional[str] = None
    default_gender:   Optional[str] = None
    default_privacy:  Optional[str] = None
    videos_per_day:   Optional[int] = Field(None, ge=1, le=10)


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
    retry_count:      int
    duration:         float
    trigger:          str
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
