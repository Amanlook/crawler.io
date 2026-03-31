import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import structlog

from services.collector.base import RawCreatorData, RawPostData

logger = structlog.get_logger()


@dataclass
class NormalizedCreator:
    platform: str
    platform_id: str
    username: str
    display_name: Optional[str]
    bio: Optional[str]
    profile_image_url: Optional[str]
    is_verified: bool
    follower_count: int
    following_count: int
    post_count: int
    engagement_rate: Optional[float]
    categories: list[str]
    external_urls: list[dict[str, str]]


@dataclass
class NormalizedPost:
    platform: str
    platform_post_id: str
    creator_platform_id: str
    post_type: str  # image, video, reel, short, carousel, story, live
    text_content: Optional[str]
    hashtags: list[str]
    mentions: list[str]
    media: list[dict[str, Any]]
    like_count: int
    comment_count: int
    share_count: int
    view_count: int
    save_count: int
    engagement_rate: Optional[float]
    published_at: Optional[datetime]


def extract_hashtags(text: str) -> list[str]:
    """Extract hashtags from text content."""
    if not text:
        return []
    return re.findall(r"#(\w+)", text)


def extract_mentions(text: str) -> list[str]:
    """Extract @mentions from text content."""
    if not text:
        return []
    return re.findall(r"@(\w+)", text)


class BaseNormalizer(ABC):
    """Abstract base for platform-specific normalizers."""

    PLATFORM: str = ""

    @abstractmethod
    def normalize_creator(self, raw: RawCreatorData) -> NormalizedCreator:
        ...

    @abstractmethod
    def normalize_post(self, raw: RawPostData) -> NormalizedPost:
        ...

    def _safe_int(self, value: Any, default: int = 0) -> int:
        """Safely convert a value to int."""
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _safe_float(self, value: Any, default: Optional[float] = None) -> Optional[float]:
        """Safely convert a value to float."""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
