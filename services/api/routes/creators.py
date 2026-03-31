"""Creator API endpoints."""

import asyncio
import base64
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.dependencies import get_db, rate_limit
from services.api.schemas import (
    BulkLookupRequest,
    BulkLookupResponse,
    BulkLookupResultItem,
    CreatorListResponse,
    CreatorResponse,
    Pagination,
)
from services.scheduler.tasks import collect_creator, collect_posts
from shared.cache.redis import cache
from shared.db.models import ApiKey, Creator

logger = structlog.get_logger()
router = APIRouter(prefix="/creators", tags=["Creators"])


# ─── Inline collection helpers (fallback when Celery is down) ───

_IG_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


async def _inline_collect_creator(platform: str, username: str, db: AsyncSession) -> Creator | None:
    """Fetch a creator directly via httpx (with warmup), normalize, and upsert.
    Returns the Creator ORM object or None on failure.
    Uses BrightData proxy when configured for IP rotation.
    """
    import httpx

    if platform != "instagram":
        # Only Instagram inline collection is implemented for now
        return None

    # Get proxy URL if available
    from services.collector.proxy_manager import proxy_manager
    proxy_obj = proxy_manager.get_proxy("instagram", priority="high")
    proxy_url = proxy_obj.url if proxy_obj else None
    if proxy_url:
        logger.info("inline_using_proxy", host=proxy_obj.host)

    try:
        transport = httpx.AsyncHTTPTransport(proxy=proxy_url) if proxy_url else None
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            transport=transport,
        ) as client:
            # Warmup: seed cookies (csrftoken, mid, ig_did)
            try:
                await client.get("https://www.instagram.com/", headers=_BROWSER_HEADERS)
            except Exception:
                pass
            await asyncio.sleep(0.5)

            user_data = None

            # Strategy 1: Web Profile Info API
            try:
                resp = await client.get(
                    "https://www.instagram.com/api/v1/users/web_profile_info/",
                    params={"username": username},
                    headers=_IG_API_HEADERS,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    user_data = data.get("data", {}).get("user")
            except Exception as e:
                logger.warning("inline_web_api_failed", error=str(e))

            # Strategy 2: __a=1&__d=dis
            if not user_data:
                try:
                    resp = await client.get(
                        f"https://www.instagram.com/{username}/",
                        params={"__a": "1", "__d": "dis"},
                        headers=_IG_API_HEADERS,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        user_data = data.get("graphql", {}).get("user") or data.get("user")
                except Exception as e:
                    logger.warning("inline_public_json_failed", error=str(e))

            if not user_data:
                logger.error("inline_all_strategies_failed", username=username)
                if proxy_obj:
                    proxy_manager.report_result(proxy_obj, platform, False, 401)
                return None

            # Parse basics
            d = user_data
            platform_id = str(d.get("pk", d.get("id", "")))
            if not platform_id:
                return None

            bio = d.get("biography", "") or ""
            edge_bio = d.get("bio_links", [])
            external_urls = [link.get("url") for link in (edge_bio or []) if link.get("url")]
            if d.get("external_url") and d["external_url"] not in external_urls:
                external_urls.insert(0, d["external_url"])

            fc = d.get("edge_followed_by", {})
            follower_count = fc.get("count", 0) if isinstance(fc, dict) else (d.get("follower_count") or 0)
            fgc = d.get("edge_follow", {})
            following_count = fgc.get("count", 0) if isinstance(fgc, dict) else (d.get("following_count") or 0)
            epc = d.get("edge_owner_to_timeline_media", {})
            post_count = epc.get("count", 0) if isinstance(epc, dict) else (d.get("media_count") or 0)
            categories = [d["category_name"]] if d.get("category_name") else []

            now = datetime.now(timezone.utc)

            # Upsert
            result = await db.execute(
                select(Creator).where(Creator.platform == platform, Creator.platform_id == platform_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.username = d.get("username", username)
                existing.display_name = d.get("full_name", "")
                existing.bio = bio
                existing.profile_image_url = d.get("profile_pic_url_hd") or d.get("profile_pic_url")
                existing.is_verified = d.get("is_verified", False)
                existing.follower_count = follower_count
                existing.following_count = following_count
                existing.post_count = post_count
                existing.categories = categories
                existing.external_urls = external_urls
                existing.last_updated_at = now
                await db.commit()
                await db.refresh(existing)
                if proxy_obj:
                    proxy_manager.report_result(proxy_obj, platform, True, 200)
                return existing
            else:
                creator = Creator(
                    platform=platform,
                    platform_id=platform_id,
                    username=d.get("username", username),
                    display_name=d.get("full_name", ""),
                    bio=bio,
                    profile_image_url=d.get("profile_pic_url_hd") or d.get("profile_pic_url"),
                    is_verified=d.get("is_verified", False),
                    follower_count=follower_count,
                    following_count=following_count,
                    post_count=post_count,
                    categories=categories,
                    external_urls=external_urls,
                )
                db.add(creator)
                await db.commit()
                await db.refresh(creator)
                if proxy_obj:
                    proxy_manager.report_result(proxy_obj, platform, True, 200)
                return creator

    except Exception as e:
        logger.error("inline_collect_failed", platform=platform, username=username, error=str(e))
        if proxy_obj:
            proxy_manager.report_result(proxy_obj, platform, False, 0)
        return None


def _creator_to_response(creator: Creator) -> CreatorResponse:
    """Convert DB model to API response."""
    now = datetime.now(timezone.utc)
    if creator.last_updated_at:
        age = now - creator.last_updated_at
        if age < timedelta(minutes=5):
            freshness = "live"
        elif age < timedelta(hours=1):
            freshness = "recent"
        else:
            freshness = "stale"
    else:
        freshness = "stale"

    return CreatorResponse(
        id=creator.id,
        platform=creator.platform,
        platform_id=creator.platform_id,
        username=creator.username,
        display_name=creator.display_name,
        bio=creator.bio,
        profile_image_url=creator.profile_image_url,
        is_verified=creator.is_verified,
        follower_count=creator.follower_count or 0,
        following_count=creator.following_count or 0,
        post_count=creator.post_count or 0,
        engagement_rate=float(creator.engagement_rate) if creator.engagement_rate else None,
        categories=creator.categories or [],
        external_urls=creator.external_urls or [],
        first_seen_at=creator.first_seen_at,
        last_updated_at=creator.last_updated_at,
        data_freshness=freshness,
    )


@router.get("/lookup", response_model=CreatorResponse)
async def lookup_creator(
    platform: str = Query(..., pattern="^(instagram|tiktok|youtube)$", description="Social media platform", examples=["instagram"]),
    username: str = Query(..., min_length=1, max_length=128, description="Creator username (without @)", examples=["virat.kohli"]),
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Look up a creator by platform and username.

    Returns the creator profile with follower counts, bio, categories, and data freshness indicator.
    If the creator is not yet in our database, returns **202 Accepted** and triggers async collection — retry after 10-30 seconds.

    **Example:**
    ```
    GET /v1/creators/lookup?platform=instagram&username=virat.kohli
    ```
    """
    # Check cache first
    cache_key = f"creator:{platform}:{username}"
    cached = await cache.get(cache_key)
    if cached:
        return CreatorResponse(**cached)

    # Check database
    result = await db.execute(
        select(Creator).where(
            Creator.platform == platform,
            Creator.username == username,
        )
    )
    creator = result.scalar_one_or_none()

    if creator:
        response = _creator_to_response(creator)
        await cache.set(cache_key, response.model_dump(mode="json"), ttl=300)

        # If data is stale, trigger async refresh
        if response.data_freshness == "stale":
            try:
                collect_creator.delay(platform, username)
            except Exception:
                logger.warning("celery_unavailable", action="refresh_creator")

        return response

    # Not in DB — collect inline (Celery .delay() silently queues even
    # without workers, so we always try inline first for immediate response)
    logger.info("inline_collect_attempt", platform=platform, username=username)
    creator = await _inline_collect_creator(platform, username, db)
    if creator:
        response = _creator_to_response(creator)
        await cache.set(cache_key, response.model_dump(mode="json"), ttl=300)

        # Also queue background refresh via Celery (best-effort)
        try:
            collect_posts.delay(platform, username, limit=20)
        except Exception:
            pass

        return response

    # Inline failed — queue to Celery as last resort and tell user to retry
    try:
        collect_creator.delay(platform, username)
        collect_posts.delay(platform, username, limit=20)
    except Exception:
        pass

    raise HTTPException(
        status_code=503,
        detail={
            "message": (
                f"Unable to fetch @{username} from {platform}. "
                f"The platform may be rate-limiting requests. "
                f"Try again in a few minutes."
            ),
            "retry_after": 120,
        },
    )


@router.get("/{creator_id}", response_model=CreatorResponse)
async def get_creator(
    creator_id: str,
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Get a creator by internal ID.

    **Example:**
    ```
    GET /v1/creators/cr_qnvo4urvptsa1cn4
    ```
    """
    result = await db.execute(select(Creator).where(Creator.id == creator_id))
    creator = result.scalar_one_or_none()

    if not creator:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "not_found", "message": "Creator not found", "status": 404}
        })

    return _creator_to_response(creator)


@router.get("/search", response_model=CreatorListResponse)  # NOTE: must be before /{creator_id}
async def search_creators(
    q: str | None = None,
    platform: str | None = Query(None, pattern="^(instagram|tiktok|youtube)$"),
    min_followers: int | None = None,
    max_followers: int | None = None,
    verified: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Search creators with filters."""
    query = select(Creator)
    conditions = []

    if platform:
        conditions.append(Creator.platform == platform)
    if min_followers is not None:
        conditions.append(Creator.follower_count >= min_followers)
    if max_followers is not None:
        conditions.append(Creator.follower_count <= max_followers)
    if verified is not None:
        conditions.append(Creator.is_verified == verified)
    if q:
        search_term = f"%{q}%"
        conditions.append(
            or_(
                Creator.username.ilike(search_term),
                Creator.display_name.ilike(search_term),
                Creator.bio.ilike(search_term),
            )
        )

    if conditions:
        query = query.where(and_(*conditions))

    # Cursor-based pagination (cursor = base64 encoded last_id)
    if cursor:
        try:
            last_id = base64.b64decode(cursor).decode()
            query = query.where(Creator.id > last_id)
        except Exception:
            pass

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Fetch results
    query = query.order_by(Creator.follower_count.desc()).limit(limit + 1)
    result = await db.execute(query)
    creators = list(result.scalars().all())

    has_more = len(creators) > limit
    creators = creators[:limit]

    next_cursor = None
    if has_more and creators:
        next_cursor = base64.b64encode(creators[-1].id.encode()).decode()

    return CreatorListResponse(
        data=[_creator_to_response(c) for c in creators],
        pagination=Pagination(
            has_more=has_more,
            next_cursor=next_cursor,
            total_count=total,
        ),
    )


@router.post("/bulk-lookup", response_model=BulkLookupResponse)
async def bulk_lookup(
    body: BulkLookupRequest,
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Look up multiple creators at once (max 100)."""
    results: list[BulkLookupResultItem] = []

    for item in body.lookups:
        result = await db.execute(
            select(Creator).where(
                Creator.platform == item.platform,
                Creator.username == item.username,
            )
        )
        creator = result.scalar_one_or_none()

        if creator:
            results.append(BulkLookupResultItem(
                platform=item.platform,
                username=item.username,
                creator=_creator_to_response(creator),
            ))
        else:
            # Queue collection
            collect_creator.delay(item.platform, item.username)
            results.append(BulkLookupResultItem(
                platform=item.platform,
                username=item.username,
                error="Not found — collection queued. Retry in 30 seconds.",
            ))

    return BulkLookupResponse(results=results)
