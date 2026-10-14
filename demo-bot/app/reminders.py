"""Напоминания клиентам о записи: за сутки и за 2 часа до визита, на языке клиента.

Фоновый цикл раз в REMINDER_CHECK_SECONDS смотрит базу. Отметка «отправлено» ставится ДО отправки,
поэтому одно напоминание не уйдёт дважды, даже если бот перезапустится или клиент заблокировал бота."""
import asyncio
import html
import logging
from datetime import date, datetime

from . import config, db, i18n
from .niches import NICHES

log = logging.getLogger("reminders")
esc = html.escape


def reminder_text(lead: dict, kind: str, lang: str) -> str:
    key = "remind_2h" if kind == "2h" else "remind_24h"
    niche = lead["niche"] if lead["niche"] in NICHES else next(iter(NICHES))
    n = i18n.niche_view(niche, lang)
    d = date.fromisoformat(lead["date"])
    return i18n.t(lang, key, company=esc(n.company), service=esc(i18n.service_label(niche, lead["service"], lang)),
                  date=d.strftime("%d.%m"), wd=i18n.WEEKDAYS[lang][d.weekday()], time=lead["time"],
                  address=esc(n.address), id=lead["id"])


async def run_once(bot, now: datetime | None = None) -> int:
    """Отправляет все созревшие напоминания. Возвращает, сколько отправлено."""
    sent = 0
    for lead, kind in await db.due_reminders(now):
        await db.mark_reminded(lead["id"], kind)
        lang = i18n.resolve(await db.get_user(lead["user_id"]))
        try:
            await bot.send_message(lead["user_id"], reminder_text(lead, kind, lang))
            sent += 1
        except Exception:
            log.warning("не удалось отправить напоминание по записи №%s", lead["id"], exc_info=True)
    return sent


async def loop(bot, interval: int | None = None):
    interval = interval or config.REMINDER_CHECK_SECONDS
    log.info("Напоминания включены, проверка раз в %s с", interval)
    while True:
        try:
            await run_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ошибка цикла напоминаний")
        await asyncio.sleep(interval)
