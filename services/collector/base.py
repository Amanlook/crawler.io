import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from services.collector.proxy_manager import Proxy, ProxyManager, proxy_manager

logger = structlog.get_logger()


@dataclass
class RawCreatorData:
    """Raw platform-specific creator data before normalization."""
    platform: str
    platform_id: str
    username: str
    raw_data: dict[str, Any]
    collected_at: datetime


@dataclass
class RawPostData:
    """Raw platform-specific post data before normalization."""
    platform: str
    platform_post_id: str
    creator_platform_id: str
    raw_data: dict[str, Any]
    collected_at: datetime


class CollectorError(Exception):
    """Base exception for collector errors."""
    pass


class RateLimitError(CollectorError):
    """Platform rate limit hit."""
    pass


class BlockedError(CollectorError):
    """IP/session blocked."""
    pass


class PlatformUnavailableError(CollectorError):
    """Platform is down or unreachable."""
    pass


class BaseCollector(ABC):
    """Abstract base for platform-specific data collectors."""

    PLATFORM: str = ""
    BASE_DELAY: float = 1.0  # Base delay between requests in seconds
    MAX_DELAY: float = 60.0

    def __init__(self, proxy_mgr: ProxyManager = proxy_manager) -> None:
        self.proxy_mgr = proxy_mgr
        self._session: Optional[aiohttp.ClientSession] = None
        self._consecutive_failures = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers=self._default_headers(),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _default_headers(self) -> dict[str, str]:
        """Default request headers. Override per platform."""
        user_agents = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        ]
        return {
            "User-Agent": random.choice(user_agents),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def _request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
        proxy_priority: str = "normal",
    ) -> dict:
        """Make an HTTP request through a proxy with error handling."""
        proxy = self.proxy_mgr.get_proxy(self.PLATFORM, priority=proxy_priority)
        session = await self._get_session()

        proxy_url = proxy.url if proxy else None

        try:
            # Add human-like delay
            delay = self.BASE_DELAY + random.uniform(0.5, 2.0)
            if self._consecutive_failures > 0:
                delay = min(delay * (2 ** self._consecutive_failures), self.MAX_DELAY)
            await asyncio.sleep(delay)

            async with session.request(
                method,
                url,
                headers=headers,
                params=params,
                proxy=proxy_url,
            ) as response:
                if response.status == 200:
                    self._consecutive_failures = 0
                    if proxy:
                        self.proxy_mgr.report_result(proxy, self.PLATFORM, True)
                    return await response.json()

                if response.status == 429:
                    if proxy:
                        self.proxy_mgr.report_result(proxy, self.PLATFORM, False, 429)
                    self._consecutive_failures += 1
                    raise RateLimitError(f"Rate limited by {self.PLATFORM}")

                if response.status in (401, 403):
                    if proxy:
                        self.proxy_mgr.report_result(proxy, self.PLATFORM, False, response.status)
                    self._consecutive_failures += 1
                    raise BlockedError(f"Blocked by {self.PLATFORM}: {response.status}")

                if response.status >= 500:
                    if proxy:
                        self.proxy_mgr.report_result(proxy, self.PLATFORM, False, response.status)
                    raise PlatformUnavailableError(f"{self.PLATFORM} returned {response.status}")

                # Other error
                if proxy:
                    self.proxy_mgr.report_result(proxy, self.PLATFORM, False, response.status)
                raise CollectorError(f"Unexpected status {response.status} from {self.PLATFORM}")

        except aiohttp.ClientError as e:
            if proxy:
                self.proxy_mgr.report_result(proxy, self.PLATFORM, False, 0)
            self._consecutive_failures += 1
            raise PlatformUnavailableError(f"Connection error to {self.PLATFORM}: {e}") from e

    @abstractmethod
    async def collect_creator(self, username: str) -> RawCreatorData:
        """Fetch creator/profile data by username."""
        ...

    @abstractmethod
    async def collect_posts(self, username: str, limit: int = 50) -> list[RawPostData]:
        """Fetch recent posts for a creator."""
        ...

    @abstractmethod
    async def collect_post_metrics(self, post_id: str) -> dict:
        """Fetch updated metrics for a specific post."""
        ...
