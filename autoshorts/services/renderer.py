"""
AutoShorts Engine — Video Renderer.

Produces a professional 1080×1920 MP4 YouTube Short from:
  - Background stock video clips
  - AI-generated narration (MP3)
  - Animated word-level subtitles (TikTok/Shorts style)
  - Optional background music
  - Zoom / motion effects
  - Smooth cross-fade transitions between clips

Public API
----------
render_short(script, audio_path, video_paths, output_path, bg_music_path) -> None

Note on 'Proc not detected':
  This is a cosmetic MoviePy 2.x / proglog warning on Windows where the
  ffmpeg process monitor cannot find the subprocess handle. It does NOT
  affect output quality. We suppress it via contextlib.redirect_stdout.
"""
from __future__ import annotations

import contextlib
import io
import random
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

from config import (
    FONT_PATH,
    MUSIC_DIR,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)
from autoshorts.services.logging_setup import get_logger

log = get_logger("renderer")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUBTITLE_COLOR       = "white"
SUBTITLE_STROKE      = "black"
WORDS_PER_CHUNK      = 6             # words per subtitle card
MIN_CHUNK_DURATION   = 0.6           # seconds

# Dynamically scaled subtitles relative to dimensions
SUBTITLE_FONT_SIZE   = int(42 * (VIDEO_WIDTH / 720))
SUBTITLE_STROKE_W    = int(3 * (VIDEO_WIDTH / 720))
SUBTITLE_Y_POS       = int(VIDEO_HEIGHT * 0.75)      # pixels from top
SUBTITLE_WIDTH       = int(VIDEO_WIDTH * 0.85)       # text box width in pixels

# Colour palette for highlighted words (TikTok style)
_HIGHLIGHT_COLORS = ["#FFFF00", "#FF6B6B", "#4ECDC4", "#FFE66D", "#A8E6CF"]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _fit_vertical(clip: VideoFileClip, clips_to_close: list) -> VideoFileClip:
    """Resize and centre-crop a clip to exactly VIDEO_WIDTH × VIDEO_HEIGHT."""
    target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT
    clip_ratio   = clip.w / clip.h

    if clip_ratio > target_ratio:
        resized = clip.resized(height=VIDEO_HEIGHT)
    else:
        resized = clip.resized(width=VIDEO_WIDTH)
    clips_to_close.append(resized)

    cropped = resized.cropped(
        x_center=resized.w / 2,
        y_center=resized.h / 2,
        width=VIDEO_WIDTH,
        height=VIDEO_HEIGHT,
    )
    clips_to_close.append(cropped)
    return cropped


def _apply_zoom(clip: VideoFileClip, zoom_factor: float = 1.04) -> VideoFileClip:
    """Apply a slow Ken Burns zoom-in effect."""
    def zoom(t: float) -> VideoFileClip:
        scale = 1 + (zoom_factor - 1) * (t / max(clip.duration, 0.001))
        new_w = int(clip.w * scale)
        new_h = int(clip.h * scale)
        resized = clip.resized(width=new_w)
        x_center = resized.w / 2
        y_center = resized.h / 2
        return resized.cropped(
            x_center=x_center,
            y_center=y_center,
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
        )

    # Use a simpler approach: pre-scale the clip slightly
    # (full dynamic zoom requires per-frame transforms which are slow)
    return clip.resized(lambda t: 1 + 0.03 * (t / max(clip.duration, 1)))


# ---------------------------------------------------------------------------
# Background assembly
# ---------------------------------------------------------------------------

def _build_background(
    video_paths: list[Path],
    required_duration: float,
    clips_to_close: list,
) -> VideoFileClip:
    """
    Assemble stock clips into one background track matching required_duration.

    Clips are looped if necessary. Each clip gets a subtle zoom effect and
    cross-dissolve transitions (1 second).
    """
    if not video_paths:
        raise RuntimeError("No video clips provided to renderer.")

    opened: list[VideoFileClip] = []

    for path in video_paths:
        try:
            clip = VideoFileClip(str(path)).without_audio()
            opened.append(clip)
            clips_to_close.append(clip)
        except Exception as exc:
            log.warning("Could not open clip %s: %s", path.name, exc)

    if not opened:
        raise RuntimeError("All video clips failed to open.")

    # Limit clips to 3 max — each open VideoFileClip holds frames in RAM
    # On free Render (512MB), more than 3 clips causes OOM
    opened = opened[:3]

    segment_duration = max(3.0, required_duration / len(opened))
    segments: list[VideoFileClip] = []
    current = 0.0
    idx = 0

    while current < required_duration:
        source = opened[idx % len(opened)]
        remaining = required_duration - current
        use_dur   = min(segment_duration, remaining)

        if source.duration >= use_dur:
            seg = source.subclipped(0, use_dur)
            clips_to_close.append(seg)
        else:
            repeats = int(use_dur // source.duration) + 1
            repeated = concatenate_videoclips(
                [source] * repeats, method="chain"
            )
            clips_to_close.append(repeated)
            seg = repeated.subclipped(0, use_dur)
            clips_to_close.append(seg)

        seg = _fit_vertical(seg, clips_to_close)
        # NOTE: zoom effect disabled on free tier to save memory
        # (each zoom call creates extra resized frame buffers)
        segments.append(seg)
        current += use_dur
        idx += 1

    background = concatenate_videoclips(segments, method="chain")
    clips_to_close.append(background)

    return background.with_duration(required_duration)


# ---------------------------------------------------------------------------
# Subtitle engine (word-level TikTok style)
# ---------------------------------------------------------------------------

def _chunk_script(
    script: str,
    total_duration: float,
) -> list[tuple[float, float, str]]:
    """
    Split script into fixed-size word chunks with estimated timing.
    Returns list of (start, end, text) tuples.
    """
    words = script.split()
    if not words:
        return []

    chunks: list[list[str]] = []
    for i in range(0, len(words), WORDS_PER_CHUNK):
        chunks.append(words[i : i + WORDS_PER_CHUNK])

    total_words = len(words)
    result: list[tuple[float, float, str]] = []
    current = 0.0

    for chunk in chunks:
        proportion = len(chunk) / total_words
        dur  = max(MIN_CHUNK_DURATION, total_duration * proportion)
        start = current
        end   = min(total_duration, current + dur)
        result.append((start, end, " ".join(chunk)))
        current = end

    # Fix last chunk to cover exactly to end
    if result:
        s, _, t = result[-1]
        result[-1] = (s, total_duration, t)

    return result


def _build_subtitle_clips(
    script: str,
    total_duration: float,
    clips_to_close: list,
) -> list[TextClip]:
    """
    Build a list of styled TextClip subtitle cards.

    Uses white text with black stroke for maximum readability on any background.
    """
    font = FONT_PATH
    from pathlib import Path as _Path

    if not _Path(font).exists():
        # Fallback: try common Linux/Mac fonts
        for fallback in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                         "/System/Library/Fonts/Helvetica.ttc"):
            if _Path(fallback).exists():
                font = fallback
                break
        else:
            log.warning("Font not found: %s — subtitles may not render", FONT_PATH)

    chunks = _chunk_script(script, total_duration)
    clips: list[TextClip] = []

    for start, end, text in chunks:
        try:
            tc = (
                TextClip(
                    font=font,
                    text=text,
                    font_size=SUBTITLE_FONT_SIZE,
                    color=SUBTITLE_COLOR,
                    stroke_color=SUBTITLE_STROKE,
                    stroke_width=SUBTITLE_STROKE_W,
                    method="caption",
                    size=(SUBTITLE_WIDTH, None),
                    text_align="center",
                )
                .with_start(start)
                .with_duration(end - start)
                .with_position(("center", SUBTITLE_Y_POS))
            )
            clips_to_close.append(tc)
            clips.append(tc)
        except Exception as exc:
            log.warning("Subtitle clip failed for '%s': %s", text[:20], exc)

    return clips


