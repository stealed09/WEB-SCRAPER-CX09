"""
═══════════════════════════════════════════════════
  🕷️ SOURCE CODE SCRAPER BOT
  Developed by: @TALK_WITH_STEALED
  Library: python-telegram-bot v20+
═══════════════════════════════════════════════════
"""

import os
import json
import logging
import asyncio
import datetime
import re
import hashlib
from io import BytesIO
from urllib.parse import urljoin, urlparse, urlunparse
from typing import Dict, List, Set, Optional

import requests
from bs4 import BeautifulSoup
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode, ChatAction
from telegram.error import BadRequest, TimedOut

# ─────────────────── CONFIGURATION ───────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Your Telegram User ID
DATA_FILE = "bot_data.json"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per chunk (Telegram limit ~50MB, use 10MB for safety)
MAX_PAGES = 100  # Maximum pages to scrape in scrapeall mode
REQUEST_TIMEOUT = 30  # seconds
MAX_REDIRECTS = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ─────────────────── LOGGING SETUP ───────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ─────────────────── DATA MANAGEMENT ───────────────────


def load_data() -> Dict:
    """Load bot data from JSON file."""
    default_data = {
        "allowed_users": [],
        "log_channel": None,
        "stats": {"total_scrapes": 0, "total_users": set()},
    }
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            # Ensure all keys exist
            for key, val in default_data.items():
                if key not in data:
                    data[key] = val
            # Convert stats list back to proper format
            if isinstance(data["stats"].get("total_users"), list):
                pass  # Keep as list for JSON serialization
            return data
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading data: {e}")
    return default_data


def save_data(data: Dict) -> None:
    """Save bot data to JSON file."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        logger.error(f"Error saving data: {e}")


# ─────────────────── HELPER FUNCTIONS ───────────────────


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id == ADMIN_ID


def is_allowed(user_id: int) -> bool:
    """Check if user is allowed to use the bot."""
    if is_admin(user_id):
        return True
    data = load_data()
    return user_id in data.get("allowed_users", [])


def validate_url(url: str) -> bool:
    """Validate URL format."""
    url_pattern = re.compile(
        r"^https?://"
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
        r"localhost|"
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
        r"(?::\d+)?"
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )
    return bool(url_pattern.match(url))


def normalize_url(url: str) -> str:
    """Normalize URL by adding scheme if missing."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def get_domain(url: str) -> str:
    """Extract domain from URL."""
    parsed = urlparse(url)
    return parsed.netloc


def is_same_domain(base_url: str, test_url: str) -> bool:
    """Check if two URLs belong to the same domain."""
    return get_domain(base_url) == get_domain(test_url)


