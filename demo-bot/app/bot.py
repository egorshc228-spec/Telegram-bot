"""Telegram: без кнопок. Клиент пишет свободным текстом или присылает фото, Claude понимает запрос.
Личный кабинет (/cabinet), профиль, отзывы, передача вопросов владельцу. Кнопки только у владельца."""
import asyncio
import html
import logging
import re
from datetime import date

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import ai, booking, cabinet, config, db, i18n, reminders
from .i18n import t
from .booking.base import BookingError
from .niches import NICHES
from .report import leads_to_xlsx

log = logging.getLogger("bot")
router = Router()
router.message.filter(F.chat.type == "private")

esc = html.escape
ACTIVE = ("new", "ok")


class Review(StatesGroup):
    waiting = State()


class Broadcast(StatesGroup):
    text = State()          # владелец пишет объявление для всех клиентов


class Reply(StatesGroup):
    text = State()          # владелец пишет ответ клиенту


# ---------- тексты ----------

def welcome(k: str, lang: str = "ru") -> str:
    n = i18n.niche_view(k, lang)
    prices = [x[1] for x in NICHES[k].services]
    services = "\n".join(f"• {esc(name)} — {p} ₴" for name, p in zip(n.services, prices))
    examples = "\n".join(f"— «{esc(x)}»" for x in n.samples)
    text = t(lang, "welcome", company=esc(n.company), about=esc(n.about), services=services, hours=esc(n.hours),
             address=esc(n.address), photo=esc(n.photo_example), examples=examples)
    if config.DEMO_MODE:
        text += "\n\n" + t(lang, "welcome_demo")
    return text


def lead_card(l: dict, title: str | None = None, lang: str = "ru") -> str:
    """Карточка заявки. Владельцу показывается на русском, в демо /owner — на языке клиента."""
    k = l["niche"] if l["niche"] in NICHES else None
    company = i18n.niche_view(k, lang).company if k else l["niche"]
    service = i18n.service_label(k, l["service"], lang) if k else l["service"]
    status = {"ok": "\n" + t(lang, "card_ok"), "no": "\n" + t(lang, "card_no"),
              "cancel": "\n" + t(lang, "card_cancel")}.get(l["status"], "")
    return (
        f"{title or t(lang, 'card_new')} №{l['id']}\n🏢 {esc(company)}\n"
        f"👤 {esc(l['name'])}   📞 {esc(l['phone'])}\n"
        f"🧾 {esc(service)} — {l['price']} ₴\n{t(lang, 'card_when', date=l['date'], time=l['time'])}\n"
        + (f"💬 {esc(l['comment'])}\n" if l["comment"] else "")
        + (f"🗂 {esc(l['crm'])} №{esc(l['external_id'])}\n" if l.get("external_id") else "")
        + t(lang, "card_source", v=esc(l["source"])) + status
    )


def kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


def owner_kb(lead_id: int, client_id: int, lang: str = "ru"):
    return kb([[(t(lang, "btn_ok"), f"ok:{lead_id}"), (t(lang, "btn_no"), f"no:{lead_id}")],
               [(t(lang, "btn_reply"), f"rp:{client_id}"), (t(lang, "btn_contacts"), f"call:{lead_id}")]])


def who(user) -> str:
    return f"@{user.username}" if user.username else f"id {user.id}"


# ---------- общие функции ----------

async def current_niche(user_or_id) -> str:
    default = config.DEFAULT_NICHE if config.DEFAULT_NICHE in NICHES else "salon"
    if not config.DEMO_MODE:
        return default
    uid = user_or_id if isinstance(user_or_id, int) else user_or_id.id
    row = await db.get_user(uid)
    k = (row or {}).get("niche")
    return k if k in NICHES else default


async def touch(user) -> dict:
    """Запоминает пользователя, возвращает строку из базы."""
    await db.touch_user(user.id, user.username)
    return await db.get_user(user.id) or {}


async def ulang(user) -> str:
    """Язык клиента: тот, на котором он писал в последний раз; пока не писал, украинский (по умолчанию)."""
    return i18n.resolve(await db.get_user(user.id))


