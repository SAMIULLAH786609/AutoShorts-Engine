"""
AutoShorts Engine — YouTube Upload Service.

Handles OAuth 2.0 authentication and video upload via the YouTube Data API v3.

This module is intentionally minimal and stable.
The working OAuth flow is preserved exactly as-is.
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from autoshorts.services.logging_setup import get_logger

log = get_logger("youtube_upload")

BASE_DIR            = Path(__file__).resolve().parents[2]
CREDENTIALS_DIR     = BASE_DIR / "credentials"
CLIENT_SECRET_FILE  = CREDENTIALS_DIR / "client_secret.json"
TOKEN_FILE          = CREDENTIALS_DIR / "youtube_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
]


def get_youtube_service():
    """Authorize the YouTube account and return the API service client."""
    if not CLIENT_SECRET_FILE.exists():
        raise FileNotFoundError(
            f"client_secret.json not found.\n"
            f"Expected: {CLIENT_SECRET_FILE}"
        )

    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            str(TOKEN_FILE), SCOPES
        )

    if credentials and credentials.expired and credentials.refresh_token:
        log.debug("Refreshing expired OAuth token…")
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        log.info("Opening OAuth browser flow (one-time setup)…")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET_FILE), SCOPES
        )
        credentials = flow.run_local_server(port=0, prompt="consent")

        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
        log.info("OAuth token saved to %s", TOKEN_FILE)

    return build("youtube", "v3", credentials=credentials)


def upload_video(
    video_path: str | Path,
    title: str,
    description: str,
    hashtags: list[str] | None = None,
    privacy_status: str = "private",
) -> str:
    """
    Upload an MP4 to YouTube and return its video ID.

    Parameters
    ----------
    video_path     : Path to the local MP4 file.
    title          : Video title (max 100 chars).
    description    : Video description.
    hashtags       : List of hashtag strings (without #).
    privacy_status : 'private' | 'unlisted' | 'public'.

    Returns the YouTube video ID string.
    """
    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if video_path.suffix.lower() != ".mp4":
        raise ValueError("Only .mp4 files are supported.")

    allowed = {"private", "unlisted", "public"}
    if privacy_status not in allowed:
        raise ValueError(f"privacy_status must be one of {allowed}")

    hashtags = hashtags or []

    # Always include Shorts-critical tags
    core_tags = ["Shorts", "Short", "YouTubeShorts", "viral", "facts", "trending"]
    all_tags  = core_tags + [t.strip().lstrip("#") for t in hashtags if t.strip()]
    # YouTube allows max 500 chars total in tags
    tags_list = list(dict.fromkeys(all_tags))[:30]   # dedupe + limit

    # Build hashtag line for description — #Shorts MUST appear in description
    # for YouTube to classify the video as a Short in the Shorts feed
    hash_core = "#Shorts #Short #viral #facts #trending"
    extra_tags = " ".join(
        f"#{t.strip().lstrip('#')}" for t in hashtags if t.strip()
    )
    hashtag_line = f"{hash_core} {extra_tags}".strip()

    final_description = description.strip()
    final_description += f"\n\n{hashtag_line}"

    youtube = get_youtube_service()

    request_body = {
        "snippet": {
            "title":       title[:100],
            "description": final_description[:5000],
            "tags":        tags_list,       # ← critical for search discovery
            "categoryId":  "27",            # 27 = Education (better for facts/science Shorts)
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":             privacy_status,
            "selfDeclaredMadeForKids":   False,
            "madeForKids":               False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=5 * 1024 * 1024,  # 5 MB chunks
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media,
    )

    log.info("Uploading '%s' to YouTube (%s)…", title[:60], privacy_status)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("Upload progress: %d%%", int(status.progress() * 100))

    video_id = response["id"]

    log.info(
        "Upload successful! Video ID: %s | URL: https://youtu.be/%s",
        video_id, video_id,
    )
    return video_id