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

# Confirmed available and working models on this API key.
# Ordered lightest → heaviest to preserve quota and avoid 503 high demand.
_FALLBACK_MODELS = [
    "gemini-flash-lite-latest",   # fastest & lightweight
    "gemini-3.5-flash-lite",      # next-gen fast flash
    "gemini-3.5-flash",           # high quality flash
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

    prompt = f"""You are the head of content for a fast-growing faceless YouTube Shorts
channel. Every idea must serve ONE narrow niche so the algorithm can lock the
channel to a clear audience. Off-niche ideas kill the channel — never suggest them.

=== THE ONLY NICHE THIS CHANNEL COVERS ===
{niche}

Everything must sit inside this niche: how money really works, how wealthy people
think and behave, money psychology and mindset, hidden economics of everyday life,
pricing/spending traps, lifestyle inflation, the psychology behind scams and cons.
EDUCATIONAL ONLY — never give stock picks, crypto calls, "invest in X", or any
personalised financial advice.

=== CURRENT TRENDS (OPTIONAL FUEL — use only if a trend truly fits the niche) ===
{trends_text}
{avoid_section}

=== YOUR TASK ===
Generate exactly {count} short-video ideas. Each idea MUST:
1. Sit 100% inside the money / wealth-psychology niche above.
2. Deliver ONE specific, surprising, verifiable insight (not vague "be disciplined" fluff).
3. Open a curiosity gap that makes a scrolling viewer stop within 1 second.
4. Fit a tight 25–35 second Short.
5. Be clearly different from each other AND from the already-used list.
6. Use a trend ONLY when it genuinely intersects the niche (a billionaire story, a
   viral scam, an inflation/price story). Otherwise pick a strong EVERGREEN angle
   and set trend_ref to "" — evergreen is fully allowed and often better here.

HIGH-PERFORMING ANGLE PATTERNS FOR THIS NICHE:
- "Why the rich [do X] and you were taught the opposite"
- "The psychological trick that makes you spend $[amount] more"
- "[Everyday thing] is designed to keep you poor — here's how"
- "Broke people focus on [X]. Wealthy people focus on [Y]."
- "The real reason [price/fee/subscription] exists"

SCORING (be honest — only strong ideas):
- 90-100: Sharp niche insight + perfect curiosity gap + concrete detail/number
- 75-89: Solid niche insight + good hook
- Below 75: Do NOT include — generic, preachy, or off-niche

Return ONLY valid JSON (no extra text, no markdown):

{{
  "ideas": [
    {{
      "trend_ref": "trend number if used, else empty string",
      "trend_keyword": "trend name if used, else the core money concept",
      "topic": "specific curiosity-gap video topic (15-60 words)",
      "style": "psychology | facts | story | educational",
      "viral_hook": "the opening line — impossible to scroll past",
      "trend_reason": "why people care about this money insight right now",
      "original_angle": "the specific counter-intuitive angle that makes this unique",
      "score": 88
    }}
  ]
}}"""

    response = _generate(prompt)

    try:
        data = json.loads(_clean_json(response.text))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Gemini returned invalid JSON for topic ideas:\n{response.text}"
        ) from exc

    ideas: list[TopicIdea] = []
    MIN_SCORE = 72  # reject weak/generic ideas

    for item in data.get("ideas", [])[:count * 2]:  # fetch extra, filter by score
        score = float(item.get("score", 50))
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
You are the scriptwriter for a faceless YouTube Shorts channel in ONE niche:
MONEY & WEALTH PSYCHOLOGY — how money really works, how wealthy people think,
spending/pricing psychology, hidden everyday economics, the psychology of scams.
Goal: MAXIMUM watch time and rewatches. Every word earns its place.

EDUCATIONAL ONLY — never name a stock/crypto/fund, never say "invest in" anything,
never give personalised financial advice. Explain behaviour and systems, not tips.

TOPIC:
{topic}

REQUESTED STYLE:
{style}
{research_section}

Create an original vertical short-form video script lasting exactly 25 to 32 seconds.

HOOK RULES (most important — determines 90% of views):
- First sentence = viewer either STAYS or LEAVES. Make it IMPOSSIBLE to scroll past.
- Use one of: shocking money stat, bold claim, or "you've been doing X wrong" reveal.
- NEVER start with: "Hey guys", "Did you know", "Today we'll talk about", "Welcome".
- Examples of great hooks for THIS niche:
  * "Being poor is expensive — and it's by design."
  * "The rich don't budget. They do this instead."
  * "That $4 coffee is costing you way more than $4."

SCRIPT RULES:
- STRICTLY 60 to 75 words total (critical — 70 words = ~30 seconds at narration pace).
- Short punchy sentences — max 10 words each.
- Deliver ONE concrete insight with a real number, name, or mechanism — no vague fluff.
- Build tension: hook -> surprising mechanism -> bigger reveal -> payoff line.
- End with: a mind-blowing takeaway OR "comment [specific question]" OR "follow for more".
- Never say: AI, script, video, channel, subscribe, like.
- Written for voice narration — must sound natural when spoken aloud.

SEO RULES (for YouTube algorithm):
- Title: MUST contain a power word (real, truth, secret, actually, never, why, rich, broke, hidden).
  Format: "[Power word] [money concept] [emotional hook]" — under 60 chars.
  Examples: "Why The Rich Never Feel Rich" / "The Real Reason You're Always Broke" / "Hidden Truth About Money"
- Description: 2-3 sentences, include the main money keyword naturally, end with a question.
- Hashtags: exactly 15 tags — mix these 3 pools for maximum reach:
  POOL 1 — Niche-specific (5 tags): moneypsychology, moneymindset, personalfinance, financialliteracy, wealthmindset
  POOL 2 — Viral Shorts (5 tags): shorts, viral, trending, fyp, explore
  POOL 3 — Broad discovery (5 tags): motivation, success, money, wealth, facts
  ALWAYS include "shorts" and "viral" in the final list.
- Thumbnail text: 2-4 SHOCKING CAPITALIZED words that make people click instantly.

VISUAL KEYWORDS:
- Exactly 5 specific cinematic visual search phrases that match money/wealth imagery.
- Think like a film director for each script moment.
- Examples: "cash counting machine close up", "luxury penthouse city skyline night",
  "empty wallet slow motion", "stock ticker board blurred", "person paying with phone"

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
    "hashtags": ["moneypsychology", "moneymindset", "personalfinance", "financialliteracy", "wealthmindset", "shorts", "viral", "trending", "fyp", "explore", "motivation", "success", "money", "wealth", "facts"],
    "thumbnail_text": "2-4 SHOCKING CAPITALIZED WORDS",
    "category": "education | psychology | facts | story | motivation",
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
        hashtags=[str(t).lstrip("#").strip() for t in data["hashtags"] if str(t).strip()][:15],
        thumbnail_text=str(data.get("thumbnail_text", topic[:30])).strip(),
        category=str(data.get("category", "education")).strip(),
        voice=str(data.get("voice", "en-US-AriaNeural")).strip(),
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
    for item in data.get("ideas", [])[:count * 2]:
        score = float(item.get("score", 50))
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