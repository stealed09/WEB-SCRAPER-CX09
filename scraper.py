"""
Advanced Web Scraping Engine with Anti-Block System.
Handles free hosting, SSL issues, redirects, bot detection.
Supports: HTML, Images, CSS, JS, Fonts, Videos, Audio.
"""

import asyncio
import re
import io
import os
import ssl
import zipfile
import time
import random
import hashlib
import logging
from urllib.parse import urljoin, urlparse, unquote
from typing import Callable, Optional
from dataclasses import dataclass, field

import aiohttp
from aiohttp import TCPConnector
from bs4 import BeautifulSoup
import certifi

from config import (
    MAX_PAGES, REQUEST_TIMEOUT, ASSET_TIMEOUT, CONNECT_TIMEOUT,
    USER_AGENTS, BROWSER_HEADERS, ASSET_HEADERS,
    CONCURRENT_REQUESTS, CONCURRENT_ASSET_DOWNLOADS,
    MAX_SINGLE_ASSET_SIZE, MAX_TOTAL_SIZE,
    MAX_ASSETS_PER_PAGE, MAX_TOTAL_ASSETS,
    MAX_RETRIES, RETRY_DELAY,
    IMAGE_EXTENSIONS, CSS_EXTENSIONS, JS_EXTENSIONS,
    FONT_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
    ALL_ASSET_EXTENSIONS,
    GOOGLE_CACHE_URL, WAYBACK_API
)
from utils import make_progress_bar, format_size

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════

@dataclass
class ScrapedAsset:
    url: str
    content: bytes
    content_type: str
    local_path: str
    size: int = 0
    asset_type: str = "other"

    def __post_init__(self):
        self.size = len(self.content)


@dataclass
class ScrapedPage:
    url: str
    original_html: str
    modified_html: str
    status_code: int
    content_type: str = ""
    size: int = 0
    local_path: str = ""
    fetch_method: str = "direct"

    def __post_init__(self):
        self.size = len(
            self.original_html.encode('utf-8', errors='replace')
        )


@dataclass
class ScrapeResult:
    pages: list = field(default_factory=list)
    assets: dict = field(default_factory=dict)
    total_pages: int = 0
    total_assets: int = 0
    total_size: int = 0
    errors: int = 0
    elapsed: float = 0.0
    fetch_method: str = "direct"
    warnings: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════
#  SSL + SESSION HELPERS
# ═══════════════════════════════════════════════════════

def create_ssl_context(verify: bool = True) -> ssl.SSLContext:
    if not verify:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    try:
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def get_random_ua() -> str:
    return random.choice(USER_AGENTS)


def build_headers(ua: str = None, referer: str = None,
                  extra: dict = None) -> dict:
    headers = dict(BROWSER_HEADERS)
    headers["User-Agent"] = ua or get_random_ua()
    if referer:
        headers["Referer"] = referer
        headers["Sec-Fetch-Site"] = "same-origin"
    if extra:
        headers.update(extra)
    return headers


# ═══════════════════════════════════════════════════════
#  ASSET EXTRACTOR
# ═══════════════════════════════════════════════════════

class AssetExtractor:
    """Extracts all asset URLs from HTML and CSS."""

    @staticmethod
    def extract_all(html: str, page_url: str) -> dict:
        assets = {
            "images": [], "css": [], "js": [],
            "fonts": [], "videos": [], "audios": [], "others": []
        }

        try:
            soup = BeautifulSoup(html, 'html.parser')
        except Exception:
            return assets

        parsed_page = urlparse(page_url)

        def make_full(href: str) -> Optional[str]:
            if not href:
                return None
            href = href.strip()
            if href.startswith('data:'):
                return None
            if href.startswith('//'):
                href = f"{parsed_page.scheme}:{href}"
            full = urljoin(page_url, href)
            if full.startswith(('http://', 'https://')):
                return full
            return None

        # ── Images ────────────────────────────────────
        for tag in soup.find_all(True):
            # src
            if tag.name in ('img', 'input') and tag.get('src'):
                u = make_full(tag['src'])
                if u:
                    assets["images"].append(u)

            # lazy load attributes
            for attr in ('data-src', 'data-lazy', 'data-original',
                         'data-lazy-src', 'data-bg', 'data-background',
                         'data-img'):
                if tag.get(attr):
                    u = make_full(tag[attr])
                    if u:
                        assets["images"].append(u)

            # srcset
            if tag.get('srcset'):
                for part in tag['srcset'].split(','):
                    part = part.strip()
                    if part:
                        u = make_full(part.split()[0])
                        if u:
                            assets["images"].append(u)

        # <picture><source>
        for tag in soup.find_all('source'):
            if tag.get('srcset'):
                for part in tag['srcset'].split(','):
                    part = part.strip()
                    if part:
                        u = make_full(part.split()[0])
                        if u:
                            assets["images"].append(u)
            if tag.get('src'):
                u = make_full(tag['src'])
                if u:
                    assets["images"].append(u)

        # Inline style background-image
        for tag in soup.find_all(style=True):
            for raw in re.findall(
                r'url\(["\']?([^"\')\s]+)["\']?\)',
                tag['style']
            ):
                u = make_full(raw)
                if u:
                    assets["images"].append(u)

        # <style> blocks
        for tag in soup.find_all('style'):
            if tag.string:
                for raw in re.findall(
                    r'url\(["\']?([^"\')\s]+)["\']?\)',
                    tag.string
                ):
                    u = make_full(raw)
                    if u:
                        assets["images"].append(u)

        # video poster
        for tag in soup.find_all('video', poster=True):
            u = make_full(tag['poster'])
            if u:
                assets["images"].append(u)

        # meta og:image / twitter:image
        for tag in soup.find_all('meta'):
            prop = (
                tag.get('property', '') or
                tag.get('name', '') or ''
            ).lower()
            content = tag.get('content', '')
            if content and any(x in prop for x in
                               ['og:image', 'twitter:image']):
                u = make_full(content)
                if u:
                    assets["images"].append(u)

        # JSON-LD image
        for tag in soup.find_all(
            'script', type='application/ld+json'
        ):
            if tag.string:
                for img in re.findall(
                    r'"image"\s*:\s*"(https?://[^"]+)"',
                    tag.string
                ):
                    assets["images"].append(img)

        # ── CSS ───────────────────────────────────────
        for tag in soup.find_all('link', href=True):
            rel = ' '.join(tag.get('rel', [])).lower()
            href = tag['href'].strip()
            full = make_full(href)
            if not full:
                continue

            if 'stylesheet' in rel:
                assets["css"].append(full)
            elif any(x in rel for x in
                     ['icon', 'shortcut', 'apple-touch']):
                assets["images"].append(full)
            elif 'preload' in rel:
                as_attr = tag.get('as', '').lower()
                if as_attr == 'font':
                    assets["fonts"].append(full)
                elif as_attr == 'image':
                    assets["images"].append(full)
                elif as_attr == 'script':
                    assets["js"].append(full)
                elif as_attr == 'style':
                    assets["css"].append(full)
                else:
                    ext = os.path.splitext(
                        urlparse(full).path
                    )[1].lower()
                    if ext in FONT_EXTENSIONS:
                        assets["fonts"].append(full)
                    elif ext in IMAGE_EXTENSIONS:
                        assets["images"].append(full)
            else:
                ext = os.path.splitext(
                    urlparse(full).path
                )[1].lower()
                if ext in FONT_EXTENSIONS:
                    assets["fonts"].append(full)

        # ── JavaScript ────────────────────────────────
        for tag in soup.find_all('script', src=True):
            u = make_full(tag['src'])
            if u:
                assets["js"].append(u)

        # ── Videos ───────────────────────────────────
        for tag in soup.find_all('video'):
            if tag.get('src'):
                u = make_full(tag['src'])
                if u:
                    assets["videos"].append(u)

        # ── Audio ─────────────────────────────────────
        for tag in soup.find_all('audio'):
            if tag.get('src'):
                u = make_full(tag['src'])
                if u:
                    assets["audios"].append(u)

        # <source> inside video/audio
        for tag in soup.find_all('source'):
            if not tag.get('src'):
                continue
            u = make_full(tag['src'])
            if not u:
                continue
            ext = os.path.splitext(urlparse(u).path)[1].lower()
            mime = tag.get('type', '').lower()
            if ext in VIDEO_EXTENSIONS or 'video' in mime:
                assets["videos"].append(u)
            elif ext in AUDIO_EXTENSIONS or 'audio' in mime:
                assets["audios"].append(u)

        # ── Embed / Object ────────────────────────────
        for tag in soup.find_all('embed', src=True):
            u = make_full(tag['src'])
            if u:
                assets["others"].append(u)
        for tag in soup.find_all('object', data=True):
            u = make_full(tag['data'])
            if u:
                assets["others"].append(u)

        # ── Manifest ──────────────────────────────────
        for tag in soup.find_all('link'):
            rel = ' '.join(tag.get('rel', [])).lower()
            if 'manifest' in rel and tag.get('href'):
                u = make_full(tag['href'])
                if u:
                    assets["others"].append(u)

        # Deduplicate
        for key in assets:
            seen = set()
            unique = []
            for u in assets[key]:
                if u and u not in seen:
                    seen.add(u)
                    unique.append(u)
            assets[key] = unique

        return assets

    @staticmethod
    def extract_css_assets(css_content: str,
                           css_url: str) -> list:
        """Extract asset URLs referenced inside CSS."""
        urls = []

        for pattern in [
            r'url\("([^"]+)"\)',
            r"url\('([^']+)'\)",
            r'url\(([^"\')\s]+)\)',
        ]:
            for match in re.finditer(pattern, css_content):
                raw = match.group(1).strip()
                if raw.startswith('data:'):
                    continue
                full = urljoin(css_url, raw)
                if full.startswith(('http://', 'https://')):
                    urls.append(full)

        for pattern in [
            r'@import\s+"([^"]+)"',
            r"@import\s+'([^']+)'",
            r'@import\s+url\(["\']?([^"\')\s]+)["\']?\)',
        ]:
            for match in re.finditer(pattern, css_content):
                raw = match.group(1).strip()
                full = urljoin(css_url, raw)
                if full.startswith(('http://', 'https://')):
                    urls.append(full)

        return list(set(urls))


