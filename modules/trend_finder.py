from typing import Any

import requests

from config import REGION_CODE, YOUTUBE_API_KEY


YOUTUBE_VIDEOS_URL = (
    "https://www.googleapis.com/youtube/v3/videos"
)


def get_youtube_trends(
    region_code: str = REGION_CODE,
    max_results: int = 25,
) -> list[dict[str, Any]]:
    if not YOUTUBE_API_KEY:
        raise RuntimeError(
            "YOUTUBE_API_KEY is missing from .env."
        )

    params = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region_code,
        "maxResults": max_results,
        "key": YOUTUBE_API_KEY,
    }

    response = requests.get(
        YOUTUBE_VIDEOS_URL,
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    results = []

    for item in response.json().get("items", []):
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})

        results.append(
            {
                "video_id": item.get("id"),
                "title": snippet.get("title", ""),
                "channel": snippet.get(
                    "channelTitle",
                    "",
                ),
                "category_id": snippet.get(
                    "categoryId",
                    "",
                ),
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

    return results