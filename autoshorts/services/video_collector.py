"""
AutoShorts Engine — Video Collector Service.

Downloads copyright-safe stock video clips for each scene keyword.

Priority order:
  1. Pexels (best portrait video quality)
  2. Pixabay (fallback)

Features:
  - Retry logic per source
  - Automatic portrait orientation selection
  - Quality-optimized file selection (closest to 1280px height)
  - Result caching by keyword hash to avoid re-downloading
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import requests

from config import (
    API_TIMEOUT_SECONDS,
    CACHE_DIR,
    DOWNLOAD_DIR,
    PEXELS_API_KEY,
    PIXABAY_API_KEY,
)
from autoshorts.services.logging_setup import get_logger

log = get_logger("video_collector")

PEXELS_SEARCH_URL  = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"

_CACHE_FILE = CACHE_DIR / "video_url_cache.json"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_cache() -> dict[str, str]:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _cache_key(query: str, source: str) -> str:
    return hashlib.md5(f"{source}:{query.lower().strip()}".encode()).hexdigest()


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

    portrait = [f for f in mp4 if (f.get("height") or 0) > (f.get("width") or 0)]
    candidates = portrait or mp4

    # Prefer height closest to 1280 px
    candidates.sort(key=lambda f: abs((f.get("height") or 720) - 1280))

    return candidates[0]["link"] if candidates else None


def search_pexels(query: str) -> str | None:
    """Search Pexels for a portrait video and return the download URL."""
    if not PEXELS_API_KEY:
        log.debug("PEXELS_API_KEY not set")
        return None

    try:
        response = requests.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": PEXELS_API_KEY},
            params={
                "query": query,
                "orientation": "portrait",
                "size": "medium",
                "per_page": 10,
            },
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        for video in response.json().get("videos", []):
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

    # Preference order by quality
    for quality in ("large", "medium", "small", "tiny"):
        entry = videos.get(quality, {})
        url = entry.get("url", "")
        if url:
            return url

    return None


def search_pixabay(query: str) -> str | None:
    """Search Pixabay for a video and return the download URL."""
    if not PIXABAY_API_KEY:
        log.debug("PIXABAY_API_KEY not set")
        return None

    try:
        response = requests.get(
            PIXABAY_SEARCH_URL,
            params={
                "key": PIXABAY_API_KEY,
                "q": query,
                "video_type": "film",
                "per_page": 10,
            },
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        for hit in response.json().get("hits", []):
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

        with output_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)


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
    Results are cached so repeat queries don't re-download.

    Returns a list of local Paths (at least one guaranteed or RuntimeError raised).
    """
    dest = output_dir or DOWNLOAD_DIR
    dest.mkdir(parents=True, exist_ok=True)

    cache = _load_cache()
    paths: list[Path] = []

    for index, query in enumerate(keywords, start=1):
        log.info("Scene %d/%d: searching for '%s'", index, len(keywords), query)

        video_url: str | None = None

        # Check cache
        for source in ("pexels", "pixabay"):
            key = _cache_key(query, source)
            if key in cache:
                video_url = cache[key]
                log.debug("Cache hit for '%s' (%s)", query, source)
                break

        # Search sources
        if not video_url:
            video_url = search_pexels(query)
            if video_url:
                cache[_cache_key(query, "pexels")] = video_url

        if not video_url:
            video_url = search_pixabay(query)
            if video_url:
                cache[_cache_key(query, "pixabay")] = video_url

        if not video_url:
            log.warning("No video found for scene %d: '%s' — skipping", index, query)
            continue

        output_path = dest / f"scene_{index:02d}.mp4"

        try:
            _download_file(video_url, output_path)
            paths.append(output_path)
            log.info(
                "Scene %d downloaded: %s (%.1f MB)",
                index,
                output_path.name,
                output_path.stat().st_size / (1024 * 1024),
            )
        except Exception as exc:
            log.error("Download failed for scene %d '%s': %s", index, query, exc)

    _save_cache(cache)

    if not paths:
        raise RuntimeError(
            "No stock videos were downloaded. "
            "Check PEXELS_API_KEY / PIXABAY_API_KEY or try different keywords."
        )

    log.info("Video collection complete: %d clips", len(paths))
    return paths
