from celery import Celery
from celery.schedules import crontab

from shared.config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "crawler_io",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "collection": {"exchange": "collection", "routing_key": "collection"},
        "collection_high": {"exchange": "collection_high", "routing_key": "collection_high"},
        "normalization": {"exchange": "normalization", "routing_key": "normalization"},
        "webhooks": {"exchange": "webhooks", "routing_key": "webhooks"},
    },
    task_routes={
        "services.scheduler.tasks.collect_creator": {"queue": "collection"},
        "services.scheduler.tasks.collect_posts": {"queue": "collection"},
        "services.scheduler.tasks.collect_creator_high_priority": {"queue": "collection_high"},
        "services.scheduler.tasks.normalize_and_store_creator": {"queue": "normalization"},
        "services.scheduler.tasks.normalize_and_store_posts": {"queue": "normalization"},
        "services.scheduler.tasks.dispatch_webhooks": {"queue": "webhooks"},
    },
    task_default_retry_delay=60,
    task_max_retries=3,
    beat_schedule={
        "refresh-tracked-creators": {
            "task": "services.scheduler.tasks.refresh_tracked_creators",
            "schedule": 60.0,  # Every 60 seconds
        },
        "cleanup-old-jobs": {
            "task": "services.scheduler.tasks.cleanup_old_jobs",
            "schedule": crontab(hour=3, minute=0),  # Daily at 3 AM
        },
    },
)

celery_app.autodiscover_tasks(["services.scheduler"])
