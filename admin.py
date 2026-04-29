"""Admin panel handlers for the Telegram Scraper Bot."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from database import db
from utils import format_timestamp, truncate_text


def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    return user_id in ADMIN_IDS


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Get the main admin panel keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("👥 Authorized Users", callback_data="admin_users"),
            InlineKeyboardButton("🚫 Banned Users", callback_data="admin_banned"),
        ],
        [
            InlineKeyboardButton("➕ Add User", callback_data="admin_add_user"),
            InlineKeyboardButton("➖ Remove User", callback_data="admin_remove_user"),
        ],
        [
            InlineKeyboardButton("🔨 Ban User", callback_data="admin_ban_user"),
            InlineKeyboardButton("✅ Unban User", callback_data="admin_unban_user"),
        ],
        [
            InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
            InlineKeyboardButton("📋 Recent Logs", callback_data="admin_logs"),
        ],
        [
            InlineKeyboardButton("📡 Set Log Channel", callback_data="admin_set_channel"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel."""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        if update.callback_query:
            await update.callback_query.answer("⛔ You are not an admin!", show_alert=True)
        return

    text = (
        "🛡️ <b>ADMIN PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select an option below:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=get_admin_keyboard(), parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=get_admin_keyboard(), parse_mode="HTML"
        )


async def handle_admin_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel callbacks."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        await query.answer("⛔ You are not an admin!", show_alert=True)
        return

    await query.answer()

    if data == "admin_users":
        await show_authorized_users(query, context)
    elif data == "admin_banned":
        await show_banned_users(query, context)
    elif data == "admin_add_user":
        await prompt_add_user(query, context)
    elif data == "admin_remove_user":
        await prompt_remove_user(query, context)
    elif data == "admin_ban_user":
        await prompt_ban_user(query, context)
    elif data == "admin_unban_user":
        await prompt_unban_user(query, context)
    elif data == "admin_stats":
        await show_stats(query, context)
    elif data == "admin_logs":
        await show_logs(query, context)
    elif data == "admin_set_channel":
        await prompt_set_channel(query, context)
    elif data == "admin_panel":
        await admin_panel(update, context)


async def show_authorized_users(query, context):
    """Show list of authorized users."""
    users = db.get_all_authorized_users()

    if not users:
        text = "👥 <b>Authorized Users</b>\n\n📭 No authorized users yet."
    else:
        text = f"👥 <b>Authorized Users ({len(users)})</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
        for u in users[:30]:  # Limit display
            username = u.get("username", "N/A") or "N/A"
            first_name = u.get("first_name", "N/A") or "N/A"
            text += (
                f"• <b>{first_name}</b> (@{username})\n"
                f"  ID: <code>{u['user_id']}</code>\n"
                f"  Added: {format_timestamp(u['authorized_at'])}\n\n"
            )
        if len(users) > 30:
            text += f"... and {len(users) - 30} more"

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
    ])
    await query.edit_message_text(
        truncate_text(text), reply_markup=back_kb, parse_mode="HTML"
    )


async def show_banned_users(query, context):
    """Show list of banned users."""
    users = db.get_banned_users()

    if not users:
        text = "🚫 <b>Banned Users</b>\n\n✅ No banned users."
    else:
        text = f"🚫 <b>Banned Users ({len(users)})</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
        for u in users[:30]:
            text += (
                f"• ID: <code>{u['user_id']}</code>\n"
                f"  Reason: {u.get('reason', 'N/A')}\n"
                f"  Banned: {format_timestamp(u['banned_at'])}\n\n"
            )

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
    ])
    await query.edit_message_text(
        truncate_text(text), reply_markup=back_kb, parse_mode="HTML"
    )


async def prompt_add_user(query, context):
    """Prompt admin to add a user."""
    context.user_data["admin_action"] = "add_user"

    text = (
        "➕ <b>Add Authorized User</b>\n\n"
        "Send the user's Telegram ID (numeric):\n\n"
        "💡 <i>User can find their ID using @userinfobot</i>"
    )
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]
    ])
    await query.edit_message_text(text, reply_markup=back_kb, parse_mode="HTML")


