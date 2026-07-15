import json
from pathlib import Path

from autoshorts.services.youtube_upload import upload_video


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"
UPLOAD_HISTORY_FILE = PROJECT_DIR / "uploaded_videos.json"


def load_upload_history() -> dict[str, str]:
    """Load previously uploaded filenames and their YouTube IDs."""

    if not UPLOAD_HISTORY_FILE.exists():
        return {}

    try:
        return json.loads(
            UPLOAD_HISTORY_FILE.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError:
        return {}


def save_upload_history(history: dict[str, str]) -> None:
    """Save uploaded filenames and YouTube IDs."""

    UPLOAD_HISTORY_FILE.write_text(
        json.dumps(history, indent=2),
        encoding="utf-8",
    )


def find_latest_unuploaded_video(
    history: dict[str, str],
) -> Path:
    """Find the newest MP4 that has not already been uploaded."""

    videos = sorted(
        OUTPUT_DIR.glob("*.mp4"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not videos:
        raise FileNotFoundError(
            f"No MP4 video found inside: {OUTPUT_DIR}"
        )

    for video in videos:
        if video.name not in history:
            return video

    raise RuntimeError(
        "All videos in the output folder have already been uploaded."
    )


def main() -> None:
    history = load_upload_history()
    video_path = find_latest_unuploaded_video(history)

    print("Selected new video:", video_path)

    confirmation = input(
        "Upload this video privately to YouTube? (y/n): "
    ).strip().lower()

    if confirmation != "y":
        print("Upload cancelled.")
        return

    video_id = upload_video(
        video_path=video_path,
        title=video_path.stem.replace("_", " ")[:100],
        description=(
            "This video was generated using AutoShorts Engine."
        ),
        hashtags=[
            "Shorts",
            "AutoShorts",
            "AI",
        ],
        privacy_status="private",
    )

    history[video_path.name] = video_id
    save_upload_history(history)

    print("Uploaded video ID:", video_id)
    print("Upload history updated.")


if __name__ == "__main__":
    main()