"""Демо «AI-менеджер продаж» внутри основного бота (вымышленная компания «Промінь Енерджі»).

Показывает, как работает бот продаж из шаблона sales-template, не трогая настоящую группу заявок и календарь:
1. На стартовом экране кнопка «🤝 Бот продажів» → человек в роли клиента выбирает, что его интересует
   (это имитация формы на сайте).
2. Бот здоровается как бот продаж: имя, услуга из заявки, свободные окна. Вопросы разбирает ИИ по фактам компании,
   записывает кнопками или по фразе «завтра в 12 в Meet», нестандартное отдаёт менеджеру.
3. «👀 Очима менеджера» — карточка лида и лента событий так, как их видит команда в группе «Заявки».
4. Дальше обычная воронка ADrenaline: презентация и запись на звонок (кнопки funnel).

Режим хранится в users.niche = "salesbot"; выбор другой сферы его выключает. Данные демо (заявка, звонок, лента,
история диалога) — в таблице salesdemo одной JSON-строкой на человека. Роутер подключается после funnel.router
и перед основным (main.py), поэтому кнопки воронки («📅 Дзвінок з ADrenaline») работают как обычно."""
import html
import json
import logging
import re
import zlib
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup

from . import ai, analytics, config, db, funnel, i18n, sales
from . import bot as core
from .config import DB_PATH
from .funnel_texts import ft
from .salesdemo_texts import ST

log = logging.getLogger("salesdemo")
router = Router()
router.message.filter(F.chat.type == "private")
esc = html.escape

MODE = "salesbot"
COMPANY: dict = json.loads((Path(__file__).with_name("salesdemo_company.json")).read_text(encoding="utf-8"))
MGR_TEXTS = set(ST["btn_mgr"].values())


class SDemo(StatesGroup):
    phone = State()          # ждём номер для звонка «телефоном»


# ================================================================ тексты с данными компании

class Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _l(v: dict, lang: str):
    return v.get(lang) or v.get("uk")


def company_vars(lang: str) -> Keep:
    m = _l(COMPANY["manager"], lang)
    v = Keep(company=COMPANY["company_en"] if lang == "en" else COMPANY["company"], min=COMPANY["call_minutes"],
             m=m["nom"], m_gen=m["gen"], m_dat=m["dat"], m_ins=m["ins"])
    v["pitch"] = _l(COMPANY["pitch"], lang).format_map(v)
    v["offer"] = _l(COMPANY["offer"], lang).format_map(v)
    return v


def tx(lang: str, key: str, **kw):
    """Текст демо на языке человека с подстановкой компании и менеджера."""
    val = _l(ST[key], lang)
    ctx = Keep({**company_vars(lang), **kw})
    if isinstance(val, dict):
        return {k: (s.format_map(ctx) if isinstance(s, str) else s) for k, s in val.items()}
    return val.format_map(ctx)


def services(lang: str) -> list[str]:
    return _l(COMPANY["services"], lang)


def svc_name(d: dict, lang: str) -> str:
    i = d.get("svc")
    return services(lang)[i].split(" ", 1)[-1] if isinstance(i, int) else ""


# ================================================================ хранение

async def _init():
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("CREATE TABLE IF NOT EXISTS salesdemo(user_id INTEGER PRIMARY KEY, data TEXT)")
        await c.commit()


async def load(uid: int) -> dict:
    await _init()
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT data FROM salesdemo WHERE user_id=?", (uid,))
        row = await cur.fetchone()
    try:
        return json.loads(row[0]) if row else {}
    except ValueError:
        return {}


async def save(uid: int, d: dict):
    await _init()
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("INSERT INTO salesdemo(user_id, data) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET data=?",
                        (uid, json.dumps(d, ensure_ascii=False), json.dumps(d, ensure_ascii=False)))
        await c.commit()


async def in_mode(uid: int) -> bool:
    return config.DEMO_MODE and ((await db.get_user(uid)) or {}).get("niche") == MODE


def event(d: dict, kind: str, **kw):
    d.setdefault("events", []).append({"k": kind, **kw})
    del d["events"][:-30]


# ================================================================ свободные окна (условные, без календаря)

def _sched(key: str, default):
    return COMPANY.get("schedule", {}).get(key, default)


