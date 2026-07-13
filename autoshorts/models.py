from dataclasses import dataclass


@dataclass
class VideoPlan:
    title: str
    hook: str
    script: str
    keywords: list[str]
    description: str
    hashtags: list[str]
    thumbnail_text: str
    category: str
    voice: str


@dataclass
class TrendItem:
    title: str
    channel: str
    views: int
    video_id: str


@dataclass
class AnalyticsSummary:
    views: int = 0
    likes: int = 0
    comments: int = 0
    average_view_duration: float = 0.0
    average_view_percentage: float = 0.0
    subscribers_gained: int = 0