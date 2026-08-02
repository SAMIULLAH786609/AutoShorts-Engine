"""
AutoShorts Engine — Fully Automated Pipeline.

run_pipeline() is the single function that drives the entire workflow:

  1. Collect worldwide trends
  2. Generate original topic ideas (Gemini)
  3. Deduplicate against history DB
  4. Select the best fresh topic
  5. Research the topic (Gemini)
  6. Generate full video plan (Gemini)
  7. Generate AI narration (Edge-TTS)
  8. Collect copyright-safe background videos (Pexels / Pixabay)
  9. Render final Short (MoviePy — subtitles, transitions, music)
 10. Generate thumbnail (Pillow)
 11. Upload to YouTube (private by default)
 12. Save all metadata to SQLite database
 13. Clean up temporary downloads

All failures are caught, logged, and retried where appropriate.
"""

from __future__ import annotations

import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from config import (
    CHANNEL_NICHE,
    DAILY_VIDEO_COUNT,
    DEFAULT_GENDER,
    DEFAULT_LANGUAGE,
    DEFAULT_PRIVACY,
    DOWNLOAD_DIR,
    MAX_PIPELINE_RETRIES,
    METADATA_DIR,
    OUTPUT_DIR,
    REGION_CODE,
)
from autoshorts.models import VideoPlan, VideoResult
from autoshorts.services.gemini_service import (
    generate_topic_ideas,
    generate_video_plan,
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
from autoshorts.services.renderer import render_short
from autoshorts.services.thumbnail_generator import generate_thumbnail
from autoshorts.services.trend_sources import collect_worldwide_trends
from autoshorts.services.video_collector import collect_scene_videos
from autoshorts.services.voice_service import generate_voice
from autoshorts.services.youtube_upload import upload_video

log = get_logger("pipeline")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class PipelineError(RuntimeError):
    """Raised when a pipeline step fails unrecoverably after all retries."""


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\s]', "_", text)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:60] or "autoshort"


def _clean_downloads() -> None:
    """Remove all temporary files from the downloads folder."""
    for item in DOWNLOAD_DIR.iterdir():
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception:
            pass


def _retry(fn, label: str, attempts: int = MAX_PIPELINE_RETRIES, delay: float = 5.0):
    """Call fn up to `attempts` times, sleeping `delay` seconds between tries."""
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            log.warning(
                "%s failed (attempt %d/%d): %s",
                label, attempt, attempts, exc,
            )
            if attempt < attempts:
                time.sleep(delay)

    raise PipelineError(f"{label} failed after {attempts} attempts") from last_exc


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------

def _step_collect_trends() -> list[dict]:
    log_step(log, "TREND DISCOVERY", "Collecting worldwide trends…")
    trends = collect_worldwide_trends()

    if not trends:
        raise PipelineError("No trend data collected from any source.")

    log.info("Total trend signals: %d", len(trends))
    return trends


def _step_select_topic(trends: list[dict]) -> dict:
    """
    Generate topic ideas and return the first one not already in history.
    Falls back through the list — never fails on a duplicate alone.
    """
    log_step(log, "TOPIC SELECTION", "Generating and scoring original ideas…")

    used_topics = get_recent_topics(50)

    ideas = _retry(
        lambda: generate_topic_ideas(
            trend_items=trends,
            count=10,
            niche=CHANNEL_NICHE,
            used_topics=used_topics,
        ),
        label="Topic idea generation",
    )

    if not ideas:
        raise PipelineError("Gemini returned no topic ideas.")

    # Sort by score descending
    ideas.sort(key=lambda x: x.score, reverse=True)

    for idea in ideas:
        if not topic_exists(idea.topic):
            log.info("Selected topic: '%s' (score=%.0f)", idea.topic, idea.score)
            log.info("Trend reason: %s", idea.trend_reason)
            log.info("Original angle: %s", idea.original_angle)
            return {
                "topic": idea.topic,
                "style": idea.style,
                "trend_reason": idea.trend_reason,
                "original_angle": idea.original_angle,
                "score": idea.score,
            }

    # All AI ideas were duplicates — extend the list
    log.warning(
        "All %d ideas were already used. Requesting fresh batch…", len(ideas)
    )
    more_ideas = generate_topic_ideas(
        trend_items=trends,
        count=5,
        niche=CHANNEL_NICHE,
        used_topics=used_topics,
    )
    for idea in more_ideas:
        if not topic_exists(idea.topic):
            return {
                "topic": idea.topic,
                "style": idea.style,
                "trend_reason": idea.trend_reason,
                "original_angle": idea.original_angle,
                "score": idea.score,
            }

    raise PipelineError("Could not find a fresh topic after extended search.")