async def sync_lang(user, text: str | None) -> str:
    """Определяет язык сообщения (ru/uk/en) и запоминает его для клиента. Нейтральный текст
    (цифры, имя, смайлик) язык не меняет. Возвращает актуальный язык клиента."""
    row = await db.get_user(user.id)
    cur = i18n.resolve(row)
    new = i18n.detect(text)
    if new and (new != cur or (row or {}).get("lang") != new):
        await db.set_lang(user.id, new)
        return new
    return cur


async def notify_owner(bot: Bot, text: str, markup=None) -> bool:
    if not config.OWNER_ID:
        log.warning("OWNER_ID не задан, уведомление не отправлено: %s", text[:120])
        return False
    try:
        await bot.send_message(config.OWNER_ID, text, reply_markup=markup)
        return True
    except Exception:
        log.exception("не удалось уведомить владельца")
        return False


async def escalate(bot: Bot, user, niche: str, reason: str, details: str = "", src: Message | None = None) -> bool:
    """Передаёт ситуацию владельцу с последними сообщениями диалога и кнопкой «Ответить клиенту»."""
    n = NICHES[niche]
    last = "\n".join(f"{'🧑' if h['role'] == 'user' else '🤖'} {esc(str(h['content'])[:200])}"
                     for h in ai.recent(user.id, niche))
    text = (f"🙋 <b>Нужно вмешательство владельца</b>\n🏢 {esc(n.company)}\n👤 {esc(who(user))} (id {user.id})\n"
            f"❓ {esc(reason)}\n" + (f"📝 {esc(details)}\n" if details else "")
            + (f"\n<b>Последние сообщения:</b>\n{last}" if last else ""))
    ok = await notify_owner(bot, text, kb([[("✉️ Ответить клиенту", f"rp:{user.id}")]]))
    if ok and src is not None:
        try:
            await bot.copy_message(config.OWNER_ID, src.chat.id, src.message_id)
        except Exception:
            log.exception("не удалось скопировать сообщение клиента владельцу")
    return ok


async def hand_over(bot: Bot, m: Message, niche: str, reason: str):
    """ИИ недоступен или лимит исчерпан: вопрос клиента уходит владельцу, клиенту отвечаем человеческой фразой."""
    ok = await escalate(bot, m.from_user, niche, reason,
                        f"Сообщение клиента: {m.text or m.caption or '[фото]'}", src=m)
    lang = await ulang(m.from_user)
    await m.answer(t(lang, "handover_ok" if ok else "handover_fail"))


async def save_lead(bot: Bot, user, niche: str, data: dict, source: str) -> int:
    """Запись в CRM (если подключена) → заявка в базе → профиль → уведомление владельцу.
    BookingError (слот занят, CRM недоступна) пробрасывается вызывающему."""
    bk = await booking.create(niche, data["service"], date.fromisoformat(data["date"]), data["time"],
                              data["name"], data["phone"], data.get("comment", ""))
    lead_id = await db.add_lead(
        user.id, user.username, niche, data["service"], data["price"], data["date"], data["time"],
        data["name"], data["phone"], data.get("comment", ""), source,
        external_id=bk.external_id if bk else "", crm=bk.system if bk else "",
    )
    prof = await db.get_user(user.id) or {}      # первый раз сохраняем имя и телефон в профиль
    await db.set_profile(user.id, None if prof.get("name") else data["name"],
                         None if prof.get("phone") else data["phone"])
    if config.OWNER_ID and config.OWNER_ID != user.id:
        l = await db.get_lead(lead_id)
        title = f"{t('ru', 'card_new' if booking.is_live(niche) else 'card_demo')} ({esc(who(user))})"
        await notify_owner(bot, lead_card(l, title), owner_kb(lead_id, user.id))
    return lead_id


