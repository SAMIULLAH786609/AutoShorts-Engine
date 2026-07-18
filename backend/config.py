"""
AutoShorts Backend — Central Configuration.
All values loaded from backend/.env
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load backend-specific .env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ── Database ──────────────────────────────────────────────────
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/autoshorts",
)

# ── Security ──────────────────────────────────────────────────
SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080")  # 7 days
)

# ── Encryption key for OAuth tokens ──────────────────────────
FERNET_KEY: str = os.getenv("FERNET_KEY", "")

# ── Email ─────────────────────────────────────────────────────
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL: str = os.getenv("FROM_EMAIL", "noreply@autoshorts.app")

# ── Cloudinary ────────────────────────────────────────────────
CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY: str     = os.getenv("CLOUDINARY_API_KEY",    "")
CLOUDINARY_API_SECRET: str  = os.getenv("CLOUDINARY_API_SECRET", "")

# ── Google OAuth ──────────────────────────────────────────────
GOOGLE_CLIENT_ID: str     = os.getenv("GOOGLE_CLIENT_ID",     "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI: str  = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8000/api/channels/oauth-callback",
)

# ── Pipeline keys (shared) ────────────────────────────────────
GEMINI_API_KEY:  str = os.getenv("GEMINI_API_KEY",  "")
PEXELS_API_KEY:  str = os.getenv("PEXELS_API_KEY",  "")
YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")

# ── App URLs ──────────────────────────────────────────────────
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL:  str = os.getenv("BACKEND_URL",  "http://localhost:8000")

# ── Environment ───────────────────────────────────────────────
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION: bool = ENVIRONMENT == "production"
