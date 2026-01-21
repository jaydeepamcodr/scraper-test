import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from manga_scraper.scrapers.base import BaseScraper


class MgekoScraper(BaseScraper):
    """Scraper for mgeko.cc - No Cloudflare protection."""

    SITE_NAME = "mgeko"
    BASE_URL = "https://www.mgeko.cc"
    REQUIRES_BROWSER = False  # Plain HTTP works

    async def scrape_series(self, url: str) -> dict[str, Any]:
        """Scrape series metadata and chapter list."""
        html = await self.fetch_page(url)
        soup = self.parse_html(html)

        # Extract source ID from URL
        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/")
        source_id = path_parts[-1] if path_parts else ""

        # Title
        title_elem = soup.select_one("h1.entry-title, .post-title h1, h1")
        title = title_elem.get_text(strip=True) if title_elem else "Unknown"

        # Alternative titles
        alt_title_elem = soup.select_one(".alternative-title, .other-name")
        title_alt = None
        if alt_title_elem:
            alt_text = alt_title_elem.get_text(strip=True)
            title_alt = [t.strip() for t in alt_text.split(",") if t.strip()]

        # Description
        desc_elem = soup.select_one(".summary__content, .description-summary, .manga-excerpt")
        description = desc_elem.get_text(strip=True) if desc_elem else None

        # Cover image
        cover_elem = soup.select_one(".summary_image img, .thumb img, .manga-poster img")
        cover_url = None
        if cover_elem:
            cover_url = cover_elem.get("data-src") or cover_elem.get("src")
            if cover_url:
                cover_url = self.absolute_url(cover_url)

        # Status
        status = "unknown"
        status_elem = soup.select_one(".post-status .summary-content, .status")
        if status_elem:
            status_text = status_elem.get_text(strip=True).lower()
            if "ongoing" in status_text:
                status = "ongoing"
            elif "completed" in status_text or "complete" in status_text:
                status = "completed"
            elif "hiatus" in status_text:
                status = "hiatus"

        # Genres
        genres = []
        genre_elems = soup.select(".genres-content a, .manga-genres a, .tags a")
        for elem in genre_elems:
            genre = elem.get_text(strip=True)
            if genre:
                genres.append(genre)

        # Authors/Artists
        authors = []
        artists = []
        author_elems = soup.select(".author-content a, .manga-authors a")
        for elem in author_elems:
            name = elem.get_text(strip=True)
            if name:
                authors.append(name)

        artist_elems = soup.select(".artist-content a, .manga-artists a")
        for elem in artist_elems:
            name = elem.get_text(strip=True)
            if name:
                artists.append(name)

        # Chapters
        chapters = []
        chapter_elems = soup.select(".wp-manga-chapter a, .chapter-list a, li.chapter a")

        for elem in chapter_elems:
            ch_url = elem.get("href")
            if not ch_url:
                continue

            ch_url = self.absolute_url(ch_url)
            ch_text = elem.get_text(strip=True)

            # Extract chapter number
            ch_num = self.extract_number(ch_text)
            if ch_num is None:
                # Try from URL
                match = re.search(r"chapter[/-](\d+(?:\.\d+)?)", ch_url, re.I)
                if match:
                    ch_num = float(match.group(1))
                else:
                    continue

            # Release date
            release_date = None
            date_elem = elem.find_next_sibling(class_="chapter-release-date")
            if date_elem:
                try:
                    date_text = date_elem.get_text(strip=True)
                    # Parse various date formats
                    for fmt in ["%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y"]:
                        try:
                            release_date = datetime.strptime(date_text, fmt)
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass

            chapters.append({
                "chapter_number": ch_num,
                "source_url": ch_url,
                "title": ch_text if ch_text != f"Chapter {ch_num}" else None,
                "release_date": release_date,
            })

        # Sort chapters by number
        chapters.sort(key=lambda x: x["chapter_number"])

        return {
            "source_site": self.SITE_NAME,
            "source_id": source_id,
            "source_url": url,
            "slug": self.slugify(title),
            "title": title,
            "title_alt": title_alt,
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
        html = await self.fetch_page(url, force_browser=force_browser)
        soup = self.parse_html(html)

        images = []

        # Try different selectors for images
        img_selectors = [
            ".reading-content img",
            ".chapter-content img",
            ".page-break img",
            "#manga-reading-nav-body img",
            ".wp-manga-chapter-img",
        ]

        img_elems = []
        for selector in img_selectors:
            img_elems = soup.select(selector)
            if img_elems:
                break

        for idx, img in enumerate(img_elems, 1):
            # Get image URL (check data-src first for lazy loading)
            img_url = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("src")
            )

            if not img_url:
                continue

            # Skip placeholder images
            if "placeholder" in img_url.lower() or "loading" in img_url.lower():
                continue

            img_url = self.absolute_url(img_url.strip())

            images.append({
                "page_number": idx,
                "source_url": img_url,
            })

        return images
