"""Tracking subscription endpoints."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.dependencies import get_db, rate_limit
from services.api.schemas import (
    Pagination,
    TrackCreatorRequest,
    TrackingListResponse,
    TrackingResponse,
)
from services.scheduler.tasks import collect_creator, collect_posts
from shared.db.models import ApiKey, Creator, TrackingSubscription

logger = structlog.get_logger()
router = APIRouter(prefix="/tracking", tags=["Tracking"])


@router.post("/creators", response_model=TrackingResponse, status_code=201)
async def track_creator(
    body: TrackCreatorRequest,
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Start tracking a creator for near real-time updates."""
    # Find or create the creator
    result = await db.execute(
        select(Creator).where(
            Creator.platform == body.platform,
            Creator.username == body.username,
        )
    )
    creator = result.scalar_one_or_none()

    if not creator:
        # Create a placeholder and trigger collection
        creator = Creator(
            platform=body.platform,
            platform_id="pending",
            username=body.username,
        )
        db.add(creator)
        await db.flush()

        # Trigger async collection
        collect_creator.delay(body.platform, body.username)
        collect_posts.delay(body.platform, body.username, limit=20)

    # Check for existing tracking
    existing = await db.execute(
        select(TrackingSubscription).where(
            TrackingSubscription.api_key_id == api_key.id,
            TrackingSubscription.creator_id == creator.id,
            TrackingSubscription.status == "active",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={
            "error": {"code": "already_exists", "message": "Already tracking this creator", "status": 409}
        })

    # Create tracking subscription
    tracking = TrackingSubscription(
        api_key_id=api_key.id,
        creator_id=creator.id,
        platform=body.platform,
        frequency=body.frequency,
    )
    db.add(tracking)
    await db.flush()

    return TrackingResponse(
        id=tracking.id,
        creator_id=creator.id,
        platform=body.platform,
        frequency=body.frequency,
        status="active",
        created_at=tracking.created_at,
    )


@router.get("/creators", response_model=TrackingListResponse)
async def list_tracking(
    status: str = Query(default="active", pattern="^(active|paused|all)$"),
    platform: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """List tracked creators for the current API key."""
    query = select(TrackingSubscription).where(
        TrackingSubscription.api_key_id == api_key.id
    )

    if status != "all":
        query = query.where(TrackingSubscription.status == status)
    if platform:
        query = query.where(TrackingSubscription.platform == platform)

    query = query.limit(limit)
    result = await db.execute(query)
    trackings = result.scalars().all()

    return TrackingListResponse(
        data=[
            TrackingResponse(
                id=t.id,
                creator_id=t.creator_id,
                platform=t.platform,
                frequency=t.frequency,
                status=t.status,
                created_at=t.created_at,
            )
            for t in trackings
        ],
        pagination=Pagination(has_more=False),
    )


@router.delete("/creators/{tracking_id}", status_code=204)
async def stop_tracking(
    tracking_id: str,
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Stop tracking a creator."""
    result = await db.execute(
        select(TrackingSubscription).where(
            TrackingSubscription.id == tracking_id,
            TrackingSubscription.api_key_id == api_key.id,
        )
    )
    tracking = result.scalar_one_or_none()

    if not tracking:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "not_found", "message": "Tracking subscription not found", "status": 404}
        })

    tracking.status = "cancelled"
