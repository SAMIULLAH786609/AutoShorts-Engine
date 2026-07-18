"""
AutoShorts Engine — Thumbnail Generator.

Creates a branded, high-contrast thumbnail JPG using Pillow.

Design:
  - Dark gradient background overlay on a still frame from the video
  - Bold title text centred in the upper third
  - Accent colour bar at the bottom
  - Contrasting stroke around text for readability
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import FONT_PATH, THUMBNAIL_DIR, VIDEO_HEIGHT, VIDEO_WIDTH
from autoshorts.services.logging_setup import get_logger

log = get_logger("thumbnail_generator")

THUMBNAIL_WIDTH  = VIDEO_WIDTH
THUMBNAIL_HEIGHT = VIDEO_HEIGHT

# Accent colours cycle per video
_ACCENT_COLORS = [
    "#FF4757",   # red
    "#FFA502",   # orange
    "#2ED573",   # green
    "#1E90FF",   # blue
    "#FF6B81",   # pink
    "#ECCC68",   # yellow
    "#7BED9F",   # light green
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load the configured font or fall back to a default."""
    for path in (FONT_PATH, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue

    return ImageFont.load_default()


def _get_accent_color(title: str) -> str:
    idx = sum(ord(c) for c in title) % len(_ACCENT_COLORS)
    return _ACCENT_COLORS[idx]


def generate_thumbnail(
    title: str,
    thumbnail_text: str,
    output_path: Path | None = None,
    background_frame: Image.Image | None = None,
) -> Path:
    """
    Generate a thumbnail for the given title.

    Parameters
    ----------
    title           : Full video title (used for accent colour selection).
    thumbnail_text  : Short punchy text overlaid on the thumbnail (3–5 words).
    output_path     : Where to save the JPEG. Auto-generated if None.
    background_frame: Optional PIL Image to use as background. Uses solid dark
                      gradient if None.

    Returns the saved thumbnail path.
    """
    if output_path is None:
        safe = re.sub(r"[^\w\-]", "_", title)[:50]
        output_path = THUMBNAIL_DIR / f"thumb_{safe}.jpg"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    accent = _get_accent_color(title)

    # ── 1. Base image ───────────────────────────────────────────────────────
    if background_frame is not None:
        img = background_frame.resize(
            (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS
        ).convert("RGB")
    else:
        img = Image.new("RGB", (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), (15, 15, 25))

    draw = ImageDraw.Draw(img)

    # ── 2. Dark gradient overlay (top and bottom) ───────────────────────────
    overlay = Image.new("RGBA", (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), (0, 0, 0, 0))
    o_draw  = ImageDraw.Draw(overlay)

    # Top-to-middle gradient
    for y in range(THUMBNAIL_HEIGHT // 2):
        alpha = int(180 * (1 - y / (THUMBNAIL_HEIGHT / 2)))
        o_draw.line([(0, y), (THUMBNAIL_WIDTH, y)], fill=(0, 0, 0, alpha))

    # Bottom gradient for text area
    for y in range(THUMBNAIL_HEIGHT // 2, THUMBNAIL_HEIGHT):
        alpha = int(200 * ((y - THUMBNAIL_HEIGHT // 2) / (THUMBNAIL_HEIGHT // 2)))
        o_draw.line([(0, y), (THUMBNAIL_WIDTH, y)], fill=(0, 0, 0, alpha))

    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── 3. Accent bar at bottom ─────────────────────────────────────────────
    bar_h = 12
    draw.rectangle(
        [(0, THUMBNAIL_HEIGHT - bar_h), (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)],
        fill=accent,
    )

    # ── 4. Thumbnail text (large, centred, vertically centred) ──────────────
    thumb_font_size = 160
    thumb_font = _load_font(thumb_font_size)

    # Wrap text
    lines = textwrap.wrap(thumbnail_text.upper(), width=12)
    line_height = thumb_font_size + 20
    total_text_height = len(lines) * line_height
    start_y = (THUMBNAIL_HEIGHT - total_text_height) // 2 - 80

    for i, line in enumerate(lines):
        y = start_y + i * line_height

        # Stroke
        for dx in (-4, 0, 4):
            for dy in (-4, 0, 4):
                draw.text(
                    (THUMBNAIL_WIDTH // 2 + dx, y + dy),
                    line,
                    font=thumb_font,
                    fill=(0, 0, 0),
                    anchor="mm",
                )

        # Main text
        draw.text(
            (THUMBNAIL_WIDTH // 2, y),
            line,
            font=thumb_font,
            fill="white",
            anchor="mm",
        )

    # ── 5. Accent dot / icon at top ─────────────────────────────────────────
    draw.ellipse(
        [(THUMBNAIL_WIDTH // 2 - 8, 60), (THUMBNAIL_WIDTH // 2 + 8, 76)],
        fill=accent,
    )

    # ── 6. Small "SHORTS" label at top ─────────────────────────────────────
    label_font = _load_font(42)
    draw.text(
        (THUMBNAIL_WIDTH // 2, 110),
        "SHORTS",
        font=label_font,
        fill=accent,
        anchor="mm",
    )

    # ── 7. Save ─────────────────────────────────────────────────────────────
    img.save(str(output_path), "JPEG", quality=92, optimize=True)

    log.info("Thumbnail saved: %s", output_path.name)
    return output_path
