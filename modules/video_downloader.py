from pathlib import Path
from typing import Any

import requests

from config import DOWNLOAD_DIR, PEXELS_API_KEY


PEXELS_SEARCH_URL = (
    "https://api.pexels.com/videos/search"
)


def select_best_video(
    video: dict[str, Any],
) -> str | None:
    files = video.get("video_files", [])

    candidates = [
        item
        for item in files
        if item.get("file_type") == "video/mp4"
        and item.get("link")
    ]

    portrait = [
        item
        for item in candidates
        if (item.get("height") or 0)
        > (item.get("width") or 0)
    ]

    candidates = portrait or candidates

    candidates.sort(
        key=lambda item: abs(
            (item.get("height") or 720) - 1280
        )
    )

    if not candidates:
        return None

    return candidates[0]["link"]


def download_scene_video(
    query: str,
    scene_number: int,
) -> Path:
    headers = {
        "Authorization": PEXELS_API_KEY,
    }

    params = {
        "query": query,
        "orientation": "portrait",
        "size": "medium",
        "per_page": 10,
    }

    response = requests.get(
        PEXELS_SEARCH_URL,
        headers=headers,
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    video_url = None

    for video in response.json().get("videos", []):
        video_url = select_best_video(video)

        if video_url:
            break

    if not video_url:
        raise RuntimeError(
            f"No video found for: {query}"
        )

    output_path = (
        DOWNLOAD_DIR / f"scene_{scene_number}.mp4"
    )

    with requests.get(
        video_url,
        stream=True,
        timeout=120,
    ) as download:
        download.raise_for_status()

        with output_path.open("wb") as file:
            for chunk in download.iter_content(
                chunk_size=1024 * 1024
            ):
                if chunk:
                    file.write(chunk)

    return output_path


def download_scene_videos(
    scenes: list[dict],
) -> list[Path]:
    paths = []

    for index, scene in enumerate(
        scenes,
        start=1,
    ):
        query = scene.get("visual_query", "").strip()

        if not query:
            continue

        print(f"Downloading scene {index}: {query}")

        try:
            paths.append(
                download_scene_video(
                    query,
                    index,
                )
            )
        except Exception as exc:
            print(
                f"Scene {index} failed: {exc}"
            )

    if not paths:
        raise RuntimeError(
            "No visual scenes were downloaded."
        )

    return paths