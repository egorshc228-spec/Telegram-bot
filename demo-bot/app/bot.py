"""Telegram: кнопочная витрина. Клиент сам выбирает компанию и пункты, смотрит, что умеет бот."""
import html
import logging
from datetime import date

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)

from . import ai, booking, config, db
from .booking.base import BookingError
from .niches import NICHES
from .report import leads_to_xlsx

log = logging.getLogger("bot")
router = Router()

WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
esc = html.escape


class Book(StatesGroup):
    name = State()
    phone = State()


class Chat(StatesGroup):
    active = State()


class Want(StatesGroup):
    text = State()


# ---------- клавиатуры и тексты ----------

def kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


def home_kb():
    rows = [[(f"{n.emoji} {n.title}", f"n:{k}")] for k, n in NICHES.items()]
    rows += [[("🧭 Как это работает", "how")], [("🚀 Хочу такого бота", "want")]]
    return kb(rows)


WELCOME = (
    "👋 <b>Это демо AI-бота для бизнеса в Telegram.</b>\n\n"
    "Выберите нишу и побудьте клиентом: узнайте цены, запишитесь, пришлите фото, задайте вопрос своими "
    "словами. Затем посмотрите, что при этом получит <b>владелец</b>: заявку с кнопками и Excel-отчёт.\n\n"
    "Все компании вымышленные, данные демонстрационные."
)

HOW = (
    "🧭 <b>Как это работает</b>\n\n"
    "<pre>Клиент пишет в Telegram\n"
    "        ↓\n"
    "Бот (Claude) читает прайс и FAQ компании\n"
    "        ↓\n"
    "Отвечает, смотрит фото, записывает\n"
    "        ↓\n"
    "Заявка летит владельцу в Telegram\n"
    "        ↓\n"
    "Владелец: ✅ Подтвердить / 💬 Связаться\n"
    "        ↓\n"
    "Excel-отчёт по всем заявкам</pre>\n"
    "<b>Что умеет бот:</b>\n"
    "• отвечает 24/7 по вашему прайсу и FAQ, не выдумывает цены\n"
    "• понимает свободный текст и фото\n"
    "• записывает клиентов и собирает контакты\n"
    "• передаёт сложные вопросы человеку\n"
    "• присылает заявки и отчёты в Excel\n\n"
    "Под ваш бизнес: загружаем ваш прайс, график и частые вопросы, и бот готов за 1–2 дня."
)


def niche_menu_kb(k: str):
    n = NICHES[k]
    return kb([
        [("📋 Услуги и цены", f"p:{k}"), ("🕒 График и адрес", f"h:{k}")],
        [("❓ Частые вопросы", f"f:{k}"), (n.book_label, f"b:{k}")],
        [("💬 Спросить своими словами", f"ai:{k}"), (n.photo_label, f"ph:{k}")],
        [("👔 Что увидит владелец", f"ow:{k}"), ("📊 Excel-отчёт", f"xl:{k}")],
        [("⬅ Все компании", "home")],
    ])


def back_kb(k: str):
    return kb([[("⬅ Меню компании", f"n:{k}")]])


async def show(cb: CallbackQuery, text: str, markup=None):
    """Редактирует сообщение, а если нельзя (например, было фото или файл), присылает новое."""
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=markup)
    await cb.answer()


def lead_card(l: dict, title: str = "🔔 Новая заявка") -> str:
    n = NICHES.get(l["niche"])
    status = {"new": "", "ok": "\n✅ <b>Подтверждена</b>", "no": "\n❌ <b>Отклонена</b>"}[l["status"]]
    return (
        f"{title} №{l['id']}\n🏢 {esc(n.company if n else l['niche'])}\n"
        f"👤 {esc(l['name'])}   📞 {esc(l['phone'])}\n"
        f"🧾 {esc(l['service'])} — {l['price']} ₴\n📅 {l['date']} в {l['time']}\n"
        + (f"💬 {esc(l['comment'])}\n" if l["comment"] else "")
        + (f"🗂 {esc(l['crm'])} №{esc(l['external_id'])}\n" if l.get("external_id") else "")
        + f"Источник: {esc(l['source'])}{status}"
    )


