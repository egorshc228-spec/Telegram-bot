"""Ядро: лиды, выбор времени, запись на звонок, карточки в группе. Не зависит от канала:
отправка идёт через send() — в Telegram инлайн-кнопками, в WhatsApp кнопками или списком.

ID кнопок одинаковые в обоих каналах:
  days · d:YYYYMMDD (день) · s:YYYYMMDDHHMM (время) · f:<формат>:YYYYMMDDHHMM · re:<call> · x:<call>"""
import html
import json
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import agent, analytics, config, db, gcal, slots, wa
from .texts import FMT_RU, day_label, fmt_label, guess_lang, norm_lang, t, when

log = logging.getLogger("core")
esc = html.escape
bot: Bot | None = None                 # задаётся в main.py (и в тестах)
bot_username = ""                      # @username бота продаж для ссылок t.me


# ================================================================ отправка лиду

def kb(rows) -> InlineKeyboardMarkup | None:
    if not rows:
        return None
    out = []
    for row in rows:
        out.append([InlineKeyboardButton(text=b[0], url=b[1][4:]) if b[1].startswith("url:")
                    else InlineKeyboardButton(text=b[0], callback_data=b[1]) for b in row])
    return InlineKeyboardMarkup(inline_keyboard=out)


async def send(lead: dict, text: str, rows=None) -> bool:
    """rows: [[(заголовок, id[, описание])]]. True — доставлено. В WhatsApp вне 24-часового окна не пишем."""
    ch = lead.get("channel")
    try:
        if ch == "tg" and lead.get("tg_id"):
            await bot.send_message(lead["tg_id"], text, reply_markup=kb(rows), disable_web_page_preview=True)
        elif ch == "wa" and lead.get("wa_id"):
            if not wa.window_open(lead):
                log.info("лид %s: окно WhatsApp закрыто, сообщение не отправлено", lead["id"])
                return False
            opts = [(b[1], b[0], b[2] if len(b) > 2 else "") for row in (rows or []) for b in row
                    if not b[1].startswith("url:")]
            if opts:
                await wa.send_options(lead["wa_id"], text, opts, t(lead_lang(lead), "list_button"))
            else:
                await wa.send_text(lead["wa_id"], text)
        else:
            return False
    except Exception:
        log.warning("лид %s: не удалось отправить в %s", lead["id"], ch, exc_info=True)
        return False
    await db.log(lead["id"], "out", ch, re.sub(r"<[^>]+>", "", text))
    return True


def lead_lang(lead: dict) -> str:
    return norm_lang(lead.get("lang"))


# ================================================================ выбор времени

