"""
AutoShorts Engine — Trend Discovery Service.

Collects trending topics from:
  1. YouTube Trending (multiple regions)
  2. GDELT News
  3. BBC / Reuters / NASA RSS feeds
  4. Reddit (hot posts via JSON API, no key needed)
  5. Hacker News (technology topics)
  6. NewsAPI (if key is configured)
  7. Google News RSS

All sources are independent — one failing never blocks the others.
Results are merged and returned as a unified list of TrendItem objects.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

import feedparser
import requests

from config import (
    API_TIMEOUT_SECONDS,
    NEWS_API_KEY,
    TREND_REGIONS,
    TREND_VIDEOS_PER_REGION,
    YOUTUBE_API_KEY,
)
from autoshorts.models import TrendItem
from autoshorts.services.logging_setup import get_logger

log = get_logger("trend_sources")

YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


# ---------------------------------------------------------------------------
# Source 1: YouTube Trending (multi-region)
# ---------------------------------------------------------------------------

def fetch_youtube_trends() -> list[TrendItem]:
    """Fetch most-popular YouTube videos across all configured regions."""
    if not YOUTUBE_API_KEY:
        log.warning("YOUTUBE_API_KEY not set — skipping YouTube trends")
        return []

    results: list[TrendItem] = []

    for region in TREND_REGIONS:
        try:
            response = requests.get(
                YOUTUBE_VIDEOS_URL,
                params={
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "regionCode": region,
                    "maxResults": TREND_VIDEOS_PER_REGION,
                    "key": YOUTUBE_API_KEY,
                },
                timeout=API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()

            for item in response.json().get("items", []):
                snippet = item.get("snippet", {})
                stats   = item.get("statistics", {})

                views    = float(stats.get("viewCount",   0))
                likes    = float(stats.get("likeCount",   0))
                comments = float(stats.get("commentCount", 0))
                score    = views + (likes * 20) + (comments * 50)

                title = str(snippet.get("title", "")).strip()
                if not title:
                    continue

                results.append(TrendItem(
                    title=title,
                    source="youtube",
                    source_url=(
                        f"https://www.youtube.com/watch?v={item.get('id', '')}"
                    ),
                    region=region,
                    popularity=score,
                    published_at=snippet.get("publishedAt", ""),
                    description=str(snippet.get("description", ""))[:300],
                ))

        except Exception as exc:
            log.warning("YouTube trends failed for region %s: %s", region, exc)

    log.info("YouTube trends: collected %d items", len(results))
    return results


# ---------------------------------------------------------------------------
# Source 2: GDELT News (worldwide)
# ---------------------------------------------------------------------------

def fetch_gdelt_trends() -> list[TrendItem]:
    """Fetch latest global news from GDELT (no API key needed)."""
    try:
        response = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": "sourcelang:english",
                "mode": "artlist",
                "maxrecords": 75,
                "format": "json",
                "sort": "datedesc",
                "timespan": "24h",
            },
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        items: list[TrendItem] = []

        for article in response.json().get("articles", []):
            title = str(article.get("title", "")).strip()
            url   = str(article.get("url",   "")).strip()
            if not title or not url:
                continue

            items.append(TrendItem(
                title=title,
                source="gdelt",
                source_url=url,
                region=str(article.get("sourcecountry", "WORLD")),
                popularity=1.0,
                published_at=str(article.get("seendate", "")),
                description="",
            ))

        log.info("GDELT trends: collected %d items", len(items))
        return items

    except Exception as exc:
        log.warning("GDELT failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Source 3: RSS Feeds
# ---------------------------------------------------------------------------

RSS_FEEDS: dict[str, str] = {
    # Breaking news
    "BBC World":          "https://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC Science":        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "Reuters World":      "https://feeds.reuters.com/reuters/worldNews",
    "Al Jazeera":         "https://www.aljazeera.com/xml/rss/all.xml",
    "Google News Top":    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "Google News Sci":    "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RZU0FtVnVHZ0pWVXlnQVAB",
    "Google News Tech":   "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB",
    # Science & Space
    "NASA":               "https://www.nasa.gov/rss/dyn/breaking_news.rss",
    "Space.com":          "https://www.space.com/feeds/all",
    "IFLScience":         "https://www.iflscience.com/rss/",
    "ScienceAlert":       "https://www.sciencealert.com/feed",
    "Futurism":           "https://futurism.com/feed",
    # Tech & Viral
    "TechCrunch":         "https://techcrunch.com/feed/",
    "The Verge":          "https://www.theverge.com/rss/index.xml",
    "Mashable":           "https://mashable.com/feeds/rss/all",
    "Interesting Eng":    "https://interestingengineering.com/feed",
    # Nature & Humans
    "Nat Geo":            "https://www.nationalgeographic.com/pages/article/rss-feed",
    "Smithsonian Mag":    "https://www.smithsonianmag.com/rss/latest_articles/",
}


def fetch_rss_trends() -> list[TrendItem]:
    """Parse multiple RSS feeds for trending headlines."""
    results: list[TrendItem] = []

    for source_name, feed_url in RSS_FEEDS.items():
        try:
            parsed = feedparser.parse(feed_url)

            for entry in parsed.entries[:20]:
                title = str(entry.get("title", "")).strip()
                if not title:
                    continue

                summary = str(entry.get("summary", entry.get("description", ""))).strip()

                results.append(TrendItem(
                    title=title,
                    source=source_name,
                    source_url=str(entry.get("link", "")),
                    region="WORLD",
                    popularity=2.0,   # RSS items are always fresh/recent
                    published_at=str(entry.get("published", "")),
                    description=summary[:300],
                ))

        except Exception as exc:
            log.warning("RSS feed failed (%s): %s", source_name, exc)

    log.info("RSS trends: collected %d items", len(results))
    return results


# ---------------------------------------------------------------------------
# Source 3b: Google Trends (real-time, no API key needed)
# ---------------------------------------------------------------------------

GOOGLE_TRENDS_REGIONS = [
    ("US", "United States"),
    ("GB", "United Kingdom"),
    ("AU", "Australia"),
    ("CA", "Canada"),
    ("IN", "India"),
]


def fetch_google_trends() -> list[TrendItem]:
    """Fetch Google Trends daily search trends via RSS (no API key required)."""
    results: list[TrendItem] = []

    for geo_code, geo_name in GOOGLE_TRENDS_REGIONS:
        try:
            url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo_code}"
            parsed = feedparser.parse(url)

            for entry in parsed.entries[:20]:
                title = str(entry.get("title", "")).strip()
                if not title:
                    continue

                # Google Trends RSS includes traffic estimate in the <ht:approx_traffic>
                # element, which feedparser exposes as entry.ht_approx_traffic (not in "tags",
                # which only holds <category> elements).
                traffic = 1000.0
                try:
                    raw_traffic = entry.get("ht_approx_traffic", "")
                    if raw_traffic:
                        traffic = float(
                            str(raw_traffic).replace("+", "").replace(",", "").strip() or "1000"
                        )
                except Exception:
                    pass

                summary = str(entry.get("summary", "")).strip()

                results.append(TrendItem(
                    title=title,
                    source=f"google_trends/{geo_code}",
                    source_url=str(entry.get("link", "")),
                    region=geo_code,
                    popularity=traffic,   # real search volume!
                    published_at=str(entry.get("published", "")),
                    description=summary[:300],
                ))

        except Exception as exc:
            log.warning("Google Trends failed for %s: %s", geo_name, exc)

    log.info("Google Trends: collected %d items", len(results))
    return results


# ---------------------------------------------------------------------------
# Source 4: Reddit Hot Posts (no API key needed)
# ---------------------------------------------------------------------------

REDDIT_SUBREDDITS = [
    "worldnews", "news", "science", "technology",
    "todayilearned", "interestingasfuck", "mildlyinteresting",
    "entertainment", "movies", "sports",
]


def fetch_reddit_trends() -> list[TrendItem]:
    """
    Fetch hot Reddit posts (public JSON endpoint).

    Reddit increasingly blocks bots — each subreddit is silently skipped
    on a 403 so the rest of the pipeline is never blocked.
    """
    results: list[TrendItem] = []

    # Reddit requires a descriptive user-agent to avoid 403 blocks
    headers = {
        "User-Agent": "AutoShorts-TrendCollector/2.0 (content research; non-commercial)",
        "Accept": "application/json",
    }

    for subreddit in REDDIT_SUBREDDITS:
        try:
            response = requests.get(
                f"https://www.reddit.com/r/{subreddit}/hot.json",
                params={"limit": 10},
                headers=headers,
                timeout=API_TIMEOUT_SECONDS,
            )

            # 403 = blocked by Reddit — skip silently (non-fatal)
            if response.status_code == 403:
                log.debug("Reddit r/%s blocked (403) — skipping", subreddit)
                continue

            response.raise_for_status()

            children = (
                response.json()
                .get("data", {})
                .get("children", [])
            )

            for child in children:
                post = child.get("data", {})
                title = str(post.get("title", "")).strip()
                if not title:
                    continue

                score = float(post.get("score", 0))

                results.append(TrendItem(
                    title=title,
                    source=f"reddit/{subreddit}",
                    source_url=f"https://reddit.com{post.get('permalink', '')}",
                    region="WORLD",
                    popularity=score,
                    published_at="",
                    description=str(post.get("selftext", ""))[:300],
                ))

            time.sleep(0.5)  # Reddit rate-limit courtesy

        except requests.exceptions.HTTPError as exc:
            log.debug("Reddit r/%s HTTP error (skipping): %s", subreddit, exc)
        except Exception as exc:
            log.warning("Reddit r/%s failed: %s", subreddit, exc)

    log.info("Reddit trends: collected %d items", len(results))
    return results


# ---------------------------------------------------------------------------
# Source 5: Hacker News (technology)
# ---------------------------------------------------------------------------

def fetch_hackernews_trends() -> list[TrendItem]:
    """Fetch top Hacker News stories."""
    try:
        ids_response = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=API_TIMEOUT_SECONDS,
        )
        ids_response.raise_for_status()
        story_ids = ids_response.json()[:30]

        results: list[TrendItem] = []

        for story_id in story_ids:
            try:
                story_response = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                    timeout=15,
                )
                story_response.raise_for_status()
                story = story_response.json()

                title = str(story.get("title", "")).strip()
                if not title:
                    continue

                results.append(TrendItem(
                    title=title,
                    source="hackernews",
                    source_url=str(story.get("url", "")),
                    region="WORLD",
                    popularity=float(story.get("score", 0)),
                    published_at="",
                    description="",
                ))

            except Exception:
                continue

        log.info("Hacker News trends: collected %d items", len(results))
        return results

    except Exception as exc:
        log.warning("Hacker News failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Source 6: NewsAPI (optional — requires API key)
# ---------------------------------------------------------------------------

def fetch_newsapi_trends() -> list[TrendItem]:
    """Fetch top headlines from NewsAPI (requires NEWS_API_KEY in .env)."""
    if not NEWS_API_KEY:
        return []

    try:
        response = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={
                "language": "en",
                "pageSize": 50,
                "apiKey": NEWS_API_KEY,
            },
            timeout=API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        results: list[TrendItem] = []

        for article in response.json().get("articles", []):
            title = str(article.get("title", "")).strip()
            if not title or title == "[Removed]":
                continue

            results.append(TrendItem(
                title=title,
                source="newsapi",
                source_url=str(article.get("url", "")),
                region="WORLD",
                popularity=1.0,
                published_at=str(article.get("publishedAt", "")),
                description=str(article.get("description", ""))[:300],
            ))

        log.info("NewsAPI trends: collected %d items", len(results))
        return results

    except Exception as exc:
        log.warning("NewsAPI failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Money-niche relevance filter
# ---------------------------------------------------------------------------

# Keywords that signal a trend is relevant to the Money & Wealth Psychology niche.
# Any trend whose title or description contains at least one of these words
# is kept; everything else is dropped before sending to Gemini.
_MONEY_KEYWORDS: tuple[str, ...] = (
    "money", "rich", "wealth", "billionaire", "millionaire", "salary",
    "income", "budget", "debt", "bank", "invest", "profit", "economy",
    "price", "inflation", "tax", "finance", "stock", "cost", "spend",
    "broke", "poor", "savings", "crypto", "scam", "fraud", "luxury",
    "expensive", "cheap", "afford", "loan", "credit", "cash", "dollar",
    "earn", "earning", "wage", "raise", "bonus", "pension", "retirement",
    "recession", "bankruptcy", "fee", "charge", "tip", "subscription",
    "paycheck", "payroll", "hedge", "fund", "venture", "startup",
    "entrepreneur", "business", "revenue", "interest", "rate", "housing",
    "rent", "mortgage", "insurance", "poverty", "inequality",
    "consumer", "spending", "shopping", "discount", "deal", "price hike",
    "cost of living", "minimum wage", "net worth",
)


def _is_money_relevant(item: "TrendItem") -> bool:
    """Return True if a trend item touches the Money & Wealth Psychology niche."""
    haystack = (item.title + " " + item.description).lower()
    return any(kw in haystack for kw in _MONEY_KEYWORDS)


def _filter_for_money_niche(
    items: list["TrendItem"],
    max_non_niche: int = 20,
) -> list["TrendItem"]:
    """
    Split items into niche-relevant and generic buckets.

    Niche-relevant items are kept in full (they directly fuel on-topic ideas).
    A small number of high-popularity generic items are appended afterwards so
    Gemini still has broader cultural context to draw evergreen angles from,
    without being swamped by off-niche noise.
    """
    niche: list[TrendItem] = []
    generic: list[TrendItem] = []

    for item in items:
        (niche if _is_money_relevant(item) else generic).append(item)

    # Keep only the most popular generic items as background context
    generic_sorted = sorted(generic, key=lambda x: x.popularity, reverse=True)
    filtered = niche + generic_sorted[:max_non_niche]

    log.info(
        "Niche filter: %d money-relevant + %d generic context = %d total (was %d)",
        len(niche), min(len(generic), max_non_niche), len(filtered), len(items),
    )
    return filtered


# ---------------------------------------------------------------------------
# Main aggregator
# ---------------------------------------------------------------------------

def collect_worldwide_trends() -> list[dict[str, Any]]:
    """
    Collect and merge trends from all sources.

    Returns a list of dicts (one per trend item) sorted by popularity
    descending. Each source is attempted independently so that a single
    failing API never blocks the whole collection.

    Deduplication is applied to avoid sending near-identical headlines
    to Gemini, which wastes context and produces repetitive ideas.

    Money-niche filtering is applied last: niche-relevant trends are
    prioritised, and only a small number of high-popularity generic items
    are kept as background context. This keeps the Gemini prompt focused
    and dramatically improves topic relevance.
    """
    log.info("Starting worldwide trend collection...")

    combined: list[TrendItem] = []

    for fetcher in (
        fetch_google_trends,       # real-time Google search volume (highest signal)
        fetch_youtube_trends,      # YouTube most-popular (multi-region)
        fetch_gdelt_trends,        # worldwide news
        fetch_rss_trends,          # curated editorial sources
        fetch_reddit_trends,       # community viral content
        fetch_hackernews_trends,   # tech community
        fetch_newsapi_trends,      # optional NewsAPI
    ):
        try:
            items = fetcher()
            combined.extend(items)
        except Exception as exc:
            log.error("Trend source %s raised unexpectedly: %s", fetcher.__name__, exc)

    # Sort by popularity descending
    combined.sort(key=lambda item: item.popularity, reverse=True)

    # Deduplicate: skip items whose title is too similar to an already-kept item
    seen_titles: list[str] = []
    deduped: list[TrendItem] = []
    for item in combined:
        title_lower = item.title.lower().strip()
        # Simple word-overlap check (avoid near-duplicate headlines)
        is_dup = False
        for seen in seen_titles:
            words_item = set(title_lower.split())
            words_seen = set(seen.split())
            overlap = len(words_item & words_seen) / max(len(words_item | words_seen), 1)
            if overlap > 0.65:
                is_dup = True
                break
        if not is_dup:
            seen_titles.append(title_lower)
            deduped.append(item)

    log.info(
        "Trends: %d raw -> %d after deduplication",
        len(combined), len(deduped),
    )

    # Apply money-niche filter — keep niche-relevant trends + top generic context
    niche_filtered = _filter_for_money_niche(deduped, max_non_niche=20)

    return [asdict(item) for item in niche_filtered]