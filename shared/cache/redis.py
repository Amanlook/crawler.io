from typing import Optional

import orjson
import redis.asyncio as aioredis

from shared.config.settings import get_settings

settings = get_settings()

redis_client = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    max_connections=50,
)


class Cache:
    """Simple Redis cache wrapper with JSON serialization."""

    def __init__(self, client: aioredis.Redis = redis_client, prefix: str = "crawler"):
        self.client = client
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    async def get(self, key: str) -> Optional[dict]:
        raw = await self.client.get(self._key(key))
        if raw is None:
            return None
        return orjson.loads(raw)

    async def set(self, key: str, value: dict, ttl: int = 3600) -> None:
        await self.client.set(self._key(key), orjson.dumps(value), ex=ttl)

    async def delete(self, key: str) -> None:
        await self.client.delete(self._key(key))

    async def exists(self, key: str) -> bool:
        return bool(await self.client.exists(self._key(key)))

    async def incr(self, key: str, ttl: int = 60) -> int:
        pipe = self.client.pipeline()
        full_key = self._key(key)
        pipe.incr(full_key)
        pipe.expire(full_key, ttl)
        results = await pipe.execute()
        return results[0]

    async def get_ttl(self, key: str) -> int:
        return await self.client.ttl(self._key(key))


cache = Cache()