def owner_kb(lead_id: int):
    return kb([[("✅ Подтвердить", f"ok:{lead_id}"), ("❌ Отклонить", f"no:{lead_id}")],
               [("💬 Связаться с клиентом", f"call:{lead_id}")]])


async def save_lead(bot: Bot, user, niche: str, data: dict, source: str) -> int:
    """Создаёт запись в CRM (если подключена), затем сохраняет заявку и уведомляет владельца.
    BookingError (слот занят, CRM недоступна) пробрасывается вызывающему."""
    bk = await booking.create(niche, data["service"], date.fromisoformat(data["date"]), data["time"],
                              data["name"], data["phone"], data.get("comment", ""))
    lead_id = await db.add_lead(
        user.id, user.username, niche, data["service"], data["price"], data["date"], data["time"],
        data["name"], data["phone"], data.get("comment", ""), source,
        external_id=bk.external_id if bk else "", crm=bk.system if bk else "",
    )
    if config.OWNER_ID and config.OWNER_ID != user.id:
        try:
            l = await db.get_lead(lead_id)
            who = f"@{user.username}" if user.username else f"id {user.id}"
            await bot.send_message(config.OWNER_ID, lead_card(l, f"🔔 {'Новая заявка' if booking.is_live(niche) else 'Демо-заявка'} ({esc(who)})"),
                                   reply_markup=owner_kb(lead_id))
        except Exception:
            log.exception("не удалось отправить заявку владельцу")
    return lead_id


# ---------- старт и общие разделы ----------

@router.message(CommandStart())
@router.message(Command("menu"))
async def start(m: Message, state: FSMContext):
    await state.clear()
    ai.reset(m.from_user.id)
    await db.touch_user(m.from_user.id, m.from_user.username)
    await m.answer(WELCOME, reply_markup=home_kb())


@router.callback_query(F.data == "home")
async def home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(cb, WELCOME, home_kb())


@router.message(Command("how"))
async def how_cmd(m: Message):
    await m.answer(HOW, reply_markup=kb([[("🚀 Хочу такого бота", "want")], [("⬅ Меню", "home")]]))


@router.callback_query(F.data == "how")
async def how(cb: CallbackQuery):
    await show(cb, HOW, kb([[("🚀 Хочу такого бота", "want")], [("⬅ Меню", "home")]]))


@router.callback_query(F.data.startswith("n:"))
async def niche_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    k = cb.data[2:]
    n = NICHES[k]
    ai.reset(cb.from_user.id)
    await show(cb, f"{n.emoji} <b>{esc(n.company)}</b>\n{esc(n.about)}\n\n"
                   f"Вы сейчас в роли клиента. Выберите пункт:", niche_menu_kb(k))


@router.callback_query(F.data.startswith("p:"))
async def prices(cb: CallbackQuery):
    k = cb.data[2:]
    n = NICHES[k]
    lines = "\n".join(f"• {esc(s[0])} — <b>{s[1]} ₴</b> (~{s[2]} мин)" for s in n.services)
    await show(cb, f"📋 <b>{esc(n.company)}: услуги и цены</b>\n\n{lines}",
               kb([[(n.book_label, f"b:{k}")], [("⬅ Меню компании", f"n:{k}")]]))


@router.callback_query(F.data.startswith("h:"))
async def hours(cb: CallbackQuery):
    k = cb.data[2:]
    n = NICHES[k]
    await show(cb, f"🕒 <b>График:</b> {esc(n.hours)}\n📍 <b>Адрес:</b> {esc(n.address)}", back_kb(k))


@router.callback_query(F.data.startswith("f:"))
async def faq(cb: CallbackQuery):
    k = cb.data[2:]
    n = NICHES[k]
    rows = [[(q, f"fq:{k}:{i}")] for i, (q, _) in enumerate(n.faq)] + [[("⬅ Меню компании", f"n:{k}")]]
    await show(cb, "❓ <b>Частые вопросы</b>\nВыберите вопрос:", kb(rows))


@router.callback_query(F.data.startswith("fq:"))
async def faq_answer(cb: CallbackQuery):
    _, k, i = cb.data.split(":")
    q, a = NICHES[k].faq[int(i)]
    await show(cb, f"❓ <b>{esc(q)}</b>\n\n{esc(a)}",
               kb([[("❓ Другие вопросы", f"f:{k}")], [("⬅ Меню компании", f"n:{k}")]]))


