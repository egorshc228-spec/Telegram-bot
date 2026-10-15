"""Воронка ADrenaline поверх демо: человек с сайта → выбор сферы → демо в роли клиента → «глазами владельца»
→ мини-презентация с калькулятором → 2 вопроса → запись на звонок в боте → фоллоу-апы тем, кто не записался.

Работает только при DEMO_MODE=1 и FUNNEL=1. Роутер подключается ПЕРЕД основным (main.py), поэтому перехватывает
/start и свои кнопки, а обычные сообщения клиента уходят в основной диалог с ИИ (bot.converse → after_ai)."""
import asyncio
import html
import logging
import re
from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)

from . import ai, analytics, config, db, i18n, reminders, sales
from . import bot as core
from .funnel_texts import FT, ft
from .niches import NICHES
from .report import leads_to_xlsx

log = logging.getLogger("funnel")
router = Router()
# Личка посетителей + группа «Заявки» (если SALES_CHAT_ID — группа): в группе работают только ответ посетителю и /funnel
router.message.filter(F.func(lambda m: m.chat.type == "private" or m.chat.id == config.SALES_CHAT_ID))
esc = html.escape

VOL_MID = [5, 20, 45, 60]                  # середина диапазона «обращений в день»; для «60+» — нижняя граница
CHECK_MID = [300, 1000, 3000, 5000]        # середина диапазона среднего чека, ₴; для «5 000+» — нижняя граница
MISS_SHARE = 0.15                          # нижняя граница оценки MedPlatforma (15–30% обращений теряется)
CLOSE_SHARE = 0.2                          # допущение: каждый пятый из потерянных стал бы клиентом
SLIDES = 6
SOURCE_NAMES = {"ai": "сайт /ai-admin", "home": "сайт, главная", "ads": "сайт /google-ads",
                "checklist": "чек-лист на сайте", "dm": "рассылка Дани", "call": "ссылка со созвона",
                "direct": "напрямую в Telegram (не с сайта)"}
FMT_RU = {"tg": "звонок в Telegram", "meet": "Google Meet", "phone": "по телефону"}
BOOKING_WORDS = re.compile(r"запис|запиш|бронь|заброн|book", re.I)
ASKING = re.compile(r"\?|телефон|номер|ім.я|имя|напишіть|напишите|уточн|підтверд|подтверд|оберіть|выберите|"
                    r"який час|какое время|на коли|на когда|phone|name", re.I)


def asks_something(answer: str) -> bool:
    """Бот в этом ответе что-то спрашивает или ждёт данных (идёт запись) — не перебиваем подсказками."""
    return bool(ASKING.search(answer or ""))


class FunnelSG(StatesGroup):
    biz = State()          # «Другое»: человек пишет, какой у него бизнес
    phone = State()        # ждём номер для звонка по телефону


class SalesReply(StatesGroup):
    text = State()         # Даниил пишет ответ посетителю


def on() -> bool:
    return config.FUNNEL_ENABLED


def _all(key: str) -> set[str]:
    return {v for v in FT[key].values() if isinstance(v, str)}


OWNER_TEXTS, CALL_TEXTS = _all("btn_owner"), _all("btn_call")


def ikb(rows) -> InlineKeyboardMarkup:
    """rows: [[(текст, callback) | (текст, 'url:https://…')]]"""
    out = []
    for row in rows:
        r = []
        for text, data in row:
            if data.startswith("url:"):
                r.append(InlineKeyboardButton(text=text, url=data[4:]))
            else:
                r.append(InlineKeyboardButton(text=text, callback_data=data))
        out.append(r)
    return InlineKeyboardMarkup(inline_keyboard=out)


def write_btn(lang: str):
    return (ft(lang, "btn_write"), f"url:https://t.me/{config.SALES_TG}")


def is_staff(uid: int, chat_id: int | None = None) -> bool:
    """Свои: владелец демо, люди из SALES_STAFF_IDS, личка SALES_CHAT_ID или любой участник группы «Заявки»."""
    if chat_id is not None and config.SALES_CHAT_ID < 0 and chat_id == config.SALES_CHAT_ID:
        return True
    return uid in ({config.OWNER_ID, config.SALES_CHAT_ID} | config.SALES_STAFF_IDS) - {0}


def niche_kb(lang: str) -> InlineKeyboardMarkup:
    b = ft(lang, "niche_btn")
    return ikb([[(b["salon"], "fn:salon"), (b["dental"], "fn:dental")],
                [(b["auto"], "fn:auto"), (b["shop"], "fn:shop")],
                [(b["other"], "fn:other")]])


