"""Creator posts sub-routes (nested under /creators/{id}/posts)."""

import base64

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.dependencies import get_db, rate_limit
from services.api.routes.posts import _post_to_response
from services.api.schemas import Pagination, PostListResponse
from shared.db.models import ApiKey, Creator, Post

logger = structlog.get_logger()
router = APIRouter(tags=["Posts"])


@router.get("/creators/{creator_id}/posts", response_model=PostListResponse)
async def get_creator_posts(
    creator_id: str,
    type: str | None = Query(None, description="Filter by post type: image, video, reel, carousel, story"),
    sort: str = Query(default="-published_at", description="Sort order: -published_at, published_at, -like_count, -view_count"),
    published_after: str | None = Query(None, description="ISO date filter (e.g. 2026-01-01)"),
    published_before: str | None = Query(None, description="ISO date filter (e.g. 2026-12-31)"),
    cursor: str | None = Query(None, description="Pagination cursor from previous response's `pagination.next_cursor`"),
    limit: int = Query(default=20, ge=1, le=100, description="Number of posts per page (max 100)"),
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Get all posts by a specific creator with pagination.

    Returns posts in Phyllo-compatible format with `work_platform`, `engagement`, `profile`, and `media_url` fields.
    Use the `cursor` from `pagination.next_cursor` to fetch subsequent pages.

    **Example:**
    ```
    GET /v1/creators/cr_qnvo4urvptsa1cn4/posts?limit=20&sort=-like_count
    ```

    **Pagination:**
    ```
    GET /v1/creators/cr_qnvo4urvptsa1cn4/posts?cursor=cG9fZ2QzMnk5NDc4ZXUyd2x2dA==
    ```
    """
    # Load creator for profile info in response
    creator_result = await db.execute(select(Creator).where(Creator.id == creator_id))
    creator = creator_result.scalar_one_or_none()

    query = select(Post).where(Post.creator_id == creator_id)
    conditions = []

    if type:
        conditions.append(Post.post_type == type)
    if published_after:
        conditions.append(Post.published_at >= published_after)
    if published_before:
        conditions.append(Post.published_at <= published_before)

    if conditions:
        query = query.where(and_(*conditions))

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_count = (await db.execute(count_query)).scalar() or 0

    if cursor:
        try:
            last_id = base64.b64decode(cursor).decode()
            query = query.where(Post.id > last_id)
        except Exception:
            pass

    sort_map = {
        "-published_at": Post.published_at.desc(),
        "published_at": Post.published_at.asc(),
        "-like_count": Post.like_count.desc(),
        "-view_count": Post.view_count.desc(),
    }
    order = sort_map.get(sort, Post.published_at.desc())
    query = query.order_by(order).limit(limit + 1)

    result = await db.execute(query)
    posts = list(result.scalars().all())

    has_more = len(posts) > limit
    posts = posts[:limit]

    next_cursor = None
    if has_more and posts:
        next_cursor = base64.b64encode(posts[-1].id.encode()).decode()

    return PostListResponse(
        data=[_post_to_response(p, creator) for p in posts],
        pagination=Pagination(has_more=has_more, next_cursor=next_cursor, total_count=total_count),
    )
