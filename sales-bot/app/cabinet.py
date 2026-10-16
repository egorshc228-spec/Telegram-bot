"""Личный кабинет клиента: профиль, календарь записей, ближайшие визиты, история, лояльность, отзывы.
Тексты на языке клиента (ru/uk/en) берутся из i18n."""
import calendar
import html
from datetime import date

from . import config
from .i18n import MONTHS, WEEKDAYS, WEEKDAYS2, niche_view, service_label, t
from .niches import NICHES

esc = html.escape

ACTIVE = ("new", "ok")


def calendar_text(year: int, month: int, marked: set, today: date | None = None, lang: str = "ru") -> str:
    """Месяц в виде сетки. [15] день с записью, (13) сегодня. Ширина 28 символов (влезает в экран телефона)."""
    lines = [f"{MONTHS[lang][month]} {year}".center(28), "".join(f" {n} " for n in WEEKDAYS2[lang])]
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        cells = []
        for d in week:
            if d == 0:
                cells.append("    ")
            elif d in marked:
                cells.append(f"[{d:2d}]")
            elif today and (today.year, today.month, today.day) == (year, month, d):
                cells.append(f"({d:2d})")
            else:
                cells.append(f" {d:2d} ")
        lines.append("".join(cells).rstrip())
    return "\n".join(lines)


def _d(l: dict) -> date:
    return date.fromisoformat(l["date"])


def render(user: dict | None, niche_key: str, leads: list, reviews: list, today: date, lang: str = "ru") -> str:
    n = niche_view(niche_key, lang)
    user = user or {}
    name, phone = user.get("name"), user.get("phone")

    out = [t(lang, "cab_title", company=esc(n.company)), ""]

    if name or phone:
        out.append(t(lang, "cab_profile", name=esc(name or t(lang, "cab_no_name")),
                     phone=esc(phone or t(lang, "cab_no_phone"))))
        out.append(t(lang, "cab_profile_note"))
    else:
        out.append(t(lang, "cab_profile_empty"))
    out.append("")

    active = [l for l in leads if l["status"] in ACTIVE]
    upcoming = sorted((l for l in active if _d(l) >= today), key=lambda l: (l["date"], l["time"]))
    past = [l for l in active if _d(l) < today]

    # календарь: текущий месяц и месяцы ближайших записей (до трёх)
    months = {(today.year, today.month)} | {(_d(l).year, _d(l).month) for l in upcoming}
    cal_blocks = []
    for y, m in sorted(months)[:3]:
        marked = {_d(l).day for l in upcoming if (_d(l).year, _d(l).month) == (y, m)}
        cal_blocks.append(calendar_text(y, m, marked, today, lang))
    out.append(t(lang, "cab_cal_h"))
    out.append("<pre>" + "\n\n".join(cal_blocks) + "</pre>")
    out.append(t(lang, "cab_cal_legend"))
    out.append("")

    if upcoming:
        out.append(t(lang, "cab_up_h"))
        for l in upcoming[:8]:
            d = _d(l)
            out.append(f"• {d.strftime('%d.%m')} ({WEEKDAYS[lang][d.weekday()]}) {l['time']} · "
                       f"{esc(service_label(niche_key, l['service'], lang))} · {l['price']} ₴\n"
                       f"   №{l['id']} · {t(lang, 'st_' + l['status']) if l['status'] in ('new', 'ok', 'no', 'cancel') else l['status']}")
        if len(upcoming) > 8:
            out.append(t(lang, "cab_more", n=len(upcoming) - 8))
    else:
        out.append(t(lang, "cab_up_none"))
    out.append("")

    visits = len(past)
    spent = sum(l["price"] or 0 for l in past)
    out.append(t(lang, "cab_hist_h"))
    out.append(t(lang, "cab_hist", visits=visits, spent=spent, reviews=len(reviews)))
    if config.LOYALTY_EVERY and config.LOYALTY_EVERY > 0:
        left = config.LOYALTY_EVERY - (visits % config.LOYALTY_EVERY)
        if left == config.LOYALTY_EVERY and visits > 0:
            out.append(t(lang, "cab_loyal_have", pct=config.LOYALTY_DISCOUNT))
        else:
            out.append(t(lang, "cab_loyal_left", pct=config.LOYALTY_DISCOUNT, left=left))
    unrated = [l for l in past if not any(r.get("lead_id") == l["id"] for r in reviews)]
    if unrated:
        out.append(t(lang, "cab_rate", id=unrated[-1]["id"]))
    out.append("")

    out.append(t(lang, "cab_todo"))
    return "\n".join(out)


def profile_text(user: dict | None, lang: str = "ru") -> str:
    user = user or {}
    return t(lang, "profile", name=esc(user.get("name") or t(lang, "not_set_name")),
             phone=esc(user.get("phone") or t(lang, "not_set_phone")))
