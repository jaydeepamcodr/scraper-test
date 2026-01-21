import pytest
from manga_scraper.scrapers import get_scraper_for_url, get_supported_domains


def test_get_supported_domains():
    """Test that supported domains are returned."""
    domains = get_supported_domains()
    assert len(domains) > 0
    assert "mgeko.cc" in domains or "www.mgeko.cc" in domains


def test_get_scraper_for_url_mgeko():
    """Test scraper selection for mgeko."""
    scraper = get_scraper_for_url("https://www.mgeko.cc/manga/test/")
    assert scraper is not None
    assert scraper.SITE_NAME == "mgeko"
    assert scraper.requires_browser is False


def test_get_scraper_for_url_asura():
    """Test scraper selection for asura."""
    scraper = get_scraper_for_url("https://asuracomic.net/series/test")
    assert scraper is not None
    assert scraper.SITE_NAME == "asura"
    assert scraper.requires_browser is True


def test_get_scraper_for_unsupported_url():
    """Test that unsupported URLs return None."""
    scraper = get_scraper_for_url("https://example.com/manga/test/")
    assert scraper is None


def test_scraper_slugify():
    """Test slug generation."""
    from manga_scraper.scrapers.base import BaseScraper
    
    class TestScraper(BaseScraper):
        SITE_NAME = "test"
        BASE_URL = "https://test.com"
        
        async def scrape_series(self, url):
            pass
        
        async def scrape_chapter(self, url, force_browser=False):
            pass
    
    scraper = TestScraper()
    assert scraper.slugify("Hello World!") == "hello-world"
    assert scraper.slugify("Solo Leveling: Ragnarok") == "solo-leveling-ragnarok"


def test_scraper_extract_number():
    """Test chapter number extraction."""
    from manga_scraper.scrapers.base import BaseScraper
    
    class TestScraper(BaseScraper):
        SITE_NAME = "test"
        BASE_URL = "https://test.com"
        
        async def scrape_series(self, url):
            pass
        
        async def scrape_chapter(self, url, force_browser=False):
            pass
    
    scraper = TestScraper()
    assert scraper.extract_number("Chapter 123") == 123.0
    assert scraper.extract_number("Ch. 45.5") == 45.5
    assert scraper.extract_number("Episode 1") == 1.0
    assert scraper.extract_number("No number here") is None
