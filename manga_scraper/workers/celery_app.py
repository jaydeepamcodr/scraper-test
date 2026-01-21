from celery import Celery
from kombu import Exchange, Queue

from manga_scraper.config import settings

celery_app = Celery(
    "manga_scraper",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=600,  # 10 minutes hard limit
    task_soft_time_limit=540,  # 9 minutes soft limit
    
    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time for browser workers
    worker_concurrency=4,  # Configurable per worker type
    
    # Result backend
    result_expires=86400,  # 24 hours
    result_extended=True,
    
    # Task routing
    task_routes={
        "manga_scraper.workers.tasks.scrape_series": {"queue": "scraper"},
        "manga_scraper.workers.tasks.scrape_chapter": {"queue": "scraper"},
        "manga_scraper.workers.tasks.scrape_chapter_browser": {"queue": "browser"},
        "manga_scraper.workers.tasks.download_images": {"queue": "downloader"},
        "manga_scraper.workers.tasks.check_series_updates": {"queue": "scheduler"},
    },
    
    # Queues
    task_queues=(
        Queue("default", Exchange("default"), routing_key="default"),
        Queue("scraper", Exchange("scraper"), routing_key="scraper"),
        Queue("browser", Exchange("browser"), routing_key="browser"),
        Queue("downloader", Exchange("downloader"), routing_key="downloader"),
        Queue("scheduler", Exchange("scheduler"), routing_key="scheduler"),
    ),
    task_default_queue="default",
    
    # Beat scheduler for periodic tasks
    beat_schedule={
        "check-updates-hourly": {
            "task": "manga_scraper.workers.tasks.check_all_series_updates",
            "schedule": 3600.0,  # Every hour
        },
        "cleanup-old-jobs-daily": {
            "task": "manga_scraper.workers.tasks.cleanup_old_jobs",
            "schedule": 86400.0,  # Every 24 hours
        },
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["manga_scraper.workers"])
