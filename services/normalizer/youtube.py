from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from dateutil import parser as dateutil_parser

from services.collector.base import RawCreatorData, RawPostData
from services.normalizer.base import (
    BaseNormalizer,
    NormalizedCreator,
    NormalizedPost,
    extract_hashtags,
    extract_mentions,
)

logger = structlog.get_logger()


class YouTubeNormalizer(BaseNormalizer):
    PLATFORM = "youtube"

    def normalize_creator(self, raw: RawCreatorData) -> NormalizedCreator:
        d = raw.raw_data
        snippet = d.get("snippet", {})
        stats = d.get("statistics", {})
        branding = d.get("brandingSettings", {}).get("channel", {})

        subscriber_count = self._safe_int(stats.get("subscriberCount", 0))
        video_count = self._safe_int(stats.get("videoCount", 0))
        view_count = self._safe_int(stats.get("viewCount", 0))

        # YouTube engagement: avg views / subscribers * 100
        engagement_rate = None
        if subscriber_count > 0 and video_count > 0:
            avg_views = view_count / video_count
            engagement_rate = round((avg_views / subscriber_count) * 100, 4)

        external_urls = []
        custom_url = snippet.get("customUrl", "")
        if custom_url:
            external_urls.append({
                "type": "youtube",
                "url": f"https://www.youtube.com/{custom_url}",
            })

        # Get best profile image
        thumbnails = snippet.get("thumbnails", {})
        profile_img = (
            thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )

        return NormalizedCreator(
            platform=self.PLATFORM,
            platform_id=raw.platform_id,
            username=raw.username,
            display_name=snippet.get("title"),
            bio=snippet.get("description", ""),
            profile_image_url=profile_img,
            is_verified=False,  # YouTube API doesn't expose verification status directly
            follower_count=subscriber_count,
            following_count=0,  # YouTube doesn't have "following"
            post_count=video_count,
            engagement_rate=engagement_rate,
            categories=[branding.get("keywords", "")] if branding.get("keywords") else [],
            external_urls=external_urls,
        )

    def normalize_post(self, raw: RawPostData) -> NormalizedPost:
        d = raw.raw_data
        snippet = d.get("snippet", {})
        stats = d.get("statistics", {})
        content_details = d.get("contentDetails", {})

        title = snippet.get("title", "")
        description = snippet.get("description", "")
        text_content = f"{title}\n\n{description}" if description else title

        # Determine type — YouTube Shorts are <= 60s vertical videos
        duration = content_details.get("duration", "")
        post_type = "video"  # Default
        # Check if it's a Short (heuristic: duration <= 60s)
        if duration:
            # Parse ISO 8601 duration (PT1M30S)
            import re
            match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
            if match:
                hours = int(match.group(1) or 0)
                minutes = int(match.group(2) or 0)
                seconds = int(match.group(3) or 0)
                total_seconds = hours * 3600 + minutes * 60 + seconds
                if total_seconds <= 60:
                    post_type = "short"

        # Best thumbnail
        thumbnails = snippet.get("thumbnails", {})
        thumb_url = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or ""
        )

        media = [{
            "type": "video",
            "url": f"https://www.youtube.com/watch?v={raw.platform_post_id}",
            "thumbnail_url": thumb_url,
            "width": thumbnails.get("maxres", {}).get("width"),
            "height": thumbnails.get("maxres", {}).get("height"),
        }]

        # Timestamp
        published_at = None
        pub_str = snippet.get("publishedAt")
        if pub_str:
            try:
                published_at = dateutil_parser.isoparse(pub_str)
            except (ValueError, TypeError):
                pass

        return NormalizedPost(
            platform=self.PLATFORM,
            platform_post_id=raw.platform_post_id,
            creator_platform_id=raw.creator_platform_id,
            post_type=post_type,
            text_content=text_content,
            hashtags=extract_hashtags(text_content),
            mentions=extract_mentions(text_content),
            media=media,
            like_count=self._safe_int(stats.get("likeCount", 0)),
            comment_count=self._safe_int(stats.get("commentCount", 0)),
            share_count=0,
            view_count=self._safe_int(stats.get("viewCount", 0)),
            save_count=0,
            engagement_rate=None,
            published_at=published_at,
        )