# ---------- запись кнопками ----------

@router.callback_query(F.data.startswith("b:"))
async def book_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    k = cb.data[2:]
    n = NICHES[k]
    rows = [[(f"{s[0]} — {s[1]} ₴", f"bs:{k}:{i}")] for i, s in enumerate(n.services)]
    rows.append([("⬅ Меню компании", f"n:{k}")])
    await show(cb, "1️⃣ Выберите услугу:", kb(rows))


@router.callback_query(F.data.startswith("bs:"))
async def book_service(cb: CallbackQuery):
    _, k, i = cb.data.split(":")
    days = ai.upcoming_days()
    try:
        res = await booking.free_slots_days(k, NICHES[k].services[int(i)][0], days)
    except BookingError as e:
        return await show(cb, f"⚠️ {esc(str(e))}", kb([[("⬅ Назад", f"b:{k}")]]))
    rows = [[(f"{WD[d.weekday()]} {d.strftime('%d.%m')}", f"bd:{k}:{i}:{j}")]
            for j, d in enumerate(days) if res.get(d)]
    if not rows:
        return await show(cb, "На ближайшие дни свободного времени нет. Попробуйте позже или выберите другую услугу.",
                          kb([[("⬅ Назад", f"b:{k}")]]))
    rows.append([("⬅ Назад", f"b:{k}")])
    await show(cb, "2️⃣ Выберите день:", kb(rows))


