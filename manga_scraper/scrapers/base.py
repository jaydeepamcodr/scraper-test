import asyncio
import random
import re
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from manga_scraper.config import settings
from manga_scraper.core.logging import get_logger
from manga_scraper.core.redis import get_redis
from manga_scraper.scrapers.browser_pool import BrowserPool

logger = get_logger("scraper")


class BaseScraper(ABC):
    """Base class for all site scrapers."""

    # Override in subclass
    SITE_NAME: str = "unknown"
    BASE_URL: str = ""
    REQUIRES_BROWSER: bool = False

    def __init__(self, requires_browser: bool | None = None):
        self.requires_browser = (
            requires_browser if requires_browser is not None else self.REQUIRES_BROWSER
        )
        self.redis = get_redis()
        self._http_client: httpx.AsyncClient | None = None
        self._browser_pool: BrowserPool | None = None

    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=self._get_headers(),
            )
        return self._http_client

    async def close(self) -> None:
        """Clean up resources."""
        if self._http_client:
            await self._http_client.aclose()
        if self._browser_pool:
            await self._browser_pool.close()

    def _get_headers(self) -> dict[str, str]:
        """Get request headers."""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

    async def _rate_limit(self) -> None:
        """Apply rate limiting."""
        domain = urlparse(self.BASE_URL).netloc
        limit = settings.get_rate_limit(domain)
        key = f"rate:{domain}"

        while not await self.redis.check_rate_limit(key, limit, window=60):
            logger.debug("rate_limited", domain=domain)
            await asyncio.sleep(1)

        # Random delay for human-like behavior
        delay = random.uniform(
            settings.scraper_request_delay_min,
            settings.scraper_request_delay_max,
        )
        await asyncio.sleep(delay)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _fetch_http(self, url: str) -> str:
        """Fetch page content via HTTP."""
        await self._rate_limit()

        client = await self.get_http_client()
        response = await client.get(url)

        # Check for Cloudflare challenge
        if self._is_cloudflare_challenge(response):
            logger.warning("cloudflare_detected", url=url)
            raise CloudflareBlockedError(f"Cloudflare challenge detected: {url}")

        response.raise_for_status()
        return response.text

    async def _fetch_browser(self, url: str, wait_selector: str | None = None) -> str:
        """Fetch page content via browser (for CF-protected sites)."""
        await self._rate_limit()

        if self._browser_pool is None:
            self._browser_pool = BrowserPool()

        return await self._browser_pool.fetch_page(url, wait_selector=wait_selector)

    async def fetch_page(
        self,
        url: str,
        force_browser: bool = False,
        wait_selector: str | None = None,
    ) -> str:
        """
        Fetch page content, using appropriate method.
        Tries HTTP first for speed, falls back to browser if blocked.
        """
        if force_browser or self.requires_browser:
            return await self._fetch_browser(url, wait_selector)

        try:
            return await self._fetch_http(url)
        except (CloudflareBlockedError, httpx.HTTPStatusError) as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code not in (403, 503):
                raise

            logger.info("falling_back_to_browser", url=url, reason=str(e))
            return await self._fetch_browser(url, wait_selector)

    def _is_cloudflare_challenge(self, response: httpx.Response) -> bool:
        """Detect Cloudflare challenge page."""
        if response.status_code in (403, 503):
            text = response.text.lower()
            indicators = [
                "just a moment",
                "checking your browser",
                "cf-browser-verification",
                "challenge-platform",
                "cloudflare",
                "_cf_chl",
            ]
            return any(ind in text for ind in indicators)
        return False

    def parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML content."""
        return BeautifulSoup(html, "lxml")

    def absolute_url(self, url: str, base: str | None = None) -> str:
        """Convert relative URL to absolute."""
        base = base or self.BASE_URL
        return urljoin(base, url)

    def extract_number(self, text: str) -> float | None:
        """Extract chapter/volume number from text."""
        if not text:
            return None
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        return float(match.group(1)) if match else None

    def slugify(self, text: str) -> str:
        """Convert text to URL-safe slug."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[-\s]+", "-", text)
        return text[:200]

    @abstractmethod
    async def scrape_series(self, url: str) -> dict[str, Any]:
        """
        Scrape series metadata and chapter list.
        
        Returns:
            {
                "source_site": str,
                "source_id": str,
                "source_url": str,
                "slug": str,
                "title": str,
                "title_alt": list[str] | None,
                "description": str | None,
                "cover_url": str | None,
                "status": str,
                "genres": list[str] | None,
                "authors": list[str] | None,
                "artists": list[str] | None,
                "chapters": list[{
                    "chapter_number": float,
                    "source_url": str,
                    "title": str | None,
                    "release_date": datetime | None,
                }]
            }
        """
        pass

    @abstractmethod
    async def scrape_chapter(
        self,
        url: str,
        force_browser: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Scrape chapter images.
        
        Returns:
            [
                {
                    "page_number": int,
                    "source_url": str,
                }
            ]
        """
        pass


class CloudflareBlockedError(Exception):
    """Raised when Cloudflare blocks the request."""

    pass
