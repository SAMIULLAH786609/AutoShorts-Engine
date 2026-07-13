import asyncio
from pathlib import Path

import edge_tts

from config import (
    VOICE_ENGLISH_FEMALE,
    VOICE_ENGLISH_MALE,
    VOICE_URDU_FEMALE,
    VOICE_URDU_MALE,
)


def choose_voice(
    language: str,
    gender: str,
) -> str:
    language = language.lower()
    gender = gender.lower()

    if language.startswith("urdu"):
        if gender == "male":
            return VOICE_URDU_MALE
        return VOICE_URDU_FEMALE

    if gender == "male":
        return VOICE_ENGLISH_MALE

    return VOICE_ENGLISH_FEMALE


async def _generate(
    text: str,
    output_path: Path,
    voice: str,
    style: str,
) -> None:
    rate = "+8%"
    pitch = "+0Hz"

    if style == "funny":
        rate = "+15%"
        pitch = "+2Hz"
    elif style == "serious":
        rate = "-2%"
        pitch = "-2Hz"
    elif style == "emotional":
        rate = "-5%"

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
    language: str = "English",
    gender: str = "female",
    style: str = "energetic",
) -> None:
    voice = choose_voice(language, gender)

    asyncio.run(
        _generate(
            text=text,
            output_path=output_path,
            voice=voice,
            style=style,
        )
    ) 