@router.callback_query(F.data.startswith("bd:"))
async def book_day(cb: CallbackQuery):
    _, k, i, j = cb.data.split(":")
    d = ai.upcoming_days()[int(j)]
    try:
        slots = (await booking.free_slots(k, NICHES[k].services[int(i)][0], d))[:24]
    except BookingError as e:
        return await show(cb, f"⚠️ {esc(str(e))}", kb([[("⬅ Другой день", f"bs:{k}:{i}")]]))
    if not slots:
        return await show(cb, "На этот день время закончилось.", kb([[("⬅ Другой день", f"bs:{k}:{i}")]]))
    rows, row = [], []
    for s in slots:
        row.append((s, f"bt:{k}:{i}:{j}:{s.replace(':', '')}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("⬅ Другой день", f"bs:{k}:{i}")])
    await show(cb, f"3️⃣ Свободное время на {WD[d.weekday()]} {d.strftime('%d.%m')}:", kb(rows))


@router.callback_query(F.data.startswith("bt:"))
async def book_time(cb: CallbackQuery, state: FSMContext):
    _, k, i, j, hhmm = cb.data.split(":")
    d = ai.upcoming_days()[int(j)]
    t = f"{hhmm[:2]}:{hhmm[2:]}"
    s = NICHES[k].services[int(i)]
    await state.set_state(Book.name)
    await state.update_data(niche=k, service=s[0], price=s[1], date=d.isoformat(), time=t)
    await show(cb, f"✅ {esc(s[0])}, {WD[d.weekday()]} {d.strftime('%d.%m')} в {t}\n\n"
                   "4️⃣ Как вас зовут? Напишите имя сообщением.")


@router.message(Book.name, F.text)
async def book_name(m: Message, state: FSMContext):
    name = m.text.strip()[:60]
    if len(name) < 2 or name.startswith("/"):
        return await m.answer("Напишите, пожалуйста, ваше имя.")
    await state.update_data(name=name)
    await state.set_state(Book.phone)
    contact_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True)
    await m.answer("5️⃣ Телефон для связи: нажмите кнопку или напишите номер "
                   "(в демо можно любой, например 0501234567).", reply_markup=contact_kb)


@router.message(Book.phone, F.contact | F.text)
async def book_phone(m: Message, state: FSMContext, bot: Bot):
    phone = m.contact.phone_number if m.contact else (m.text or "").strip()
    if sum(ch.isdigit() for ch in phone) < 7:
        return await m.answer("Не похоже на номер. Введите хотя бы 7 цифр.")
    data = await state.get_data()
    await state.clear()
    data["phone"] = phone[:30]
    k = data["niche"]
    try:
        lead_id = await save_lead(bot, m.from_user, k, data, "кнопки")
    except BookingError as e:
        await m.answer(f"⚠️ {esc(str(e))}", reply_markup=ReplyKeyboardRemove())
        return await m.answer("Выберите другое время:", reply_markup=kb(
            [[(NICHES[k].book_label, f"b:{k}")], [("⬅ Меню компании", f"n:{k}")]]))
    await m.answer("✅ Готово!", reply_markup=ReplyKeyboardRemove())
    await m.answer(
        f"🎉 <b>Заявка №{lead_id} принята</b>\n{esc(data['service'])}\n{data['date']} в {data['time']}\n\n"
        "Мы напомним за день до визита. Теперь посмотрите, что в этот момент увидел владелец:",
        reply_markup=kb([[("👔 Что увидит владелец", f"ow:{k}")], [("⬅ Меню компании", f"n:{k}")]]))


# ---------- роль владельца ----------

@router.callback_query(F.data.startswith("ow:"))
async def owner_view(cb: CallbackQuery):
    k = cb.data[3:]
    l = await db.last_lead(cb.from_user.id, k)
    if not l:
        return await cb.answer("Сначала запишитесь в этой компании, и здесь появится заявка.", show_alert=True)
    await cb.message.answer(
        "👔 <b>Так это выглядит у владельца в его Telegram:</b>\n\n" + lead_card(l),
        reply_markup=owner_kb(l["id"]))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^(ok|no|call):\d+$"))
async def owner_action(cb: CallbackQuery, bot: Bot):
    act, lid = cb.data.split(":")
    l = await db.get_lead(int(lid))
    if not l:
        return await cb.answer("Заявка не найдена.", show_alert=True)
    if cb.from_user.id not in (l["user_id"], config.OWNER_ID):
        return await cb.answer("Это чужая заявка.", show_alert=True)
    if act == "call":
        who = f"@{l['username']}" if l["username"] else f"id {l['user_id']}"
        return await cb.answer(f"В реальном боте откроется чат с клиентом ({who}, {l['phone']}).",
                               show_alert=True)
    await db.set_status(l["id"], act)
    l["status"] = act
    n = NICHES.get(l["niche"])
    company = n.company if n else ""
    note = (f"✅ {company}: ваша запись подтверждена — {l['service']}, {l['date']} в {l['time']}. Ждём вас!"
            if act == "ok" else f"❌ {company}: к сожалению, это время недоступно. Мы свяжемся, чтобы подобрать другое.")
    try:
        await cb.message.edit_text(lead_card(l) + f"\n\n📨 <b>Клиенту отправлено:</b>\n{esc(note)}",
                                   reply_markup=None)
    except TelegramBadRequest:
        pass
    if cb.from_user.id != l["user_id"]:
        try:
            await bot.send_message(l["user_id"], note)
        except Exception:
            log.exception("не удалось уведомить клиента")
    else:
        await cb.message.answer("☝️ Это сообщение клиент получает автоматически, когда владелец нажимает кнопку.")
    await cb.answer()


@router.callback_query(F.data.startswith("xl:"))
async def excel_report(cb: CallbackQuery):
    k = cb.data[3:]
    leads = await db.leads_for(cb.from_user.id, k)
    if not leads:
        return await cb.answer("Пока нет заявок. Запишитесь, и отчёт появится.", show_alert=True)
    data = leads_to_xlsx(leads)
    await cb.message.answer_document(BufferedInputFile(data, "zayavki.xlsx"),
                                     caption="📊 Так выглядит отчёт по заявкам для владельца.")
    await cb.answer()


# ---------- ИИ: вопросы словами и фото ----------

@router.callback_query(F.data.startswith("ai:"))
async def ai_mode(cb: CallbackQuery, state: FSMContext):
    k = cb.data[3:]
    n = NICHES[k]
    await state.set_state(Chat.active)
    await state.update_data(niche=k)
    ex = "\n".join(f"• {esc(s)}" for s in n.samples)
    await show(cb, f"💬 Вы общаетесь с AI-администратором «{esc(n.company)}». Пишите как обычному человеку, "
                   f"в том числе просите записать.\n\nНапример:\n{ex}", back_kb(k))


@router.callback_query(F.data.startswith("ph:"))
async def photo_mode(cb: CallbackQuery, state: FSMContext):
    k = cb.data[3:]
    n = NICHES[k]
    await state.set_state(Chat.active)
    await state.update_data(niche=k)
    await show(cb, f"{n.photo_label}\n\n{esc(n.photo_hint)}\n\nПришлите фото (можно с подписью).", back_kb(k))


async def _ai_reply(m: Message, state: FSMContext, bot: Bot, text: str, image: bytes | None):
    data = await state.get_data()
    k = data.get("niche")
    if not k:
        return await m.answer("Сначала выберите компанию:", reply_markup=home_kb())
    if not config.ANTHROPIC_API_KEY:
        return await m.answer("ИИ в этой копии бота не подключён. Кнопки меню работают.",
                              reply_markup=back_kb(k))
    verdict = await db.hit(m.from_user.id, config.USER_DAILY_LIMIT, config.GLOBAL_DAILY_LIMIT)
    if verdict != "ok":
        msg = ("Вы использовали дневной лимит демо-сообщений. Кнопки меню продолжают работать, а завтра лимит обновится."
               if verdict == "user_limit" else "Демо сегодня очень популярно, лимит ИИ на сегодня исчерпан. "
                                                "Кнопки меню работают, загляните завтра.")
        return await m.answer(msg, reply_markup=back_kb(k))
    await bot.send_chat_action(m.chat.id, "typing")

    async def on_lead(d):
        return await save_lead(bot, m.from_user, k, d, "AI-диалог")

    try:
        answer, lead_id = await ai.ask(m.from_user.id, k, text, image, on_lead)
    except Exception:
        log.exception("ошибка Claude")
        return await m.answer("ИИ временно недоступен. Попробуйте позже или пользуйтесь кнопками.",
                              reply_markup=back_kb(k))
    markup = (kb([[("👔 Что увидит владелец", f"ow:{k}")], [("⬅ Меню компании", f"n:{k}")]])
              if lead_id else back_kb(k))
    await m.answer(esc(answer)[:4000], reply_markup=markup)


@router.message(Chat.active, F.photo)
async def chat_photo(m: Message, state: FSMContext, bot: Bot):
    buf = await bot.download(m.photo[-1])
    await _ai_reply(m, state, bot, m.caption or "", buf.read())


@router.message(Chat.active, F.text)
async def chat_text(m: Message, state: FSMContext, bot: Bot):
    await _ai_reply(m, state, bot, m.text[:1000], None)


# ---------- «Хочу такого бота» ----------

@router.callback_query(F.data == "want")
async def want(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Want.text)
    await show(cb, "🚀 <b>Хотите такого бота для своего бизнеса?</b>\n\nОдним сообщением напишите, чем "
                   "занимается ваш бизнес и как с вами связаться (телефон или @ник). Мы напишем вам.")


@router.message(Want.text, F.text)
async def want_text(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    who = f"@{m.from_user.username}" if m.from_user.username else f"id {m.from_user.id}"
    if config.OWNER_ID:
        try:
            await bot.send_message(config.OWNER_ID, f"🚀 <b>Хочет такого бота</b>\n{esc(who)}\n\n{esc(m.text[:1500])}")
        except Exception:
            log.exception("не удалось отправить заявку на бота")
    else:
        log.warning("OWNER_ID не задан, заявка на бота: %s %s", who, m.text)
    await m.answer("Спасибо! Мы свяжемся с вами в ближайшее время.", reply_markup=home_kb())


# ---------- служебное ----------

@router.message(Command("stats"))
async def stats(m: Message):
    if config.OWNER_ID and m.from_user.id == config.OWNER_ID:
        s = await db.stats()
        await m.answer(f"👥 Пользователей: {s['users']}\n🧾 Заявок: {s['leads']}\n🤖 Сообщений ИИ сегодня: {s['ai_today']}")


@router.message(Command("leads"))
async def all_leads(m: Message):
    if config.OWNER_ID and m.from_user.id == config.OWNER_ID:
        leads = await db.all_leads()
        await m.answer_document(BufferedInputFile(leads_to_xlsx(leads), "all_leads.xlsx"))


@router.message()
async def fallback(m: Message):
    await m.answer("Выберите раздел кнопками ниже 👇", reply_markup=home_kb())
