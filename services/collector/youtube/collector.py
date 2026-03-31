from datetime import datetime, timezone
from typing import Optional

import structlog

from services.collector.base import (
    BaseCollector,
    CollectorError,
    RawCreatorData,
    RawPostData,
)
from shared.config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


class YouTubeCollector(BaseCollector):
    """YouTube data collector using official Data API v3."""

    PLATFORM = "youtube"
    BASE_DELAY = 0.5  # Official API is more lenient

    API_BASE = "https://www.googleapis.com/youtube/v3"

    def _api_params(self, **kwargs: str) -> dict[str, str]:
        """Add API key to params."""
        params = {"key": settings.youtube_api_key}
        params.update(kwargs)
        return params

    async def collect_creator(self, username: str) -> RawCreatorData:
        """Fetch YouTube channel data by username or handle."""
        logger.info("collecting_youtube_creator", username=username)

        # Try by handle first (@username)
        handle = username if username.startswith("@") else f"@{username}"

        try:
            url = f"{self.API_BASE}/channels"
            params = self._api_params(
                forHandle=handle,
                part="snippet,statistics,brandingSettings,contentDetails",
            )
            response = await self._request(url, params=params, proxy_priority="low")
            items = response.get("items", [])

            if not items:
                # Try by custom URL / username
                params = self._api_params(
                    forUsername=username,
                    part="snippet,statistics,brandingSettings,contentDetails",
                )
                response = await self._request(url, params=params, proxy_priority="low")
                items = response.get("items", [])

            if not items:
                raise CollectorError(f"YouTube channel not found: {username}")

            channel = items[0]
            return RawCreatorData(
                platform=self.PLATFORM,
                platform_id=channel["id"],
                username=username,
                raw_data=channel,
                collected_at=datetime.now(timezone.utc),
            )
        except CollectorError:
            raise
        except Exception as e:
            raise CollectorError(f"Failed to collect YouTube channel @{username}") from e

    async def collect_posts(self, username: str, limit: int = 50) -> list[RawPostData]:
        """Fetch recent videos for a YouTube channel."""
        logger.info("collecting_youtube_posts", username=username, limit=limit)

        creator = await self.collect_creator(username)
        channel_id = creator.platform_id

        # Get uploads playlist ID
        uploads_playlist = (
            creator.raw_data.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads", "")
        )

        if not uploads_playlist:
            raise CollectorError(f"No uploads playlist for channel {channel_id}")

        # Fetch playlist items
        posts: list[RawPostData] = []
        page_token: Optional[str] = None

        while len(posts) < limit:
            try:
                url = f"{self.API_BASE}/playlistItems"
                params = self._api_params(
                    playlistId=uploads_playlist,
                    part="snippet,contentDetails",
                    maxResults=str(min(50, limit - len(posts))),
                )
                if page_token:
                    params["pageToken"] = page_token

                response = await self._request(url, params=params, proxy_priority="low")
                items = response.get("items", [])

                if not items:
                    break

                # Get video IDs for statistics
                video_ids = [
                    item["contentDetails"]["videoId"]
                    for item in items
                    if "contentDetails" in item
                ]

                # Batch fetch video statistics
                video_stats = await self._fetch_video_stats(video_ids)

                for item in items:
                    video_id = item.get("contentDetails", {}).get("videoId", "")
                    # Merge stats into item data
                    item["statistics"] = video_stats.get(video_id, {})

                    posts.append(
                        RawPostData(
                            platform=self.PLATFORM,
                            platform_post_id=video_id,
                            creator_platform_id=channel_id,
                            raw_data=item,
                            collected_at=datetime.now(timezone.utc),
                        )
                    )

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            except CollectorError:
                logger.warning("youtube_posts_partial", collected=len(posts))
                break

        logger.info("youtube_posts_collected", username=username, count=len(posts))
        return posts[:limit]

    async def _fetch_video_stats(self, video_ids: list[str]) -> dict[str, dict]:
        """Batch fetch video statistics."""
        if not video_ids:
            return {}

        url = f"{self.API_BASE}/videos"
        params = self._api_params(
            id=",".join(video_ids),
            part="statistics,contentDetails",
        )

        try:
            response = await self._request(url, params=params, proxy_priority="low")
            stats = {}
            for item in response.get("items", []):
                stats[item["id"]] = item.get("statistics", {})
            return stats
        except CollectorError:
            return {}

    async def collect_post_metrics(self, video_id: str) -> dict:
        """Fetch updated metrics for a YouTube video."""
        stats_map = await self._fetch_video_stats([video_id])
        stats = stats_map.get(video_id, {})

        return {
            "like_count": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "view_count": int(stats.get("viewCount", 0)),
            "share_count": 0,  # YouTube doesn't expose share count via API
        }
