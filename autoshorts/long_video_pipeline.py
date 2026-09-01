"""
AutoShorts Engine — Long-form Hindi Video Pipeline.

Daily ek 6-8 minute Hindi video banata hai worldwide trends se.
Shorts ke saath alag schedule pe run hota hai.
"""

from __future__ import annotations

import random
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

from config import (
    API_TIMEOUT_SECONDS,
    DEFAULT_PRIVACY,
    DOWNLOAD_DIR,
    OUTPUT_DIR,
    PEXELS_API_KEY,
    PIXABAY_API_KEY,
    REGION_CODE,
    THUMBNAIL_DIR,
)
from autoshorts.models import VideoResult
from autoshorts.services.gemini_service import (
    generate_long_hindi_video_plan,
    generate_long_video_topics,
    research_topic,
)
from autoshorts.services.history_db import (
    get_recent_topics,
    initialize_database,
    mark_video_uploaded,
    record_failure,
    save_topic,
    script_hash,
    topic_exists,
    topic_hash,
)
from autoshorts.services.logging_setup import get_logger, log_step
from autoshorts.services.renderer import render_long_video
from autoshorts.services.thumbnail_generator import generate_thumbnail
from autoshorts.services.trend_sources import collect_worldwide_trends
from autoshorts.services.voice_service import generate_voice
from autoshorts.services.youtube_upload import upload_video

log = get_logger("long_video_pipeline")

LONG_VIDEO_CLIPS_NEEDED = 4
PEXELS_SEARCH_URL  = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"


def _collect_landscape_clips(keywords: list[str], job_id: str, count: int = 4) -> list[Path]:
    """Collect landscape (16:9) stock video clips from Pexels/Pixabay."""
    clips: list[Path] = []
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Repeat keywords if fewer than needed
    expanded = (keywords * 3)[:count * 2]

    for keyword in expanded:
        if len(clips) >= count:
            break

        # Try Pexels first
        if PEXELS_API_KEY:
            try:
                page = random.randint(1, 5)
                resp = requests.get(
                    PEXELS_SEARCH_URL,
                    headers={"Authorization": PEXELS_API_KEY},
                    params={
                        "query": keyword, "per_page": 5,
                        "page": page, "orientation": "landscape",
                    },
                    timeout=API_TIMEOUT_SECONDS,
                )
                if resp.status_code == 200:
                    for vid in resp.json().get("videos", []):
                        files = vid.get("video_files", [])
                        land = [
                            f for f in files
                            if f.get("file_type") == "video/mp4"
                            and (f.get("width") or 0) > (f.get("height") or 0)
                        ]
                        land.sort(key=lambda f: abs((f.get("height") or 720) - 1080))
                        if land:
                            url  = land[0]["link"]
                            dest = job_dir / f"{uuid.uuid4().hex[:8]}.mp4"
                            dl   = requests.get(url, timeout=60, stream=True)
                            if dl.status_code == 200:
                                with open(dest, "wb") as fh:
                                    for chunk in dl.iter_content(1024 * 256):
                                        fh.write(chunk)
                                if dest.stat().st_size > 50_000:
                                    clips.append(dest)
                                    log.info("Landscape clip: %s", dest.name)
                                    break
            except Exception as exc:
                log.warning("Pexels landscape failed for '%s': %s", keyword, exc)

        # Pixabay fallback
        if len(clips) < count and PIXABAY_API_KEY:
            try:
                resp = requests.get(
                    PIXABAY_SEARCH_URL,
                    params={
                        "key": PIXABAY_API_KEY, "q": keyword,
                        "video_type": "film", "per_page": 5,
                        "orientation": "horizontal",
                    },
                    timeout=API_TIMEOUT_SECONDS,
                )
                if resp.status_code == 200:
                    for hit in resp.json().get("hits", []):
                        videos = hit.get("videos", {})
                        src = (
                            videos.get("large") or videos.get("medium") or {}
                        ).get("url", "")
                        if src:
                            dest = job_dir / f"{uuid.uuid4().hex[:8]}.mp4"
                            dl   = requests.get(src, timeout=60, stream=True)
                            if dl.status_code == 200:
                                with open(dest, "wb") as fh:
                                    for chunk in dl.iter_content(1024 * 256):
                                        fh.write(chunk)
                                if dest.stat().st_size > 50_000:
                                    clips.append(dest)
                                    break
            except Exception as exc:
                log.warning("Pixabay landscape failed for '%s': %s", keyword, exc)

        time.sleep(0.3)

    log.info("Collected %d / %d landscape clips", len(clips), count)
    return clips