async def prompt_remove_user(query, context):
    """Prompt admin to remove a user."""
    context.user_data["admin_action"] = "remove_user"

    users = db.get_all_authorized_users()
    if not users:
        text = "📭 No authorized users to remove."
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
        ])
        await query.edit_message_text(text, reply_markup=back_kb, parse_mode="HTML")
        return

    keyboard = []
    for u in users[:20]:
        name = u.get("first_name", "") or str(u["user_id"])
        username = u.get("username", "")
        label = f"❌ {name}"
        if username:
            label += f" (@{username})"
        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"remove_user_{u['user_id']}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
    ])

    text = "➖ <b>Remove User</b>\n\nSelect user to remove:"
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
    )


async def prompt_ban_user(query, context):
    """Prompt admin to ban a user."""
    context.user_data["admin_action"] = "ban_user"

    text = (
        "🔨 <b>Ban User</b>\n\n"
        "Send the user ID to ban:\n"
        "Format: <code>USER_ID reason</code>\n\n"
        "Example: <code>123456789 Spamming</code>"
    )
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]
    ])
    await query.edit_message_text(text, reply_markup=back_kb, parse_mode="HTML")


async def prompt_unban_user(query, context):
    """Prompt admin to unban a user."""
    users = db.get_banned_users()
    if not users:
        text = "✅ No banned users to unban."
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
        ])
        await query.edit_message_text(text, reply_markup=back_kb, parse_mode="HTML")
        return

    keyboard = []
    for u in users[:20]:
        keyboard.append([
            InlineKeyboardButton(
                f"✅ Unban {u['user_id']} ({u.get('reason', 'N/A')})",
                callback_data=f"unban_user_{u['user_id']}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
    ])

    text = "✅ <b>Unban User</b>\n\nSelect user to unban:"
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
    )


async def show_stats(query, context):
    """Show bot statistics."""
    stats = db.get_stats()
    log_channel = db.get_setting("log_channel_id")

    text = (
        "📊 <b>BOT STATISTICS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Authorized Users: <b>{stats['total_users']}</b>\n"
        f"🚫 Banned Users: <b>{stats['banned_users']}</b>\n"
        f"📋 Total Actions: <b>{stats['total_actions']}</b>\n"
        f"🔍 Total Scrapes: <b>{stats['total_scrapes']}</b>\n"
        f"📄 Total Pages Scraped: <b>{stats['total_pages']}</b>\n"
        f"📡 Log Channel: <b>"
        f"{'Set (' + log_channel + ')' if log_channel else 'Not Set'}</b>\n"
    )

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ])
    await query.edit_message_text(text, reply_markup=back_kb, parse_mode="HTML")


async def show_logs(query, context):
    """Show recent activity logs."""
    logs = db.get_recent_logs(20)

    if not logs:
        text = "📋 <b>Recent Logs</b>\n\n📭 No activity logs yet."
    else:
        text = "📋 <b>Recent Logs (Last 20)</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
        for log in logs:
            status_icon = "✅" if log["status"] == "success" else "❌"
            username = log.get("username", "N/A") or "N/A"
            text += (
                f"{status_icon} <b>{log['action']}</b> by @{username}\n"
                f"   ID: {log['user_id']} | "
                f"{format_timestamp(log['timestamp'])}\n"
            )
            if log.get("url"):
                url_short = (log["url"][:50] + "..."
                             if len(log["url"]) > 50 else log["url"])
                text += f"   URL: {url_short}\n"
            if log.get("pages_scraped"):
                text += f"   Pages: {log['pages_scraped']}\n"
            text += "\n"

    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_logs")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
    ])
    await query.edit_message_text(
        truncate_text(text), reply_markup=back_kb, parse_mode="HTML"
    )


