"""Webhook management endpoints."""

import hashlib

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.dependencies import get_db, rate_limit
from services.api.schemas import WebhookCreateRequest, WebhookResponse
from shared.db.models import ApiKey, Webhook

logger = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

VALID_EVENTS = {
    "post.created",
    "post.updated",
    "metrics.updated",
    "creator.updated",
    "creator.new_post",
}


@router.post("", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    body: WebhookCreateRequest,
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Register a new webhook endpoint."""
    # Validate events
    invalid = set(body.events) - VALID_EVENTS
    if invalid:
        raise HTTPException(status_code=400, detail={
            "error": {
                "code": "invalid_request",
                "message": f"Invalid events: {', '.join(invalid)}. Valid: {', '.join(sorted(VALID_EVENTS))}",
                "status": 400,
            }
        })

    webhook = Webhook(
        api_key_id=api_key.id,
        url=body.url,
        events=body.events,
        filters=body.filters,
        secret=hashlib.sha256(body.secret.encode()).hexdigest(),
    )
    db.add(webhook)
    await db.flush()

    return WebhookResponse(
        id=webhook.id,
        url=body.url,
        events=body.events,
        filters=body.filters,
        is_active=True,
        created_at=webhook.created_at,
    )


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """List all webhooks for the current API key."""
    result = await db.execute(
        select(Webhook).where(
            Webhook.api_key_id == api_key.id,
            Webhook.is_active == True,
        )
    )
    webhooks = result.scalars().all()

    return [
        WebhookResponse(
            id=w.id,
            url=w.url,
            events=w.events,
            filters=w.filters,
            is_active=w.is_active,
            created_at=w.created_at,
        )
        for w in webhooks
    ]


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    api_key: ApiKey = Depends(rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook."""
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.api_key_id == api_key.id,
        )
    )
    webhook = result.scalar_one_or_none()

    if not webhook:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "not_found", "message": "Webhook not found", "status": 404}
        })

    webhook.is_active = False
