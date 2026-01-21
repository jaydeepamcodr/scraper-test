from urllib.parse import urlparse

from manga_scraper.scrapers.base import BaseScraper
from manga_scraper.scrapers.mgeko import MgekoScraper
from manga_scraper.scrapers.asura import AsuraScraper
from manga_scraper.scrapers.manhwatop import ManhwatopScraper

# Registry of scrapers by domain
SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    "mgeko.cc": MgekoScraper,
    "www.mgeko.cc": MgekoScraper,
    "asuracomic.net": AsuraScraper,
    "www.asuracomic.net": AsuraScraper,
    "asura.nacm.xyz": AsuraScraper,
    "manhwatop.com": ManhwatopScraper,
    "www.manhwatop.com": ManhwatopScraper,
}

# Domains that require browser (Cloudflare protected)
BROWSER_REQUIRED_DOMAINS = {
    "asuracomic.net",
    "www.asuracomic.net",
    "asura.nacm.xyz",
    "manhwatop.com",
    "www.manhwatop.com",
}


def get_scraper_for_url(url: str) -> BaseScraper | None:
    """Get appropriate scraper instance for URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    scraper_class = SCRAPER_REGISTRY.get(domain)
    if scraper_class:
        requires_browser = domain in BROWSER_REQUIRED_DOMAINS
        return scraper_class(requires_browser=requires_browser)

    return None


def get_supported_domains() -> list[str]:
    """Get list of supported domains."""
    return list(set(SCRAPER_REGISTRY.keys()))


__all__ = [
    "BaseScraper",
    "MgekoScraper",
    "AsuraScraper",
    "ManhwatopScraper",
    "get_scraper_for_url",
    "get_supported_domains",
    "SCRAPER_REGISTRY",
    "BROWSER_REQUIRED_DOMAINS",
]
