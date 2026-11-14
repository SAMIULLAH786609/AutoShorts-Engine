"""
AutoShorts Engine — Video Collector Service.

Downloads copyright-safe stock video clips for each scene keyword.

Priority order:
  1. Pexels (best portrait video quality)
  2. Pixabay (fallback)

Features:
  - Random page selection so each video gets DIFFERENT clips
  - Retry logic per source
  - Automatic portrait orientation selection
  - Quality-optimized file selection (closest to 720px height)
  - Per-job unique output filenames to prevent reuse
"""

from __future__ import annotations

import hashlib
import random
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from config import (
    API_TIMEOUT_SECONDS,
    DOWNLOAD_DIR,
    PEXELS_API_KEY,
    PIXABAY_API_KEY,
)
from autoshorts.services.logging_setup import get_logger

log = get_logger("video_collector")

PEXELS_SEARCH_URL  = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"


# ---------------------------------------------------------------------------
# Pexels
# ---------------------------------------------------------------------------

def _select_best_pexels_file(video: dict[str, Any]) -> str | None:
    """Choose the best portrait MP4 from a Pexels video object."""
    files = video.get("video_files", [])

    mp4 = [
        f for f in files
        if f.get("file_type") == "video/mp4" and f.get("link")
    ]

    portrait   = [f for f in mp4 if (f.get("height") or 0) > (f.get("width") or 0)]
    candidates = portrait or mp4

    # Prefer height closest to 720 px (safer for 512 MB RAM server limit)
    candidates.sort(key=lambda f: abs((f.get("height") or 720) - 720))

    return candidates[0]["link"] if candidates else None


def search_pexels(query: str) -> str | None:
    """
    Search Pexels for a portrait video and return the download URL.
    Uses a RANDOM page (1-5) so each generation gets different clips.
    """
    if not PEXELS_API_KEY:
        log.debug("PEXELS_API_KEY not set")
        return None

    # Random page so we don't always get the same top result
    page = random.randint(1, 5)

    try:
        response = requests.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": PEXELS_API_KEY},
            params={
                "query":       query,
                "orientation": "portrait",
                "size":        "medium",
                "per_page":    15,
                "page":        page,
            },
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        videos = response.json().get("videos", [])
        # Shuffle results so we don't always pick index 0
        random.shuffle(videos)

        for video in videos:
            url = _select_best_pexels_file(video)
            if url:
                return url

        # If random page had no results, try page 1 as fallback
        if page > 1:
            response2 = requests.get(
                PEXELS_SEARCH_URL,
                headers={"Authorization": PEXELS_API_KEY},
                params={
                    "query":       query,
                    "orientation": "portrait",
                    "size":        "medium",
                    "per_page":    15,
                    "page":        1,
                },
                timeout=API_TIMEOUT_SECONDS,
            )
            response2.raise_for_status()
            videos2 = response2.json().get("videos", [])
            random.shuffle(videos2)
            for video in videos2:
                url = _select_best_pexels_file(video)
                if url:
                    return url

    except Exception as exc:
        log.warning("Pexels search failed for '%s': %s", query, exc)

    return None


# ---------------------------------------------------------------------------
# Pixabay
# ---------------------------------------------------------------------------

def _select_best_pixabay_file(hit: dict[str, Any]) -> str | None:
    """Select the best video URL from a Pixabay video hit."""
    videos = hit.get("videos", {})

    # Prefer medium/small for 512 MB RAM server limit
    for quality in ("medium", "small", "tiny"):
        entry = videos.get(quality, {})
        url = entry.get("url", "")
        if url:
            return url

    return None


def search_pixabay(query: str) -> str | None:
    """
    Search Pixabay for a video and return the download URL.
    Uses a RANDOM page (1-4) for variety.
    """
    if not PIXABAY_API_KEY:
        log.debug("PIXABAY_API_KEY not set")
        return None

    page = random.randint(1, 4)

    try:
        response = requests.get(
            PIXABAY_SEARCH_URL,
            params={
                "key":        PIXABAY_API_KEY,
                "q":          query,
                "video_type": "film",
                "per_page":   15,
                "page":       page,
            },
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        hits = response.json().get("hits", [])
        random.shuffle(hits)

        for hit in hits:
            url = _select_best_pixabay_file(hit)
            if url:
                return url

    except Exception as exc:
        log.warning("Pixabay search failed for '%s': %s", query, exc)

    return None


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

def _download_file(url: str, output_path: Path) -> None:
    """Stream-download a file to disk."""
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        size_limit = 100 * 1024 * 1024
        if int(resp.headers.get("Content-Length", "0")) > size_limit:
            raise RuntimeError("Stock clip exceeds the 100 MB download limit")
        total = 0
        with output_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    total += len(chunk)
                    if total > size_limit:
                        raise RuntimeError("Stock clip exceeds the 100 MB download limit")
                    fh.write(chunk)
        if not total:
            raise RuntimeError("Stock provider returned an empty clip")


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def collect_scene_videos(
    keywords: list[str],
    output_dir: Path | None = None,
) -> list[Path]:
    """
    Download one video clip for each visual keyword.

    Tries Pexels first, then Pixabay.
    Uses random pages so each video job gets UNIQUE stock footage.
    Each job gets its own sub-folder with a unique ID to prevent file reuse.

    Returns a list of local Paths (at least one guaranteed or RuntimeError raised).
    """
    base_dest = output_dir or DOWNLOAD_DIR

    # Unique sub-folder per job so different videos never share files
    job_id  = uuid.uuid4().hex[:10]
    dest    = base_dest / job_id
    dest.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []

    for index, query in enumerate(keywords, start=1):
        log.info("Scene %d/%d: searching for '%s'", index, len(keywords), query)

        # Unique filename: scene index + random suffix so files are never confused
        rand_suffix = uuid.uuid4().hex[:6]
        output_path = dest / f"scene_{index:02d}_{rand_suffix}.mp4"

        for source_name, source in (("Pexels", search_pexels), ("Pixabay", search_pixabay)):
            try:
                video_url = source(query)
                if not video_url:
                    continue
                _download_file(video_url, output_path)
                paths.append(output_path)
                log.info("Scene %d downloaded via %s: %s", index, source_name, output_path.name)
                break
            except Exception as exc:
                output_path.unlink(missing_ok=True)
                log.warning("Scene %d download failed via %s (%s); trying fallback", index, source_name, type(exc).__name__)

    if not paths:
        raise RuntimeError(
            "No stock videos were downloaded. "
            "Check PEXELS_API_KEY / PIXABAY_API_KEY or try different keywords."
        )

    log.info("Video collection complete: %d unique clips in %s", len(paths), dest.name)
    return paths
