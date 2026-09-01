"""
AutoShorts Backend — Multi-User Pipeline Runner.

Adapts the existing single-user pipeline to run per user with:
  - User-scoped topic deduplication
  - User's YouTube OAuth credentials
  - User's content preferences (niche, language, gender, privacy)
  - Cloudinary upload for persistent video storage
"""

from __future__ import annotations

import gc
import hashlib
import sys
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.models import User, UserSchedule, UsedTopic, VideoJob, YouTubeChannel

# Ensure project root is on path so we can import from autoshorts/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _topic_hash(topic: str) -> str:
    normalized = " ".join(topic.lower().strip().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _get_used_topics(user_id: str, db: Session, limit: int = 50) -> list[str]:
    rows = (
        db.query(UsedTopic)
        .filter(UsedTopic.user_id == user_id)
        .order_by(UsedTopic.created_at.desc())
        .limit(limit)
        .all()
    )
    return [row.topic for row in rows]


def _save_used_topic(user_id: str, topic: str, db: Session) -> None:
    th = _topic_hash(topic)
    existing = (
        db.query(UsedTopic)
        .filter(UsedTopic.user_id == user_id, UsedTopic.topic_hash == th)
        .first()
    )
    if not existing:
        db.add(UsedTopic(user_id=user_id, topic_hash=th, topic=topic))
        db.commit()


def _topic_exists_for_user(user_id: str, topic: str, db: Session) -> bool:
    th = _topic_hash(topic)
    return (
        db.query(UsedTopic)
        .filter(UsedTopic.user_id == user_id, UsedTopic.topic_hash == th)
        .first()
    ) is not None


def _upload_to_cloudinary(file_path: Path, resource_type: str = "video") -> str:
    """Upload a file to Cloudinary and return the public URL."""
    from backend.config import (
        CLOUDINARY_API_KEY,
        CLOUDINARY_API_SECRET,
        CLOUDINARY_CLOUD_NAME,
    )

    if not CLOUDINARY_CLOUD_NAME:
        # No Cloudinary configured — return local path as fallback
        return str(file_path)

    import cloudinary
    import cloudinary.uploader

    cloudinary.config(
        cloud_name = CLOUDINARY_CLOUD_NAME,
        api_key    = CLOUDINARY_API_KEY,
        api_secret = CLOUDINARY_API_SECRET,
        secure     = True,
    )

    result = cloudinary.uploader.upload(
        str(file_path),
        resource_type = resource_type,
        folder        = "autoshorts",
    )
    return result.get("secure_url", str(file_path))


def run_pipeline_for_user(
    user:    User,
    channel: YouTubeChannel,
    db:      Session,
    job_id:  str | None = None,
) -> dict[str, Any]:
    """
    Run the complete video generation pipeline for one user.

    Returns a dict with all result metadata.
    Raises on unrecoverable failure.
    """
    # ── Import pipeline services ─────────────────────────────
    from autoshorts.services.trend_sources   import collect_worldwide_trends
    from autoshorts.services.gemini_service  import generate_topic_ideas, generate_video_plan, research_topic
    from autoshorts.services.voice_service   import generate_voice
    from autoshorts.services.video_collector import collect_scene_videos
    from autoshorts.services.renderer        import render_short
    from autoshorts.services.thumbnail_generator import generate_thumbnail

    def check_cancelled():
        if not job_id:
            return
        # Bug 7 fixed: Use a fresh session instead of db.expire_all().
        # expire_all() invalidates ALL objects in the main session (user, channel, etc.)
        # which can trigger DetachedInstanceError on next access in the pipeline.
        from backend.database import SessionLocal as _SL
        _tmp = _SL()
        try:
            from backend.models import VideoJob as _VJ
            j = _tmp.query(_VJ).filter(_VJ.id == job_id).first()
            if j and j.status == "failed" and "Cancelled" in (j.error_message or ""):
                raise RuntimeError("Cancelled by user")
        finally:
            _tmp.close()

    # ── Override pipeline config with user preferences ───────
    os.environ["CHANNEL_NICHE"]    = user.channel_niche or "Interesting facts and viral stories"
    os.environ["DEFAULT_LANGUAGE"] = user.default_language or "English"
    os.environ["DEFAULT_GENDER"]   = user.default_gender or "female"

    # Use user-specific temp directory to avoid conflicts between users
    user_dir    = PROJECT_ROOT / "downloads" / user.id
    output_dir  = PROJECT_ROOT / "output"    / user.id
    thumb_dir   = PROJECT_ROOT / "thumbnails"/ user.id
    user_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = None
    thumb_path = None
    duration = 0.0

    try:
        # ── Step 1: Collect trends ────────────────────────────────
        check_cancelled()
        trends = collect_worldwide_trends()
        if not trends:
            raise RuntimeError("No trend data available from any source")

        # ── Step 2: Select a fresh topic ─────────────────────────
        check_cancelled()
        used = _get_used_topics(user.id, db)

        ideas = generate_topic_ideas(
            trend_items = trends,
            count       = 10,
            niche       = user.channel_niche or "Interesting facts and viral stories",
            used_topics = used,
        )
        if not ideas:
            raise RuntimeError("Gemini returned no topic ideas")

        ideas.sort(key=lambda x: x.score, reverse=True)

        selected = None
        for idea in ideas:
            if not _topic_exists_for_user(user.id, idea.topic, db):
                selected = idea
                break

        if not selected:
            raise RuntimeError("All generated topics already used — try again later")

        topic = selected.topic
        style = selected.style

        # ── Step 3: Research ──────────────────────────────────────
        check_cancelled()
        research = research_topic(topic)

        # ── Step 4: Generate video plan ───────────────────────────
        check_cancelled()
        plan = generate_video_plan(topic=topic, style=style, research_summary=research)

        # ── Step 5: Generate voice ────────────────────────────────
        check_cancelled()
        import re
        safe_name  = re.sub(r'[^a-zA-Z0-9_\-]', '_', plan.title)[:40] or "short_video"
        audio_path = user_dir / f"{safe_name}_voice.mp3"

        generate_voice(
            text        = plan.script,
            output_path = audio_path,
            voice       = plan.voice,
            language    = user.default_language or "English",
            gender      = user.default_gender   or "female",
            style       = plan.style,
        )

        # ── Step 6: Collect videos ────────────────────────────────
        check_cancelled()
        # Limit to a maximum of 3 keywords to prevent high RAM usage in MoviePy
        limited_keywords = plan.keywords[:3] if plan.keywords else []
        video_paths = collect_scene_videos(limited_keywords, output_dir=user_dir)

        # ── Step 7: Render ────────────────────────────────────────
        check_cancelled()
        video_path = output_dir / f"{safe_name}_{timestamp}.mp4"
        render_short(
            script      = plan.script,
            audio_path  = audio_path,
            video_paths = video_paths,
            output_path = video_path,
        )

        # ── Step 8: Thumbnail ─────────────────────────────────────
        check_cancelled()
        thumb_path = thumb_dir / f"{safe_name}.jpg"
        try:
            from autoshorts.services.thumbnail_generator import generate_thumbnail
            generate_thumbnail(
                title           = plan.title,
                thumbnail_text  = plan.thumbnail_text,
                output_path     = thumb_path,
            )
        except Exception:
            thumb_path = None

        # ── Step 9: Upload to Cloudinary ──────────────────────────
        check_cancelled()
        video_url = ""
        thumb_url = ""

        try:
            video_url = _upload_to_cloudinary(video_path, resource_type="video")
        except Exception as exc:
            video_url = str(video_path)  # fallback to local

        try:
            if thumb_path and thumb_path.exists():
                thumb_url = _upload_to_cloudinary(thumb_path, resource_type="image")
        except Exception:
            thumb_url = str(thumb_path) if thumb_path else ""

        # ── Step 10: Upload to YouTube ────────────────────────────
        youtube_video_id = _upload_to_youtube(
            plan     = plan,
            video_path = video_path,
            channel  = channel,
            privacy  = user.default_privacy or "private",
            db       = db,
        )

        # ── Step 11: Save used topic ──────────────────────────────
        _save_used_topic(user.id, topic, db)

        # ── Duration ──────────────────────────────────────────────
        try:
            import subprocess as _sp, json as _json
            r = _sp.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(video_path)],
                capture_output=True, text=True, timeout=15
            )
            for s in _json.loads(r.stdout).get("streams", []):
                if s.get("duration"):
                    duration = float(s["duration"]); break
        except Exception:
            pass

        # ── Step 12: Complete disk cleanup (delete all data after upload) ──
        # All video, audio, stock clips, and thumbnails are deleted from disk
        import shutil as _shutil_s
        for p in (video_path, thumb_path, audio_path):
            try:
                if p and Path(p).exists():
                    Path(p).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            _shutil_s.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            _shutil_s.rmtree(thumb_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            _shutil_s.rmtree(user_dir, ignore_errors=True)
        except Exception:
            pass

        log.info("Cleaned all temporary video/audio data from disk for job %s", job_id or "manual")
        gc.collect()

        return {
            "topic":            topic,
            "title":            plan.title,
            "style":            style,
            "video_url":        video_url,
            "thumbnail_url":    thumb_url,
            "youtube_video_id": youtube_video_id,
            "duration":         duration,
        }

    finally:
        import shutil as _shutil
        try:
            _shutil.rmtree(user_dir, ignore_errors=True)
        except Exception:
            pass
        gc.collect()


def _upload_to_youtube(
    plan,
    video_path: Path,
    channel:    YouTubeChannel,
    privacy:    str,
    db:         Session,
) -> str:
    """Upload the rendered video to the user's YouTube channel."""
    from backend.auth_service import decrypt_token
    from backend.routers.channels import refresh_channel_tokens
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from backend.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

    # Refresh tokens if possible to ensure token validity
    access_token = ""
    try:
        access_token = refresh_channel_tokens(channel, db)
    except Exception:
        access_token = decrypt_token(channel.access_token_enc or "")

    refresh_token = decrypt_token(channel.refresh_token_enc or "")

    if not access_token and not refresh_token:
        raise RuntimeError("YouTube channel has no valid tokens. User must reconnect.")

    credentials = Credentials(
        token         = access_token,
        refresh_token = refresh_token,
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = GOOGLE_CLIENT_ID,
        client_secret = GOOGLE_CLIENT_SECRET,
        scopes        = ["https://www.googleapis.com/auth/youtube.upload"],
    )

    youtube = build("youtube", "v3", credentials=credentials)

    description = plan.description
    hashtag_str = " ".join(f"#{t}" for t in plan.hashtags)

    # #Shorts + viral tags MUST appear in description — YouTube only shows video
    # in the Shorts feed if #Shorts is present. fyp/viral/trending boost impressions.
    shorts_core = "#Shorts #Short #YouTubeShorts #fyp #viral #trending"
    if hashtag_str:
        description += f"\n\n{shorts_core} {hashtag_str}"
    else:
        description += f"\n\n{shorts_core}"

    # Build tags list — guaranteed viral + niche tags for maximum search discovery
    guaranteed_tags = ["Shorts", "Short", "YouTubeShorts", "fyp", "viral", "trending", "explore"]
    plan_tags = [t.strip().lstrip("#") for t in plan.hashtags if t.strip()]
    all_tags  = list(dict.fromkeys(guaranteed_tags + plan_tags))[:30]  # dedupe + cap

    request_body = {
        "snippet": {
            "title":           plan.title[:100],
            "description":     description[:5000],
            "tags":            all_tags,
            "categoryId":      "27",   # 27 = Education (correct for facts/money content)
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":             privacy,
            "selfDeclaredMadeForKids":   False,   # Required for Shorts monetization
            "madeForKids":               False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=5 * 1024 * 1024,  # 5MB chunks
        resumable=True,
    )
    request = youtube.videos().insert(
        part       = "snippet,status",
        body       = request_body,
        media_body = media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()

    return response["id"]