# ═══════════════════════════════════════════════════════
#  PATH MANAGER
# ═══════════════════════════════════════════════════════

class PathManager:
    """Manages local file paths for ZIP structure."""

    TYPE_FOLDERS = {
        "image": "assets/images",
        "css":   "assets/css",
        "js":    "assets/js",
        "font":  "assets/fonts",
        "video": "assets/videos",
        "audio": "assets/audio",
        "other": "assets/other",
    }

    def __init__(self, base_domain: str):
        self.base_domain = base_domain
        self.url_to_path: dict = {}
        self.used_paths: set = set()

    def get_local_path(self, url: str,
                       asset_type: str = "other") -> str:
        if url in self.url_to_path:
            return self.url_to_path[url]

        parsed = urlparse(url)
        path = unquote(parsed.path).strip("/")
        filename = os.path.basename(path) or ""

        if not filename:
            ext = self._guess_ext(asset_type)
            filename = (
                hashlib.md5(url.encode()).hexdigest()[:12] + ext
            )

        filename = re.sub(r'[^\w\-.]', '_', filename)
        filename = filename.split('?')[0]

        if '.' not in filename:
            filename += self._guess_ext(asset_type)

        if len(filename) > 100:
            name, ext = os.path.splitext(filename)
            filename = name[:90] + ext

        folder = self.TYPE_FOLDERS.get(asset_type, "assets/other")
        local_path = f"{folder}/{filename}"

        if local_path in self.used_paths:
            name, ext = os.path.splitext(local_path)
            c = 1
            while f"{name}_{c}{ext}" in self.used_paths:
                c += 1
            local_path = f"{name}_{c}{ext}"

        self.used_paths.add(local_path)
        self.url_to_path[url] = local_path
        return local_path

    def get_page_path(self, url: str) -> str:
        if url in self.url_to_path:
            return self.url_to_path[url]

        parsed = urlparse(url)
        path = unquote(parsed.path).strip("/")

        if not path:
            safe = "index.html"
        else:
            safe = re.sub(r'[^\w\-./]', '_', path)
            safe = safe.replace("/", "_")
            if not safe.endswith(('.html', '.htm', '.php', '.asp')):
                safe += ".html"

        if len(safe) > 100:
            safe = safe[:95] + ".html"

        if safe in self.used_paths:
            name, ext = os.path.splitext(safe)
            c = 1
            while f"{name}_{c}{ext}" in self.used_paths:
                c += 1
            safe = f"{name}_{c}{ext}"

        self.used_paths.add(safe)
        self.url_to_path[url] = safe
        return safe

    @staticmethod
    def _guess_ext(asset_type: str) -> str:
        return {
            "image": ".png", "css": ".css", "js": ".js",
            "font": ".woff2", "video": ".mp4", "audio": ".mp3"
        }.get(asset_type, ".bin")

    @staticmethod
    def get_relative_path(from_file: str, to_file: str) -> str:
        from_dir = os.path.dirname(from_file)
        if not from_dir:
            return to_file
        from_parts = [p for p in from_dir.split("/") if p]
        to_parts = [p for p in to_file.split("/") if p]
        common = 0
        for a, b in zip(from_parts, to_parts):
            if a == b:
                common += 1
            else:
                break
        ups = len(from_parts) - common
        rel_parts = ['..'] * ups + to_parts[common:]
        result = '/'.join(rel_parts)
        return result if result else to_file


# ═══════════════════════════════════════════════════════
#  HTML REWRITER
# ═══════════════════════════════════════════════════════

