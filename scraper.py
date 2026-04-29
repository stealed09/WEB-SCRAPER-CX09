"""Web scraping engine for the Telegram Scraper Bot."""

import asyncio
import re
import io
import zipfile
import time
from urllib.parse import urljoin, urlparse
from typing import Callable, Optional

import aiohttp
from bs4 import BeautifulSoup

from config import (
    MAX_PAGES, REQUEST_TIMEOUT, USER_AGENT,
    CONCURRENT_REQUESTS, MAX_FILE_SIZE
)
from utils import make_progress_bar, format_size


class ScrapedPage:
    """Represents a single scraped page."""

    def __init__(self, url: str, content: str, status_code: int,
                 content_type: str = ""):
        self.url = url
        self.content = content
        self.status_code = status_code
        self.content_type = content_type
        self.size = len(content.encode('utf-8', errors='replace'))

    def get_filename(self) -> str:
        """Generate a safe filename from the URL."""
        parsed = urlparse(self.url)
        path = parsed.path.strip("/")
        if not path:
            path = "index"
        # Clean the path
        safe = re.sub(r'[^\w\-./]', '_', path)
        safe = safe.replace("/", "_")
        if not safe.endswith(('.html', '.htm', '.txt')):
            safe += ".html"
        # Limit length
        if len(safe) > 100:
            safe = safe[:95] + ".html"
        return safe