def clean_url(url: str) -> str:
    """Remove fragments and normalize URL."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


# ─────────────────── SCRAPING ENGINE ───────────────────


def fetch_page(url: str, session: requests.Session) -> Optional[requests.Response]:
    """Fetch a single page with error handling."""
    try:
        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        return response
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout fetching: {url}")
        return None
    except requests.exceptions.TooManyRedirects:
        logger.warning(f"Too many redirects: {url}")
        return None
    except requests.exceptions.SSLError:
        logger.warning(f"SSL Error: {url}")
        return None
    except requests.exceptions.ConnectionError:
        logger.warning(f"Connection Error: {url}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.warning(f"HTTP Error {e.response.status_code}: {url}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return None


def extract_links(html: str, base_url: str) -> Set[str]:
    """Extract all internal links from HTML."""
    links = set()
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["a", "link", "area"]):
            href = tag.get("href")
            if href:
                full_url = urljoin(base_url, href)
                full_url = clean_url(full_url)
                if is_same_domain(base_url, full_url):
                    links.add(full_url)
    except Exception as e:
        logger.error(f"Error extracting links: {e}")
    return links


def scrape_single_page(url: str) -> Dict:
    """Scrape a single page and return result dict."""
    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS

    result = {
        "url": url,
        "success": False,
        "source_code": None,
        "status_code": None,
        "error": None,
        "title": None,
        "content_type": None,
    }

    response = fetch_page(url, session)
    if response is None:
        result["error"] = "Failed to fetch the URL. The site might be down, blocked, or the URL is invalid."
        return result

    result["status_code"] = response.status_code
    result["success"] = True
    result["source_code"] = response.text
    result["content_type"] = response.headers.get("Content-Type", "unknown")

    # Try to extract title
    try:
        soup = BeautifulSoup(response.text, "html.parser")
        title_tag = soup.find("title")
        result["title"] = title_tag.text.strip() if title_tag else "No title"
    except Exception:
        result["title"] = "Could not parse title"

    session.close()
    return result


async def scrape_all_pages_async(
    start_url: str, context: ContextTypes.DEFAULT_TYPE, chat_id: int
) -> Dict:
    """Scrape all pages from a starting URL (same domain)."""
    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS

    result = {
        "start_url": start_url,
        "pages": {},
        "total_pages": 0,
        "errors": [],
    }

    visited: Set[str] = set()
    to_visit: Set[str] = {clean_url(start_url)}
    domain = get_domain(start_url)

    progress_msg = None

    while to_visit and len(visited) < MAX_PAGES:
        current_url = to_visit.pop()

        if current_url in visited:
            continue
        visited.add(current_url)

        # Update progress
        page_num = len(visited)
        try:
            progress_text = (
                f"🔍 **Scraping in Progress**\n\n"
                f"📄 Page {page_num}/{len(to_visit) + page_num}\n"
                f"🌐 `{current_url[:60]}...`\n\n"
                f"✅ Found: {result['total_pages']} pages\n"
                f"⏳ Queue: {len(to_visit)} remaining"
            )
            if progress_msg:
                try:
                    await progress_msg.edit_text(progress_text, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    pass
            else:
                progress_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=progress_text,
                    parse_mode=ParseMode.MARKDOWN,
                )
        except Exception:
            pass

        # Fetch page (run in executor to not block)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, lambda: fetch_page(current_url, session))

        if response is None:
            result["errors"].append(f"Failed: {current_url}")
            continue

        # Store source code
        page_data = {
            "url": current_url,
            "status_code": response.status_code,
            "source_code": response.text,
            "content_type": response.headers.get("Content-Type", "unknown"),
        }
        result["pages"][current_url] = page_data
        result["total_pages"] += 1

        # Extract more links
        if "text/html" in response.headers.get("Content-Type", ""):
            new_links = await asyncio.get_running_loop().run_in_executor(
                None, lambda: extract_links(response.text, current_url)
            )
            for link in new_links:
                if link not in visited:
                    to_visit.add(link)

    # Delete progress message
    if progress_msg:
        try:
            await progress_msg.delete()
        except Exception:
            pass

    session.close()
    return result


# ─────────────────── FILE SENDING ───────────────────


async def send_source_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    source_code: str,
    filename: str,
    caption: str = "",
    is_html: bool = False,
) -> None:
    """Send source code as a file, splitting if necessary."""
    extension = ".html" if is_html else ".txt"
    encoding = "utf-8"

    source_bytes = source_code.encode(encoding)
    total_size = len(source_bytes)
    chunk_size = MAX_FILE_SIZE

    if total_size <= chunk_size:
        # Single file
        bio = BytesIO(source_bytes)
        bio.name = filename + extension
        bio.seek(0)

        await update.message.reply_document(
            document=bio,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        # Split into multiple files
        num_chunks = (total_size + chunk_size - 1) // chunk_size
        await update.message.reply_text(
            f"📦 File too large ({total_size / 1024:.1f} KB). Splitting into {num_chunks} parts...",
        )

        for i in range(num_chunks):
            start = i * chunk_size
            end = min(start + chunk_size, total_size)
            chunk = source_bytes[start:end]

            bio = BytesIO(chunk)
            bio.name = f"{filename}_part{i + 1}{extension}"
            bio.seek(0)

            part_caption = f"📄 Part {i + 1}/{num_chunks}\n{caption}"
            await update.message.reply_document(
                document=bio,
                caption=part_caption,
                parse_mode=ParseMode.MARKDOWN,
            )


async def send_scrapeall_files(
    chat_id: int,
    bot,
    context: ContextTypes.DEFAULT_TYPE,
    result: Dict,
) -> None:
    """Send all scraped pages as individual files."""
    total = result["total_pages"]
    domain = get_domain(result["start_url"])
    safe_domain = re.sub(r"[^\w\-.]", "_", domain)

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ **Scraping Complete!**\n\n"
            f"🌐 Domain: `{domain}`\n"
            f"📄 Total Pages: {total}\n"
            f"❌ Errors: {len(result['errors'])}\n\n"
            f"📤 Sending source codes..."
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    count = 0
    for url, page_data in result["pages"].items():
        count += 1
        # Create safe filename
        parsed = urlparse(url)
        path = parsed.path.strip("/").replace("/", "_") or "index"
        safe_name = f"{safe_domain}_{path}"

        # Progress
        await bot.send_message(
            chat_id=chat_id,
            text=f"📤 Sending page {count}/{total}: `{url[:50]}...`",
            parse_mode=ParseMode.MARKDOWN,
        )

        is_html = "html" in page_data.get("content_type", "")
        caption = (
            f"📄 Page {count}/{total}\n"
            f"🌐 `{url}`\n"
            f"📊 Status: {page_data.get('status_code', 'N/A')}"
        )

        # Send file directly
        source_bytes = page_data["source_code"].encode("utf-8")
        extension = ".html" if is_html else ".txt"
        bio = BytesIO(source_bytes)
        bio.name = safe_name + extension
        bio.seek(0)

        try:
            await bot.send_document(
                chat_id=chat_id,
                document=bio,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Failed to send file {safe_name}: {e}")
            # Try splitting if too large
            chunk_size = MAX_FILE_SIZE
            if len(source_bytes) > chunk_size:
                num_chunks = (len(source_bytes) + chunk_size - 1) // chunk_size
                for i in range(num_chunks):
                    start_b = i * chunk_size
                    end_b = min(start_b + chunk_size, len(source_bytes))
                    chunk = source_bytes[start_b:end_b]
                    part_bio = BytesIO(chunk)
                    part_bio.name = f"{safe_name}_part{i + 1}{extension}"
                    part_bio.seek(0)
                    await bot.send_document(
                        chat_id=chat_id,
                        document=part_bio,
                        caption=f"📄 Part {i + 1}/{num_chunks} - {caption}",
                        parse_mode=ParseMode.MARKDOWN,
                    )

        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)

    # Send error summary if any
    if result["errors"]:
        error_text = "⚠️ **Errors encountered:**\n\n"
        for err in result["errors"][:20]:  # Limit error messages
            error_text += f"• `{err}`\n"
        if len(result["errors"]) > 20:
            error_text += f"\n... and {len(result['errors']) - 20} more errors."

        await bot.send_message(chat_id=chat_id, text=error_text, parse_mode=ParseMode.MARKDOWN)


# ─────────────────── LOGGING TO CHANNEL ───────────────────


async def log_to_channel(context: ContextTypes.DEFAULT_TYPE, message: str) -> None:
    """Send log message to the configured log channel."""
    data = load_data()
    channel = data.get("log_channel")
    if channel:
        try:
            await context.bot.send_message(
                chat_id=channel,
                text=f"📋 **Bot Log**\n\n{message}\n\n🕐 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Failed to log to channel: {e}")


# ─────────────────── COMMAND HANDLERS ───────────────────


WELCOME_TEXT = (
    "```\n"
    "╔══════════════════════════════╗\n"
    "║  🙏 THANKS FOR USING THE BOT  ║\n"
    "╠══════════════════════════════╣\n"
    "║                              ║\n"
    "║  👨‍💻 THIS BOT IS DEVELOPED BY  ║\n"
    "║                              ║\n"
    "║  ⚡ @TALK_WITH_STEALED ⚡      ║\n"
    "║                              ║\n"
    "║  📩 CONTACT HIM FOR YOUR      ║\n"
    "║       CUSTOM BOTS            ║\n"
    "║                              ║\n"
    "╚══════════════════════════════╝\n"
    "```"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - Send welcome message."""
    user = update.effective_user
    user_id = user.id

    # Track user
    data = load_data()
    if "total_users" not in data["stats"]:
        data["stats"]["total_users"] = []
    if user_id not in data["stats"]["total_users"]:
        data["stats"]["total_users"].append(user_id)
        save_data(data)

    # Welcome message
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔍 Scrape URL", callback_data="action_scrape"),
                InlineKeyboardButton("🌐 Scrape All", callback_data="action_scrapeall"),
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="action_help"),
                InlineKeyboardButton("📊 Status", callback_data="action_status"),
            ],
            [
                InlineKeyboardButton(
                    "📩 Contact Developer", url="https://t.me/TALK_WITH_STEALED"
                )
            ],
        ]
    )

    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )

    # Log
    await log_to_channel(
        context,
        f"👤 New user started bot\n"
        f"• Name: {user.first_name}\n"
        f"• Username: @{user.username or 'N/A'}\n"
        f"• ID: `{user_id}`",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = (
        "📖 **HOW TO USE THIS BOT**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**🔍 Scrape Single Page:**\n"
        "• Click `🔍 Scrape URL` button\n"
        "• Or use `/scrape <url>`\n"
        "• Bot will fetch and send the source code\n\n"
        "**🌐 Scrape All Pages:**\n"
        "• Click `🌐 Scrape All` button\n"
        "• Or use `/scrapeall <url>`\n"
        "• Bot will crawl all pages on the domain\n\n"
        "**📝 Commands:**\n"
        "• `/start` - Welcome message\n"
        "• `/scrape <url>` - Scrape single page\n"
        "• `/scrapeall <url>` - Scrape all pages\n"
        "• `/help` - This help message\n\n"
        "**⚠️ Notes:**\n"
        "• Large files are split automatically\n"
        "• Max 100 pages per scrapeall request\n"
        "• Some sites may block scraping\n"
        "• Source code is sent as `.txt` or `.html`"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔍 Scrape URL", callback_data="action_scrape"),
                InlineKeyboardButton("🌐 Scrape All", callback_data="action_scrapeall"),
            ],
            [
                InlineKeyboardButton(
                    "📩 Contact Developer", url="https://t.me/TALK_WITH_STEALED"
                )
            ],
        ]
    )

    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scrape command."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text(
            "🚫 **Access Denied**\n\nYou are not authorized to use this bot. "
            "Contact the admin to get access.",
            parse_mode=ParseMode.MARKDOWN,
        )
        await log_to_channel(
            context,
            f"🚫 Unauthorized access attempt\n• User ID: `{user_id}`",
        )
        return

    if not context.args:
        # Set waiting state
        context.user_data["waiting_for"] = "scrape"
        await update.message.reply_text(
            "🔍 **Send me the URL you want to scrape:**\n\n"
            "Example: `https://example.com`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = " ".join(context.args)
    await do_scrape(update, context, url)


async def scrapeall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scrapeall command."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text(
            "🚫 **Access Denied**\n\nYou are not authorized to use this bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not context.args:
        context.user_data["waiting_for"] = "scrapeall"
        await update.message.reply_text(
            "🌐 **Send me the URL to start crawling:**\n\n"
            "The bot will scrape all pages on the same domain.\n"
            "Example: `https://example.com`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = " ".join(context.args)
    await do_scrapeall(update, context, url)


# ─────────────────── BUTTON CALLBACK HANDLER ───────────────────


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "action_scrape":
        if not is_allowed(user_id):
            await query.edit_message_text(
                "🚫 **Access Denied**\n\nYou are not authorized to use this bot.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        context.user_data["waiting_for"] = "scrape"
        await query.edit_message_text(
            "🔍 **SCRAPE SINGLE PAGE**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Please send me the URL you want to scrape.\n\n"
            "Example: `https://example.com`",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "action_scrapeall":
        if not is_allowed(user_id):
            await query.edit_message_text(
                "🚫 **Access Denied**\n\nYou are not authorized to use this bot.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        context.user_data["waiting_for"] = "scrapeall"
        await query.edit_message_text(
            "🌐 **SCRAPE ALL PAGES**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Please send me the starting URL.\n"
            "The bot will crawl all linked pages on the same domain.\n\n"
            "Example: `https://example.com`",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "action_help":
        help_text = (
            "📖 **HOW TO USE THIS BOT**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**🔍 Scrape Single Page:**\n"
            "• Click `🔍 Scrape URL` button\n"
            "• Or use `/scrape <url>`\n"
            "• Bot fetches and sends source code\n\n"
            "**🌐 Scrape All Pages:**\n"
            "• Click `🌐 Scrape All` button\n"
            "• Or use `/scrapeall <url>`\n"
            "• Bot crawls all pages on domain\n\n"
            "**⚠️ Notes:**\n"
            "• Large files auto-split\n"
            "• Max 100 pages per crawl\n"
            "• Some sites may block scraping"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔙 Back", callback_data="action_back"),
                ]
            ]
        )
        await query.edit_message_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )

    elif data == "action_status":
        bot_data = load_data()
        stats = bot_data.get("stats", {})
        total_users = len(stats.get("total_users", []))
        total_scrapes = stats.get("total_scrapes", 0)

        status_text = (
            "📊 **BOT STATUS**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ Bot is running\n"
            f"👥 Total Users: {total_users}\n"
            f"🕷️ Total Scrapes: {total_scrapes}\n"
            f"📋 Log Channel: {'Set ✅' if bot_data.get('log_channel') else 'Not set ❌'}\n"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔙 Back", callback_data="action_back")]
            ]
        )
        await query.edit_message_text(
            status_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )

    elif data == "action_back":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔍 Scrape URL", callback_data="action_scrape"),
                    InlineKeyboardButton("🌐 Scrape All", callback_data="action_scrapeall"),
                ],
                [
                    InlineKeyboardButton("❓ Help", callback_data="action_help"),
                    InlineKeyboardButton("📊 Status", callback_data="action_status"),
                ],
                [
                    InlineKeyboardButton(
                        "📩 Contact Developer", url="https://t.me/TALK_WITH_STEALED"
                    )
                ],
            ]
        )
        await query.edit_message_text(
            WELCOME_TEXT,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )


