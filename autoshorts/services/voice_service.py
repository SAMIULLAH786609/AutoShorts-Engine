"""
AutoShorts Engine — AI Voice Service (Edge-TTS).

Generates MP3 narration from script text.
Supports English and Urdu voices with dynamic rate/pitch per style.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import edge_tts

from config import (
    VOICE_ENGLISH_FEMALE,
    VOICE_ENGLISH_MALE,
    VOICE_URDU_FEMALE,
    VOICE_URDU_MALE,
)
from autoshorts.services.logging_setup import get_logger

log = get_logger("voice_service")

# Style → (rate, pitch) tuning
_STYLE_PARAMS: dict[str, tuple[str, str]] = {
    "funny":       ("+15%", "+2Hz"),
    "energetic":   ("+12%", "+1Hz"),
    "motivational":("+10%", "+1Hz"),
    "facts":       ("+6%",  "+0Hz"),
    "educational": ("+4%",  "+0Hz"),
    "story":       ("+2%",  "-1Hz"),
    "serious":     ("-2%",  "-2Hz"),
    "emotional":   ("-5%",  "-1Hz"),
}

_DEFAULT_RATE  = "+6%"
_DEFAULT_PITCH = "+0Hz"


def choose_voice(language: str = "English", gender: str = "female") -> str:
    """Return the Edge-TTS voice ID for the given language and gender."""
    language = language.lower()
    gender   = gender.lower()

    if "urdu" in language or language == "ur":
        return VOICE_URDU_MALE if gender == "male" else VOICE_URDU_FEMALE

    return VOICE_ENGLISH_MALE if gender == "male" else VOICE_ENGLISH_FEMALE


async def _synthesize(
    text: str,
    output_path: Path,
    voice: str,
    style: str,
) -> list[dict]:
    """
    Internal async synthesizer.

    Streams the audio so we can also capture per-word timing (WordBoundary
    events). Returns a list of {"word", "start", "end"} dicts in seconds —
    used by the renderer for perfectly synced karaoke-style captions.
    """
    rate, pitch = _STYLE_PARAMS.get(style.lower(), (_DEFAULT_RATE, _DEFAULT_PITCH))

    communicator = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        boundary="WordBoundary",   # per-word timing for synced captions
    )

    words: list[dict] = []
    with open(output_path, "wb") as audio_file:
        async for chunk in communicator.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7          # 100ns ticks -> seconds
                dur   = chunk["duration"] / 1e7
                words.append({
                    "word":  chunk["text"],
                    "start": round(start, 3),
                    "end":   round(start + dur, 3),
                })

    return words


def generate_voice(
    text: str,
    output_path: Path,
    voice: str | None = None,
    language: str = "English",
    gender: str = "female",
    style: str = "facts",
) -> Path:
    """
    Generate an MP3 narration from text.

    Parameters
    ----------
    text        : The script to narrate.
    output_path : Where to save the MP3.
    voice       : Edge-TTS voice ID (overrides language/gender if given).
    language    : 'English' or 'Urdu' (used when voice is None).
    gender      : 'male' or 'female' (used when voice is None).
    style       : Content style for rate/pitch tuning.

    Returns the output path for chaining.
    """
    selected_voice = voice or choose_voice(language, gender)

    log.info(
        "Generating voice: %s | style=%s | output=%s",
        selected_voice, style, output_path.name,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    word_timings = asyncio.run(
        _synthesize(
            text=text,
            output_path=output_path,
            voice=selected_voice,
            style=style,
        )
    )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Voice generation failed — output is missing: {output_path}")

    # Write a sidecar timing file next to the MP3 (e.g. foo_voice.words.json).
    # The renderer picks this up for word-synced captions; if it's missing or
    # empty the renderer falls back to an even time split.
    if word_timings:
        timing_path = output_path.parent / (output_path.stem + ".words.json")
        try:
            timing_path.write_text(json.dumps(word_timings), encoding="utf-8")
            log.info("Captured %d word timings -> %s", len(word_timings), timing_path.name)
        except Exception as exc:
            log.warning("Could not write word-timing file (non-fatal): %s", exc)

    log.info("Voice generated: %s (%.1f KB)", output_path.name, output_path.stat().st_size / 1024)
    return output_path
