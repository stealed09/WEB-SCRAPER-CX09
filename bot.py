#!/usr/bin/env python3
# ============================================================
#   🤖 Telegram Web Scraper Bot
#   Developer: @TALK_WITH_STEALED
#   Version: 2.0.0  |  python-telegram-bot v20+
# ============================================================

import os, json, asyncio, logging, zipfile, io, re, time
import hashlib, urllib.parse
from datetime import datetime
from pathlib import Path
from collections import deque
from typing import Optional, List, Dict, Set

import requests
from bs4 import BeautifulSoup
import validators
from dotenv import load_dotenv

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from telegram.constants import ParseMode, ChatAction
from telegram.error import TelegramError

# ─── Load Environment ────────────────────────────────────────
load_dotenv()

BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
ADMIN_ID       = int(os.getenv("ADMIN_ID", 0))
MAX_FILES_ZIP  = int(os.getenv("MAX_FILES_PER_ZIP", 599))
MAX_DEPTH      = int(os.getenv("MAX_DEPTH", 3))
REQ_TIMEOUT    = int(os.getenv("REQUEST_TIMEOUT", 30))
MAX_PAGES      = int(os.getenv("MAX_PAGES", 200))

# ─── Paths & Logging ─────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
CFG_FILE   = DATA_DIR / "config.json"
LOG_DIR    = DATA_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ScraperBot")

# ─── Conversation States ──────────────────────────────────────
WAITING_URL, WAITING_FORMAT, ADMIN_MENU = range(3)

# ─── Progress Bar Builder ─────────────────────────────────────
def make_progress(current: int, total: int, width: int = 20) -> str:
    pct = (current / total) if total > 0 else 0
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct*100:.1f}% ({current}/{total})"


# ─── Data Management ─────────────────────────────────────────
def load_users() -> Dict:
    if USERS_FILE.exists():
        with open(USERS_FILE) as f:
            return json.load(f)
    return {"approved": [], "banned": [], "pending": []}

def save_users(data: Dict):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_config() -> Dict:
    if CFG_FILE.exists():
        with open(CFG_FILE) as f:
            return json.load(f)
    return {"log_channel": None, "max_depth": MAX_DEPTH, "max_pages": MAX_PAGES}

