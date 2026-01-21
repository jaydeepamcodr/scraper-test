import asyncio
import traceback
from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import select, and_

from manga_scraper.core.database import get_sync_db
from manga_scraper.core.logging import get_logger
from manga_scraper.models import Job, JobStatus, JobType, Series, Chapter
from manga_scraper.scrapers import get_scraper_for_url
from manga_scraper.storage import ImageStorage

logger = get_logger("tasks")


def run_async(coro):
    """Run async function in sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def scrape_series(self, series_url: str, job_id: int | None = None):
    """
    Scrape series metadata and chapter list.
    Uses HTTP scraper first, falls back to browser if needed.
    """
    db = get_sync_db()
    job = None

    try:
        # Update job status
        if job_id:
            job = db.get(Job, job_id)
            if job:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc)
                job.celery_task_id = self.request.id
                db.commit()

        logger.info("scraping_series", url=series_url, job_id=job_id)

        # Get appropriate scraper
        scraper = get_scraper_for_url(series_url)
        if not scraper:
            raise ValueError(f"No scraper available for URL: {series_url}")

        # Run scraper
        series_data = run_async(scraper.scrape_series(series_url))

        # Save to database
        series = db.execute(
            select(Series).where(
                and_(
                    Series.source_site == series_data["source_site"],
                    Series.source_id == series_data["source_id"],
                )
            )
        ).scalar_one_or_none()

        if series is None:
            series = Series(**{k: v for k, v in series_data.items() if k != "chapters"})
            db.add(series)
            db.flush()
        else:
            for key, value in series_data.items():
                if key != "chapters" and value is not None:
                    setattr(series, key, value)

        # Save chapters
        chapters_added = 0
        for ch_data in series_data.get("chapters", []):
            existing = db.execute(
                select(Chapter).where(
                    and_(
                        Chapter.series_id == series.id,
                        Chapter.chapter_number == ch_data["chapter_number"],
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                chapter = Chapter(series_id=series.id, **ch_data)
                db.add(chapter)
                chapters_added += 1

        series.last_checked_at = datetime.now(timezone.utc)
        series.total_chapters = len(series_data.get("chapters", []))
        if series_data.get("chapters"):
            series.latest_chapter = max(c["chapter_number"] for c in series_data["chapters"])

        db.commit()

        # Update job
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.result_data = {
                "series_id": series.id,
                "chapters_found": len(series_data.get("chapters", [])),
                "chapters_added": chapters_added,
            }
            db.commit()

        logger.info(
            "series_scraped",
            series_id=series.id,
            title=series.title,
            chapters=len(series_data.get("chapters", [])),
        )

        return {"series_id": series.id, "chapters_added": chapters_added}

    except Exception as exc:
        logger.error("scrape_series_failed", url=series_url, error=str(exc))

        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.error_traceback = traceback.format_exc()
            job.retry_count += 1
            db.commit()

        db.rollback()
        raise self.retry(exc=exc)

    finally:
        db.close()


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def scrape_chapter(self, chapter_id: int, job_id: int | None = None):
    """Scrape chapter images. Tries HTTP first, falls back to browser."""
    db = get_sync_db()
    job = None

    try:
        chapter = db.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError(f"Chapter {chapter_id} not found")

        if job_id:
            job = db.get(Job, job_id)
            if job:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now(timezone.utc)
                job.celery_task_id = self.request.id
                db.commit()

        logger.info("scraping_chapter", chapter_id=chapter_id, url=chapter.source_url)

        scraper = get_scraper_for_url(chapter.source_url)
        if not scraper:
            raise ValueError(f"No scraper for URL: {chapter.source_url}")

        # Scrape images
        images_data = run_async(scraper.scrape_chapter(chapter.source_url))

        # Save images and queue downloads
        from manga_scraper.models import ChapterImage

        for img_data in images_data:
            existing = db.execute(
                select(ChapterImage).where(
                    and_(
                        ChapterImage.chapter_id == chapter_id,
                        ChapterImage.page_number == img_data["page_number"],
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                image = ChapterImage(chapter_id=chapter_id, **img_data)
                db.add(image)

        chapter.is_scraped = True
        chapter.scraped_at = datetime.now(timezone.utc)
        chapter.total_images = len(images_data)
        db.commit()

        # Queue image downloads
        download_images.delay(chapter_id)

        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.result_data = {"images_found": len(images_data)}
            db.commit()

        logger.info("chapter_scraped", chapter_id=chapter_id, images=len(images_data))
        return {"chapter_id": chapter_id, "images": len(images_data)}

    except Exception as exc:
        logger.error("scrape_chapter_failed", chapter_id=chapter_id, error=str(exc))

        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.retry_count += 1
            db.commit()

        db.rollback()
        raise self.retry(exc=exc)

    finally:
        db.close()


@shared_task(bind=True, max_retries=2)
def scrape_chapter_browser(self, chapter_id: int, job_id: int | None = None):
    """
    Scrape chapter using browser (for Cloudflare protected sites).
    Runs on dedicated browser worker queue.
    """
    db = get_sync_db()

    try:
        chapter = db.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError(f"Chapter {chapter_id} not found")

        logger.info("scraping_chapter_browser", chapter_id=chapter_id)

        scraper = get_scraper_for_url(chapter.source_url)
        if not scraper:
            raise ValueError(f"No scraper for URL: {chapter.source_url}")

        # Force browser mode
        images_data = run_async(scraper.scrape_chapter(chapter.source_url, force_browser=True))

        from manga_scraper.models import ChapterImage

        for img_data in images_data:
            existing = db.execute(
                select(ChapterImage).where(
                    and_(
                        ChapterImage.chapter_id == chapter_id,
                        ChapterImage.page_number == img_data["page_number"],
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                image = ChapterImage(chapter_id=chapter_id, **img_data)
                db.add(image)

        chapter.is_scraped = True
        chapter.scraped_at = datetime.now(timezone.utc)
        chapter.total_images = len(images_data)
        db.commit()

        download_images.delay(chapter_id)

        return {"chapter_id": chapter_id, "images": len(images_data)}

    except Exception as exc:
        logger.error("scrape_chapter_browser_failed", chapter_id=chapter_id, error=str(exc))
        db.rollback()
        raise self.retry(exc=exc)

    finally:
        db.close()


@shared_task(bind=True, max_retries=3)
def download_images(self, chapter_id: int):
    """Download and store chapter images to S3/MinIO."""
    db = get_sync_db()

    try:
        chapter = db.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError(f"Chapter {chapter_id} not found")

        from manga_scraper.models import ChapterImage

        images = db.execute(
            select(ChapterImage)
            .where(
                and_(
                    ChapterImage.chapter_id == chapter_id,
                    ChapterImage.is_downloaded == False,
                )
            )
            .order_by(ChapterImage.page_number)
        ).scalars().all()

        if not images:
            logger.info("no_images_to_download", chapter_id=chapter_id)
            return {"downloaded": 0}

        logger.info("downloading_images", chapter_id=chapter_id, count=len(images))

        storage = ImageStorage()
        downloaded = 0

        for image in images:
            try:
                result = run_async(
                    storage.download_and_store(
                        source_url=image.source_url,
                        series_id=chapter.series_id,
                        chapter_id=chapter_id,
                        page_number=image.page_number,
                    )
                )

                image.storage_path = result["path"]
                image.storage_url = result["url"]
                image.file_size = result.get("size")
                image.content_type = result.get("content_type")
                image.is_downloaded = True
                downloaded += 1

            except Exception as e:
                logger.warning("image_download_failed", image_id=image.id, error=str(e))

        db.commit()
        logger.info("images_downloaded", chapter_id=chapter_id, downloaded=downloaded)

        return {"chapter_id": chapter_id, "downloaded": downloaded}

    except Exception as exc:
        logger.error("download_images_failed", chapter_id=chapter_id, error=str(exc))
        db.rollback()
        raise self.retry(exc=exc)

    finally:
        db.close()


@shared_task
def check_all_series_updates():
    """Periodic task to check all active series for new chapters."""
    db = get_sync_db()

    try:
        # Get active series that haven't been checked recently
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        series_list = db.execute(
            select(Series).where(
                and_(
                    Series.is_active == True,
                    (Series.last_checked_at == None) | (Series.last_checked_at < cutoff),
                )
            )
        ).scalars().all()

        logger.info("checking_series_updates", count=len(series_list))

        for series in series_list:
            # Create job and queue scrape
            job = Job(
                job_type=JobType.CHECK_UPDATES,
                series_id=series.id,
                input_data={"series_url": series.source_url},
            )
            db.add(job)
            db.commit()

            scrape_series.delay(series.source_url, job.id)

        return {"series_checked": len(series_list)}

    finally:
        db.close()


@shared_task
def cleanup_old_jobs():
    """Clean up completed jobs older than 7 days."""
    db = get_sync_db()

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        result = db.execute(
            select(Job).where(
                and_(
                    Job.status.in_([JobStatus.COMPLETED, JobStatus.FAILED]),
                    Job.completed_at < cutoff,
                )
            )
        )
        old_jobs = result.scalars().all()

        count = len(old_jobs)
        for job in old_jobs:
            db.delete(job)

        db.commit()
        logger.info("cleaned_old_jobs", count=count)

        return {"deleted": count}

    finally:
        db.close()
