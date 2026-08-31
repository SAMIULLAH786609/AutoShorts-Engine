"""
AutoShorts Backend — YouTube Channel Router.

Endpoints:
  GET    /api/channels                  — list connected channels
  GET    /api/channels/oauth-url        — get Google OAuth URL
  GET    /api/channels/oauth-callback   — handle OAuth callback + save tokens
  DELETE /api/channels/{id}             — disconnect channel
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.auth_service import decrypt_token, encrypt_token, get_current_user
from backend.config import (
    FRONTEND_URL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
)
from backend.database import get_db
from backend.models import User, YouTubeChannel
from backend.schemas import ChannelResponse

router = APIRouter(prefix="/api/channels", tags=["channels"])

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API_URL  = "https://www.googleapis.com/youtube/v3/channels"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "openid",
    "email",
    "profile",
]


# ── List connected channels ───────────────────────────────────

@router.get("", response_model=List[ChannelResponse])
def list_channels(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    return (
        db.query(YouTubeChannel)
        .filter(YouTubeChannel.user_id == current_user.id)
        .all()
    )


# ── Get OAuth URL ─────────────────────────────────────────────

@router.get("/oauth-url")
def get_oauth_url(current_user: User = Depends(get_current_user)):
    """Return the Google OAuth consent page URL for the user to visit."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID in backend/.env",
        )

    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         " ".join(SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         current_user.id,   # pass user_id through OAuth flow
    }

    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return {"oauth_url": url}


# ── OAuth Callback ────────────────────────────────────────────

@router.get("/oauth-callback")
def oauth_callback(
    code:  str          = Query(...),
    state: str          = Query(...),   # user_id
    error: str | None   = Query(None),
    db:    Session      = Depends(get_db),
):
    """
    Google redirects here after user grants consent.
    Exchanges code for tokens and saves the channel to the database.
    """
    if error:
        return _redirect_to_frontend(f"/settings?error={error}")

    user_id = state
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return _redirect_to_frontend("/settings?error=invalid_state")

    # Exchange code for tokens
    try:
        token_data = _exchange_code(code)
    except Exception as exc:
        return _redirect_to_frontend(f"/settings?error=token_exchange_failed")

    access_token  = token_data.get("access_token",  "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in    = int(token_data.get("expires_in", 3600))
    expires_at    = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Fetch channel info
    try:
        channel_info = _fetch_channel_info(access_token)
    except Exception:
        channel_info = {}

    channel_id   = channel_info.get("id",    "unknown")
    channel_name = channel_info.get("title", "My Channel")
    channel_url  = f"https://youtube.com/channel/{channel_id}"
    thumb_url    = channel_info.get("thumbnail", "")

    # Upsert channel record
    existing = (
        db.query(YouTubeChannel)
        .filter(
            YouTubeChannel.user_id    == user_id,
            YouTubeChannel.channel_id == channel_id,
        )
        .first()
    )

    if existing:
        existing.access_token_enc  = encrypt_token(access_token)
        existing.refresh_token_enc = encrypt_token(refresh_token) if refresh_token else existing.refresh_token_enc
        existing.token_expires_at  = expires_at
        existing.is_connected      = True
        existing.channel_name      = channel_name
        existing.channel_url       = channel_url
        existing.thumbnail_url     = thumb_url
    else:
        channel = YouTubeChannel(
            user_id           = user_id,
            channel_id        = channel_id,
            channel_name      = channel_name,
            channel_url       = channel_url,
            thumbnail_url     = thumb_url,
            access_token_enc  = encrypt_token(access_token),
            refresh_token_enc = encrypt_token(refresh_token) if refresh_token else "",
            token_expires_at  = expires_at,
            is_connected      = True,
        )
        db.add(channel)

    db.commit()

    return _redirect_to_frontend("/settings?connected=true")


# ── Disconnect channel ────────────────────────────────────────

@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_channel(
    channel_id:   str,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    channel = (
        db.query(YouTubeChannel)
        .filter(
            YouTubeChannel.id      == channel_id,
            YouTubeChannel.user_id == current_user.id,
        )
        .first()
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    db.delete(channel)
    db.commit()


# ── Helpers ───────────────────────────────────────────────────

def _exchange_code(code: str) -> dict:
    """Exchange OAuth authorization code for access/refresh tokens."""
    with httpx.Client() as client:
        resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  GOOGLE_REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


def _fetch_channel_info(access_token: str) -> dict:
    """Fetch the authenticated user's YouTube channel details."""
    with httpx.Client() as client:
        resp = client.get(
            YOUTUBE_API_URL,
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return {}

        item = items[0]
        snippet = item.get("snippet", {})
        thumbs  = snippet.get("thumbnails", {})
        thumb   = (
            thumbs.get("default", {}).get("url", "")
            or thumbs.get("medium", {}).get("url", "")
        )

        return {
            "id":        item.get("id", ""),
            "title":     snippet.get("title", ""),
            "thumbnail": thumb,
        }


def _redirect_to_frontend(path: str):
    """Redirect the browser to the React frontend after OAuth."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{FRONTEND_URL}{path}")


# ── Token refresh helper (used by pipeline runner) ────────────

def refresh_channel_tokens(channel: YouTubeChannel, db: Session) -> str:
    """
    Refresh the OAuth access token if expired.
    Returns the fresh access token (plain text).
    """
    refresh_token = decrypt_token(channel.refresh_token_enc or "")

    if not refresh_token:
        raise RuntimeError("No refresh token available. User must reconnect their channel.")

    with httpx.Client() as client:
        resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    new_access = data.get("access_token", "")
    expires_in = int(data.get("expires_in", 3600))

    channel.access_token_enc = encrypt_token(new_access)
    channel.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    db.commit()

    return new_access
