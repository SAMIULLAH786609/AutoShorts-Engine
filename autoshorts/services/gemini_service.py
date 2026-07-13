import json
import re

from google import genai

from autoshorts.config import GEMINI_API_KEY, GEMINI_MODEL
from autoshorts.models import AnalyticsSummary, TrendItem, VideoPlan


def clean_json(text: str) -> str:
    text = text.strip()

    text = re.sub(
        r"^```json\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    return text.strip()


def get_client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is missing from the .env file."
        )

    return genai.Client(api_key=GEMINI_API_KEY)


def generate_video_plan(
    topic: str,
    style: str = "auto",
) -> VideoPlan:

    prompt = f"""
You are an expert YouTube Shorts writer, comedy writer,
retention editor and SEO strategist.

TOPIC:
{topic}

REQUESTED STYLE:
{style}

Create an original vertical short-video script lasting 40 to 60 seconds.

HOOK RULES:
- The first sentence must capture attention within 3 seconds.
- Do not begin with greetings.
- Use surprise, curiosity, conflict or humour.
- The hook must immediately introduce the main idea.

FUNNY CONTENT RULES:
- If the style or topic is comedy, funny, meme or entertainment,
  create a genuinely funny story.
- Use a relatable situation.
- Include setup, escalation, misdirection and punchline.
- Avoid explaining scientific facts unless specifically requested.
- Avoid childish, copied or famous jokes.
- Make the humour easy to represent visually.

RETENTION RULES:
- Introduce a pattern interrupt every 2 to 3 sentences.
- Avoid filler.
- Use short spoken sentences.
- End with a payoff, punchline or surprising conclusion.

SEO RULES:
- Create an accurate searchable title.
- Do not use misleading clickbait.
- Generate focused hashtags relevant to the topic.
- Create a short searchable description.

VISUAL RULES:
- Generate five concrete stock-video search phrases.
- Put the phrases in the same order as the script scenes.
- Describe visible people, objects, actions or locations.

VOICE:
Choose exactly one suitable Edge-TTS voice:

- en-US-AriaNeural
- en-US-GuyNeural
- en-GB-SoniaNeural
- ur-PK-UzmaNeural
- ur-PK-AsadNeural

Return ONLY valid JSON in exactly this format:

{{
    "title": "SEO-friendly title under 60 characters",
    "hook": "strong opening sentence",
    "script": "complete narration between 95 and 135 words",
    "keywords": [
        "scene search phrase 1",
        "scene search phrase 2",
        "scene search phrase 3",
        "scene search phrase 4",
        "scene search phrase 5"
    ],
    "description": "short searchable description",
    "hashtags": [
        "shorts",
        "relevant_topic",
        "relevant_niche"
    ],
    "thumbnail_text": "two to five words",
    "category": "comedy, facts, education, story, motivation, technology, or other",
    "voice": "one voice from the allowed list"
}}
"""

    response = get_client().models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")

    try:
        data = json.loads(clean_json(response.text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Gemini did not return valid JSON.\n\n"
            f"Received:\n{response.text}"
        ) from exc

    return VideoPlan(
        title=str(data["title"]).strip(),
        hook=str(data["hook"]).strip(),
        script=str(data["script"]).strip(),
        keywords=[
            str(keyword).strip()
            for keyword in data["keywords"]
            if str(keyword).strip()
        ][:5],
        description=str(data["description"]).strip(),
        hashtags=[
            str(tag).lstrip("#").strip()
            for tag in data["hashtags"]
            if str(tag).strip()
        ][:8],
        thumbnail_text=str(data["thumbnail_text"]).strip(),
        category=str(data["category"]).strip(),
        voice=str(
            data.get("voice", "en-US-AriaNeural")
        ).strip(),
    )