import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from manga_scraper.scrapers.base import BaseScraper


class ManhwatopScraper(BaseScraper):
    """
    Scraper for manhwatop.com - Cloudflare protected.
    Uses browser pool for all requests.
    """

    SITE_NAME = "manhwatop"
    BASE_URL = "https://manhwatop.com"
    REQUIRES_BROWSER = True

    async def scrape_series(self, url: str) -> dict[str, Any]:
        """Scrape series metadata and chapter list."""
        html = await self.fetch_page(
            url,
            wait_selector=".post-title h1, .manga-title",
        )
        soup = self.parse_html(html)

        # Extract source ID from URL
        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/")
        source_id = path_parts[-1] if len(path_parts) > 1 else ""

        # Title
        title_elem = soup.select_one(
            ".post-title h1, .manga-title, h1.entry-title"
        )
        title = title_elem.get_text(strip=True) if title_elem else "Unknown"

        # Alternative titles
        title_alt = None
        alt_elem = soup.select_one(".alternative, .other-name, .alt-name")
        if alt_elem:
            alt_text = alt_elem.get_text(strip=True)
            if alt_text:
                title_alt = [t.strip() for t in re.split(r"[,;/]", alt_text) if t.strip()]

        # Description
        desc_elem = soup.select_one(
            ".description-summary .summary__content, .manga-excerpt, .summary p"
        )
        description = None
        if desc_elem:
            description = desc_elem.get_text(strip=True)
            # Clean up "Show more" type text
            description = re.sub(r"\s*(Show more|Show less|Read more).*$", "", description, flags=re.I)

        # Cover image
        cover_url = None
        cover_elem = soup.select_one(
            ".summary_image img, .manga-poster img, .thumb img"
        )
        if cover_elem:
            cover_url = (
                cover_elem.get("data-src")
                or cover_elem.get("data-lazy-src")
                or cover_elem.get("src")
            )
            if cover_url:
                cover_url = self.absolute_url(cover_url)

        # Status
        status = "unknown"
        status_elem = soup.select_one(
            ".post-status .summary-content, .manga-status"
        )
        if status_elem:
            status_text = status_elem.get_text(strip=True).lower()
            if "ongoing" in status_text:
                status = "ongoing"
            elif "completed" in status_text or "complete" in status_text:
                status = "completed"
            elif "hiatus" in status_text:
                status = "hiatus"
            elif "cancelled" in status_text or "dropped" in status_text:
                status = "cancelled"

        # Genres
        genres = []
        genre_elems = soup.select(".genres-content a, .manga-genres a, .wp-manga-genre a")
        for elem in genre_elems:
            genre = elem.get_text(strip=True)
            if genre:
                genres.append(genre)

        # Authors
        authors = []
        author_elems = soup.select(".author-content a, .manga-authors a")
        for elem in author_elems:
            name = elem.get_text(strip=True)
            if name and name.lower() != "updating":
                authors.append(name)

        # Artists
        artists = []
        artist_elems = soup.select(".artist-content a, .manga-artists a")
        for elem in artist_elems:
            name = elem.get_text(strip=True)
            if name and name.lower() != "updating":
                artists.append(name)

        # Chapters
        chapters = []
        chapter_elems = soup.select(
            ".wp-manga-chapter a, li.chapter a, .chapter-item a"
        )

        for elem in chapter_elems:
            ch_url = elem.get("href")
            if not ch_url:
                continue

            ch_url = self.absolute_url(ch_url)
            ch_text = elem.get_text(strip=True)

            # Extract chapter number
            ch_num = None
            match = re.search(r"chapter[/-](\d+(?:\.\d+)?)", ch_url, re.I)
            if match:
                ch_num = float(match.group(1))
            else:
                ch_num = self.extract_number(ch_text)

            if ch_num is None:
                continue

            # Skip duplicates
            if any(c["chapter_number"] == ch_num for c in chapters):
                continue

            # Try to get release date
            release_date = None
            date_elem = elem.find_parent("li")
            if date_elem:
                date_span = date_elem.select_one(".chapter-release-date, .release-date, time")
                if date_span:
                    date_text = date_span.get("datetime") or date_span.get_text(strip=True)
                    if date_text:
                        for fmt in ["%Y-%m-%d", "%B %d, %Y", "%d/%m/%Y"]:
                            try:
                                release_date = datetime.strptime(date_text[:10], fmt)
                                break
                            except ValueError:
                                continue

            chapters.append({
                "chapter_number": ch_num,
                "source_url": ch_url,
                "title": ch_text if "chapter" not in ch_text.lower() else None,
                "release_date": release_date,
            })

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
        # Always use browser for manhwatop
        html = await self.fetch_page(
            url,
            force_browser=True,
            wait_selector=".reading-content img, .chapter-content img",
        )
        soup = self.parse_html(html)

        images = []

        # Try multiple selectors
        img_selectors = [
            ".reading-content img",
            ".chapter-content img",
            ".page-break img",
            "#manga-reading img",
            ".wp-manga-chapter-img",
        ]

        img_elems = []
        for selector in img_selectors:
            img_elems = soup.select(selector)
            if img_elems:
                break

        seen_urls = set()
        for img in img_elems:
            img_url = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("src")
            )

            if not img_url:
                continue

            # Skip placeholders and non-content images
            if any(skip in img_url.lower() for skip in [
                "placeholder", "loading", "spinner", "logo", "icon", "avatar", "banner"
            ]):
                continue

            img_url = self.absolute_url(img_url.strip())

            if img_url in seen_urls:
                continue
            seen_urls.add(img_url)

            images.append({
                "page_number": len(images) + 1,
                "source_url": img_url,
            })

        return images
