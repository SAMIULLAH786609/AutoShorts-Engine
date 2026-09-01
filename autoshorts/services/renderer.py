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

import re
import shutil

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

WORDS_PER_CHUNK = 3      # subtitle words per card (short = higher retention)
SUBTITLE_FONT_SIZE = 58  # big & bold, but safe against edge-clipping on 720px (no auto-wrap)
SUBTITLE_Y_RATIO   = 0.66   # vertical position (fraction of height)


def _find_ffmpeg() -> str:
    """Return path to ffmpeg executable (system PATH or imageio_ffmpeg)."""
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    if imageio_ffmpeg is not None:
        try:
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if os.path.exists(exe):
                return exe
        except Exception:
            pass
    return "ffmpeg"


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
    """Return duration in seconds using ffprobe or ffmpeg fallback."""
    ffprobe_exe = shutil.which("ffprobe")
    if ffprobe_exe:
        cmd = [
            ffprobe_exe, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", str(path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for stream in data.get("streams", []):
                    dur = stream.get("duration")
                    if dur:
                        return float(dur)
        except Exception:
            pass

    # Fallback: parse ffmpeg -i output for Duration
    ffmpeg_exe = _find_ffmpeg()
    cmd = [ffmpeg_exe, "-i", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr or "")
    if match:
        hours, minutes, seconds = match.groups()
        return float(hours) * 3600 + float(minutes) * 60 + float(seconds)

    raise RuntimeError(f"Could not determine duration of {path.name}")


# ---------------------------------------------------------------------------
# Subtitle generation (ffmpeg drawtext filter chains)
# ---------------------------------------------------------------------------

def _card_timings(
    script: str,
    duration: float,
    word_timings: list[dict] | None,
) -> list[tuple[str, float, float]]:
    """
    Return a list of (text, t_start, t_end) caption cards.

    If real per-word timings are available (from Edge-TTS WordBoundary events)
    the cards are synced to the actual narration. Otherwise we fall back to an
    even split across the audio duration.
    """
    words = script.strip().split()
    if not words:
        return []

    # ---- Preferred path: real word timings ---------------------------------
    if word_timings:
        cards: list[tuple[str, float, float]] = []
        group: list[dict] = []
        for w in word_timings:
            group.append(w)
            if len(group) >= WORDS_PER_CHUNK:
                text = " ".join(g["word"] for g in group).strip()
                cards.append((text, group[0]["start"], group[-1]["end"]))
                group = []
        if group:
            text = " ".join(g["word"] for g in group).strip()
            cards.append((text, group[0]["start"], group[-1]["end"]))

        # Stretch each card's end to the next card's start so there is never a
        # blank gap, and clamp the last card to the audio duration.
        fixed: list[tuple[str, float, float]] = []
        for i, (text, ts, te) in enumerate(cards):
            next_start = cards[i + 1][1] if i + 1 < len(cards) else duration
            fixed.append((text, max(0.0, ts), max(te, next_start)))
        if fixed:
            last = fixed[-1]
            fixed[-1] = (last[0], last[1], duration)
        return fixed

    # ---- Fallback: even split --------------------------------------------------
    chunks = [
        " ".join(words[i:i + WORDS_PER_CHUNK])
        for i in range(0, len(words), WORDS_PER_CHUNK)
    ]
    slice_dur = duration / len(chunks)
    return [
        (chunk, i * slice_dur, (i + 1) * slice_dur)
        for i, chunk in enumerate(chunks)
    ]


def _build_subtitle_filter(
    script: str,
    duration: float,
    font_path: str,
    word_timings: list[dict] | None = None,
) -> str:
    """
    Build a chained ffmpeg drawtext filter string for word-level subtitles.
    Cards are synced to real narration timing when available.
    No ImageMagick, no PIL, no RAM — pure ffmpeg text rendering.
    """
    cards = _card_timings(script, duration, word_timings)
    if not cards:
        return "null"   # no-op filter

    y_pos = int(VIDEO_HEIGHT * SUBTITLE_Y_RATIO)

    # Normalize smart/typographic punctuation to plain ASCII. Non-ASCII text
    # (e.g. a curly apostrophe) gets mangled when it crosses the Windows
    # subprocess -> ffmpeg.exe command-line boundary (codepage mojibake),
    # which then breaks ffmpeg's filter_complex parser entirely.
    _PUNCT_MAP = str.maketrans({
        "‘": "'", "’": "'",
        "“": '"', "”": '"',
        "–": "-", "—": "-",
        "…": "...",
    })

    # Escape text for ffmpeg (colons, apostrophes, backslashes)
    def escape(text: str) -> str:
        text = text.translate(_PUNCT_MAP)
        text = text.encode("ascii", "ignore").decode("ascii")
        text = text.replace("\\", "\\\\")
        text = text.replace(":", r"\:")
        text = text.replace("%", r"\%")
        # Escape a literal single quote inside the single-quoted drawtext
        # value using ffmpeg's close-quote/escape/reopen-quote trick.
        text = text.replace("'", "'\\''")
        return text

    # Bug 5 fixed: On Windows, font_path contains backslashes (e.g. C:\Windows\Fonts\arialbd.ttf).
    # ffmpeg's filter_complex parser requires:
    #   1. Backslashes doubled first:  C:\W...  →  C:\\W...
    #   2. Colons escaped after:       C:\\W...  →  C\\:\W...  (wrong order breaks it)
    # CORRECT order: escape backslashes FIRST, then colons.
    if font_path:
        escaped_font_path = font_path.replace("\\", "\\\\").replace(":", r"\:")
    else:
        escaped_font_path = ""
    font_arg = f":fontfile='{escaped_font_path}'" if escaped_font_path else ""

    parts = []
    for text_raw, t_start, t_end in cards:
        text = escape(text_raw.upper())   # ALL-CAPS reads better on Shorts

        dt = (
            f"drawtext="
            f"text='{text}'"
            f"{font_arg}"
            f":fontsize={SUBTITLE_FONT_SIZE}"
            f":fontcolor=white"
            f":bordercolor=black"
            f":borderw=6"
            f":box=1"
            f":boxcolor=black@0.55"
            f":boxborderw=22"
            f":line_spacing=8"
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

    # Load per-word timings written by the voice service (foo_voice.words.json)
    # for narration-synced captions. Missing/corrupt file → even-split fallback.
    word_timings: list[dict] | None = None
    timing_path = audio_path.parent / (audio_path.stem + ".words.json")
    if timing_path.exists():
        try:
            word_timings = json.loads(timing_path.read_text(encoding="utf-8")) or None
            if word_timings:
                log.info("Using %d word timings for synced captions", len(word_timings))
        except Exception as exc:
            log.warning("Could not read word-timing file (%s) — using even split", exc)

    # Limit to 3 clips maximum to keep RAM low
    clips = video_paths[:3]
    n     = len(clips)
    clip_duration = duration / max(n, 1)

    # ── Build ffmpeg inputs ──────────────────────────────────────────────────
    # Loop each clip for its slice duration (duration / n) so all clips get equal screen time
    cmd_inputs: list[str] = []
    for clip_path in clips:
        cmd_inputs += ["-stream_loop", "-1", "-t", f"{clip_duration:.3f}", "-i", str(clip_path)]

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
    subtitle_chain = _build_subtitle_filter(script, duration, font_path, word_timings)
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
    ffmpeg_exe = _find_ffmpeg()
    cmd = [
        ffmpeg_exe, "-y",
        *cmd_inputs,
        "-filter_complex", filter_complex,
        "-map", "[vfinal]",
        "-map", audio_map,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "medium",    # Better quality than ultrafast — YouTube re-encodes anyway
        "-crf", "23",           # Higher quality (23 = good, 28 = noticeably blurry)
        "-r", str(VIDEO_FPS),
        "-pix_fmt", "yuv420p",  # Required for max device compatibility
        "-c:a", "aac",
        "-b:a", "192k",         # Better audio quality (192k vs 128k)
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


