import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

CHANNEL_NICHE = os.getenv("CHANNEL_NICHE", "student comedy").strip()
REGION_CODE = os.getenv("REGION_CODE", "PK").strip().upper()
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en").strip()
DAILY_VIDEO_COUNT = int(os.getenv("DAILY_VIDEO_COUNT", "3"))

VOICE_ENGLISH_FEMALE = os.getenv(
    "VOICE_ENGLISH_FEMALE",
    "en-US-AriaNeural",
)

VOICE_ENGLISH_MALE = os.getenv(
    "VOICE_ENGLISH_MALE",
    "en-US-GuyNeural",
)

VOICE_URDU_FEMALE = os.getenv(
    "VOICE_URDU_FEMALE",
    "ur-PK-UzmaNeural",
)

VOICE_URDU_MALE = os.getenv(
    "VOICE_URDU_MALE",
    "ur-PK-AsadNeural",
)

DOWNLOAD_DIR = BASE_DIR / "downloads"
OUTPUT_DIR = BASE_DIR / "output"
THUMBNAIL_DIR = BASE_DIR / "thumbnails"
METADATA_DIR = BASE_DIR / "metadata"
LOG_DIR = BASE_DIR / "logs"
CREDENTIALS_DIR = BASE_DIR / "credentials"

for folder in (
    DOWNLOAD_DIR,
    OUTPUT_DIR,
    THUMBNAIL_DIR,
    METADATA_DIR,
    LOG_DIR,
    CREDENTIALS_DIR,
):
    folder.mkdir(parents=True, exist_ok=True)