#!/usr/bin/env python3
"""
Quick test script to verify scraper works.
Run after: pip install -e .
"""
import asyncio
import sys

sys.path.insert(0, ".")


async def test_mgeko():
    """Test mgeko.cc scraper (no Cloudflare)."""
    from manga_scraper.scrapers.mgeko import MgekoScraper

    scraper = MgekoScraper()

    print("Testing mgeko.cc scraper...")
    print("-" * 50)

    # Test series scraping
    test_url = "https://www.mgeko.cc/manga/ovcharka/"
    print(f"Scraping series: {test_url}")

    try:
        series_data = await scraper.scrape_series(test_url)
        print(f"✓ Title: {series_data['title']}")
        print(f"✓ Status: {series_data['status']}")
        print(f"✓ Chapters found: {len(series_data['chapters'])}")

        if series_data["chapters"]:
            # Test chapter scraping
            first_chapter = series_data["chapters"][0]
            print(f"\nScraping chapter: {first_chapter['source_url']}")

            images = await scraper.scrape_chapter(first_chapter["source_url"])
            print(f"✓ Images found: {len(images)}")

            if images:
                print(f"  First image: {images[0]['source_url'][:80]}...")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await scraper.close()


async def test_asura():
    """Test asuracomic.net scraper (Cloudflare protected)."""
    from manga_scraper.scrapers.asura import AsuraScraper

    scraper = AsuraScraper()

    print("\n" + "=" * 50)
    print("Testing asuracomic.net scraper (Cloudflare)...")
    print("-" * 50)

    test_url = "https://asuracomic.net/series/solo-leveling-7a80569d"

    print(f"Scraping series: {test_url}")
    print("(This will launch a browser to bypass Cloudflare)")

    try:
        series_data = await scraper.scrape_series(test_url)
        print(f"✓ Title: {series_data['title']}")
        print(f"✓ Status: {series_data['status']}")
        print(f"✓ Chapters found: {len(series_data['chapters'])}")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await scraper.close()


async def main():
    print("=" * 50)
    print("Manga Scraper Test Suite")
    print("=" * 50)

    # Test non-CF site first
    await test_mgeko()

    # Optionally test CF-protected site
    response = input("\nTest Cloudflare-protected site? (y/n): ")
    if response.lower() == "y":
        await test_asura()

    print("\n" + "=" * 50)
    print("Tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
