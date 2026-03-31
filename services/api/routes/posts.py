"""Post API endpoints."""

import base64
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from services.api.dependencies import get_db, rate_limit
from services.api.schemas import (
    MediaItem,
    MetricsDataPoint,
    MetricsHistoryResponse,
    Pagination,
    PLATFORM_INFO,
    PostEngagement,
    PostListResponse,
    PostProfile,
    PostResponse,
    WorkPlatform,
)
from shared.db.models import ApiKey, Creator, MetricsSnapshot, Post

logger = structlog.get_logger()
router = APIRouter(prefix="/posts", tags=["Posts"])


# Format mapping from internal type to Phyllo-style format
_FORMAT_MAP = {
    "image": "IMAGE",
    "video": "VIDEO",
    "reel": "REEL",
    "carousel": "CAROUSEL",
    "story": "STORY",
    "short": "SHORT",
    "live": "LIVE",
}

# Type mapping (content placement)
_TYPE_MAP = {
    "image": "FEED",
    "video": "FEED",
    "carousel": "FEED",
    "reel": "REEL",
    "story": "STORY",
    "short": "SHORT",
    "live": "LIVE",
}

# Platform URL patterns
_POST_URL_MAP = {
    "instagram": "https://www.instagram.com/p/{code}",
    "tiktok": "https://www.tiktok.com/@{username}/video/{code}",
    "youtube": "https://www.youtube.com/watch?v={code}",
}

_PROFILE_URL_MAP = {
    "instagram": "https://www.instagram.com/{username}",
    "tiktok": "https://www.tiktok.com/@{username}",
    "youtube": "https://www.youtube.com/@{username}",
}


def _post_to_response(post: Post, creator: Creator | None = None) -> PostResponse:
    """Convert DB model to Phyllo-style API response."""
    media_items = []
    media_url = None
    thumbnail_url = None

    if post.media:
        for m in (post.media if isinstance(post.media, list) else []):
            media_items.append(MediaItem(
                type=m.get("type", "image"),
                url=m.get("url", ""),
                thumbnail_url=m.get("thumbnail_url"),
                duration_seconds=m.get("duration_seconds"),
                width=m.get("width"),
                height=m.get("height"),
            ))
        if media_items:
            media_url = media_items[0].url or None
            thumbnail_url = media_items[0].thumbnail_url or media_url

    # Build platform info
    platform = post.platform or "instagram"
    pinfo = PLATFORM_INFO.get(platform, PLATFORM_INFO["instagram"])

    # Build post URL
    post_url = None
    if post.platform_post_id:
        url_tpl = _POST_URL_MAP.get(platform)
        if url_tpl:
            username = creator.username if creator else ""
            post_url = url_tpl.format(code=post.platform_post_id, username=username)

    # Build profile info
    profile = None
    if creator:
        profile_url = _PROFILE_URL_MAP.get(platform, "").format(username=creator.username)
        profile = PostProfile(
            platform_username=creator.username,
            url=profile_url or None,
            image_url=creator.profile_image_url,
            is_verified=creator.is_verified,
        )

    # Caption as title (first 200 chars) and full description
    text = post.text_content or ""
    title = text[:200] if text else None
    description = text if text else None

    return PostResponse(
        id=post.id,
        creator_id=post.creator_id,
        work_platform=WorkPlatform(**pinfo),
        platform_content_id=post.platform_post_id,
        title=title,
        description=description,
        format=_FORMAT_MAP.get(post.post_type, "IMAGE"),
        type=_TYPE_MAP.get(post.post_type, "FEED"),
        url=post_url,
        media_url=media_url,
        thumbnail_url=thumbnail_url,
        media_urls=media_items,
        published_at=post.published_at,
        engagement=PostEngagement(
            like_count=post.like_count or 0,
            comment_count=post.comment_count or 0,
            share_count=post.share_count or 0,
            view_count=post.view_count if post.view_count else None,
            save_count=post.save_count if post.save_count else None,
            engagement_rate=float(post.engagement_rate) if post.engagement_rate else None,
        ),
        hashtags=post.hashtags or [],
        mentions=post.mentions or [],
        profile=profile,
        collected_at=post.collected_at,
        metrics_updated_at=post.metrics_updated_at,
    )


