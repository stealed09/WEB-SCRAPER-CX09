"""
╔══════════════════════════════════════════╗
║  Website Source Code Scraper Telegram Bot  ║
║  Developed by @TALK_WITH_STEALED          ║
╚══════════════════════════════════════════╝
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
    MessageHandler, ContextTypes, filters, ConversationHandler
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

# ─── Logging ───────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Conversation States ──────────────────────────────
(WAITING_URL_SINGLE, WAITING_URL_ALL,
 WAITING_FORMAT_CHOICE) = range(3)

# ─── Scraper Instance ─────────────────────────────────
scraper = WebScraper()


# ═══════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════

def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Get the main menu keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("🔍 Scrape Single Page",
                                 callback_data="scrape_single"),
            InlineKeyboardButton("🌐 Scrape All Pages",
                                 callback_data="scrape_all"),
        ],
        [
            InlineKeyboardButton("📖 Help", callback_data="help"),
        ],
        [
            InlineKeyboardButton("📩 Contact Developer",
                                 url=DEVELOPER_LINK),
        ],
    ]
    # Admin button
    if is_admin(user_id):
        keyboard.insert(2, [
            InlineKeyboardButton("🛡️ Admin Panel",
                                 callback_data="admin_panel")
        ])
    return InlineKeyboardMarkup(keyboard)


def get_format_keyboard() -> InlineKeyboardMarkup:
    """Get file format choice keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📄 Single File (.html)",
                                 callback_data="format_single"),
            InlineKeyboardButton("📦 ZIP Archive (.zip)",
                                 callback_data="format_zip"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu"),
        ],
    ])


def check_access(user_id: int) -> tuple[bool, str]:
    """Check if user has access to the bot."""
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


async def send_log(context: ContextTypes.DEFAULT_TYPE,
                   user, action: str, url: str = "",
                   pages: int = 0, status: str = "success",
                   details: str = ""):
    """Send log to the log channel and database."""
    username = user.username or "N/A"
    first_name = user.first_name or "N/A"
    user_id = user.id

    db.add_log(user_id, username, action, url, pages, status, details)

    channel_id = db.get_setting("log_channel_id")
    if channel_id:
        try:
            status_icon = "✅" if status == "success" else "❌"
            log_text = (
                f"📋 <b>Bot Log</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{status_icon} <b>Action:</b> {action}\n"
                f"👤 <b>User:</b> {first_name} (@{username})\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            )
            if url:
                safe_url = html_module.escape(url[:200])
                log_text += f"🔗 <b>URL:</b> {safe_url}\n"
            if pages:
                log_text += f"📄 <b>Pages:</b> {pages}\n"
            if details:
                log_text += f"📝 <b>Details:</b> {details[:300]}\n"
            log_text += f"🕐 <b>Time:</b> {format_timestamp(time.time())}"

            await context.bot.send_message(
                int(channel_id), log_text, parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send log to channel: {e}")


# ═══════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════

async def start_command(update: Update,
                        context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user

    # Clear any ongoing conversation state
    context.user_data.clear()

    welcome = get_welcome_message()
    keyboard = get_main_keyboard(user.id)

    await update.message.reply_text(
        welcome,
        reply_markup=keyboard,
        parse_mode=None  # Plain text for the box drawing
    )

    await send_log(context, user, "start")


async def help_command(update: Update,
                       context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ])
    await update.message.reply_text(
        get_help_message(), reply_markup=back_kb, parse_mode="HTML"
    )


async def scrape_command(update: Update,
                         context: ContextTypes.DEFAULT_TYPE):
    """Handle /scrape <url> command."""
    user = update.effective_user
    has_access, msg = check_access(user.id)
    if not has_access:
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a URL.\n"
            "Usage: /scrape <url>\n\n"
            "Example: /scrape https://example.com"
        )
        return

    url = context.args[0]
    is_valid, result = validate_url(url)
    if not is_valid:
        await update.message.reply_text(result)
        return

    # Store data and ask format
    context.user_data["scrape_url"] = result
    context.user_data["scrape_mode"] = "single"

    await update.message.reply_text(
        f"🔗 URL: <code>{html_module.escape(result)}</code>\n\n"
        f"📦 How would you like to receive the file?",
        reply_markup=get_format_keyboard(),
        parse_mode="HTML"
    )


async def scrapeall_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    """Handle /scrapeall <url> command."""
    user = update.effective_user
    has_access, msg = check_access(user.id)
    if not has_access:
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a URL.\n"
            "Usage: /scrapeall <url>\n\n"
            "Example: /scrapeall https://example.com"
        )
        return

    url = context.args[0]
    is_valid, result = validate_url(url)
    if not is_valid:
        await update.message.reply_text(result)
        return

    context.user_data["scrape_url"] = result
    context.user_data["scrape_mode"] = "all"

    await update.message.reply_text(
        f"🔗 URL: <code>{html_module.escape(result)}</code>\n\n"
        f"🌐 This will scrape up to <b>{MAX_PAGES}</b> internal pages.\n\n"
        f"📦 How would you like to receive the files?",
        reply_markup=get_format_keyboard(),
        parse_mode="HTML"
    )