# ---------------------------------------------------------------------------
# Background music
# ---------------------------------------------------------------------------

def _find_background_music() -> Path | None:
    """Return a random music file from the music/ folder, or None."""
    music_files = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))

    if not music_files:
        return None

    return random.choice(music_files)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_short(
    script: str,
    audio_path: Path,
    video_paths: list[Path],
    output_path: Path,
    bg_music_path: Path | None = None,
) -> None:
    """
    Compose and export the final Short video.

    Parameters
    ----------
    script        : Narration text (used for subtitle generation).
    audio_path    : Pre-generated MP3 narration.
    video_paths   : List of background clip paths.
    output_path   : Where to write the final MP4.
    bg_music_path : Optional background music track.
    """
    log.info("Rendering short video → %s", output_path.name)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    narration = AudioFileClip(str(audio_path))
    total_duration = narration.duration

    log.info("Narration duration: %.2f seconds", total_duration)

    clips_to_close = [narration]
    background = None
    subtitles: list[TextClip] = []
    final = None

    try:
        # 1 — Background
        background = _build_background(video_paths, total_duration, clips_to_close)

        # 2 — Subtitles
        subtitles = _build_subtitle_clips(script, total_duration, clips_to_close)

        # 3 — Composite
        layers = [background, *subtitles]

        final = CompositeVideoClip(
            layers,
            size=(VIDEO_WIDTH, VIDEO_HEIGHT),
        ).with_audio(narration)
        clips_to_close.append(final)

        # 4 — Optional background music (ducked to 10% volume)
        if bg_music_path is None:
            bg_music_path = _find_background_music()

        if bg_music_path and bg_music_path.exists():
            try:
                music = (
                    AudioFileClip(str(bg_music_path))
                    .subclipped(0, total_duration)
                    .with_volume_scaled(0.08)
                )
                clips_to_close.append(music)
                from moviepy import CompositeAudioClip
                comp_audio = CompositeAudioClip([narration, music])
                clips_to_close.append(comp_audio)
                
                final = final.with_audio(comp_audio)
                clips_to_close.append(final)
                log.info("Background music added: %s", bg_music_path.name)
            except Exception as exc:
                log.warning("Background music failed (skipping): %s", exc)

        # 5 — Export
        # Wrap in stdout redirect to suppress MoviePy 2.x 'Proc not detected'
        # noise. This is a cosmetic proglog/ffmpeg process-monitor bug on Windows
        # and does not affect the output video in any way.
        log.info("Encoding video…")
        _suppressed = io.StringIO()
        with contextlib.redirect_stdout(_suppressed):
            final.write_videofile(
                str(output_path),
                fps=VIDEO_FPS,
                codec="libx264",
                audio_codec="aac",
                preset="ultrafast",   # fastest encode = lowest peak RAM usage
                threads=1,
                logger=None,
                bitrate="1200k",      # lower bitrate = less memory during encode
            )

        # Forward any non-trivial suppressed output to debug log
        _captured = _suppressed.getvalue().strip()
        if _captured and "proc not detected" not in _captured.lower():
            log.debug("MoviePy stdout: %s", _captured[:500])

        log.info(
            "Render complete: %s (%.1f MB)",
            output_path.name,
            output_path.stat().st_size / (1024 * 1024),
        )

    finally:
        log.info("Closing %d video and audio clips to release memory...", len(clips_to_close))
        for clip in clips_to_close:
            try:
                clip.close()
            except Exception:
                pass
        
        # Explicit garbage collection to free memory on 512MB RAM server
        import gc
        gc.collect()