@router.get("/search", response_model=PostListResponse)
async def search_posts(
    q: str | None = Query(None, description="Search text in post captions"),
    hashtag: str | None = Query(None, description="Filter by hashtag (without #)"),
    platform: str | None = Query(None, description="Platform filter: instagram, tiktok, youtube (comma-separated)"),
    min_likes: int | None = Query(None, description="Minimum like count"),
    min_views: int | None = Query(None, description="Minimum view count"),
    type: str | None = Query(None, description="Post type: image, video, reel, carousel, story"),
    published_after: str | None = Query(None, description="ISO date (e.g. 2026-01-01)"),
    published_before: str | None = Query(None, description="ISO date (e.g. 2026-12-31)"),
    sort: str = Query(default="-published_at", description="Sort: -published_at, published_at, -like_count, -view_count"),
    cursor: str | None = Query(None, description="Pagination cursor from previous response"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page (max 100)"),
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Search posts across all creators with powerful filters.

    Combine multiple filters to find specific content. Results are returned in Phyllo-compatible format.

    **Examples:**
    ```
    GET /v1/posts/search?platform=instagram&min_likes=1000000
    GET /v1/posts/search?q=cricket&type=reel&sort=-like_count
    GET /v1/posts/search?hashtag=IPL&published_after=2026-03-01
    ```
    """
    query = select(Post)
    conditions = []

    if platform:
        platforms = [p.strip() for p in platform.split(",")]
        conditions.append(Post.platform.in_(platforms))
    if hashtag:
        conditions.append(Post.hashtags.any(hashtag))
    if q:
        conditions.append(Post.text_content.ilike(f"%{q}%"))
    if min_likes is not None:
        conditions.append(Post.like_count >= min_likes)
    if min_views is not None:
        conditions.append(Post.view_count >= min_views)
    if type:
        conditions.append(Post.post_type == type)
    if published_after:
        conditions.append(Post.published_at >= published_after)
    if published_before:
        conditions.append(Post.published_at <= published_before)

    if conditions:
        query = query.where(and_(*conditions))

    if cursor:
        try:
            last_id = base64.b64decode(cursor).decode()
            query = query.where(Post.id > last_id)
        except Exception:
            pass

    # Sorting
    sort_map = {
        "-published_at": Post.published_at.desc(),
        "published_at": Post.published_at.asc(),
        "-like_count": Post.like_count.desc(),
        "-view_count": Post.view_count.desc(),
    }
    order = sort_map.get(sort, Post.published_at.desc())
    query = query.options(selectinload(Post.creator)).order_by(order).limit(limit + 1)

    result = await db.execute(query)
    posts = list(result.scalars().all())

    has_more = len(posts) > limit
    posts = posts[:limit]

    next_cursor = None
    if has_more and posts:
        next_cursor = base64.b64encode(posts[-1].id.encode()).decode()

    return PostListResponse(
        data=[_post_to_response(p, p.creator) for p in posts],
        pagination=Pagination(has_more=has_more, next_cursor=next_cursor),
    )


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: str,
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Get a single post by ID.

    Returns full post details with engagement metrics, media URLs, and creator profile info.

    **Example:**
    ```
    GET /v1/posts/po_2kia9af79kjhs878
    ```
    """
    result = await db.execute(
        select(Post).options(selectinload(Post.creator)).where(Post.id == post_id)
    )
    post = result.scalar_one_or_none()

    if not post:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "not_found", "message": "Post not found", "status": 404}
        })

    return _post_to_response(post, post.creator)


@router.get("/{post_id}/metrics", response_model=MetricsHistoryResponse)
async def get_post_metrics(
    post_id: str,
    interval: str = Query(default="hourly", pattern="^(5m|15m|hourly|daily)$"),
    start_date: str | None = None,
    end_date: str | None = None,
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Get metrics history for a post."""
    # Verify post exists
    post_result = await db.execute(select(Post).where(Post.id == post_id))
    if not post_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={
            "error": {"code": "not_found", "message": "Post not found", "status": 404}
        })

    query = select(MetricsSnapshot).where(MetricsSnapshot.post_id == post_id)

    if start_date:
        query = query.where(MetricsSnapshot.captured_at >= start_date)
    if end_date:
        query = query.where(MetricsSnapshot.captured_at <= end_date)

    query = query.order_by(MetricsSnapshot.captured_at.asc()).limit(500)

    result = await db.execute(query)
    snapshots = result.scalars().all()

    return MetricsHistoryResponse(
        entity_id=post_id,
        data=[
            MetricsDataPoint(
                timestamp=s.captured_at,
                like_count=s.like_count,
                comment_count=s.comment_count,
                share_count=s.share_count,
                view_count=s.view_count,
                save_count=s.save_count,
            )
            for s in snapshots
        ],
    )