async def save_review(bot: Bot, user, niche: str, rating: int, text: str) -> int:
    today = ai._now().date()
    leads = await db.leads_for(user.id, niche)
    reviewed = {r["lead_id"] for r in await db.user_reviews(user.id, niche)}
    past = [l for l in leads if l["status"] in ACTIVE and date.fromisoformat(l["date"]) < today
            and l["id"] not in reviewed]
    rid = await db.add_review(user.id, user.username, niche, rating, text, past[-1]["id"] if past else None)
    low = "\n⚠️ <b>Низкая оценка, стоит связаться с клиентом.</b>" if rating <= 3 else ""
    await notify_owner(
        bot, f"⭐ <b>Новый отзыв: {rating}/5</b> · {esc(NICHES[niche].company)}\n👤 {esc(who(user))}\n"
             f"💬 {esc(text) or '(без текста)'}{low}",
        kb([[("✉️ Ответить клиенту", f"rp:{user.id}")]]) if rating <= 3 else None)
    return rid


def parse_review(text: str):
    """Достаёт оценку 1–5 (цифра, «4/5», «5 из 5» или ⭐) и комментарий."""
    t = text.strip()
    cleaned = re.sub(r"\b[1-5]\s*(?:/|из|із|з|of)\s*5\b", lambda m: m.group(0)[0], t)
    m = re.search(r"(?<!\d)([1-5])(?!\d)", cleaned)
    if m:
        rating = int(m.group(1))
        comment = (cleaned[:m.start()] + cleaned[m.end():]).strip(" .,:;-—")
        return rating, comment
    stars = t.count("⭐") or t.count("★")
    if 1 <= stars <= 5:
        return stars, t.replace("⭐", "").replace("★", "").strip(" .,:;-—")
    return None, t


class ClientActions:
    """Действия, которые Claude может выполнить от имени клиента (вызываются из ai.ask)."""

    def __init__(self, bot: Bot, message: Message, niche: str):
        self.bot, self.message, self.niche = bot, message, niche
        self.user = message.from_user
        self.lead_id = None
        self.show_cabinet = False
        self.want_bot = False          # демо-воронка: человек хочет такого бота себе

    async def create_lead(self, data: dict) -> int:
        self.lead_id = await save_lead(self.bot, self.user, self.niche, data, "AI-диалог")
        return self.lead_id

    async def update_profile(self, name, phone) -> str:
        name, phone = (name or "").strip()[:60], (phone or "").strip()[:30]
        if not name and not phone:
            raise ValueError("Не передано ни имени, ни телефона.")
        if name and len(name) < 2:
            raise ValueError("Слишком короткое имя.")
        if phone and sum(ch.isdigit() for ch in phone) < 7:
            raise ValueError("В телефоне должно быть не меньше 7 цифр.")
        await db.set_profile(self.user.id, name or None, phone or None)
        return "Данные профиля обновлены."

    async def cancel_booking(self, booking_id: int) -> str:
        l = await db.get_lead(booking_id)
        if not l or l["user_id"] != self.user.id:
            raise ValueError("Записи с таким номером у этого клиента нет.")
        if l["status"] not in ACTIVE or date.fromisoformat(l["date"]) < ai._now().date():
            raise ValueError("Эту запись уже нельзя отменить.")
        if l.get("external_id"):      # запись создана в CRM: отмену подтверждает владелец
            await escalate(self.bot, self.user, self.niche,
                           f"Клиент просит отменить запись №{l['id']} ({l['crm']} №{l['external_id']})",
                           f"{l['service']}, {l['date']} {l['time']}")
            return ("Запись создана во внешней системе, запрос на отмену передан владельцу. "
                    "Скажи клиенту, что владелец подтвердит отмену.")
        await db.set_status(l["id"], "cancel")
        await notify_owner(self.bot, f"🚫 Клиент {esc(who(self.user))} отменил запись №{l['id']}: "
                                     f"{esc(l['service'])}, {l['date']} {l['time']}")
        return f"Запись №{l['id']} отменена."

    async def leave_review(self, rating: int, text: str) -> str:
        if not 1 <= rating <= 5:
            raise ValueError("Оценка должна быть от 1 до 5.")
        await save_review(self.bot, self.user, self.niche, rating, text)
        return "Отзыв сохранён и передан владельцу. Поблагодари клиента."

    async def ask_owner(self, reason: str, details: str) -> str:
        if config.FUNNEL_ENABLED and "такого бота" in reason.lower():
            self.want_bot = True       # воронка сама покажет кнопку записи на звонок и уведомит ADrenaline
        ok = await escalate(self.bot, self.user, self.niche, reason, details,
                            src=self.message if self.message.photo else None)
        if ok and self.want_bot:
            return ("Передано команде ADrenaline. Коротко скажи, что это отличная идея и что ниже появится кнопка, "
                    "чтобы сразу выбрать время 20-минутного звонка с Даниилом.")
        if ok:
            return "Передано владельцу. Скажи клиенту: сейчас уточню у владельца и отвечу вам здесь."
        return ("Владелец сейчас недоступен. Скажи клиенту, что не можешь помочь с этим вопросом, "
                "и предложи связаться с компанией напрямую.")


