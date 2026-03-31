import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

from shared.config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


class ProxyType(str, Enum):
    RESIDENTIAL = "residential"
    DATACENTER = "datacenter"


@dataclass
class Proxy:
    host: str
    port: int
    username: str
    password: str
    proxy_type: ProxyType
    _success_count: int = field(default=0, repr=False)
    _failure_count: int = field(default=0, repr=False)
    _cooldowns: dict[str, float] = field(default_factory=dict, repr=False)
    _last_used: float = field(default=0.0, repr=False)

    @property
    def url(self) -> str:
        return f"http://{self.username}:{self.password}@{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        total = self._success_count + self._failure_count
        if total == 0:
            return 1.0
        return self._success_count / total

    def in_cooldown(self, platform: str) -> bool:
        cooldown_until = self._cooldowns.get(platform, 0)
        return time.time() < cooldown_until

    def set_cooldown(self, platform: str, duration: int) -> None:
        self._cooldowns[platform] = time.time() + duration

    def record_success(self) -> None:
        self._success_count += 1
        self._last_used = time.time()

    def record_failure(self, status_code: int, platform: str) -> None:
        self._failure_count += 1
        self._last_used = time.time()

        if status_code == 429:
            self.set_cooldown(platform, random.randint(300, 900))
        elif status_code == 403:
            self.set_cooldown(platform, random.randint(600, 1800))
        elif status_code == 401:
            self.set_cooldown(platform, 3600)


class ProxyManager:
    """Manages proxy pools with health tracking, rotation, and cooldown."""

    def __init__(self) -> None:
        self._pools: dict[ProxyType, list[Proxy]] = {
            ProxyType.RESIDENTIAL: [],
            ProxyType.DATACENTER: [],
        }
        self._initialize_pools()

    def _initialize_pools(self) -> None:
        # BrightData residential proxy (rotates IPs automatically via their gateway)
        if settings.brightdata_host:
            for i in range(20):  # 20 sticky sessions
                self._pools[ProxyType.RESIDENTIAL].append(
                    Proxy(
                        host=settings.brightdata_host,
                        port=settings.brightdata_port,
                        username=f"{settings.brightdata_username}-session-{i}",
                        password=settings.brightdata_password,
                        proxy_type=ProxyType.RESIDENTIAL,
                    )
                )
            logger.info("proxy_pool_initialized", type="residential", count=20)

        # For MVP without BrightData, support direct proxies via env
        # Add datacenter proxies from a config file or env later
        logger.info(
            "proxy_manager_ready",
            residential=len(self._pools[ProxyType.RESIDENTIAL]),
            datacenter=len(self._pools[ProxyType.DATACENTER]),
        )

    def get_proxy(
        self,
        platform: str,
        priority: str = "normal",
        proxy_type: Optional[ProxyType] = None,
    ) -> Optional[Proxy]:
        """Get a healthy proxy for the given platform."""
        # High priority jobs prefer residential
        if priority == "high" or proxy_type == ProxyType.RESIDENTIAL:
            pool = self._pools[ProxyType.RESIDENTIAL]
        else:
            # Try datacenter first (cheaper), fall back to residential
            pool = self._pools[ProxyType.DATACENTER] or self._pools[ProxyType.RESIDENTIAL]

        if not pool:
            logger.warning("no_proxies_available", platform=platform)
            return None

        # Filter out proxies in cooldown for this platform
        available = [p for p in pool if not p.in_cooldown(platform)]

        if not available:
            logger.warning("all_proxies_in_cooldown", platform=platform)
            # Return the one with shortest remaining cooldown
            pool.sort(key=lambda p: p._cooldowns.get(platform, 0))
            return pool[0]

        # Sort by success rate, prefer less recently used
        available.sort(key=lambda p: (p.success_rate, -p._last_used), reverse=True)

        # Weighted random from top 5
        candidates = available[: min(5, len(available))]
        weights = [max(p.success_rate, 0.1) for p in candidates]
        total = sum(weights)
        weights = [w / total for w in weights]

        chosen = random.choices(candidates, weights=weights, k=1)[0]
        chosen._last_used = time.time()
        return chosen

    def report_result(
        self, proxy: Proxy, platform: str, success: bool, status_code: int = 200
    ) -> None:
        if success:
            proxy.record_success()
        else:
            proxy.record_failure(status_code, platform)
            logger.warning(
                "proxy_failure",
                proxy_host=proxy.host,
                platform=platform,
                status_code=status_code,
                success_rate=proxy.success_rate,
            )

    @property
    def pool_stats(self) -> dict:
        stats = {}
        for ptype, pool in self._pools.items():
            healthy = [p for p in pool if p.success_rate > 0.5]
            stats[ptype.value] = {
                "total": len(pool),
                "healthy": len(healthy),
                "avg_success_rate": (
                    sum(p.success_rate for p in pool) / len(pool) if pool else 0
                ),
            }
        return stats


# Singleton
proxy_manager = ProxyManager()
