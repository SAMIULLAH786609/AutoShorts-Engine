import json
import re

from google import genai

from config import CHANNEL_NICHE, GEMINI_API_KEY
from modules.gemini_helper import generate_with_retry

MODEL_NAME = "gemini-3.5-flash"


def clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.I)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_original_daily_topics(
    trend_items: list[dict],
    count: int = 3,
    niche: str = CHANNEL_NICHE,
) -> list[dict]:
  

    trends_text = "\n".join(
        (
            f"- {item['title']} | "
            f"views={item['views']} | "
            f"likes={item['likes']}"
        )
        for item in trend_items
    )

    prompt = f"""
You are a short-form video strategist.

Channel niche:
{niche}

Current popular YouTube titles:
{trends_text}

Generate {count} ORIGINAL short-video ideas.

Do not copy titles, scripts, creators, characters or exact concepts.

Use trends only to understand:
- audience interest
- emotional pattern
- title structure
- topic demand

Each idea should be suitable for a 35 to 55 second Short.

Return only valid JSON:

{{
  "ideas": [
    {{
      "topic": "original topic",
      "style": "funny, facts, story, educational or motivational",
      "trend_reason": "why this may interest viewers",
      "original_angle": "what makes it different"
    }}
  ]
}}
"""

    response = generate_with_retry(
    prompt=prompt,
)

    if not response.text:
        raise RuntimeError("No daily ideas generated.")

    data = json.loads(clean_json(response.text))
    return data.get("ideas", [])[:count]