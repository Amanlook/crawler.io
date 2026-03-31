"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Creators
    op.create_table(
        "creators",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("platform_id", sa.String(64), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256)),
        sa.Column("bio", sa.Text),
        sa.Column("profile_image_url", sa.Text),
        sa.Column("is_verified", sa.Boolean, default=False),
        sa.Column("follower_count", sa.BigInteger, default=0),
        sa.Column("following_count", sa.BigInteger, default=0),
        sa.Column("post_count", sa.BigInteger, default=0),
        sa.Column("engagement_rate", sa.Numeric(7, 4)),
        sa.Column("categories", postgresql.ARRAY(sa.String)),
        sa.Column("external_urls", postgresql.JSONB),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("uix_creators_platform_id", "creators", ["platform", "platform_id"], unique=True)
    op.create_index("idx_creators_platform_username", "creators", ["platform", "username"])
    op.create_index("idx_creators_followers", "creators", ["follower_count"])

    # Posts
    op.create_table(
        "posts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("creator_id", sa.String(32), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("platform_post_id", sa.String(128), nullable=False),
        sa.Column("post_type", sa.String(20), nullable=False),
        sa.Column("text_content", sa.Text),
        sa.Column("hashtags", postgresql.ARRAY(sa.String)),
        sa.Column("mentions", postgresql.ARRAY(sa.String)),
        sa.Column("media", postgresql.JSONB),
        sa.Column("like_count", sa.BigInteger, default=0),
        sa.Column("comment_count", sa.BigInteger, default=0),
        sa.Column("share_count", sa.BigInteger, default=0),
        sa.Column("view_count", sa.BigInteger, default=0),
        sa.Column("save_count", sa.BigInteger, default=0),
        sa.Column("engagement_rate", sa.Numeric(7, 4)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("metrics_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("uix_posts_platform_id", "posts", ["platform", "platform_post_id"], unique=True)
    op.create_index("idx_posts_creator", "posts", ["creator_id"])
    op.create_index("idx_posts_published", "posts", ["published_at"])
    op.create_index("idx_posts_hashtags", "posts", ["hashtags"], postgresql_using="gin")

    # Metrics Snapshots
    op.create_table(
        "metrics_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.String(32), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("like_count", sa.BigInteger),
        sa.Column("comment_count", sa.BigInteger),
        sa.Column("share_count", sa.BigInteger),
        sa.Column("view_count", sa.BigInteger),
        sa.Column("save_count", sa.BigInteger),
    )
    op.create_index("idx_metrics_post_time", "metrics_snapshots", ["post_id", "captured_at"])

    # Collection Jobs
    op.create_table(
        "collection_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("job_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("priority", sa.Integer, default=5),
        sa.Column("retry_count", sa.Integer, default=0),
        sa.Column("last_error", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_jobs_status_priority", "collection_jobs", ["status", "priority"])

    # API Keys
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("tier", sa.String(20), default="free"),
        sa.Column("owner_email", sa.String(256), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("rate_limit_per_minute", sa.Integer, default=10),
        sa.Column("daily_limit", sa.Integer, default=100),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )

    # Webhooks
    op.create_table(
        "webhooks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("api_key_id", sa.String(32), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("events", postgresql.ARRAY(sa.String), nullable=False),
        sa.Column("filters", postgresql.JSONB),
        sa.Column("secret", sa.String(256), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Tracking Subscriptions
    op.create_table(
        "tracking_subscriptions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("api_key_id", sa.String(32), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("creator_id", sa.String(32), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("frequency", sa.String(20), default="standard"),
        sa.Column("status", sa.String(20), default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_tracking_apikey", "tracking_subscriptions", ["api_key_id"])
    op.create_index("idx_tracking_creator", "tracking_subscriptions", ["creator_id"])


def downgrade() -> None:
    op.drop_table("tracking_subscriptions")
    op.drop_table("webhooks")
    op.drop_table("api_keys")
    op.drop_table("collection_jobs")
    op.drop_table("metrics_snapshots")
    op.drop_table("posts")
    op.drop_table("creators")
