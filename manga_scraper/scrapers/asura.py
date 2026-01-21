import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from manga_scraper.scrapers.base import BaseScraper


class AsuraScraper(BaseScraper):
    """
    Scraper for asuracomic.net - Cloudflare protected.
    Uses browser pool for all requests.
    """

    SITE_NAME = "asura"
    BASE_URL = "https://asuracomic.net"
    REQUIRES_BROWSER = True

    async def scrape_series(self, url: str) -> dict[str, Any]:
        """Scrape series metadata and chapter list."""
        # Wait for series content to load
        html = await self.fetch_page(
            url,
            wait_selector="img[alt*='poster'], .grid img",
        )
        soup = self.parse_html(html)

        # Extract source ID from URL
        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/")
        # URL format: /series/slug-id
        source_id = path_parts[-1] if path_parts else ""

        # Title - usually in h1 or span with specific class
        title_elem = soup.select_one(
            "h1, span.text-xl.font-bold, h3.text-xl"
        )
        title = title_elem.get_text(strip=True) if title_elem else "Unknown"

        # Clean up title (remove "- Asura Scans" suffix etc)
        title = re.sub(r"\s*[-–]\s*Asura\s*Scans?\s*$", "", title, flags=re.I)

        # Description
        desc_elem = soup.select_one(
            "span.font-medium.text-sm, .prose p, [class*='description']"
        )
        description = desc_elem.get_text(strip=True) if desc_elem else None

        # Cover image
        cover_url = None
        cover_selectors = [
            "img[alt*='poster']",
            "img[alt*='cover']",
            ".grid img[src*='storage']",
            "img[src*='covers']",
        ]
        for selector in cover_selectors:
            cover_elem = soup.select_one(selector)
            if cover_elem:
                cover_url = cover_elem.get("src")
                if cover_url:
                    cover_url = self.absolute_url(cover_url)
                    break

        # Status
        status = "unknown"
        status_elem = soup.find(string=re.compile(r"Status", re.I))
        if status_elem:
            parent = status_elem.find_parent()
            if parent:
                status_text = parent.get_text(strip=True).lower()
                if "ongoing" in status_text:
                    status = "ongoing"
                elif "completed" in status_text or "complete" in status_text:
                    status = "completed"
                elif "hiatus" in status_text:
                    status = "hiatus"
                elif "dropped" in status_text:
                    status = "cancelled"

        # Genres - look for buttons/badges
        genres = []
        genre_elems = soup.select(
            "button[class*='genre'], a[href*='genre'], span[class*='badge']"
        )
        for elem in genre_elems:
            genre = elem.get_text(strip=True)
            if genre and len(genre) < 50:  # Filter out non-genre text
                genres.append(genre)

        # Authors/Artists
        authors = []
        author_elem = soup.find(string=re.compile(r"Author", re.I))
        if author_elem:
            parent = author_elem.find_parent()
            if parent:
                # Look for the value in next sibling or child
                for sibling in parent.find_next_siblings():
                    text = sibling.get_text(strip=True)
                    if text and text != "Author":
                        authors.append(text)
                        break

        artists = []
        artist_elem = soup.find(string=re.compile(r"Artist", re.I))
        if artist_elem:
            parent = artist_elem.find_parent()
            if parent:
                for sibling in parent.find_next_siblings():
                    text = sibling.get_text(strip=True)
                    if text and text != "Artist":
                        artists.append(text)
                        break

        # Chapters - Asura uses dynamic chapter list
        chapters = []
        chapter_elems = soup.select(
            "a[href*='/chapter-'], div[class*='chapter'] a, h3 a[href*='chapter']"
        )

        for elem in chapter_elems:
            ch_url = elem.get("href")
            if not ch_url:
                continue

            ch_url = self.absolute_url(ch_url)
            ch_text = elem.get_text(strip=True)

            # Extract chapter number
            ch_num = None
            # Try URL first
            match = re.search(r"chapter[/-](\d+(?:\.\d+)?)", ch_url, re.I)
            if match:
                ch_num = float(match.group(1))
            else:
                # Try text
                ch_num = self.extract_number(ch_text)

            if ch_num is None:
                continue

            # Skip duplicates
            if any(c["chapter_number"] == ch_num for c in chapters):
                continue

            chapters.append({
                "chapter_number": ch_num,
                "source_url": ch_url,
                "title": None,
                "release_date": None,
            })

        # Sort chapters
        chapters.sort(key=lambda x: x["chapter_number"])

        return {
            "source_site": self.SITE_NAME,
            "source_id": source_id,
            "source_url": url,
            "slug": self.slugify(title),
            "title": title,
            "title_alt": None,
            "description": description,
            "cover_url": cover_url,
            "status": status,
            "genres": genres or None,
            "authors": authors or None,
            "artists": artists or None,
            "chapters": chapters,
        }

    async def scrape_chapter(
        self,
        url: str,
        force_browser: bool = False,
    ) -> list[dict[str, Any]]:
        """Scrape chapter images."""
        # Always use browser for Asura
        html = await self.fetch_page(
            url,
            force_browser=True,
            wait_selector="img[alt*='chapter'], img[src*='storage/media']",
        )
        soup = self.parse_html(html)

        images = []

        # Asura typically uses img tags with storage URLs
        img_selectors = [
            "img[src*='storage/media']",
            "img[alt*='chapter']",
            ".w-full img[src*='asura']",
            "img.max-w-full",
        ]

        img_elems = []
        for selector in img_selectors:
            img_elems = soup.select(selector)
            if img_elems:
                break

        # Filter and deduplicate
        seen_urls = set()
        for img in img_elems:
            img_url = img.get("src")

            if not img_url:
                continue

            # Skip non-chapter images
            if any(skip in img_url.lower() for skip in [
                "logo", "icon", "avatar", "banner", "ads", "placeholder"
            ]):
                continue

            img_url = self.absolute_url(img_url.strip())

            # Skip duplicates
            if img_url in seen_urls:
                continue
            seen_urls.add(img_url)

            images.append({
                "page_number": len(images) + 1,
                "source_url": img_url,
            })

        return images
