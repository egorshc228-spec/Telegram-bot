"""Автоматика касаний: кто не открыл Telegram/WhatsApp сам — шаблон в WhatsApp; нет ответа — карточка
«позвонить вручную»; общался, но не записался — одно напоминание; за 2 часа до звонка — напоминание."""
import asyncio
import logging
from datetime import datetime, timedelta

from . import config, core, db, slots, wa
from .texts import FMT_RU, fmt_label, t, when

log = logging.getLogger("scheduler")


async def need_call(lead: dict, reason: str):
    await db.update_lead(lead["id"], stage="need_call", next_at=None)
    phone = lead.get("phone") or lead.get("contact") or "—"
    await core.note(lead, f"☎️ <b>Позвонить вручную</b>: {reason}\n📱 {phone}",
                    [[("🙋 Беру сам", f"g:take:{lead['id']}"), ("🚫 Не целевой", f"g:lost:{lead['id']}")]])


async def first_touch(lead: dict, at: datetime):
    """Человек не открыл Telegram/WhatsApp сам за TG_WAIT_MIN минут."""
    if not slots.in_contact_hours(at):
        return await db.update_lead(lead["id"], next_at=db.iso(slots.next_contact_time(at)))
    if not (config.wa_enabled() and lead.get("wa_id")):
        why = "нет телефона в заявке" if not lead.get("phone") else "WhatsApp-канал не подключён"
        return await need_call(lead, f"не открыл Telegram/WhatsApp сам, {why}")
    lang = core.lead_lang(lead)
    code = config.WA_TEMPLATE_LANGS.get(lang) or config.WA_TEMPLATE_LANGS.get("uk", "uk")
    try:
        await wa.send_template(lead["wa_id"], config.WA_TEMPLATE, code, [lead.get("name") or ""])
    except wa.WAError as e:
        log.warning("шаблон лиду %s не отправлен: %s", lead["id"], e)
        return await need_call(lead, f"WhatsApp не отправлен ({str(e)[:120]})")
    await db.log(lead["id"], "out", "wa", "[WhatsApp-шаблон: вы оставили заявку на сайте, когда удобно созвониться?]")
    await db.update_lead(lead["id"], stage="wa_sent", channel="wa",
                         next_at=db.iso(at + timedelta(minutes=config.NO_REPLY_MIN)))
    await core.note(lead, "💬 Отправлено первое сообщение в WhatsApp, ждём ответ", silent=True)


async def nudge(lead: dict, at: datetime):
    if await db.active_call(lead["id"]) or lead.get("nudged"):
        return await db.update_lead(lead["id"], next_at=None)
    if not slots.in_contact_hours(at):
        return await db.update_lead(lead["id"], next_at=db.iso(slots.next_contact_time(at)))
    await db.update_lead(lead["id"], nudged=1, next_at=None)
    await core.show_days(lead, t(core.lead_lang(lead), "nudge"))


async def remind(c: dict):
    await db.set_call(c["id"], reminded=1)
    lead = await db.get_lead(c["lead_id"])
    if not lead:
        return
    lang = core.lead_lang(lead)
    at = datetime.fromisoformat(c["at"])
    link = f"\n🔗 {config.MEET_URL}" if c["format"] == "meet" and config.MEET_URL else ""
    ok = await core.send(lead, t(lang, "reminder", when=when(at, lang), fmt=fmt_label(lang, c["format"]), link=link),
                         core.call_rows(lead, c["id"]))
    if not ok and lead.get("channel") == "wa" and config.WA_REMINDER_TEMPLATE and lead.get("wa_id"):
        code = config.WA_TEMPLATE_LANGS.get(lang) or "uk"
        try:
            await wa.send_template(lead["wa_id"], config.WA_REMINDER_TEMPLATE, code,
                                   [lead.get("name") or "", when(at, lang)])
            ok = True
        except wa.WAError:
            log.warning("напоминание-шаблон лиду %s не отправлено", lead["id"], exc_info=True)
    phone = c.get("phone") or lead.get("phone") or lead.get("contact") or ""
    await core.note(lead, f"⏰ Скоро звонок: <b>{when(at, 'ru')}</b>, {FMT_RU.get(c['format'], c['format'])} · {phone}"
                          + ("" if ok else "\n⚠️ Напоминание клиенту не доставлено (окно WhatsApp закрыто)"))


async def run_once(at: datetime | None = None) -> dict:
    at = at or db.now()
    done = {"touched": 0, "reminders": 0}
    if config.AUTOMATION:
        for lead in await db.due_leads(at):
            try:
                st = lead.get("stage")
                if st == "new" and lead.get("source") == "site" and not lead.get("channel"):
                    await first_touch(lead, at)
                elif st == "wa_sent":
                    await need_call(lead, f"нет ответа в WhatsApp {config.NO_REPLY_MIN} мин")
                elif st == "talking":
                    await nudge(lead, at)
                else:
                    await db.update_lead(lead["id"], next_at=None)
                done["touched"] += 1
            except Exception:
                log.exception("автоматика по лиду %s", lead["id"])
    for c in await db.due_reminders(at):
        try:
            await remind(c)
            done["reminders"] += 1
        except Exception:
            log.exception("напоминание о звонке %s", c["id"])
    return done


async def loop():
    log.info("Автоматика: %s, проверка раз в %s с", "вкл" if config.AUTOMATION else "выкл", config.CHECK_SECONDS)
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ошибка цикла автоматики")
        await asyncio.sleep(config.CHECK_SECONDS)