async def admin_command(update: Update,
                        context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command."""
    await admin_panel(update, context)


# ═══════════════════════════════════════════════════════
#  CALLBACK QUERY HANDLERS
# ═══════════════════════════════════════════════════════

async def button_callback(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    """Handle all button callbacks."""
    query = update.callback_query
    data = query.data
    user = query.from_user

    # ─── Main Menu ─────────────────────────────────
    if data == "main_menu":
        await query.answer()
        context.user_data.clear()
        welcome = get_welcome_message()
        keyboard = get_main_keyboard(user.id)
        await query.edit_message_text(welcome, reply_markup=keyboard)
        return

    # ─── Help ──────────────────────────────────────
    if data == "help":
        await query.answer()
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ])
        await query.edit_message_text(
            get_help_message(), reply_markup=back_kb, parse_mode="HTML"
        )
        return

    # ─── Admin Panel ───────────────────────────────
    if data == "admin_panel":
        await handle_admin_callback(update, context)
        return

    if data.startswith("admin_"):
        await handle_admin_callback(update, context)
        return

    if data.startswith("remove_user_") or data.startswith("unban_user_"):
        await handle_remove_unban_callback(update, context)
        return

    # ─── Scrape Buttons ───────────────────────────
    if data == "scrape_single":
        await query.answer()
        has_access, msg = check_access(user.id)
        if not has_access:
            await query.edit_message_text(msg, parse_mode="HTML")
            return

        context.user_data["awaiting_url"] = "single"
        text = (
            "🔍 <b>Scrape Single Page</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📎 Send me the URL you want to scrape:\n\n"
            "💡 Example: <code>https://example.com</code>"
        )
        cancel_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]
        ])
        await query.edit_message_text(
            text, reply_markup=cancel_kb, parse_mode="HTML"
        )
        return

    if data == "scrape_all":
        await query.answer()
        has_access, msg = check_access(user.id)
        if not has_access:
            await query.edit_message_text(msg, parse_mode="HTML")
            return

        context.user_data["awaiting_url"] = "all"
        text = (
            "🌐 <b>Scrape All Pages</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📎 Send me the base URL to scrape:\n\n"
            f"⚡ Will crawl up to <b>{MAX_PAGES}</b> internal pages\n\n"
            "💡 Example: <code>https://example.com</code>"
        )
        cancel_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]
        ])
        await query.edit_message_text(
            text, reply_markup=cancel_kb, parse_mode="HTML"
        )
        return

    # ─── Format Choice ─────────────────────────────
    if data in ("format_single", "format_zip"):
        await query.answer()

        url = context.user_data.get("scrape_url")
        mode = context.user_data.get("scrape_mode")

        if not url or not mode:
            await query.edit_message_text(
                "❌ Session expired. Please start again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu",
                                          callback_data="main_menu")]
                ])
            )
            return

        output_format = "single" if data == "format_single" else "zip"
        context.user_data["output_format"] = output_format

        await perform_scrape(query, context, url, mode, output_format, user)
        return


# ═══════════════════════════════════════════════════════
#  SCRAPING EXECUTION
# ═══════════════════════════════════════════════════════

async def perform_scrape(query, context, url, mode, output_format, user):
    """Execute the scraping operation."""
    # Send initial loading message
    loading_msg = await query.edit_message_text(
        f"🔄 <b>Starting scrape...</b>\n\n"
        f"🔗 URL: <code>{html_module.escape(url[:100])}</code>\n"
        f"📋 Mode: {'Single Page' if mode == 'single' else 'All Pages'}\n"
        f"📦 Format: {'Single File' if output_format == 'single' else 'ZIP'}\n\n"
        f"{make_progress_bar(0, 1)}\n\n"
        f"⏳ Please wait...",
        parse_mode="HTML"
    )

    last_update_time = [time.time()]

    async def progress_callback(status_text: str):
        """Update progress message (rate limited)."""
        now = time.time()
        if now - last_update_time[0] < 2:  # Max 1 update per 2 seconds
            return
        last_update_time[0] = now
        try:
            await loading_msg.edit_text(status_text, parse_mode="HTML")
        except Exception:
            pass

    try:
        if mode == "single":
            # Single page scrape
            page, error = await scraper.scrape_single(url, progress_callback)

            if error:
                await send_log(
                    context, user, "scrape_single", url,
                    status="error", details=error
                )
                await loading_msg.edit_text(
                    f"❌ <b>Scraping Failed</b>\n\n{error}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Try Again",
                                              callback_data="scrape_single")],
                        [InlineKeyboardButton("🔙 Main Menu",
                                              callback_data="main_menu")]
                    ])
                )
                return

            pages = [page]

        else:
            # Multi-page scrape
            pages, error = await scraper.scrape_all_pages(
                url, progress_callback
            )

            if error:
                await send_log(
                    context, user, "scrape_all", url,
                    status="error", details=error
                )
                await loading_msg.edit_text(
                    f"❌ <b>Scraping Failed</b>\n\n{error}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Try Again",
                                              callback_data="scrape_all")],
                        [InlineKeyboardButton("🔙 Main Menu",
                                              callback_data="main_menu")]
                    ])
                )
                return

        if not pages:
            await loading_msg.edit_text(
                "❌ No content could be scraped.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu",
                                          callback_data="main_menu")]
                ])
            )
            return

        # Generate file
        await loading_msg.edit_text(
            f"📦 <b>Preparing {'ZIP' if output_format == 'zip' else 'file'}...</b>\n\n"
            f"📄 Pages: {len(pages)}\n"
            f"💾 Total size: {format_size(sum(p.size for p in pages))}\n\n"
            f"{make_progress_bar(len(pages), len(pages))}",
            parse_mode="HTML"
        )

        if output_format == "zip":
            file_bytes, filename = create_zip_file(pages, url)
        else:
            file_bytes, filename = create_single_file(pages, url)

        file_size = len(file_bytes)

        # Check Telegram file size limit (50MB)
        if file_size > 50 * 1024 * 1024:
            await loading_msg.edit_text(
                f"❌ <b>File too large!</b>\n\n"
                f"Generated file: {format_size(file_size)}\n"
                f"Telegram limit: 50 MB\n\n"
                f"💡 Try scraping fewer pages or use ZIP format.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu",
                                          callback_data="main_menu")]
                ])
            )
            return

        # Send file
        file_obj = io.BytesIO(file_bytes)
        file_obj.name = filename

        caption = (
            f"✅ <b>Scrape Complete!</b>\n\n"
            f"🔗 URL: {html_module.escape(url[:100])}\n"
            f"📄 Pages: {len(pages)}\n"
            f"💾 Size: {format_size(file_size)}\n"
            f"📦 Format: {'ZIP' if output_format == 'zip' else 'HTML'}\n\n"
            f"⚡ @TALK_WITH_STEALED"
        )

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=InputFile(file_obj, filename=filename),
            caption=caption,
            parse_mode="HTML"
        )

        # Update loading message
        await loading_msg.edit_text(
            f"✅ <b>File sent successfully!</b>\n\n"
            f"{make_progress_bar(len(pages), len(pages))}\n\n"
            f"📄 {len(pages)} page(s) scraped",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Scrape Another",
                                      callback_data="scrape_single"),
                 InlineKeyboardButton("🌐 Scrape All",
                                      callback_data="scrape_all")],
                [InlineKeyboardButton("🔙 Main Menu",
                                      callback_data="main_menu")]
            ])
        )

        # Log success
        await send_log(
            context, user,
            "scrape_single" if mode == "single" else "scrape_all",
            url, len(pages), "success",
            f"Format: {output_format}, Size: {format_size(file_size)}"
        )

    except Exception as e:
        logger.error(f"Scrape error: {e}", exc_info=True)
        await send_log(
            context, user, f"scrape_{mode}", url,
            status="error", details=str(e)[:300]
        )
        try:
            await loading_msg.edit_text(
                f"❌ <b>An error occurred</b>\n\n"
                f"Error: {html_module.escape(str(e)[:300])}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu",
                                          callback_data="main_menu")]
                ])
            )
        except Exception:
            pass

    finally:
        # Clean up context
        context.user_data.pop("scrape_url", None)
        context.user_data.pop("scrape_mode", None)
        context.user_data.pop("output_format", None)


# ═══════════════════════════════════════════════════════
#  MESSAGE HANDLER (URL input)
# ═══════════════════════════════════════════════════════

async def handle_message(update: Update,
                         context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (URL input and admin input)."""
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.strip()

    # Check if it's admin input first
    if is_admin(user.id):
        handled = await process_admin_input(update, context)
        if handled:
            return

    # Check if we're awaiting a URL
    awaiting = context.user_data.get("awaiting_url")
    if not awaiting:
        # Not awaiting anything - show hint
        await update.message.reply_text(
            "💡 Use the buttons below to get started!",
            reply_markup=get_main_keyboard(user.id)
        )
        return

    # Check access
    has_access, msg = check_access(user.id)
    if not has_access:
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # Validate URL
    is_valid, result = validate_url(text)
    if not is_valid:
        await update.message.reply_text(
            f"{result}\n\n💡 Please send a valid URL.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]
            ])
        )
        return

    # Store URL and ask for format
    context.user_data["scrape_url"] = result
    context.user_data["scrape_mode"] = awaiting  # "single" or "all"
    context.user_data.pop("awaiting_url", None)

    mode_text = "single page" if awaiting == "single" else f"all pages (max {MAX_PAGES})"

    await update.message.reply_text(
        f"🔗 <b>URL:</b> <code>{html_module.escape(result[:100])}</code>\n"
        f"📋 <b>Mode:</b> Scraping {mode_text}\n\n"
        f"📦 <b>Choose output format:</b>",
        reply_markup=get_format_keyboard(),
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════
#  ERROR HANDLER
# ═══════════════════════════════════════════════════════

async def error_handler(update: Update,
                        context: ContextTypes.DEFAULT_TYPE):
    """Handle all uncaught errors."""
    logger.error(f"Update {update} caused error: {context.error}",
                 exc_info=context.error)

    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An unexpected error occurred. Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu",
                                          callback_data="main_menu")]
                ])
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════
#  MAIN - BOT STARTUP
# ═══════════════════════════════════════════════════════

