"""Данные воронки: посетители демо (prospects), записи на звонок (calls), свободные окна и расписание фоллоу-апов.

Хранится в той же SQLite, что и заявки демо. Таблицы создаются при старте (init), старые базы не трогаются."""
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import aiosqlite

from . import config
from .config import DB_PATH

TZ = ZoneInfo(config.TIMEZONE)

PROSPECT_COLS = {
    "source": "TEXT", "cid": "TEXT", "started": "TEXT", "last_active": "TEXT", "stage": "TEXT",
    "biz": "TEXT", "biz_text": "TEXT", "volume": "TEXT", "avg_check": "TEXT", "handler": "TEXT",
    "calc": "TEXT", "demo_msgs": "INTEGER DEFAULT 0", "demo_booked": "INTEGER DEFAULT 0",
    "nudged": "INTEGER DEFAULT 0", "owner_seen": "INTEGER DEFAULT 0", "pitch_seen": "INTEGER DEFAULT -1",
    "slots_seen": "INTEGER DEFAULT 0", "want_bot": "INTEGER DEFAULT 0", "fu_step": "INTEGER DEFAULT 0",
    "fu_next": "TEXT", "opted_out": "INTEGER DEFAULT 0", "call_id": "INTEGER",
}

STAGES = ["start", "niche", "demo", "owner", "pitch", "qualify", "slots", "booked"]


def now() -> datetime:
    return datetime.now(TZ)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


_ready = False


async def init():
    global _ready
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS prospects(user_id INTEGER PRIMARY KEY)")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,"
            " name TEXT, at TEXT, format TEXT, phone TEXT, status TEXT DEFAULT 'booked', created TEXT,"
            " reminded INTEGER DEFAULT 0)")
        for col, typ in PROSPECT_COLS.items():
            try:
                await db.execute(f"ALTER TABLE prospects ADD COLUMN {col} {typ}")
            except Exception:
                pass
        await db.commit()
    _ready = True


async def _rows(sql, args=()):
    if not _ready:                                  # таблицы создаются и без явного init (тесты, старые запуски)
        await init()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, args)
        return [dict(r) for r in await cur.fetchall()]


async def _exec(sql, args=()):
    if not _ready:
        await init()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, args)
        await db.commit()
        return cur.lastrowid


# ---------------------------------------------------------------- посетители

def parse_payload(payload: str | None) -> tuple[str, str]:
    """Метка из ссылки t.me/CladchatBot?start=<источник>_<ga-client-id>.
    Пример: ai_123456789-1700000000 → ('ai', '123456789.1700000000'). Без метки → ('direct', '')."""
    p = (payload or "").strip()
    if not p:
        return "direct", ""
    m = re.fullmatch(r"([A-Za-z0-9-]{1,30})(?:_(\d{4,12})-(\d{6,12}))?", p)
    if not m:
        return re.sub(r"[^A-Za-z0-9_-]", "", p)[:30] or "direct", ""
    cid = f"{m.group(2)}.{m.group(3)}" if m.group(2) else ""
    return m.group(1), cid


async def get(user_id: int) -> dict | None:
    r = await _rows("SELECT * FROM prospects WHERE user_id=?", (user_id,))
    return r[0] if r else None


async def start(user_id: int, source: str, cid: str) -> dict:
    """Новый вход в воронку (или повторный /start). Источник не затираем, если новый вход без метки."""
    p = await get(user_id)
    t = _iso(now())
    if not p:
        await _exec("INSERT INTO prospects(user_id, source, cid, started, last_active, stage) VALUES(?,?,?,?,?,?)",
                    (user_id, source, cid, t, t, "start"))
    else:
        if source != "direct" or not p.get("source"):
            await _exec("UPDATE prospects SET source=? WHERE user_id=?", (source, user_id))
        if cid:
            await _exec("UPDATE prospects SET cid=? WHERE user_id=?", (cid, user_id))
    await touch(user_id)
    return await get(user_id)


