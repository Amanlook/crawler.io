import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from celery import shared_task
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.cache.redis import cache
from shared.config.settings import get_settings
from shared.db.database import async_session_factory
from shared.db.models import (
    CollectionJob,
    Creator,
    MetricsSnapshot,
    Post,
    TrackingSubscription,
    generate_id,
)
from services.collector.instagram.collector import InstagramCollector
from services.collector.tiktok.collector import TikTokCollector
from services.collector.youtube.collector import YouTubeCollector
from services.collector.base import RawCreatorData, RawPostData, CollectorError
from services.normalizer.registry import get_normalizer

logger = structlog.get_logger()
settings = get_settings()

COLLECTORS = {
    "instagram": InstagramCollector,
    "tiktok": TikTokCollector,
    "youtube": YouTubeCollector,
}


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def collect_creator(self, platform: str, username: str, job_id: Optional[str] = None):
    """Collect a creator's profile from a platform and store normalized data."""
    logger.info("task_collect_creator", platform=platform, username=username, job_id=job_id)

    async def _run():
        collector_cls = COLLECTORS.get(platform)
        if not collector_cls:
            raise ValueError(f"Unknown platform: {platform}")

        collector = collector_cls()
        try:
            # Update job status
            if job_id:
                await _update_job_status(job_id, "running")

            # Collect raw data
            raw_data = await collector.collect_creator(username)

            # Normalize
            normalizer = get_normalizer(platform)
            normalized = normalizer.normalize_creator(raw_data)

            # Store
            await _store_creator(normalized)

            # Update job status
            if job_id:
                await _update_job_status(job_id, "completed")

            # Cache invalidation
            await cache.delete(f"creator:{platform}:{username}")

            logger.info("creator_collected_successfully",
                        platform=platform, username=username)
            return {"status": "success", "platform": platform, "username": username}

        except CollectorError as e:
            logger.warning("creator_collection_failed",
                           platform=platform, username=username, error=str(e))
            if job_id:
                await _update_job_status(job_id, "failed", error=str(e))
            raise
        finally:
            await collector.close()

    try:
        return _run_async(_run())
    except CollectorError as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def collect_posts(self, platform: str, username: str, limit: int = 50, job_id: Optional[str] = None):
    """Collect a creator's posts from a platform and store normalized data."""
    logger.info("task_collect_posts", platform=platform, username=username, limit=limit)

    async def _run():
        collector_cls = COLLECTORS.get(platform)
        if not collector_cls:
            raise ValueError(f"Unknown platform: {platform}")

        collector = collector_cls()
        try:
            if job_id:
                await _update_job_status(job_id, "running")

            # Collect raw posts
            raw_posts = await collector.collect_posts(username, limit=limit)

            # Normalize and store
            normalizer = get_normalizer(platform)
            stored_count = 0
            for raw_post in raw_posts:
                try:
                    normalized = normalizer.normalize_post(raw_post)
                    await _store_post(normalized, platform)
                    stored_count += 1
                except Exception as e:
                    logger.warning("post_normalization_failed",
                                   post_id=raw_post.platform_post_id, error=str(e))

            if job_id:
                await _update_job_status(job_id, "completed")

            logger.info("posts_collected_successfully",
                        platform=platform, username=username, total=len(raw_posts), stored=stored_count)
            return {"status": "success", "stored": stored_count}

        except CollectorError as e:
            logger.warning("posts_collection_failed",
                           platform=platform, username=username, error=str(e))
            if job_id:
                await _update_job_status(job_id, "failed", error=str(e))
            raise
        finally:
            await collector.close()

    try:
        return _run_async(_run())
    except CollectorError as exc:
        raise self.retry(exc=exc)


@shared_task
def refresh_tracked_creators():
    """Periodic task: check which tracked creators need refreshing and queue jobs."""
    logger.info("refreshing_tracked_creators")

    async def _run():
        async with async_session_factory() as session:
            # Get active tracking subscriptions
            result = await session.execute(
                select(TrackingSubscription, Creator)
                .join(Creator, TrackingSubscription.creator_id == Creator.id)
                .where(TrackingSubscription.status == "active")
            )
            rows = result.all()

            now = datetime.now(timezone.utc)
            queued = 0

            for tracking, creator in rows:
                # Calculate refresh interval based on frequency
                interval_map = {
                    "realtime": timedelta(seconds=30),
                    "frequent": timedelta(minutes=5),
                    "standard": timedelta(hours=1),
                }
                interval = interval_map.get(tracking.frequency, timedelta(hours=1))

                # Check if we need to refresh
                if creator.last_updated_at and (now - creator.last_updated_at) < interval:
                    continue

                # Queue collection jobs
                collect_creator.delay(tracking.platform, creator.username)
                collect_posts.delay(tracking.platform, creator.username, limit=10)
                queued += 1

            logger.info("tracked_creators_refresh_queued", total=len(rows), queued=queued)

    _run_async(_run())


