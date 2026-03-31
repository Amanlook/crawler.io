"""Registry mapping platforms to their normalizer implementations."""

from services.normalizer.base import BaseNormalizer
from services.normalizer.instagram import InstagramNormalizer
from services.normalizer.tiktok import TikTokNormalizer
from services.normalizer.youtube import YouTubeNormalizer

NORMALIZERS: dict[str, BaseNormalizer] = {
    "instagram": InstagramNormalizer(),
    "tiktok": TikTokNormalizer(),
    "youtube": YouTubeNormalizer(),
}


def get_normalizer(platform: str) -> BaseNormalizer:
    normalizer = NORMALIZERS.get(platform)
    if not normalizer:
        raise ValueError(f"No normalizer registered for platform: {platform}")
    return normalizer
