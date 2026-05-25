import aiosqlite
import logging
from datetime import date
from config import config

logger = logging.getLogger(__name__)
DB = config.DB_PATH


# ══════════════════════════════════════════════════════════════
#  INIT
# ══════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                lang_pref   TEXT DEFAULT 'auto',
                joined_at   TEXT DEFAULT (datetime('now')),
                last_seen   TEXT DEFAULT (datetime('now')),
                is_banned   INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS requests (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                req_type    TEXT DEFAULT 'stt',
                req_date    TEXT DEFAULT (date('now')),
                req_time    TEXT DEFAULT (datetime('now')),
                duration_s  REAL DEFAULT 0,
                char_count  INTEGER DEFAULT 0,
                success     INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS rate_limit (
                user_id     INTEGER NOT NULL,
                req_time    TEXT DEFAULT (datetime('now'))
            );
        """)
        await db.commit()
    logger.info("✅ Database tayyor.")


# ══════════════════════════════════════════════════════════════
#  USER
# ══════════════════════════════════════════════════════════════

async def upsert_user(user_id: int, username: str | None, full_name: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name,
                last_seen = datetime('now')
        """, (user_id, username, full_name))
        await db.commit()


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def set_lang_pref(user_id: int, lang: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE users SET lang_pref = ? WHERE user_id = ?", (lang, user_id))
        await db.commit()


async def ban_user(user_id: int, banned: bool = True):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?",
            (int(banned), user_id)
        )
        await db.commit()


async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE is_banned = 0"
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


# ══════════════════════════════════════════════════════════════
#  REQUESTS
# ══════════════════════════════════════════════════════════════

async def log_request(
    user_id: int,
    duration_s: float,
    char_count: int,
    success: bool = True,
    req_type: str = "stt"
):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            INSERT INTO requests (user_id, req_type, duration_s, char_count, success)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, req_type, duration_s, char_count, int(success)))
        await db.commit()


async def get_daily_count(user_id: int) -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM requests WHERE user_id = ? AND req_date = ?",
            (user_id, today)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_user_full_stats(user_id: int) -> dict:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        stats = {}
        today = date.today().isoformat()

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM requests WHERE user_id = ?", (user_id,)
        ) as c:
            stats["total"] = (await c.fetchone())["cnt"]

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM requests WHERE user_id = ? AND req_date = ?",
            (user_id, today)
        ) as c:
            stats["today"] = (await c.fetchone())["cnt"]

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM requests WHERE user_id = ? AND success = 1",
            (user_id,)
        ) as c:
            stats["successful"] = (await c.fetchone())["cnt"]

        async with db.execute(
            "SELECT AVG(duration_s) as avg FROM requests WHERE user_id = ? AND success = 1",
            (user_id,)
        ) as c:
            row = (await c.fetchone())["avg"]
            stats["avg_duration"] = round(row, 2) if row else 0

        async with db.execute(
            "SELECT SUM(char_count) as total FROM requests WHERE user_id = ?",
            (user_id,)
        ) as c:
            row = (await c.fetchone())["total"]
            stats["total_chars"] = row or 0

        return stats


# ══════════════════════════════════════════════════════════════
#  RATE LIMIT
# ══════════════════════════════════════════════════════════════

async def check_rate_limit(user_id: int) -> bool:
    """True = ruxsat, False = limit oshgan."""
    window = config.RATE_LIMIT_WINDOW
    max_req = config.RATE_LIMIT_REQUESTS
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "DELETE FROM rate_limit WHERE req_time < datetime('now', ?)",
            (f"-{window} seconds",)
        )
        async with db.execute(
            "SELECT COUNT(*) FROM rate_limit WHERE user_id = ?", (user_id,)
        ) as cur:
            count = (await cur.fetchone())[0]

        if count >= max_req:
            await db.commit()
            return False

        await db.execute("INSERT INTO rate_limit (user_id) VALUES (?)", (user_id,))
        await db.commit()
        return True


# ══════════════════════════════════════════════════════════════
#  GLOBAL STATS
# ══════════════════════════════════════════════════════════════

async def get_global_stats() -> dict:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        stats = {}

        async with db.execute("SELECT COUNT(*) as cnt FROM users") as c:
            stats["total_users"] = (await c.fetchone())["cnt"]

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE last_seen >= datetime('now', '-1 day')"
        ) as c:
            stats["active_today"] = (await c.fetchone())["cnt"]

        async with db.execute("SELECT COUNT(*) as cnt FROM requests") as c:
            stats["total_requests"] = (await c.fetchone())["cnt"]

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM requests WHERE req_date = date('now')"
        ) as c:
            stats["requests_today"] = (await c.fetchone())["cnt"]

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM requests WHERE success = 1"
        ) as c:
            stats["successful"] = (await c.fetchone())["cnt"]

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE is_banned = 1"
        ) as c:
            stats["banned_users"] = (await c.fetchone())["cnt"]

        async with db.execute(
            "SELECT COUNT(*) as cnt FROM requests WHERE req_type = 'translate'"
        ) as c:
            stats["translate_requests"] = (await c.fetchone())["cnt"]

        return stats
