"""FastAPI dependencies: auth, DB session, rate limiting."""

import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.cache.redis import cache
from shared.db.database import async_session_factory
from shared.db.models import ApiKey

logger = structlog.get_logger()

# ─── Rate Limit Config Per Tier ───────────────────
TIER_LIMITS = {
    "free":       {"rpm": 10,  "daily": 100},
    "starter":    {"rpm": 100, "daily": 10_000},
    "pro":        {"rpm": 500, "daily": 100_000},
    "enterprise": {"rpm": 2000, "daily": 1_000_000},
}


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def authenticate(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Validate API key from Authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail={
            "error": {"code": "authentication_failed", "message": "Missing Authorization header", "status": 401}
        })

    # Expect: Bearer sk_live_xxxxx
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail={
            "error": {"code": "authentication_failed", "message": "Invalid Authorization format. Use: Bearer <api_key>", "status": 401}
        })

    raw_key = parts[1].strip()

    # Hash the key for lookup
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=401, detail={
            "error": {"code": "authentication_failed", "message": "Invalid API key", "status": 401}
        })

    # Update last used timestamp (fire-and-forget, don't block)
    api_key.last_used_at = datetime.now(timezone.utc)

    return api_key


async def rate_limit(
    request: Request,
    api_key: ApiKey = Depends(authenticate),
) -> ApiKey:
    """Check rate limits for the authenticated API key."""
    limits = TIER_LIMITS.get(api_key.tier, TIER_LIMITS["free"])

    # Per-minute rate limit
    minute_key = f"ratelimit:rpm:{api_key.id}:{int(time.time()) // 60}"
    current_rpm = await cache.incr(minute_key, ttl=60)

    # Per-day rate limit
    day_key = f"ratelimit:daily:{api_key.id}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    current_daily = await cache.incr(day_key, ttl=86400)

    # Set rate limit headers on response
    request.state.rate_limit_limit = limits["rpm"]
    request.state.rate_limit_remaining = max(0, limits["rpm"] - current_rpm)
    request.state.rate_limit_reset = (int(time.time()) // 60 + 1) * 60

    if current_rpm > limits["rpm"]:
        retry_after = 60 - (int(time.time()) % 60)
        raise HTTPException(status_code=429, detail={
            "error": {
                "code": "rate_limit_exceeded",
                "message": f"Rate limit exceeded: {limits['rpm']} requests per minute",
                "status": 429,
                "retry_after": retry_after,
            }
        })

    if current_daily > limits["daily"]:
        raise HTTPException(status_code=429, detail={
            "error": {
                "code": "rate_limit_exceeded",
                "message": f"Daily limit exceeded: {limits['daily']} requests per day",
                "status": 429,
            }
        })

    return api_key
