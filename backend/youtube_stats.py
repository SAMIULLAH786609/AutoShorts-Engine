"""
AutoShorts Backend — YouTube Stats Fetcher.

Fetches live video statistics (views, likes, comments) from the
YouTube Data API v3.

Strategy:
  1. Use the channel's stored OAuth access token directly via HTTP request
     (no token refresh library needed — works even without GOOGLE_CLIENT_ID)
  2. If access token fails/expired, try with YOUTUBE_API_KEY env var
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("autoshorts.youtube_stats")

YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def fetch_video_stats(channel, video_id: str) -> dict:
    """
    Fetch views, likes, and comment count for a YouTube video.

    Parameters
    ----------
    channel  : YouTubeChannel ORM model with stored OAuth tokens.
    video_id : YouTube video ID (e.g. 'dQw4w9WgXcQ').

    Returns
    -------
    dict with keys: 'views', 'likes', 'comments'
    """
    # --- Attempt 1: use stored OAuth access token directly ---
    try:
        from backend.auth_service import decrypt_token
        access_token = decrypt_token(channel.access_token_enc) if channel.access_token_enc else None

        if access_token:
            result = _fetch_with_token(video_id, access_token)
            if result is not None:
                log.info("Stats via OAuth token for %s: %s", video_id, result)
                return result
    except Exception as exc:
        log.warning("OAuth token stats attempt failed: %s", exc)

    # --- Attempt 2: use YOUTUBE_API_KEY (no OAuth needed for public videos) ---
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if api_key:
        try:
            result = _fetch_with_api_key(video_id, api_key)
            if result is not None:
                log.info("Stats via API key for %s: %s", video_id, result)
                return result
        except Exception as exc:
            log.warning("API key stats attempt failed: %s", exc)

    # --- Attempt 3: try refresh token to get a new access token ---
    try:
        new_token = _refresh_access_token(channel)
        if new_token:
            result = _fetch_with_token(video_id, new_token)
            if result is not None:
                log.info("Stats via refreshed token for %s: %s", video_id, result)
                return result
    except Exception as exc:
        log.warning("Token refresh stats attempt failed: %s", exc)

    raise RuntimeError(
        "Could not fetch YouTube stats. Make sure the video is Public and your channel is connected. "
        "Try adding YOUTUBE_API_KEY to your Render environment variables."
    )


def _fetch_with_token(video_id: str, access_token: str) -> dict | None:
    """Call YouTube Data API using OAuth Bearer token."""
    resp = requests.get(
        YT_VIDEOS_URL,
        params={"part": "statistics", "id": video_id},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if resp.status_code == 401:
        log.warning("Access token expired (401)")
        return None
    resp.raise_for_status()
    return _parse_stats(resp.json(), video_id)


def _fetch_with_api_key(video_id: str, api_key: str) -> dict | None:
    """Call YouTube Data API using a server API key (works for public videos)."""
    resp = requests.get(
        YT_VIDEOS_URL,
        params={"part": "statistics", "id": video_id, "key": api_key},
        timeout=10,
    )
    resp.raise_for_status()
    return _parse_stats(resp.json(), video_id)


def _refresh_access_token(channel) -> str | None:
    """Try to get a fresh access token using the stored refresh token."""
    from backend.auth_service import decrypt_token
    refresh_token = decrypt_token(channel.refresh_token_enc) if channel.refresh_token_enc else None
    if not refresh_token:
        return None

    client_id     = os.environ.get("GOOGLE_CLIENT_ID",     "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None

    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("access_token")


def _parse_stats(data: dict, video_id: str) -> dict | None:
    """Parse the YouTube API response and return stats dict."""
    items = data.get("items", [])
    if not items:
        log.warning("YouTube API returned no items for video %s (private/deleted?)", video_id)
        return {"views": 0, "likes": 0, "comments": 0}

    stats = items[0].get("statistics", {})
    return {
        "views":    int(stats.get("viewCount",    0)),
        "likes":    int(stats.get("likeCount",    0)),
        "comments": int(stats.get("commentCount", 0)),
    }
