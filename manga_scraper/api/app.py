from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from manga_scraper.config import settings
from manga_scraper.core.database import init_db
from manga_scraper.core.logging import setup_logging
from manga_scraper.core.redis import get_redis
from manga_scraper.storage import ImageStorage


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    setup_logging()
    await init_db()
    
    # Ensure S3 bucket exists
    storage = ImageStorage()
    await storage.ensure_bucket_exists()
    
    yield
    
    # Shutdown
    redis = get_redis()
    await redis.close()


def create_app() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="Manga Scraper API",
        description="Production-ready manga scraping service with Cloudflare bypass",
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    from manga_scraper.api.routes import health, series, chapters, jobs

    app.include_router(health.router, tags=["Health"])
    app.include_router(series.router, prefix="/api/v1/series", tags=["Series"])
    app.include_router(chapters.router, prefix="/api/v1/chapters", tags=["Chapters"])
    app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])

    return app


app = create_app()