class HTMLRewriter:
    """Rewrites HTML/CSS to use local asset paths."""

    @staticmethod
    def rewrite_html(html: str, page_url: str,
                     page_local_path: str,
                     pm: PathManager) -> str:
        try:
            soup = BeautifulSoup(html, 'html.parser')
        except Exception:
            return html

        def local_rel(orig: str) -> Optional[str]:
            full = urljoin(page_url, orig.strip())
            if full in pm.url_to_path:
                local = pm.url_to_path[full]
                return PathManager.get_relative_path(
                    page_local_path, local
                )
            return None

        # All tags with src / lazy attrs
        for tag in soup.find_all(True):
            for attr in ('src', 'data-src', 'data-lazy',
                         'data-original', 'data-lazy-src',
                         'data-img'):
                if tag.get(attr):
                    rel = local_rel(tag[attr])
                    if rel:
                        tag[attr] = rel

            if tag.get('srcset'):
                new_parts = []
                for part in tag['srcset'].split(','):
                    part = part.strip()
                    if not part:
                        continue
                    pieces = part.split()
                    rel = local_rel(pieces[0])
                    if rel:
                        pieces[0] = rel
                    new_parts.append(' '.join(pieces))
                tag['srcset'] = ', '.join(new_parts)

            if tag.get('poster'):
                rel = local_rel(tag['poster'])
                if rel:
                    tag['poster'] = rel

        # <link href>
        for tag in soup.find_all('link', href=True):
            rel = local_rel(tag['href'])
            if rel:
                tag['href'] = rel

        # <script src>
        for tag in soup.find_all('script', src=True):
            rel = local_rel(tag['src'])
            if rel:
                tag['src'] = rel

        # Inline styles
        for tag in soup.find_all(style=True):
            tag['style'] = HTMLRewriter._rewrite_css_str(
                tag['style'], page_url, page_local_path, pm
            )

        # <style> blocks
        for tag in soup.find_all('style'):
            if tag.string:
                tag.string = HTMLRewriter._rewrite_css_str(
                    tag.string, page_url, page_local_path, pm
                )

        return str(soup)

    @staticmethod
    def _rewrite_css_str(css: str, base_url: str,
                         local_path: str,
                         pm: PathManager) -> str:
        def replace(match):
            raw = match.group(1)
            if raw.startswith('data:'):
                return match.group(0)
            full = urljoin(base_url, raw.strip())
            if full in pm.url_to_path:
                local = pm.url_to_path[full]
                rel = PathManager.get_relative_path(local_path, local)
                return f'url("{rel}")'
            return match.group(0)

        return re.sub(
            r'url\(["\']?([^"\')\s]+)["\']?\)',
            replace, css
        )

    @staticmethod
    def rewrite_css(css_content: str, css_url: str,
                    css_local_path: str,
                    pm: PathManager) -> str:
        def replace(match):
            raw = match.group(1)
            if raw.startswith('data:'):
                return match.group(0)
            full = urljoin(css_url, raw.strip())
            if full in pm.url_to_path:
                local = pm.url_to_path[full]
                rel = PathManager.get_relative_path(
                    css_local_path, local
                )
                return f'url("{rel}")'
            return match.group(0)

        return re.sub(
            r'url\(["\']?([^"\')\s]+)["\']?\)',
            replace, css_content
        )


# ═══════════════════════════════════════════════════════
#  ADVANCED FETCHER - MULTIPLE STRATEGIES
# ═══════════════════════════════════════════════════════

