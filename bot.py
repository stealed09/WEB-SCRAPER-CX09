"""
╔══════════════════════════════════════════════╗
║  Website Source Code Scraper Telegram Bot      ║
║  Full Asset Support: Images/CSS/JS/Fonts       ║
║  Anti-Block: 6 Fetch Strategies               ║
║  Developed by @TALK_WITH_STEALED               ║
╚══════════════════════════════════════════════╝
"""

import io
import logging
import html as html_module
import time

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

from config import BOT_TOKEN, ADMIN_IDS, DEVELOPER_LINK, MAX_PAGES
from database import db
from utils import (
    get_welcome_message, get_help_message, validate_url,
    make_progress_bar, format_size, format_timestamp
)
from scraper import WebScraper, create_single_file, create_zip_file
from admin import (
    is_admin, admin_panel, handle_admin_callback,
    process_admin_input, handle_remove_unban_callback
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

scraper = WebScraper()


# ═══════════════════════════════════════════════════════
#  KEYBOARDS
# ═══════════════════════════════════════════════════════

def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(
                "🔍 Scrape Single Page",
                callback_data="scrape_single"
            ),
            InlineKeyboardButton(
                "🌐 Scrape All Pages",
                callback_data="scrape_all"
            ),
        ],
        [
            InlineKeyboardButton("📖 Help", callback_data="help"),
        ],
        [
            InlineKeyboardButton(
                "📩 Contact Developer", url=DEVELOPER_LINK
            ),
        ],
    ]
    if is_admin(user_id):
        keyboard.insert(2, [
            InlineKeyboardButton(
                "🛡️ Admin Panel",
                callback_data="admin_panel"
            )
        ])
    return InlineKeyboardMarkup(keyboard)


def get_asset_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📄 HTML Only (Source Code)",
                callback_data="assets_no"
            ),
        ],
        [
            InlineKeyboardButton(
                "📦 HTML + All Assets (Images/CSS/JS/Fonts/Videos)",
                callback_data="assets_yes"
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel", callback_data="main_menu"
            ),
        ],
    ])


def get_format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📄 Single File (.html)",
                callback_data="format_single"
            ),
            InlineKeyboardButton(
                "📦 ZIP Archive (.zip)",
                callback_data="format_zip"
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel", callback_data="main_menu"
            ),
        ],
    ])


def get_format_zip_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📦 Download as ZIP (with all assets)",
                callback_data="format_zip"
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel", callback_data="main_menu"
            ),
        ],
    ])


# ═══════════════════════════════════════════════════════
#  ACCESS CONTROL
# ═══════════════════════════════════════════════════════

def check_access(user_id: int) -> tuple[bool, str]:
    if is_admin(user_id):
        return True, ""
    if db.is_banned(user_id):
        return False, "🚫 You have been banned from using this bot."
    if not db.is_authorized(user_id):
        return False, (
            "⛔ <b>Access Denied</b>\n\n"
            "You are not authorized to use this bot.\n"
            "Contact an admin to get access.\n\n"
            f"📩 Developer: {DEVELOPER_LINK}"
        )
    return True, ""


# ═══════════════════════════════════════════════════════
#  LOG SENDER
# ═══════════════════════════════════════════════════════

