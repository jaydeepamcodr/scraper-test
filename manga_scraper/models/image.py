from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from manga_scraper.models.base import Base


class ChapterImage(Base):
    __tablename__ = "chapter_images"
    __table_args__ = (
        Index("ix_images_chapter_id", "chapter_id"),
        Index("ix_images_page_number", "page_number"),
    )

    # Foreign key
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Image data
    page_number: Mapped[int] = mapped_column(nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    
    # Storage
    storage_path: Mapped[str | None] = mapped_column(String(500))
    storage_url: Mapped[str | None] = mapped_column(String(1024))
    
    # Metadata
    width: Mapped[int | None] = mapped_column()
    height: Mapped[int | None] = mapped_column()
    file_size: Mapped[int | None] = mapped_column()
    content_type: Mapped[str | None] = mapped_column(String(50))

    # Status
    is_downloaded: Mapped[bool] = mapped_column(default=False)

    # Relationship
    chapter: Mapped["Chapter"] = relationship("Chapter", back_populates="images")

    def __repr__(self) -> str:
        return f"<ChapterImage(id={self.id}, chapter_id={self.chapter_id}, page={self.page_number})>"


from manga_scraper.models.chapter import Chapter
