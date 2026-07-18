"""
AutoShorts Engine — shared data models.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrendItem:
    title: str
    source: str
    source_url: str
    region: str
    popularity: float
    published_at: str = ""
    description: str = ""


@dataclass
class TopicIdea:
    topic: str
    style: str            # funny | facts | story | educational | motivational
    trend_reason: str
    original_angle: str
    score: float = 0.0


@dataclass
class VideoPlan:
    title: str
    hook: str
    script: str
    keywords: list[str]       # visual search phrases
    description: str
    hashtags: list[str]
    thumbnail_text: str
    category: str
    voice: str                # Edge-TTS voice ID
    style: str = "facts"
    research_summary: str = ""


@dataclass
class VideoResult:
    topic: str
    topic_hash: str
    video_path: str
    title: str
    description: str
    hashtags: list[str]
    thumbnail_path: str
    youtube_video_id: str = ""
    upload_status: str = "pending"
    trend_source: str = ""
    script_hash: str = ""
    duration: float = 0.0