async def send_log(
    context: ContextTypes.DEFAULT_TYPE,
    user, action: str, url: str = "",
    pages: int = 0, assets: int = 0,
    status: str = "success", details: str = ""
):
    username = user.username or "N/A"
    first_name = user.first_name or "N/A"
    user_id = user.id

    db.add_log(
        user_id, username, action, url,
        pages, assets, status, details
    )

    channel_id = db.get_setting("log_channel_id")
    if not channel_id:
        return

    try:
        icon = "✅" if status == "success" else "❌"
        log_text = (
            f"📋 <b>Bot Log</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{icon} <b>Action:</b> {action}\n"
            f"👤 <b>User:</b> {first_name} (@{username})\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        )
        if url:
            log_text += (
                f"🔗 <b>URL:</b> "
                f"{html_module.escape(url[:200])}\n"
            )
        if pages:
            log_text += f"📄 <b>Pages:</b> {pages}\n"
        if assets:
            log_text += f"📦 <b>Assets:</b> {assets}\n"
        if details:
            log_text += f"📝 <b>Details:</b> {details[:300]}\n"
        log_text += (
            f"🕐 <b>Time:</b> {format_timestamp(time.time())}"
        )

        await context.bot.send_message(
            int(channel_id), log_text, parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Log channel error: {e}")


# ═══════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════

async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    context.user_data.clear()

    await update.message.reply_text(
        get_welcome_message(),
        reply_markup=get_main_keyboard(user.id),
        parse_mode=None
    )
    await send_log(context, user, "start")


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🔙 Main Menu", callback_data="main_menu"
        )
    ]])
    await update.message.reply_text(
        get_help_message(), reply_markup=kb, parse_mode="HTML"
    )


async def scrape_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    ok, msg = check_access(user.id)
    if not ok:
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /scrape <url>\n"
            "Example: /scrape https://example.com"
        )
        return

    valid, result = validate_url(context.args[0])
    if not valid:
        await update.message.reply_text(result)
        return

    context.user_data["scrape_url"] = result
    context.user_data["scrape_mode"] = "single"

    await update.message.reply_text(
        f"🔗 URL: <code>{html_module.escape(result)}</code>\n\n"
        f"🖼 Include all assets?",
        reply_markup=get_asset_choice_keyboard(),
        parse_mode="HTML"
    )


async def scrapeall_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    ok, msg = check_access(user.id)
    if not ok:
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Usage: /scrapeall <url>\n"
            "Example: /scrapeall https://example.com"
        )
        return

    valid, result = validate_url(context.args[0])
    if not valid:
        await update.message.reply_text(result)
        return

    context.user_data["scrape_url"] = result
    context.user_data["scrape_mode"] = "all"

    await update.message.reply_text(
        f"🔗 URL: <code>{html_module.escape(result)}</code>\n\n"
        f"🌐 Will scrape up to <b>{MAX_PAGES}</b> pages\n\n"
        f"🖼 Include all assets?",
        reply_markup=get_asset_choice_keyboard(),
        parse_mode="HTML"
    )


async def admin_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    await admin_panel(update, context)


# ═══════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ═══════════════════════════════════════════════════════