class WebScraper:
    """Handles all web scraping operations."""

    def __init__(self):
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    async def scrape_single(self, url: str,
                            progress_callback: Optional[Callable] = None
                            ) -> tuple[Optional[ScrapedPage], str]:
        """
        Scrape a single page.
        Returns (ScrapedPage or None, error_message).
        """
        if progress_callback:
            await progress_callback("🔄 Connecting to server...")

        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            connector = aiohttp.TCPConnector(ssl=False)

            async with aiohttp.ClientSession(
                headers=self.headers,
                timeout=timeout,
                connector=connector
            ) as session:
                if progress_callback:
                    await progress_callback("📡 Fetching page content...")

                async with session.get(url, allow_redirects=True) as response:
                    status = response.status

                    if status == 403:
                        return None, "🚫 Access Forbidden (403) - Site blocked bot access."
                    elif status == 404:
                        return None, "❌ Page Not Found (404)."
                    elif status == 429:
                        return None, "⏳ Rate Limited (429) - Too many requests."
                    elif status >= 500:
                        return None, f"🔥 Server Error ({status})."
                    elif status != 200:
                        return None, f"⚠️ HTTP Error: {status}"

                    content_type = response.headers.get("Content-Type", "")
                    text = await response.text(errors='replace')

                    if progress_callback:
                        await progress_callback(
                            f"✅ Page fetched! Size: {format_size(len(text.encode()))}"
                        )

                    page = ScrapedPage(
                        url=str(response.url),
                        content=text,
                        status_code=status,
                        content_type=content_type
                    )
                    return page, ""

        except aiohttp.ClientConnectorError:
            return None, "🔌 Connection failed - Could not reach the server."
        except aiohttp.InvalidURL:
            return None, "❌ Invalid URL format."
        except asyncio.TimeoutError:
            return None, f"⏰ Request timed out after {REQUEST_TIMEOUT} seconds."
        except aiohttp.ClientError as e:
            return None, f"🌐 Network error: {str(e)[:200]}"
        except Exception as e:
            return None, f"❗ Unexpected error: {str(e)[:200]}"

    async def scrape_all_pages(self, base_url: str,
                               progress_callback: Optional[Callable] = None
                               ) -> tuple[list[ScrapedPage], str]:
        """
        Scrape all internal pages starting from base_url.
        Returns (list of ScrapedPage, error_message).
        """
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc

        visited = set()
        to_visit = [base_url]
        pages = []
        errors_count = 0
        start_time = time.time()

        if progress_callback:
            await progress_callback(
                f"🚀 Starting multi-page scrape\n"
                f"🌐 Domain: {base_domain}\n"
                f"📄 Max pages: {MAX_PAGES}\n\n"
                f"{make_progress_bar(0, 1)}"
            )

        semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        connector = aiohttp.TCPConnector(ssl=False, limit=CONCURRENT_REQUESTS)

        try:
            async with aiohttp.ClientSession(
                headers=self.headers,
                timeout=timeout,
                connector=connector
            ) as session:

                while to_visit and len(pages) < MAX_PAGES:
                    # Process in batches
                    batch = []
                    while to_visit and len(batch) < CONCURRENT_REQUESTS:
                        url = to_visit.pop(0)
                        normalized = self._normalize_url(url)
                        if normalized not in visited:
                            visited.add(normalized)
                            batch.append(url)

                    if not batch:
                        break

                    # Fetch batch concurrently
                    tasks = [
                        self._fetch_page(session, url, semaphore)
                        for url in batch
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for url, result in zip(batch, results):
                        if isinstance(result, Exception):
                            errors_count += 1
                            continue

                        if result is None:
                            errors_count += 1
                            continue

                        page_content, status, content_type, final_url = result

                        if status == 200 and page_content:
                            page = ScrapedPage(
                                url=final_url,
                                content=page_content,
                                status_code=status,
                                content_type=content_type
                            )
                            pages.append(page)

                            # Extract links if HTML
                            if "text/html" in content_type:
                                new_links = self._extract_links(
                                    page_content, final_url, base_domain
                                )
                                for link in new_links:
                                    norm = self._normalize_url(link)
                                    if (norm not in visited
                                            and len(to_visit) + len(pages) < MAX_PAGES):
                                        to_visit.append(link)

                    # Progress update
                    if progress_callback:
                        total_est = len(pages) + len(to_visit)
                        elapsed = time.time() - start_time
                        await progress_callback(
                            f"🔄 <b>Scraping in progress...</b>\n\n"
                            f"✅ Pages scraped: <b>{len(pages)}</b>\n"
                            f"📋 Queue remaining: <b>{len(to_visit)}</b>\n"
                            f"❌ Errors: <b>{errors_count}</b>\n"
                            f"⏱ Elapsed: <b>{elapsed:.1f}s</b>\n\n"
                            f"{make_progress_bar(len(pages), min(total_est, MAX_PAGES))}\n\n"
                            f"📄 Max limit: {MAX_PAGES} pages"
                        )

                    # Small delay to be polite
                    await asyncio.sleep(0.3)

        except Exception as e:
            if not pages:
                return [], f"❗ Scraping failed: {str(e)[:200]}"

        if not pages:
            return [], "❌ No pages could be scraped from this URL."

        elapsed = time.time() - start_time

        if progress_callback:
            await progress_callback(
                f"✅ <b>Scraping complete!</b>\n\n"
                f"📄 Total pages: <b>{len(pages)}</b>\n"
                f"❌ Errors: <b>{errors_count}</b>\n"
                f"⏱ Time: <b>{elapsed:.1f}s</b>\n"
                f"💾 Total size: <b>"
                f"{format_size(sum(p.size for p in pages))}</b>\n\n"
                f"{make_progress_bar(len(pages), len(pages))}\n\n"
                f"📦 Preparing files..."
            )

        return pages, ""

    async def _fetch_page(self, session: aiohttp.ClientSession,
                          url: str, semaphore: asyncio.Semaphore
                          ) -> Optional[tuple]:
        """Fetch a single page with semaphore control."""
        async with semaphore:
            try:
                async with session.get(url, allow_redirects=True) as response:
                    content_type = response.headers.get("Content-Type", "")

                    # Only process HTML content
                    if "text/html" not in content_type and "text/plain" not in content_type:
                        return None

                    text = await response.text(errors='replace')
                    return (text, response.status, content_type, str(response.url))

            except Exception:
                return None

    def _extract_links(self, html: str, page_url: str,
                       base_domain: str) -> list[str]:
        """Extract internal links from HTML content."""
        links = []
        try:
            soup = BeautifulSoup(html, 'html.parser')

            for tag in soup.find_all('a', href=True):
                href = tag['href'].strip()

                # Skip unwanted links
                if any(href.startswith(p) for p in
                       ['#', 'mailto:', 'tel:', 'javascript:', 'data:']):
                    continue

                # Resolve relative URLs
                full_url = urljoin(page_url, href)
                parsed = urlparse(full_url)

                # Only internal links
                if parsed.netloc != base_domain:
                    continue

                # Skip non-HTML resources
                path_lower = parsed.path.lower()
                skip_ext = (
                    '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico',
                    '.css', '.js', '.pdf', '.zip', '.rar', '.exe',
                    '.mp3', '.mp4', '.avi', '.mov', '.webp', '.woff',
                    '.woff2', '.ttf', '.eot', '.map'
                )
                if any(path_lower.endswith(ext) for ext in skip_ext):
                    continue

                # Clean URL (remove fragment)
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if parsed.query:
                    clean_url += f"?{parsed.query}"

                links.append(clean_url)

        except Exception:
            pass

        return links

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        return normalized.lower()


def create_single_file(pages: list[ScrapedPage], url: str) -> tuple[bytes, str]:
    """
    Create a single combined file from scraped pages.
    Returns (file_bytes, filename).
    """
    content_parts = []
    separator = "\n" + "=" * 80 + "\n"

    for i, page in enumerate(pages, 1):
        header = (
            f"{separator}"
            f"PAGE {i}/{len(pages)}\n"
            f"URL: {page.url}\n"
            f"STATUS: {page.status_code}\n"
            f"SIZE: {format_size(page.size)}\n"
            f"{separator}\n"
        )
        content_parts.append(header + page.content)

    full_content = "\n".join(content_parts)
    filename = _make_base_filename(url)

    if len(pages) == 1:
        filename += ".html"
    else:
        filename += f"_{len(pages)}_pages.html"

    return full_content.encode('utf-8', errors='replace'), filename


def create_zip_file(pages: list[ScrapedPage], url: str) -> tuple[bytes, str]:
    """
    Create a ZIP file containing all scraped pages.
    Returns (zip_bytes, filename).
    """
    buffer = io.BytesIO()
    used_names = set()

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add index/summary file
        summary_lines = [
            f"Web Scrape Summary",
            f"Base URL: {url}",
            f"Total Pages: {len(pages)}",
            f"Total Size: {format_size(sum(p.size for p in pages))}",
            f"",
            f"{'='*60}",
            f"",
            f"Pages:",
        ]
        for i, page in enumerate(pages, 1):
            summary_lines.append(
                f"  {i}. {page.url} ({format_size(page.size)})"
            )

        zf.writestr("_summary.txt", "\n".join(summary_lines))

        # Add each page
        for page in pages:
            name = page.get_filename()
            # Ensure unique filename
            original_name = name
            counter = 1
            while name in used_names:
                base, ext = (name.rsplit('.', 1) if '.' in name
                             else (name, 'html'))
                name = f"{original_name.rsplit('.', 1)[0]}_{counter}.{ext}"
                counter += 1

            used_names.add(name)
            zf.writestr(
                name,
                page.content.encode('utf-8', errors='replace')
            )

    zip_bytes = buffer.getvalue()
    filename = _make_base_filename(url) + f"_{len(pages)}_pages.zip"
    return zip_bytes, filename


def _make_base_filename(url: str) -> str:
    """Generate a base filename from URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace(".", "_").replace(":", "_")
    return f"scrape_{domain}"