@shared_task
def cleanup_old_jobs():
    """Remove completed/failed jobs older than 7 days."""
    logger.info("cleaning_up_old_jobs")

    async def _run():
        async with async_session_factory() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            await session.execute(
                CollectionJob.__table__.delete().where(
                    CollectionJob.created_at < cutoff,
                    CollectionJob.status.in_(["completed", "failed"]),
                )
            )
            await session.commit()

    _run_async(_run())


# ─── Database Storage Helpers ───────────────────────────────────

async def _store_creator(normalized) -> str:
    """Upsert a normalized creator into the database."""
    async with async_session_factory() as session:
        # Check if creator exists
        result = await session.execute(
            select(Creator).where(
                Creator.platform == normalized.platform,
                Creator.platform_id == normalized.platform_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update
            existing.username = normalized.username
            existing.display_name = normalized.display_name
            existing.bio = normalized.bio
            existing.profile_image_url = normalized.profile_image_url
            existing.is_verified = normalized.is_verified
            existing.follower_count = normalized.follower_count
            existing.following_count = normalized.following_count
            existing.post_count = normalized.post_count
            existing.engagement_rate = normalized.engagement_rate
            existing.categories = normalized.categories
            existing.external_urls = normalized.external_urls
            existing.last_updated_at = datetime.now(timezone.utc)
            await session.commit()
            return existing.id
        else:
            # Insert
            creator = Creator(
                platform=normalized.platform,
                platform_id=normalized.platform_id,
                username=normalized.username,
                display_name=normalized.display_name,
                bio=normalized.bio,
                profile_image_url=normalized.profile_image_url,
                is_verified=normalized.is_verified,
                follower_count=normalized.follower_count,
                following_count=normalized.following_count,
                post_count=normalized.post_count,
                engagement_rate=normalized.engagement_rate,
                categories=normalized.categories,
                external_urls=normalized.external_urls,
            )
            session.add(creator)
            await session.commit()
            return creator.id


async def _store_post(normalized, platform: str) -> str:
    """Upsert a normalized post into the database."""
    async with async_session_factory() as session:
        # Find the creator
        creator_result = await session.execute(
            select(Creator).where(
                Creator.platform == platform,
                Creator.platform_id == normalized.creator_platform_id,
            )
        )
        creator = creator_result.scalar_one_or_none()
        if not creator:
            logger.warning("post_orphaned_no_creator",
                           platform=platform,
                           creator_platform_id=normalized.creator_platform_id)
            return ""

        # Check if post exists
        result = await session.execute(
            select(Post).where(
                Post.platform == platform,
                Post.platform_post_id == normalized.platform_post_id,
            )
        )
        existing = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing:
            # Update metrics
            existing.like_count = normalized.like_count
            existing.comment_count = normalized.comment_count
            existing.share_count = normalized.share_count
            existing.view_count = normalized.view_count
            existing.save_count = normalized.save_count
            existing.metrics_updated_at = now

            # Snapshot metrics
            snapshot = MetricsSnapshot(
                post_id=existing.id,
                captured_at=now,
                like_count=normalized.like_count,
                comment_count=normalized.comment_count,
                share_count=normalized.share_count,
                view_count=normalized.view_count,
                save_count=normalized.save_count,
            )
            session.add(snapshot)
            await session.commit()
            return existing.id
        else:
            # Insert new post
            post = Post(
                creator_id=creator.id,
                platform=platform,
                platform_post_id=normalized.platform_post_id,
                post_type=normalized.post_type,
                text_content=normalized.text_content,
                hashtags=normalized.hashtags,
                mentions=normalized.mentions,
                media=normalized.media,
                like_count=normalized.like_count,
                comment_count=normalized.comment_count,
                share_count=normalized.share_count,
                view_count=normalized.view_count,
                save_count=normalized.save_count,
                engagement_rate=normalized.engagement_rate,
                published_at=normalized.published_at,
            )
            session.add(post)
            await session.commit()

            # Initial metrics snapshot
            snapshot = MetricsSnapshot(
                post_id=post.id,
                captured_at=now,
                like_count=normalized.like_count,
                comment_count=normalized.comment_count,
                share_count=normalized.share_count,
                view_count=normalized.view_count,
                save_count=normalized.save_count,
            )
            session.add(snapshot)
            await session.commit()
            return post.id


async def _update_job_status(job_id: str, status: str, error: Optional[str] = None):
    """Update a collection job's status."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(CollectionJob).where(CollectionJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job:
            job.status = status
            if status == "running":
                job.started_at = datetime.now(timezone.utc)
            elif status in ("completed", "failed"):
                job.completed_at = datetime.now(timezone.utc)
            if error:
                job.last_error = error
                job.retry_count += 1
            await session.commit()
