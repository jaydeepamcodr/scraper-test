from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manga_scraper.core.database import get_db
from manga_scraper.models import Job, JobStatus, JobType
from manga_scraper.workers.celery_app import celery_app

router = APIRouter()


# Schemas
class JobResponse(BaseModel):
    id: int
    celery_task_id: str | None
    job_type: JobType
    status: JobStatus
    series_id: int | None
    chapter_id: int | None
    progress: int
    total_items: int
    processed_items: int
    error_message: str | None
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    per_page: int


class JobStatsResponse(BaseModel):
    pending: int
    running: int
    completed: int
    failed: int
    total: int


# Routes
@router.get("/", response_model=JobListResponse)
async def list_jobs(
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    status: JobStatus | None = None,
    job_type: JobType | None = None,
    series_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List jobs with filters."""
    query = select(Job)

    if status:
        query = query.where(Job.status == status)
    if job_type:
        query = query.where(Job.job_type == job_type)
    if series_id:
        query = query.where(Job.series_id == series_id)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Paginate
    query = query.order_by(Job.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    items = result.scalars().all()

    return JobListResponse(
        items=[JobResponse.model_validate(j) for j in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/stats", response_model=JobStatsResponse)
async def get_job_stats(db: AsyncSession = Depends(get_db)):
    """Get job statistics."""
    stats = {}

    for status in [JobStatus.PENDING, JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED]:
        count = await db.scalar(
            select(func.count()).where(Job.status == status)
        )
        stats[status.value] = count or 0

    total = sum(stats.values())

    return JobStatsResponse(
        pending=stats["pending"],
        running=stats["running"],
        completed=stats["completed"],
        failed=stats["failed"],
        total=total,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get job details."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse.model_validate(job)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending or running job."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.is_finished:
        raise HTTPException(
            status_code=409,
            detail=f"Job already finished with status: {job.status}",
        )

    # Revoke Celery task
    if job.celery_task_id:
        celery_app.control.revoke(job.celery_task_id, terminate=True)

    job.status = JobStatus.CANCELLED
    job.completed_at = datetime.utcnow()

    return {"message": "Job cancelled"}


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed job."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail="Only failed jobs can be retried",
        )

    # Reset job status
    job.status = JobStatus.PENDING
    job.error_message = None
    job.error_traceback = None
    job.started_at = None
    job.completed_at = None

    # Re-queue based on job type
    from manga_scraper.workers.tasks import scrape_series, scrape_chapter, download_images

    if job.job_type == JobType.SCRAPE_SERIES:
        url = job.input_data.get("url") if job.input_data else None
        if url:
            scrape_series.delay(url, job.id)

    elif job.job_type in (JobType.SCRAPE_CHAPTER, JobType.CHECK_UPDATES):
        if job.chapter_id:
            scrape_chapter.delay(job.chapter_id, job.id)

    elif job.job_type == JobType.DOWNLOAD_IMAGES:
        if job.chapter_id:
            download_images.delay(job.chapter_id)

    return {"message": "Job requeued"}


@router.delete("/{job_id}")
async def delete_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a job record."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == JobStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete running job. Cancel it first.",
        )

    await db.delete(job)
    return {"message": "Job deleted"}
