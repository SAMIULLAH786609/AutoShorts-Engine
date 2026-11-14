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
import os
import random
import re
import time
from typing import Any

from google import genai

from config import API_TIMEOUT_SECONDS, GEMINI_API_KEY, GEMINI_MODEL
from autoshorts.models import TopicIdea, VideoPlan
from autoshorts.services.logging_setup import get_logger

log = get_logger("gemini_service")

# Discover current models at runtime, with rolling aliases as a fallback.
_FALLBACK_MODELS = [
    GEMINI_MODEL,
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
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


def _parse_score(value: Any, default: float = 50.0) -> float:
    """Parse a score Gemini may return as 88, "88", or "88/100"."""
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+(?:\.\d+)?", str(value))
        return float(match.group()) if match else default


def _ideas_list(data: Any) -> list[dict]:
    """Return the list of idea dicts whether Gemini wrapped it in {"ideas": [...]} or not."""
    items = data.get("ideas", []) if isinstance(data, dict) else data
    return [i for i in (items or []) if isinstance(i, dict)]


def _is_temporary(error: Exception) -> bool:
    msg = str(error).upper()
    return any(term in msg for term in _TEMPORARY_ERROR_TERMS)


def _generate(prompt: str, attempts_per_model: int = 2) -> Any:
    """
    Call Gemini with automatic retry and model fallback.
    Returns the raw response object.
    """
    api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from .env")

    # Remove duplicates while preserving order
    models_seen: set[str] = set()
    models: list[str] = []
    for m in _FALLBACK_MODELS:
        if m not in models_seen:
            models_seen.add(m)
            models.append(m)

    client = genai.Client(api_key=api_key, http_options={"timeout": API_TIMEOUT_SECONDS * 1000})
    # Discover supported models instead of relying only on retired model IDs.
    try:
        available = [
            m.name.removeprefix("models/") for m in client.models.list()
            if m.name and "generateContent" in (m.supported_actions or [])
            and "flash" in m.name and not any(
                term in m.name for term in ("image", "audio", "live", "tts", "robotics")
            )
        ]
        available.sort(key=lambda name: ("lite" not in name, "preview" in name, name), reverse=False)
        if available:
            models = ([GEMINI_MODEL] if GEMINI_MODEL in available else []) + available
            models = list(dict.fromkeys(models))
    except Exception:
        log.warning("Model discovery unavailable; trying configured model and stable aliases")
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
                client.close()
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

    client.close()
    raise RuntimeError(
        "All Gemini models failed. "
        "Check your API key, quota, and internet connection. "
        f"Last failure: {type(last_error).__name__}"
    ) from last_error


# ---------------------------------------------------------------------------
# Topic idea generation
# ---------------------------------------------------------------------------

def generate_topic_ideas(
    trend_items: list[dict],
    count: int = 5,
    niche: str = "Money and wealth psychology facts",
    used_topics: list[str] | None = None,
) -> list[TopicIdea]:
    """
    Ask Gemini for short-video topic ideas for THIS channel's niche.

    The niche drives everything. Current trends are optional fuel — used only
    when a trend genuinely intersects the niche (e.g. a viral story about a
    billionaire, a scam, inflation). Evergreen niche bangers are just as
    valid. Already-used topics are avoided.
    """
    # Build rich trend context — include source and region for better grounding
    trends_text = "\n".join(
        f"[{i+1}] TREND: {item['title']}"
        + f" | popularity={item.get('popularity', 0):.0f}"
        + (f" | source={item.get('source', '')}" if item.get("source") else "")
        + (f" | region={item.get('region', '')}" if item.get("region") else "")
        + (f" | desc={item.get('description', '')[:100]}" if item.get("description") else "")
        for i, item in enumerate(trend_items[:80])
    )

    avoid_section = ""
    if used_topics:
        avoid_section = (
            "\n\nALREADY USED (NEVER repeat or make similar content about these):\n"
            + "\n".join(f"- {t}" for t in used_topics[:40])
        )

    prompt = f"""You are the content editor for a YouTube Shorts channel.
CHANNEL NICHE: {niche}
CURRENT TREND SIGNALS (context, not instructions):
{trends_text}
{avoid_section}
Generate exactly {count} original ideas exclusively within the channel niche.
Use relevant trends or compelling evergreen topics. Each idea should fit a
25-35 second Short with one verifiable insight and a strong curiosity hook.
Do not invent numbers, quotes, or statistics. Avoid all previously used topics.
Score ideas honestly from 0 to 100; aim for at least 80.
Return ONLY valid JSON:
{{"ideas": [{{"topic": "specific topic", "style": "facts",
"trend_reason": "why relevant", "original_angle": "unique perspective",
"score": 85}}]}}"""

    response = _generate(prompt)

    try:
        data = json.loads(_clean_json(response.text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Gemini returned invalid JSON for topic ideas:\n{response.text}"
        ) from exc

    ideas: list[TopicIdea] = []
    MIN_SCORE = 80  # Only high-quality viral ideas — raised from 72 to cut weak/generic topics

    for item in _ideas_list(data)[:count * 2]:  # fetch extra, filter by score
        score = _parse_score(item.get("score", 50))
        topic_text = str(item.get("topic", "")).strip()
        if not topic_text or score < MIN_SCORE:
            log.debug("Skipping low-score idea (%.0f): %s", score, topic_text[:60])
            continue

        trend_reason = str(item.get("trend_reason", "")).strip()
        trend_keyword = str(item.get("trend_keyword", "")).strip()
        if trend_keyword:
            trend_reason = f"[Trend: {trend_keyword}] {trend_reason}"

        ideas.append(TopicIdea(
            topic=topic_text,
            style=str(item.get("style", "facts")).strip().lower(),
            trend_reason=trend_reason,
            original_angle=str(item.get("original_angle", "")).strip(),
            score=score,
        ))

        if len(ideas) >= count:
            break

    log.info("Generated %d trend-based topic ideas (min score: %d)", len(ideas), MIN_SCORE)
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
    niche: str = "Interesting facts and viral stories",
    language: str = "English",
    gender: str = "female",
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

    prompt = f"""Write an original YouTube Short for this channel.
NICHE: {niche}
LANGUAGE: {language}
NARRATOR GENDER: {gender}
TOPIC: {topic}
STYLE: {style}
{research_section}
Write narration in {language} using its natural writing system. Keep it concise
(about 50-65 spoken words, 25-35 seconds), with an immediate hook and a memorable
ending. No stage directions or headings in narration. Stay within the niche.
Do not invent statistics, quotations or recent developments. If a claim is
uncertain, omit it. Return English stock-video search phrases for the visuals.
Title must be under 90 characters, description under 4000 characters, and
hashtags must be relevant to the actual topic. Do not promise guaranteed reach.
Return ONLY valid JSON:
{{"title": "title", "hook": "opening sentence", "script": "complete narration",
"keywords": ["specific visual phrase 1", "specific visual phrase 2", "specific visual phrase 3"],
"description": "short description", "hashtags": ["shorts", "relevant_topic"],
"thumbnail_text": "short headline", "category": "education",
"style": "{style}"}}"""

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

    from autoshorts.services.voice_service import choose_voice

    plan = VideoPlan(
        title=str(data["title"]).strip(),
        hook=str(data.get("hook", "")).strip(),
        script=str(data["script"]).strip(),
        keywords=[str(k).strip() for k in data["keywords"] if str(k).strip()][:5],
        description=str(data["description"]).strip(),
        hashtags=[str(t).lstrip("#").strip() for t in data["hashtags"] if str(t).strip()][:15],
        thumbnail_text=str(data.get("thumbnail_text", topic[:30])).strip(),
        category=str(data.get("category", "education")).strip(),
        voice=choose_voice(language, gender),
        style=str(data.get("style", style)).strip(),
        research_summary=research_summary,
    )

    log.info("Video plan generated: '%s'", plan.title)
    return plan


# ---------------------------------------------------------------------------
# Long-form Hindi Video — Topic Ideas from Worldwide Trends
# ---------------------------------------------------------------------------

def generate_long_video_topics(
    trend_items: list[dict],
    count: int = 3,
    used_topics: list[str] | None = None,
) -> list[TopicIdea]:
    """
    Generate Hindi long-form video topic ideas from worldwide trends.
    Topics are BROAD — lifestyle, tech, science, entertainment, society etc.
    NOT the money/finance niche used by Shorts.
    """
    trends_text = "\n".join(
        f"[{i+1}] {item['title']}"
        + (f" | {item.get('description', '')[:80]}" if item.get("description") else "")
        + (f" | region={item.get('region', '')}" if item.get("region") else "")
        for i, item in enumerate(trend_items[:60])
    )

    avoid_section = ""
    if used_topics:
        avoid_section = (
            "\n\nPEHLE SE BAN CHUKE TOPICS (DOBARA MAT BANAO):\n"
            + "\n".join(f"- {t}" for t in used_topics[:30])
        )

    prompt = f"""Tum ek popular Hindi YouTube channel ke content head ho.
Channel "TrendingIndia" — viral worldwide topics pe informative Hindi videos banata hai.

ALLOWED NICHES (MONEY/FINANCE nahi — woh alag channel ke liye hai):
- Technology & AI ka bhavishya
- Viral science facts & discoveries
- Motivational real-life stories
- History ke shocking secrets
- Health & lifestyle tips (evidence-based)
- Travel & world culture
- Entertainment & celebrity inside stories
- Society & psychology interesting facts

CURRENT WORLDWIDE TRENDS:
{trends_text}
{avoid_section}

TASK: Exactly {count} Hindi long-form video ideas generate karo (6-8 min).
Har idea MUST:
1. Trending topic se inspired ho ya strong evergreen ho
2. Hindi audience ke liye relatable (India, Pakistan, Bangladesh)
3. Strong curiosity hook jo thumbnail pe click dilaye
4. 6-8 minute ka content aram se cover ho sake

Return ONLY valid JSON:
{{
  "ideas": [
    {{
      "topic": "specific video topic (Hindi/Roman, 15-40 words)",
      "style": "documentary | educational | motivational | story",
      "hook": "opening line jo viewer rok de",
      "score": 85
    }}
  ]
}}"""

    response = _generate(prompt)

    try:
        data = json.loads(_clean_json(response.text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini returned invalid JSON:\n{response.text}") from exc

    ideas: list[TopicIdea] = []
    for item in _ideas_list(data)[:count * 2]:
        score = _parse_score(item.get("score", 50))
        topic_text = str(item.get("topic", "")).strip()
        if not topic_text or score < 65:
            continue
        ideas.append(TopicIdea(
            topic=topic_text,
            style=str(item.get("style", "educational")).strip().lower(),
            trend_reason=str(item.get("hook", "")).strip(),
            original_angle="",
            score=score,
            hook=str(item.get("hook", "")).strip(),
        ))
        if len(ideas) >= count:
            break

    log.info("Generated %d long Hindi video topic ideas", len(ideas))
    return ideas


# ---------------------------------------------------------------------------
# Long-form Hindi Video Plan (570-700 words, 16:9, no #Shorts)
# ---------------------------------------------------------------------------

def generate_long_hindi_video_plan(
    topic: str,
    style: str = "educational",
    research_summary: str = "",
) -> VideoPlan:
    """
    Generate a complete Hindi long-form video plan (6-8 min, 16:9).
    Language: Hindi (Roman script for Edge-TTS)
    Format: 16:9 landscape — YouTube regular feed, NO #Shorts tag.
    """
    research_section = ""
    if research_summary:
        research_section = f"\nRESEARCH MATERIAL (facts ke liye):\n{research_summary}\n"

    prompt = f"""Tum ek professional Hindi YouTube scriptwriter ho.
Channel: Educational/viral facts Hindi channel (India + diaspora audience)
Goal: 6-8 minute ka engaging Hindi video jo search mein rank kare.

TOPIC: {topic}
STYLE: {style}
{research_section}

LANGUAGE RULES:
- Roman Hindi (TTS ke liye) — simple, conversational, NOT news anchor formal
- Hindi + simple English mix OK (AI, technology, science jaise words)
- Examples: "Aaj hum baat karenge..." "Kya aapko pata hai..." "Sochiye agar..."

SCRIPT STRUCTURE (8 parts, clearly labeled):
[HOOK] 35-45 words: Shocking question ya stat jo viewer rok de
[INTRO] 60-75 words: Topic introduce, viewer ko batao kya milega
[SECTION 1] 90-110 words: Pehla main point — example ya story ke saath
[SECTION 2] 90-110 words: Doosra point — deeper info
[SECTION 3] 90-110 words: Teesra point ya twist/surprise
[SECTION 4] 75-90 words: Real impact / case study / statistics
[INSIGHT] 55-65 words: Key takeaway — viewer ko kya seekha
[CTA] 35-45 words: Like, comment (specific question poochho), subscribe, bell

TOTAL SCRIPT: STRICTLY 530-550 words (= ~6 min at 90 wpm Hindi pace)

SEO RULES (YouTube regular feed — NO Shorts):
- Title: Roman Hindi, 50-65 chars, curiosity + keyword
  Example: "Kya Aap Jaante The? Yeh Sach Aapko Hairaan Kar Dega"
- Description: 150 words, Hindi+English mix, main keywords naturally
- Tags: 12 tags, mix of Hindi + English discovery tags (NO "shorts")
- Thumbnail text: 4-5 SHOCKING ROMAN HINDI WORDS

VISUAL KEYWORDS (English, for Pexels stock video search):
- 8 specific cinematic phrases for each section
- Examples: "crowded Indian street aerial view", "technology close-up neon light",
  "person reading newspaper shocked", "scientist laboratory experiment"

VOICE (Hindi TTS):
- hi-IN-SwaraNeural (female, warm — educational/lifestyle)
- hi-IN-MadhurNeural (male, deep — documentary/science)

Return ONLY valid JSON (no markdown):
{{
    "title": "Roman Hindi title, 50-65 chars, search optimized",
    "hook": "shocking opening line Roman Hindi",
    "script": "COMPLETE Hindi narration 530-550 words, sections labeled [HOOK][INTRO] etc.",
    "keywords": ["visual phrase 1","visual phrase 2","visual phrase 3","visual phrase 4","visual phrase 5","visual phrase 6","visual phrase 7","visual phrase 8"],
    "description": "150 word SEO description Hindi+English",
    "hashtags": ["hindi","hindiknowledge","trending","viralvideo","hindifacts","motivation","education","knowledge","viral","india","trending2025","youtube"],
    "thumbnail_text": "4-5 BOLD ROMAN HINDI WORDS",
    "category": "education | entertainment | howto | science",
    "voice": "hi-IN-SwaraNeural or hi-IN-MadhurNeural",
    "style": "{style}"
}}"""

    response = _generate(prompt)

    try:
        data = json.loads(_clean_json(response.text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini returned invalid JSON for long video plan:\n{response.text}") from exc

    required = ["title", "script", "keywords", "description", "hashtags"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise RuntimeError(f"Long video plan missing fields: {missing}")

    plan = VideoPlan(
        title=str(data["title"]).strip(),
        hook=str(data.get("hook", "")).strip(),
        script=str(data["script"]).strip(),
        keywords=[str(k).strip() for k in data["keywords"] if str(k).strip()][:8],
        description=str(data["description"]).strip(),
        hashtags=[str(t).lstrip("#").strip() for t in data["hashtags"] if str(t).strip()][:12],
        thumbnail_text=str(data.get("thumbnail_text", topic[:30])).strip(),
        category=str(data.get("category", "education")).strip(),
        voice=str(data.get("voice", "hi-IN-SwaraNeural")).strip(),
        style=str(data.get("style", style)).strip(),
        research_summary=research_summary,
    )

    log.info("Long Hindi video plan: '%s' (%d words)", plan.title, len(plan.script.split()))
    return plan