def free(at: datetime | None = None, d: dict | None = None) -> dict[date, list[datetime]]:
    """Окна на неделю вперёд по графику компании. Часть «занята» (стабильно, по хэшу), чтобы демо было живым."""
    at = at or sales.now()
    days = {int(x) for x in str(_sched("days", "1,2,3,4,5")).split(",") if x.strip().isdigit()}
    a, b = (time.fromisoformat(x) for x in _sched("hours", "09:00-18:00").split("-"))
    step = timedelta(minutes=int(_sched("slot_min", 60)))
    earliest = at + timedelta(hours=float(_sched("min_lead_hours", 1)))
    mine = ((d or {}).get("call") or {}).get("at")
    out: dict[date, list[datetime]] = {}
    for i in range(int(_sched("days_ahead", 7)) + 1):
        day = at.date() + timedelta(days=i)
        if day.isoweekday() not in days:
            continue
        t, end = datetime.combine(day, a, sales.TZ), datetime.combine(day, b, sales.TZ)
        while t + step <= end:
            busy = zlib.crc32(f"sd{day.isoformat()}{t:%H%M}".encode()) % 4 == 0
            if t >= earliest and not busy and sales._iso(t) != mine:
                out.setdefault(day, []).append(t)
            t += step
    return out


def is_free(at: datetime, d: dict | None = None) -> bool:
    return at in free(d=d).get(at.date(), [])


def stamp(at: datetime) -> str:
    return f"{at:%Y%m%d%H%M}"


