"""Pydantic schemas for API request/response models."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Shared ───────────────────────────────────────

class Pagination(BaseModel):
    has_more: bool = False
    next_cursor: Optional[str] = None
    total_count: Optional[int] = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    status: int
    retry_after: Optional[int] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: Optional[str] = None


# ─── Creator ──────────────────────────────────────

class CreatorResponse(BaseModel):
    id: str
    platform: str
    platform_id: str
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    profile_image_url: Optional[str] = None
    is_verified: bool = False
    follower_count: int = 0
    following_count: int = 0
    post_count: int = 0
    engagement_rate: Optional[float] = None
    categories: list[str] = []
    external_urls: list[dict[str, str]] = []
    first_seen_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    data_freshness: str = "recent"

    model_config = {"from_attributes": True}


class CreatorListResponse(BaseModel):
    data: list[CreatorResponse]
    pagination: Pagination


class CreatorLookupParams(BaseModel):
    platform: str = Field(..., pattern="^(instagram|tiktok|youtube)$")
    username: str = Field(..., min_length=1, max_length=128)


class CreatorSearchParams(BaseModel):
    q: Optional[str] = None
    platform: Optional[str] = None
    min_followers: Optional[int] = None
    max_followers: Optional[int] = None
    verified: Optional[bool] = None
    category: Optional[str] = None
    cursor: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)


class BulkLookupItem(BaseModel):
    platform: str = Field(..., pattern="^(instagram|tiktok|youtube)$")
    username: str


class BulkLookupRequest(BaseModel):
    lookups: list[BulkLookupItem] = Field(..., max_length=100)


class BulkLookupResultItem(BaseModel):
    platform: str
    username: str
    creator: Optional[CreatorResponse] = None
    error: Optional[str] = None


class BulkLookupResponse(BaseModel):
    results: list[BulkLookupResultItem]


# ─── Post ─────────────────────────────────────────

PLATFORM_INFO = {
    "instagram": {
        "id": "9bb8913b-ddd9-430b-a66a-d74d846e6c66",
        "name": "Instagram",
        "logo_url": "https://cdn.insightiq.ai/platforms_logo/logos/logo_instagram.png",
    },
    "tiktok": {
        "id": "de55aeec-0dc8-4119-bf90-16b3d1f0c987",
        "name": "TikTok",
        "logo_url": "https://cdn.insightiq.ai/platforms_logo/logos/logo_tiktok.png",
    },
    "youtube": {
        "id": "14d9ddf5-51c6-415e-bde6-f8ed36ad7054",
        "name": "YouTube",
        "logo_url": "https://cdn.insightiq.ai/platforms_logo/logos/logo_youtube.png",
    },
}


class WorkPlatform(BaseModel):
    id: str
    name: str
    logo_url: str


class PostEngagement(BaseModel):
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    view_count: Optional[int] = None
    save_count: Optional[int] = None
    engagement_rate: Optional[float] = None


class MediaItem(BaseModel):
    type: str
    url: str = ""
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None


class PostProfile(BaseModel):
    platform_username: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    is_verified: Optional[bool] = None


class PostResponse(BaseModel):
    id: str
    work_platform: WorkPlatform
    platform_content_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    format: str  # IMAGE, VIDEO, REEL, CAROUSEL, STORY
    type: str  # FEED, STORY, REEL
    url: Optional[str] = None
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    media_urls: list[MediaItem] = []
    published_at: Optional[datetime] = None
    engagement: PostEngagement
    hashtags: list[str] = []
    mentions: list[str] = []
    profile: Optional[PostProfile] = None
    collected_at: Optional[datetime] = None
    metrics_updated_at: Optional[datetime] = None

    # Internal fields
    creator_id: str

    model_config = {"from_attributes": True}


class PostListResponse(BaseModel):
    data: list[PostResponse]
    pagination: Pagination


class PostSearchParams(BaseModel):
    q: Optional[str] = None
    hashtag: Optional[str] = None
    platform: Optional[str] = None
    min_likes: Optional[int] = None
    min_views: Optional[int] = None
    type: Optional[str] = None
    published_after: Optional[str] = None
    published_before: Optional[str] = None
    sort: str = "-published_at"
    cursor: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)


# ─── Tracking ─────────────────────────────────────

class TrackCreatorRequest(BaseModel):
    platform: str = Field(..., pattern="^(instagram|tiktok|youtube)$")
    username: str = Field(..., min_length=1)
    frequency: str = Field(default="standard", pattern="^(realtime|frequent|standard)$")


class TrackingResponse(BaseModel):
    id: str
    creator_id: str
    platform: str
    frequency: str
    status: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TrackingListResponse(BaseModel):
    data: list[TrackingResponse]
    pagination: Pagination


# ─── Webhooks ─────────────────────────────────────

class WebhookCreateRequest(BaseModel):
    url: str = Field(..., pattern=r"^https://")
    events: list[str] = Field(..., min_length=1)
    filters: Optional[dict[str, Any]] = None
    secret: str = Field(..., min_length=16)


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    filters: Optional[dict[str, Any]] = None
    is_active: bool = True
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ─── Metrics History ──────────────────────────────

class MetricsDataPoint(BaseModel):
    timestamp: datetime
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    share_count: Optional[int] = None
    view_count: Optional[int] = None
    save_count: Optional[int] = None


class MetricsHistoryResponse(BaseModel):
    entity_id: str
    data: list[MetricsDataPoint]