async def send_cabinet(m: Message, user=None):
    user = user or m.from_user
    k = await current_niche(user)
    await m.answer(cabinet.render(await db.get_user(user.id), k, await db.leads_for(user.id, k),
                                  await db.user_reviews(user.id, k), ai._now().date(), await ulang(user)))


async def converse(m: Message, bot: Bot, text: str, image: bytes | None = None):
    user = m.from_user
    await touch(user)
    await sync_lang(user, text)
    niche = await current_niche(user)
    if not config.ANTHROPIC_API_KEY:
        return await hand_over(bot, m, niche, "ИИ не подключён (нет ключа Claude)")
    verdict = await db.hit(user.id, config.USER_DAILY_LIMIT, config.GLOBAL_DAILY_LIMIT)
    if verdict != "ok":
        return await hand_over(bot, m, niche, "Лимит ИИ-сообщений на сегодня исчерпан")
    await bot.send_chat_action(m.chat.id, "typing")
    today = ai._now().date()
    bookings = [l for l in await db.leads_for(user.id, niche)
                if l["status"] in ACTIVE and date.fromisoformat(l["date"]) >= today]
    actions = ClientActions(bot, m, niche)
    try:
        answer = await ai.ask(user.id, niche, text, image, actions, await db.get_user(user.id) or {}, bookings)
    except Exception:
        log.exception("ошибка Claude")
        return await hand_over(bot, m, niche, "ИИ временно недоступен")
    await m.answer(ai.to_html(answer))
    if actions.show_cabinet:
        await send_cabinet(m)
    if config.FUNNEL_ENABLED:
        from . import funnel            # импорт здесь: funnel сам импортирует этот модуль
        try:
            await funnel.after_ai(bot, m, actions, answer)
        except Exception:
            log.exception("ошибка воронки после ответа ИИ")


# ---------- команды ----------

@router.message(CommandStart())
@router.message(Command("menu"))
async def start(m: Message, state: FSMContext):
    await state.clear()
    await touch(m.from_user)
    ai.reset(m.from_user.id)
    await m.answer(welcome(await current_niche(m.from_user), await ulang(m.from_user)))


@router.message(Command("salon", "auto", "shop", "dental"))
async def switch_niche(m: Message, command: CommandObject, state: FSMContext):
    lang = await ulang(m.from_user)
    if not config.DEMO_MODE:
        return await m.answer(t(lang, "just_write"))
    await state.clear()
    await touch(m.from_user)
    await db.set_niche(m.from_user.id, command.command)
    ai.reset(m.from_user.id)
    await m.answer(welcome(command.command, lang))


