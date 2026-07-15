from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config import (
    DOWNLOAD_DIR,
    METADATA_DIR,
    OUTPUT_DIR,
)
from modules.script_generator import generate_content_plan
from modules.video_downloader import download_scene_videos
from modules.voice_generator import generate_voice


def safe_name(text: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    cleaned = "".join(char if char in allowed else "_" for char in text)
    return "_".join(filter(None, cleaned.split("_")))[:70] or "autoshort"


def create_short(
    topic: str,
    style: str = "funny",
    language: str = "English",
    gender: str = "female",
) -> dict:
    print("\n[1/5] Generating content plan...")

    plan = generate_content_plan(
        topic=topic,
        style=style,
        language=language,
    )

    title = plan["title_options"][0]
    filename = safe_name(title)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    metadata_path = METADATA_DIR / f"{filename}_{timestamp}.json"
    metadata_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("[2/5] Generating voice...")

    audio_path = DOWNLOAD_DIR / f"{filename}_voice.mp3"

    generate_voice(
        text=plan["script"],
        output_path=audio_path,
        language=language,
        gender=gender,
        style=plan.get("voice_style", style),
    )

    print("[3/5] Downloading scene videos...")

    scene_paths = download_scene_videos(plan["scenes"])

    print("[4/5] Rendering video...")

    # Temporary bridge to your existing renderer.
    # We will replace this with the final v2 editor next.
    from make_video import make_final_video

    output_path = OUTPUT_DIR / f"{filename}.mp4"

    make_final_video(
        script=plan["script"],
        audio_path=audio_path,
        video_paths=scene_paths,
        output_path=output_path,
    )

    print("[5/5] Completed.")

    result = {
        "video_path": str(output_path),
        "metadata_path": str(metadata_path),
        "title": title,
        "description": plan["description"],
        "hashtags": plan["hashtags"],
        "thumbnail_text": plan["thumbnail_text"],
    }

    print("\nVideo:", output_path)
    print("Title:", title)
    print("Hashtags:", " ".join(f"#{x}" for x in plan["hashtags"]))

    return result