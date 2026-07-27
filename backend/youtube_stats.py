"""
AutoShorts Backend — YouTube Stats Fetcher.

Fetches live video statistics (views, likes, comments) from the
YouTube Data API v3 using the channel's stored OAuth credentials.

No separate YOUTUBE_API_KEY needed — uses the same OAuth token
that was used for uploading the video.
"""

from __future__ import annotations

import logging
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

log = logging.getLogger("autoshorts.youtube_stats")


def _build_youtube_service(channel):
    """
    Build a YouTube API service client from the channel's stored OAuth tokens.
    Falls back gracefully if token refresh fails.
    """
    from backend.auth_service import decrypt_token

    access_token  = decrypt_token(channel.access_token_enc)  if channel.access_token_enc  else None
    refresh_token = decrypt_token(channel.refresh_token_enc) if channel.refresh_token_enc else None

    if not access_token and not refresh_token:
        raise ValueError("Channel has no stored OAuth tokens — cannot fetch stats")

    client_id     = os.environ.get("GOOGLE_CLIENT_ID",     "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    creds = Credentials(
        token         = access_token,
        refresh_token = refresh_token,
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = client_id,
        client_secret = client_secret,
        scopes        = ["https://www.googleapis.com/auth/youtube"],
    )

    # Try to refresh if token is expired
    if refresh_token and client_id and client_secret:
        try:
            if creds.expired:
                creds.refresh(Request())
        except Exception as exc:
            log.warning("Token refresh failed (will try with current token): %s", exc)

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


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
    youtube = _build_youtube_service(channel)

    response = youtube.videos().list(
        part="statistics",
        id=video_id,
    ).execute()

    items = response.get("items", [])
    if not items:
        # Video might be private or not found — return zeros
        log.warning("YouTube API returned no items for video ID: %s (private/deleted?)", video_id)
        return {"views": 0, "likes": 0, "comments": 0}

    stats = items[0].get("statistics", {})

    result = {
        "views":    int(stats.get("viewCount",    0)),
        "likes":    int(stats.get("likeCount",    0)),
        # commentCount may be missing if comments are disabled
        "comments": int(stats.get("commentCount", 0)),
    }

    log.info(
        "Stats for video %s: %d views, %d likes, %d comments",
        video_id, result["views"], result["likes"], result["comments"],
    )
    return result
