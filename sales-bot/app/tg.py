"""Telegram: личка с лидом (запись, вопросы к ИИ) и группа «Заявки» (кнопки карточек, ответ лиду через бота)."""
import html
import logging
import re
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, Message

from . import config, core, db
from .texts import FMT_RU, lead_lang_of, t, when

log = logging.getLogger("tg")
esc = html.escape
router = Router()
LEAD_CB = re.compile(r"^(days|d:\d{8}|s:\d{12}|f:(tg|wa|meet|phone):\d{12}|(re|x):\d+)$")


class StaffReply(StatesGroup):
    text = State()


def is_group(m: Message) -> bool:
    return m.chat.type in ("group", "supergroup")


# ================================================================ личка с лидом

async def lead_for(user) -> dict:
    lead = await db.lead_by_tg(user.id)
    if lead:
        return lead
    lead = await db.create_lead(source="tg", lang=lead_lang_of(user.language_code), name=user.first_name or "",
                                contact=f"@{user.username}" if user.username else f"tg id {user.id}",
                                tg_id=user.id, tg_username=user.username or None, channel="tg", stage="talking")
    await core.post_card(lead)
    return lead


@router.message(CommandStart(), F.chat.type == "private")
async def start(m: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    arg = (command.args or "").strip()
    lead = await db.lead_by_token(arg[2:]) if arg.startswith("l_") else None
    if lead:
        lead = await core.link_channel(lead, "tg", tg_id=m.from_user.id, tg_username=m.from_user.username or None)
    else:
        lead = await lead_for(m.from_user)
    await core.greet(lead)


@router.callback_query(F.data.regexp(LEAD_CB))
async def lead_button(cb: CallbackQuery):
    lead = await db.lead_by_tg(cb.from_user.id)
    await cb.answer()
    if not lead:
        return
    try:
        await cb.message.edit_reply_markup(reply_markup=None)       # старые кнопки не нажать повторно
    except TelegramBadRequest:
        pass
    await core.on_choice(lead, cb.data)


@router.message(F.chat.type == "private", F.contact, StateFilter(None))
async def contact(m: Message):
    lead = await lead_for(m.from_user)
    ph = core.normalize_phone(m.contact.phone_number) or m.contact.phone_number
    if not lead.get("phone"):
        await db.update_lead(lead["id"], phone=ph)
    await core.incoming(await db.get_lead(lead["id"]), ph)


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"), StateFilter(None))
async def text(m: Message):
    lead = await lead_for(m.from_user)
    if lead.get("channel") != "tg":
        await db.update_lead(lead["id"], channel="tg", tg_id=m.from_user.id)
        lead = await db.get_lead(lead["id"])
    await core.incoming(lead, m.text[:1500])


@router.message(F.chat.type == "private", ~F.text, StateFilter(None))
async def other(m: Message):
    lead = await lead_for(m.from_user)
    await core.incoming(lead, m.caption or "[надіслав вкладення без тексту]")


# ================================================================ группа «Заявки»: кнопки карточек

@router.callback_query(F.data.regexp(r"^g:(take|lost|msg|ok):\d+$"))
async def staff_button(cb: CallbackQuery, state: FSMContext):
    if not core.staff(cb.from_user.id, cb.message.chat.id):
        return await cb.answer("Эта кнопка только для ADrenaline.", show_alert=True)
    _, act, n = cb.data.split(":")
    who = f"@{cb.from_user.username}" if cb.from_user.username else cb.from_user.first_name
    if act == "ok":
        call = await db.get_call(int(n))
        if not call or call["status"] not in db.ACTIVE_CALL:
            return await cb.answer("Звонок уже неактуален", show_alert=True)
        lead = await db.get_lead(call["lead_id"])
        await db.set_call(call["id"], status="confirmed")
        lang = core.lead_lang(lead)
        link = f"\n🔗 {config.MEET_URL}" if call["format"] == "meet" and config.MEET_URL else ""
        ok = await core.send(lead, ("👍 Даниїл підтвердив дзвінок <b>{w}</b>." if lang == "uk"
                                    else "👍 Даниил подтвердил звонок <b>{w}</b>.").format(
            w=when(datetime.fromisoformat(call["at"]), lang)) + link)
        await cb.answer("Подтверждено" + ("" if ok else " (клиенту не доставлено — окно WhatsApp закрыто)"),
                        show_alert=not ok)
        return await _mark(cb, f"✅ Подтвердил {who}")
    lead = await db.get_lead(int(n))
    if not lead:
        return await cb.answer("Лид не найден", show_alert=True)
    if act == "take":
        await db.update_lead(lead["id"], stage="taken", assignee=who, next_at=None)
        await cb.answer("Автоматика по лиду выключена, ИИ больше не отвечает")
        return await _mark(cb, f"🙋 Взял {who} — ИИ и автоматика выключены")
    if act == "lost":
        await db.update_lead(lead["id"], stage="lost", next_at=None)
        await cb.answer("Помечен как нецелевой")
        return await _mark(cb, f"🚫 Нецелевой ({who})")
    if not lead.get("channel"):
        return await cb.answer("Лид ещё не открыл Telegram/WhatsApp — написать через бота нельзя. Позвоните: "
                               + (lead.get("phone") or lead.get("contact") or "—"), show_alert=True)
    await state.set_state(StaffReply.text)
    await state.update_data(lead_id=lead["id"])
    await cb.answer()
    ch = {"tg": "Telegram", "wa": "WhatsApp"}[lead["channel"]]
    await cb.message.answer(f"✍️ Ответьте на это сообщение — отправлю лиду #{lead['id']} "
                            f"{esc(lead.get('name') or '')} в {ch} от имени Даниила. Отмена: /cancel",
                            reply_markup=ForceReply(input_field_placeholder="Сообщение лиду"))


async def _mark(cb: CallbackQuery, line: str):
    try:
        await cb.message.edit_text(cb.message.html_text + f"\n\n<b>{esc(line)}</b>", reply_markup=None,
                                   disable_web_page_preview=True)
    except TelegramBadRequest:
        pass


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
        await m.answer("Отменено.")


@router.message(StaffReply.text, F.text, ~F.text.startswith("/"))
async def staff_send(m: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    lead = await db.get_lead(data["lead_id"])
    lang = core.lead_lang(lead)
    ok = await core.send(lead, t(lang, "from_daniil", text=esc(m.text)))
    if ok:
        await db.update_lead(lead["id"], stage="taken", assignee=lead.get("assignee") or "Даниил", next_at=None)
        return await m.answer(f"✅ Отправлено лиду #{lead['id']}. ИИ по нему больше не отвечает — дальше вы.")
    tip = (f" Позвоните: +{lead['wa_id']}" if lead.get("wa_id") else "")
    await m.answer("⚠️ Не доставлено: в WhatsApp можно писать только 24 часа после последнего сообщения человека."
                   + tip)


# ================================================================ /leads для команды

@router.message(Command("leads"))
async def leads_cmd(m: Message):
    if not core.staff(m.from_user.id, m.chat.id):
        return
    rows = await db.rows("SELECT * FROM leads ORDER BY id DESC LIMIT 15")
    if not rows:
        return await m.answer("Лидов пока нет.")
    st = {"new": "🆕", "wa_sent": "💬", "need_call": "☎️", "talking": "🗣", "booked": "✅", "taken": "🙋",
          "lost": "🚫", "opted_out": "🔕"}
    out = ["<b>Последние лиды</b>"]
    for r in rows:
        call = await db.active_call(r["id"])
        tail = f" · {when(datetime.fromisoformat(call['at']), 'ru')} {FMT_RU.get(call['format'], '')}" if call else ""
        out.append(f"{st.get(r['stage'], '•')} #{r['id']} {esc(r.get('name') or '—')} · {r.get('channel') or '—'}{tail}")
    await m.answer("\n".join(out))
