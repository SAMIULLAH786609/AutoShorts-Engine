"""
AutoShorts Backend — YouTube Stats Fetcher.

Fetches live video statistics (views, likes, comments) from the
YouTube Data API v3 using the channel's stored OAuth credentials.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

log = logging.getLogger("autoshorts.youtube_stats")


def _build_credentials(channel) -> Credentials:
    """Build a Google OAuth Credentials object from the channel's stored tokens."""
    from backend.auth_service import decrypt_token

    access_token  = decrypt_token(channel.access_token_enc)  if channel.access_token_enc  else None
    refresh_token = decrypt_token(channel.refresh_token_enc) if channel.refresh_token_enc else None

    if not access_token and not refresh_token:
        raise ValueError("Channel has no stored OAuth tokens")

    import os
    creds = Credentials(
        token         = access_token,
        refresh_token = refresh_token,
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = os.environ.get("GOOGLE_CLIENT_ID", ""),
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        scopes        = [
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/youtube.upload",
        ],
    )

    # Refresh the token if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            log.warning("Failed to refresh OAuth token: %s", exc)

    return creds


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
    try:
        creds   = _build_credentials(channel)
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        log.warning("Could not build YouTube service: %s — using API key fallback", exc)
        youtube = _build_with_api_key()

    response = youtube.videos().list(
        part="statistics",
        id=video_id,
    ).execute()

    items = response.get("items", [])
    if not items:
        log.warning("YouTube API returned no items for video ID: %s", video_id)
        return {"views": 0, "likes": 0, "comments": 0}

    stats = items[0].get("statistics", {})
    return {
        "views":    int(stats.get("viewCount",    0)),
        "likes":    int(stats.get("likeCount",    0)),
        "comments": int(stats.get("commentCount", 0)),
    }


def _build_with_api_key():
    """Fallback: build YouTube client using a simple API key (read-only)."""
    import os
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "No YOUTUBE_API_KEY env variable set and OAuth credentials unavailable"
        )
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)
