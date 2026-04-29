"""Configuration file for the Telegram Scraper Bot."""

import os

# Bot Token - Replace with your actual bot token
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Admin User IDs - Replace with actual admin Telegram user IDs
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",")]

# Log Channel ID - Will be set by admin via bot
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", None)
if LOG_CHANNEL_ID:
    LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)

# Scraping settings
MAX_PAGES = 599
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
CONCURRENT_REQUESTS = 10
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Database
DB_FILE = "bot_database.db"

# Developer info
DEVELOPER_USERNAME = "@TALK_WITH_STEALED"
DEVELOPER_LINK = "https://t.me/TALK_WITH_STEALED"
