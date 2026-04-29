"""Database management for the Telegram Scraper Bot."""

import sqlite3
import time
from typing import Optional
from config import DB_FILE


class Database:
    """Handles all database operations."""

    def __init__(self):
        self.db_file = DB_FILE
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS authorized_users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                authorized_by INTEGER,
                authorized_at REAL,
                is_active     INTEGER DEFAULT 1
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER,
                username       TEXT,
                action         TEXT,
                url            TEXT,
                pages_scraped  INTEGER DEFAULT 0,
                assets_scraped INTEGER DEFAULT 0,
                status         TEXT,
                timestamp      REAL,
                details        TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id   INTEGER PRIMARY KEY,
                reason    TEXT,
                banned_by INTEGER,
                banned_at REAL
            )
        """)

        conn.commit()
        conn.close()

    # ── Authorized Users ──────────────────────────────

    def add_authorized_user(self, user_id: int, username: str,
                            first_name: str, authorized_by: int) -> bool:
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO authorized_users
                   (user_id, username, first_name, authorized_by,
                    authorized_at, is_active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (user_id, username, first_name, authorized_by, time.time())
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def remove_authorized_user(self, user_id: int) -> bool:
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM authorized_users WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False
        finally:
            conn.close()

    def is_authorized(self, user_id: int) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT 1 FROM authorized_users "
            "WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def get_all_authorized_users(self) -> list:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM authorized_users WHERE is_active = 1 "
            "ORDER BY authorized_at DESC"
        )
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return users

    # ── Banned Users ──────────────────────────────────

    def ban_user(self, user_id: int, reason: str,
                 banned_by: int) -> bool:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO banned_users VALUES (?, ?, ?, ?)",
                (user_id, reason, banned_by, time.time())
            )
            conn.execute(
                "UPDATE authorized_users SET is_active = 0 "
                "WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def unban_user(self, user_id: int) -> bool:
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM banned_users WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False
        finally:
            conn.close()

    def is_banned(self, user_id: int) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT 1 FROM banned_users WHERE user_id = ?",
            (user_id,)
        )
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def get_banned_users(self) -> list:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM banned_users ORDER BY banned_at DESC"
        )
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return users

    # ── Settings ──────────────────────────────────────

    def set_setting(self, key: str, value: str) -> bool:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) "
                "VALUES (?, ?)",
                (key, value)
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def get_setting(self, key: str) -> Optional[str]:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        conn.close()
        return row["value"] if row else None

    # ── Logs ──────────────────────────────────────────

    def add_log(self, user_id: int, username: str, action: str,
                url: str = "", pages_scraped: int = 0,
                assets_scraped: int = 0,
                status: str = "success", details: str = ""):
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO usage_logs
                   (user_id, username, action, url, pages_scraped,
                    assets_scraped, status, timestamp, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, username, action, url, pages_scraped,
                 assets_scraped, status, time.time(), details)
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def get_recent_logs(self, limit: int = 50) -> list:
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM usage_logs "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return logs

    def get_stats(self) -> dict:
        conn = self._get_conn()
        stats = {}

        cursor = conn.execute(
            "SELECT COUNT(*) as c FROM authorized_users "
            "WHERE is_active = 1"
        )
        stats["total_users"] = cursor.fetchone()["c"]

        cursor = conn.execute(
            "SELECT COUNT(*) as c FROM banned_users"
        )
        stats["banned_users"] = cursor.fetchone()["c"]

        cursor = conn.execute(
            "SELECT COUNT(*) as c FROM usage_logs"
        )
        stats["total_actions"] = cursor.fetchone()["c"]

        cursor = conn.execute(
            "SELECT COUNT(*) as c FROM usage_logs "
            "WHERE action IN ('scrape_single', 'scrape_all')"
        )
        stats["total_scrapes"] = cursor.fetchone()["c"]

        cursor = conn.execute(
            "SELECT SUM(pages_scraped) as c FROM usage_logs"
        )
        row = cursor.fetchone()
        stats["total_pages"] = row["c"] if row["c"] else 0

        cursor = conn.execute(
            "SELECT SUM(assets_scraped) as c FROM usage_logs"
        )
        row = cursor.fetchone()
        stats["total_assets"] = row["c"] if row["c"] else 0

        conn.close()
        return stats


# Singleton instance
db = Database()