def main():
    """Start the bot."""
    print("╔══════════════════════════════════════════╗")
    print("║  Website Scraper Bot Starting...           ║")
    print("║  Developed by @TALK_WITH_STEALED           ║")
    print("╚══════════════════════════════════════════╝")

    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌ ERROR: Please set your BOT_TOKEN in config.py!")
        print("   Get one from @BotFather on Telegram")
        return

    # Build application
    app = Application.builder().token(BOT_TOKEN).build()

    # ─── Command Handlers ──────────────────────────
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CommandHandler("scrapeall", scrapeall_command))
    app.add_handler(CommandHandler("admin", admin_command))

    # ─── Callback Query Handler ────────────────────
    app.add_handler(CallbackQueryHandler(button_callback))

    # ─── Message Handler ───────────────────────────
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    # ─── Error Handler ─────────────────────────────
    app.add_error_handler(error_handler)

    # ─── Start Polling ─────────────────────────────
    print("\n✅ Bot is running! Press Ctrl+C to stop.")
    print(f"📋 Admin IDs: {ADMIN_IDS}")

    log_ch = db.get_setting("log_channel_id")
    print(f"📡 Log Channel: {log_ch or 'Not set (use /admin)'}")
    print(f"👥 Authorized Users: {len(db.get_all_authorized_users())}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