async def button_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    data = query.data
    user = query.from_user

    # ── Main Menu ──────────────────────────────────────
    if data == "main_menu":
        await query.answer()
        context.user_data.clear()
        await query.edit_message_text(
            get_welcome_message(),
            reply_markup=get_main_keyboard(user.id)
        )
        return

    # ── Help ───────────────────────────────────────────
    if data == "help":
        await query.answer()
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "🔙 Main Menu", callback_data="main_menu"
            )
        ]])
        await query.edit_message_text(
            get_help_message(),
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    # ── Admin ──────────────────────────────────────────
    if data == "admin_panel" or data.startswith("admin_"):
        await handle_admin_callback(update, context)
        return

    if (data.startswith("remove_user_") or
            data.startswith("unban_user_")):
        await handle_remove_unban_callback(update, context)
        return

    # ── Scrape Single ──────────────────────────────────
    if data == "scrape_single":
        await query.answer()
        ok, msg = check_access(user.id)
        if not ok:
            await query.edit_message_text(msg, parse_mode="HTML")
            return

        context.user_data["awaiting_url"] = "single"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "❌ Cancel", callback_data="main_menu"
            )
        ]])
        await query.edit_message_text(
            "🔍 <b>Scrape Single Page</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📎 Send me the URL:\n\n"
            "💡 Example: <code>https://example.com</code>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    # ── Scrape All ─────────────────────────────────────
    if data == "scrape_all":
        await query.answer()
        ok, msg = check_access(user.id)
        if not ok:
            await query.edit_message_text(msg, parse_mode="HTML")
            return

        context.user_data["awaiting_url"] = "all"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "❌ Cancel", callback_data="main_menu"
            )
        ]])
        await query.edit_message_text(
            "🌐 <b>Scrape All Pages</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📎 Send me the base URL:\n\n"
            f"⚡ Crawls up to <b>{MAX_PAGES}</b> internal pages\n\n"
            "💡 Example: <code>https://example.com</code>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    # ── Asset Choice ───────────────────────────────────
    if data in ("assets_yes", "assets_no"):
        await query.answer()
        include_assets = (data == "assets_yes")
        context.user_data["include_assets"] = include_assets

        url = context.user_data.get("scrape_url")
        if not url:
            await query.edit_message_text(
                "❌ Session expired. Start again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔙 Main Menu",
                        callback_data="main_menu"
                    )
                ]])
            )
            return

        safe_url = html_module.escape(url[:80])

        if include_assets:
            await query.edit_message_text(
                f"🔗 URL: <code>{safe_url}</code>\n\n"
                f"📦 <b>Assets:</b> ✅ Included\n"
                f"  🖼 Images • 🎨 CSS • ⚙️ JS • 🔤 Fonts • 🎬 Video\n\n"
                f"📁 ZIP format required for assets:",
                reply_markup=get_format_zip_only(),
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text(
                f"🔗 URL: <code>{safe_url}</code>\n\n"
                f"📦 <b>Assets:</b> ❌ HTML source only\n\n"
                f"📁 Choose output format:",
                reply_markup=get_format_keyboard(),
                parse_mode="HTML"
            )
        return

    # ── Format Choice ──────────────────────────────────
    if data in ("format_single", "format_zip"):
        await query.answer()

        url = context.user_data.get("scrape_url")
        mode = context.user_data.get("scrape_mode")
        include_assets = context.user_data.get(
            "include_assets", False
        )

        if not url or not mode:
            await query.edit_message_text(
                "❌ Session expired. Start again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔙 Main Menu",
                        callback_data="main_menu"
                    )
                ]])
            )
            return

        output_format = "single" if data == "format_single" else "zip"
        if include_assets:
            output_format = "zip"

        context.user_data["output_format"] = output_format

        await perform_scrape(
            query, context, url, mode,
            output_format, include_assets, user
        )
        return


# ═══════════════════════════════════════════════════════
#  PERFORM SCRAPE
# ═══════════════════════════════════════════════════════

