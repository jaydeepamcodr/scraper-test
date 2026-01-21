from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from manga_scraper.models.base import Base


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("series_id", "chapter_number", name="uq_chapter_series_number"),
        Index("ix_chapters_series_id", "series_id"),
        Index("ix_chapters_number", "chapter_number"),
        Index("ix_chapters_scraped", "is_scraped"),
    )

    # Foreign key
    series_id: Mapped[int] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Identifiers
    chapter_number: Mapped[float] = mapped_column(nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(255))

    # Metadata
    title: Mapped[str | None] = mapped_column(String(500))
    volume: Mapped[int | None] = mapped_column()
    release_date: Mapped[datetime | None] = mapped_column()

    # Scraping status
    is_scraped: Mapped[bool] = mapped_column(default=False)
    scraped_at: Mapped[datetime | None] = mapped_column()
    total_images: Mapped[int] = mapped_column(default=0)
    
    # Storage
    images_path: Mapped[str | None] = mapped_column(String(500))

    # Extra data
    extra_data: Mapped[dict | None] = mapped_column(JSONB)

    # Relationships
    series: Mapped["Series"] = relationship("Series", back_populates="chapters")
    images: Mapped[list["ChapterImage"]] = relationship(
        "ChapterImage",
        back_populates="chapter",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Chapter(id={self.id}, series_id={self.series_id}, number={self.chapter_number})>"


from manga_scraper.models.series import Series
from manga_scraper.models.image import ChapterImage
