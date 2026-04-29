"""Utility functions for the Telegram Scraper Bot."""

import re
import time
from urllib.parse import urlparse

from config import DEVELOPER_USERNAME, DEVELOPER_LINK


def get_welcome_message() -> str:
    """Return the formatted welcome message."""
    return (
        "╔══════════════════════════════╗\n"
        "║   🙏 THANKS FOR USING THE BOT   ║\n"
        "╠══════════════════════════════╣\n"
        "║                                                              ║\n"
        "║   👨‍💻 THIS BOT IS DEVELOPED BY           ║\n"
        "║                                                              ║\n"
        "║   ⚡ @TALK_WITH_STEALED ⚡    ║\n"
        "║                                                              ║\n"
        "║   📩 CONTACT HIM FOR YOUR    ║\n"
        "║        CUSTOM BOTS                       ║\n"
        "║                                                              ║\n"
        "╚══════════════════════════════╝"
    )


def get_help_message() -> str:
    """Return the HTML formatted help message."""
    return (
        "📖 <b>HOW TO USE THIS BOT</b>\n\n"
        "1️⃣ Click <b>🔍 Scrape Single Page</b> — scrape one page\n"
        "2️⃣ Click <b>🌐 Scrape All Pages</b> — crawl entire site\n"
        "3️⃣ Send the URL when prompted\n"
        "4️⃣ Choose: <b>HTML Only</b> or <b>HTML + All Assets</b>\n"
        "5️⃣ Choose: <b>Single File</b> or <b>ZIP Archive</b>\n\n"
        "📦 <b>What gets downloaded:</b>\n"
        "  🖼 Images (jpg, png, gif, svg, webp, ico, avif...)\n"
        "  🎨 CSS Stylesheets + url() assets inside CSS\n"
        "  ⚙️ JavaScript files\n"
        "  🔤 Fonts (woff, woff2, ttf, eot, otf)\n"
        "  🎬 Videos (mp4, webm, ogg)\n"
        "  🎵 Audio (mp3, wav, aac)\n"
        "  📄 Other linked resources\n\n"
        "⚡ <b>Commands:</b>\n"
        "/start — Welcome message\n"
        "/help — This message\n"
        "/scrape &lt;url&gt; — Quick single page\n"
        "/scrapeall &lt;url&gt; — Quick full site\n"
        "/admin — Admin panel\n\n"
        f"👨‍💻 Developer: {DEVELOPER_USERNAME}\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )


def validate_url(url: str) -> tuple[bool, str]:
    """Validate URL. Returns (is_valid, cleaned_url_or_error)."""
    url = url.strip()
    if not url:
        return False, "❌ URL cannot be empty."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False, "❌ Invalid URL format."
        if not re.match(
            r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
            parsed.netloc.split(':')[0]
        ):
            return False, "❌ Invalid domain name."
        return True, url
    except Exception:
        return False, "❌ Could not parse URL."


def make_progress_bar(current: int, total: int,
                      bar_length: int = 20) -> str:
    """Create a text progress bar."""
    if total == 0:
        percentage = 100
    else:
        percentage = min(int((current / total) * 100), 100)
    filled = min(int(bar_length * current / max(total, 1)), bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    return f"[{bar}] {percentage}% ({current}/{total})"


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def format_timestamp(ts: float) -> str:
    """Format unix timestamp to readable string."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def truncate_text(text: str, max_len: int = 4000) -> str:
    """Truncate text to fit Telegram message limit."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 20] + "\n\n... [TRUNCATED]"
