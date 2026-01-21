import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from manga_scraper.config import settings
from manga_scraper.core.logging import get_logger
from manga_scraper.core.redis import get_redis

logger = get_logger("browser_pool")


@dataclass
class BrowserInstance:
    """Represents a browser instance in the pool."""

    browser: Any
    page: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_count: int = 0
    last_used: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_busy: bool = False

    @property
    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()


class BrowserPool:
    """
    Manages a pool of browser instances for Cloudflare bypass.
    Uses nodriver for undetected browser automation.
    """

    MAX_REQUESTS_PER_BROWSER = 50
    MAX_BROWSER_AGE_SECONDS = 1800  # 30 minutes
    CF_WAIT_TIMEOUT = 15000  # 15 seconds for CF challenge

    def __init__(self, pool_size: int | None = None):
        self.pool_size = pool_size or settings.scraper_concurrent_browsers
        self._instances: list[BrowserInstance] = []
        self._lock = asyncio.Lock()
        self._redis = get_redis()
        self._initialized = False

    async def _create_browser(self) -> BrowserInstance:
        """Create a new browser instance using nodriver."""
        try:
            import nodriver as nd

            browser = await nd.start(
                headless=True,
                browser_args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-setuid-sandbox",
                    "--disable-accelerated-2d-canvas",
                    "--disable-software-rasterizer",
                ],
            )

            page = await browser.get("about:blank")

            instance = BrowserInstance(browser=browser, page=page)
            logger.info("browser_created", pool_size=len(self._instances) + 1)

            return instance

        except Exception as e:
            logger.error("browser_create_failed", error=str(e))
            raise

    async def _destroy_browser(self, instance: BrowserInstance) -> None:
        """Destroy a browser instance."""
        try:
            if instance.browser:
                instance.browser.stop()
            logger.debug("browser_destroyed")
        except Exception as e:
            logger.warning("browser_destroy_error", error=str(e))

    async def _get_instance(self) -> BrowserInstance:
        """Get an available browser instance from the pool."""
        async with self._lock:
            # Find available instance
            for instance in self._instances:
                if not instance.is_busy:
                    # Check if instance needs replacement
                    if (
                        instance.request_count >= self.MAX_REQUESTS_PER_BROWSER
                        or instance.age_seconds >= self.MAX_BROWSER_AGE_SECONDS
                    ):
                        await self._destroy_browser(instance)
                        self._instances.remove(instance)
                        continue

                    instance.is_busy = True
                    return instance

            # Create new instance if pool not full
            if len(self._instances) < self.pool_size:
                instance = await self._create_browser()
                instance.is_busy = True
                self._instances.append(instance)
                return instance

            # Wait for available instance
            logger.debug("waiting_for_browser")
            await asyncio.sleep(0.5)

        # Retry recursively
        return await self._get_instance()

    async def _release_instance(self, instance: BrowserInstance) -> None:
        """Release browser instance back to pool."""
        instance.is_busy = False
        instance.request_count += 1
        instance.last_used = datetime.now(timezone.utc)

    @asynccontextmanager
    async def acquire(self):
        """Context manager to acquire a browser instance."""
        instance = await self._get_instance()
        try:
            yield instance
        finally:
            await self._release_instance(instance)

    async def fetch_page(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """
        Fetch page content using browser, handling Cloudflare.
        
        Args:
            url: URL to fetch
            wait_selector: CSS selector to wait for (indicates page loaded)
            timeout: Timeout in milliseconds
        """
        timeout = timeout or settings.scraper_browser_timeout

        async with self.acquire() as instance:
            page = instance.page

            try:
                logger.debug("browser_navigating", url=url)

                # Navigate to page
                await page.get(url)

                # Wait for Cloudflare challenge to resolve
                await self._wait_for_cloudflare(page, timeout)

                # Wait for specific content if selector provided
                if wait_selector:
                    try:
                        await page.select(wait_selector, timeout=timeout / 1000)
                    except Exception:
                        logger.warning("selector_not_found", selector=wait_selector)

                # Get page content
                content = await page.get_content()

                # Store cookies for future HTTP requests
                await self._store_cookies(url, page)

                logger.debug("browser_fetch_complete", url=url, content_length=len(content))
                return content

            except Exception as e:
                logger.error("browser_fetch_failed", url=url, error=str(e))
                raise

    async def _wait_for_cloudflare(self, page: Any, timeout: int) -> None:
        """Wait for Cloudflare challenge to complete."""
        import asyncio

        start_time = asyncio.get_event_loop().time()
        max_wait = timeout / 1000  # Convert to seconds

        while (asyncio.get_event_loop().time() - start_time) < max_wait:
            try:
                # Check page title
                title = await page.evaluate("document.title")

                if title and "just a moment" not in title.lower():
                    # Also check for challenge elements
                    has_challenge = await page.evaluate(
                        """
                        () => {
                            return document.querySelector('#challenge-running') !== null ||
                                   document.querySelector('.cf-browser-verification') !== null;
                        }
                        """
                    )

                    if not has_challenge:
                        logger.debug("cloudflare_resolved", title=title)
                        return

            except Exception:
                pass

            await asyncio.sleep(0.5)

        logger.warning("cloudflare_wait_timeout")

    async def _store_cookies(self, url: str, page: Any) -> None:
        """Store browser cookies in Redis for HTTP requests."""
        try:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc
            cookies = await page.evaluate(
                """
                () => {
                    return document.cookie.split(';').map(c => {
                        const [name, value] = c.trim().split('=');
                        return {name, value};
                    });
                }
                """
            )

            if cookies:
                await self._redis.store_cookies(domain, cookies)
                logger.debug("cookies_stored", domain=domain, count=len(cookies))

        except Exception as e:
            logger.warning("cookie_store_failed", error=str(e))

    async def close(self) -> None:
        """Close all browser instances."""
        async with self._lock:
            for instance in self._instances:
                await self._destroy_browser(instance)
            self._instances.clear()
            logger.info("browser_pool_closed")

    @property
    def active_count(self) -> int:
        """Number of active browser instances."""
        return len(self._instances)

    @property
    def busy_count(self) -> int:
        """Number of busy browser instances."""
        return sum(1 for i in self._instances if i.is_busy)