def _step_research(topic: str) -> str:
    log_step(log, "RESEARCH", f"Researching: {topic}")
    return _retry(
        lambda: research_topic(topic),
        label="Topic research",
    )


def _step_generate_plan(topic: str, style: str, research: str) -> VideoPlan:
    log_step(log, "SCRIPT GENERATION", "Writing original script…")
    return _retry(
        lambda: generate_video_plan(topic=topic, style=style, research_summary=research),
        label="Video plan generation",
    )


def _step_generate_voice(plan: VideoPlan, audio_path: Path) -> Path:
    log_step(log, "VOICE GENERATION", f"Voice: {plan.voice}")
    return _retry(
        lambda: generate_voice(
            text=plan.script,
            output_path=audio_path,
            voice=plan.voice,
            language=DEFAULT_LANGUAGE,
            gender=DEFAULT_GENDER,
            style=plan.style,
        ),
        label="Voice generation",
        delay=3.0,
    )


def _step_collect_videos(plan: VideoPlan) -> list[Path]:
    log_step(log, "VIDEO COLLECTION", "Downloading copyright-safe clips…")
    # Limit to a maximum of 3 keywords to keep storage and memory footprint small
    limited_keywords = plan.keywords[:3] if plan.keywords else []
    return _retry(
        lambda: collect_scene_videos(limited_keywords),
        label="Video collection",
    )


def _step_render(
    plan: VideoPlan,
    audio_path: Path,
    video_paths: list[Path],
    output_path: Path,
) -> None:
    log_step(log, "RENDERING", f"Output: {output_path.name}")
    _retry(
        lambda: render_short(
            script=plan.script,
            audio_path=audio_path,
            video_paths=video_paths,
            output_path=output_path,
        ),
        label="Video rendering",
        attempts=2,
    )


def _step_generate_thumbnail(plan: VideoPlan, output_path: Path) -> Path:
    log_step(log, "THUMBNAIL", "Generating thumbnail…")
    try:
        return generate_thumbnail(
            title=plan.title,
            thumbnail_text=plan.thumbnail_text,
        )
    except Exception as exc:
        log.warning("Thumbnail generation failed (non-fatal): %s", exc)
        return Path("")


def _step_upload(plan: VideoPlan, video_path: Path) -> str:
    log_step(log, "UPLOAD", f"Uploading to YouTube ({DEFAULT_PRIVACY})…")

    description = plan.description
    description += (
        "\n\nThis content is created with original research and an original script."
    )

    return _retry(
        lambda: upload_video(
            video_path=video_path,
            title=plan.title,
            description=description,
            hashtags=plan.hashtags,
            privacy_status=DEFAULT_PRIVACY,
        ),
        label="YouTube upload",
        delay=10.0,
    )


