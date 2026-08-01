"""
AutoShorts Engine — Gemini AI Service.

Handles all LLM interactions:
  - Topic idea generation (from trend signals)
  - Topic research (fact gathering)
  - Full video plan generation (script, SEO, voice, visuals)

Uses automatic retry across fallback models.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL
from autoshorts.models import TopicIdea, VideoPlan
from autoshorts.services.logging_setup import get_logger

log = get_logger("gemini_service")

# Ordered fallback list — confirmed available on this API key.
# Lighter models are first to preserve quota on the heavier ones.
_FALLBACK_MODELS = [
    "gemini-flash-lite-latest",   # lightest, works even under quota pressure
    "gemini-flash-latest",        # standard flash
    "gemini-3.5-flash",           # newest flash variant
    "gemini-2.0-flash",           # fallback (may hit 429 under heavy load)
    "gemini-2.0-flash-lite",      # lite fallback
]

_TEMPORARY_ERROR_TERMS = (
    "503", "UNAVAILABLE", "HIGH DEMAND", "429",
    "RESOURCE_EXHAUSTED", "GETADDRINFO FAILED",
    "CONNECTERROR", "CONNECTION ERROR",
    "TIMED OUT", "TIMEOUT", "TEMPORARY FAILURE",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_json(text: str) -> str:
    """Strip markdown code fences that Gemini sometimes wraps JSON in."""
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _is_temporary(error: Exception) -> bool:
    msg = str(error).upper()
    return any(term in msg for term in _TEMPORARY_ERROR_TERMS)


def _generate(prompt: str, attempts_per_model: int = 2) -> Any:
    """
    Call Gemini with automatic retry and model fallback.
    Returns the raw response object.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing from .env")

    # Remove duplicates while preserving order
    models_seen: set[str] = set()
    models: list[str] = []
    for m in _FALLBACK_MODELS:
        if m not in models_seen:
            models_seen.add(m)
            models.append(m)

    client = genai.Client(api_key=GEMINI_API_KEY)
    last_error: Exception | None = None

    for model in models:
        log.debug("Trying Gemini model: %s", model)

        for attempt in range(1, attempts_per_model + 1):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )

                if not response.text:
                    raise RuntimeError(f"{model} returned an empty response.")

                log.debug("Gemini success: %s (attempt %d)", model, attempt)
                return response

            except Exception as error:
                last_error = error

                if not _is_temporary(error):
                    log.debug("Model %s permanent error: %s", model, error)
                    break

                if attempt < attempts_per_model:
                    # 429 RESOURCE_EXHAUSTED needs a longer wait than 503
                    is_rate_limit = "429" in str(error) or "RESOURCE_EXHAUSTED" in str(error).upper()
                    base_wait = 65 if is_rate_limit else 4
                    wait = base_wait * (2 ** (attempt - 1)) + random.uniform(0, 5)
                    log.warning(
                        "Model %s %s, retrying in %.1fs…",
                        model,
                        "rate-limited (429)" if is_rate_limit else "temporarily unavailable",
                        wait,
                    )
                    time.sleep(wait)

    raise RuntimeError(
        "All Gemini models failed. "
        "Check your API key, quota, and internet connection."
    ) from last_error


# ---------------------------------------------------------------------------
# Topic idea generation
# ---------------------------------------------------------------------------