def parse_stamp(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d%H%M").replace(tzinfo=sales.TZ)


def parse_any(s: str) -> datetime | None:
    """«2026-10-16T10:30» или «2026-10-16 10:30» от ИИ → время по Киеву."""
    try:
        dt = datetime.fromisoformat((s or "").strip().replace(" ", "T"))
    except ValueError:
        return None
    return dt.replace(tzinfo=sales.TZ) if dt.tzinfo is None else dt.astimezone(sales.TZ)


def fmt_label(lang: str, fmt: str) -> str:
    return tx(lang, "fmt").get(fmt, fmt)


def call_rows(lang: str):
    return [[(tx(lang, "btn_resched"), "sd:re"), (tx(lang, "btn_cancel"), "sd:x")]]


# ================================================================ вход в демо

def demo_kb(lang: str) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=s)] for s in _l(COMPANY["samples"], lang)]
    rows.append([KeyboardButton(text=tx(lang, "btn_mgr")), KeyboardButton(text=ft(lang, "btn_call"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def svc_kb(lang: str):
    return funnel.ikb([[(s, f"sd:svc:{i}")] for i, s in enumerate(services(lang))])


async def enter(target: Message, user):
    """Включает режим демо бота продаж и показывает экран «что вас интересует»."""
    lang = await core.ulang(user)
    await core.touch(user)
    if not await sales.get(user.id):
        await sales.start(user.id, "direct", "")
    await db.set_niche(user.id, MODE)
    old = await load(user.id)
    await save(user.id, {"n": (old.get("n") or 1000 + user.id % 9000) + (1 if old else 0)})
    await sales.update(user.id, biz=MODE)
    await sales.advance(user.id, "demo")
    await sales.touch(user.id)
    analytics.track(await sales.get(user.id), user.id, "demo_niche", niche=MODE)
    await target.answer(tx(lang, "intro"), reply_markup=svc_kb(lang))


@router.callback_query(F.data.in_({"fn:salesbot", "sd:restart"}))
async def pick(cb: CallbackQuery):
    await cb.answer()
    await enter(cb.message, cb.from_user)


@router.message(Command("salesbot"))
async def salesbot_cmd(m: Message, state: FSMContext):
    if not config.DEMO_MODE:
        raise SkipHandler
    await state.clear()
    await enter(m, m.from_user)


@router.callback_query(F.data.regexp(r"^sd:svc:[0-2]$"))
async def site_request(cb: CallbackQuery):
    """Человек «отправил форму на сайте»: заявка → карточка в группе → бот здоровается и показывает окна."""
    user = cb.from_user
    lang = await core.ulang(user)
    await cb.answer()
    if not await in_mode(user.id):
        await db.set_niche(user.id, MODE)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    d = await load(user.id)
    d.update(svc=int(cb.data[-1]), src="site", call=None, hist=[], events=[{"k": "open"}])
    await save(user.id, d)
    await cb.message.answer(tx(lang, "sent"), reply_markup=demo_kb(lang))
    hello = tx(lang, "hello_lead", name=esc(user.first_name or ""), svc=esc(svc_name(d, lang)))
    await show_days(cb.message, user, lang, d, head=hello)
    await cb.message.answer(tx(lang, "hint"))
    await sales.touch(user.id)


# ================================================================ выбор времени (как в боте продаж)

async def show_days(target: Message, user, lang: str, d: dict, head: str = "", edit: bool = False):
    slots = free(d=d)
    days = list(slots)[:6]
    btns = [(funnel.day_label(x, lang), f"sd:d:{x:%Y%m%d}") for x in days]
    text = (head + "\n\n" if head else "") + tx(lang, "pick_day")
    markup = funnel.ikb([btns[i:i + 2] for i in range(0, len(btns), 2)])
    if edit:
        try:
            return await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            pass
    await target.answer(text, reply_markup=markup)


@router.callback_query(F.data == "sd:days")
async def days_cb(cb: CallbackQuery):
    await cb.answer()
    await show_days(cb.message, cb.from_user, await core.ulang(cb.from_user), await load(cb.from_user.id), edit=True)


@router.callback_query(F.data.regexp(r"^sd:d:\d{8}$"))
async def day_cb(cb: CallbackQuery):
    lang = await core.ulang(cb.from_user)
    d = await load(cb.from_user.id)
    day = datetime.strptime(cb.data[5:], "%Y%m%d").date()
    ts = free(d=d).get(day, [])
    await cb.answer()
    if not ts:
        return await show_days(cb.message, cb.from_user, lang, d, head=tx(lang, "taken"), edit=True)
    btns = [(f"{x:%H:%M}", f"sd:t:{stamp(x)}") for x in ts]
    rows = [btns[i:i + 4] for i in range(0, len(btns), 4)] + [[(tx(lang, "btn_back"), "sd:days")]]
    try:
        await cb.message.edit_text(tx(lang, "pick_time", day=funnel.day_label(day, lang)), reply_markup=funnel.ikb(rows))
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.regexp(r"^sd:t:\d{12}$"))
async def time_cb(cb: CallbackQuery):
    lang = await core.ulang(cb.from_user)
    d = await load(cb.from_user.id)
    at = parse_stamp(cb.data[5:])
    await cb.answer()
    if d.get("call"):
        c = d["call"]
        return await cb.message.answer(
            tx(lang, "already", when=funnel.when_text(datetime.fromisoformat(c["at"]), lang),
               fmt=fmt_label(lang, c["fmt"])), reply_markup=funnel.ikb(call_rows(lang)))
    if not is_free(at, d):
        return await show_days(cb.message, cb.from_user, lang, d, head=tx(lang, "taken"), edit=True)
    s = stamp(at)
    rows = [[(fmt_label(lang, f), f"sd:f:{f}:{s}")] for f in ("tg", "meet", "phone")]
    rows.append([(tx(lang, "btn_back"), "sd:days")])
    try:
        await cb.message.edit_text(tx(lang, "pick_format", when=funnel.when_text(at, lang)),
                                   reply_markup=funnel.ikb(rows))
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.regexp(r"^sd:f:(tg|meet|phone):\d{12}$"))
async def format_cb(cb: CallbackQuery, state: FSMContext, bot: Bot):
    lang = await core.ulang(cb.from_user)
    _, _, fmt, s = cb.data.split(":")
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    if fmt == "phone":
        await state.set_state(SDemo.phone)
        await state.update_data(stamp=s)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=tx(lang, "btn_share_phone"), request_contact=True)]],
                                 resize_keyboard=True, one_time_keyboard=True)
        return await cb.message.answer(tx(lang, "ask_phone"), reply_markup=kb)
    d = await load(cb.from_user.id)
    if await book(cb.message, cb.from_user, lang, d, parse_stamp(s), fmt):
        await after_booking(bot, cb.message, cb.from_user, lang)


