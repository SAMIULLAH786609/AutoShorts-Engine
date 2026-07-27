"""
AutoShorts SaaS Backend — Main FastAPI Application.

Startup:
  uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import FRONTEND_URL, IS_PRODUCTION
from backend.database import init_db

log = logging.getLogger("autoshorts.main")


# ── App lifecycle ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # ── STARTUP ──
    log.info("AutoShorts backend starting…")

    # Create all tables in Supabase PostgreSQL
    init_db()
    log.info("Database tables ready")

    # Run column migrations (safe: only adds missing columns, never drops)
    try:
        from backend.database import engine
        with engine.connect() as conn:
            migrations = [
                "ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS yt_views    INTEGER DEFAULT 0",
                "ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS yt_likes    INTEGER DEFAULT 0",
                "ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS yt_comments INTEGER DEFAULT 0",
                "ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS yt_stats_updated TIMESTAMP WITH TIME ZONE",
            ]
            for sql in migrations:
                conn.execute(__import__("sqlalchemy").text(sql))
            conn.commit()
        log.info("Column migrations applied successfully")
    except Exception as exc:
        log.warning("Column migration warning (safe to ignore if columns already exist): %s", exc)

    # Clean temporary directories on startup to prevent storage build-up
    try:
        import shutil
        from config import DOWNLOAD_DIR, OUTPUT_DIR, THUMBNAIL_DIR
        for folder in (DOWNLOAD_DIR, OUTPUT_DIR, THUMBNAIL_DIR):
            if folder.exists():
                for item in folder.iterdir():
                    try:
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                    except Exception:
                        pass
        log.info("Temporary directories cleaned up on startup")
    except Exception as exc:
        log.warning("Startup cleanup failed: %s", exc)

    # Start the background scheduler (runs jobs every minute)
    from backend.scheduler import start_scheduler
    start_scheduler()

    yield  # ← server runs here

    # ── SHUTDOWN ──
    from backend.scheduler import stop_scheduler
    stop_scheduler()
    log.info("AutoShorts backend stopped")


# ── FastAPI App ───────────────────────────────────────────────

app = FastAPI(
    title       = "AutoShorts Engine API",
    description = "Multi-user YouTube Shorts automation platform",
    version     = "2.0.0",
    lifespan    = lifespan,
    docs_url    = None if IS_PRODUCTION else "/docs",
    redoc_url   = None if IS_PRODUCTION else "/redoc",
)

# ── CORS ──────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins     = [FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ───────────────────────────────────────────────────

from backend.routers.auth     import router as auth_router
from backend.routers.jobs     import router as jobs_router
from backend.routers.channels import router as channels_router
from backend.routers.dashboard import dashboard_router, schedule_router

app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(channels_router)
app.include_router(dashboard_router)
app.include_router(schedule_router)


# ── Health check ──────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "autoshorts-backend"}


@app.get("/")
def root():
    return {
        "message": "AutoShorts Engine API",
        "docs":    "/docs",
        "health":  "/health",
    }


# ── Logging config ────────────────────────────────────────────

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
