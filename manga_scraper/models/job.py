import enum
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from manga_scraper.models.base import Base


class JobType(str, enum.Enum):
    SCRAPE_SERIES = "scrape_series"
    SCRAPE_CHAPTER = "scrape_chapter"
    DOWNLOAD_IMAGES = "download_images"
    CHECK_UPDATES = "check_updates"
    FULL_SYNC = "full_sync"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_type", "job_type"),
        Index("ix_jobs_celery_id", "celery_task_id"),
        Index("ix_jobs_series_id", "series_id"),
    )

    # Job identification
    celery_task_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    job_type: Mapped[JobType] = mapped_column(Enum(JobType), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus),
        default=JobStatus.PENDING,
        nullable=False,
    )

    # Related entities
    series_id: Mapped[int | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"),
    )
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"),
    )

    # Job input/output
    input_data: Mapped[dict | None] = mapped_column(JSONB)
    result_data: Mapped[dict | None] = mapped_column(JSONB)

    # Progress tracking
    progress: Mapped[int] = mapped_column(default=0)
    total_items: Mapped[int] = mapped_column(default=0)
    processed_items: Mapped[int] = mapped_column(default=0)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()

    # Error handling
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_traceback: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, type={self.job_type}, status={self.status})>"

    @property
    def is_finished(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
