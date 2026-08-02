"""
AutoShorts Engine — FFmpeg-based Video Renderer (LOW MEMORY).

Replaces MoviePy completely. Uses ffmpeg subprocess directly.
Peak RAM: ~80 MB  (vs ~500 MB with MoviePy — fixes OOM on Render free tier).

Public API is identical to the old renderer:
    render_short(script, audio_path, video_paths, output_path, bg_music_path)
"""

from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from config import MUSIC_DIR, VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH
from autoshorts.services.logging_setup import get_logger

log = get_logger("renderer")

FFMPEG  = "ffmpeg"
FFPROBE = "ffprobe"

WORDS_PER_CHUNK = 5      # subtitle words per card
SUBTITLE_FONT_SIZE = 48
SUBTITLE_Y_RATIO   = 0.75   # vertical position (fraction of height)


# ---------------------------------------------------------------------------
# Font detection (Windows dev + Linux/Render prod)
# ---------------------------------------------------------------------------

def _find_font() -> str:
    """Return absolute path to a bold font, searching common locations."""
    candidates = [
        # Linux (Render / Ubuntu)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        # Windows (local dev)
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    env_font = os.environ.get("FONT_PATH", "").strip()
    if env_font:
        candidates.insert(0, env_font)

    for path in candidates:
        if os.path.exists(path):
            return path

    # ffmpeg drawtext can work without fontfile on many systems
    return ""


# ---------------------------------------------------------------------------
# Duration helper
# ---------------------------------------------------------------------------

def _get_duration(path: Path) -> float:
    """Return duration in seconds using ffprobe."""
    cmd = [
        FFPROBE, "-v", "quiet",
        "-print_format", "json",
        "-show_streams", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path.name}: {result.stderr[:300]}")

    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        dur = stream.get("duration")
        if dur:
            return float(dur)
    raise RuntimeError(f"Could not determine duration of {path.name}")


# ---------------------------------------------------------------------------
# Subtitle generation (ffmpeg drawtext filter chains)
# ---------------------------------------------------------------------------

def _build_subtitle_filter(script: str, duration: float, font_path: str) -> str:
    """
    Build a chained ffmpeg drawtext filter string for word-level subtitles.
    Each chunk of WORDS_PER_CHUNK words is shown for its time slice.
    No ImageMagick, no PIL, no RAM — pure ffmpeg text rendering.
    """
    words = script.strip().split()
    if not words:
        return "null"   # no-op filter

    # Split into chunks
    chunks = [
        " ".join(words[i:i + WORDS_PER_CHUNK])
        for i in range(0, len(words), WORDS_PER_CHUNK)
    ]
    n = len(chunks)
    slice_dur = duration / n

    y_pos = int(VIDEO_HEIGHT * SUBTITLE_Y_RATIO)

    # Escape text for ffmpeg (colons, apostrophes, backslashes)
    def escape(text: str) -> str:
        return (
            text
            .replace("\\", "\\\\")
            .replace("'",  "\u2019")    # replace smart apostrophe — avoids quoting hell
            .replace(":",  r"\:")
            .replace("%",  r"\%")
        )

    font_arg = f":fontfile='{font_path}'" if font_path else ""

    parts = []
    for i, chunk in enumerate(chunks):
        t_start = i * slice_dur
        t_end   = (i + 1) * slice_dur
        text    = escape(chunk)

        dt = (
            f"drawtext="
            f"text='{text}'"
            f"{font_arg}"
            f":fontsize={SUBTITLE_FONT_SIZE}"
            f":fontcolor=white"
            f":bordercolor=black"
            f":borderw=3"
            f":x=(w-text_w)/2"
            f":y={y_pos}"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )
        parts.append(dt)

    # Chain all drawtext filters: [vin]dt1,dt2,dt3[vout]
    return ",".join(parts)


# ---------------------------------------------------------------------------
# Background music helper
# ---------------------------------------------------------------------------

def _find_background_music() -> Path | None:
    """Find a random MP3 in the music directory."""
    import random
    music_files = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.m4a"))
    return random.choice(music_files) if music_files else None


# ---------------------------------------------------------------------------
# Main render function (public API — same signature as old renderer)
# ---------------------------------------------------------------------------

def render_short(
    script:        str,
    audio_path:    Path,
    video_paths:   list[Path],
    output_path:   Path,
    bg_music_path: Path | None = None,
) -> None:
    """
    Render a YouTube Short using ffmpeg subprocess.
    Uses ~80 MB peak RAM — safe on Render free tier (512 MB limit).

    Parameters
    ----------
    script        : Narration text (used to generate subtitles).
    audio_path    : Pre-generated MP3 narration.
    video_paths   : List of background stock video clip paths.
    output_path   : Where to write the final MP4.
    bg_music_path : Optional background music track.
    """
    gc.collect()   # free memory before heavy work

    log.info("Rendering short (ffmpeg) → %s", output_path.name)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not video_paths:
        raise RuntimeError("No video clips provided to renderer.")

    duration  = _get_duration(audio_path)
    font_path = _find_font()
    log.info("Narration duration: %.2f s | Font: %s", duration, font_path or "(system default)")

    # Limit to 3 clips maximum to keep RAM low
    clips = video_paths[:3]
    n     = len(clips)

    # ── Build ffmpeg inputs ──────────────────────────────────────────────────
    # Use -stream_loop -1 on each clip so short clips can be looped
    cmd_inputs: list[str] = []
    for clip_path in clips:
        cmd_inputs += ["-stream_loop", "-1", "-t", str(duration), "-i", str(clip_path)]

    narration_idx = n          # index of narration audio input
    cmd_inputs   += ["-i", str(audio_path)]

    music_idx = None
    if bg_music_path is None:
        bg_music_path = _find_background_music()
    if bg_music_path and bg_music_path.exists():
        music_idx = n + 1
        cmd_inputs += ["-i", str(bg_music_path)]

    # ── Build filter_complex ─────────────────────────────────────────────────
    filter_parts: list[str] = []

    # Scale + crop each clip to 720×1280
    for i in range(n):
        filter_parts.append(
            f"[{i}:v]"
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"setsar=1"
            f"[sv{i}]"
        )

    # Concat clips
    concat_inputs = "".join(f"[sv{i}]" for i in range(n))
    if n > 1:
        filter_parts.append(
            f"{concat_inputs}concat=n={n}:v=1:a=0[vcat]"
        )
        vcat = "[vcat]"
    else:
        vcat = "[sv0]"

    # Add subtitles via drawtext chains
    subtitle_chain = _build_subtitle_filter(script, duration, font_path)
    filter_parts.append(f"{vcat}{subtitle_chain}[vfinal]")

    # Audio: mix narration + optional music
    if music_idx is not None:
        filter_parts.append(
            f"[{narration_idx}:a]volume=1.0[narr];"
            f"[{music_idx}:a]volume=0.07,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[music];"
            f"[narr][music]amix=inputs=2:duration=first[afinal]"
        )
        audio_map = "[afinal]"
    else:
        audio_map = f"{narration_idx}:a"

    filter_complex = ";".join(filter_parts)

    # ── Assemble full ffmpeg command ─────────────────────────────────────────
    cmd = [
        FFMPEG, "-y",
        *cmd_inputs,
        "-filter_complex", filter_complex,
        "-map", "[vfinal]",
        "-map", audio_map,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "ultrafast",   # fastest = lowest peak RAM
        "-crf", "28",             # decent quality, small file
        "-r", str(VIDEO_FPS),
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    log.info("Running ffmpeg (memory-efficient render)…")
    log.debug("CMD: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,   # 5 minute timeout
    )

    if result.returncode != 0:
        err = (result.stderr or "")[-1500:]
        raise RuntimeError(f"ffmpeg render failed:\n{err}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    log.info("Render complete: %s (%.1f MB)", output_path.name, size_mb)

    gc.collect()