def generate_topic_ideas(
    trend_items: list[dict],
    count: int = 5,
    niche: str = "Interesting facts and viral stories",
    used_topics: list[str] | None = None,
) -> list[TopicIdea]:
    """
    Ask Gemini to generate original short-video topic ideas inspired by
    current trending content, avoiding any already-used topics.
    """
    trends_text = "\n".join(
        f"- {item['title']} | popularity={item.get('popularity', 0):.0f}"
        + (f" | source={item.get('source', '')}" if item.get("source") else "")
        for item in trend_items[:60]
    )

    avoid_section = ""
    if used_topics:
        avoid_section = (
            "\n\nALREADY USED TOPICS (never repeat these or anything similar):\n"
            + "\n".join(f"- {t}" for t in used_topics[:30])
        )

    prompt = f"""
You are a viral YouTube Shorts strategist whose job is to MAXIMIZE views and clicks.

CHANNEL NICHE:
{niche}

CURRENT WORLDWIDE TRENDING TOPICS:
{trends_text}
{avoid_section}

Generate exactly {{count}} ORIGINAL, UNIQUE short-video ideas with MAXIMUM viral potential.

Rules for MAXIMUM VIEWS:
- Each idea must trigger one of: SHOCK, CURIOSITY, DISBELIEF, FEAR, AWE, or LAUGHTER.
- The topic title itself must make someone STOP scrolling and MUST click.
- Use the "curiosity gap" technique — hint at something surprising without revealing it.
- Prioritize topics that people will SHARE because they can't believe it.
- Each idea must be suitable for a 25–30 second YouTube Short.
- Each idea must be completely different from the others.
- AVOID generic topics — choose specific, surprising angles.
- Score each idea 0–100 for viral potential (not just suitability).

High-performing idea patterns:
- "The REAL reason why [common thing] happens"
- "[Famous thing] is actually [shocking truth]"
- "[Number] seconds that will blow your mind"
- "Why [popular belief] is completely WRONG"
- "Scientists discovered [shocking fact]"

Return ONLY valid JSON, no extra text:

{{
  "ideas": [
    {{
      "topic": "specific, curiosity-gap original topic",
      "style": "funny | facts | story | educational | motivational",
      "viral_hook": "one shocking/curiosity sentence that makes people click",
      "trend_reason": "why this resonates with current audiences",
      "original_angle": "what makes this version unique and original",
      "score": 85
    }}
  ]
}}
"""

    response = _generate(prompt)

    try:
        data = json.loads(_clean_json(response.text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Gemini returned invalid JSON for topic ideas:\n{response.text}"
        ) from exc

    ideas: list[TopicIdea] = []

    for item in data.get("ideas", [])[:count]:
        ideas.append(TopicIdea(
            topic=str(item.get("topic", "")).strip(),
            style=str(item.get("style", "facts")).strip().lower(),
            trend_reason=str(item.get("trend_reason", "")).strip(),
            original_angle=str(item.get("original_angle", "")).strip(),
            score=float(item.get("score", 50)),
        ))

    log.info("Generated %d topic ideas", len(ideas))
    return ideas


# ---------------------------------------------------------------------------
# Topic research
# ---------------------------------------------------------------------------

def research_topic(topic: str) -> str:
    """
    Ask Gemini to research a topic and return a factual summary that the
    script writer will use as its source material.
    """
    prompt = f"""
You are a professional researcher and fact-checker for short-form video content.

TOPIC TO RESEARCH:
{topic}

Research this topic thoroughly. Provide:
1. The most interesting, surprising, or little-known facts about this topic.
2. Recent developments or news related to this topic (if applicable).
3. Key data, statistics, or quotes that would engage a short-form audience.
4. Any common misconceptions to address.

Rules:
- Be factual and accurate.
- Prioritize surprising or counter-intuitive information.
- Keep the summary between 200 and 400 words.
- Do not copy from any specific article. Synthesize and summarize.
- Write in clear, simple language suitable for a general audience.

Return a plain text research summary (not JSON).
"""

    response = _generate(prompt)
    summary = response.text.strip()
    log.info("Research complete for topic: %s (%d chars)", topic, len(summary))
    return summary


# ---------------------------------------------------------------------------
# Full video plan generation
# ---------------------------------------------------------------------------

def generate_video_plan(
    topic: str,
    style: str = "facts",
    research_summary: str = "",
) -> VideoPlan:
    """
    Generate a complete, original video plan including script, SEO data,
    visual keywords, voice selection, and thumbnail text.
    """
    research_section = ""
    if research_summary:
        research_section = f"""
RESEARCH MATERIAL (use as factual source, do NOT copy verbatim):
{research_summary}
"""

    prompt = f"""
You are a viral YouTube Shorts expert whose ONLY goal is MAXIMUM VIEWS and WATCH TIME.
Every word must earn its place. Boring = viewers scroll away.

TOPIC:
{topic}

REQUESTED STYLE:
{style}
{research_section}

Create an original vertical short-form video script lasting exactly 25 to 30 seconds.

HOOK RULES (most important — determines 90% of views):
- First sentence = viewer either STAYS or LEAVES. Make it IMPOSSIBLE to scroll past.
- Use one of: shocking stat, bold claim, controversial statement, or disbelief statement.
- NEVER start with: "Hey guys", "Did you know", "Today we'll talk about", "Welcome".
- Examples of great hooks:
  * "This is illegal in 47 countries."
  * "Scientists just found out they were WRONG about this."
  * "Your brain has been lying to you your entire life."

SCRIPT RULES:
- STRICTLY 60 to 75 words total (critical — 70 words = ~30 seconds at narration pace).
- Short punchy sentences — max 10 words each.
- Every sentence must ADD VALUE or CREATE CURIOSITY — no padding.
- Build tension: hook → surprising fact → bigger reveal → payoff.
- End with: a mind-blowing fact OR "comment below [question]" OR "follow for more".
- Never say: AI, script, video, channel, subscribe, like.
- Written for voice narration — must sound natural when spoken.

SEO RULES (for YouTube algorithm):
- Title: MUST contain a power word (shocking, secret, real, truth, actually, never, always).
  Use format: "[Number/Power word] [Topic] [Emotional hook]" — under 60 chars.
  Examples: "The REAL Reason Planes Never Crash" / "5 Facts That Will Ruin Your Day"
- Description: 2-3 sentences, include main keyword naturally, end with a question to boost comments.
- Hashtags: 8 tags — mix of viral (#facts #mindblown #shorts) + niche-specific tags.
- Thumbnail text: 2-4 SHOCKING CAPITALIZED words that make people click.

VISUAL KEYWORDS:
- Exactly 5 specific cinematic visual search phrases.
- Think like a film director: what STRIKING imagery matches each script moment?
- Examples: "astronaut floating in space closeup", "slow motion water drop impact"

VOICE SELECTION:
Choose the voice that best fits the content energy:
- en-US-AriaNeural  (female, energetic — best for facts/shocking content)
- en-US-GuyNeural   (male, confident — best for serious/dramatic content)
- en-GB-SoniaNeural (female, professional — best for educational)
- ur-PK-UzmaNeural  (female, Urdu — for Urdu content)
- ur-PK-AsadNeural  (male, Urdu — for Urdu content)

Return ONLY valid JSON in exactly this format:

{{
    "title": "CTR-optimized title with power word, under 60 chars",
    "hook": "jaw-dropping opening sentence — makes viewer stop scrolling",
    "script": "complete narration STRICTLY 60-75 words — ends with engagement CTA",
    "keywords": [
        "cinematic visual phrase 1",
        "cinematic visual phrase 2",
        "cinematic visual phrase 3",
        "cinematic visual phrase 4",
        "cinematic visual phrase 5"
    ],
    "description": "2-3 sentence SEO description ending with a question",
    "hashtags": ["shorts", "facts", "mindblown", "viral", "tag5", "tag6", "tag7", "tag8"],
    "thumbnail_text": "2-4 SHOCKING CAPITALIZED WORDS",
    "category": "comedy | facts | education | story | motivation | technology | science | other",
    "voice": "one voice from the allowed list",
    "style": "{style}"
}}
"""

    response = _generate(prompt)

    try:
        data = json.loads(_clean_json(response.text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Gemini returned invalid JSON for video plan:\n{response.text}"
        ) from exc

    # Validate required fields
    required = ["title", "script", "keywords", "description", "hashtags"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise RuntimeError(f"Gemini video plan missing fields: {missing}")

    plan = VideoPlan(
        title=str(data["title"]).strip(),
        hook=str(data.get("hook", "")).strip(),
        script=str(data["script"]).strip(),
        keywords=[str(k).strip() for k in data["keywords"] if str(k).strip()][:5],
        description=str(data["description"]).strip(),
        hashtags=[str(t).lstrip("#").strip() for t in data["hashtags"] if str(t).strip()][:8],
        thumbnail_text=str(data.get("thumbnail_text", topic[:30])).strip(),
        category=str(data.get("category", "facts")).strip(),
        voice=str(data.get("voice", "en-US-AriaNeural")).strip(),
        style=str(data.get("style", style)).strip(),
        research_summary=research_summary,
    )

    log.info("Video plan generated: '%s'", plan.title)
    return plan