# ─────────────────── MESSAGE HANDLER ───────────────────


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages - mainly URLs."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Check access
    if not is_allowed(user_id):
        await update.message.reply_text(
            "🚫 **Access Denied**\n\nYou are not authorized to use this bot.\n"
            "Contact admin for access.",
            parse_mode=ParseMode.MARKDOWN,
        )
        await log_to_channel(
            context,
            f"🚫 Unauthorized attempt by `{user_id}`\nMessage: {text[:100]}",
        )
        return

    # Check if we're waiting for a URL
    waiting_for = context.user_data.get("waiting_for")

    # Check if the text looks like a URL
    is_url = text.startswith(("http://", "https://", "www.")) or (
        "." in text and " " not in text and not text.startswith("/")
    )

    if waiting_for in ("scrape", "scrapeall"):
        context.user_data.pop("waiting_for", None)

        if waiting_for == "scrape":
            await do_scrape(update, context, text)
        else:
            await do_scrapeall(update, context, text)

    elif is_url:
        # Auto-detect URL and offer options
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔍 Scrape Single", callback_data=f"url_scrape|{text}"),
                    InlineKeyboardButton("🌐 Scrape All", callback_data=f"url_scrapeall|{text}"),
                ]
            ]
        )
        await update.message.reply_text(
            f"🔗 **URL Detected:** `{text}`\n\nWhat would you like to do?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text(
            "❓ I didn't understand that.\n\n"
            "Use the buttons below or send a URL to get started!",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_url_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle URL-specific callbacks (from auto-detected URLs)."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not is_allowed(user_id):
        await query.edit_message_text("🚫 Access Denied.", parse_mode=ParseMode.MARKDOWN)
        return

    data = query.data
    if "|" in data:
        action, url = data.split("|", 1)
    else:
        return

    # Delete the question message
    await query.message.delete()

    if action == "url_scrape":
        await do_scrape(update, context, url)
    elif action == "url_scrapeall":
        await do_scrapeall(update, context, url)


# ─────────────────── CORE SCRAPE FUNCTIONS ───────────────────


async def do_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    """Execute single page scrape."""
    url = normalize_url(url)

    if not validate_url(url):
        await update.message.reply_text(
            "❌ **Invalid URL**\n\nPlease send a valid URL.\n"
            "Example: `https://example.com`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Send loading message
    loading_msg = await update.message.reply_text(
        "⏳ **Scraping in progress...**\n\n"
        f"🌐 URL: `{url}`\n"
        "🔄 Please wait...",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Send chat action
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        # Run scrape in executor to not block
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: scrape_single_page(url))

        # Delete loading message
        try:
            await loading_msg.delete()
        except Exception:
            pass

        if not result["success"]:
            await update.message.reply_text(
                f"❌ **Scraping Failed**\n\n"
                f"🌐 URL: `{url}`\n"
                f"⚠️ Error: {result['error']}\n\n"
                "The website might be down, blocking bots, or the URL might be incorrect.",
                parse_mode=ParseMode.MARKDOWN,
            )
            await log_to_channel(
                context,
                f"❌ Scrape failed\n• URL: `{url}`\n• User: `{update.effective_user.id}`\n• Error: {result['error']}",
            )
            return

        # Success
        source_code = result["source_code"]
        domain = get_domain(url)
        safe_domain = re.sub(r"[^\w\-.]", "_", domain)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_domain}_{timestamp}"

        is_html = "html" in result.get("content_type", "")
        size_kb = len(source_code.encode("utf-8")) / 1024

        caption = (
            f"✅ **Source Code Scraped!**\n\n"
            f"🌐 URL: `{url}`\n"
            f"📄 Title: {result['title']}\n"
            f"📊 Status: {result['status_code']}\n"
            f"📦 Size: {size_kb:.1f} KB\n"
            f"🏷️ Type: {result['content_type']}"
        )

        await send_source_file(update, context, source_code, filename, caption, is_html)

        # Update stats
        data = load_data()
        data["stats"]["total_scrapes"] = data["stats"].get("total_scrapes", 0) + 1
        save_data(data)

        # Log to channel
        await log_to_channel(
            context,
            f"✅ Single page scraped\n"
            f"• URL: `{url}`\n"
            f"• User: `{update.effective_user.id}` (@{update.effective_user.username or 'N/A'})\n"
            f"• Size: {size_kb:.1f} KB",
        )

    except Exception as e:
        try:
            await loading_msg.delete()
        except Exception:
            pass
        logger.error(f"Scrape error: {e}")
        await update.message.reply_text(
            f"❌ **An unexpected error occurred**\n\n`{str(e)[:200]}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def do_scrapeall(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    """Execute full site scrape."""
    url = normalize_url(url)

    if not validate_url(url):
        await update.message.reply_text(
            "❌ **Invalid URL**\n\nPlease send a valid URL.\n"
            "Example: `https://example.com`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Confirmation message
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes, Start!", callback_data=f"confirm_scrapeall|{url}"
                ),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_scrapeall"),
            ]
        ]
    )
    await update.message.reply_text(
        f"🌐 **SCRAPE ALL PAGES**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Starting URL: `{url}`\n"
        f"Domain: `{get_domain(url)}`\n\n"
        f"⚠️ This will crawl all linked pages on the same domain.\n"
        f"📌 Maximum {MAX_PAGES} pages will be scraped.\n\n"
        f"Are you sure you want to proceed?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def confirm_scrapeall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle scrapeall confirmation."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if "|" in data:
        _, url = data.split("|", 1)
    else:
        await query.edit_message_text("❌ Invalid request.")
        return

    chat_id = query.message.chat_id

    await query.edit_message_text(
        f"⏳ **Starting full site scrape...**\n\n🌐 `{url}`\n\n🔄 Please wait, this may take a while...",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        # Run the async scrape
        result = await scrape_all_pages_async(url, context, chat_id)

        if result["total_pages"] == 0:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"❌ **No pages could be scraped**\n\n"
                    f"🌐 URL: `{url}`\n"
                    f"The site might be blocking our requests."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Send all files using bot directly
        await send_scrapeall_files(chat_id, context.bot, context, result)

        # Update stats
        bot_data = load_data()
        bot_data["stats"]["total_scrapes"] = bot_data["stats"].get("total_scrapes", 0) + result["total_pages"]
        save_data(bot_data)

        # Log
        await log_to_channel(
            context,
            f"🌐 Full site scraped\n"
            f"• URL: `{url}`\n"
            f"• Pages: {result['total_pages']}\n"
            f"• User: `{query.from_user.id}` (@{query.from_user.username or 'N/A'})",
        )

    except Exception as e:
        logger.error(f"Scrapeall error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ **Error during scraping**\n\n`{str(e)[:200]}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def cancel_scrapeall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel scrapeall."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ Scrape cancelled.\n\nSend a new URL or use the commands to get started.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────── ADMIN COMMANDS ───────────────────


async def admin_setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the log channel (admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return

    if not context.args:
        await update.message.reply_text(
            "📋 **Set Log Channel**\n\nUsage: `/setchannel <channel_id>`\n\n"
            "Example: `/setchannel -1001234567890`\n\n"
            "💡 Forward a message from the channel to @userinfobot to get the channel ID.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        channel_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID. Must be a number.")
        return

    data = load_data()
    data["log_channel"] = channel_id
    save_data(data)

    await update.message.reply_text(
        f"✅ **Log channel set to:** `{channel_id}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Test by sending a message to the channel
    try:
        await context.bot.send_message(
            chat_id=channel_id,
            text="✅ **Log Channel Connected!**\n\nBot logs will be sent here.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Channel saved but test message failed:\n`{str(e)[:200]}`\n\n"
            "Make sure the bot is added to the channel as admin.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def admin_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a user to allowed list (admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return

    if not context.args:
        await update.message.reply_text(
            "👤 **Add User**\n\nUsage: `/adduser <user_id>`\n\n"
            "Example: `/adduser 123456789`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    data = load_data()
    if user_id not in data["allowed_users"]:
        data["allowed_users"].append(user_id)
        save_data(data)
        await update.message.reply_text(
            f"✅ User `{user_id}` has been added to the allowed list.",
            parse_mode=ParseMode.MARKDOWN,
        )
        await log_to_channel(context, f"👤 User `{user_id}` added to allowed list by admin.")
    else:
        await update.message.reply_text(
            f"ℹ️ User `{user_id}` is already in the allowed list.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def admin_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a user from allowed list (admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return

    if not context.args:
        await update.message.reply_text(
            "👤 **Remove User**\n\nUsage: `/removeuser <user_id>`\n\n"
            "Example: `/removeuser 123456789`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    data = load_data()
    if user_id in data["allowed_users"]:
        data["allowed_users"].remove(user_id)
        save_data(data)
        await update.message.reply_text(
            f"✅ User `{user_id}` has been removed from the allowed list.",
            parse_mode=ParseMode.MARKDOWN,
        )
        await log_to_channel(context, f"👤 User `{user_id}` removed from allowed list by admin.")
    else:
        await update.message.reply_text(
            f"ℹ️ User `{user_id}` is not in the allowed list.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def admin_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all allowed users (admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return

    data = load_data()
    users = data.get("allowed_users", [])

    if not users:
        await update.message.reply_text(
            "📋 **Allowed Users List**\n\nNo users added yet. Use `/adduser <id>` to add users.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    user_list = "📋 **Allowed Users**\n\n"
    for uid in users:
        user_list += f"• `{uid}`\n"

    user_list += f"\n**Total:** {len(users)} users"

    await update.message.reply_text(user_list, parse_mode=ParseMode.MARKDOWN)


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Broadcast message to all users (admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Admin only command.")
        return

    if not context.args:
        await update.message.reply_text(
            "📢 **Broadcast**\n\nUsage: `/broadcast <message>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    message = " ".join(context.args)
    data = load_data()
    users = data.get("stats", {}).get("total_users", [])

    sent = 0
    failed = 0
    for uid in users:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 **Broadcast Message**\n\n{message}",
                parse_mode=ParseMode.MARKDOWN,
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Rate limiting

    await update.message.reply_text(
        f"📢 **Broadcast Complete**\n\n✅ Sent: {sent}\n❌ Failed: {failed}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────── ERROR HANDLER ───────────────────


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors globally."""
    logger.error(f"Exception while handling an update: {context.error}")

    if update and isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text(
                "❌ **An error occurred**\n\nSomething went wrong. Please try again later.\n\n"
                "If the problem persists, contact @TALK_WITH_STEALED",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    # Log error to channel
    if context.error:
        await log_to_channel(
            context,
            f"❌ **Bot Error**\n\n`{str(context.error)[:500]}`",
        )


# ─────────────────── MAIN FUNCTION ───────────────────


def main() -> None:
    """Start the bot."""
    print("=" * 50)
    print("  🕷️ SOURCE CODE SCRAPER BOT")
    print("  Developed by: @TALK_WITH_STEALED")
    print("=" * 50)

    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌ ERROR: BOT_TOKEN not set!")
        print("Set it via environment variable or edit the code.")
        print("\nExample: BOT_TOKEN=your_token ADMIN_ID=123 python bot.py")
        return

    # Build application
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("scrape", scrape_command))
    application.add_handler(CommandHandler("scrapeall", scrapeall_command))

    # Admin commands
    application.add_handler(CommandHandler("setchannel", admin_setchannel))
    application.add_handler(CommandHandler("adduser", admin_adduser))
    application.add_handler(CommandHandler("removeuser", admin_removeuser))
    application.add_handler(CommandHandler("listusers", admin_listusers))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))

    # Callback query handlers
    application.add_handler(
        CallbackQueryHandler(button_callback, pattern=r"^action_")
    )
    application.add_handler(
        CallbackQueryHandler(handle_url_callback, pattern=r"^url_")
    )
    application.add_handler(
        CallbackQueryHandler(confirm_scrapeall, pattern=r"^confirm_scrapeall")
    )
    application.add_handler(
        CallbackQueryHandler(cancel_scrapeall, pattern=r"^cancel_scrapeall")
    )

    # Message handler (for URLs and general text)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Error handler
    application.add_error_handler(error_handler)

    # Start polling
    print("\n✅ Bot is running! Press Ctrl+C to stop.\n")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


async def post_init(application: Application) -> None:
    """Post initialization - set bot commands."""
    commands = [
        BotCommand("start", "🚀 Start the bot"),
        BotCommand("scrape", "🔍 Scrape single page URL"),
        BotCommand("scrapeall", "🌐 Scrape all pages"),
        BotCommand("help", "❓ How to use the bot"),
    ]
    await application.bot.set_my_commands(commands)
    print("✅ Bot commands registered.")


if __name__ == "__main__":
    main()
