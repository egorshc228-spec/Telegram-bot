"""SQLite: лиды, переписка, звонки. Таблицы и новые колонки создаются при старте, старые данные не трогаются."""
import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite

from . import config

TZ = ZoneInfo(config.TIMEZONE)

LEAD_COLS = {
    "token": "TEXT", "created": "TEXT", "source": "TEXT", "page": "TEXT", "lang": "TEXT",
    "name": "TEXT", "contact": "TEXT", "phone": "TEXT", "tg_username": "TEXT",
    "service": "TEXT", "niche": "TEXT", "site": "TEXT", "budget": "TEXT", "pain": "TEXT", "term": "TEXT",
    "calc": "TEXT", "attribution": "TEXT", "cid": "TEXT",
    # stage: new → (wa_sent) → talking → booked; либо need_call / taken (взял человек) / lost / opted_out
    "stage": "TEXT DEFAULT 'new'", "channel": "TEXT", "tg_id": "INTEGER", "wa_id": "TEXT",
    "next_at": "TEXT", "last_in": "TEXT", "last_out": "TEXT", "nudged": "INTEGER DEFAULT 0",
    "card_id": "INTEGER", "assignee": "TEXT", "call_id": "INTEGER", "biz": "TEXT", "request": "TEXT",
    "ai_day": "TEXT", "ai_count": "INTEGER DEFAULT 0", "pending": "TEXT",
}
CALL_COLS = {
    "lead_id": "INTEGER", "at": "TEXT", "format": "TEXT", "phone": "TEXT", "status": "TEXT DEFAULT 'booked'",
    "created": "TEXT", "reminded": "INTEGER DEFAULT 0", "event_id": "TEXT",
}
ACTIVE_CALL = ("booked", "confirmed")
_ready = False


def now() -> datetime:
    return datetime.now(TZ)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


async def init():
    global _ready
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY AUTOINCREMENT)")
        await db.execute("CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY AUTOINCREMENT)")
        await db.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER,"
                         " ts TEXT, dir TEXT, channel TEXT, text TEXT)")
        for table, cols in (("leads", LEAD_COLS), ("calls", CALL_COLS)):
            for col, typ in cols.items():
                try:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                except Exception:
                    pass
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS leads_token ON leads(token)")
        await db.commit()
    _ready = True


async def rows(sql, args=()) -> list[dict]:
    if not _ready:
        await init()
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, args)
        return [dict(r) for r in await cur.fetchall()]


async def one(sql, args=()) -> dict | None:
    r = await rows(sql, args)
    return r[0] if r else None


async def exec_(sql, args=()) -> int:
    if not _ready:
        await init()
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(sql, args)
        await db.commit()
        return cur.lastrowid


# ---------------------------------------------------------------- лиды

async def create_lead(**fields) -> dict:
    fields = {k: v for k, v in fields.items() if k in LEAD_COLS}
    if isinstance(fields.get("attribution"), dict):
        fields["attribution"] = json.dumps(fields["attribution"], ensure_ascii=False)
    fields.setdefault("token", secrets.token_urlsafe(6).replace("-", "x").replace("_", "y").lower())
    fields.setdefault("created", iso(now()))
    fields.setdefault("stage", "new")
    cols = ", ".join(fields)
    lid = await exec_(f"INSERT INTO leads({cols}) VALUES({', '.join('?' * len(fields))})", tuple(fields.values()))
    return await get_lead(lid)


async def get_lead(lead_id: int) -> dict | None:
    return await one("SELECT * FROM leads WHERE id=?", (lead_id,))


async def lead_by_token(token: str) -> dict | None:
    return await one("SELECT * FROM leads WHERE token=?", ((token or "").lower(),))


async def lead_by_tg(tg_id: int) -> dict | None:
    return await one("SELECT * FROM leads WHERE tg_id=? ORDER BY id DESC LIMIT 1", (tg_id,))


async def lead_by_wa(wa_id: str) -> dict | None:
    return await one("SELECT * FROM leads WHERE wa_id=? ORDER BY id DESC LIMIT 1", (wa_id,))


async def lead_by_phone(phone: str) -> dict | None:
    return await one("SELECT * FROM leads WHERE phone=? ORDER BY id DESC LIMIT 1", (phone,))


async def update_lead(lead_id: int, **fields):
    fields = {k: v for k, v in fields.items() if k in LEAD_COLS}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    await exec_(f"UPDATE leads SET {sets} WHERE id=?", (*fields.values(), lead_id))


async def due_leads(at: datetime) -> list[dict]:
    return await rows("SELECT * FROM leads WHERE next_at IS NOT NULL AND next_at<=?", (iso(at),))


async def ai_hit(lead: dict) -> bool:
    """Считает ответы ИИ лиду за сутки. False — лимит исчерпан (защита от бесконечной переписки и спама)."""
    today = now().date().isoformat()
    n = (lead.get("ai_count") or 0) + 1 if lead.get("ai_day") == today else 1
    await update_lead(lead["id"], ai_day=today, ai_count=n)
    return n <= config.AI_DAILY_LIMIT


# ---------------------------------------------------------------- переписка

async def log(lead_id: int, direction: str, channel: str, text: str):
    await exec_("INSERT INTO messages(lead_id, ts, dir, channel, text) VALUES(?,?,?,?,?)",
                (lead_id, iso(now()), direction, channel, (text or "")[:2000]))
    col = {"in": "last_in", "out": "last_out"}.get(direction)
    if col:
        await update_lead(lead_id, **{col: iso(now())})


async def history(lead_id: int, n: int = 16) -> list[dict]:
    r = await rows("SELECT * FROM messages WHERE lead_id=? AND dir IN ('in','out') ORDER BY id DESC LIMIT ?",
                   (lead_id, n))
    return list(reversed(r))


# ---------------------------------------------------------------- звонки

async def add_call(lead_id: int, at: datetime, fmt: str, phone: str = "", event_id: str = "") -> int:
    reminded = 1 if (at - now()).total_seconds() <= 2 * 3600 else 0
    return await exec_("INSERT INTO calls(lead_id, at, format, phone, status, created, reminded, event_id)"
                       " VALUES(?,?,?,?,?,?,?,?)", (lead_id, iso(at), fmt, phone, "booked", iso(now()), reminded,
                                                     event_id))


async def get_call(call_id: int) -> dict | None:
    return await one("SELECT * FROM calls WHERE id=?", (call_id,))


async def active_call(lead_id: int) -> dict | None:
    return await one("SELECT * FROM calls WHERE lead_id=? AND status IN ('booked','confirmed') AND at>=? "
                     "ORDER BY at LIMIT 1", (lead_id, iso(now())))


async def set_call(call_id: int, **fields):
    fields = {k: v for k, v in fields.items() if k in CALL_COLS}
    sets = ", ".join(f"{k}=?" for k in fields)
    await exec_(f"UPDATE calls SET {sets} WHERE id=?", (*fields.values(), call_id))


async def taken_slots() -> set[str]:
    return {r["at"] for r in await rows("SELECT at FROM calls WHERE status IN ('booked','confirmed')")}


async def due_reminders(at: datetime) -> list[dict]:
    out = []
    for c in await rows("SELECT * FROM calls WHERE status IN ('booked','confirmed') AND COALESCE(reminded,0)=0"):
        left = (datetime.fromisoformat(c["at"]) - at).total_seconds()
        if 0 < left <= 2 * 3600:
            out.append(c)
    return out
