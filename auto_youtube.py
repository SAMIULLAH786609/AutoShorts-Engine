from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from autoshorts.services.youtube_upload import upload_video
from modules.optimizer import generate_original_daily_topics
from pipeline import create_short


# ---------------------------------------------------------
# Project configuration
# ---------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent

load_dotenv(PROJECT_DIR / ".env")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
CHANNEL_NICHE = os.getenv(
    "CHANNEL_NICHE",
    "Pakistani student comedy",
).strip()
REGION_CODE = os.getenv("REGION_CODE", "PK").strip().upper()
DEFAULT_LANGUAGE = os.getenv(
    "DEFAULT_LANGUAGE",
    "English",
).strip()
DEFAULT_GENDER = os.getenv(
    "DEFAULT_GENDER",
    "female",
).strip().lower()
DEFAULT_PRIVACY = os.getenv(
    "DEFAULT_PRIVACY",
    "private",
).strip().lower()

UPLOAD_HISTORY_FILE = PROJECT_DIR / "uploaded_videos.json"

YOUTUBE_POPULAR_URL = (
    "https://www.googleapis.com/youtube/v3/videos"
)


# ---------------------------------------------------------
# Upload history
# ---------------------------------------------------------

def load_upload_history() -> dict[str, str]:
    """Load filenames that have already been uploaded."""

    if not UPLOAD_HISTORY_FILE.exists():
        return {}

    try:
        data = json.loads(
            UPLOAD_HISTORY_FILE.read_text(encoding="utf-8")
        )

        if isinstance(data, dict):
            return {
                str(filename): str(video_id)
                for filename, video_id in data.items()
            }

    except (json.JSONDecodeError, OSError):
        pass

    return {}


def save_upload_history(history: dict[str, str]) -> None:
    """Save uploaded filenames and their YouTube IDs."""

    UPLOAD_HISTORY_FILE.write_text(
        json.dumps(
            history,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------
# YouTube trends
# ---------------------------------------------------------

def fetch_popular_youtube_videos(
    region_code: str,
    max_results: int = 25,
) -> list[dict[str, Any]]:
    """
    Retrieve current popular YouTube videos for a country.

    The results are used only as trend signals. The program later
    generates an original topic instead of copying a video.
    """

    if not YOUTUBE_API_KEY:
        raise RuntimeError(
            "YOUTUBE_API_KEY is missing from the .env file."
        )

    params = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region_code,
        "maxResults": max_results,
        "key": YOUTUBE_API_KEY,
    }

    print(
        f"Checking current popular YouTube content "
        f"for region: {region_code}..."
    )

    response = requests.get(
        YOUTUBE_POPULAR_URL,
        params=params,
        timeout=30,
    )

    if response.status_code == 403:
        raise RuntimeError(
            "YouTube API returned 403.\n"
            "Check that YouTube Data API v3 is enabled and "
            "your API key is valid."
        )

    response.raise_for_status()

    items = response.json().get("items", [])

    trends: list[dict[str, Any]] = []

    for item in items:
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})

        title = str(snippet.get("title", "")).strip()

        if not title:
            continue

        trends.append(
            {
                "video_id": str(item.get("id", "")),
                "title": title,
                "channel": str(
                    snippet.get("channelTitle", "")
                ),
                "category_id": str(
                    snippet.get("categoryId", "")
                ),
                "description": str(
                    snippet.get("description", "")
                )[:500],
                "views": int(
                    statistics.get("viewCount", 0)
                ),
                "likes": int(
                    statistics.get("likeCount", 0)
                ),
                "comments": int(
                    statistics.get("commentCount", 0)
                ),
            }
        )

    if not trends:
        raise RuntimeError(
            "YouTube returned no popular-video results."
        )

    trends.sort(
        key=lambda item: (
            item["views"],
            item["likes"],
            item["comments"],
        ),
        reverse=True,
    )

    return trends