def demo_kb(lang: str, niche: str) -> ReplyKeyboardMarkup:
    samples = i18n.niche_view(niche, lang).samples[:3]
    rows = [[KeyboardButton(text=s)] for s in samples]
    rows.append([KeyboardButton(text=ft(lang, "btn_owner")), KeyboardButton(text=ft(lang, "btn_call"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def guess_niche(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"стомат|зуб|клінік|клиник|медиц|лікар|врач|космет", t):
        return "dental"
    if re.search(r"авто|сто\b|шин|машин|мийк|мойк", t):
        return "auto"
    if re.search(r"магаз|одяг|одеж|взутт|обув|товар|shop|бутік|бутик|інтернет", t):
        return "shop"
    return "salon"


def money(n: float) -> str:
    return f"{int(round(n, -2) if n >= 1000 else round(n)):,}".replace(",", " ")


def when_text(dt: datetime, lang: str) -> str:
    wd = i18n.WEEKDAYS.get(lang, i18n.WEEKDAYS["uk"])[dt.weekday()]
    word = {"ru": "в", "uk": "о", "en": "at"}.get(lang, "о")
    delta = (dt.date() - sales.now().date()).days
    rel = {0: {"ru": "сегодня", "uk": "сьогодні", "en": "today"},
           1: {"ru": "завтра", "uk": "завтра", "en": "tomorrow"}}.get(delta, {}).get(lang, "")
    return (f"{rel}, " if rel else "") + f"{wd} {dt:%d.%m} {word} {dt:%H:%M}"


def fmt_label(lang: str, fmt: str) -> str:
    return ft(lang, "fmt_short").get(fmt, fmt)


def times_word(x: int, lang: str) -> str:
    """«у 3 рази», «у 5 разів» / «в 3 раза», «в 5 раз»."""
    few = x % 10 in (2, 3, 4) and x % 100 not in (12, 13, 14)
    if lang == "en":
        return "times"
    if lang == "ru":
        return "раза" if few else "раз"
    return "рази" if few else "разів"


async def lang_of(user) -> str:
    return await core.ulang(user)


async def tracked(user_id: int, name: str, **params):
    analytics.track(await sales.get(user_id), user_id, name, **params)


# ================================================================ вход

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group_guard(m: Message, state: FSMContext):
    """Группа «Заявки»: бот не ведёт там демо и не отвечает ИИ — только ответ посетителю, /cancel и /funnel."""
    text = m.text or ""
    in_reply = await state.get_state() == SalesReply.text.state
    if text.startswith("/cancel") and in_reply:
        await state.clear()
        return await m.answer("Отменено.")
    if in_reply or text.startswith("/funnel"):
        raise SkipHandler
    return


@router.message(CommandStart())
async def start(m: Message, command: CommandObject, state: FSMContext):
    if not on():
        raise SkipHandler
    await state.clear()
    await core.touch(m.from_user)
    ai.reset(m.from_user.id)
    source, cid = sales.parse_payload(command.args)
    await sales.start(m.from_user.id, source, cid)
    await tracked(m.from_user.id, "bot_start", entry=source)
    lang = await lang_of(m.from_user)
    if source == "checklist":                       # лид-магнит с сайта: сначала чек-лист, потом демо
        url = "https://adrenalinegrowth.com/ru/checklist" if lang == "ru" else "https://adrenalinegrowth.com/checklist"
        await m.answer(ft(lang, "checklist", url=url), disable_web_page_preview=True)
    await m.answer(ft(lang, "intro"), reply_markup=niche_kb(lang))


@router.callback_query(F.data.regexp(r"^fn:(salon|dental|auto|shop|other)$"))
async def pick_niche(cb: CallbackQuery, state: FSMContext):
    lang = await lang_of(cb.from_user)
    k = cb.data[3:]
    await cb.answer()
    if k == "other":
        await state.set_state(FunnelSG.biz)
        return await cb.message.answer(ft(lang, "ask_biz"))
    await choose_niche(cb.message, cb.from_user, k, lang)


@router.message(StateFilter(None), F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def start_window_text(m: Message):
    """Человек не нажал кнопку сферы, а написал текст на стартовом экране: переводим экран на язык сообщения."""
    if not on():
        raise SkipHandler
    p = await sales.get(m.from_user.id)
    if (not p or (p.get("stage") or "start") != "start" or i18n.detect(m.text) is None
            or m.text in OWNER_TEXTS or m.text in CALL_TEXTS):
        raise SkipHandler
    lang = await core.sync_lang(m.from_user, m.text)
    await m.answer(ft(lang, "intro"), reply_markup=niche_kb(lang))


@router.message(FunnelSG.biz, F.text, ~F.text.startswith("/"))
async def other_biz(m: Message, state: FSMContext):
    await state.clear()
    lang = await core.sync_lang(m.from_user, m.text)
    k = guess_niche(m.text)
    await m.answer(ft(lang, "biz_mapped", title=esc(i18n.niche_view(k, lang).title)))
    await choose_niche(m, m.from_user, k, lang, biz_text=m.text[:200])


async def choose_niche(target: Message, user, k: str, lang: str, biz_text: str | None = None):
    await core.touch(user)
    if not await sales.get(user.id):
        await sales.start(user.id, "direct", "")
    await db.set_niche(user.id, k)
    ai.reset(user.id)
    fields = {"biz": k}
    if biz_text:
        fields["biz_text"] = biz_text
    await sales.update(user.id, **fields)
    await sales.advance(user.id, "demo")
    await sales.touch(user.id)
    await tracked(user.id, "demo_niche", niche=k)
    n = i18n.niche_view(k, lang)
    await target.answer(ft(lang, "role", company=esc(n.company)), reply_markup=demo_kb(lang, k))


# ================================================================ после каждого ответа ИИ в демо

async def after_ai(bot: Bot, m: Message, actions, answer: str = "") -> None:
    """Вызывается из bot.converse после ответа ИИ: считаем шаги демо и вовремя подсказываем следующий."""
    if not on():
        return
    uid = m.from_user.id
    p = await sales.get(uid)
    if not p:
        p = await sales.start(uid, "direct", "")
    await sales.touch(uid)
    await sales.advance(uid, "demo")
    n = await sales.bump(uid, "demo_msgs")
    lang = await lang_of(m.from_user)
    if getattr(actions, "want_bot", False):
        await sales.update(uid, want_bot=1)
        await tracked(uid, "want_bot")
        await m.answer(ft(lang, "want_bot"), reply_markup=ikb([[(ft(lang, "btn_book"), "fb:go")], [write_btn(lang)]]))
        if config.SALES_CHAT_ID and config.SALES_CHAT_ID != config.OWNER_ID:
            await notify_sales(bot, "🔥 <b>Хочет такого бота</b> (написал в демо)\n" + await prospect_card(m.from_user))
        return
    if getattr(actions, "lead_id", None) and not p.get("demo_booked"):
        await sales.update(uid, demo_booked=1)
        await tracked(uid, "demo_booking")
        await m.answer(ft(lang, "nudge_booked"))
        await show_owner(m, m.from_user)          # сразу его собственная заявка глазами владельца
        if config.SALES_CHAT_ID and config.SALES_CHAT_ID != config.OWNER_ID:
            lead = await db.get_lead(actions.lead_id)
            if lead:
                await notify_sales(bot, core.lead_card(lead, f"🧪 Посетитель записался в демо как клиент "
                                                             f"({esc(core.who(m.from_user))})"))
        return
    if p.get("demo_booked") or p.get("nudged"):
        return
    if BOOKING_WORDS.search(m.text or m.caption or ""):
        # человек уже сам записывается: подсказка «попробуйте записаться» ему не нужна ни сейчас, ни потом
        return await sales.update(uid, nudged=1)
    # подсказку не вставляем посреди записи: если бот сейчас что-то спрашивает, ждём следующего хода
    if n >= 3 and not asks_something(answer):
        await sales.update(uid, nudged=1)
        await m.answer(ft(lang, "nudge_try_booking"), reply_markup=ikb([[(ft(lang, "btn_owner"), "fo:owner")]]))


# ================================================================ глазами владельца

@router.message(F.text.func(lambda t: t in OWNER_TEXTS))
async def owner_text(m: Message):
    if not on():
        raise SkipHandler
    await show_owner(m, m.from_user)


@router.callback_query(F.data == "fo:owner")
async def owner_cb(cb: CallbackQuery):
    await cb.answer()
    await show_owner(cb.message, cb.from_user)


async def show_owner(target: Message, user):
    lang = await lang_of(user)
    k = await core.current_niche(user)
    lead = await db.last_lead(user.id, k)
    if lead:
        await target.answer(ft(lang, "owner_title") + core.lead_card(lead, lang=lang),
                            reply_markup=core.owner_kb(lead["id"], user.id, lang))
    else:
        n = i18n.niche_view(k, lang)
        tomorrow = (sales.now() + timedelta(days=1)).strftime("%d.%m")
        await target.answer(ft(lang, "owner_sample", company=esc(n.company), service=esc(n.services[0]),
                               date=tomorrow))
    p = await sales.get(user.id) or {}
    rows = [[(ft(lang, "btn_report"), "fo:report"), (ft(lang, "btn_remind"), "fo:remind")]]
    seen = p.get("pitch_seen") if p.get("pitch_seen") is not None else -1
    if seen < SLIDES - 1:                     # презентацию ещё не досмотрел — предлагаем её
        rows.append([(ft(lang, "btn_pitch"), "fpn:0")])
    elif not await sales.active_call(user.id):  # досмотрел, но не записан — сразу запись на звонок
        rows.append([(ft(lang, "btn_book"), "fb:go")])
    await target.answer(ft(lang, "owner_explain"), reply_markup=ikb(rows))
    await sales.update(user.id, owner_seen=1)
    await sales.advance(user.id, "owner")
    await sales.touch(user.id)
    await tracked(user.id, "owner_view", with_lead=bool(lead))


@router.callback_query(F.data.in_({"fo:report", "fo:remind"}))
async def owner_extras(cb: CallbackQuery):
    lang = await lang_of(cb.from_user)
    k = await core.current_niche(cb.from_user)
    if cb.data == "fo:report":
        leads = await db.leads_for(cb.from_user.id, k)
        if not leads:
            return await cb.answer(ft(lang, "need_booking"), show_alert=True)
        await cb.answer()
        return await cb.message.answer_document(BufferedInputFile(leads_to_xlsx(leads), "zayavky.xlsx"),
                                                caption=i18n.t(lang, "report_caption"))
    lead = await db.last_lead(cb.from_user.id, k)
    if not lead:
        return await cb.answer(ft(lang, "need_booking"), show_alert=True)
    await cb.answer()
    await cb.message.answer(reminders.reminder_text(lead, "24h", lang))
    await cb.message.answer(i18n.t(lang, "remind_demo_note"))


# ================================================================ мини-презентация (6 экранов)

def slide(lang: str, i: int) -> tuple[str, InlineKeyboardMarkup]:
    text = ft(lang, f"p{i}", site=config.SITE_URL) if i == 3 else ft(lang, f"p{i}")
    rows = []
    if i == 2:
        v = ft(lang, "volume_opts")
        rows += [[(v[0], "fc:v:0"), (v[1], "fc:v:1")], [(v[2], "fc:v:2"), (v[3], "fc:v:3")]]
    nav = []
    if i > 0:
        nav.append((ft(lang, "btn_back"), f"fp:{i - 1}"))
    if i < SLIDES - 1:
        nav.append((ft(lang, "btn_next"), f"fp:{i + 1}"))
    if nav:
        rows.append(nav)
    rows.append([(ft(lang, "btn_book"), "fb:go")])
    if i == SLIDES - 1:
        rows.append([write_btn(lang)])
    return text, ikb(rows)


async def _show(cb: CallbackQuery, text: str, markup, new: bool):
    if new:
        return await cb.message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    try:
        await cb.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.regexp(r"^fpn?:\d$"))
async def pitch(cb: CallbackQuery):
    lang = await lang_of(cb.from_user)
    new, i = cb.data.startswith("fpn"), int(cb.data[-1])
    i = max(0, min(SLIDES - 1, i))
    await cb.answer()
    text, markup = slide(lang, i)
    await _show(cb, text, markup, new)
    p = await sales.get(cb.from_user.id) or {}
    if i > (p.get("pitch_seen") if p.get("pitch_seen") is not None else -1):
        await sales.update(cb.from_user.id, pitch_seen=i)
    await sales.advance(cb.from_user.id, "pitch")
    await sales.touch(cb.from_user.id)
    await tracked(cb.from_user.id, "pitch_view", slide=i + 1)


@router.callback_query(F.data.regexp(r"^fc:[vc]:[0-3]$"))
async def calc(cb: CallbackQuery):
    lang = await lang_of(cb.from_user)
    kind, j = cb.data[3], int(cb.data[-1])
    await cb.answer()
    await sales.touch(cb.from_user.id)
    if kind == "v":
        await sales.update(cb.from_user.id, volume=str(j))
        c = ft(lang, "check_opts")
        return await _show(cb, ft(lang, "p2_check"), ikb([
            [(c[0], "fc:c:0"), (c[1], "fc:c:1")], [(c[2], "fc:c:2"), (c[3], "fc:c:3")],
            [(ft(lang, "btn_back"), "fp:2")]]), False)
    await sales.update(cb.from_user.id, avg_check=str(j))
    p = await sales.get(cb.from_user.id)
    vol = int(p.get("volume") or 1)
    month = VOL_MID[vol] * 30
    lost = round(month * MISS_SHARE)
    loss = lost * CLOSE_SHARE * CHECK_MID[j]
    x = loss / (160 * config.USD_UAH)
    ratio = ft(lang, "ratio", x=int(x), word=times_word(int(x), lang)) if x >= 2 else ""
    clients = round(lost * CLOSE_SHARE)
    await sales.update(cb.from_user.id, calc=f"~{lost} обращений/мес без быстрого ответа → ~{clients} клиентов "
                                             f"≈ {money(loss)} ₴/мес (оценка)")
    await tracked(cb.from_user.id, "calc_done", volume=vol, check=j)
    await _show(cb, ft(lang, "p2_result", month=money(month), lost=money(lost), money=money(loss), ratio=ratio),
                ikb([[(ft(lang, "btn_back"), "fp:2"), (ft(lang, "btn_next"), "fp:3")],
                     [(ft(lang, "btn_book"), "fb:go")]]), False)


# ================================================================ квалификация и запись на звонок

@router.message(Command("call"))
async def call_cmd(m: Message):
    if not on():
        raise SkipHandler
    await go_book(m, m.from_user)


@router.message(F.text.func(lambda t: t in CALL_TEXTS))
async def call_text(m: Message):
    if not on():
        raise SkipHandler
    await go_book(m, m.from_user)


@router.callback_query(F.data == "fb:go")
async def call_cb(cb: CallbackQuery):
    await cb.answer()
    await go_book(cb.message, cb.from_user)


async def go_book(target: Message, user):
    lang = await lang_of(user)
    if not await sales.get(user.id):
        await sales.start(user.id, "direct", "")
    await sales.touch(user.id)
    c = await sales.active_call(user.id)
    if c:
        return await target.answer(ft(lang, "already_booked", when=when_text(datetime.fromisoformat(c["at"]), lang)),
                                   reply_markup=call_kb(lang, c["id"]))
    p = await sales.get(user.id)
    if p.get("volume") in (None, ""):
        await sales.advance(user.id, "qualify")
        v = ft(lang, "volume_opts")
        return await target.answer(ft(lang, "q_volume"), reply_markup=ikb(
            [[(v[0], "fq:v:0"), (v[1], "fq:v:1")], [(v[2], "fq:v:2"), (v[3], "fq:v:3")]]))
    if p.get("handler") in (None, ""):
        await sales.advance(user.id, "qualify")
        h = ft(lang, "handler_opts")
        return await target.answer(ft(lang, "q_handler"), reply_markup=ikb([[(h[0], "fq:h:0"), (h[1], "fq:h:1")],
                                                                             [(h[2], "fq:h:2")], [(h[3], "fq:h:3")]]))
    await show_days(target, user, lang)


@router.callback_query(F.data.regexp(r"^fq:[vh]:[0-3]$"))
async def qualify(cb: CallbackQuery):
    kind, j = cb.data[3], cb.data[-1]
    await sales.update(cb.from_user.id, **({"volume": j} if kind == "v" else {"handler": j}))
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await go_book(cb.message, cb.from_user)


def day_label(d: date, lang: str) -> str:
    return f"{i18n.WEEKDAYS.get(lang, i18n.WEEKDAYS['uk'])[d.weekday()]} {d:%d.%m}"


async def show_days(target: Message, user, lang: str, note_key: str = "pick_day", edit: bool = False):
    slots = await sales.free_slots()
    await sales.advance(user.id, "slots")
    await sales.update(user.id, slots_seen=1)
    await tracked(user.id, "slots_view")
    if not slots:
        return await target.answer(ft(lang, "no_slots", tg=config.SALES_TG), reply_markup=ikb([[write_btn(lang)]]))
    days = list(slots)[:4]
    rows = [[(day_label(d, lang), f"fs:d:{d.isoformat()}") for d in days[:2]]]
    if days[2:]:
        rows.append([(day_label(d, lang), f"fs:d:{d.isoformat()}") for d in days[2:]])
    text = ft(lang, note_key) if note_key == "pick_day" else ft(lang, note_key) + "\n\n" + ft(lang, "pick_day")
    if edit:
        try:
            return await target.edit_text(text, reply_markup=ikb(rows))
        except TelegramBadRequest:
            pass
    await target.answer(text, reply_markup=ikb(rows))


@router.callback_query(F.data == "fs:back")
async def days_back(cb: CallbackQuery):
    await cb.answer()
    await show_days(cb.message, cb.from_user, await lang_of(cb.from_user), edit=True)


@router.callback_query(F.data.regexp(r"^fs:d:\d{4}-\d\d-\d\d$"))
async def pick_day(cb: CallbackQuery):
    lang = await lang_of(cb.from_user)
    d = date.fromisoformat(cb.data[5:])
    times = (await sales.free_slots()).get(d, [])
    await cb.answer()
    if not times:
        return await show_days(cb.message, cb.from_user, lang, "slot_taken", edit=True)
    btns = [(f"{t:%H:%M}", f"fs:t:{t:%Y-%m-%dT%H%M}") for t in times]
    rows = [btns[i:i + 4] for i in range(0, len(btns), 4)]
    rows.append([(ft(lang, "btn_back"), "fs:back")])
    try:
        await cb.message.edit_text(ft(lang, "pick_time", day=day_label(d, lang)), reply_markup=ikb(rows))
    except TelegramBadRequest:
        await cb.message.answer(ft(lang, "pick_time", day=day_label(d, lang)), reply_markup=ikb(rows))


def parse_stamp(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H%M").replace(tzinfo=sales.TZ)


async def slot_free(at: datetime) -> bool:
    return at in (await sales.free_slots()).get(at.date(), [])


@router.callback_query(F.data.regexp(r"^fs:t:\d{4}-\d\d-\d\dT\d{4}$"))
async def pick_time(cb: CallbackQuery):
    lang = await lang_of(cb.from_user)
    stamp = cb.data[5:]
    at = parse_stamp(stamp)
    await cb.answer()
    if not await slot_free(at):
        return await show_days(cb.message, cb.from_user, lang, "slot_taken", edit=True)
    f = ft(lang, "fmt")
    try:
        await cb.message.edit_text(ft(lang, "pick_format", when=when_text(at, lang)), reply_markup=ikb(
            [[(f["tg"], f"ff:tg:{stamp}")], [(f["meet"], f"ff:meet:{stamp}")], [(f["phone"], f"ff:phone:{stamp}")],
             [(ft(lang, "btn_back"), "fs:back")]]))
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.regexp(r"^ff:(tg|meet|phone):\d{4}-\d\d-\d\dT\d{4}$"))
async def pick_format(cb: CallbackQuery, state: FSMContext, bot: Bot):
    lang = await lang_of(cb.from_user)
    _, fmt, stamp = cb.data.split(":", 2)
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    old = await sales.active_call(cb.from_user.id)
    if old:
        # уже есть звонок (нажали старые кнопки времени): молча второй не создаём и не переносим — спрашиваем
        return await cb.message.answer(
            ft(lang, "move_confirm", old=when_text(datetime.fromisoformat(old["at"]), lang),
               new=when_text(parse_stamp(stamp), lang), fmt=fmt_label(lang, fmt)),
            reply_markup=ikb([[(ft(lang, "btn_move_yes"), f"fm:{fmt}:{stamp}")],
                              [(ft(lang, "btn_move_keep"), "fm:keep")]]))
    await go_format(bot, cb.message, cb.from_user, lang, fmt, stamp, state)


async def go_format(bot: Bot, target: Message, user, lang: str, fmt: str, stamp: str, state: FSMContext,
                    replace: int | None = None):
    if fmt == "phone":
        await state.set_state(FunnelSG.phone)
        await state.update_data(stamp=stamp, replace=replace)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=ft(lang, "btn_share_phone"), request_contact=True)]],
                                 resize_keyboard=True, one_time_keyboard=True)
        return await target.answer(ft(lang, "ask_phone"), reply_markup=kb)
    await book(bot, target, user, lang, parse_stamp(stamp), fmt, replace=replace)


