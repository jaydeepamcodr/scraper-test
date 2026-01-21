from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from manga_scraper.core.database import get_db
from manga_scraper.core.redis import get_redis

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check."""
    return {"status": "healthy"}


@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """
    Readiness check - verifies all dependencies are available.
    """
    checks = {
        "database": False,
        "redis": False,
    }

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass

    # Check Redis
    try:
        redis = get_redis()
        client = await redis.get_async_client()
        await client.ping()
        checks["redis"] = True
    except Exception:
        pass

    all_healthy = all(checks.values())
    
    return {
        "status": "ready" if all_healthy else "not_ready",
        "checks": checks,
    }


@router.get("/health/live")
async def liveness_check():
    """Liveness check - app is running."""
    return {"status": "alive"}