class AdvancedFetcher:
    """
    Tries 7 strategies to fetch a URL:
    0. InfinityFree/epizy/wuaze __test cookie bypass (NEW)
    1. Direct with SSL verification
    2. Direct WITHOUT SSL (free hosts with bad certs)
    3. With cookies (cookie walls)
    4. Rotate all user agents
    5. Google Cache
    6. Wayback Machine
    """

    @staticmethod
    def _solve_infinityfree_token(html: str):
        """
        InfinityFree/epizy/wuaze challenge solver.
        Their JS challenge looks like:
            var cheungId = 3452878;
            var toChk = 1000003;
            document.cookie = "__test=" + (cheungId * toChk) + "; path=/";
            location.href = ".../?i=1";
        We extract the two variable values, multiply them, build the cookie.
        Also handles older addition-based and direct-value patterns.
        """
        import re as _re

        # ── Pattern 1 (MAIN): named vars then multiplication in cookie ──
        # var cheungId = NNN; var toChk = NNN;
        # document.cookie = "__test=" + (cheungId * toChk)
        vars_found = {}
        for vm in _re.finditer(r'var\s+(\w+)\s*=\s*(\d+)', html):
            vars_found[vm.group(1)] = int(vm.group(2))

        # Find the cookie line: "__test=" + (varA * varB) or (varA + varB)
        cm = _re.search(
            r'document\.cookie\s*=\s*"__test="\s*\+\s*\((\w+)\s*([*+])\s*(\w+)\)',
            html
        )
        if cm and vars_found:
            va, op, vb = cm.group(1), cm.group(2), cm.group(3)
            a = vars_found.get(va, 0)
            b = vars_found.get(vb, 0)
            if a and b:
                result = a * b if op == '*' else a + b
                return f"__test={result}"

        # ── Pattern 2: inline multiplication in cookie string ──
        m = _re.search(
            r'document\.cookie\s*=\s*"__test="\s*\+\s*\((\d+)\s*\*\s*(\d+)\)',
            html
        )
        if m:
            return f"__test={int(m.group(1)) * int(m.group(2))}"

        # ── Pattern 3: inline addition in cookie string ──
        m = _re.search(
            r'document\.cookie\s*=\s*"__test="\s*\+\s*\((\d+)\s*\+\s*(\d+)\)',
            html
        )
        if m:
            return f"__test={int(m.group(1)) + int(m.group(2))}"

        # ── Pattern 4: var s = N * N or N + N ──
        m = _re.search(r'var\s+s\s*=\s*(\d+)\s*([*+])\s*(\d+)', html)
        if m:
            a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
            result = a * b if op == '*' else a + b
            return f"__test={result}"

        # ── Pattern 5: __test=NNN directly in URL or meta ──
        m = _re.search(r'__test=(\d+)', html)
        if m:
            return f"__test={m.group(1)}"

        return None

    async def _fetch_infinityfree_bypass(self, url: str):
        """
        Full bypass for InfinityFree/epizy/wuaze.com anti-bot challenge.
        Steps:
          1. Hit the URL — get JS challenge page
          2. Solve the __test cookie math from JS
          3. Wait 2s (mimic real browser JS execution)
          4. Re-request with solved cookie + ?i=1 redirect target
          5. Retry up to 3 times
        """
        ssl_ctx = create_ssl_context(verify=False)
        connector = TCPConnector(ssl=ssl_ctx, limit=10, force_close=True)
        timeout = aiohttp.ClientTimeout(
            total=REQUEST_TIMEOUT + 30, connect=CONNECT_TIMEOUT
        )
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        headers = build_headers()
        headers.update({
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "no-cache",
        })

        try:
            async with aiohttp.ClientSession(
                connector=connector, timeout=timeout,
                headers=headers,
                cookie_jar=aiohttp.CookieJar(unsafe=True)
            ) as session:

                # ── Step 1: hit the URL, get challenge page ──
                async with session.get(
                    url, allow_redirects=True, max_redirects=10
                ) as resp:
                    first_html = await resp.text(errors='replace')
                    first_status = resp.status
                    first_url = str(resp.url)

                logger.info(
                    f"InfinityFree bypass step1: HTTP {first_status}, "
                    f"size={len(first_html)}, url={first_url}"
                )

                # If real content already returned (no challenge), done
                challenge_keywords = [
                    '__test', 'cheungid', 'tochk',
                    'checking your browser', 'security check',
                    'please wait', 'anti-bot'
                ]
                is_challenge = any(
                    kw in first_html.lower() for kw in challenge_keywords
                )
                if not is_challenge and first_status == 200 and len(first_html) > 1000:
                    return first_html, 200, "text/html", first_url

                # ── Step 2: solve the cookie math ──
                cookie_val = self._solve_infinityfree_token(first_html)
                if not cookie_val:
                    logger.warning(
                        f"InfinityFree bypass: could not solve token. "
                        f"Page snippet: {first_html[:500]}"
                    )
                    return None

                logger.info(f"InfinityFree bypass: solved cookie → {cookie_val}")

                # ── Step 3: wait 2s like a real browser would ──
                await asyncio.sleep(2.0)

                # ── Step 4: replay request with solved cookie ──
                # InfinityFree redirects to ?i=1 after challenge
                redirect_url = url
                loc_match = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']'
                                      , first_html)
                if loc_match:
                    candidate = loc_match.group(1)
                    if candidate.startswith('http'):
                        redirect_url = candidate
                    elif candidate.startswith('/'):
                        redirect_url = base + candidate

                bypass_headers = dict(headers)
                bypass_headers["Cookie"] = cookie_val
                bypass_headers["Referer"] = base

                for attempt in range(3):
                    target = redirect_url if attempt == 0 else url
                    async with session.get(
                        target,
                        allow_redirects=True,
                        max_redirects=10,
                        headers=bypass_headers
                    ) as resp2:
                        s2 = resp2.status
                        ct2 = resp2.headers.get("Content-Type", "text/html")
                        final2 = str(resp2.url)
                        html2 = await resp2.text(errors='replace')

                        logger.info(
                            f"InfinityFree bypass attempt {attempt+1}: "
                            f"HTTP {s2}, size={len(html2)}"
                        )

                        still_challenge = any(
                            kw in html2.lower() for kw in challenge_keywords
                        )
                        if s2 == 200 and len(html2) > 500 and not still_challenge:
                            return html2, 200, ct2, final2

                    await asyncio.sleep(1.5)

        except Exception as e:
            raise Exception(f"InfinityFree bypass failed: {e}")

        return None

    async def fetch_with_fallback(
        self, url: str,
        progress_callback: Optional[Callable] = None
    ) -> tuple:
        """
        Returns:
          (html, status_code, content_type, final_url, method_name)
        """
        strategies = [
            ("infinityfree_bypass", self._fetch_infinityfree_bypass, {}),
            ("direct_ssl",      self._fetch_direct,
             {"ssl_verify": True}),
            ("direct_no_ssl",   self._fetch_direct,
             {"ssl_verify": False}),
            ("with_cookies",    self._fetch_with_cookies, {}),
            ("alt_user_agents", self._fetch_alt_ua, {}),
            ("google_cache",    self._fetch_google_cache, {}),
            ("wayback_machine", self._fetch_wayback, {}),
        ]

        last_error = "Unknown error"

        for name, func, kwargs in strategies:
            if progress_callback:
                await progress_callback(
                    f"🔄 <b>Trying method: {name}...</b>\n\n"
                    f"🔗 URL: <code>{url[:80]}</code>"
                )
            try:
                result = await func(url, **kwargs)
                if result and result[0] and len(result[0]) > 100:
                    logger.info(f"✅ {name} succeeded for {url}")
                    content, status, ct, final_url = result
                    return content, status, ct, final_url, name
            except Exception as e:
                last_error = str(e)
                logger.warning(f"❌ {name} failed: {e}")
                await asyncio.sleep(0.5)

        return None, 0, "", url, f"all_failed:{last_error[:100]}"

    async def _fetch_direct(
        self, url: str,
        ssl_verify: bool = True,
        ua: str = None
    ) -> Optional[tuple]:
        """Direct HTTP fetch with retry logic."""
        ssl_ctx = create_ssl_context(verify=ssl_verify)
        connector = TCPConnector(
            ssl=ssl_ctx, limit=20, force_close=True
        )
        timeout = aiohttp.ClientTimeout(
            total=REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT
        )
        headers = build_headers(ua=ua)

        for attempt in range(MAX_RETRIES):
            try:
                async with aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                    headers=headers,
                    cookie_jar=aiohttp.CookieJar()
                ) as session:
                    async with session.get(
                        url,
                        allow_redirects=True,
                        max_redirects=15
                    ) as resp:
                        ct = resp.headers.get("Content-Type", "")
                        final = str(resp.url)
                        status = resp.status

                        if status == 200:
                            text = await resp.text(errors='replace')
                            if text and len(text) > 100:
                                return text, status, ct, final
                        elif status == 429:
                            await asyncio.sleep(
                                RETRY_DELAY * (attempt + 2)
                            )
                        elif status >= 500:
                            if attempt < MAX_RETRIES - 1:
                                await asyncio.sleep(
                                    RETRY_DELAY * (attempt + 1)
                                )
                        else:
                            raise Exception(f"HTTP {status}")

            except (
                aiohttp.ClientConnectorError,
                aiohttp.ServerDisconnectedError,
                asyncio.TimeoutError
            ) as e:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    raise e

        return None

    async def _fetch_with_cookies(
        self, url: str
    ) -> Optional[tuple]:
        """Fetch with cookie acceptance - handles cookie walls."""
        ssl_ctx = create_ssl_context(verify=False)
        connector = TCPConnector(
            ssl=ssl_ctx, limit=10, force_close=True
        )
        timeout = aiohttp.ClientTimeout(
            total=REQUEST_TIMEOUT + 30,
            connect=CONNECT_TIMEOUT
        )
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        headers = build_headers()
        headers["Cookie"] = (
            "cookieConsent=accepted; GDPR=1; session=active"
        )

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=headers,
                cookie_jar=aiohttp.CookieJar()
            ) as session:
                # Pre-visit root to gather cookies
                try:
                    async with session.get(
                        base,
                        allow_redirects=True,
                        max_redirects=10
                    ):
                        pass
                except Exception:
                    pass

                await asyncio.sleep(1)  # Human-like pause

                async with session.get(
                    url,
                    allow_redirects=True,
                    max_redirects=10,
                    headers={"Referer": base}
                ) as resp:
                    if resp.status == 200:
                        ct = resp.headers.get("Content-Type", "")
                        text = await resp.text(errors='replace')
                        if text and len(text) > 100:
                            return text, 200, ct, str(resp.url)

        except Exception as e:
            raise e

        return None

    async def _fetch_alt_ua(self, url: str) -> Optional[tuple]:
        """Try all user agents one by one."""
        for ua in USER_AGENTS:
            try:
                result = await self._fetch_direct(
                    url, ssl_verify=False, ua=ua
                )
                if result:
                    return result
                await asyncio.sleep(0.5)
            except Exception:
                continue
        return None

    async def _fetch_google_cache(
        self, url: str
    ) -> Optional[tuple]:
        """Fetch from Google Cache."""
        cache_url = f"{GOOGLE_CACHE_URL}{url}"
        ssl_ctx = create_ssl_context(verify=True)
        connector = TCPConnector(ssl=ssl_ctx, limit=5)
        timeout = aiohttp.ClientTimeout(total=30, connect=15)

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=build_headers()
            ) as session:
                async with session.get(
                    cache_url, allow_redirects=True
                ) as resp:
                    if resp.status == 200:
                        ct = resp.headers.get("Content-Type", "")
                        text = await resp.text(errors='replace')
                        if text and len(text) > 100:
                            # Remove Google cache header bar
                            soup = BeautifulSoup(text, 'html.parser')
                            for d in soup.find_all(
                                id='google-cache-hdr'
                            ):
                                d.decompose()
                            return str(soup), 200, ct, url

        except Exception as e:
            raise Exception(f"Google cache: {e}")

        return None

    async def _fetch_wayback(self, url: str) -> Optional[tuple]:
        """Fetch from Wayback Machine as last resort."""
        api_url = f"{WAYBACK_API}{url}"
        ssl_ctx = create_ssl_context(verify=True)
        connector = TCPConnector(ssl=ssl_ctx, limit=5)
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=build_headers()
            ) as session:
                async with session.get(api_url) as api_resp:
                    if api_resp.status == 200:
                        data = await api_resp.json()
                        archived = (
                            data.get("archived_snapshots", {})
                            .get("closest", {})
                        )
                        if archived and archived.get("available"):
                            wb_url = archived["url"]
                            async with session.get(
                                wb_url, allow_redirects=True
                            ) as page_resp:
                                if page_resp.status == 200:
                                    ct = page_resp.headers.get(
                                        "Content-Type", ""
                                    )
                                    text = await page_resp.text(
                                        errors='replace'
                                    )
                                    if text and len(text) > 100:
                                        return text, 200, ct, url

        except Exception as e:
            raise Exception(f"Wayback: {e}")

        return None


