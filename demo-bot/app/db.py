import aiosqlite
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import DB_PATH, TIMEZONE


def today_str() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, username TEXT, niche TEXT,
                service TEXT, price INTEGER, date TEXT, time TEXT,
                name TEXT, phone TEXT, comment TEXT, source TEXT,
                status TEXT DEFAULT 'new', created TEXT);
            CREATE TABLE IF NOT EXISTS usage(
                user_id INTEGER, day TEXT, n INTEGER, PRIMARY KEY(user_id, day));
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY, username TEXT, first_seen TEXT);
            """
        )
        for col in ("external_id", "crm"):       # миграция для баз, созданных раньше
            try:
                await db.execute(f"ALTER TABLE leads ADD COLUMN {col} TEXT")
            except Exception:
                pass
        await db.commit()


async def touch_user(user_id: int, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users VALUES(?,?,?)",
            (user_id, username, datetime.now().isoformat(timespec="seconds")),
        )
        await db.commit()


async def add_lead(user_id, username, niche, service, price, date, time,
                   name, phone, comment="", source="кнопки", external_id="", crm="") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO leads(user_id,username,niche,service,price,date,time,name,phone,comment,source,created,"
            "external_id,crm) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, username, niche, service, price, date, time, name, phone, comment, source,
             datetime.now().isoformat(timespec="seconds"), external_id, crm),
        )
        await db.commit()
        return cur.lastrowid


async def _rows(sql, args=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, args)
        return [dict(r) for r in await cur.fetchall()]


async def get_lead(lead_id: int):
    r = await _rows("SELECT * FROM leads WHERE id=?", (lead_id,))
    return r[0] if r else None


async def last_lead(user_id: int, niche: str):
    r = await _rows("SELECT * FROM leads WHERE user_id=? AND niche=? ORDER BY id DESC LIMIT 1",
                    (user_id, niche))
    return r[0] if r else None


async def leads_for(user_id: int, niche: str | None = None):
    if niche:
        return await _rows("SELECT * FROM leads WHERE user_id=? AND niche=? ORDER BY id", (user_id, niche))
    return await _rows("SELECT * FROM leads WHERE user_id=? ORDER BY id", (user_id,))


async def all_leads():
    return await _rows("SELECT * FROM leads ORDER BY id")


async def set_status(lead_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
        await db.commit()


async def hit(user_id: int, user_limit: int, global_limit: int) -> str:
    """Учёт сообщений ИИ. Возвращает 'ok', 'user_limit' или 'global_limit'."""
    day = today_str()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COALESCE(SUM(n),0) FROM usage WHERE day=?", (day,))
        total = (await cur.fetchone())[0]
        if total >= global_limit:
            return "global_limit"
        cur = await db.execute("SELECT n FROM usage WHERE user_id=? AND day=?", (user_id, day))
        row = await cur.fetchone()
        if row and row[0] >= user_limit:
            return "user_limit"
        await db.execute(
            "INSERT INTO usage VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET n=n+1",
            (user_id, day),
        )
        await db.commit()
        return "ok"


async def stats() -> dict:
    users = (await _rows("SELECT COUNT(*) c FROM users"))[0]["c"]
    leads = (await _rows("SELECT COUNT(*) c FROM leads"))[0]["c"]
    ai = (await _rows("SELECT COALESCE(SUM(n),0) c FROM usage WHERE day=?", (today_str(),)))[0]["c"]
    return {"users": users, "leads": leads, "ai_today": ai}
