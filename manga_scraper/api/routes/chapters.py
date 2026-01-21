from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from manga_scraper.core.database import get_db
from manga_scraper.models import Chapter, ChapterImage, Job, JobType, Series
from manga_scraper.workers.tasks import scrape_chapter, download_images

router = APIRouter()


# Schemas
class ChapterResponse(BaseModel):
    id: int
    series_id: int
    chapter_number: float
    title: str | None
    source_url: str
    is_scraped: bool
    scraped_at: datetime | None
    total_images: int
    release_date: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class ChapterDetailResponse(ChapterResponse):
    images: list["ImageResponse"]


class ImageResponse(BaseModel):
    id: int
    page_number: int
    source_url: str
    storage_url: str | None
    is_downloaded: bool

    class Config:
        from_attributes = True


class ChapterListResponse(BaseModel):
    items: list[ChapterResponse]
    total: int
    page: int
    per_page: int


class ScrapeJobResponse(BaseModel):
    job_id: int
    message: str


# Routes
@router.get("/series/{series_id}", response_model=ChapterListResponse)
async def list_chapters(
    series_id: int,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 50,
    scraped_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List chapters for a series."""
    # Verify series exists
    series = await db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    query = select(Chapter).where(Chapter.series_id == series_id)

    if scraped_only:
        query = query.where(Chapter.is_scraped == True)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Paginate
    query = query.order_by(Chapter.chapter_number.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    items = result.scalars().all()

    return ChapterListResponse(
        items=[ChapterResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{chapter_id}", response_model=ChapterDetailResponse)
async def get_chapter(
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get chapter details with images."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    # Get images
    result = await db.execute(
        select(ChapterImage)
        .where(ChapterImage.chapter_id == chapter_id)
        .order_by(ChapterImage.page_number)
    )
    images = result.scalars().all()

    return ChapterDetailResponse(
        **ChapterResponse.model_validate(chapter).model_dump(),
        images=[ImageResponse.model_validate(i) for i in images],
    )


@router.post("/{chapter_id}/scrape", response_model=ScrapeJobResponse)
async def scrape_chapter_images(
    chapter_id: int,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Scrape chapter images."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    if chapter.is_scraped and not force:
        raise HTTPException(
            status_code=409,
            detail="Chapter already scraped. Use force=true to re-scrape.",
        )

    job = Job(
        job_type=JobType.SCRAPE_CHAPTER,
        chapter_id=chapter_id,
        series_id=chapter.series_id,
        input_data={"chapter_url": chapter.source_url},
    )
    db.add(job)
    await db.flush()

    scrape_chapter.delay(chapter_id, job.id)

    return ScrapeJobResponse(
        job_id=job.id,
        message="Chapter scrape job queued",
    )


@router.post("/series/{series_id}/scrape-all", response_model=ScrapeJobResponse)
async def scrape_all_chapters(
    series_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Queue scraping for all unscraped chapters in a series."""
    series = await db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    # Get unscraped chapters
    result = await db.execute(
        select(Chapter).where(
            and_(
                Chapter.series_id == series_id,
                Chapter.is_scraped == False,
            )
        )
    )
    chapters = result.scalars().all()

    if not chapters:
        raise HTTPException(
            status_code=409,
            detail="All chapters already scraped",
        )

    # Create jobs for each chapter
    job_count = 0
    for chapter in chapters:
        job = Job(
            job_type=JobType.SCRAPE_CHAPTER,
            chapter_id=chapter.id,
            series_id=series_id,
        )
        db.add(job)
        await db.flush()

        scrape_chapter.delay(chapter.id, job.id)
        job_count += 1

    return ScrapeJobResponse(
        job_id=0,  # Multiple jobs
        message=f"Queued {job_count} chapter scrape jobs",
    )


@router.post("/{chapter_id}/download", response_model=ScrapeJobResponse)
async def download_chapter_images(
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Download chapter images to storage."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    if not chapter.is_scraped:
        raise HTTPException(
            status_code=409,
            detail="Chapter not scraped yet. Scrape first.",
        )

    job = Job(
        job_type=JobType.DOWNLOAD_IMAGES,
        chapter_id=chapter_id,
        series_id=chapter.series_id,
    )
    db.add(job)
    await db.flush()

    download_images.delay(chapter_id)

    return ScrapeJobResponse(
        job_id=job.id,
        message="Image download job queued",
    )


@router.delete("/{chapter_id}")
async def delete_chapter(
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a chapter and its images."""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    # Delete images from storage
    from manga_scraper.storage import ImageStorage
    storage = ImageStorage()
    await storage.delete_chapter_images(chapter.series_id, chapter_id)

    await db.delete(chapter)

    return {"message": "Chapter deleted"}