async def prompt_set_channel(query, context):
    """Prompt admin to set log channel."""
    context.user_data["admin_action"] = "set_channel"

    current = db.get_setting("log_channel_id")
    current_text = f"Current: <code>{current}</code>" if current else "Currently: Not set"

    text = (
        "📡 <b>Set Log Channel</b>\n\n"
        f"{current_text}\n\n"
        "Send the channel ID (e.g., <code>-1001234567890</code>)\n\n"
        "💡 <i>Steps:\n"
        "1. Add bot to your private channel as admin\n"
        "2. Forward a message from channel to @userinfobot\n"
        "3. Send the channel ID here</i>"
    )
    back_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]
    ])
    await query.edit_message_text(text, reply_markup=back_kb, parse_mode="HTML")


async def process_admin_input(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Process admin text input.
    Returns True if the message was handled as admin input.
    """
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return False

    action = context.user_data.get("admin_action")
    if not action:
        return False

    text = update.message.text.strip()

    if action == "add_user":
        context.user_data.pop("admin_action", None)
        try:
            target_id = int(text.split()[0])
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ Invalid user ID. Must be numeric.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
            return True

        success = db.add_authorized_user(
            target_id, "", "", user_id
        )
        if success:
            db.add_log(
                user_id, update.effective_user.username or "",
                "admin_add_user", details=f"Added user {target_id}"
            )
            await update.message.reply_text(
                f"✅ User <code>{target_id}</code> has been authorized!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
        else:
            await update.message.reply_text(
                "❌ Failed to add user.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
        return True

    elif action == "ban_user":
        context.user_data.pop("admin_action", None)
        parts = text.split(maxsplit=1)
        try:
            target_id = int(parts[0])
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ Invalid format. Use: USER_ID reason",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
            return True

        reason = parts[1] if len(parts) > 1 else "No reason provided"

        success = db.ban_user(target_id, reason, user_id)
        if success:
            db.add_log(
                user_id, update.effective_user.username or "",
                "admin_ban_user",
                details=f"Banned user {target_id}: {reason}"
            )
            await update.message.reply_text(
                f"🔨 User <code>{target_id}</code> has been banned!\n"
                f"Reason: {reason}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
        else:
            await update.message.reply_text("❌ Failed to ban user.")
        return True

    elif action == "set_channel":
        context.user_data.pop("admin_action", None)
        try:
            channel_id = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid channel ID. Must be numeric (usually negative).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
            return True

        # Test sending to channel
        try:
            await context.bot.send_message(
                channel_id,
                "✅ Log channel connected successfully!\n"
                "This channel will receive bot activity logs."
            )
            db.set_setting("log_channel_id", str(channel_id))
            db.add_log(
                user_id, update.effective_user.username or "",
                "admin_set_channel",
                details=f"Set log channel to {channel_id}"
            )
            await update.message.reply_text(
                f"✅ Log channel set to <code>{channel_id}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Failed to send to channel.\n"
                f"Make sure the bot is an admin in the channel.\n"
                f"Error: {str(e)[:200]}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
        return True

    return False


async def handle_remove_unban_callback(update: Update,
                                       context: ContextTypes.DEFAULT_TYPE):
    """Handle remove/unban user callbacks."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        await query.answer("⛔ Not authorized!", show_alert=True)
        return

    await query.answer()

    if data.startswith("remove_user_"):
        target_id = int(data.replace("remove_user_", ""))
        success = db.remove_authorized_user(target_id)
        if success:
            db.add_log(
                user_id, query.from_user.username or "",
                "admin_remove_user",
                details=f"Removed user {target_id}"
            )
            await query.edit_message_text(
                f"✅ User <code>{target_id}</code> has been removed.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
        else:
            await query.edit_message_text(
                "❌ User not found.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )

    elif data.startswith("unban_user_"):
        target_id = int(data.replace("unban_user_", ""))
        success = db.unban_user(target_id)
        if success:
            db.add_log(
                user_id, query.from_user.username or "",
                "admin_unban_user",
                details=f"Unbanned user {target_id}"
            )
            await query.edit_message_text(
                f"✅ User <code>{target_id}</code> has been unbanned.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
        else:
            await query.edit_message_text(
                "❌ User not found in ban list.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Admin Panel",
                                          callback_data="admin_panel")]
                ])
            )
