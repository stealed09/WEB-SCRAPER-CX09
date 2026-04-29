"""Configuration file for the Telegram Scraper Bot."""

import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",")]

LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", None)
if LOG_CHANNEL_ID:
    LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)

# ── Scraping Settings ─────────────────────────────────
MAX_PAGES = 599
MAX_ASSETS_PER_PAGE = 300
MAX_TOTAL_ASSETS = 5000
REQUEST_TIMEOUT = 60          # Increased for slow free hosts
ASSET_TIMEOUT = 90            # Increased for large assets
CONNECT_TIMEOUT = 30          # Connection timeout
MAX_RETRIES = 5               # More retries for flaky free hosts
RETRY_DELAY = 2.0             # Delay between retries
CONCURRENT_REQUESTS = 5       # Lower for free hosts (polite)
CONCURRENT_ASSET_DOWNLOADS = 10
MAX_FILE_SIZE = 50 * 1024 * 1024       # 50MB Telegram limit
MAX_SINGLE_ASSET_SIZE = 25 * 1024 * 1024  # 25MB per asset
MAX_TOTAL_SIZE = 300 * 1024 * 1024     # 300MB total

# ── Browser User Agents (Rotate) ─────────────────────
USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
    "Gecko/20100101 Firefox/121.0",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Safari Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome Android
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]

# ── Full Browser Headers ──────────────────────────────
BROWSER_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;"
        "q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "DNT": "1",
}

ASSET_HEADERS = {
    "Accept": (
        "image/avif,image/webp,image/apng,image/svg+xml,"
        "image/*,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-origin",
}

# ── Asset Extensions ──────────────────────────────────
IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.webp',
    '.bmp', '.tiff', '.tif', '.avif', '.apng', '.jfif', '.pjpeg', '.pjp'
}
CSS_EXTENSIONS = {'.css'}
JS_EXTENSIONS = {'.js', '.mjs', '.cjs'}
FONT_EXTENSIONS = {'.woff', '.woff2', '.ttf', '.eot', '.otf'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.ogg', '.ogv', '.mov', '.avi'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.aac', '.flac', '.m4a'}
OTHER_ASSET_EXTENSIONS = {'.pdf', '.xml', '.json', '.map', '.txt'}

ALL_ASSET_EXTENSIONS = (
    IMAGE_EXTENSIONS | CSS_EXTENSIONS | JS_EXTENSIONS |
    FONT_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS |
    OTHER_ASSET_EXTENSIONS
)

# ── Alternative Fetch Methods ─────────────────────────
# Will try these proxy/fetch methods if direct fails
GOOGLE_CACHE_URL = "https://webcache.googleusercontent.com/search?q=cache:"
WAYBACK_API = "http://archive.org/wayback/available?url="

# ── Database ─────────────────────────────────────────
DB_FILE = "bot_database.db"

# ── Developer ────────────────────────────────────────
DEVELOPER_USERNAME = "@TALK_WITH_STEALED"
DEVELOPER_LINK = "https://t.me/TALK_WITH_STEALED"