async def perform_scrape(
    query, context, url: str, mode: str,
    output_format: str, include_assets: bool, user
):
    asset_text = (
        "HTML + All Assets" if include_assets else "HTML Only"
    )
    fmt_text = (
        "Single File" if output_format == "single" else "ZIP"
    )

    loading_msg = await query.edit_message_text(
        f"🔄 <b>Starting scrape...</b>\n\n"
        f"🔗 URL: <code>{html_module.escape(url[:80])}</code>\n"
        f"📋 Mode: {'Single Page' if mode=='single' else 'All Pages'}\n"
        f"📦 Content: {asset_text}\n"
        f"📁 Format: {fmt_text}\n\n"
        f"{make_progress_bar(0, 1)}\n\n"
        f"⏳ Please wait...",
        parse_mode="HTML"
    )

    last_update = [time.time()]

    async def progress(text: str):
        now = time.time()
        if now - last_update[0] < 2.5:
            return
        last_update[0] = now
        try:
            await loading_msg.edit_text(text, parse_mode="HTML")
        except Exception:
            pass

    try:
        if mode == "single":
            result, error = await scraper.scrape_single(
                url,
                download_assets=include_assets,
                progress_callback=progress
            )
        else:
            result, error = await scraper.scrape_all_pages(
                url,
                download_assets=include_assets,
                progress_callback=progress
            )

        if error or not result or not result.pages:
            err_msg = error or "❌ No content scraped."
            retry_cb = (
                "scrape_single" if mode == "single"
                else "scrape_all"
            )
            await send_log(
                context, user, f"scrape_{mode}", url,
                status="error", details=err_msg[:300]
            )
            await loading_msg.edit_text(
                f"❌ <b>Failed</b>\n\n{err_msg}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🔄 Try Again",
                        callback_data=retry_cb
                    )],
                    [InlineKeyboardButton(
                        "🔙 Main Menu",
                        callback_data="main_menu"
                    )],
                ])
            )
            return

        # Pack file
        await loading_msg.edit_text(
            f"📦 <b>Packing {'ZIP' if output_format=='zip' else 'file'}...</b>\n\n"
            f"📄 Pages: {result.total_pages}\n"
            f"📦 Assets: {result.total_assets}\n"
            f"💾 Data: {format_size(result.total_size)}\n\n"
            f"{make_progress_bar(result.total_pages, result.total_pages)}",
            parse_mode="HTML"
        )

        if output_format == "zip":
            file_bytes, filename = create_zip_file(
                result, url, include_assets=include_assets
            )
        else:
            file_bytes, filename = create_single_file(
                result, url, include_assets=False
            )

        file_size = len(file_bytes)

        # Handle large files - split and send parts
        if file_size > 50 * 1024 * 1024:
            await loading_msg.edit_text(
                f"⚠️ <b>Large file: {format_size(file_size)}</b>\n\n"
                f"🔄 Splitting into 49MB parts...",
                parse_mode="HTML"
            )
            parts = split_zip(file_bytes, filename)
            for i, (pb, pname) in enumerate(parts, 1):
                fo = io.BytesIO(pb)
                fo.name = pname
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=InputFile(fo, filename=pname),
                    caption=(
                        f"📦 Part {i}/{len(parts)} | "
                        f"{format_size(len(pb))}"
                    )
                )
            await loading_msg.edit_text(
                f"✅ <b>Sent {len(parts)} parts!</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔙 Main Menu",
                        callback_data="main_menu"
                    )
                ]])
            )
            await send_log(
                context, user, f"scrape_{mode}", url,
                result.total_pages, result.total_assets,
                "success",
                f"Split {len(parts)} parts, "
                f"Size: {format_size(file_size)}"
            )
            return

        # Send single file
        fo = io.BytesIO(file_bytes)
        fo.name = filename

        asset_line = ""
        if result.total_assets > 0:
            asset_line = f"📦 Assets: {result.total_assets}\n"

        caption = (
            f"✅ <b>Scrape Complete!</b>\n\n"
            f"🔗 {html_module.escape(url[:70])}\n"
            f"📄 Pages: {result.total_pages}\n"
            f"{asset_line}"
            f"💾 Size: {format_size(file_size)}\n"
            f"⏱ Time: {result.elapsed:.1f}s\n"
            f"📡 Method: {result.fetch_method}\n\n"
            f"⚡ @TALK_WITH_STEALED"
        )

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=InputFile(fo, filename=filename),
            caption=caption,
            parse_mode="HTML"
        )

        await loading_msg.edit_text(
            f"✅ <b>File sent!</b>\n\n"
            f"📄 Pages: {result.total_pages}\n"
            f"📦 Assets: {result.total_assets}\n"
            f"💾 Size: {format_size(file_size)}\n"
            f"⏱ Time: {result.elapsed:.1f}s\n\n"
            f"{make_progress_bar(1, 1)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔍 Scrape Another",
                        callback_data="scrape_single"
                    ),
                    InlineKeyboardButton(
                        "🌐 Scrape All",
                        callback_data="scrape_all"
                    ),
                ],
                [InlineKeyboardButton(
                    "🔙 Main Menu",
                    callback_data="main_menu"
                )],
            ])
        )

        await send_log(
            context, user, f"scrape_{mode}", url,
            result.total_pages, result.total_assets,
            "success",
            f"Format:{output_format} "
            f"Assets:{include_assets} "
            f"Size:{format_size(file_size)}"
        )

    except Exception as e:
        logger.error(f"perform_scrape error: {e}", exc_info=True)
        await send_log(
            context, user, f"scrape_{mode}", url,
            status="error", details=str(e)[:300]
        )
        try:
            await loading_msg.edit_text(
                f"❌ <b>Unexpected error</b>\n\n"
                f"{html_module.escape(str(e)[:300])}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔙 Main Menu",
                        callback_data="main_menu"
                    )
                ]])
            )
        except Exception:
            pass

    finally:
        for k in ["scrape_url", "scrape_mode",
                  "output_format", "include_assets"]:
            context.user_data.pop(k, None)


