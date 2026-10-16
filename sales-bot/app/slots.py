"""Окна для звонков с Даниилом: рабочие дни и часы минус уже занятые звонки и занятость Google Calendar."""
from datetime import date, datetime, time, timedelta

from . import config, db, gcal

TZ = db.TZ


def work_days() -> set[int]:
    out = {int(x) for x in config.SALES_DAYS.replace(" ", "").split(",") if x.isdigit() and 1 <= int(x) <= 7}
    return out or {1, 2, 3, 4, 5}


def hours(spec: str | None = None) -> tuple[time, time]:
    try:
        a, b = (spec or config.SALES_HOURS).split("-")
        return time.fromisoformat(a.strip()), time.fromisoformat(b.strip())
    except ValueError:
        return time(10), time(19)


async def free(at: datetime | None = None) -> dict[date, list[datetime]]:
    """{день: [время, ...]} на SALES_DAYS_AHEAD дней вперёд, только непустые дни."""
    at = at or db.now()
    taken = await db.taken_slots()
    start_t, end_t = hours()
    step = timedelta(minutes=config.SALES_SLOT_MIN)
    dur = timedelta(minutes=config.CALL_MIN)
    earliest = at + timedelta(hours=config.SALES_MIN_LEAD_HOURS)
    horizon = at + timedelta(days=config.SALES_DAYS_AHEAD + 1)
    busy = await gcal.busy(at, horizon)
    out: dict[date, list[datetime]] = {}
    for i in range(config.SALES_DAYS_AHEAD + 1):
        d = at.date() + timedelta(days=i)
        if d.isoweekday() not in work_days():
            continue
        t = datetime.combine(d, start_t, TZ)
        end = datetime.combine(d, end_t, TZ)
        while t + step <= end:
            clash = any(b0 < t + dur and t < b1 for b0, b1 in busy)
            if t >= earliest and db.iso(t) not in taken and not clash:
                out.setdefault(d, []).append(t)
            t += step
    return out


async def is_free(at: datetime) -> bool:
    return at in (await free()).get(at.date(), [])


def stamp(at: datetime) -> str:
    return f"{at:%Y%m%d%H%M}"


def parse_stamp(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d%H%M").replace(tzinfo=TZ)


def parse_any(s: str) -> datetime | None:
    """«2026-10-16T10:30» или «2026-10-16 10:30» от ИИ → время по Киеву."""
    s = (s or "").strip().replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def in_contact_hours(dt: datetime) -> bool:
    a, b = hours(config.CONTACT_HOURS)
    return a <= dt.timetz().replace(tzinfo=None) < b


def next_contact_time(dt: datetime) -> datetime:
    """Ближайший момент, когда можно писать/звонить человеку (CONTACT_HOURS, любой день)."""
    a, b = hours(config.CONTACT_HOURS)
    if in_contact_hours(dt):
        return dt
    day = dt.date() if dt.timetz().replace(tzinfo=None) < a else dt.date() + timedelta(days=1)
    return datetime.combine(day, a, TZ)