def run_long_video_pipeline(privacy: str | None = None) -> VideoResult | None:
    """
    Run the complete long-form Hindi video pipeline.

    Returns VideoResult on success, None if skipped or failed.
    privacy: 'public' | 'unlisted' | 'private' (default from .env)
    """
    initialize_database()
    privacy = privacy or DEFAULT_PRIVACY

    log_step(log, "LONG VIDEO PIPELINE", "Starting Hindi long-form video pipeline")

    job_id    = f"long_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    job_dir   = DOWNLOAD_DIR / job_id
    topic     = ""
    video_path: Path | None = None

    try:
        # Step 1: Trends
        log_step(log, "STEP 1", "Collecting worldwide trends")
        trends = collect_worldwide_trends(region=REGION_CODE)
        if not trends:
            log.warning("No trends — skipping long video today")
            return None

        # Step 2: Topic ideas (Hindi, broad niche)
        log_step(log, "STEP 2", "Generating Hindi topic ideas")
        used  = get_recent_topics(days=60, limit=50)
        ideas = generate_long_video_topics(trends, count=3, used_topics=used)
        if not ideas:
            log.warning("No Hindi long video ideas generated")
            return None

        # Step 3: Pick unused topic
        log_step(log, "STEP 3", "Selecting fresh topic")
        chosen = next((i for i in ideas if not topic_exists(i.topic)), ideas[0])
        topic  = chosen.topic
        style  = chosen.style
        log.info("Topic: %s", topic)

        # Step 4: Research
        log_step(log, "STEP 4", "Researching topic")
        try:
            research = research_topic(topic)
        except Exception as exc:
            log.warning("Research failed (%s) — proceeding without", exc)
            research = ""

        # Step 5: Hindi video plan
        log_step(log, "STEP 5", "Generating Hindi video plan")
        plan = generate_long_hindi_video_plan(topic, style=style, research_summary=research)
        log.info("Script: %d words | Voice: %s", len(plan.script.split()), plan.voice)

        # Step 6: Hindi narration
        log_step(log, "STEP 6", "Generating Hindi narration (Edge-TTS)")
        job_dir.mkdir(parents=True, exist_ok=True)
        audio_path = job_dir / "narration.mp3"
        generate_voice(plan.script, str(audio_path), voice=plan.voice)

        # Step 7: Landscape clips
        log_step(log, "STEP 7", "Collecting landscape stock clips")
        clips = _collect_landscape_clips(plan.keywords, job_id, count=LONG_VIDEO_CLIPS_NEEDED)
        if not clips:
            raise RuntimeError("No landscape clips downloaded — cannot render")

        # Step 8: Render 16:9 1080p
        log_step(log, "STEP 8", "Rendering 16:9 1080p long video")
        video_path = OUTPUT_DIR / f"{job_id}.mp4"
        render_long_video(
            script=plan.script,
            audio_path=audio_path,
            video_paths=clips,
            output_path=video_path,
        )

        # Step 9: Thumbnail
        log_step(log, "STEP 9", "Generating thumbnail")
        thumb_path = THUMBNAIL_DIR / f"{job_id}_thumb.jpg"
        try:
            generate_thumbnail(
                title=plan.title,
                thumbnail_text=plan.thumbnail_text,
                output_path=thumb_path,
                style=plan.style,
            )
        except Exception as exc:
            log.warning("Thumbnail failed: %s", exc)
            thumb_path = None

        # Step 10: Upload (NO #Shorts)
        log_step(log, "STEP 10", f"Uploading to YouTube ({privacy})")
        guaranteed = ["hindi", "viral", "trending", "explore", "knowledge"]
        plan_tags  = [t.lstrip("#").strip() for t in plan.hashtags if t.strip()]
        long_tags  = list(dict.fromkeys(guaranteed + plan_tags))[:20]

        description = plan.description + "\n\n" + " ".join(f"#{t}" for t in long_tags)

        youtube_video_id = upload_video(
            video_path=str(video_path),
            title=plan.title,
            description=description,
            hashtags=long_tags,
            privacy_status=privacy,
        )
        log.info("Uploaded: https://youtu.be/%s", youtube_video_id)

        # Step 11: Save to DB
        log_step(log, "STEP 11", "Saving to DB")
        th = save_topic(
            topic=topic, style=style,
            source_type="long-video", source_urls="", score=chosen.score,
        )
        mark_video_uploaded(
            topic_hash_value=th, title=plan.title, description=plan.description,
            keywords=plan.keywords, hashtags=long_tags, local_path=str(video_path),
            thumbnail_path=str(thumb_path) if thumb_path else "",
            youtube_video_id=youtube_video_id, platform="youtube-long",
            duration=0.0, script_hash_value=script_hash(plan.script),
            trend_source="worldwide",
        )

        # Step 12: Cleanup
        log_step(log, "STEP 12", "Cleaning up temp files")
        try:
            shutil.rmtree(job_dir, ignore_errors=True)
            if video_path and video_path.exists():
                video_path.unlink(missing_ok=True)
        except Exception:
            pass

        log_step(log, "LONG VIDEO COMPLETE", f"https://youtu.be/{youtube_video_id}")
        return VideoResult(
            topic=topic, topic_hash=topic_hash(topic), video_path=str(video_path),
            title=plan.title, description=plan.description, hashtags=long_tags,
            thumbnail_path=str(thumb_path) if thumb_path else "",
            youtube_video_id=youtube_video_id, upload_status="uploaded",
            trend_source="worldwide-hindi", script_hash=script_hash(plan.script),
            duration=0.0,
        )

    except Exception as exc:
        log.exception("Long video pipeline failed: %s", exc)
        record_failure(stage="long_video_pipeline", message=str(exc), topic=topic)
        return None