# ═══════════════════════════════════════════════════════
#  MAIN WEB SCRAPER
# ═══════════════════════════════════════════════════════

class WebScraper:
    """Full scraper with anti-block and complete asset support."""

    def __init__(self):
        self.extractor = AssetExtractor()
        self.fetcher = AdvancedFetcher()

    async def scrape_single(
        self,
        url: str,
        download_assets: bool = True,
        progress_callback: Optional[Callable] = None
    ) -> tuple:
        """Scrape a single page with all its assets."""
        result = ScrapeResult()
        start_time = time.time()

        if progress_callback:
            await progress_callback(
                f"🔄 <b>Fetching page...</b>\n\n"
                f"🔗 URL: <code>{url[:80]}</code>\n\n"
                f"⚡ Trying multiple methods..."
            )

        # Fetch with 6-strategy fallback
        html, status, ct, final_url, method = \
            await self.fetcher.fetch_with_fallback(
                url, progress_callback
            )

        if not html:
            return None, (
                "❌ <b>Could not fetch the page.</b>\n\n"
                "Possible reasons:\n"
                "• Site requires JavaScript (React/Vue/Angular)\n"
                "• Site actively blocks all scrapers\n"
                "• Site is down or unreachable\n"
                "• DNS resolution failed\n\n"
                f"Last result: <code>{method}</code>"
            )

        result.fetch_method = method

        if progress_callback:
            await progress_callback(
                f"✅ <b>Page fetched via {method}!</b>\n\n"
                f"📄 Size: {format_size(len(html.encode()))}\n"
                f"🔗 Final: <code>{final_url[:80]}</code>\n\n"
                f"{'🔍 Extracting assets...' if download_assets else '📝 Processing...'}"
            )

        parsed_base = urlparse(final_url)
        pm = PathManager(parsed_base.netloc)
        page_local = pm.get_page_path(final_url)

        if download_assets:
            # Extract all asset URLs
            asset_map = self.extractor.extract_all(html, final_url)
            total_found = sum(len(v) for v in asset_map.values())

            if progress_callback:
                await progress_callback(
                    f"🔍 <b>Assets found: {total_found}</b>\n\n"
                    f"  🖼 Images: {len(asset_map['images'])}\n"
                    f"  🎨 CSS:    {len(asset_map['css'])}\n"
                    f"  ⚙️ JS:     {len(asset_map['js'])}\n"
                    f"  🔤 Fonts:  {len(asset_map['fonts'])}\n"
                    f"  🎬 Videos: {len(asset_map['videos'])}\n"
                    f"  🎵 Audio:  {len(asset_map['audios'])}\n\n"
                    f"⬇️ Downloading..."
                )

            type_map = {
                "images": "image", "css": "css", "js": "js",
                "fonts": "font", "videos": "video",
                "audios": "audio", "others": "other"
            }

            # Build asset list with local paths
            asset_list = []
            for cat, urls in asset_map.items():
                atype = type_map[cat]
                for aurl in urls[:MAX_ASSETS_PER_PAGE]:
                    local = pm.get_local_path(aurl, atype)
                    asset_list.append((aurl, atype, local))

            # Download all assets
            downloaded = await self._download_assets(
                asset_list, final_url, progress_callback
            )

            # Find and download CSS sub-assets
            css_sub = []
            for asset in downloaded:
                if asset.asset_type == "css":
                    try:
                        css_text = asset.content.decode(
                            'utf-8', errors='replace'
                        )
                        for su in self.extractor.extract_css_assets(
                            css_text, asset.url
                        ):
                            if su not in pm.url_to_path:
                                ext = os.path.splitext(
                                    urlparse(su).path
                                )[1].lower()
                                st = (
                                    "font"
                                    if ext in FONT_EXTENSIONS
                                    else "image"
                                    if ext in IMAGE_EXTENSIONS
                                    else "other"
                                )
                                lp = pm.get_local_path(su, st)
                                css_sub.append((su, st, lp))
                    except Exception:
                        pass

            if css_sub:
                if progress_callback:
                    await progress_callback(
                        f"🔍 {len(css_sub)} CSS sub-assets...\n"
                        f"⬇️ Downloading..."
                    )
                sub_dl = await self._download_assets(
                    css_sub, final_url, None
                )
                downloaded.extend(sub_dl)

            # Store all assets
            for asset in downloaded:
                result.assets[asset.url] = asset

            # Rewrite CSS content with local paths
            for asset in result.assets.values():
                if asset.asset_type == "css":
                    try:
                        css_text = asset.content.decode(
                            'utf-8', errors='replace'
                        )
                        rewritten = HTMLRewriter.rewrite_css(
                            css_text, asset.url,
                            asset.local_path, pm
                        )
                        asset.content = rewritten.encode(
                            'utf-8', errors='replace'
                        )
                        asset.size = len(asset.content)
                    except Exception:
                        pass

            # Rewrite HTML with local paths
            modified_html = HTMLRewriter.rewrite_html(
                html, final_url, page_local, pm
            )
        else:
            modified_html = html

        page = ScrapedPage(
            url=final_url,
            original_html=html,
            modified_html=modified_html,
            status_code=status,
            content_type=ct,
            local_path=page_local,
            fetch_method=method
        )
        result.pages.append(page)
        result.total_pages = 1
        result.total_assets = len(result.assets)
        result.total_size = (
            page.size +
            sum(a.size for a in result.assets.values())
        )
        result.elapsed = time.time() - start_time

        if progress_callback:
            await progress_callback(
                f"✅ <b>Complete!</b>\n\n"
                f"📄 Pages: 1\n"
                f"📦 Assets: {result.total_assets}\n"
                f"💾 Size: {format_size(result.total_size)}\n"
                f"⏱ Time: {result.elapsed:.1f}s\n"
                f"📡 Method: {method}\n\n"
                f"{make_progress_bar(1, 1)}"
            )

        return result, ""

    async def scrape_all_pages(
        self,
        base_url: str,
        download_assets: bool = True,
        progress_callback: Optional[Callable] = None
    ) -> tuple:
        """Scrape all pages of a site with all assets."""
        result = ScrapeResult()
        start_time = time.time()

        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc
        pm = PathManager(base_domain)
        visited_pages: set = set()
        to_visit = [base_url]
        all_asset_urls: dict = {}
        errors_count = 0

        if progress_callback:
            await progress_callback(
                f"🚀 <b>Starting full site scrape</b>\n\n"
                f"🌐 Domain: <code>{base_domain}</code>\n"
                f"📄 Max pages: {MAX_PAGES}\n"
                f"📦 Assets: {'Yes' if download_assets else 'No'}\n\n"
                f"{make_progress_bar(0, 1)}"
            )

        # Fetch first page with all 6 fallback strategies
        html, status, ct, final_url, method = \
            await self.fetcher.fetch_with_fallback(
                base_url, progress_callback
            )

        if not html:
            return None, (
                f"❌ Cannot reach <code>{base_url}</code>\n\n"
                "The site may be:\n"
                "• Down or unreachable\n"
                "• Blocking all scrapers\n"
                "• Requiring JavaScript\n"
                "• Behind Cloudflare protection\n\n"
                "Try again later or check the URL."
            )

        result.fetch_method = method

        if progress_callback:
            await progress_callback(
                f"✅ Connected via <b>{method}</b>!\n"
                f"🔄 Crawling pages..."
            )

        # Process first page
        page_local = pm.get_page_path(final_url)
        first_page = ScrapedPage(
            url=final_url,
            original_html=html,
            modified_html=html,
            status_code=status,
            content_type=ct,
            local_path=page_local,
            fetch_method=method
        )
        result.pages.append(first_page)
        visited_pages.add(self._normalize_url(final_url))

        type_map = {
            "images": "image", "css": "css", "js": "js",
            "fonts": "font", "videos": "video",
            "audios": "audio", "others": "other"
        }

        if "text/html" in ct:
            # Extract links from first page
            for link in self._extract_links(
                html, final_url, base_domain
            ):
                if len(to_visit) + len(result.pages) < MAX_PAGES:
                    to_visit.append(link)

            # Extract assets from first page
            if download_assets:
                pa = self.extractor.extract_all(html, final_url)
                for cat, urls in pa.items():
                    atype = type_map[cat]
                    for aurl in urls:
                        if aurl not in all_asset_urls:
                            lp = pm.get_local_path(aurl, atype)
                            all_asset_urls[aurl] = (atype, lp)

        # Setup session for crawling remaining pages
        ssl_ctx = create_ssl_context(verify=False)
        connector = TCPConnector(
            ssl=ssl_ctx,
            limit=CONCURRENT_REQUESTS * 2,
            force_close=False
        )
        page_timeout = aiohttp.ClientTimeout(
            total=REQUEST_TIMEOUT,
            connect=CONNECT_TIMEOUT
        )
        page_sem = asyncio.Semaphore(CONCURRENT_REQUESTS)

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=page_timeout,
                headers=build_headers(),
                cookie_jar=aiohttp.CookieJar()
            ) as session:

                # ── Phase 1: Crawl all pages ──────────
                while to_visit and len(result.pages) < MAX_PAGES:
                    batch = []
                    while (
                        to_visit and
                        len(batch) < CONCURRENT_REQUESTS
                    ):
                        url = to_visit.pop(0)
                        norm = self._normalize_url(url)
                        if norm not in visited_pages:
                            visited_pages.add(norm)
                            batch.append(url)

                    if not batch:
                        break

                    tasks = [
                        self._fetch_page(session, u, page_sem)
                        for u in batch
                    ]
                    fetched = await asyncio.gather(
                        *tasks, return_exceptions=True
                    )

                    for url, fr in zip(batch, fetched):
                        if isinstance(fr, Exception) or not fr:
                            errors_count += 1
                            continue

                        content, s, fct, furl = fr

                        if s == 200 and content:
                            pl = pm.get_page_path(furl)
                            page = ScrapedPage(
                                url=furl,
                                original_html=content,
                                modified_html=content,
                                status_code=s,
                                content_type=fct,
                                local_path=pl,
                                fetch_method="crawl"
                            )
                            result.pages.append(page)

                            if "text/html" in fct:
                                # Extract more links
                                for link in self._extract_links(
                                    content, furl, base_domain
                                ):
                                    norm = self._normalize_url(link)
                                    if (
                                        norm not in visited_pages
                                        and len(to_visit) +
                                        len(result.pages) < MAX_PAGES
                                    ):
                                        to_visit.append(link)

                                # Collect asset URLs
                                if download_assets:
                                    pa2 = self.extractor.extract_all(
                                        content, furl
                                    )
                                    for cat, urls in pa2.items():
                                        atype = type_map[cat]
                                        for aurl in urls:
                                            if (
                                                aurl not in all_asset_urls
                                                and len(all_asset_urls) <
                                                MAX_TOTAL_ASSETS
                                            ):
                                                lp = pm.get_local_path(
                                                    aurl, atype
                                                )
                                                all_asset_urls[aurl] = (
                                                    atype, lp
                                                )
                        else:
                            errors_count += 1

                    # Progress update after each batch
                    if progress_callback:
                        total_est = (
                            len(result.pages) + len(to_visit)
                        )
                        elapsed = time.time() - start_time
                        await progress_callback(
                            f"🔄 <b>Crawling pages...</b>\n\n"
                            f"✅ Pages: <b>{len(result.pages)}</b>\n"
                            f"📋 Queue: <b>{len(to_visit)}</b>\n"
                            f"📦 Assets: <b>{len(all_asset_urls)}</b>\n"
                            f"❌ Errors: <b>{errors_count}</b>\n"
                            f"⏱ Time: <b>{elapsed:.1f}s</b>\n\n"
                            f"{make_progress_bar(len(result.pages), min(total_est, MAX_PAGES))}"
                        )

                    await asyncio.sleep(0.2)

                # ── Phase 2: Download all assets ──────
                if download_assets and all_asset_urls:
                    if progress_callback:
                        await progress_callback(
                            f"📦 <b>Downloading "
                            f"{len(all_asset_urls)} assets...</b>\n\n"
                            f"{make_progress_bar(0, len(all_asset_urls))}"
                        )

                    first_url = (
                        result.pages[0].url
                        if result.pages else base_url
                    )
                    asset_list = [
                        (url, atype, local)
                        for url, (atype, local)
                        in all_asset_urls.items()
                    ]
                    downloaded = await self._download_assets(
                        asset_list, first_url, progress_callback
                    )

                    for asset in downloaded:
                        result.assets[asset.url] = asset

                    # Find CSS sub-assets
                    css_sub = []
                    for asset in downloaded:
                        if asset.asset_type == "css":
                            try:
                                css_text = asset.content.decode(
                                    'utf-8', errors='replace'
                                )
                                for su in self.extractor.extract_css_assets(
                                    css_text, asset.url
                                ):
                                    if su not in pm.url_to_path:
                                        ext = os.path.splitext(
                                            urlparse(su).path
                                        )[1].lower()
                                        st = (
                                            "font"
                                            if ext in FONT_EXTENSIONS
                                            else "image"
                                            if ext in IMAGE_EXTENSIONS
                                            else "other"
                                        )
                                        lp = pm.get_local_path(su, st)
                                        css_sub.append((su, st, lp))
                            except Exception:
                                pass

                    if css_sub:
                        sub_dl = await self._download_assets(
                            css_sub, first_url, None
                        )
                        for a in sub_dl:
                            result.assets[a.url] = a

                    # ── Phase 3: Rewrite CSS files ────
                    for asset in result.assets.values():
                        if asset.asset_type == "css":
                            try:
                                css_text = asset.content.decode(
                                    'utf-8', errors='replace'
                                )
                                rewritten = HTMLRewriter.rewrite_css(
                                    css_text, asset.url,
                                    asset.local_path, pm
                                )
                                asset.content = rewritten.encode(
                                    'utf-8', errors='replace'
                                )
                                asset.size = len(asset.content)
                            except Exception:
                                pass

                    # ── Phase 4: Rewrite all HTML ─────
                    if progress_callback:
                        await progress_callback(
                            "✏️ <b>Rewriting HTML with local paths...</b>"
                        )
                    for page in result.pages:
                        page.modified_html = HTMLRewriter.rewrite_html(
                            page.original_html, page.url,
                            page.local_path, pm
                        )

        except Exception as e:
            logger.error(f"Crawl error: {e}", exc_info=True)
            if not result.pages:
                return None, f"Crawl failed: {str(e)[:200]}"
            result.warnings.append(f"Partial: {str(e)[:100]}")

        result.total_pages = len(result.pages)
        result.total_assets = len(result.assets)
        result.total_size = (
            sum(p.size for p in result.pages) +
            sum(a.size for a in result.assets.values())
        )
        result.errors = errors_count
        result.elapsed = time.time() - start_time

        if progress_callback:
            await progress_callback(
                f"✅ <b>Complete!</b>\n\n"
                f"📄 Pages: <b>{result.total_pages}</b>\n"
                f"📦 Assets: <b>{result.total_assets}</b>\n"
                f"💾 Size: <b>{format_size(result.total_size)}</b>\n"
                f"❌ Errors: <b>{result.errors}</b>\n"
                f"⏱ Time: <b>{result.elapsed:.1f}s</b>\n\n"
                f"{make_progress_bar(result.total_pages, result.total_pages)}\n\n"
                f"📦 Packing files..."
            )

        return result, ""

    async def _download_assets(
        self,
        asset_list: list,
        referer: str,
        progress_callback: Optional[Callable] = None
    ) -> list:
        """Download all assets concurrently with smart headers."""
        downloaded = []
        total = len(asset_list)
        completed = [0]
        failed = [0]
        total_bytes = [0]
        last_update = [time.time()]

        ssl_ctx = create_ssl_context(verify=False)
        connector = TCPConnector(
            ssl=ssl_ctx,
            limit=CONCURRENT_ASSET_DOWNLOADS * 2,
            limit_per_host=10,
            force_close=False
        )
        timeout = aiohttp.ClientTimeout(
            total=ASSET_TIMEOUT,
            connect=CONNECT_TIMEOUT
        )
        base_headers = dict(ASSET_HEADERS)
        base_headers["User-Agent"] = get_random_ua()
        base_headers["Referer"] = referer
        sem = asyncio.Semaphore(CONCURRENT_ASSET_DOWNLOADS)

        async def dl_one(
            url: str,
            asset_type: str,
            local_path: str
        ):
            async with sem:
                # Set type-specific headers
                headers = dict(base_headers)
                if asset_type == "css":
                    headers["Accept"] = "text/css,*/*;q=0.1"
                    headers["Sec-Fetch-Dest"] = "style"
                elif asset_type == "js":
                    headers["Accept"] = "*/*"
                    headers["Sec-Fetch-Dest"] = "script"
                elif asset_type == "font":
                    headers["Accept"] = "*/*"
                    headers["Sec-Fetch-Dest"] = "font"
                else:
                    headers["Accept"] = (
                        "image/avif,image/webp,image/apng,"
                        "image/svg+xml,image/*,*/*;q=0.8"
                    )
                    headers["Sec-Fetch-Dest"] = "image"

                for attempt in range(MAX_RETRIES):
                    try:
                        async with aiohttp.ClientSession(
                            connector=connector,
                            timeout=timeout,
                            headers=headers
                        ) as session:
                            async with session.get(
                                url,
                                allow_redirects=True,
                                max_redirects=10
                            ) as resp:
                                if resp.status == 200:
                                    # Check size header first
                                    cl = resp.headers.get(
                                        'Content-Length', 0
                                    )
                                    if (
                                        cl and
                                        int(cl) > MAX_SINGLE_ASSET_SIZE
                                    ):
                                        failed[0] += 1
                                        return

                                    data = await resp.read()

                                    if len(data) > MAX_SINGLE_ASSET_SIZE:
                                        failed[0] += 1
                                        return

                                    ct = resp.headers.get(
                                        "Content-Type", ""
                                    )
                                    asset = ScrapedAsset(
                                        url=url,
                                        content=data,
                                        content_type=ct,
                                        local_path=local_path,
                                        asset_type=asset_type
                                    )
                                    downloaded.append(asset)
                                    total_bytes[0] += asset.size
                                    completed[0] += 1

                                    # Rate limited progress update
                                    now = time.time()
                                    if (
                                        progress_callback and
                                        now - last_update[0] > 2.5
                                    ):
                                        last_update[0] = now
                                        await progress_callback(
                                            f"⬇️ <b>Downloading assets...</b>\n\n"
                                            f"✅ Done: <b>{completed[0]}/{total}</b>\n"
                                            f"❌ Failed: <b>{failed[0]}</b>\n"
                                            f"💾 Downloaded: "
                                            f"<b>{format_size(total_bytes[0])}</b>\n\n"
                                            f"{make_progress_bar(completed[0], total)}"
                                        )
                                    return

                                elif resp.status == 429:
                                    await asyncio.sleep(
                                        RETRY_DELAY * (attempt + 2)
                                    )
                                else:
                                    break

                    except asyncio.TimeoutError:
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAY)
                    except Exception:
                        break

                failed[0] += 1

        # Process in batches
        batch_size = CONCURRENT_ASSET_DOWNLOADS * 3
        for i in range(0, len(asset_list), batch_size):
            batch = asset_list[i:i + batch_size]
            tasks = [
                dl_one(url, atype, local)
                for url, atype, local in batch
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Stop if total size limit exceeded
            if total_bytes[0] > MAX_TOTAL_SIZE:
                logger.warning("Max total size reached")
                break

        return downloaded

    async def _fetch_page(
        self,
        session: aiohttp.ClientSession,
        url: str,
        semaphore: asyncio.Semaphore
    ) -> Optional[tuple]:
        """Fetch a single HTML page using existing session."""
        async with semaphore:
            for attempt in range(MAX_RETRIES):
                try:
                    headers = build_headers(
                        ua=get_random_ua(), referer=url
                    )
                    async with session.get(
                        url,
                        allow_redirects=True,
                        max_redirects=10,
                        headers=headers
                    ) as resp:
                        ct = resp.headers.get("Content-Type", "")
                        if (
                            "text/html" not in ct and
                            "text/plain" not in ct
                        ):
                            return None

                        if resp.status == 200:
                            text = await resp.text(errors='replace')
                            return (
                                text, resp.status,
                                ct, str(resp.url)
                            )
                        elif resp.status in (429, 503):
                            await asyncio.sleep(
                                RETRY_DELAY * (attempt + 2)
                            )
                        else:
                            return None

                except asyncio.TimeoutError:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                except Exception:
                    break

            return None

    def _extract_links(
        self,
        html: str,
        page_url: str,
        base_domain: str
    ) -> list:
        """Extract all internal links from HTML."""
        links = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for tag in soup.find_all('a', href=True):
                href = tag['href'].strip()
                if not href or any(
                    href.startswith(p) for p in
                    ['#', 'mailto:', 'tel:', 'javascript:', 'data:']
                ):
                    continue

                full = urljoin(page_url, href)
                parsed = urlparse(full)

                if parsed.netloc != base_domain:
                    continue

                path_lower = parsed.path.lower()
                skip = ALL_ASSET_EXTENSIONS - {
                    '.html', '.htm', '.php',
                    '.asp', '.aspx'
                }
                if any(path_lower.endswith(e) for e in skip):
                    continue

                clean = (
                    f"{parsed.scheme}://"
                    f"{parsed.netloc}{parsed.path}"
                )
                if parsed.query:
                    clean += f"?{parsed.query}"

                links.append(clean)

        except Exception:
            pass

        return links

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        norm = (
            f"{parsed.scheme}://{parsed.netloc}{path}"
        )
        if parsed.query:
            norm += f"?{parsed.query}"
        return norm.lower()




# ═══════════════════════════════════════════════════════
#  FILE CREATORS
# ═══════════════════════════════════════════════════════

def create_single_file(
    result: ScrapeResult,
    url: str,
    include_assets: bool = False
) -> tuple:
    """
    Create a single combined HTML file from all scraped pages.
    Uses original_html so all external URLs stay intact.
    """
    parts = []
    sep = "\n" + "=" * 80 + "\n"

    for i, page in enumerate(result.pages, 1):
        header = (
            f"{sep}"
            f"PAGE {i}/{len(result.pages)}\n"
            f"URL: {page.url}\n"
            f"STATUS: {page.status_code}\n"
            f"SIZE: {format_size(page.size)}\n"
            f"METHOD: {page.fetch_method}\n"
            f"{sep}\n"
        )
        parts.append(header + page.original_html)

    content = "\n".join(parts)
    parsed = urlparse(url)
    domain = re.sub(r'[^\w-]', '_', parsed.netloc)
    filename = (
        f"scrape_{domain}_{len(result.pages)}_pages.html"
    )
    return content.encode('utf-8', errors='replace'), filename


def create_zip_file(
    result: ScrapeResult,
    url: str,
    include_assets: bool = True
) -> tuple:
    """
    Create organized ZIP archive with all pages and assets.

    ZIP structure:
        _README.txt
        index.html
        about.html
        ...
        assets/
            images/
            css/
            js/
            fonts/
            videos/
            audio/
            other/
    """
    buffer = io.BytesIO()
    used_names: set = set()

    with zipfile.ZipFile(
        buffer, 'w',
        zipfile.ZIP_DEFLATED,
        compresslevel=6
    ) as zf:

        # ── Build asset stats for README ──────────────
        asset_stats: dict = {}
        for asset in result.assets.values():
            t = asset.asset_type
            if t not in asset_stats:
                asset_stats[t] = {"count": 0, "size": 0}
            asset_stats[t]["count"] += 1
            asset_stats[t]["size"] += asset.size

        type_icons = {
            "image": "🖼",
            "css":   "🎨",
            "js":    "⚙️",
            "font":  "🔤",
            "video": "🎬",
            "audio": "🎵",
            "other": "📄"
        }

        # ── Build README content ───────────────────────
        readme_lines = [
            "╔══════════════════════════════════════╗",
            "║          WEB SCRAPE REPORT             ║",
            "║       by @TALK_WITH_STEALED            ║",
            "╚══════════════════════════════════════╝",
            "",
            f"Source URL : {url}",
            f"Pages      : {result.total_pages}",
            f"Assets     : {result.total_assets}",
            f"Total Size : {format_size(result.total_size)}",
            f"Scrape Time: {result.elapsed:.1f}s",
            f"Method     : {result.fetch_method}",
            f"Errors     : {result.errors}",
        ]

        if result.warnings:
            readme_lines.append(
                f"Warnings   : {'; '.join(result.warnings)}"
            )

        # Asset breakdown table
        readme_lines.extend([
            "",
            "─" * 50,
            "",
            "ASSET BREAKDOWN:",
        ])
        for atype, stats in sorted(asset_stats.items()):
            icon = type_icons.get(atype, "📄")
            readme_lines.append(
                f"  {icon} {atype:8s}: "
                f"{stats['count']:4d} files"
                f" ({format_size(stats['size'])})"
            )

        # Page list
        readme_lines.extend([
            "",
            "─" * 50,
            "",
            "PAGES:",
        ])
        for i, page in enumerate(result.pages, 1):
            readme_lines.append(
                f"  {i:3d}. {page.url}\n"
                f"       -> {page.local_path}"
                f" ({format_size(page.size)})"
                f" [{page.fetch_method}]"
            )

        # Asset list
        if include_assets and result.assets:
            readme_lines.extend([
                "",
                "─" * 50,
                "",
                "ASSETS:",
            ])
            for asset in sorted(
                result.assets.values(),
                key=lambda a: a.asset_type
            ):
                icon = type_icons.get(asset.asset_type, "📄")
                readme_lines.append(
                    f"  {icon} [{asset.asset_type:5s}] "
                    f"{asset.local_path}"
                    f" ({format_size(asset.size)})"
                )

        zf.writestr("_README.txt", "\n".join(readme_lines))

        # ── Write HTML pages ───────────────────────────
        for page in result.pages:
            path = page.local_path

            # Ensure unique filename
            if path in used_names:
                name, ext = os.path.splitext(path)
                c = 1
                while f"{name}_{c}{ext}" in used_names:
                    c += 1
                path = f"{name}_{c}{ext}"
            used_names.add(path)

            # Use modified_html (local paths) if assets included
            # Use original_html (external URLs) if html only
            html_out = (
                page.modified_html
                if include_assets
                else page.original_html
            )
            zf.writestr(
                path,
                html_out.encode('utf-8', errors='replace')
            )

        # ── Write all asset files ──────────────────────
        if include_assets:
            for asset in result.assets.values():
                path = asset.local_path

                # Ensure unique filename
                if path in used_names:
                    name, ext = os.path.splitext(path)
                    c = 1
                    while f"{name}_{c}{ext}" in used_names:
                        c += 1
                    path = f"{name}_{c}{ext}"
                used_names.add(path)

                # Write binary asset content
                zf.writestr(path, asset.content)

    zip_bytes = buffer.getvalue()

    # Build filename
    parsed = urlparse(url)
    domain = re.sub(r'[^\w-]', '_', parsed.netloc)
    fn = f"scrape_{domain}_{result.total_pages}p"
    if include_assets:
        fn += f"_{result.total_assets}a"
    fn += ".zip"

    return zip_bytes, fn