async def update(user_id: int, **fields):
    if not fields:
        return
    bad = set(fields) - set(PROSPECT_COLS)
    if bad:
        raise ValueError(f"unknown prospect fields: {bad}")
    sets = ", ".join(f"{k}=?" for k in fields)
    await _exec(f"UPDATE prospects SET {sets} WHERE user_id=?", (*fields.values(), user_id))


async def advance(user_id: int, stage: str):
    """Стадия только растёт (повторный показ шага не откатывает человека назад)."""
    p = await get(user_id)
    if not p:
        return
    cur = p.get("stage") or "start"
    if STAGES.index(stage) > (STAGES.index(cur) if cur in STAGES else 0):
        await update(user_id, stage=stage)


async def bump(user_id: int, col: str, by: int = 1) -> int:
    if col not in PROSPECT_COLS:
        raise ValueError(col)
    await _exec(f"UPDATE prospects SET {col}=COALESCE({col},0)+? WHERE user_id=?", (by, user_id))
    p = await get(user_id)
    return (p or {}).get(col) or 0


async def touch(user_id: int):
    """Активность посетителя: сдвигает следующий фоллоу-ап от последнего действия."""
    p = await get(user_id)
    if not p:
        return
    t = now()
    nxt = next_followup(t, p.get("fu_step") or 0)
    await update(user_id, last_active=_iso(t), fu_next=_iso(nxt))


# ---------------------------------------------------------------- фоллоу-апы

def delays() -> list[timedelta]:
    out = []
    for part in config.FOLLOWUP_DELAYS.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", part)
        if m:
            n, u = int(m.group(1)), m.group(2)
            out.append(timedelta(minutes=n) if u == "m" else timedelta(hours=n) if u == "h" else timedelta(days=n))
    return out


def window() -> tuple[int, int]:
    try:
        a, b = (int(x) for x in config.FOLLOWUP_WINDOW.split("-"))
        return a, b
    except ValueError:
        return 10, 20


def in_window(dt: datetime) -> datetime:
    """Переносит отправку в окно (по умолчанию 10:00–20:00 по Киеву): ночью не пишем."""
    a, b = window()
    dt = dt.astimezone(TZ)
    if dt.hour < a:
        return dt.replace(hour=a, minute=0, second=0, microsecond=0)
    if dt.hour >= b:
        return (dt + timedelta(days=1)).replace(hour=a, minute=0, second=0, microsecond=0)
    return dt


def next_followup(last_active: datetime, step: int) -> datetime | None:
    d = delays()
    if step >= len(d):
        return None
    return in_window(last_active + d[step])


async def due_followups(at: datetime | None = None) -> list[dict]:
    at = at or now()
    rows = await _rows("SELECT * FROM prospects WHERE COALESCE(opted_out,0)=0 AND call_id IS NULL "
                       "AND fu_next IS NOT NULL AND stage IS NOT NULL")
    return [r for r in rows if datetime.fromisoformat(r["fu_next"]) <= at and (r["fu_step"] or 0) < len(delays())]


async def mark_followup_sent(user_id: int):
    p = await get(user_id)
    step = (p.get("fu_step") or 0) + 1
    last = datetime.fromisoformat(p["last_active"]) if p.get("last_active") else now()
    nxt = next_followup(last, step)
    if nxt and nxt <= now():                    # если человек давно молчит, следующий — не раньше чем через сутки
        nxt = in_window(now() + timedelta(days=1))
    await update(user_id, fu_step=step, fu_next=_iso(nxt))


# ---------------------------------------------------------------- окна для звонков

def _work_days() -> set[int]:
    out = set()
    for x in config.SALES_DAYS.split(","):
        x = x.strip()
        if x.isdigit() and 1 <= int(x) <= 7:
            out.add(int(x))
    return out or {1, 2, 3, 4, 5}


def _hours() -> tuple[time, time]:
    try:
        a, b = config.SALES_HOURS.split("-")
        return time.fromisoformat(a.strip()), time.fromisoformat(b.strip())
    except ValueError:
        return time(10), time(19)


async def taken() -> set[str]:
    rows = await _rows("SELECT at FROM calls WHERE status IN ('booked','confirmed')")
    return {r["at"] for r in rows}