@router.message(Command("cancel"))
async def cancel_state(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(t(await ulang(m.from_user), "cancel_state"))


@router.message(Command("cabinet", "my"))
async def cabinet_cmd(m: Message):
    await touch(m.from_user)
    await send_cabinet(m)


@router.message(Command("profile"))
async def profile_cmd(m: Message):
    await touch(m.from_user)
    await m.answer(cabinet.profile_text(await db.get_user(m.from_user.id), await ulang(m.from_user)))


@router.message(Command("name"))
async def name_cmd(m: Message, command: CommandObject):
    lang = await ulang(m.from_user)
    val = (command.args or "").strip()[:60]
    if len(val) < 2:
        return await m.answer(t(lang, "name_usage"))
    await touch(m.from_user)
    await db.set_profile(m.from_user.id, name=val)
    await m.answer(t(lang, "name_saved", v=esc(val)))


@router.message(Command("phone"))
async def phone_cmd(m: Message, command: CommandObject):
    lang = await ulang(m.from_user)
    val = (command.args or "").strip()[:30]
    if sum(ch.isdigit() for ch in val) < 7:
        return await m.answer(t(lang, "phone_usage"))
    await touch(m.from_user)
    await db.set_profile(m.from_user.id, phone=val)
    await m.answer(t(lang, "phone_saved", v=esc(val)))


@router.message(Command("review"))
async def review_cmd(m: Message, state: FSMContext):
    await touch(m.from_user)
    await state.set_state(Review.waiting)
    await m.answer(t(await ulang(m.from_user), "review_prompt"))


# --- демо-команды: взгляд владельца ---

@router.message(Command("how"))
async def how_cmd(m: Message):
    if config.DEMO_MODE:
        await m.answer(t(await ulang(m.from_user), "how"))


@router.message(Command("owner"))
async def owner_view(m: Message):
    if not config.DEMO_MODE:
        return
    lang = await ulang(m.from_user)
    k = await current_niche(m.from_user)
    l = await db.last_lead(m.from_user.id, k)
    if not l:
        return await m.answer(t(lang, "owner_view_need"))
    await m.answer(t(lang, "owner_view_title") + lead_card(l, lang=lang),
                   reply_markup=owner_kb(l["id"], m.from_user.id, lang))


@router.message(Command("report"))
async def report_view(m: Message):
    if not config.DEMO_MODE:
        return
    lang = await ulang(m.from_user)
    k = await current_niche(m.from_user)
    leads = await db.leads_for(m.from_user.id, k)
    if not leads:
        return await m.answer(t(lang, "report_need"))
    await m.answer_document(BufferedInputFile(leads_to_xlsx(leads, lang), "zayavki.xlsx"),
                            caption=t(lang, "report_caption"))


@router.message(Command("reminder"))
async def reminder_demo(m: Message):
    if not config.DEMO_MODE:
        return
    lang = await ulang(m.from_user)
    l = await db.last_lead(m.from_user.id, await current_niche(m.from_user))
    if not l:
        return await m.answer(t(lang, "remind_demo_need"))
    await m.answer(reminders.reminder_text(l, "24h", lang))
    await m.answer(t(lang, "remind_demo_note"))


# --- команды владельца ---

def _is_owner(m: Message) -> bool:
    return bool(config.OWNER_ID) and m.from_user.id == config.OWNER_ID


@router.message(Command("stats"))
async def stats(m: Message):
    if _is_owner(m):
        s = await db.stats()
        rv = s["reviews"]
        await m.answer(f"👥 Пользователей: {s['users']}\n🧾 Записей: {s['leads']}\n"
                       f"🤖 Сообщений ИИ сегодня: {s['ai_today']}\n"
                       f"⭐ Отзывов: {rv['count']}, средняя оценка: {rv['avg'] or '—'}")


@router.message(Command("leads"))
async def all_leads(m: Message):
    if _is_owner(m):
        await m.answer_document(BufferedInputFile(leads_to_xlsx(await db.all_leads(), "ru"), "all_leads.xlsx"))


@router.message(Command("broadcast", "announce"))
async def broadcast_cmd(m: Message, command: CommandObject, state: FSMContext):
    """Только владелец: /broadcast текст (или просто /broadcast и следующим сообщением текст)."""
    if not _is_owner(m):
        return
    await state.clear()
    text = (command.args or "").strip()
    if not text:
        await state.set_state(Broadcast.text)
        return await m.answer("📢 Напишите текст объявления для всех клиентов бота (отмена: /cancel).")
    await broadcast_preview(m, state, text)


@router.message(Broadcast.text, F.text, ~F.text.startswith("/"))
async def broadcast_text(m: Message, state: FSMContext):
    if not _is_owner(m):
        return
    await broadcast_preview(m, state, m.text.strip())


async def broadcast_preview(m: Message, state: FSMContext, text: str):
    text = text[:3500]
    n = len([u for u in await db.all_user_ids() if u != config.OWNER_ID])
    await state.set_state(None)
    await state.update_data(bc_text=text)
    await m.answer(f"📢 <b>Так увидят клиенты</b> (получателей: {n}):\n\n{esc(text)}",
                   reply_markup=kb([[(f"✅ Отправить всем ({n})", "bc:go"), ("❌ Отмена", "bc:no")]]))


@router.callback_query(F.data.regexp(r"^bc:(go|no)$"))
async def broadcast_confirm(cb: CallbackQuery, state: FSMContext, bot: Bot):
    if not (config.OWNER_ID and cb.from_user.id == config.OWNER_ID):
        return await cb.answer("Только для владельца.", show_alert=True)
    data = await state.get_data()
    text = data.get("bc_text")
    await state.update_data(bc_text=None)
    await cb.answer()
    if cb.data == "bc:no" or not text:
        return await cb.message.edit_text("Рассылка отменена." if text else "Текст не найден, начните заново: /broadcast")
    await cb.message.edit_text("⏳ Отправляю…")
    ok = fail = 0
    for uid in await db.all_user_ids():
        if uid == config.OWNER_ID:
            continue
        try:
            await bot.send_message(uid, "📢 " + esc(text))
            ok += 1
        except Exception:                      # заблокировал бота и т.п.
            fail += 1
        await asyncio.sleep(0.05)              # лимит Telegram ~30 сообщений в секунду
    await cb.message.edit_text(f"✅ Рассылка отправлена: доставлено {ok}, не доставлено {fail}.")


@router.message(Command("reviews"))
async def reviews_cmd(m: Message):
    if not _is_owner(m):
        return
    rows = await db.reviews_list(10)
    st = await db.review_stats()
    if not rows:
        return await m.answer("Отзывов пока нет.")
    lines = [f"⭐ <b>Отзывы</b>: всего {st['count']}, средняя оценка {st['avg']}\n"]
    for r in rows:
        who_ = f"@{r['username']}" if r["username"] else f"id {r['user_id']}"
        lines.append(f"{'⭐' * r['rating']} {esc(who_)}: {esc(r['text'] or '(без текста)')}")
    await m.answer("\n".join(lines)[:4000])


# ---------- кнопки владельца ----------

@router.callback_query(F.data.regexp(r"^(ok|no|call):\d+$"))
async def owner_action(cb: CallbackQuery, bot: Bot):
    act, lid = cb.data.split(":")
    l = await db.get_lead(int(lid))
    # владельцу всё на русском; клиент (в демо он сам себе владелец) видит свой язык
    client_lang = i18n.resolve(await db.get_user(l["user_id"])) if l else "ru"
    ol = client_lang if (l and cb.from_user.id == l["user_id"]) else "ru"
    if not l:
        return await cb.answer(t("ru", "alert_not_found"), show_alert=True)
    if cb.from_user.id not in (l["user_id"], config.OWNER_ID):
        return await cb.answer(t(ol, "alert_foreign"), show_alert=True)
    if act == "call":
        who_ = f"@{l['username']}" if l["username"] else f"id {l['user_id']}"
        return await cb.answer(t(ol, "alert_contact", who=who_, phone=l["phone"]), show_alert=True)
    if l["status"] == "cancel":
        return await cb.answer(t(ol, "alert_cancelled"), show_alert=True)
    await db.set_status(l["id"], act)
    l["status"] = act
    k = l["niche"] if l["niche"] in NICHES else None
    company = i18n.niche_view(k, client_lang).company if k else ""
    service = i18n.service_label(k, l["service"], client_lang) if k else l["service"]
    note = t(client_lang, "confirm_ok" if act == "ok" else "confirm_no", company=company, service=service,
             date=l["date"], time=l["time"])
    try:
        await cb.message.edit_text(lead_card(l, lang=ol) + f"\n\n{t(ol, 'card_sent')}\n{esc(note)}",
                                   reply_markup=owner_kb(l["id"], l["user_id"], ol))
    except TelegramBadRequest:
        pass
    if cb.from_user.id != l["user_id"]:
        try:
            await bot.send_message(l["user_id"], note)
        except Exception:
            log.exception("не удалось уведомить клиента")
    await cb.answer(t(ol, "alert_done"))


@router.callback_query(F.data.regexp(r"^rp:\d+$"))
async def owner_reply_start(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != config.OWNER_ID:
        return await cb.answer("Эта кнопка только для владельца.", show_alert=True)
    to = int(cb.data[3:])
    await state.set_state(Reply.text)
    await state.update_data(to=to)
    await cb.message.answer("✍️ Напишите ответ клиенту следующим сообщением, я передам его. Отмена: /cancel")
    await cb.answer()


# ---------- сообщения (порядок важен) ----------

@router.message(Reply.text, F.text, ~F.text.startswith("/"))
async def owner_reply_send(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    if m.from_user.id != config.OWNER_ID:
        return
    to = data["to"]
    lang = i18n.resolve(await db.get_user(to))
    company = i18n.niche_view(await current_niche(to), lang).company
    try:
        await bot.send_message(to, t(lang, "admin_prefix", company=esc(company), text=esc(m.text)))
    except Exception:
        log.exception("не удалось отправить ответ клиенту")
        return await m.answer("Не удалось отправить: возможно, клиент заблокировал бота.")
    await m.answer("✅ Отправлено клиенту.")


@router.message(Review.waiting, F.text, ~F.text.startswith("/"))
async def review_text(m: Message, state: FSMContext, bot: Bot):
    await touch(m.from_user)
    lang = await sync_lang(m.from_user, m.text)
    rating, comment = parse_review(m.text)
    if rating is None:
        return await m.answer(t(lang, "review_need_rating"))
    await state.clear()
    await touch(m.from_user)
    await save_review(bot, m.from_user, await current_niche(m.from_user), rating, comment[:500])
    await m.answer(t(lang, "review_thanks_hi" if rating >= 4 else "review_thanks_lo"))


@router.message(F.photo)
async def on_photo(m: Message, bot: Bot):
    buf = await bot.download(m.photo[-1])
    await converse(m, bot, m.caption or "", buf.read())


MY_PHONE = {"ru": "Мой номер телефона: {p}", "uk": "Мій номер телефону: {p}", "en": "My phone number: {p}"}


@router.message(F.contact)
async def on_contact(m: Message, bot: Bot):
    """Клиент поделился контактом (скрепка → Контакт), когда ИИ спросил телефон: сохраняем номер в профиль
    и продолжаем диалог так, будто клиент написал номер текстом."""
    c = m.contact
    if c.user_id and c.user_id != m.from_user.id:            # чужой контакт — просто передаём ИИ как текст
        return await converse(m, bot, f"{c.first_name or ''} {c.phone_number}".strip())
    await touch(m.from_user)
    await db.set_profile(m.from_user.id, None, c.phone_number)
    lang = await ulang(m.from_user)
    await converse(m, bot, MY_PHONE.get(lang, MY_PHONE["ru"]).format(p=c.phone_number))


@router.message(F.text, ~F.text.startswith("/"))
async def on_text(m: Message, bot: Bot):
    await converse(m, bot, m.text[:1000])


@router.message(F.text.startswith("/"))
async def unknown_command(m: Message):
    await m.answer(t(await ulang(m.from_user), "unknown_cmd"))


@router.message()
async def other_content(m: Message):
    await m.answer(t(await ulang(m.from_user), "other_content"))
