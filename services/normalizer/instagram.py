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


class InstagramNormalizer(BaseNormalizer):
    PLATFORM = "instagram"

    def normalize_creator(self, raw: RawCreatorData) -> NormalizedCreator:
        d = raw.raw_data

        # Handle both web API and GraphQL response formats
        follower_count = (
            d.get("edge_followed_by", {}).get("count")
            or d.get("follower_count")
            or 0
        )
        following_count = (
            d.get("edge_follow", {}).get("count")
            or d.get("following_count")
            or 0
        )
        post_count = (
            d.get("edge_owner_to_timeline_media", {}).get("count")
            or d.get("media_count")
            or 0
        )

        bio = d.get("biography", d.get("bio", ""))
        external_url = d.get("external_url") or (d.get("bio_links", [{}])[0].get("url") if d.get("bio_links") else None)

        external_urls = []
        if external_url:
            external_urls.append({"type": "website", "url": external_url})

        # Calculate engagement rate: avg likes+comments per post / followers * 100
        engagement_rate = None
        if follower_count > 0 and post_count > 0:
            edges = d.get("edge_owner_to_timeline_media", {}).get("edges", [])
            if edges:
                total_engagement = sum(
                    (e.get("node", {}).get("edge_liked_by", {}).get("count", 0)
                     + e.get("node", {}).get("edge_media_to_comment", {}).get("count", 0))
                    for e in edges[:12]
                )
                avg_engagement = total_engagement / min(len(edges), 12)
                engagement_rate = round((avg_engagement / follower_count) * 100, 4)

        return NormalizedCreator(
            platform=self.PLATFORM,
            platform_id=raw.platform_id,
            username=d.get("username", raw.username),
            display_name=d.get("full_name"),
            bio=bio,
            profile_image_url=d.get("profile_pic_url_hd", d.get("profile_pic_url")),
            is_verified=d.get("is_verified", False),
            follower_count=self._safe_int(follower_count),
            following_count=self._safe_int(following_count),
            post_count=self._safe_int(post_count),
            engagement_rate=engagement_rate,
            categories=[d.get("category_name")] if d.get("category_name") else [],
            external_urls=external_urls,
        )

    def normalize_post(self, raw: RawPostData) -> NormalizedPost:
        d = raw.raw_data

        # Determine post type
        typename = d.get("__typename", "")
        is_video = d.get("is_video", False)
        product_type = d.get("product_type", "")

        if product_type == "clips" or "Reel" in typename:
            post_type = "reel"
        elif product_type == "story":
            post_type = "story"
        elif is_video:
            post_type = "video"
        elif d.get("edge_sidecar_to_children"):
            post_type = "carousel"
        else:
            post_type = "image"

        # Extract text
        caption_edges = d.get("edge_media_to_caption", {}).get("edges", [])
        text_content = ""
        if caption_edges:
            text_content = caption_edges[0].get("node", {}).get("text", "")
        elif d.get("caption"):
            if isinstance(d["caption"], dict):
                text_content = d["caption"].get("text", "")
            else:
                text_content = str(d["caption"])

        # Build media list
        media = []
        if is_video:
            media.append({
                "type": "video",
                "url": d.get("video_url", ""),
                "thumbnail_url": d.get("display_url", d.get("thumbnail_src", "")),
                "duration_seconds": d.get("video_duration"),
                "width": d.get("dimensions", {}).get("width"),
                "height": d.get("dimensions", {}).get("height"),
            })
        else:
            media.append({
                "type": "image",
                "url": d.get("display_url", d.get("thumbnail_src", "")),
                "thumbnail_url": d.get("thumbnail_src", ""),
                "width": d.get("dimensions", {}).get("width"),
                "height": d.get("dimensions", {}).get("height"),
            })

        # Metrics
        like_count = self._safe_int(
            d.get("edge_media_preview_like", {}).get("count")
            or d.get("edge_liked_by", {}).get("count")
            or d.get("like_count")
        )
        comment_count = self._safe_int(
            d.get("edge_media_preview_comment", {}).get("count")
            or d.get("edge_media_to_comment", {}).get("count")
            or d.get("comment_count")
        )
        view_count = self._safe_int(d.get("video_view_count", d.get("play_count", 0)))

        # Timestamp
        published_at = None
        ts = d.get("taken_at_timestamp") or d.get("taken_at")
        if ts:
            published_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)

        return NormalizedPost(
            platform=self.PLATFORM,
            platform_post_id=d.get("shortcode", d.get("code", raw.platform_post_id)),
            creator_platform_id=raw.creator_platform_id,
            post_type=post_type,
            text_content=text_content,
            hashtags=extract_hashtags(text_content),
            mentions=extract_mentions(text_content),
            media=media,
            like_count=like_count,
            comment_count=comment_count,
            share_count=0,  # Instagram doesn't expose shares
            view_count=view_count,
            save_count=0,
            engagement_rate=None,
            published_at=published_at,
        )