def normalize_phone(raw: str) -> str:
    p = re.sub(r"[^\d+]", "", raw or "")
    if re.fullmatch(r"\+\d{10,15}", p):
        return p
    if re.fullmatch(r"380\d{9}", p):
        return "+" + p
    if re.fullmatch(r"0\d{9}", p):
        return "+38" + p
    return ""


@router.message(SDemo.phone, F.contact)
@router.message(SDemo.phone, F.text, ~F.text.startswith("/"))
async def got_phone(m: Message, state: FSMContext, bot: Bot):
    lang = await core.ulang(m.from_user)
    phone = normalize_phone(m.contact.phone_number if m.contact else m.text)
    if not phone:
        return await m.answer(tx(lang, "bad_phone"))
    data = await state.get_data()
    await state.clear()
    d = await load(m.from_user.id)
    if await book(m, m.from_user, lang, d, parse_stamp(data["stamp"]), "phone", phone):
        await after_booking(bot, m, m.from_user, lang)


async def book(target: Message, user, lang: str, d: dict, at: datetime, fmt: str, phone: str = "") -> bool:
    """Запись на звонок в демо: подтверждение клиенту и событие в ленту менеджера (в настоящую группу не уходит)."""
    if not is_free(at, d):
        await show_days(target, user, lang, d, head=tx(lang, "taken"))
        return False
    d["call"] = {"at": sales._iso(at), "fmt": fmt, "phone": phone}
    event(d, "booked", at=sales._iso(at), fmt=fmt, phone=phone)
    await save(user.id, d)
    nxt = tx(lang, "next")[fmt].replace("{phone}", esc(phone))
    await target.answer(tx(lang, "booked", when=funnel.when_text(at, lang), fmt=fmt_label(lang, fmt), next=nxt),
                        reply_markup=funnel.ikb(call_rows(lang)))
    return True


async def after_booking(bot: Bot, target: Message, user, lang: str):
    """После первой записи в демо: показываем, что получил менеджер, и сообщаем команде ADrenaline."""
    p = await sales.get(user.id) or {}
    await sales.touch(user.id)
    if not p.get("demo_booked"):
        await sales.update(user.id, demo_booked=1)
        analytics.track(p, user.id, "demo_booking", niche=MODE)
        if config.SALES_CHAT_ID and config.SALES_CHAT_ID != config.OWNER_ID:
            await funnel.notify_sales(bot, f"🧪 Посетитель записался в демо <b>бота продаж</b> как клиент "
                                           f"({esc(core.who(user))})\n" + await funnel.prospect_card(user))
    await target.answer(tx(lang, "after_booked"))
    await show_mgr(target, user)


@router.callback_query(F.data.in_({"sd:re", "sd:x"}))
async def call_action(cb: CallbackQuery):
    lang = await core.ulang(cb.from_user)
    d = await load(cb.from_user.id)
    await cb.answer()
    c = d.get("call")
    if not c:
        return
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    d["call"] = None
    event(d, "cancel" if cb.data == "sd:x" else "resched", at=c["at"])
    await save(cb.from_user.id, d)
    if cb.data == "sd:x":
        return await cb.message.answer(tx(lang, "cancelled"))
    await show_days(cb.message, cb.from_user, lang, d)


# ================================================================ глазами менеджера

CITY = {"uk": "Київ", "ru": "Киев", "en": "Kyiv"}


def _event_line(e: dict, lang: str) -> str:
    ev = tx(lang, "ev")
    k = e.get("k")
    if k in ("booked", "resched", "cancel"):
        x = f"{funnel.when_text(datetime.fromisoformat(e['at']), lang)} ({CITY.get(lang, CITY['uk'])})"
        if k == "booked":
            todo = tx(lang, "todo")[e["fmt"]].replace("{phone}", esc(e.get("phone") or ""))
            x += f", {fmt_label(lang, e['fmt'])}\n{todo}"
        return ev[k].replace("{x}", x)
    return ev.get(k, "•").replace("{x}", esc(str(e.get("x", ""))[:300]))


