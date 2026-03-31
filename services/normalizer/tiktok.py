from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from services.collector.base import RawCreatorData, RawPostData
from services.normalizer.base import (
    BaseNormalizer,
    NormalizedCreator,
    NormalizedPost,
    extract_hashtags,
    extract_mentions,
)

logger = structlog.get_logger()


class TikTokNormalizer(BaseNormalizer):
    PLATFORM = "tiktok"

    def normalize_creator(self, raw: RawCreatorData) -> NormalizedCreator:
        d = raw.raw_data
        user = d.get("user", d)
        stats = d.get("stats", {})

        follower_count = self._safe_int(stats.get("followerCount", 0))
        heart_count = self._safe_int(stats.get("heartCount", 0))
        video_count = self._safe_int(stats.get("videoCount", 0))

        # TikTok engagement: avg hearts / followers * 100
        engagement_rate = None
        if follower_count > 0 and video_count > 0:
            avg_hearts = heart_count / video_count if video_count else 0
            engagement_rate = round((avg_hearts / follower_count) * 100, 4)

        bio_link = user.get("bioLink", {})
        external_urls = []
        if bio_link and bio_link.get("link"):
            external_urls.append({"type": "website", "url": bio_link["link"]})

        return NormalizedCreator(
            platform=self.PLATFORM,
            platform_id=raw.platform_id,
            username=user.get("uniqueId", raw.username),
            display_name=user.get("nickname"),
            bio=user.get("signature", ""),
            profile_image_url=user.get("avatarLarger", user.get("avatarMedium")),
            is_verified=user.get("verified", False),
            follower_count=follower_count,
            following_count=self._safe_int(stats.get("followingCount", 0)),
            post_count=video_count,
            engagement_rate=engagement_rate,
            categories=[],
            external_urls=external_urls,
        )

    def normalize_post(self, raw: RawPostData) -> NormalizedPost:
        d = raw.raw_data
        stats = d.get("stats", {})
        video = d.get("video", {})
        desc = d.get("desc", "")

        # Extract hashtags from challenges and description
        hashtags = extract_hashtags(desc)
        challenges = d.get("challenges", [])
        for challenge in challenges:
            title = challenge.get("title", "")
            if title and title not in hashtags:
                hashtags.append(title)

        # Build media
        media = [{
            "type": "video",
            "url": video.get("playAddr", video.get("downloadAddr", "")),
            "thumbnail_url": video.get("cover", video.get("originCover", "")),
            "duration_seconds": video.get("duration"),
            "width": video.get("width"),
            "height": video.get("height"),
        }]

        # Timestamp
        published_at = None
        create_time = d.get("createTime")
        if create_time:
            published_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc)

        return NormalizedPost(
            platform=self.PLATFORM,
            platform_post_id=str(d.get("id", raw.platform_post_id)),
            creator_platform_id=raw.creator_platform_id,
            post_type="short",  # All TikTok posts are short-form video
            text_content=desc,
            hashtags=hashtags,
            mentions=extract_mentions(desc),
            media=media,
            like_count=self._safe_int(stats.get("diggCount", 0)),
            comment_count=self._safe_int(stats.get("commentCount", 0)),
            share_count=self._safe_int(stats.get("shareCount", 0)),
            view_count=self._safe_int(stats.get("playCount", 0)),
            save_count=self._safe_int(stats.get("collectCount", 0)),
            engagement_rate=None,
            published_at=published_at,
        )
