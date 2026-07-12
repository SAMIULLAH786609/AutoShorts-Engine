import asyncio
import json
import os
import re
import shutil 
from pathlib import Path
from typing import Any

import edge_tts
import requests
from dotenv import load_dotenv
from google import genai
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

# -----------------------------
# Project configuration
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
OUTPUT_DIR = BASE_DIR / "output"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30
VOICE = "en-US-AriaNeural"
GEMINI_MODEL = "gemini-3.5-flash"

# Windows font path. Change it if Arial is not available.
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()


def prepare_folders() -> None:
    """Create clean working folders."""
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    for item in DOWNLOAD_DIR.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def validate_keys() -> None:
    """Stop early when required API keys are missing."""
    missing = []

    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")

    if not PEXELS_API_KEY:
        missing.append("PEXELS_API_KEY")

    if missing:
        raise RuntimeError(
            "Missing API key(s): "
            + ", ".join(missing)
            + "\nCreate a .env file and add the required keys."
        )


def clean_json_response(text: str) -> str:
    """Remove Markdown code fences that an AI model may return."""
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_video_plan(topic: str) -> dict[str, Any]:
    """Use Gemini to create a highly engaging script and visual keywords."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
You are an expert short-form video writer for YouTube Shorts,
Instagram Reels and TikTok.

USER TOPIC:
{topic}

First identify the content style from the topic.

Possible styles:
- funny/comedy
- facts
- motivational
- scary
- educational
- technology
- animals
- storytelling

If the topic contains words such as funny, comedy, hilarious, joke,
meme or entertainment, you MUST create genuinely funny content.

For funny content:
- Use a relatable everyday situation.
- Include a clear comedic setup.
- Add exaggeration, surprise and a punchline.
- Use short sentences suitable for voice narration.
- Avoid explaining scientific facts unless specifically requested.
- Do not write forced or childish jokes.
- Make the humour visual so relevant stock clips can be used.
- End with a funny final line.
- The script must feel like an original comedy short, not an article.

For all other content:
- Start with a strong hook in the first sentence.
- Maintain curiosity throughout the script.
- Use a pattern interrupt every 2 to 3 sentences.
- End with a memorable conclusion.

Return ONLY valid JSON in this exact structure:

{{
  "title": "clickable title under 55 characters",
  "hook": "first attention-grabbing sentence",
  "script": "natural narration between 90 and 125 words",
  "keywords": [
    "visual search phrase 1",
    "visual search phrase 2",
    "visual search phrase 3",
    "visual search phrase 4",
    "visual search phrase 5"
  ],
  "description": "short YouTube description",
  "hashtags": ["hashtag1", "hashtag2", "hashtag3", "shorts"],
  "category": "detected content style"
}}

Important rules:
- Script must be original.
- Do not copy known jokes, movies, creators or viral scripts.
- Do not mention that AI generated the content.
- Do not use headings inside the narration.
- Do not include stage directions.
- Keywords must describe visible scenes, people, animals, places or actions.
- Keywords must match each part of the script.
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")

    raw_json = clean_json_response(response.text)

    try:
        plan = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Gemini did not return valid JSON.\n\nReceived:\n" + raw_json
        ) from exc

    script = str(plan.get("script", "")).strip()
    keywords = plan.get("keywords", [])

    if not script:
        raise RuntimeError("Gemini response did not contain a script.")

    if not isinstance(keywords, list) or not keywords:
        raise RuntimeError("Gemini response did not contain keywords.")

    plan["keywords"] = [
        str(keyword).strip()
        for keyword in keywords
        if str(keyword).strip()
    ][:5]

    return plan
async def generate_voice(script: str, output_path: Path) -> None:
    """Convert narration text to an MP3 file."""
    communicate = edge_tts.Communicate(
        text=script,
        voice=VOICE,
        rate="+5%",
    )
    await communicate.save(str(output_path))


def choose_best_video_file(video: dict[str, Any]) -> str | None:
    """Select a reasonable portrait or HD MP4 file from one Pexels result."""
    files = video.get("video_files", [])

    mp4_files = [
        item
        for item in files
        if item.get("file_type") == "video/mp4" and item.get("link")
    ]

    if not mp4_files:
        return None

    portrait_files = [
        item
        for item in mp4_files
        if (item.get("height") or 0) > (item.get("width") or 0)
    ]

    candidates = portrait_files or mp4_files

    # Avoid extremely large downloads while still preferring useful quality.
    candidates.sort(
        key=lambda item: abs((item.get("height") or 720) - 1280)
    )

    return candidates[0].get("link")


def search_pexels_video(keyword: str) -> str | None:
    """Search Pexels and return a downloadable video URL."""
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": keyword,
        "orientation": "portrait",
        "size": "medium",
        "per_page": 8,
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    videos = response.json().get("videos", [])

    for video in videos:
        selected = choose_best_video_file(video)
        if selected:
            return selected

    return None


def download_file(url: str, output_path: Path) -> None:
    """Download a file in chunks."""
    with requests.get(url, stream=True, timeout=90) as response:
        response.raise_for_status()

        with output_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)


def download_background_videos(keywords: list[str]) -> list[Path]:
    """Download one background video for each Gemini keyword."""
    paths: list[Path] = []

    for index, keyword in enumerate(keywords, start=1):
        print(f"[Pexels] Searching: {keyword}")

        try:
            video_url = search_pexels_video(keyword)
        except requests.RequestException as exc:
            print(f"  Search failed: {exc}")
            continue

        if not video_url:
            print("  No usable video found.")
            continue

        output_path = DOWNLOAD_DIR / f"clip_{index}.mp4"

        try:
            download_file(video_url, output_path)
            paths.append(output_path)
            print(f"  Downloaded: {output_path.name}")
        except requests.RequestException as exc:
            print(f"  Download failed: {exc}")

    if not paths:
        raise RuntimeError(
            "No Pexels videos were downloaded. "
            "Check your API key, internet connection, or try another topic."
        )

    return paths


def fit_vertical(clip: VideoFileClip) -> VideoFileClip:
    """Resize and crop a video to fill 1080x1920."""
    target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT
    clip_ratio = clip.w / clip.h

    if clip_ratio > target_ratio:
        # Video is too wide: match height, then crop width.
        resized = clip.resized(height=VIDEO_HEIGHT)
    else:
        # Video is too narrow: match width, then crop height.
        resized = clip.resized(width=VIDEO_WIDTH)

    return resized.cropped(
        x_center=resized.w / 2,
        y_center=resized.h / 2,
        width=VIDEO_WIDTH,
        height=VIDEO_HEIGHT,
    )


def build_background(
    video_paths: list[Path],
    required_duration: float,
) -> VideoFileClip:
    """Join enough stock-video segments to cover the narration."""
    opened_clips: list[VideoFileClip] = []
    final_segments: list[VideoFileClip] = []

    try:
        for path in video_paths:
            opened_clips.append(VideoFileClip(str(path)).without_audio())

        if not opened_clips:
            raise RuntimeError("No valid video clips could be opened.")

        segment_duration = max(3.0, required_duration / len(opened_clips))
        current_duration = 0.0
        index = 0

        while current_duration < required_duration:
            source = opened_clips[index % len(opened_clips)]
            remaining = required_duration - current_duration
            use_duration = min(segment_duration, remaining)

            if source.duration >= use_duration:
                segment = source.subclipped(0, use_duration)
            else:
                repeats = int(use_duration // source.duration) + 1
                repeated = concatenate_videoclips(
                    [source] * repeats,
                    method="compose",
                )
                segment = repeated.subclipped(0, use_duration)

            final_segments.append(fit_vertical(segment))
            current_duration += use_duration
            index += 1

        background = concatenate_videoclips(
            final_segments,
            method="compose",
        ).with_duration(required_duration)

        return background

    except Exception:
        for clip in final_segments:
            try:
                clip.close()
            except Exception:
                pass

        for clip in opened_clips:
            try:
                clip.close()
            except Exception:
                pass

        raise


def split_script_for_subtitles(
    script: str,
    total_duration: float,
) -> list[tuple[float, float, str]]:
    """Create estimated subtitle timing based on word count."""
    words = script.split()

    if not words:
        return []

    chunks: list[list[str]] = []
    chunk_size = 7

    for index in range(0, len(words), chunk_size):
        chunks.append(words[index:index + chunk_size])

    total_words = len(words)
    subtitles: list[tuple[float, float, str]] = []
    current_time = 0.0

    for chunk in chunks:
        duration = total_duration * (len(chunk) / total_words)
        start = current_time
        end = min(total_duration, current_time + duration)
        text = " ".join(chunk)

        subtitles.append((start, end, text))
        current_time = end

    if subtitles:
        start, _, text = subtitles[-1]
        subtitles[-1] = (start, total_duration, text)

    return subtitles


def create_subtitle_clips(
    script: str,
    total_duration: float,
) -> list[TextClip]:
    """Create styled subtitle clips near the bottom of the video."""
    if not Path(FONT_PATH).exists():
        raise FileNotFoundError(
            f"Font not found: {FONT_PATH}\n"
            "Update FONT_PATH in make_video.py."
        )

    subtitle_items = split_script_for_subtitles(script, total_duration)
    clips: list[TextClip] = []

    for start, end, text in subtitle_items:
        subtitle = (
            TextClip(
                font=FONT_PATH,
                text=text,
                font_size=64,
                color="white",
                stroke_color="black",
                stroke_width=5,
                method="caption",
                size=(920, None),
                text_align="center",
            )
            .with_start(start)
            .with_duration(end - start)
            .with_position(("center", 1450))
        )
        clips.append(subtitle)

    return clips


def make_final_video(
    script: str,
    audio_path: Path,
    video_paths: list[Path],
    output_path: Path,
) -> None:
    """Compose background, narration, and subtitles into an MP4."""
    audio = AudioFileClip(str(audio_path))
    background = None
    final = None
    subtitles: list[TextClip] = []

    try:
        duration = audio.duration
        background = build_background(video_paths, duration)
        subtitles = create_subtitle_clips(script, duration)

        final = CompositeVideoClip(
            [background, *subtitles],
            size=(VIDEO_WIDTH, VIDEO_HEIGHT),
        ).with_audio(audio)

        final.write_videofile(
            str(output_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4,
        )

    finally:
        if final is not None:
            final.close()

        if background is not None:
            background.close()

        for subtitle in subtitles:
            subtitle.close()

        audio.close()


def safe_filename(text: str) -> str:
    """Turn a title into a Windows-safe filename."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "", text)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return cleaned[:60] or "autoshort"