def card_text(d: dict, user, lang: str) -> str:
    svc = f"\n🎯 {esc(svc_name(d, lang))}" if d.get("svc") is not None else ""
    contact = f"@{user.username}" if user.username else "+380 67 ••• •• ••"
    src = d.get("src") or "tg"
    return tx(lang, "card", n=d.get("n", 1000), src=tx(lang, "src")[src], name=esc(user.first_name or "—"),
              contact=esc(contact), svc=svc, campaign=tx(lang, "campaign") if src == "site" else "—",
              plan=tx(lang, "plan") if src == "site" else "—")


def mgr_kb(lang: str):
    return funnel.ikb([[(tx(lang, "mg_take"), "sd:mg:take"), (tx(lang, "mg_msg"), "sd:mg:msg")],
                       [(tx(lang, "mg_lost"), "sd:mg:lost")]])


async def show_mgr(target: Message, user):
    lang = await core.ulang(user)
    d = await load(user.id)
    if not d.get("src"):
        return await target.answer(tx(lang, "need_lead"), reply_markup=svc_kb(lang))
    await target.answer(tx(lang, "mgr_title"))
    await target.answer(card_text(d, user, lang), reply_markup=mgr_kb(lang))
    lines = [_event_line(e, lang) for e in d.get("events", [])[-15:]]
    feed = tx(lang, "feed_title", n=d.get("n", 1000)) + "\n\n" + ("\n".join(lines) if lines else tx(lang, "feed_empty"))
    ok = funnel.ikb([[(tx(lang, "mg_ok"), "sd:mg:ok"), (tx(lang, "mg_msg"), "sd:mg:msg")]]) if d.get("call") else None
    await target.answer(feed[:4000], reply_markup=ok)
    p = await sales.get(user.id) or {}
    seen = p.get("pitch_seen") if p.get("pitch_seen") is not None else -1
    rows = [[(ft(lang, "btn_pitch"), "fpn:0")]] if seen < funnel.SLIDES - 1 else []
    rows += [[(ft(lang, "btn_call"), "fb:go")], [(tx(lang, "btn_restart"), "sd:restart")]]  # звонок с ADrenaline, не с Мариной
    await target.answer(tx(lang, "mgr_explain"), reply_markup=funnel.ikb(rows))
    await sales.update(user.id, owner_seen=1)
    await sales.advance(user.id, "owner")
    await sales.touch(user.id)
    analytics.track(p, user.id, "owner_view", niche=MODE, with_lead=bool(d.get("call")))


@router.message(F.text.func(lambda t: t in MGR_TEXTS))
async def mgr_text(m: Message):
    await show_mgr(m, m.from_user)


@router.callback_query(F.data == "sd:mgr")
async def mgr_cb(cb: CallbackQuery):
    await cb.answer()
    await show_mgr(cb.message, cb.from_user)


@router.callback_query(F.data.regexp(r"^sd:mg:(take|msg|lost|ok)$"))
async def mgr_button(cb: CallbackQuery):
    lang = await core.ulang(cb.from_user)
    await cb.answer(tx(lang, "alert")[cb.data[6:]], show_alert=True)


# ================================================================ диалог с ИИ (агент продаж)

RULES = """\
Ты — AI-ассистент {m_gen} из {company}. Человек оставил заявку (или написал сам), твоя цель — записать его на {min}-минутный
звонок с {m_ins}. Это продажа через пользу, не давление.

Как общаться:
- Пиши как живой менеджер: 1–3 коротких предложения, без markdown (никаких **, #, списков со звёздочками), максимум одно эмодзи.
- Отвечай на языке человека: украинский, русский или английский (язык лида указан ниже). Обращайся на «вы».
- Если спрашивают, бот ли ты — честно: ты AI-ассистент {m_gen}, {m} лично проведёт звонок.
- На вопрос отвечай по сути из фактов, потом мягко веди к звонку. Не задавай больше одного вопроса за раз.
- {qualify}
- Не выдумывай цены, сроки, кейсы, обещания результата. Нет в фактах — «уточню у {m_gen}» и handoff.

Запись:
- Чтобы показать человеку кнопки со свободным временем, вызови show_slots. Время называй только из списка свободных окон.
- Если человек сам назвал день и время, и оно есть в свободных окнах, и понятен формат — вызови book_call.
  Форматы: tg (звонок в Telegram), meet (Google Meet), phone (обычный звонок — нужен номер).
  Формат не назван — спроси или покажи кнопки (show_slots).
- «Сегодня», «завтра», «в четверг» — считай от текущей даты ниже; день недели — ближайший такой день в будущем.
- После успешного book_call подтверждение с деталями уходит отдельным сообщением: не повторяй детали, ответь одной фразой.

Когда звать {m_gen} (handoff): просит живого человека, сложный или нестандартный вопрос, {topics}.
Скажи, что {m} ответит здесь лично.

Это демонстрация для владельца бизнеса, который смотрит, как работает бот продаж; компания вымышленная. Оставайся
в роли. Если спрашивают о самом боте, о том, кто его сделал, или «хочу такого бота себе» — одной фразой скажи, что
это демо от ADrenaline и что кнопка «📅 Дзвінок з ADrenaline» внизу записывает на разговор с ними; handoff не вызывай."""

