"""
AutoShorts Engine — AI Voice Service (Edge-TTS).

Generates MP3 narration from script text.
Supports English and Urdu voices with dynamic rate/pitch per style.
"""

from __future__ import annotations

import asyncio
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
) -> None:
    """Internal async synthesizer."""
    rate, pitch = _STYLE_PARAMS.get(style.lower(), (_DEFAULT_RATE, _DEFAULT_PITCH))

    communicator = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
    )

    await communicator.save(str(output_path))


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

    asyncio.run(
        _synthesize(
            text=text,
            output_path=output_path,
            voice=selected_voice,
            style=style,
        )
    )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Voice generation failed — output is missing: {output_path}")

    log.info("Voice generated: %s (%.1f KB)", output_path.name, output_path.stat().st_size / 1024)
    return output_path