async def free_slots(at: datetime | None = None) -> dict[date, list[datetime]]:
    """Свободные окна на ближайшие SALES_DAYS_AHEAD дней: {день: [время, ...]}, только непустые дни."""
    at = at or now()
    busy = await taken()
    start_t, end_t = _hours()
    step = timedelta(minutes=config.SALES_SLOT_MIN)
    earliest = at + timedelta(hours=config.SALES_MIN_LEAD_HOURS)
    out: dict[date, list[datetime]] = {}
    for i in range(config.SALES_DAYS_AHEAD + 1):
        d = at.date() + timedelta(days=i)
        if d.isoweekday() not in _work_days():
            continue
        t = datetime.combine(d, start_t, TZ)
        end = datetime.combine(d, end_t, TZ)
        while t + step <= end:
            if t >= earliest and _iso(t) not in busy:
                out.setdefault(d, []).append(t)
            t += step
    return out


async def book_call(user_id: int, username: str | None, name: str, at: datetime, fmt: str, phone: str = "") -> int:
    """Создаёт запись на звонок, если окно ещё свободно. Иначе ValueError('taken')."""
    if _iso(at) in await taken():
        raise ValueError("taken")
    reminded = 1 if at - now() <= timedelta(hours=2) else 0
    cid = await _exec("INSERT INTO calls(user_id, username, name, at, format, phone, status, created, reminded) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (user_id, username, name, _iso(at), fmt, phone, "booked", _iso(now()), reminded))
    await update(user_id, call_id=cid, stage="booked", fu_next=None)
    return cid


async def get_call(call_id: int) -> dict | None:
    r = await _rows("SELECT * FROM calls WHERE id=?", (call_id,))
    return r[0] if r else None


async def active_call(user_id: int) -> dict | None:
    r = await _rows("SELECT * FROM calls WHERE user_id=? AND status IN ('booked','confirmed') AND at>=? "
                    "ORDER BY at LIMIT 1", (user_id, _iso(now() - timedelta(hours=1))))
    return r[0] if r else None


async def set_call_status(call_id: int, status: str):
    await _exec("UPDATE calls SET status=? WHERE id=?", (status, call_id))
    c = await get_call(call_id)
    if c and status in ("cancelled", "resched"):     # звонка больше нет: человек снова в воронке
        await update(c["user_id"], call_id=None)


async def due_call_reminders(at: datetime | None = None) -> list[dict]:
    at = at or now()
    rows = await _rows("SELECT * FROM calls WHERE status IN ('booked','confirmed') AND COALESCE(reminded,0)=0")
    out = []
    for c in rows:
        left = datetime.fromisoformat(c["at"]) - at
        if timedelta(0) < left <= timedelta(hours=2):
            out.append(c)
    return out


async def mark_call_reminded(call_id: int):
    await _exec("UPDATE calls SET reminded=1 WHERE id=?", (call_id,))


# ---------------------------------------------------------------- статистика

async def funnel_stats(days: int = 30) -> dict:
    since = _iso(now() - timedelta(days=days))
    rows = await _rows("SELECT * FROM prospects WHERE started>=?", (since,))
    calls = await _rows("SELECT * FROM calls WHERE created>=?", (since,))
    by_source: dict[str, dict] = {}
    for r in rows:
        s = by_source.setdefault(r.get("source") or "direct", {"start": 0, "booked": 0})
        s["start"] += 1
        if r.get("stage") == "booked" or r.get("call_id"):
            s["booked"] += 1

    def reached(stage: str) -> int:
        i = STAGES.index(stage)
        return sum(1 for r in rows if (r.get("stage") in STAGES and STAGES.index(r["stage"]) >= i))

    return {
        "days": days, "total": len(rows),
        "stages": {s: reached(s) for s in STAGES},
        "demo_booked": sum(1 for r in rows if r.get("demo_booked")),
        "want_bot": sum(1 for r in rows if r.get("want_bot")),
        "opted_out": sum(1 for r in rows if r.get("opted_out") == 1),
        "blocked": sum(1 for r in rows if r.get("opted_out") == 2),
        "calls": len(calls), "calls_cancelled": sum(1 for c in calls if c["status"] == "cancelled"),
        "by_source": by_source,
    }