TOOLS = [
    {"name": "show_slots", "description": "Показать человеку кнопки со свободными днями и временем звонка.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "book_call", "description": "Записать на звонок, когда известны время из свободных окон и формат.",
     "input_schema": {"type": "object", "properties": {
         "datetime": {"type": "string", "description": "YYYY-MM-DDTHH:MM по Киеву"},
         "format": {"type": "string", "enum": ["tg", "meet", "phone"]},
         "phone": {"type": "string", "description": "Номер для формата phone, если человек его назвал"}},
         "required": ["datetime", "format"]}},
    {"name": "save_info", "description": "Сохранить то, что человек рассказал: для чего станция, город, запрос.",
     "input_schema": {"type": "object", "properties": {
         "business": {"type": "string", "description": "Дом или бизнес, город"},
         "request": {"type": "string", "description": "Что хочет / что болит"}}}},
    {"name": "handoff", "description": "Передать разговор менеджеру лично.",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
]
WD_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def rules() -> str:
    v = company_vars("ru")
    v["qualify"] = COMPANY["ai"]["qualify"].format_map(v)
    v["topics"] = COMPANY["ai"]["handoff_topics"].format_map(v)
    return RULES.format_map(v) + "\n\nФакты:\n" + "\n".join(COMPANY["ai"]["facts"])


def slots_text(d: dict) -> str:
    s = free(d=d)
    return "\n".join(f"- {x.isoformat()} ({WD_RU[x.weekday()]}): " + ", ".join(f"{t:%H:%M}" for t in ts)
                     for x, ts in list(s.items())[:6]) or "Свободных окон нет — предложи handoff."


def dynamic(d: dict, user, lang: str) -> str:
    now = sales.now()
    c = d.get("call")
    booked = (f"Уже записан: {c['at']}, формат {c['fmt']}. Новую запись не создавай, перенос — через show_slots."
              if c else "Пока не записан.")
    lead = [f"Источник: {'заявка с сайта' if d.get('src') == 'site' else 'написал боту сам'}",
            f"Имя: {user.first_name or '—'}"]
    if d.get("svc") is not None:
        lead.append(f"Что интересует (из формы): {svc_name(d, 'ru')}")
    for k, label in (("biz", "Для чего станция / город"), ("request", "Запрос")):
        if d.get(k):
            lead.append(f"{label}: {d[k]}")
    return (f"Сейчас {now:%Y-%m-%d %H:%M}, {WD_RU[now.weekday()]} (Киев). Канал: Telegram. "
            f"Язык лида: {i18n.lang_name_ru(lang)} ({lang}).\n{booked}\n\nДанные лида:\n" + "\n".join(lead)
            + f"\n\nСвободные окна для звонка:\n{slots_text(d)}")


async def agent_reply(user, lang: str, d: dict, target: Message, acts) -> str:
    """Один ход агента продаж. Последнее сообщение человека уже в d['hist']."""
    messages = [dict(h) for h in d.get("hist", [])]
    system = [{"type": "text", "text": rules(), "cache_control": {"type": "ephemeral"}},
              {"type": "text", "text": dynamic(d, user, lang)}]
    c = await ai._get_client()
    text = ""
    for _ in range(5):
        resp = await c.messages.create(model=config.CLAUDE_MODEL, max_tokens=500, system=system, tools=TOOLS,
                                       messages=messages)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if resp.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            res, err = await run_tool(b.name, b.input or {}, user, lang, d, target, acts)
            log.info("демо продаж: %s (user %s): %s", b.name, user.id, res[:120])
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": res, **({"is_error": True} if err else {})})
        messages.append({"role": "user", "content": results})
    return text


async def run_tool(name: str, args: dict, user, lang: str, d: dict, target: Message, acts) -> tuple[str, bool]:
    if name == "show_slots":
        acts.show_slots = True
        return "Кнопки со свободным временем будут показаны отдельным сообщением. Коротко подведи к выбору.", False
    if name == "book_call":
        at, fmt = parse_any(str(args.get("datetime", ""))), str(args.get("format", ""))
        if not at:
            return "Неверный формат времени. Нужен YYYY-MM-DDTHH:MM.", True
        if fmt not in ("tg", "meet", "phone"):
            return "Формат должен быть tg, meet или phone.", True
        if d.get("call"):
            return "Человек уже записан. Новую запись не создавай; для переноса — show_slots.", True
        if not is_free(at, d):
            return f"Время {at:%Y-%m-%d %H:%M} недоступно. Свободно:\n{slots_text(d)}", True
        phone = normalize_phone(str(args.get("phone") or ""))
        if fmt == "phone" and not phone:
            return "Для звонка по телефону нужен номер. Спроси его.", True
        ok = await book(target, user, lang, d, at, fmt, phone)
        acts.booked = ok
        return ("Запись создана, подтверждение с деталями уже отправлено. Ответь одной короткой фразой."
                if ok else "Окно заняли, кнопки с другим временем показаны."), not ok
    if name == "save_info":
        got = {k: str(args[v])[:200] for k, v in (("biz", "business"), ("request", "request")) if args.get(v)}
        d.update(got)
        if got:
            event(d, "info", x="; ".join(got.values()))
        return "Сохранено.", False
    if name == "handoff":
        acts.handoff = str(args.get("reason", ""))[:200] or "просит менеджера"
        return f"Передано. Скажи, что {company_vars('ru')['m']} ответит здесь лично.", False
    return "Неизвестный инструмент.", True


async def converse(m: Message, bot: Bot, text: str):
    user = m.from_user
    await core.touch(user)
    lang = await core.sync_lang(user, text)
    d = await load(user.id)
    first = not d.get("hist")
    if not d.get("src"):                                 # написал сам, без «заявки с сайта»
        d.update(src="tg", svc=None, call=None, hist=[], events=[])
    event(d, "in", x=text[:300])
    d.setdefault("hist", []).append({"role": "user", "content": text[:1000]})
    if not config.ANTHROPIC_API_KEY or await db.hit(user.id, config.USER_DAILY_LIMIT, config.GLOBAL_DAILY_LIMIT) != "ok":
        event(d, "noai")
        d["hist"].append({"role": "assistant", "content": tx(lang, "busy_ai")})
        await save(user.id, d)
        return await m.answer(tx(lang, "busy_ai"))
    await bot.send_chat_action(m.chat.id, "typing")
    acts = SimpleNamespace(show_slots=False, handoff="", booked=False)
    try:
        answer = await agent_reply(user, lang, d, m, acts)
    except Exception:
        log.exception("демо продаж: ошибка Claude")
        answer = ""
    answer = answer or tx(lang, "busy_ai")
    d["hist"].append({"role": "assistant", "content": answer})
    del d["hist"][:-12]
    if acts.handoff:
        event(d, "handoff", x=acts.handoff)
    await save(user.id, d)
    await m.answer(ai.to_html(answer))
    if acts.booked:
        await after_booking(bot, m, user, lang)
    elif acts.handoff:
        await m.answer(tx(lang, "after_handoff"))
    elif acts.show_slots or (first and not d.get("call")):
        await show_days(m, user, lang, d)
    await sales.touch(user.id)
    await sales.bump(user.id, "demo_msgs")


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def on_text(m: Message, bot: Bot):
    if not await in_mode(m.from_user.id):
        raise SkipHandler
    await converse(m, bot, m.text[:1000])


@router.message(StateFilter(None), F.photo)
async def on_photo(m: Message, bot: Bot):
    if not await in_mode(m.from_user.id):
        raise SkipHandler
    await converse(m, bot, ("[фото] " + (m.caption or "")).strip())
