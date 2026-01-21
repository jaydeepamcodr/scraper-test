from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manga_scraper.core.database import get_db
from manga_scraper.models import Job, JobStatus, JobType, Series, SeriesStatus
from manga_scraper.scrapers import get_scraper_for_url, get_supported_domains
from manga_scraper.workers.tasks import scrape_series

router = APIRouter()


# Pydantic schemas
class SeriesCreate(BaseModel):
    url: HttpUrl


class SeriesResponse(BaseModel):
    id: int
    slug: str
    title: str
    title_alt: list[str] | None
    description: str | None
    cover_url: str | None
    cover_path: str | None
    source_site: str
    source_url: str
    status: SeriesStatus
    genres: list[str] | None
    authors: list[str] | None
    artists: list[str] | None
    total_chapters: int
    latest_chapter: float | None
    is_active: bool
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SeriesListResponse(BaseModel):
    items: list[SeriesResponse]
    total: int
    page: int
    per_page: int
    pages: int


class ScrapeJobResponse(BaseModel):
    job_id: int
    message: str


# Routes
@router.get("/supported-sites")
async def get_supported_sites():
    """Get list of supported scraping sites."""
    return {"sites": get_supported_domains()}


@router.post("/", response_model=ScrapeJobResponse)
async def add_series(
    data: SeriesCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Add a new series by URL. Creates a background job to scrape it.
    """
    url = str(data.url)

    # Validate URL is supported
    scraper = get_scraper_for_url(url)
    if not scraper:
        raise HTTPException(
            status_code=400,
            detail=f"URL not supported. Supported sites: {get_supported_domains()}",
        )

    # Check if already exists
    existing = await db.execute(
        select(Series).where(Series.source_url == url)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Series already exists",
        )

    # Create job
    job = Job(
        job_type=JobType.SCRAPE_SERIES,
        input_data={"url": url},
    )
    db.add(job)
    await db.flush()

    # Queue scrape task
    scrape_series.delay(url, job.id)

    return ScrapeJobResponse(
        job_id=job.id,
        message="Series scrape job queued",
    )


@router.get("/", response_model=SeriesListResponse)
async def list_series(
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    status: SeriesStatus | None = None,
    source_site: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all series with pagination and filters."""
    query = select(Series)

    # Apply filters
    if status:
        query = query.where(Series.status == status)
    if source_site:
        query = query.where(Series.source_site == source_site)
    if search:
        query = query.where(Series.title.ilike(f"%{search}%"))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Paginate
    query = query.order_by(Series.updated_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    items = result.scalars().all()

    return SeriesListResponse(
        items=[SeriesResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/{series_id}", response_model=SeriesResponse)
async def get_series(
    series_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get series by ID."""
    series = await db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    return SeriesResponse.model_validate(series)


@router.delete("/{series_id}")
async def delete_series(
    series_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a series and all its chapters."""
    series = await db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    await db.delete(series)
    return {"message": "Series deleted"}


@router.post("/{series_id}/refresh", response_model=ScrapeJobResponse)
async def refresh_series(
    series_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Refresh series metadata and check for new chapters."""
    series = await db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    job = Job(
        job_type=JobType.CHECK_UPDATES,
        series_id=series_id,
        input_data={"url": series.source_url},
    )
    db.add(job)
    await db.flush()

    scrape_series.delay(series.source_url, job.id)

    return ScrapeJobResponse(
        job_id=job.id,
        message="Refresh job queued",
    )


@router.patch("/{series_id}/toggle-active")
async def toggle_series_active(
    series_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Toggle series active status for auto-updates."""
    series = await db.get(Series, series_id)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")

    series.is_active = not series.is_active

    return {
        "id": series_id,
        "is_active": series.is_active,
    }
