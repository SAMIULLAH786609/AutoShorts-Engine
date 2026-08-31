"""
AutoShorts Backend — SQLAlchemy ORM Models.

All models in one file for simplicity. Tables:
  - users            : accounts
  - youtube_channels : per-user connected YouTube channels
  - video_jobs       : pipeline run records
  - user_schedules   : when to auto-generate videos
  - used_topics      : per-user topic deduplication
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id                   = Column(String, primary_key=True, default=_new_uuid)
    email                = Column(String(255), unique=True, nullable=False, index=True)
    name                 = Column(String(100), nullable=False)
    password_hash        = Column(String(255), nullable=False)
    is_active            = Column(Boolean, default=True, nullable=False)
    is_verified          = Column(Boolean, default=False, nullable=False)

    # Password reset
    reset_token          = Column(String(255), nullable=True)
    reset_token_expires  = Column(DateTime(timezone=True), nullable=True)

    # Channel niche / preferences
    channel_niche        = Column(String(255), default="Interesting facts and viral stories")
    default_language     = Column(String(20),  default="English")
    default_gender       = Column(String(10),  default="female")
    default_privacy      = Column(String(20),  default="private")
    videos_per_day       = Column(Integer,      default=3)

    created_at           = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at           = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    channels    = relationship("YouTubeChannel", back_populates="user", cascade="all, delete-orphan")
    jobs        = relationship("VideoJob",       back_populates="user", cascade="all, delete-orphan")
    schedule    = relationship("UserSchedule",   back_populates="user", cascade="all, delete-orphan", uselist=False)
    used_topics = relationship("UsedTopic",      back_populates="user", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────
# YouTube Channels
# ─────────────────────────────────────────────────────────────

class YouTubeChannel(Base):
    __tablename__ = "youtube_channels"

    id              = Column(String, primary_key=True, default=_new_uuid)
    user_id         = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id      = Column(String(100), nullable=False)
    channel_name    = Column(String(255), nullable=True)
    channel_url     = Column(String(500), nullable=True)
    thumbnail_url   = Column(String(500), nullable=True)

    # Tokens stored ENCRYPTED — never in plain text
    access_token_enc  = Column(Text, nullable=True)   # encrypted
    refresh_token_enc = Column(Text, nullable=True)   # encrypted
    token_expires_at  = Column(DateTime(timezone=True), nullable=True)

    is_connected    = Column(Boolean, default=True)
    connected_at    = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User", back_populates="channels")
    jobs = relationship("VideoJob", back_populates="channel")

    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", name="uq_user_channel"),
    )


# ─────────────────────────────────────────────────────────────
# Video Jobs
# ─────────────────────────────────────────────────────────────

class VideoJob(Base):
    __tablename__ = "video_jobs"

    id               = Column(String, primary_key=True, default=_new_uuid)
    user_id          = Column(String, ForeignKey("users.id",            ondelete="CASCADE"), nullable=False, index=True)
    channel_id       = Column(String, ForeignKey("youtube_channels.id", ondelete="SET NULL"), nullable=True)

    # Status: pending | running | complete | failed
    status           = Column(String(20), default="pending", nullable=False, index=True)

    # Content metadata
    topic            = Column(String(500), nullable=True)
    title            = Column(String(255), nullable=True)
    script           = Column(Text,        nullable=True)
    style            = Column(String(50),  nullable=True)

    # Output URLs (stored on Cloudinary)
    video_url        = Column(String(1000), nullable=True)
    thumbnail_url    = Column(String(1000), nullable=True)
    local_video_path = Column(String(1000), nullable=True)

    # YouTube result
    youtube_video_id = Column(String(50),  nullable=True)
    youtube_url      = Column(String(200), nullable=True)

    # YouTube stats (refreshed on demand)
    yt_views         = Column(Integer, default=0, nullable=True)
    yt_likes         = Column(Integer, default=0, nullable=True)
    yt_comments      = Column(Integer, default=0, nullable=True)
    yt_stats_updated = Column(DateTime(timezone=True), nullable=True)

    # Error tracking
    error_message    = Column(Text, nullable=True)
    retry_count      = Column(Integer, default=0)

    # Duration (seconds)
    duration         = Column(Float, default=0.0)

    # Video Type: short (9:16 vertical) | long (16:9 full HD)
    video_type       = Column(String(20), default="short")

    # Trigger type: manual | scheduled | retry
    trigger          = Column(String(20), default="manual")

    created_at       = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    started_at       = Column(DateTime(timezone=True), nullable=True)
    completed_at     = Column(DateTime(timezone=True), nullable=True)

    user    = relationship("User",           back_populates="jobs")
    channel = relationship("YouTubeChannel", back_populates="jobs")


# ─────────────────────────────────────────────────────────────
# User Schedules
# ─────────────────────────────────────────────────────────────

class UserSchedule(Base):
    __tablename__ = "user_schedules"

    id             = Column(String, primary_key=True, default=_new_uuid)
    user_id        = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    videos_per_day = Column(Integer, default=3)

    # Legacy fixed slots (kept for backward compat)
    time_slot_1    = Column(String(5), default="09:00")   # HH:MM
    time_slot_2    = Column(String(5), default="15:00")
    time_slot_3    = Column(String(5), default="21:00")

    # Flexible Shorts schedule
    start_time     = Column(String(5), default="09:00")   # HH:MM UTC
    end_time       = Column(String(5), default="23:00")   # HH:MM UTC

    # Daily Long-Form Video (Hindi 16:9) Schedule
    long_video_enabled = Column(Boolean,   default=True)
    long_video_time    = Column(String(5), default="13:00") # 1:00 PM UTC

    timezone       = Column(String(50), default="UTC")
    is_active      = Column(Boolean, default=True)

    created_at     = Column(DateTime(timezone=True), default=_utcnow)
    updated_at     = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user = relationship("User", back_populates="schedule")


# ─────────────────────────────────────────────────────────────
# Used Topics (per-user deduplication)
# ─────────────────────────────────────────────────────────────

class UsedTopic(Base):
    __tablename__ = "used_topics"

    id          = Column(String, primary_key=True, default=_new_uuid)
    user_id     = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_hash  = Column(String(64), nullable=False)
    topic       = Column(String(500), nullable=False)
    created_at  = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User", back_populates="used_topics")

    __table_args__ = (
        UniqueConstraint("user_id", "topic_hash", name="uq_user_topic"),
    )
