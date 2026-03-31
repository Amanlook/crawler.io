import secrets
import string
from datetime import datetime, timezone

import nanoid
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.database import Base


def generate_id(prefix: str) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return f"{prefix}_{nanoid.generate(alphabet, 16)}"


class Creator(Base):
    __tablename__ = "creators"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: generate_id("cr"))
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    platform_id: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(256))
    bio: Mapped[str | None] = mapped_column(Text)
    profile_image_url: Mapped[str | None] = mapped_column(Text)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    follower_count: Mapped[int] = mapped_column(BigInteger, default=0)
    following_count: Mapped[int] = mapped_column(BigInteger, default=0)
    post_count: Mapped[int] = mapped_column(BigInteger, default=0)
    engagement_rate: Mapped[float | None] = mapped_column(Numeric(7, 4))
    categories: Mapped[list | None] = mapped_column(ARRAY(String), default=list)
    external_urls: Mapped[dict | None] = mapped_column(JSONB, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    posts: Mapped[list["Post"]] = relationship(back_populates="creator", lazy="selectin")

    __table_args__ = (
        Index("uix_creators_platform_id", "platform", "platform_id", unique=True),
        Index("idx_creators_platform_username", "platform", "username"),
        Index("idx_creators_followers", "follower_count"),
    )


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: generate_id("po"))
    creator_id: Mapped[str] = mapped_column(String(32), ForeignKey("creators.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    platform_post_id: Mapped[str] = mapped_column(String(128), nullable=False)
    post_type: Mapped[str] = mapped_column(String(20), nullable=False)  # image, video, reel, short, story, carousel, live
    text_content: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list | None] = mapped_column(ARRAY(String), default=list)
    mentions: Mapped[list | None] = mapped_column(ARRAY(String), default=list)
    media: Mapped[dict | None] = mapped_column(JSONB, default=list)
    like_count: Mapped[int] = mapped_column(BigInteger, default=0)
    comment_count: Mapped[int] = mapped_column(BigInteger, default=0)
    share_count: Mapped[int] = mapped_column(BigInteger, default=0)
    view_count: Mapped[int] = mapped_column(BigInteger, default=0)
    save_count: Mapped[int] = mapped_column(BigInteger, default=0)
    engagement_rate: Mapped[float | None] = mapped_column(Numeric(7, 4))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    metrics_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    creator: Mapped["Creator"] = relationship(back_populates="posts")

    __table_args__ = (
        Index("uix_posts_platform_id", "platform", "platform_post_id", unique=True),
        Index("idx_posts_creator", "creator_id"),
        Index("idx_posts_published", "published_at"),
        Index("idx_posts_hashtags", "hashtags", postgresql_using="gin"),
    )


class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[str] = mapped_column(String(32), ForeignKey("posts.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    comment_count: Mapped[int | None] = mapped_column(BigInteger)
    share_count: Mapped[int | None] = mapped_column(BigInteger)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    save_count: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        Index("idx_metrics_post_time", "post_id", "captured_at"),
    )


class CollectionJob(Base):
    __tablename__ = "collection_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: generate_id("job"))
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    job_type: Mapped[str] = mapped_column(String(20), nullable=False)  # profile, posts, metrics
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)  # creator username or hashtag
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, running, completed, failed
    priority: Mapped[int] = mapped_column(Integer, default=5)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_jobs_status_priority", "status", "priority"),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: generate_id("key"))
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)  # sk_live_xxxx for display
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), default="free")  # free, starter, pro, enterprise
    owner_email: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=10)
    daily_limit: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: generate_id("wh"))
    api_key_id: Mapped[str] = mapped_column(String(32), ForeignKey("api_keys.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list] = mapped_column(ARRAY(String), nullable=False)
    filters: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    secret: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TrackingSubscription(Base):
    __tablename__ = "tracking_subscriptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: generate_id("trk"))
    api_key_id: Mapped[str] = mapped_column(String(32), ForeignKey("api_keys.id"), nullable=False)
    creator_id: Mapped[str] = mapped_column(String(32), ForeignKey("creators.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), default="standard")  # realtime, frequent, standard
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, paused, cancelled
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_tracking_apikey", "api_key_id"),
        Index("idx_tracking_creator", "creator_id"),
    )