@router.callback_query(F.data.regexp(r"^fm:(keep|(tg|meet|phone):\d{4}-\d\d-\d\dT\d{4})$"))
async def move_call(cb: CallbackQuery, state: FSMContext, bot: Bot):
    lang = await lang_of(cb.from_user)
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    old = await sales.active_call(cb.from_user.id)
    if cb.data == "fm:keep":
        if old:
            await cb.message.answer(ft(lang, "move_kept", when=when_text(datetime.fromisoformat(old["at"]), lang)),
                                    reply_markup=call_kb(lang, old["id"]))
        return
    _, fmt, stamp = cb.data.split(":", 2)
    await go_format(bot, cb.message, cb.from_user, lang, fmt, stamp, state, replace=old["id"] if old else None)


@router.message(FunnelSG.phone, F.contact)
async def got_contact(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await book(bot, m, m.from_user, await lang_of(m.from_user), parse_stamp(data["stamp"]), "phone",
               m.contact.phone_number, replace=data.get("replace"))


@router.message(FunnelSG.phone, F.text, ~F.text.startswith("/"))
async def got_phone_text(m: Message, state: FSMContext, bot: Bot):
    lang = await lang_of(m.from_user)
    if sum(ch.isdigit() for ch in m.text) < 9:
        return await m.answer(ft(lang, "bad_phone"))
    data = await state.get_data()
    await state.clear()
    await book(bot, m, m.from_user, lang, parse_stamp(data["stamp"]), "phone", m.text.strip()[:30],
               replace=data.get("replace"))


@router.message(F.contact, F.chat.type == "private")
async def contact_outside_booking(m: Message, bot: Bot):
    """Контакт прислали не на шаге «номер для звонка». Если есть звонок без номера — прикрепляем номер к нему.
    Дальше (или если ИИ в демо как раз спросил телефон) контакт уходит в обычный диалог: bot.on_contact."""
    if not on():
        raise SkipHandler
    c = await sales.active_call(m.from_user.id)
    own = not m.contact.user_id or m.contact.user_id == m.from_user.id
    if not (c and own and not c.get("phone")):
        raise SkipHandler
    phone = m.contact.phone_number
    await sales.set_call_phone(c["id"], phone)
    await db.set_profile(m.from_user.id, None, phone)
    at = datetime.fromisoformat(c["at"])
    await notify_sales(bot, f"📱 {esc(core.who(m.from_user))} прислал номер {esc(phone)} к звонку "
                            f"{when_text(at, 'ru')} ({FMT_RU.get(c['format'], c['format'])})")
    last_bot = next((h["content"] for h in reversed(ai.recent(m.from_user.id, await core.current_niche(m.from_user)))
                     if h["role"] == "assistant"), "")
    if re.search(r"телефон|номер|phone", str(last_bot), re.I):
        raise SkipHandler                      # ИИ в демо ждёт номер для записи клиента — пусть продолжит
    lang = await lang_of(m.from_user)
    await m.answer(ft(lang, "phone_added", phone=esc(phone), when=when_text(at, lang)),
                   reply_markup=ReplyKeyboardRemove())


def call_kb(lang: str, call_id: int) -> InlineKeyboardMarkup:
    return ikb([[(ft(lang, "btn_resched"), f"fb:re:{call_id}"), (ft(lang, "btn_cancel_call"), f"fb:x:{call_id}")]])


def next_step(lang: str, fmt: str) -> str:
    if fmt == "meet" and config.MEET_URL:
        return ft(lang, "next_meet_url", url=esc(config.MEET_URL))
    return ft(lang, "next_" + fmt) if fmt in ("tg", "meet", "phone") else ""


def meet_line(lang: str, fmt: str) -> str:
    return ft(lang, "meet_link", url=esc(config.MEET_URL)) if fmt == "meet" and config.MEET_URL else ""


async def book(bot: Bot, target: Message, user, lang: str, at: datetime, fmt: str, phone: str = "",
               replace: int | None = None):
    """Запись на звонок. replace — id звонка, который человек подтвердил перенести на это время."""
    old = await sales.get_call(replace) if replace else None
    if old and old["status"] not in ("booked", "confirmed"):
        old = None
    if old and old["at"] == sales._iso(at):            # то же время, другой формат: сначала освобождаем окно
        await sales.set_call_status(old["id"], "resched")
    try:
        call_id = await sales.book_call(user.id, user.username, user.full_name, at, fmt, phone)
    except ValueError:
        return await show_days(target, user, lang, "slot_taken")
    moved = ""
    if old:
        await sales.set_call_status(old["id"], "resched")
        await sales.update(user.id, call_id=call_id)
        moved = when_text(datetime.fromisoformat(old["at"]), "ru")
    if phone:
        await db.set_profile(user.id, None, phone)
    await tracked(user.id, "call_booked", fmt=fmt)
    head = ft(lang, "moved_from", old=when_text(datetime.fromisoformat(old["at"]), lang)) if old else ""
    await target.answer(head + ft(lang, "booked", when=when_text(at, lang), fmt=fmt_label(lang, fmt),
                                  next=next_step(lang, fmt)),
                        reply_markup=call_kb(lang, call_id), disable_web_page_preview=True)
    meet_todo = (f"🔗 Клиенту отправлена ссылка: {esc(config.MEET_URL)}" if config.MEET_URL else
                 "🔗 Нужна ссылка на Google Meet: создай встречу и отправь кнопкой «Написать через бота»")
    todo = {"meet": meet_todo, "phone": "☎️ Позвонить на номер выше", "tg": "📞 Позвонить в Telegram"}.get(fmt, "")
    title = (f"🔁 <b>Перенос звонка</b> с {moved} → {when_text(at, 'ru')} (Киев), {FMT_RU.get(fmt, fmt)}" if moved
             else f"📞 <b>Запись на звонок</b> — {when_text(at, 'ru')} (Киев), {FMT_RU.get(fmt, fmt)}")
    card = (title + (f"\n📱 {esc(phone)}" if phone else "") + "\n" + await prospect_card(user)
            + (f"\n\n{todo}" if todo else ""))
    await notify_sales(bot, card, ikb([[("✅ Подтвердить", f"sc:ok:{call_id}"), ("🔁 Другое время", f"sc:re:{call_id}")],
                                       [("✉️ Написать через бота", f"sr:{user.id}")]]))


@router.callback_query(F.data.regexp(r"^fb:(re|x):\d+$"))
async def user_call_action(cb: CallbackQuery, bot: Bot):
    lang = await lang_of(cb.from_user)
    _, act, cid = cb.data.split(":")
    c = await sales.get_call(int(cid))
    if not c or c["user_id"] != cb.from_user.id or c["status"] not in ("booked", "confirmed"):
        return await cb.answer("—", show_alert=False)
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    when = when_text(datetime.fromisoformat(c["at"]), "ru")
    if act == "x":
        await sales.set_call_status(c["id"], "cancelled")
        await sales.touch(cb.from_user.id)
        await tracked(cb.from_user.id, "call_cancelled")
        await cb.message.answer(ft(lang, "call_cancelled"))
        return await notify_sales(bot, f"❌ {esc(core.who(cb.from_user))} отменил звонок {when}")
    await sales.set_call_status(c["id"], "resched")
    await notify_sales(bot, f"🔁 {esc(core.who(cb.from_user))} переносит звонок {when}, выбирает новое время")
    await show_days(cb.message, cb.from_user, lang)


# ================================================================ кнопки Даниила

@router.callback_query(F.data.regexp(r"^sc:(ok|re):\d+$"))
async def sales_action(cb: CallbackQuery, bot: Bot):
    if not is_staff(cb.from_user.id, cb.message.chat.id):
        return await cb.answer("Эта кнопка только для ADrenaline.", show_alert=True)
    _, act, cid = cb.data.split(":")
    c = await sales.get_call(int(cid))
    if not c:
        return await cb.answer("Звонок не найден", show_alert=True)
    if c["status"] not in ("booked", "confirmed"):
        return await cb.answer(f"Статус уже: {c['status']}", show_alert=True)
    ulang = i18n.resolve(await db.get_user(c["user_id"]))
    at = datetime.fromisoformat(c["at"])
    try:
        if act == "ok":
            await sales.set_call_status(c["id"], "confirmed")
            await bot.send_message(c["user_id"], ft(ulang, "call_confirmed", when=when_text(at, ulang))
                                   + meet_line(ulang, c["format"]), disable_web_page_preview=True)
            note = "✅ Подтверждено, клиенту отправлено"
        else:
            await sales.set_call_status(c["id"], "resched")
            await bot.send_message(c["user_id"], ft(ulang, "call_resched_req"))
            fake = await bot.send_message(c["user_id"], "📅")
            await show_days(fake, SimpleUser(c["user_id"]), ulang, edit=True)
            note = "🔁 Клиента попросили выбрать другое время"
    except (TelegramForbiddenError, TelegramBadRequest):
        note = "⚠️ Не удалось написать клиенту (заблокировал бота?)"
    await cb.answer()
    try:
        await cb.message.edit_text(cb.message.html_text + f"\n\n<b>{note}</b>",
                                   reply_markup=ikb([[("✉️ Написать через бота", f"sr:{c['user_id']}")]]))
    except TelegramBadRequest:
        pass


class SimpleUser:
    """Минимальный «пользователь» для show_days, когда действие инициирует Даниил, а не сам посетитель."""

    def __init__(self, uid: int):
        self.id = uid


@router.callback_query(F.data.regexp(r"^sr:\d+$"))
async def sales_reply_start(cb: CallbackQuery, state: FSMContext):
    if not is_staff(cb.from_user.id, cb.message.chat.id):
        return await cb.answer("Эта кнопка только для ADrenaline.", show_alert=True)
    await state.set_state(SalesReply.text)
    to = int(cb.data[3:])
    await state.update_data(to=to)
    await cb.answer()
    who_ = await _who_id(to)
    # ForceReply: в группе бот видит ответ на своё сообщение даже с включённым режимом приватности
    await cb.message.answer(f"✍️ Ответьте на это сообщение — отправлю {who_} от имени «Даниил, ADrenaline». "
                            "Отмена: /cancel", reply_markup=ForceReply(input_field_placeholder="Сообщение посетителю"))


@router.message(SalesReply.text, F.text, ~F.text.startswith("/"))
async def sales_reply_send(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    to = data["to"]
    lang = i18n.resolve(await db.get_user(to))
    try:
        await bot.send_message(to, ft(lang, "sales_prefix", text=esc(m.text)))
    except Exception:
        return await m.answer("Не удалось отправить: возможно, посетитель заблокировал бота.")
    await m.answer(f"✅ Отправлено {await _who_id(to)}.")


async def _who_id(uid: int) -> str:
    """Кому уходит сообщение: @ник или имя посетителя."""
    u = await db.get_user(uid) or {}
    p = await sales.get(uid) or {}
    nick = u.get("username") or p.get("username")
    return f"@{nick}" if nick else esc(u.get("name") or u.get("first_name") or f"id {uid}")


async def notify_sales(bot: Bot, text: str, markup=None) -> bool:
    if not config.SALES_CHAT_ID:
        log.warning("SALES_CHAT_ID/OWNER_ID не задан: %s", text[:120])
        return False
    try:
        await bot.send_message(config.SALES_CHAT_ID, text[:4000], reply_markup=markup)
        return True
    except Exception:
        log.exception("не удалось уведомить ADrenaline")
        return False


def _opt(key: str, idx) -> str:
    try:
        return FT[key]["ru"][int(idx)]
    except (TypeError, ValueError, IndexError):
        return "—"


async def prospect_card(user) -> str:
    """Что Даниилу нужно знать перед звонком: кто, какая сфера, объём, кто отвечает, что делал в демо."""
    p = await sales.get(user.id) or {}
    biz = NICHES[p["biz"]].title if p.get("biz") in NICHES else "—"
    if p.get("biz_text"):
        biz += f" («{esc(p['biz_text'])}»)"
    src = SOURCE_NAMES.get(p.get("source") or "direct", p.get("source") or "—")
    seen = p.get("pitch_seen")
    pitch = f"{seen + 1}/{SLIDES}" if isinstance(seen, int) and seen >= 0 else "не открывал"
    yes = lambda v: "✅" if v else "нет"  # noqa: E731
    lines = [
        f"👤 {esc(core.who(user))} · id {user.id}",
        f"🏢 Сфера: {biz}",
        f"📈 Обращений в день: {_opt('volume_opts', p.get('volume'))} · средний чек: {_opt('check_opts', p.get('avg_check'))}",
        f"🙋 Сейчас отвечает: {_opt('handler_opts', p.get('handler'))}",
    ]
    if p.get("calc"):
        lines.append(f"🧮 Калькулятор: {esc(p['calc'])}")
    lines += [
        f"🧭 Источник: {esc(src)}" + (" (GA связан)" if p.get("cid") else ""),
        f"🎬 Демо: {p.get('demo_msgs') or 0} сообщ. · записался как клиент {yes(p.get('demo_booked'))} · "
        f"видел заявку владельца {yes(p.get('owner_seen'))} · презентация {pitch}",
    ]
    return "\n".join(lines)


# ================================================================ фоллоу-апы и напоминания о звонке

def followup_kb(lang: str, step: int) -> InlineKeyboardMarkup:
    book_btn = (ft(lang, "btn_book"), "fb:go")
    stop_btn = (ft(lang, "btn_stop"), "fu:stop")
    if step == 1:
        return ikb([[(ft(lang, "btn_calc"), "fpn:2")], [book_btn]])
    if step == 3:
        return ikb([[book_btn], [write_btn(lang)]])
    return ikb([[book_btn], [stop_btn]])


@router.callback_query(F.data == "fu:stop")
async def followup_stop(cb: CallbackQuery):
    lang = await lang_of(cb.from_user)
    await sales.update(cb.from_user.id, opted_out=1, fu_next=None)
    await tracked(cb.from_user.id, "opt_out")
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await cb.message.answer(ft(lang, "stopped"))


async def run_once(bot: Bot, at: datetime | None = None) -> dict:
    """Отправляет созревшие фоллоу-апы и напоминания о звонках. Отметка ставится ДО отправки."""
    sent = {"followups": 0, "reminders": 0}
    if config.FOLLOWUPS_ENABLED:
        for p in await sales.due_followups(at):
            uid, step = p["user_id"], p.get("fu_step") or 0
            await sales.mark_followup_sent(uid)
            lang = i18n.resolve(await db.get_user(uid))
            text = ft(lang, f"fu{step + 1}", site=config.SITE_URL, tg=config.SALES_TG)
            try:
                await bot.send_message(uid, text, reply_markup=followup_kb(lang, step), disable_web_page_preview=True)
                sent["followups"] += 1
                analytics.track(p, uid, "followup_sent", step=step + 1)
            except TelegramForbiddenError:
                await sales.update(uid, opted_out=2, fu_next=None)       # заблокировал бота
            except Exception:
                log.warning("фоллоу-ап %s для %s не отправлен", step + 1, uid, exc_info=True)
    for c in await sales.due_call_reminders(at):
        await sales.mark_call_reminded(c["id"])
        lang = i18n.resolve(await db.get_user(c["user_id"]))
        at_dt = datetime.fromisoformat(c["at"])
        try:
            await bot.send_message(c["user_id"], ft(lang, "call_reminder", when=when_text(at_dt, lang),
                                                    fmt=fmt_label(lang, c["format"])) + meet_line(lang, c["format"]),
                                   reply_markup=call_kb(lang, c["id"]), disable_web_page_preview=True)
            sent["reminders"] += 1
        except Exception:
            log.warning("напоминание о звонке №%s не отправлено", c["id"], exc_info=True)
        who_ = "@" + c["username"] if c.get("username") else esc(c.get("name") or str(c["user_id"]))
        await notify_sales(bot, f"⏰ Скоро звонок: <b>{when_text(at_dt, 'ru')}</b>, {FMT_RU.get(c['format'], c['format'])} · "
                                f"{who_}" + (f" · 📱 {esc(c['phone'])}" if c.get("phone") else ""),
                           ikb([[("✉️ Написать через бота", f"sr:{c['user_id']}")]]))
    return sent


async def loop(bot: Bot, interval: int | None = None):
    interval = interval or config.FUNNEL_CHECK_SECONDS
    log.info("Воронка: фоллоу-апы %s, проверка раз в %s с", "вкл" if config.FOLLOWUPS_ENABLED else "выкл", interval)
    while True:
        try:
            await run_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ошибка цикла воронки")
        await asyncio.sleep(interval)


# ================================================================ статистика для команды

@router.message(Command("funnel"))
async def funnel_stats(m: Message, command: CommandObject):
    if not is_staff(m.from_user.id, m.chat.id):
        raise SkipHandler
    days = int(command.args) if (command.args or "").isdigit() else 30
    s = await sales.funnel_stats(days)
    names = {"start": "Запустили бота", "niche": "Выбрали сферу", "demo": "Начали демо", "owner": "Глазами владельца",
             "pitch": "Открыли презентацию", "qualify": "Начали запись", "slots": "Увидели окна", "booked": "Записались"}
    total = s["total"] or 1
    lines = [f"📊 <b>Воронка демо за {days} дн.</b>\n"]
    for k in sales.STAGES:
        if k == "niche":
            continue
        v = s["stages"][k]
        lines.append(f"{names[k]}: <b>{v}</b> ({round(100 * v / total)}%)")
    lines += ["", f"Записались в демо как клиент: {s['demo_booked']}", f"Писали «хочу такого бота»: {s['want_bot']}",
              f"Звонков: {s['calls']} (отменено {s['calls_cancelled']})",
              f"Отписались: {s['opted_out']} · заблокировали: {s['blocked']}", "", "<b>Источники</b> (старты → записи):"]
    for src, v in sorted(s["by_source"].items(), key=lambda x: -x[1]["start"]):
        lines.append(f"• {esc(SOURCE_NAMES.get(src, src))}: {v['start']} → {v['booked']}")
    await m.answer("\n".join(lines))
