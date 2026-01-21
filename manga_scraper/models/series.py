import enum
from datetime import datetime

from sqlalchemy import Enum, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship


from manga_scraper.models.base import Base


class SeriesStatus(str, enum.Enum):
    ONGOING = "ongoing"
    COMPLETED = "completed"
    HIATUS = "hiatus"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class Series(Base):
    __tablename__ = "series"
    __table_args__ = (
        UniqueConstraint("source_site", "source_id", name="uq_series_source"),
        Index("ix_series_slug", "slug"),
        Index("ix_series_status", "status"),
        Index("ix_series_source_site", "source_site"),
    )

    # Identifiers
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    source_site: Mapped[str] = mapped_column(String(100), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)

    # Metadata
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    title_alt: Mapped[list[str] | None] = mapped_column(ARRAY(String(500)))
    description: Mapped[str | None] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(String(1024))
    cover_path: Mapped[str | None] = mapped_column(String(500))

    # Classification
    status: Mapped[SeriesStatus] = mapped_column(
        Enum(SeriesStatus),
        default=SeriesStatus.UNKNOWN,
        nullable=False,
    )
    genres: Mapped[list[str] | None] = mapped_column(ARRAY(String(100)))
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(String(200)))
    artists: Mapped[list[str] | None] = mapped_column(ARRAY(String(200)))

    # Stats
    total_chapters: Mapped[int] = mapped_column(default=0)
    latest_chapter: Mapped[float | None] = mapped_column()
    rating: Mapped[float | None] = mapped_column()

    # Tracking
    is_active: Mapped[bool] = mapped_column(default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column()
    last_chapter_at: Mapped[datetime | None] = mapped_column()

    # Extra data
    extra_data: Mapped[dict | None] = mapped_column(JSONB)

    # Relationships
    chapters: Mapped[list["Chapter"]] = relationship(
        "Chapter",
        back_populates="series",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Series(id={self.id}, title='{self.title}', source='{self.source_site}')>"


from manga_scraper.models.chapter import Chapter
