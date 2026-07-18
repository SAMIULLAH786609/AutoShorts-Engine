"""
AutoShorts Engine — History Database (SQLite).

Stores:
  - topics     : every topic ever selected (deduplication key)
  - videos     : every video ever rendered and uploaded
  - failures   : every pipeline failure (for monitoring)

All timestamps are stored in UTC ISO-8601.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR
from autoshorts.services.logging_setup import get_logger

log = get_logger("history_db")

DATABASE_PATH = DATA_DIR / "autoshorts.db"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrency
    return conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def initialize_database() -> None:
    """Create all tables if they do not already exist, then migrate."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS topics (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_hash   TEXT    NOT NULL UNIQUE,
                topic        TEXT    NOT NULL,
                style        TEXT,
                source_type  TEXT,
                source_urls  TEXT,
                score        REAL    DEFAULT 0,
                status       TEXT    NOT NULL DEFAULT 'selected',
                created_at   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS videos (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_hash       TEXT    NOT NULL,
                title            TEXT,
                description      TEXT,
                keywords         TEXT,
                hashtags         TEXT,
                local_path       TEXT,
                thumbnail_path   TEXT,
                youtube_video_id TEXT,
                platform         TEXT    DEFAULT 'youtube',
                upload_status    TEXT    DEFAULT 'pending',
                duration         REAL    DEFAULT 0,
                script_hash      TEXT,
                trend_source     TEXT,
                created_at       TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS failures (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                stage      TEXT    NOT NULL,
                message    TEXT    NOT NULL,
                details    TEXT,
                created_at TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_topics_hash
                ON topics (topic_hash);

            CREATE INDEX IF NOT EXISTS idx_videos_topic_hash
                ON videos (topic_hash);

            CREATE INDEX IF NOT EXISTS idx_videos_created_at
                ON videos (created_at);
            """
        )
    log.debug("Database initialised at %s", DATABASE_PATH)
    _migrate_database()


def _migrate_database() -> None:
    """
    Apply schema migrations for databases created before an upgrade.
    Uses ALTER TABLE ADD COLUMN which is a no-op if the column already exists
    (handled via try/except since SQLite has no IF NOT EXISTS for columns).
    """
    migrations: list[tuple[str, str]] = [
        # failures table — added 'topic' column in v2 upgrade
        ("failures", "ALTER TABLE failures ADD COLUMN topic TEXT"),
        # videos table — added many columns in v2 upgrade
        ("videos",   "ALTER TABLE videos ADD COLUMN title TEXT"),
        ("videos",   "ALTER TABLE videos ADD COLUMN description TEXT"),
        ("videos",   "ALTER TABLE videos ADD COLUMN keywords TEXT"),
        ("videos",   "ALTER TABLE videos ADD COLUMN hashtags TEXT"),
        ("videos",   "ALTER TABLE videos ADD COLUMN thumbnail_path TEXT"),
        ("videos",   "ALTER TABLE videos ADD COLUMN duration REAL DEFAULT 0"),
        ("videos",   "ALTER TABLE videos ADD COLUMN script_hash TEXT"),
        ("videos",   "ALTER TABLE videos ADD COLUMN trend_source TEXT"),
        # topics table — added 'style' column in v2 upgrade
        ("topics",   "ALTER TABLE topics ADD COLUMN style TEXT"),
    ]

    with get_connection() as conn:
        for table, sql in migrations:
            try:
                conn.execute(sql)
                log.debug("Migration applied: %s", sql)
            except Exception:
                # Column already exists — safe to ignore
                pass

    log.debug("Schema migration complete")


# ---------------------------------------------------------------------------
# Topic helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_topic(topic: str) -> str:
    return " ".join(topic.lower().strip().split())


def topic_hash(topic: str) -> str:
    return hashlib.sha256(normalize_topic(topic).encode("utf-8")).hexdigest()


def script_hash(script: str) -> str:
    return hashlib.sha256(script.strip().encode("utf-8")).hexdigest()


def topic_exists(topic: str) -> bool:
    """Return True if this topic (or a near-duplicate) has been used before."""
    h = topic_hash(topic)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM topics WHERE topic_hash = ?",
            (h,),
        ).fetchone()
    return row is not None


def save_topic(
    topic: str,
    style: str = "",
    source_type: str = "",
    source_urls: str = "",
    score: float = 0.0,
) -> str:
    """
    Persist a topic to the database.
    Returns the topic hash.
    """
    h = topic_hash(topic)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO topics
              (topic_hash, topic, style, source_type, source_urls, score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (h, topic, style, source_type, source_urls, score, _now_utc()),
        )
    return h


def get_recent_topics(n: int = 50) -> list[str]:
    """Return the N most recently used topic strings."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT topic FROM topics ORDER BY created_at DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [row["topic"] for row in rows]


# ---------------------------------------------------------------------------
# Video helpers
# ---------------------------------------------------------------------------

def mark_video_uploaded(
    topic_hash_value: str,
    title: str,
    description: str,
    keywords: list[str],
    hashtags: list[str],
    local_path: str,
    thumbnail_path: str,
    youtube_video_id: str,
    platform: str = "youtube",
    duration: float = 0.0,
    script_hash_value: str = "",
    trend_source: str = "",
) -> None:
    """Record a successfully uploaded video in the database."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO videos
              (topic_hash, title, description, keywords, hashtags,
               local_path, thumbnail_path, youtube_video_id, platform,
               upload_status, duration, script_hash, trend_source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, ?, ?, ?)
            """,
            (
                topic_hash_value,
                title,
                description,
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(hashtags, ensure_ascii=False),
                local_path,
                thumbnail_path,
                youtube_video_id,
                platform,
                duration,
                script_hash_value,
                trend_source,
                _now_utc(),
            ),
        )
    log.info("Video record saved: youtube_id=%s", youtube_video_id)


# ---------------------------------------------------------------------------
# Failure logging
# ---------------------------------------------------------------------------

def record_failure(
    stage: str,
    message: str,
    topic: str = "",
    details: str = "",
) -> None:
    """Log a pipeline failure to the database."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO failures (stage, topic, message, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (stage, topic, message, details, _now_utc()),
        )
    log.debug("Failure recorded: stage=%s topic=%s", stage, topic)