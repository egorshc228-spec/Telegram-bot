import aiosqlite
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import DB_PATH, TIMEZONE


def now_tz() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def lead_dt(l: dict) -> datetime | None:
    """Дата и время визита в часовом поясе компании."""
    try:
        return datetime.fromisoformat(f"{l['date']}T{l['time']}").replace(tzinfo=ZoneInfo(TIMEZONE))
    except (ValueError, KeyError, TypeError):
        return None


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
            CREATE TABLE IF NOT EXISTS reviews(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, username TEXT, niche TEXT, lead_id INTEGER,
                rating INTEGER, text TEXT, created TEXT);
            """
        )
        for table, col in (("leads", "external_id"), ("leads", "crm"),      # миграция баз, созданных раньше
                           ("users", "niche"), ("users", "name"), ("users", "phone"),
                           ("users", "lang"), ("users", "tg_lang")):
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
            except Exception:
                pass
        for col in ("rem24", "rem2"):                                        # флаги «напоминание уже отправлено»
            try:
                await db.execute(f"ALTER TABLE leads ADD COLUMN {col} INTEGER DEFAULT 0")
            except Exception:
                pass
        await db.commit()


async def touch_user(user_id: int, username: str | None, tg_lang: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id, username, first_seen) VALUES(?,?,?)",
            (user_id, username, datetime.now().isoformat(timespec="seconds")),
        )
        await db.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
        if tg_lang:
            await db.execute("UPDATE users SET tg_lang=? WHERE user_id=?", (tg_lang, user_id))
        await db.commit()


async def get_user(user_id: int):
    r = await _rows("SELECT * FROM users WHERE user_id=?", (user_id,))
    return r[0] if r else None


async def set_niche(user_id: int, niche: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET niche=? WHERE user_id=?", (niche, user_id))
        await db.commit()


async def set_lang(user_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))
        await db.commit()


async def set_profile(user_id: int, name: str | None = None, phone: str | None = None):
    """Сохраняет только переданные поля профиля (имя и телефон клиента)."""
    async with aiosqlite.connect(DB_PATH) as db:
        if name:
            await db.execute("UPDATE users SET name=? WHERE user_id=?", (name, user_id))
        if phone:
            await db.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))
        await db.commit()


async def add_lead(user_id, username, niche, service, price, date, time,
                   name, phone, comment="", source="кнопки", external_id="", crm="") -> int:
    # если до визита меньше 25 ч / 3 ч, соответствующее напоминание не нужно (клиент только что записался)
    rem24 = rem2 = 0
    when = lead_dt({"date": date, "time": time})
    if when:
        left = when - now_tz()
        rem24 = 1 if left < timedelta(hours=25) else 0
        rem2 = 1 if left < timedelta(hours=3) else 0
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO leads(user_id,username,niche,service,price,date,time,name,phone,comment,source,created,"
            "external_id,crm,rem24,rem2) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, username, niche, service, price, date, time, name, phone, comment, source,
             datetime.now().isoformat(timespec="seconds"), external_id, crm, rem24, rem2),
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


async def due_reminders(now: datetime | None = None) -> list:
    """Список (запись, '24h'|'2h') для отправки. За 2 часа важнее, чем за сутки: обе сразу не шлём."""
    now = now or now_tz()
    rows = await _rows("SELECT * FROM leads WHERE status IN ('new','ok') AND (COALESCE(rem24,0)=0 OR COALESCE(rem2,0)=0) "
                       "AND date >= ? ORDER BY id", ((now - timedelta(days=1)).date().isoformat(),))
    out = []
    for l in rows:
        when = lead_dt(l)
        if not when:
            continue
        left = when - now
        if left <= timedelta(0):
            continue
        if not l.get("rem2") and left <= timedelta(hours=2):
            out.append((l, "2h"))
        elif not l.get("rem24") and left <= timedelta(hours=24) and left > timedelta(hours=2):
            out.append((l, "24h"))
    return out


async def mark_reminded(lead_id: int, kind: str):
    async with aiosqlite.connect(DB_PATH) as db:
        if kind == "2h":
            await db.execute("UPDATE leads SET rem2=1, rem24=1 WHERE id=?", (lead_id,))
        else:
            await db.execute("UPDATE leads SET rem24=1 WHERE id=?", (lead_id,))
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
    return {"users": users, "leads": leads, "ai_today": ai, "reviews": await review_stats()}


async def add_review(user_id, username, niche, rating, text, lead_id=None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO reviews(user_id,username,niche,lead_id,rating,text,created) VALUES(?,?,?,?,?,?,?)",
            (user_id, username, niche, lead_id, rating, text,
             datetime.now().isoformat(timespec="seconds")),
        )
        await db.commit()
        return cur.lastrowid


async def reviews_list(limit: int = 10, niche: str | None = None):
    if niche:
        return await _rows("SELECT * FROM reviews WHERE niche=? ORDER BY id DESC LIMIT ?", (niche, limit))
    return await _rows("SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (limit,))


async def user_reviews(user_id: int, niche: str):
    return await _rows("SELECT * FROM reviews WHERE user_id=? AND niche=? ORDER BY id DESC", (user_id, niche))


async def review_stats(niche: str | None = None) -> dict:
    where, args = ("WHERE niche=?", (niche,)) if niche else ("", ())
    r = (await _rows(f"SELECT COUNT(*) c, AVG(rating) a FROM reviews {where}", args))[0]
    return {"count": r["c"], "avg": round(r["a"], 2) if r["a"] else None}
