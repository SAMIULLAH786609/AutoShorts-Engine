from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


BASE_DIR = Path(__file__).resolve().parents[2]

CREDENTIALS_DIR = BASE_DIR / "credentials"
CLIENT_SECRET_FILE = CREDENTIALS_DIR / "client_secret.json"
TOKEN_FILE = CREDENTIALS_DIR / "youtube_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
]


def get_youtube_service():
    """Authorize the YouTube account and return the API service."""

    if not CLIENT_SECRET_FILE.exists():
        raise FileNotFoundError(
            "client_secret.json was not found.\n"
            f"Expected location: {CLIENT_SECRET_FILE}"
        )

    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            str(TOKEN_FILE),
            SCOPES,
        )

    if (
        credentials
        and credentials.expired
        and credentials.refresh_token
    ):
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET_FILE),
            SCOPES,
        )

        credentials = flow.run_local_server(
            port=0,
            prompt="consent",
        )

        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

        TOKEN_FILE.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    return build(
        "youtube",
        "v3",
        credentials=credentials,
    )


def upload_video(
    video_path: str | Path,
    title: str,
    description: str,
    hashtags: list[str] | None = None,
    privacy_status: str = "private",
) -> str:
    """Upload an MP4 to YouTube and return its video ID."""

    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(
            f"Video file was not found: {video_path}"
        )

    if video_path.suffix.lower() != ".mp4":
        raise ValueError("Only MP4 video files are supported.")

    allowed_privacy = {"private", "unlisted", "public"}

    if privacy_status not in allowed_privacy:
        raise ValueError(
            "privacy_status must be private, unlisted, or public."
        )

    hashtags = hashtags or []

    hashtag_text = " ".join(
        f"#{tag.strip().lstrip('#')}"
        for tag in hashtags
        if tag.strip()
    )

    final_description = description.strip()

    if hashtag_text:
        final_description += f"\n\n{hashtag_text}"

    youtube = get_youtube_service()

    request_body = {
        "snippet": {
            "title": title[:100],
            "description": final_description,
            "categoryId": "24",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=-1,
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media,
    )

    print("Uploading video to YouTube...")

    response = request.execute()
    video_id = response["id"]

    print("Upload completed successfully.")
    print("YouTube Video ID:", video_id)

    return video_id