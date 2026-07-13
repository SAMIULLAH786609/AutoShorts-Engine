import json
import re
from typing import Any

from google import genai

from config import GEMINI_API_KEY

from modules.gemini_helper import generate_with_retry
MODEL_NAME = "gemini-3.5-flash"

def clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_content_plan(
    topic: str,
    style: str = "funny",
    language: str = "English",
) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing.")

    

    prompt = f"""
You are a professional viral short-form content writer.

Topic:
{topic}

Style:
{style}

Language:
{language}

Create an original 35 to 55 second vertical video.

The first sentence must hook the viewer within 3 seconds.

If style is funny:
- Use a relatable situation.
- Add escalation.
- Add visual comedy.
- Include one unexpected twist.
- End with a strong punchline.
- Do not write a boring article.
- Do not explain the joke.
- Avoid childish or copied jokes.

Retention requirements:
- Short spoken sentences.
- A curiosity gap.
- A pattern interrupt every few sentences.
- No slow introduction.
- No generic greeting.

Return ONLY valid JSON:

{{
  "topic": "refined topic",
  "style": "{style}",
  "hook": "first 3-second hook",
  "script": "complete narration",
  "title_options": [
    "SEO title option 1",
    "SEO title option 2",
    "SEO title option 3"
  ],
  "description": "short SEO description",
  "hashtags": [
    "shorts",
    "viral",
    "relevanttag1",
    "relevanttag2",
    "relevanttag3"
  ],
  "thumbnail_text": "maximum 5 words",
  "scenes": [
    {{
      "narration": "part of script",
      "visual_query": "specific stock-video search query",
      "duration": 5
    }}
  ],
  "voice_style": "energetic, funny, serious or emotional"
}}
"""

    response = generate_with_retry(
  
    prompt=prompt,
)

    if not response.text:
        raise RuntimeError("Gemini returned empty content.")

    try:
        plan = json.loads(clean_json(response.text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Gemini returned invalid JSON:\n{response.text}"
        ) from exc

    required = [
        "hook",
        "script",
        "title_options",
        "description",
        "hashtags",
        "thumbnail_text",
        "scenes",
    ]

    missing = [key for key in required if not plan.get(key)]

    if missing:
        raise RuntimeError(
            "Gemini plan missing fields: " + ", ".join(missing)
        )

    return plan