def main() -> None:
    print("\n=== AutoShorts Engine ===\n")

    validate_keys()
    prepare_folders()

    topic = input("Enter video topic: ").strip()

    if not topic:
        raise ValueError("Topic cannot be empty.")

    print("\n[1/4] Creating script with Gemini...")
    plan = generate_video_plan(topic)

    title = str(plan.get("title", topic)).strip()
    script = str(plan["script"]).strip()
    keywords = plan["keywords"]

    print("\nTitle:", title)
    print("\nScript:\n", script)
    print("\nVisual keywords:", ", ".join(keywords))

    script_path = OUTPUT_DIR / f"{safe_filename(title)}_script.txt"
    script_path.write_text(script, encoding="utf-8")

    print("\n[2/4] Generating AI voice...")
    audio_path = DOWNLOAD_DIR / "voice.mp3"
    asyncio.run(generate_voice(script, audio_path))

    print("\n[3/4] Downloading background videos...")
    video_paths = download_background_videos(keywords)

    print("\n[4/4] Rendering final video...")
    output_path = OUTPUT_DIR / f"{safe_filename(title)}.mp4"
    make_final_video(
        script=script,
        audio_path=audio_path,
        video_paths=video_paths,
        output_path=output_path,
    )

    print("\nSUCCESS!")
    print("Video:", output_path)
    print("Script:", script_path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
    except Exception as error:
        print("\nERROR:", error)
