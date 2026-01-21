import json
from datetime import timedelta
from typing import Any

import redis.asyncio as aioredis
from redis import Redis

from manga_scraper.config import settings


class RedisClient:
    """Redis client wrapper with common operations."""

    def __init__(self, url: str | None = None):
        self.url = url or settings.redis_url
        self._async_client: aioredis.Redis | None = None
        self._sync_client: Redis | None = None

    async def get_async_client(self) -> aioredis.Redis:
        if self._async_client is None:
            self._async_client = await aioredis.from_url(
                self.url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._async_client

    def get_sync_client(self) -> Redis:
        if self._sync_client is None:
            self._sync_client = Redis.from_url(
                self.url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._sync_client

    async def close(self) -> None:
        if self._async_client:
            await self._async_client.close()
        if self._sync_client:
            self._sync_client.close()

    # Rate limiting
    async def check_rate_limit(self, key: str, limit: int, window: int = 60) -> bool:
        """Check if rate limit is exceeded. Returns True if allowed."""
        client = await self.get_async_client()
        current = await client.get(key)

        if current is None:
            await client.setex(key, window, 1)
            return True

        if int(current) >= limit:
            return False

        await client.incr(key)
        return True

    async def get_rate_limit_remaining(self, key: str, limit: int) -> int:
        """Get remaining requests in rate limit window."""
        client = await self.get_async_client()
        current = await client.get(key)
        if current is None:
            return limit
        return max(0, limit - int(current))

    # Cookie/Session storage
    async def store_cookies(self, domain: str, cookies: list[dict]) -> None:
        """Store browser cookies for domain."""
        client = await self.get_async_client()
        key = f"cookies:{domain}"
        await client.setex(key, timedelta(hours=2), json.dumps(cookies))

    async def get_cookies(self, domain: str) -> list[dict] | None:
        """Get stored cookies for domain."""
        client = await self.get_async_client()
        key = f"cookies:{domain}"
        data = await client.get(key)
        if data:
            return json.loads(data)
        return None

    # URL deduplication
    async def is_url_scraped(self, url: str) -> bool:
        """Check if URL has been scraped recently."""
        client = await self.get_async_client()
        return await client.sismember("scraped_urls", url)

    async def mark_url_scraped(self, url: str, ttl: int = 86400) -> None:
        """Mark URL as scraped."""
        client = await self.get_async_client()
        await client.sadd("scraped_urls", url)
        await client.expire("scraped_urls", ttl)

    # Generic cache operations
    async def get_cached(self, key: str) -> Any | None:
        """Get cached value."""
        client = await self.get_async_client()
        data = await client.get(f"cache:{key}")
        if data:
            return json.loads(data)
        return None

    async def set_cached(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set cached value."""
        client = await self.get_async_client()
        await client.setex(f"cache:{key}", ttl, json.dumps(value))

    # Lock for distributed operations
    async def acquire_lock(self, name: str, timeout: int = 30) -> bool:
        """Acquire distributed lock."""
        client = await self.get_async_client()
        return await client.set(f"lock:{name}", "1", nx=True, ex=timeout)

    async def release_lock(self, name: str) -> None:
        """Release distributed lock."""
        client = await self.get_async_client()
        await client.delete(f"lock:{name}")


# Global instance
_redis_client: RedisClient | None = None


def get_redis() -> RedisClient:
    """Get global Redis client instance."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client