def save_config(data: Dict):
    with open(CFG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_approved(user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    return user_id in load_users()["approved"]

def is_banned(user_id: int) -> bool:
    return user_id in load_users()["banned"]

async def send_log(bot, msg: str):
    cfg = load_config()
    ch = cfg.get("log_channel")
    if not ch: return
    try:
        await bot.send_message(ch, f"📋 LOG\n{msg}", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"Log channel error: {e}")

async def notify_pending(bot, user):
    """Notify admin of new access request"""
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"),
        InlineKeyboardButton("❌ Deny", callback_data=f"deny_{user.id}"),
    ]])
    name = user.full_name
    username = f"@{user.username}" if user.username else "no username"
    await bot.send_message(
        ADMIN_ID,
        f"🔔 New Access Request\n\n"
        f"👤 Name: {name}\n"
        f"🆔 ID: {user.id}\n"
        f"📱 Username: {username}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


# ─── Scraper Engine ──────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

def fetch_page(url: str) -> Dict:
    """Fetch a single page. Returns dict with html, status, error."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQ_TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        return {"url": url, "html": r.text, "status": r.status_code, "error": None}
    except requests.exceptions.Timeout:
        return {"url": url, "html": "", "status": 0, "error": "Timeout"}
    except requests.exceptions.ConnectionError:
        return {"url": url, "html": "", "status": 0, "error": "Connection refused / DNS fail"}
    except requests.exceptions.HTTPError as e:
        return {"url": url, "html": "", "status": e.response.status_code, "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"url": url, "html": "", "status": 0, "error": str(e)[:100]}

def extract_links(html: str, base_url: str, domain: str) -> List[str]:
    """Extract all same-domain links from HTML."""
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        full = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(full)
        if parsed.netloc == domain and parsed.scheme in ("http", "https"):
            clean = parsed._replace(fragment="").geturl()
            links.add(clean)
    return list(links)

def url_to_filename(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/").replace("/", "__") or "index"
    h = hashlib.md5(url.encode()).hexdigest()[:6]
    safe = re.sub(r"[^\w\-.]", "_", path)[:60]
    return f"{safe}_{h}.html"

async def scrape_single(url: str, progress_msg, bot) -> List[Dict]:
    """Scrape one page with progress update."""
    await progress_msg.edit_text(
        f"⚡ Scraping single page...\n\n🔗 URL: {url}\n\n{make_progress(0, 1)}"
    )
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, fetch_page, url)
    await progress_msg.edit_text(
        f"✅ Done!\n\n🔗 {url}\n\n{make_progress(1, 1)}"
    )
    return [result]

async def scrape_all_pages(start_url: str, progress_msg, bot) -> List[Dict]:
    """BFS crawl all pages within same domain."""
    cfg = load_config()
    max_p = cfg.get("max_pages", MAX_PAGES)
    max_d = cfg.get("max_depth", MAX_DEPTH)

    parsed_start = urllib.parse.urlparse(start_url)
    domain = parsed_start.netloc

    visited: Set[str] = set()
    queue   = deque([(start_url, 0)])
    results = []

    while queue and len(results) < max_p:
        url, depth = queue.popleft()
        if url in visited: continue
        visited.add(url)

        idx = len(results) + 1
        try:
            await progress_msg.edit_text(
                f"🕸️ Crawling all pages...\n\n"
                f"📄 Page: {idx} | Depth: {depth}/{max_d}\n"
                f"🔗 {url[:60]}...\n"
                f"📊 Queue: {len(queue)} URLs pending\n\n"
                f"{make_progress(idx, min(max_p, idx + len(queue)))}",
                parse_mode=ParseMode.HTML
            )
        except: pass

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, fetch_page, url)
        results.append(result)

        if result["html"] and depth < max_d:
            links = extract_links(result["html"], url, domain)
            for link in links:
                if link not in visited:
                    queue.append((link, depth + 1))

        await asyncio.sleep(0.3)  # polite delay

    return results



# ─── /start Handler ──────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return

    welcome = (
        "╔══════════════════════════════╗\n"
        "║   🙏 THANKS FOR USING THE BOT   ║\n"
        "╠══════════════════════════════╣\n"
        "║                              ║\n"
        "║   👨‍💻 THIS BOT IS DEVELOPED BY   ║\n"
        "║                              ║\n"
        "║   ⚡ @TALK_WITH_STEALED ⚡     ║\n"
        "║                              ║\n"
        "║   📩 CONTACT HIM FOR YOUR     ║\n"
        "║        CUSTOM BOTS            ║\n"
        "║                              ║\n"
        "╚══════════════════════════════╝\n\n"
        "👋 Hello {name}! Choose an action below:"
    ).format(name=user.first_name)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕷️ Scrape Single Page",  callback_data="do_scrape"),
         InlineKeyboardButton("🌐 Scrape All Pages",     callback_data="do_scrapeall")],
        [InlineKeyboardButton("❓ Help",                  callback_data="do_help"),
         InlineKeyboardButton("📊 My Stats",             callback_data="do_stats")],
        [InlineKeyboardButton("📩 Contact Developer",    url="https://t.me/TALK_WITH_STEALED")],
    ])
    await update.message.reply_text(welcome, parse_mode=ParseMode.HTML, reply_markup=kb)

    if not is_approved(user.id):
        users = load_users()
        if user.id not in users["pending"]:
            users["pending"].append(user.id)
            save_users(users)
            await notify_pending(context.bot, user)

# ─── /help Handler ───────────────────────────────────────────
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "📖 How to use WebScraper Bot\n\n"
        "Method 1 — Buttons (Recommended)\n"
        "  1️⃣ Press /start\n"
        "  2️⃣ Tap 🕷️ Scrape or 🌐 Scrape All\n"
        "  3️⃣ Send your URL directly\n"
        "  4️⃣ Choose ZIP or Single file\n\n"
        "Method 2 — Commands\n"
        "  /scrape https://example.com\n"
        "  /scrapeall https://example.com\n\n"
        "Limits\n"
        "  📄 Max pages: 200\n"
        "  📦 Max files/ZIP: 599\n"
        "  ⏱️ Timeout: 30s per page\n\n"
        "⚠️ Note: Access must be granted by admin."
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Back to Menu", callback_data="back_start")
    ]])
    await (update.message or update.callback_query.message).reply_text(
        txt, parse_mode=ParseMode.HTML, reply_markup=kb
    )

# ─── /scrape & /scrapeall Commands ───────────────────────────
async def cmd_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _start_scrape(update, context, mode="single")

async def cmd_scrapeall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _start_scrape(update, context, mode="all")

async def _start_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    user = update.effective_user
    if not is_approved(user.id):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📩 Request Access", callback_data="req_access")
        ]])
        await update.message.reply_text(
            "🔒 Access Required\n\nYou need admin approval to use this bot.",
            parse_mode=ParseMode.HTML, reply_markup=kb
        )
        return
    args = context.args
    if not args:
        context.user_data["mode"] = mode
        await update.message.reply_text(
            f"{'🕷️ Single page' if mode=='single' else '🌐 All pages'} mode\n\n"
            "📎 Please send the URL now:"
        )
        return WAITING_URL
    url = args[0]
    await process_url(update, context, url, mode)


# ─── Core URL Processor ──────────────────────────────────────
async def process_url(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       url: str, mode: str):
    user = update.effective_user
    msg  = update.message or update.callback_query.message

    # Validate URL
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not validators.url(url):
        await msg.reply_text("❌ Invalid URL!\n\nPlease send a valid URL like:\nhttps://example.com",
                              parse_mode=ParseMode.HTML)
        return

    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pmsg  = await msg.reply_text("⏳ Initializing scraper...\n\n" + make_progress(0, 1))

    await context.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
    await send_log(context.bot,
        f"🕷 Scrape started\n👤 {user.full_name} ({user.id})\n"
        f"🔗 {url}\n📋 Mode: {mode}\n🕐 {ts}"
    )

    try:
        if mode == "single":
            results = await scrape_single(url, pmsg, context.bot)
        else:
            results = await scrape_all_pages(url, pmsg, context.bot)
    except Exception as e:
        await pmsg.edit_text(f"❌ Scraper crashed: {e}")
        await send_log(context.bot, f"❌ CRASH: {e} | User: {user.id}")
        return

    ok  = [r for r in results if r["html"]]
    err = [r for r in results if r["error"]]

    if not ok:
        errmsg = err[0]["error"] if err else "Unknown error"
        await pmsg.edit_text(
            f"❌ Failed to scrape\n\n🔗 {url}\n⚠️ Reason: {errmsg}\n\n"
            "Possible causes:\n• Site is blocked\n• Invalid URL\n• Rate limited",
            parse_mode=ParseMode.HTML
        )
        return

    # Ask user: ZIP or single files?
    context.user_data["results"]  = ok
    context.user_data["scrape_url"] = url
    count = len(ok)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📦 ZIP ({min(count, MAX_FILES_ZIP)} files)", callback_data="fmt_zip"),
         InlineKeyboardButton(f"📄 Single .txt",                              callback_data="fmt_txt")],
        [InlineKeyboardButton(f"🌐 Single .html (merged)",                     callback_data="fmt_html")],
        [InlineKeyboardButton("❌ Cancel",                                      callback_data="fmt_cancel")],
    ])
    await pmsg.edit_text(
        f"✅ Scraping complete!\n\n"
        f"📄 Pages scraped: {count}\n"
        f"❌ Failed: {len(err)}\n\n"
        "📥 How do you want the files?",
        parse_mode=ParseMode.HTML, reply_markup=kb
    )

# ─── File Delivery ────────────────────────────────────────────
async def deliver_files(query, context: ContextTypes.DEFAULT_TYPE, fmt: str):
    results = context.user_data.get("results", [])
    url     = context.user_data.get("scrape_url", "unknown")
    user    = query.from_user

    if not results:
        await query.message.reply_text("❌ No data found. Please scrape again.")
        return

    pmsg = await query.message.reply_text("📦 Preparing files...")

    if fmt == "zip":
        slices = [results[i:i+MAX_FILES_ZIP] for i in range(0, len(results), MAX_FILES_ZIP)]
        for si, chunk in enumerate(slices, 1):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, r in enumerate(chunk, 1):
                    fname = url_to_filename(r["url"])
                    await pmsg.edit_text(f"📦 Building ZIP {si}...\n{make_progress(i, len(chunk))}")
                    zf.writestr(fname, r["html"])
                    await asyncio.sleep(0.05)
                # Add index
                idx_content = "\n".join(
                    f"{i}. {r['url']}" for i, r in enumerate(chunk, 1)
                )
                zf.writestr("_index.txt", idx_content)
            buf.seek(0)
            if buf.getbuffer().nbytes > 50 * 1024 * 1024:
                await pmsg.edit_text("⚠️ ZIP too large for Telegram (>50MB). Splitting...")
                continue
            zname = f"scraped_part{si}.zip"
            await query.message.reply_document(buf, filename=zname,
                caption=f"📦 Part {si}/{len(slices)} — {len(chunk)} pages")
    elif fmt == "txt":
        combined = ""
        for r in results:
            combined += f"{'='*60}\nURL: {r['url']}\n{'='*60}\n{r['html']}\n\n"
        buf = io.BytesIO(combined.encode("utf-8", errors="replace"))
        buf.name = "scraped.txt"
        await query.message.reply_document(buf, filename="scraped.txt",
            caption=f"📄 {len(results)} pages combined")
    elif fmt == "html":
        parts = []
        for r in results:
            parts.append(f'
'
                         f'
{r["url"]}
{r["html"]}
')
        html_out = f'{"".join(parts)}
'
        buf = io.BytesIO(html_out.encode("utf-8", errors="replace"))
        await query.message.reply_document(buf, filename="scraped.html",
            caption=f"🌐 {len(results)} pages merged HTML")

    await pmsg.delete()
    await send_log(context.bot,
        f"📤 Files delivered | 👤 {user.full_name} ({user.id}) | "  
        f"Format: {fmt} | Pages: {len(results)} | URL: {url}"
                  )


# ─── Admin Panel ──────────────────────────────────────────────
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Admin only command.")
        return
    await show_admin_panel(update.message, context)

async def show_admin_panel(msg, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    cfg   = load_config()
    log_ch = cfg.get("log_channel") or "Not set"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 View Users",        callback_data="adm_users"),
         InlineKeyboardButton("⏳ Pending",           callback_data="adm_pending")],
        [InlineKeyboardButton("➕ Add User",          callback_data="adm_adduser"),
         InlineKeyboardButton("🚫 Ban User",          callback_data="adm_ban")],
        [InlineKeyboardButton("📋 Set Log Channel",   callback_data="adm_setlog"),
         InlineKeyboardButton("⚙️ Settings",          callback_data="adm_settings")],
        [InlineKeyboardButton("📊 Stats",             callback_data="adm_stats"),
         InlineKeyboardButton("📢 Broadcast",         callback_data="adm_broadcast")],
        [InlineKeyboardButton("🏠 Back to Menu",      callback_data="back_start")],
    ])
    await msg.reply_text(
        f"🛡️ Admin Panel\n\n"
        f"👥 Approved users: {len(users['approved'])}\n"
        f"⏳ Pending: {len(users['pending'])}\n"
        f"🚫 Banned: {len(users['banned'])}\n"
        f"📋 Log channel: {log_ch}\n"
        f"🕸️ Max depth: {cfg.get('max_depth', MAX_DEPTH)}\n"
        f"📄 Max pages: {cfg.get('max_pages', MAX_PAGES)}",
        parse_mode=ParseMode.HTML, reply_markup=kb
    )

# ─── Callback Query Router ────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    user = q.from_user
    await q.answer()

    # ── Format selection ─
    if   data == "fmt_zip":    await deliver_files(q, context, "zip")
    elif data == "fmt_txt":    await deliver_files(q, context, "txt")
    elif data == "fmt_html":   await deliver_files(q, context, "html")
    elif data == "fmt_cancel": await q.message.edit_text("❌ Cancelled.")

    # ── Scrape buttons ──
    elif data == "do_scrape":
        if not is_approved(user.id): await q.message.reply_text("🔒 Access required. Use /start to request."); return
        context.user_data["mode"] = "single"
        await q.message.reply_text("🕷️ Single Page Mode\n\n📎 Send the URL now:", parse_mode=ParseMode.HTML)
    elif data == "do_scrapeall":
        if not is_approved(user.id): await q.message.reply_text("🔒 Access required."); return
        context.user_data["mode"] = "all"
        await q.message.reply_text("🌐 Multi-Page Mode\n\n📎 Send the starting URL now:", parse_mode=ParseMode.HTML)
    elif data == "do_help":    await cmd_help(update, context)
    elif data == "back_start": await cmd_start(update, context)

    # ── Access request ──
    elif data == "req_access":
        users = load_users()
        if user.id not in users["pending"]:
            users["pending"].append(user.id)
            save_users(users)
            await notify_pending(context.bot, user)
        await q.message.reply_text("📩 Request sent! Admin will review soon.")

    # ── Admin approve/deny ──
    elif data.startswith("approve_"):
        uid = int(data.split("_")[1])
        users = load_users()
        if uid not in users["approved"]: users["approved"].append(uid)
        if uid in users["pending"]: users["pending"].remove(uid)
        save_users(users)
        await q.message.edit_text(f"✅ User {uid} approved!")
        try: await context.bot.send_message(uid, "✅ Your access has been approved! Use /start to begin.")
        except: pass
    elif data.startswith("deny_"):
        uid = int(data.split("_")[1])
        users = load_users()
        if uid in users["pending"]: users["pending"].remove(uid)
        save_users(users)
        await q.message.edit_text(f"❌ User {uid} denied.")

    # ── Admin panel callbacks ──
    elif data == "adm_users":
        await adm_view_users(q, context)
    elif data == "adm_pending":
        await adm_view_pending(q, context)
    elif data == "adm_setlog":
        context.user_data["adm_state"] = "setlog"
        await q.message.reply_text(
            "📋 Set Log Channel\n\n"
            "1. Add this bot to your private channel as Admin\n"
            "2. Forward any message from the channel here\n"
            "   OR send the channel ID (e.g. -100XXXXXXXXXX)",
            parse_mode=ParseMode.HTML
        )
    elif data == "adm_stats":
        await adm_stats(q, context)
    elif data == "adm_settings":
        await adm_settings_menu(q, context)
    elif data.startswith("setdepth_"):
        val = int(data.split("_")[1])
        cfg = load_config(); cfg["max_depth"] = val; save_config(cfg)
        await q.message.edit_text(f"✅ Max depth set to {val}")
    elif data.startswith("setpages_"):
        val = int(data.split("_")[1])
        cfg = load_config(); cfg["max_pages"] = val; save_config(cfg)
        await q.message.edit_text(f"✅ Max pages set to {val}")
    elif data.startswith("revoke_"):
        uid = int(data.split("_")[1])
        users = load_users()
        if uid in users["approved"]: users["approved"].remove(uid)
        save_users(users)
        await q.message.edit_text(f"🔒 Access revoked for {uid}")
    elif data.startswith("ban_"):
        uid = int(data.split("_")[1])
        users = load_users()
        if uid not in users["banned"]: users["banned"].append(uid)
        if uid in users["approved"]: users["approved"].remove(uid)
        save_users(users)
        await q.message.edit_text(f"🚫 User {uid} banned.")


# ─── Admin Sub-menu Functions ─────────────────────────────────
async def adm_view_users(q, context):
    users = load_users()
    approved = users["approved"]
    if not approved:
        await q.message.reply_text("👥 No approved users yet."); return
    btns = []
    for uid in approved[:20]:
        btns.append([
            InlineKeyboardButton(f"🆔 {uid}", callback_data=f"noop"),
            InlineKeyboardButton("🔒 Revoke", callback_data=f"revoke_{uid}"),
            InlineKeyboardButton("🚫 Ban",    callback_data=f"ban_{uid}"),
        ])
    btns.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="back_admin")])
    await q.message.reply_text(
        f"👥 Approved Users ({len(approved)})",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(btns)
    )

async def adm_view_pending(q, context):
    users = load_users()
    pending = users["pending"]
    if not pending:
        await q.message.reply_text("⏳ No pending requests."); return
    btns = []
    for uid in pending[:20]:
        btns.append([
            InlineKeyboardButton(f"🆔 {uid}",   callback_data="noop"),
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{uid}"),
            InlineKeyboardButton("❌ Deny",    callback_data=f"deny_{uid}"),
        ])
    btns.append([InlineKeyboardButton("🔙 Admin Panel", callback_data="back_admin")])
    await q.message.reply_text(
        f"⏳ Pending Requests ({len(pending)})",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(btns)
    )

async def adm_stats(q, context):
    users = load_users()
    cfg   = load_config()
    await q.message.reply_text(
        f"📊 Bot Statistics\n\n"
        f"👥 Approved: {len(users['approved'])}\n"
        f"⏳ Pending: {len(users['pending'])}\n"
        f"🚫 Banned: {len(users['banned'])}\n"
        f"📋 Log channel: {cfg.get('log_channel','Not set')}\n"
        f"🕸️ Max crawl depth: {cfg.get('max_depth', MAX_DEPTH)}\n"
        f"📄 Max pages/session: {cfg.get('max_pages', MAX_PAGES)}\n"
        f"📦 Max files/ZIP: {MAX_FILES_ZIP}",
        parse_mode=ParseMode.HTML
    )

async def adm_settings_menu(q, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Depth: 1",callback_data="setdepth_1"),
         InlineKeyboardButton("Depth: 2",callback_data="setdepth_2"),
         InlineKeyboardButton("Depth: 3",callback_data="setdepth_3"),
         InlineKeyboardButton("Depth: 5",callback_data="setdepth_5")],
        [InlineKeyboardButton("Pages: 50", callback_data="setpages_50"),
         InlineKeyboardButton("Pages: 100",callback_data="setpages_100"),
         InlineKeyboardButton("Pages: 200",callback_data="setpages_200")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_admin")]
    ])
    await q.message.reply_text("⚙️ Settings\n\nAdjust crawl depth and max pages:",
                                parse_mode=ParseMode.HTML, reply_markup=kb)

# ─── Generic Message Handler ──────────────────────────────────
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    # Admin: setting log channel via message
    if user.id == ADMIN_ID and context.user_data.get("adm_state") == "setlog":
        ch_id = None
        if update.message.forward_from_chat:
            ch_id = update.message.forward_from_chat.id
        elif text.lstrip("-").isdigit():
            ch_id = int(text)
        if ch_id:
            cfg = load_config(); cfg["log_channel"] = ch_id; save_config(cfg)
            context.user_data["adm_state"] = None
            await update.message.reply_text(f"✅ Log channel set to: {ch_id}", parse_mode=ParseMode.HTML)
            await send_log(context.bot, f"✅ Log channel configured: {ch_id}")
        else:
            await update.message.reply_text("❌ Could not detect channel. Forward a message or send channel ID.")
        return

    # Admin: adding user by ID
    if user.id == ADMIN_ID and context.user_data.get("adm_state") == "adduser":
        if text.isdigit():
            uid = int(text)
            users = load_users()
            if uid not in users["approved"]: users["approved"].append(uid)
            save_users(users)
            context.user_data["adm_state"] = None
            await update.message.reply_text(f"✅ User {uid} added.", parse_mode=ParseMode.HTML)
        return

    # User awaiting URL input
    mode = context.user_data.get("mode")
    if mode and (text.startswith("http") or "." in text):
        context.user_data["mode"] = None
        await process_url(update, context, text, mode)
    else:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🕷️ Scrape Single", callback_data="do_scrape"),
            InlineKeyboardButton("🌐 Scrape All",    callback_data="do_scrapeall"),
        ]])
        await update.message.reply_text(
            "💡 Use the buttons below or /start to begin:", reply_markup=kb
        )


# ─── Main Entry Point ─────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set in .env!")
        return
    if not ADMIN_ID:
        logger.error("❌ ADMIN_ID not set in .env!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # ── Register Handlers ──
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("scrape",    cmd_scrape))
    app.add_handler(CommandHandler("scrapeall", cmd_scrapeall))
    app.add_handler(CommandHandler("admin",     cmd_admin))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        message_handler
    ))

    # ── Set Bot Commands ──
    async def post_init(app):
        await app.bot.set_my_commands([
            BotCommand("start",     "Welcome message & menu"),
            BotCommand("scrape",    "Scrape single page"),
            BotCommand("scrapeall", "Scrape all pages"),
            BotCommand("help",      "How to use the bot"),
            BotCommand("admin",     "Admin panel (admin only)"),
        ])

    app.post_init = post_init

    logger.info("🤖 Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
  