def _step_save_to_db(
    topic_data: dict,
    plan: VideoPlan,
    video_path: Path,
    thumbnail_path: Path,
    youtube_video_id: str,
    trends: list[dict],
) -> None:
    log_step(log, "DATABASE", "Saving metadata…")

    topic = topic_data["topic"]
    th = save_topic(
        topic=topic,
        style=topic_data.get("style", plan.style),
        source_type="multi-source",
        source_urls=",".join(
            t.get("source_url", "") for t in trends[:3]
        ),
        score=topic_data.get("score", 0.0),
    )

    duration = 0.0
    try:
        import subprocess, json as _json
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(video_path)],
            capture_output=True, text=True, timeout=15
        )
        for s in _json.loads(r.stdout).get("streams", []):
            if s.get("duration"):
                duration = float(s["duration"]); break
    except Exception:
        pass

    mark_video_uploaded(
        topic_hash_value=th,
        title=plan.title,
        description=plan.description,
        keywords=plan.keywords,
        hashtags=plan.hashtags,
        local_path=str(video_path),
        thumbnail_path=str(thumbnail_path),
        youtube_video_id=youtube_video_id,
        platform="youtube",
        duration=duration,
        script_hash_value=script_hash(plan.script),
        trend_source=trends[0].get("source", "") if trends else "",
    )

    log.info("Metadata saved for video ID: %s", youtube_video_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_pipeline() -> VideoResult:
    """
    Execute the full automated pipeline end-to-end.

    Returns a VideoResult with all metadata.
    Raises PipelineError on unrecoverable failure.
    """
    initialize_database()

    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    topic_data: dict = {}
    plan: VideoPlan | None = None
    audio_path: Path | None = None
    video_path: Path | None = None
    thumbnail_path: Path | None = None

    log_step(log, "PIPELINE START", f"AutoShorts Engine — {timestamp}")

    try:
        # 1. Trends
        trends = _step_collect_trends()

        # 2. Topic selection (with dedup)
        topic_data = _step_select_topic(trends)
        topic = topic_data["topic"]
        style = topic_data.get("style", "facts")

        # 3. Research
        research = _step_research(topic)

        # 4. Script / plan
        plan = _step_generate_plan(topic, style, research)
        filename = _safe_filename(plan.title)

        # 5. Voice
        audio_path = DOWNLOAD_DIR / f"{filename}_voice.mp3"
        _step_generate_voice(plan, audio_path)

        # 6. Videos
        video_paths = _step_collect_videos(plan)

        # 7. Render
        video_path = OUTPUT_DIR / f"{filename}_{timestamp}.mp4"
        _step_render(plan, audio_path, video_paths, video_path)

        # 8. Thumbnail
        thumbnail_path = _step_generate_thumbnail(plan, video_path)

        # 9. Upload
        youtube_video_id = _step_upload(plan, video_path)

        # 10. Save to DB
        _step_save_to_db(
            topic_data, plan, video_path, thumbnail_path,
            youtube_video_id, trends,
        )

        log_step(
            log,
            "PIPELINE COMPLETE",
            f"Video ID: {youtube_video_id} | {plan.title}",
        )
        log.info("Watch (once made public): https://youtu.be/%s", youtube_video_id)

        return VideoResult(
            topic=topic,
            topic_hash=topic_hash(topic),
            video_path=str(video_path),
            title=plan.title,
            description=plan.description,
            hashtags=plan.hashtags,
            thumbnail_path=str(thumbnail_path),
            youtube_video_id=youtube_video_id,
            upload_status="uploaded",
            trend_source=trends[0].get("source", "") if trends else "",
            script_hash=script_hash(plan.script),
            duration=0.0,
        )

    except PipelineError as exc:
        log.error("Pipeline failed: %s", exc)
        record_failure(
            stage="pipeline",
            message=str(exc),
            topic=topic_data.get("topic", ""),
        )
        raise

    except Exception as exc:
        log.exception("Unexpected pipeline error: %s", exc)
        record_failure(
            stage="pipeline",
            message=str(exc),
            topic=topic_data.get("topic", ""),
            details=repr(exc),
        )
        raise PipelineError(f"Unexpected error: {exc}") from exc

    finally:
        # Wipe all files from temporary folders to guarantee 0MB usage
        _clean_downloads()
        try:
            if video_path and video_path.exists():
                video_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if thumbnail_path and thumbnail_path.exists():
                thumbnail_path.unlink(missing_ok=True)
        except Exception:
            pass


def run_daily_batch(count: int = DAILY_VIDEO_COUNT) -> list[VideoResult]:
    """
    Run the pipeline `count` times to produce the day's videos.

    Each run is independent — a failure in one video does not stop the others.
    """
    results: list[VideoResult] = []

    for i in range(1, count + 1):
        log.info("=== Daily batch: video %d of %d ===", i, count)

        try:
            result = run_pipeline()
            results.append(result)

            if i < count:
                log.info("Waiting 30 seconds before next video…")
                time.sleep(30)

        except PipelineError as exc:
            log.error("Video %d/%d failed: %s — continuing…", i, count, exc)

    log.info(
        "Daily batch complete: %d/%d videos produced.",
        len(results), count,
    )
    return results