async def show_days(lead: dict, note: str | None = None):
    lang = lead_lang(lead)
    free = await slots.free()
    head = (note + "\n\n" if note else "")
    if not free:
        return await send(lead, head + t(lang, "no_slots", tg=config.SALES_TG),
                          [[(t(lang, "btn_write"), f"url:https://t.me/{config.SALES_TG}")]])
    if lead.get("channel") == "wa":               # в WhatsApp один список: ближайшие окна по 2–3 на день
        opts, per_day = [], max(2, 10 // max(1, min(len(free), 5)))
        for d, ts in free.items():
            pick = ts if len(ts) <= per_day else [ts[round(i * (len(ts) - 1) / (per_day - 1))] for i in range(per_day)]
            for x in dict.fromkeys(pick):
                opts.append((f"{day_label(d, lang)} {x:%H:%M}", f"s:{slots.stamp(x)}"))
                if len(opts) == 10:
                    break
            if len(opts) == 10:
                break
        return await send(lead, head + t(lang, "list_body"), [[o] for o in opts])
    days = list(free)[:6]
    btns = [(day_label(d, lang), f"d:{d:%Y%m%d}") for d in days]
    return await send(lead, head + t(lang, "pick_day"), [btns[i:i + 2] for i in range(0, len(btns), 2)])


async def show_times(lead: dict, d):
    lang = lead_lang(lead)
    ts = (await slots.free()).get(d, [])
    if not ts:
        return await show_days(lead, t(lang, "taken"))
    btns = [(f"{x:%H:%M}", f"s:{slots.stamp(x)}") for x in ts]
    rows = [btns[i:i + 4] for i in range(0, len(btns), 4)] + [[(t(lang, "btn_back"), "days")]]
    await send(lead, t(lang, "pick_time", day=day_label(d, lang)), rows)


def formats(lead: dict) -> list[str]:
    return ["tg" if lead.get("channel") == "tg" else "wa", "meet", "phone"]


async def show_formats(lead: dict, at: datetime):
    lang = lead_lang(lead)
    s = slots.stamp(at)
    await send(lead, t(lang, "pick_format", when=when(at, lang)),
               [[(fmt_label(lang, f), f"f:{f}:{s}")] for f in formats(lead)])


def call_rows(lead: dict, call_id: int):
    lang = lead_lang(lead)
    return [[(t(lang, "btn_resched"), f"re:{call_id}"), (t(lang, "btn_cancel"), f"x:{call_id}")]]


async def on_choice(lead: dict, cid: str):
    """Нажатие кнопки лидом (Telegram callback или ответ на кнопку/список WhatsApp)."""
    lang = lead_lang(lead)
    if cid == "days":
        return await show_days(lead)
    if m := re.fullmatch(r"d:(\d{8})", cid):
        return await show_times(lead, datetime.strptime(m[1], "%Y%m%d").date())
    if m := re.fullmatch(r"s:(\d{12})", cid):
        call = await db.active_call(lead["id"])
        if call:
            return await send(lead, t(lang, "already", when=when(datetime.fromisoformat(call["at"]), lang),
                                      fmt=fmt_label(lang, call["format"])), call_rows(lead, call["id"]))
        at = slots.parse_stamp(m[1])
        if not await slots.is_free(at):
            return await show_days(lead, t(lang, "taken"))
        return await show_formats(lead, at)
    if m := re.fullmatch(r"f:(tg|wa|meet|phone):(\d{12})", cid):
        fmt, at = m[1], slots.parse_stamp(m[2])
        if fmt == "phone" and not lead.get("phone"):
            await db.update_lead(lead["id"], pending=f"phone:{m[2]}")
            return await send(lead, t(lang, "ask_phone"))
        return await book(lead, at, fmt, lead.get("phone") or "")
    if m := re.fullmatch(r"(re|x):(\d+)", cid):
        call = await db.get_call(int(m[2]))
        if not call or call["lead_id"] != lead["id"] or call["status"] not in db.ACTIVE_CALL:
            return
        await db.set_call(call["id"], status="resched" if m[1] == "re" else "cancelled")
        await gcal.delete_event(call.get("event_id") or "")
        await db.update_lead(lead["id"], call_id=None, stage="talking")
        was = when(datetime.fromisoformat(call["at"]), "ru")
        if m[1] == "x":
            await note(lead, f"❌ Отменил звонок {was}")
            return await send(lead, t(lang, "cancelled"))
        await note(lead, f"🔁 Переносит звонок {was}, выбирает новое время")
        return await show_days(lead)


def normalize_phone(raw: str) -> str:
    d = re.sub(r"[^\d+]", "", raw or "")
    if re.fullmatch(r"\+\d{10,15}", d):
        return d
    if re.fullmatch(r"380\d{9}", d):
        return "+" + d
    if re.fullmatch(r"0\d{9}", d):
        return "+38" + d
    return ""


async def book(lead: dict, at: datetime, fmt: str, phone: str = "") -> bool:
    lang = lead_lang(lead)
    if not await slots.is_free(at):
        await show_days(lead, t(lang, "taken"))
        return False
    contact = phone or lead.get("phone") or (f"@{lead['tg_username']}" if lead.get("tg_username") else "")
    desc = "\n".join(x for x in [
        f"Лид: {lead.get('name') or '—'} · {FMT_RU.get(fmt, fmt)} · {contact or '—'}",
        f"Интересует: {lead.get('service')}" if lead.get("service") else "",
        f"Бизнес: {lead.get('biz') or lead.get('niche')}" if (lead.get("biz") or lead.get("niche")) else "",
        f"Запрос: {lead.get('request') or lead.get('pain')}" if (lead.get("request") or lead.get("pain")) else "",
        f"WhatsApp: https://wa.me/{lead['wa_id']}" if lead.get("wa_id") else "",
        f"Telegram: https://t.me/{lead['tg_username']}" if lead.get("tg_username") else ""] if x)
    event = await gcal.add_event(at, f"ADrenaline · {lead.get('name') or 'лид'} · {FMT_RU.get(fmt, fmt)}", desc)
    call_id = await db.add_call(lead["id"], at, fmt, phone, event)
    upd = {"stage": "booked", "call_id": call_id, "next_at": None, "pending": None}
    if phone and not lead.get("phone"):
        upd["phone"] = phone
    await db.update_lead(lead["id"], **upd)
    lead.update(upd)
    nxt = t(lang, "next")
    nx = (nxt["meet_url"].format(url=esc(config.MEET_URL)) if fmt == "meet" and config.MEET_URL
          else nxt[fmt].format(phone=esc(phone or contact)))
    await send(lead, t(lang, "booked", when=when(at, lang), fmt=fmt_label(lang, fmt), next=nx), call_rows(lead, call_id))
    todo = {"meet": f"🔗 Ссылка клиенту: {esc(config.MEET_URL)}" if config.MEET_URL else "🔗 Отправь ссылку на Meet",
            "phone": f"☎️ Позвонить на {esc(phone or contact)}", "tg": "📞 Позвонить в Telegram",
            "wa": f"📞 Позвонить в WhatsApp +{lead.get('wa_id', '')}"}[fmt]
    await note(lead, f"✅ <b>Записался на звонок</b>: {when(at, 'ru')} (Киев), {FMT_RU.get(fmt, fmt)}\n{todo}"
                     + ("\n📅 Событие в календаре создано" if event else ""),
               [[("✅ Подтвердить", f"g:ok:{call_id}"), ("✉️ Написать через бота", f"g:msg:{lead['id']}")]])
    analytics.track(lead, "call_booked", fmt=fmt, channel=lead.get("channel") or "")
    return True


# ================================================================ входящие сообщения (оба канала)

async def incoming(lead: dict, text: str):
    """Текст от лида: телефон по запросу → запись; занятый Даниилом лид → в группу; иначе отвечает агент."""
    lang = lead_lang(lead)
    await db.log(lead["id"], "in", lead.get("channel") or "", text)
    lead = await db.get_lead(lead["id"])
    await note(lead, f"💬 {esc(text[:500])}", silent=True)
    pend = lead.get("pending") or ""
    if pend.startswith("phone:"):
        ph = normalize_phone(text)
        if not ph:
            return await send(lead, t(lang, "bad_phone"))
        await db.update_lead(lead["id"], pending=None, phone=ph)
        lead["phone"] = ph
        return await book(lead, slots.parse_stamp(pend[6:]), "phone", ph)
    if lead.get("stage") in ("taken", "lost"):
        return                                            # ведёт Даниил: сообщение уже в группе
    first = lead.get("stage") in ("new", "wa_sent", "need_call")   # первый ответ: после ИИ точно покажем окна
    upd = {}
    if lead.get("stage") in ("new", "wa_sent", "need_call", "opted_out"):
        upd["stage"] = "talking"
    if lead.get("stage") != "booked" and not lead.get("nudged"):
        upd["next_at"] = db.iso(db.now() + timedelta(hours=config.NUDGE_HOURS))
    g = guess_lang(text, None)
    if g and g != lead.get("lang"):
        upd["lang"] = g
    if upd:
        await db.update_lead(lead["id"], **upd)
        lead.update(upd)
        lang = lead_lang(lead)
    if not config.ANTHROPIC_API_KEY or not await db.ai_hit(lead):
        await note(lead, "⚠️ ИИ не ответил (нет ключа или лимит за сутки) — ответьте вручную",
                   [[("✉️ Написать через бота", f"g:msg:{lead['id']}")]])
        return await send(lead, t(lang, "busy_ai"))
    acts = agent.new_actions(lambda at, fmt, phone: book(lead, at, fmt, phone))
    try:
        answer = await agent.reply(lead, acts)
    except Exception:
        log.exception("агент упал на лиде %s", lead["id"])
        await note(lead, "⚠️ ИИ временно недоступен — ответьте вручную",
                   [[("✉️ Написать через бота", f"g:msg:{lead['id']}")]])
        return await send(lead, t(lang, "busy_ai"))
    answer = re.sub(r"\*\*(.+?)\*\*", r"\1", answer or "").strip()
    if answer:
        await send(lead, esc(answer))
    if acts.stop:
        await db.update_lead(lead["id"], stage="opted_out", next_at=None)
        await note(lead, "🚫 Попросил больше не писать")
    elif acts.handoff:
        await db.update_lead(lead["id"], stage="taken", next_at=None)
        await note(lead, f"🙋 <b>Нужен Даниил</b>: {esc(acts.handoff)}",
                   [[("✉️ Ответить через бота", f"g:msg:{lead['id']}")]])
    elif acts.show_slots or (first and not await db.active_call(lead["id"])):
        await show_days(await db.get_lead(lead["id"]))


async def link_channel(lead: dict, channel: str, **ids) -> dict:
    """Человек сам открыл Telegram или WhatsApp по кнопке: дальше общаемся там, автоматика ожидания выключается."""
    upd = {"channel": channel, **ids}
    if lead.get("stage") in ("new", "wa_sent", "need_call"):
        upd.update(stage="talking", next_at=db.iso(db.now() + timedelta(hours=config.NUDGE_HOURS)))
    await db.update_lead(lead["id"], **upd)
    lead = await db.get_lead(lead["id"])
    await note(lead, {"tg": "📲 Открыл Telegram-бота", "wa": "📲 Написал в WhatsApp"}[channel])
    analytics.track(lead, "lead_channel", channel=channel)
    return lead


async def greet(lead: dict):
    lang = lead_lang(lead)
    if lead.get("source") == "site":
        svc = t(lang, "svc", s=esc(lead["service"])) if lead.get("service") else ""
        text = t(lang, "hello_lead", name=esc(lead.get("name") or ""), svc=svc)
    else:
        text = t(lang, "hello_direct")
    call = await db.active_call(lead["id"])
    if call:
        await send(lead, text.split("\n\n")[0])
        return await send(lead, t(lang, "already", when=when(datetime.fromisoformat(call["at"]), lang),
                                  fmt=fmt_label(lang, call["format"])), call_rows(lead, call["id"]))
    await show_days(lead, text)


# ================================================================ новые лиды

def lang_from(body: dict) -> str:
    a = body.get("attribution") or {}
    page = f"{body.get('page', '')} {a.get('landing', '')}"
    return "ru" if "/ru" in page or body.get("lang") == "ru" else "uk"


async def site_lead(body: dict) -> dict:
    contact = str(body.get("contact") or "").strip()[:200]
    phone = normalize_phone(contact)
    m = re.search(r"@([A-Za-z0-9_]{4,32})|t\.me/([A-Za-z0-9_]{4,32})", contact)
    tg_user = (m[1] or m[2]) if m else ""
    a = body.get("attribution") or {}
    lead = await db.create_lead(
        source="site", page=str(body.get("page") or a.get("landing") or "")[:200], lang=lang_from(body),
        name=str(body.get("name") or "").strip()[:80], contact=contact, phone=phone, tg_username=tg_user,
        service=str(body.get("service") or "")[:120], niche=str(body.get("niche") or "")[:200],
        site=str(body.get("site") or "")[:200], budget=str(body.get("budget") or "")[:60],
        pain=str(body.get("pain") or "")[:300], term=str(body.get("term") or "")[:60],
        calc=str(body.get("calc") or "")[:200], attribution=a, cid=str(body.get("cid") or "")[:60],
        wa_id=wa.phone_to_wa(phone) if phone else None,
        next_at=db.iso(db.now() + timedelta(minutes=config.TG_WAIT_MIN)) if config.AUTOMATION else None)
    await post_card(lead)
    return lead


def links(lead: dict) -> dict:
    out = {"token": lead["token"]}
    if bot_username:
        out["tg"] = f"https://t.me/{bot_username}?start=l_{lead['token']}"
    if config.wa_enabled() and config.WA_NUMBER:
        from urllib.parse import quote
        msg = ("Заявка #{tok}: хочу выбрать время звонка" if lead_lang(lead) == "ru"
               else "Заявка #{tok}: хочу обрати час дзвінка").format(tok=lead["token"])
        out["wa"] = f"https://wa.me/{config.WA_NUMBER}?text={quote(msg)}"
    return out


# ================================================================ группа «Заявки»

def staff(uid: int, chat_id: int | None = None) -> bool:
    if chat_id is not None and config.SALES_CHAT_ID < 0 and chat_id == config.SALES_CHAT_ID:
        return True
    return uid in (config.SALES_STAFF_IDS | {config.SALES_CHAT_ID}) - {0}


def card_text(lead: dict) -> str:
    src = {"site": "заявка с сайта", "tg": "написал боту продаж", "wa": "написал в WhatsApp"}.get(lead.get("source"), "")
    try:
        a = json.loads(lead.get("attribution") or "{}")
    except ValueError:
        a = {}
    ad = " / ".join(x for x in [a.get("utm_source"), a.get("utm_campaign"), a.get("utm_term")] if x)
    rows = [f"🆕 <b>Лид #{lead['id']}</b> · {src}" + (" · RU" if lead.get("lang") == "ru" else ""),
            f"👤 {esc(lead.get('name') or '—')} · {esc(lead.get('contact') or lead.get('phone') or '—')}"]
    for k, label in (("service", "🎯"), ("niche", "🏢"), ("site", "🌐"), ("budget", "💰"), ("pain", "🧩"),
                     ("calc", "🧮"), ("term", "📆")):
        if lead.get(k):
            rows.append(f"{label} {esc(lead[k])}")
    if ad or a.get("gclid"):
        rows.append(f"📣 {esc(ad or 'google')}" + (" · gclid" if a.get("gclid") else ""))
    plan = []
    if lead.get("source") == "site" and config.AUTOMATION:
        plan.append(f"ждём {config.TG_WAIT_MIN} мин, откроет ли Telegram/WhatsApp сам")
        plan.append("потом шаблон в WhatsApp" if (config.wa_enabled() and lead.get("phone")) else
                    "потом — позвонить вручную (WhatsApp не подключён или нет телефона)")
    if plan:
        rows.append("🤖 " + "; ".join(plan))
    return "\n".join(rows)


def card_kb(lead: dict):
    return kb([[("🙋 Беру сам", f"g:take:{lead['id']}"), ("✉️ Написать через бота", f"g:msg:{lead['id']}")],
               [("🚫 Не целевой", f"g:lost:{lead['id']}")]])


async def post_card(lead: dict):
    if not config.SALES_CHAT_ID or bot is None:
        return
    try:
        m = await bot.send_message(config.SALES_CHAT_ID, card_text(lead), reply_markup=card_kb(lead),
                                   disable_web_page_preview=True)
        await db.update_lead(lead["id"], card_id=m.message_id)
        lead["card_id"] = m.message_id
    except Exception:
        log.exception("карточка лида %s не отправлена", lead["id"])


async def note(lead: dict, text: str, rows=None, silent: bool = False):
    """Событие по лиду — ответом на его карточку, чтобы в группе была лента по каждому лиду."""
    if not config.SALES_CHAT_ID or bot is None:
        return
    head = f"#{lead['id']} {esc(lead.get('name') or '')}: "
    kw = {"reply_markup": kb(rows), "disable_web_page_preview": True, "disable_notification": silent}
    if lead.get("card_id"):
        kw["reply_to_message_id"] = lead["card_id"]
        kw["allow_sending_without_reply"] = True
    try:
        await bot.send_message(config.SALES_CHAT_ID, head + text, **kw)
    except Exception:
        log.warning("заметка по лиду %s не отправлена", lead["id"], exc_info=True)
