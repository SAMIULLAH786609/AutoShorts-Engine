"""
AutoShorts Engine — Single source-of-truth configuration.

All modules across the project import from here.
Every value is controlled via the .env file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

DOWNLOAD_DIR    = BASE_DIR / "downloads"
OUTPUT_DIR      = BASE_DIR / "output"
THUMBNAIL_DIR   = BASE_DIR / "thumbnails"
METADATA_DIR    = BASE_DIR / "metadata"
LOG_DIR         = BASE_DIR / "logs"
CREDENTIALS_DIR = BASE_DIR / "credentials"
DATA_DIR        = BASE_DIR / "data"
MUSIC_DIR       = BASE_DIR / "music"
CACHE_DIR       = BASE_DIR / "cache"

for _folder in (
    DOWNLOAD_DIR, OUTPUT_DIR, THUMBNAIL_DIR, METADATA_DIR,
    LOG_DIR, CREDENTIALS_DIR, DATA_DIR, MUSIC_DIR, CACHE_DIR,
):
    _folder.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY",  "").strip()
PEXELS_API_KEY  = os.getenv("PEXELS_API_KEY",  "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
NEWS_API_KEY    = os.getenv("NEWS_API_KEY",    "").strip()

# ---------------------------------------------------------------------------
# Gemini model
# ---------------------------------------------------------------------------

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip()

# ---------------------------------------------------------------------------
# Channel / content settings
# ---------------------------------------------------------------------------

CHANNEL_NICHE    = os.getenv("CHANNEL_NICHE",    "Interesting facts and viral stories").strip()
REGION_CODE      = os.getenv("REGION_CODE",      "US").strip().upper()
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "English").strip()
DEFAULT_GENDER   = os.getenv("DEFAULT_GENDER",   "female").strip().lower()
DEFAULT_PRIVACY  = os.getenv("DEFAULT_PRIVACY",  "private").strip().lower()

DAILY_VIDEO_COUNT = int(os.getenv("DAILY_VIDEO_COUNT", "2"))

# ---------------------------------------------------------------------------
# Scheduler upload times (24-hour HH:MM)
# ---------------------------------------------------------------------------

UPLOAD_TIME_1 = os.getenv("UPLOAD_TIME_1", "10:00").strip()
UPLOAD_TIME_2 = os.getenv("UPLOAD_TIME_2", "18:00").strip()

# ---------------------------------------------------------------------------
# Trend discovery settings
# ---------------------------------------------------------------------------

TREND_REGIONS = [
    r.strip().upper()
    for r in os.getenv("TREND_REGIONS", "US,GB,CA,AU,IN,PK,DE,FR,BR,JP").split(",")
    if r.strip()
]

TREND_VIDEOS_PER_REGION = int(os.getenv("TREND_VIDEOS_PER_REGION", "10"))

# ---------------------------------------------------------------------------
# Voice settings (Edge-TTS voice IDs)
# ---------------------------------------------------------------------------

VOICE_ENGLISH_FEMALE = os.getenv("VOICE_ENGLISH_FEMALE", "en-US-AriaNeural")
VOICE_ENGLISH_MALE   = os.getenv("VOICE_ENGLISH_MALE",   "en-US-GuyNeural")
VOICE_URDU_FEMALE    = os.getenv("VOICE_URDU_FEMALE",     "ur-PK-UzmaNeural")
VOICE_URDU_MALE      = os.getenv("VOICE_URDU_MALE",       "ur-PK-AsadNeural")

# ---------------------------------------------------------------------------
# Video renderer settings
# ---------------------------------------------------------------------------

VIDEO_WIDTH  = int(os.getenv("VIDEO_WIDTH",  "1080"))
VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "1920"))
VIDEO_FPS    = int(os.getenv("VIDEO_FPS",    "30"))

# Windows default bold font — update if running on Linux/Mac
FONT_PATH = os.getenv("FONT_PATH", r"C:\Windows\Fonts\arialbd.ttf")

# ---------------------------------------------------------------------------
# Retry / resilience
# ---------------------------------------------------------------------------

MAX_PIPELINE_RETRIES = int(os.getenv("MAX_PIPELINE_RETRIES", "3"))
API_TIMEOUT_SECONDS  = int(os.getenv("API_TIMEOUT_SECONDS",  "45"))