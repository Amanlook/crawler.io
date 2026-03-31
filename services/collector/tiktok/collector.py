import json
from datetime import datetime, timezone
from typing import Optional

import structlog

from services.collector.base import (
    BaseCollector,
    CollectorError,
    RawCreatorData,
    RawPostData,
)

logger = structlog.get_logger()


class TikTokCollector(BaseCollector):
    """TikTok data collector using web API endpoints."""

    PLATFORM = "tiktok"
    BASE_DELAY = 1.5

    WEB_API_BASE = "https://www.tiktok.com/api"

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers.update({
            "Referer": "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com",
        })
        return headers

    async def collect_creator(self, username: str) -> RawCreatorData:
        """Fetch TikTok creator profile data."""
        logger.info("collecting_tiktok_creator", username=username)

        # Strategy 1: TikTok web API
        try:
            url = f"{self.WEB_API_BASE}/user/detail/"
            params = {"uniqueId": username, "aid": "1988"}
            response = await self._request(url, params=params)
            user_info = response.get("userInfo", {})
            user_data = user_info.get("user", {})

            if not user_data:
                raise CollectorError(f"No user data for @{username}")

            return RawCreatorData(
                platform=self.PLATFORM,
                platform_id=str(user_data.get("id", "")),
                username=username,
                raw_data=user_info,  # Contains user + stats
                collected_at=datetime.now(timezone.utc),
            )
        except CollectorError:
            raise
        except Exception as e:
            logger.error("tiktok_creator_collection_failed", username=username, error=str(e))
            raise CollectorError(f"Failed to collect TikTok creator @{username}") from e

    async def collect_posts(self, username: str, limit: int = 50) -> list[RawPostData]:
        """Fetch recent TikTok posts for a creator."""
        logger.info("collecting_tiktok_posts", username=username, limit=limit)

        creator = await self.collect_creator(username)
        sec_uid = creator.raw_data.get("user", {}).get("secUid", "")

        if not sec_uid:
            raise CollectorError(f"Could not get secUid for @{username}")

        posts: list[RawPostData] = []
        cursor: int = 0

        while len(posts) < limit:
            try:
                url = f"{self.WEB_API_BASE}/post/item_list/"
                params = {
                    "secUid": sec_uid,
                    "count": min(35, limit - len(posts)),
                    "cursor": str(cursor),
                    "aid": "1988",
                }
                response = await self._request(url, params=params)
                items = response.get("itemList", [])

                if not items:
                    break

                for item in items:
                    posts.append(
                        RawPostData(
                            platform=self.PLATFORM,
                            platform_post_id=str(item.get("id", "")),
                            creator_platform_id=creator.platform_id,
                            raw_data=item,
                            collected_at=datetime.now(timezone.utc),
                        )
                    )

                if not response.get("hasMore", False):
                    break
                cursor = response.get("cursor", 0)

            except CollectorError:
                logger.warning("tiktok_posts_partial", collected=len(posts))
                break

        logger.info("tiktok_posts_collected", username=username, count=len(posts))
        return posts[:limit]

    async def collect_post_metrics(self, post_id: str) -> dict:
        """Fetch updated metrics for a TikTok post."""
        url = f"{self.WEB_API_BASE}/item/detail/"
        params = {"itemId": post_id, "aid": "1988"}

        try:
            response = await self._request(url, params=params)
            item = response.get("itemInfo", {}).get("itemStruct", {})
            stats = item.get("stats", {})
            return {
                "like_count": stats.get("diggCount", 0),
                "comment_count": stats.get("commentCount", 0),
                "share_count": stats.get("shareCount", 0),
                "view_count": stats.get("playCount", 0),
            }
        except CollectorError as e:
            logger.warning("tiktok_metrics_failed", post_id=post_id, error=str(e))
            raise
