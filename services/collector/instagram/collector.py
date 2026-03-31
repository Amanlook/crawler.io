from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from services.collector.base import (
    BaseCollector,
    BlockedError,
    CollectorError,
    RawCreatorData,
    RawPostData,
)

logger = structlog.get_logger()


class InstagramCollector(BaseCollector):
    """Instagram data collector using web API endpoints."""

    PLATFORM = "instagram"
    BASE_DELAY = 2.0  # Instagram is aggressive with rate limits

    # Instagram web API endpoints
    WEB_API_BASE = "https://www.instagram.com/api/v1"
    GRAPHQL_BASE = "https://www.instagram.com/graphql/query"

    # GraphQL query hashes (these change periodically — update as needed)
    QUERY_HASH_USER_POSTS = "69cba40317214236af40e7efa697781d"
    QUERY_HASH_USER_INFO = "c9100bf9110dd6361671f113dd02e7d6"

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers.update({
            "X-IG-App-ID": "936619743392459",  # Instagram web app ID
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.instagram.com/",
            "Origin": "https://www.instagram.com",
        })
        return headers

    async def collect_creator(self, username: str) -> RawCreatorData:
        """Fetch Instagram creator profile data."""
        logger.info("collecting_instagram_creator", username=username)

        # Strategy 1: Web profile API
        try:
            data = await self._fetch_profile_web_api(username)
            return RawCreatorData(
                platform=self.PLATFORM,
                platform_id=str(data.get("pk", data.get("id", ""))),
                username=username,
                raw_data=data,
                collected_at=datetime.now(timezone.utc),
            )
        except (CollectorError, KeyError) as e:
            logger.warning("instagram_web_api_failed", username=username, error=str(e))

        # Strategy 2: GraphQL API
        try:
            data = await self._fetch_profile_graphql(username)
            user_data = data.get("data", {}).get("user", data)
            return RawCreatorData(
                platform=self.PLATFORM,
                platform_id=str(user_data.get("id", "")),
                username=username,
                raw_data=user_data,
                collected_at=datetime.now(timezone.utc),
            )
        except (CollectorError, KeyError) as e:
            logger.warning("instagram_graphql_failed", username=username, error=str(e))

        # Strategy 3: Public page scrape (fallback)
        try:
            data = await self._fetch_profile_public(username)
            return RawCreatorData(
                platform=self.PLATFORM,
                platform_id=str(data.get("id", "")),
                username=username,
                raw_data=data,
                collected_at=datetime.now(timezone.utc),
            )
        except (CollectorError, KeyError) as e:
            logger.error("instagram_all_strategies_failed", username=username, error=str(e))
            raise CollectorError(f"All collection strategies failed for @{username}") from e

    async def _fetch_profile_web_api(self, username: str) -> dict:
        """Fetch profile via Instagram's web API."""
        url = f"{self.WEB_API_BASE}/users/web_profile_info/"
        params = {"username": username}
        response = await self._request(url, params=params)
        user_data = response.get("data", {}).get("user", {})
        if not user_data:
            raise CollectorError(f"No user data in web API response for @{username}")
        return user_data

    async def _fetch_profile_graphql(self, username: str) -> dict:
        """Fetch profile via GraphQL endpoint."""
        url = self.GRAPHQL_BASE
        params = {
            "query_hash": self.QUERY_HASH_USER_INFO,
            "variables": f'{{"username":"{username}"}}',
        }
        return await self._request(url, params=params)

    async def _fetch_profile_public(self, username: str) -> dict:
        """Fetch profile data from public page JSON."""
        url = f"https://www.instagram.com/{username}/"
        params = {"__a": "1", "__d": "dis"}
        response = await self._request(url, params=params)
        user_data = response.get("graphql", {}).get("user", {})
        if not user_data:
            user_data = response.get("user", response)
        return user_data

    async def collect_posts(self, username: str, limit: int = 50) -> list[RawPostData]:
        """Fetch recent posts for an Instagram creator."""
        logger.info("collecting_instagram_posts", username=username, limit=limit)

        # First get user ID
        creator_data = await self.collect_creator(username)
        user_id = creator_data.platform_id

        posts: list[RawPostData] = []
        end_cursor: Optional[str] = None
        batch_size = min(limit, 50)

        while len(posts) < limit:
            try:
                data = await self._fetch_user_posts(user_id, batch_size, end_cursor)
                edges = (
                    data.get("data", {})
                    .get("user", {})
                    .get("edge_owner_to_timeline_media", {})
                    .get("edges", [])
                )

                if not edges:
                    break

                for edge in edges:
                    node = edge.get("node", edge)
                    posts.append(
                        RawPostData(
                            platform=self.PLATFORM,
                            platform_post_id=node.get("shortcode", node.get("code", "")),
                            creator_platform_id=user_id,
                            raw_data=node,
                            collected_at=datetime.now(timezone.utc),
                        )
                    )

                # Pagination
                page_info = (
                    data.get("data", {})
                    .get("user", {})
                    .get("edge_owner_to_timeline_media", {})
                    .get("page_info", {})
                )
                if not page_info.get("has_next_page"):
                    break
                end_cursor = page_info.get("end_cursor")

            except CollectorError:
                logger.warning("instagram_posts_collection_partial", collected=len(posts))
                break

        logger.info("instagram_posts_collected", username=username, count=len(posts))
        return posts[:limit]

    async def _fetch_user_posts(
        self, user_id: str, count: int, after: Optional[str] = None
    ) -> dict:
        """Fetch user posts via GraphQL."""
        variables: dict[str, Any] = {"id": user_id, "first": count}
        if after:
            variables["after"] = after

        import json
        url = self.GRAPHQL_BASE
        params = {
            "query_hash": self.QUERY_HASH_USER_POSTS,
            "variables": json.dumps(variables),
        }
        return await self._request(url, params=params)

    async def collect_post_metrics(self, post_shortcode: str) -> dict:
        """Fetch metrics for a specific post."""
        url = f"https://www.instagram.com/p/{post_shortcode}/"
        params = {"__a": "1", "__d": "dis"}
        try:
            response = await self._request(url, params=params)
            media = (
                response.get("graphql", {}).get("shortcode_media", {})
                or response.get("items", [{}])[0]
            )
            return {
                "like_count": media.get("edge_media_preview_like", {}).get("count", media.get("like_count", 0)),
                "comment_count": media.get("edge_media_preview_comment", {}).get("count", media.get("comment_count", 0)),
                "view_count": media.get("video_view_count", media.get("play_count", 0)),
            }
        except (CollectorError, KeyError, IndexError) as e:
            logger.warning("instagram_metrics_failed", shortcode=post_shortcode, error=str(e))
            raise CollectorError(f"Failed to collect metrics for post {post_shortcode}") from e