def choose_original_trending_topic(
    trends: list[dict[str, Any]],
) -> dict[str, str]:
    """
    Ask Gemini to study popular-video patterns and generate one
    original idea for the configured channel niche.
    """

    print(
        f"Creating an original topic for niche: "
        f"{CHANNEL_NICHE}..."
    )

    ideas = generate_original_daily_topics(
        trend_items=trends,
        count=1,
        niche=CHANNEL_NICHE,
    )

    if not ideas:
        raise RuntimeError(
            "Gemini could not generate a trend-based topic."
        )

    idea = ideas[0]

    topic = str(idea.get("topic", "")).strip()

    if not topic:
        raise RuntimeError(
            "The generated trend idea did not contain a topic."
        )

    return {
        "topic": topic,
        "style": str(
            idea.get("style", "funny")
        ).strip().lower(),
        "trend_reason": str(
            idea.get("trend_reason", "")
        ).strip(),
        "original_angle": str(
            idea.get("original_angle", "")
        ).strip(),
    }


# ---------------------------------------------------------
# Complete pipeline
# ---------------------------------------------------------

def clean_hashtags(value: Any) -> list[str]:
    """Return hashtags in the format expected by the uploader."""

    if not isinstance(value, list):
        return ["Shorts", "AutoShorts", "AI"]

    hashtags: list[str] = []

    for item in value:
        tag = str(item).strip().lstrip("#")

        if tag:
            hashtags.append(tag)

    return hashtags or ["Shorts", "AutoShorts", "AI"]


def generate_and_upload_trending_video() -> str:
    """Find a trend, create a Short, and upload it privately."""

    print("\n==========================================")
    print(" AutoShorts Automatic Trending Pipeline")
    print("==========================================")

    # Step 1: Find trends
    trends = fetch_popular_youtube_videos(
        region_code=REGION_CODE,
        max_results=25,
    )

    print(f"Received {len(trends)} trend signals.")

    # Step 2: Generate one original topic
    idea = choose_original_trending_topic(trends)

    topic = idea["topic"]
    style = idea["style"]

    allowed_styles = {
        "funny",
        "facts",
        "story",
        "educational",
        "motivational",
    }

    if style not in allowed_styles:
        style = "funny"

    print("\nSelected original topic:")
    print(topic)

    if idea["trend_reason"]:
        print("\nTrend reason:")
        print(idea["trend_reason"])

    if idea["original_angle"]:
        print("\nOriginal angle:")
        print(idea["original_angle"])

    # Step 3: Create complete MP4
    print("\nCreating the complete Short...")

    result = create_short(
        topic=topic,
        style=style,
        language=DEFAULT_LANGUAGE,
        gender=DEFAULT_GENDER,
    )

    video_path = Path(result["video_path"]).resolve()

    if not video_path.exists():
        raise FileNotFoundError(
            f"Generated video was not found: {video_path}"
        )

    # Step 4: Protect against duplicate uploads
    history = load_upload_history()

    if video_path.name in history:
        raise RuntimeError(
            "This generated file has already been uploaded.\n"
            f"Existing video ID: {history[video_path.name]}"
        )

    title = str(
        result.get("title")
        or video_path.stem.replace("_", " ")
    ).strip()[:100]

    description = str(
        result.get("description")
        or (
            "Generated with AutoShorts Engine using "
            "an original trend-inspired topic."
        )
    ).strip()

    description += (
        "\n\nThis content uses current audience-interest "
        "patterns only as inspiration and presents an "
        "original script and angle."
    )

    hashtags = clean_hashtags(
        result.get("hashtags")
    )

    # Step 5: Upload privately
    print("\nUploading the generated video to YouTube...")
    print("Video:", video_path)
    print("Title:", title)
    print("Privacy:", DEFAULT_PRIVACY)

    video_id = upload_video(
        video_path=video_path,
        title=title,
        description=description,
        hashtags=hashtags,
        privacy_status=DEFAULT_PRIVACY,
    )

    history[video_path.name] = video_id
    save_upload_history(history)

    print("\n==========================================")
    print(" SUCCESS")
    print("==========================================")
    print("Topic:", topic)
    print("Generated video:", video_path)
    print("YouTube video ID:", video_id)
    print("Privacy:", DEFAULT_PRIVACY)

    return video_id


def main() -> None:
    generate_and_upload_trending_video()


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\nOperation cancelled.")

    except Exception as error:
        print("\nERROR:", error)
        raise SystemExit(1)