def split_zip(data: bytes, filename: str,
              max_size: int = 49 * 1024 * 1024) -> list:
    if len(data) <= max_size:
        return [(data, filename)]
    base = filename.rsplit('.', 1)[0]
    parts = []
    for i, start in enumerate(range(0, len(data), max_size), 1):
        chunk = data[start:start + max_size]
        parts.append((chunk, f"{base}_part{i}.zip"))
    return parts


# ═══════════════════════════════════════════════════════
#  MESSAGE HANDLER
# ══════════════════════════════════════════════════════

async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.strip()

    # Admin input first
    if is_admin(user.id):
        handled = await process_admin_input(update, context)
        if handled:
            return

    # Check awaiting URL
    awaiting = context.user_data.get("awaiting_url")
    if not awaiting:
        await update.message.reply_text(
            "💡 Use the buttons to get started!",
            reply_markup=get_main_keyboard(user.id)
        )
        return

    # Access check
    ok, msg = check_access(user.id)
    if not ok:
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # Validate URL
    valid, result = validate_url(text)
    if not valid:
        await update.message.reply_text(
            f"{result}\n\n💡 Please send a valid URL.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "❌ Cancel", callback_data="main_menu"
                )
            ]])
        )
        return

    # Store and ask about assets
    context.user_data["scrape_url"] = result
    context.user_data["scrape_mode"] = awaiting
    context.user_data.pop("awaiting_url", None)

    mode_label = (
        "single page" if awaiting == "single"
        else f"all pages (max {MAX_PAGES})"
    )

    await update.message.reply_text(
        f"🔗 <b>URL:</b> <code>"
        f"{html_module.escape(result[:80])}</code>\n"
        f"📋 <b>Mode:</b> {mode_label}\n\n"
        f"🖼 <b>Include all assets?</b>\n\n"
        f"  🖼 Images • 🎨 CSS • ⚙️ JS\n"
        f"  🔤 Fonts • 🎬 Videos • 🎵 Audio",
        reply_markup=get_asset_choice_keyboard(),
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════
#  ERROR HANDLER
# ═══════════════════════════════════════════════════════

async def error_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    logger.error(
        f"Update {update} caused error: {context.error}",
        exc_info=context.error
    )
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An unexpected error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔙 Main Menu",
                        callback_data="main_menu"
                    )
                ]])
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    print("╔═══════════════════════════════════════════════╗")
    print("║  Website Scraper Bot v2.0                       ║")
    print("║  Full Assets + Anti-Block + Admin Panel         ║")
    print("║  Developed by @TALK_WITH_STEALED                ║")
    print("╚═══════════════════════════════════════════════╝")

    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌ Set your BOT_TOKEN in config.py!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CommandHandler("scrapeall", scrapeall_command))
    app.add_handler(CommandHandler("admin", admin_command))

    # Callbacks
    app.add_handler(CallbackQueryHandler(button_callback))

    # Messages
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    # Errors
    app.add_error_handler(error_handler)

    # Start
    print(f"\n✅ Bot running! Ctrl+C to stop.")
    print(f"📋 Admin IDs: {ADMIN_IDS}")
    log_ch = db.get_setting("log_channel_id")
    print(f"📡 Log Channel: {log_ch or 'Not set'}")
    print(f"👥 Users: {len(db.get_all_authorized_users())}")
    print("━" * 50)

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
