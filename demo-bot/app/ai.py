"""AI-администратор: клиент пишет свободным текстом или присылает фото, Claude понимает запрос
и действует через инструменты (запись, личный кабинет, профиль, отмена, отзыв, вызов владельца)."""
import asyncio
import base64
import re
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import booking, config, i18n
from .booking.base import BookingError
from .niches import NICHES
from .rules import RULES_COMMON, RULES_DEMO, RULES_FUNNEL

log = logging.getLogger("ai")

client = None  # AsyncAnthropic, создаётся лениво (в тестах подменяется)
_history: dict = {}
_locks: dict = {}

TOOLS = [
    {
        "name": "create_lead",
        "description": (
            "Создать запись или заказ. Вызывай ТОЛЬКО когда известны услуга, дата и время (из свободных окон) "
            "и клиент подтвердил запись. Имя и телефон можно не передавать, если они уже есть в профиле клиента."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Название услуги или товара ровно как в прайсе (русское название)"},
                "date": {"type": "string", "description": "Дата YYYY-MM-DD"},
                "time": {"type": "string", "description": "Время HH:MM"},
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "comment": {"type": "string", "description": "Пожелания клиента, если есть"},
            },
            "required": ["service", "date", "time"],
        },
    },
    {
        "name": "show_cabinet",
        "description": "Показать клиенту личный кабинет: календарь его записей, ближайшие визиты, историю. "
                       "Кабинет отправляется отдельным сообщением.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_profile",
        "description": "Изменить сохранённые имя и/или телефон клиента.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "phone": {"type": "string"}},
        },
    },
    {
        "name": "cancel_booking",
        "description": "Отменить запись клиента по её номеру из списка его записей.",
        "input_schema": {
            "type": "object",
            "properties": {"booking_id": {"type": "integer"}},
            "required": ["booking_id"],
        },
    },
    {
        "name": "leave_review",
        "description": "Сохранить отзыв клиента: оценка от 1 до 5 и комментарий.",
        "input_schema": {
            "type": "object",
            "properties": {"rating": {"type": "integer", "minimum": 1, "maximum": 5},
                           "text": {"type": "string"}},
            "required": ["rating"],
        },
    },
    {
        "name": "set_language",
        "description": "Переключить язык общения с клиентом (ru, uk или en): когда клиент просит говорить на другом "
                       "языке. Язык сохраняется для всех следующих сообщений, напоминаний и личного кабинета.",
        "input_schema": {
            "type": "object",
            "properties": {"lang": {"type": "string", "enum": ["ru", "uk", "en"]}},
            "required": ["lang"],
        },
    },
    {
        "name": "ask_owner",
        "description": "Передать вопрос владельцу, когда нужна его помощь или решение (нет данных, жалоба, "
                       "клиент просит человека, запись не получается, ситуация непонятна). "
                       "После вызова скажи клиенту, что сейчас уточнишь у владельца.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "Суть одной фразой"},
                           "details": {"type": "string", "description": "Важные подробности"}},
            "required": ["reason"],
        },
    },
]


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def upcoming_days(n: int = 5) -> list:
    start = _now().date() + timedelta(days=1)
    return [start + timedelta(days=i) for i in range(n)]


def static_system(niche_key: str) -> str:
    """Постоянная часть промпта: правила и данные компании (кэшируется)."""
    n = NICHES[niche_key]
    uk, en = i18n.niche_view(niche_key, "uk").services, i18n.niche_view(niche_key, "en").services
    services = "\n".join(
        f"- {s[0]}" + (f" (uk: {uk[i]}; en: {en[i]})" if (uk[i], en[i]) != (s[0], s[0]) else "")
        + f": {s[1]} ₴ (~{s[2]} мин)" for i, s in enumerate(n.services))
    faq = "\n".join(f"Q: {q}\nA: {a}" for q, a in n.faq)
    return f"""Ты AI-администратор компании «{n.company}» в Telegram.
Тон: {n.tone}.

{RULES_COMMON}
Правила для этой компании: {n.rules or 'нет особых'}
{(RULES_FUNNEL if config.FUNNEL_ENABLED else RULES_DEMO) if config.DEMO_MODE else ''}
О компании: {n.about}
Адрес: {n.address}
График: {n.hours}

Прайс:
{services}

Частые вопросы:
{faq}"""


async def _days_text(niche_key: str) -> str:
    try:
        res = await booking.free_slots_days(niche_key, None, upcoming_days())
    except BookingError:
        return ("Расписание сейчас недоступно. Не называй конкретное время и не создавай записи: "
                "вызови ask_owner (расписание недоступно) и скажи клиенту, что администратор уточнит время.")
    return "\n".join(f"- {d.isoformat()} ({d.strftime('%a')}): {', '.join(res.get(d, [])) or 'занято'}"
                     for d in upcoming_days() if d in res)


async def dynamic_system(niche_key: str, profile: dict, bookings: list) -> str:
    """Меняющаяся часть: дата, свободные окна, профиль и записи конкретного клиента."""
    name, phone = profile.get("name"), profile.get("phone")
    prof = (f"Имя: {name or 'не указано'}, телефон: {phone or 'не указан'}. "
            + ("Эти данные уже сохранены: не спрашивай их повторно при записи." if name and phone
               else "Недостающие данные спроси при записи."))
    mine = "\n".join(f"- №{b['id']}: {b['service']}, {b['date']} {b['time']}, статус {b['status']}"
                     for b in bookings) or "нет"
    lang = i18n.resolve(profile)
    return (f"Язык клиента: {i18n.lang_name_ru(lang)} ({lang}). Отвечай на нём.\n"
            f"Сегодня {_now().date().isoformat()} ({_now().strftime('%A')}).\n\n"
            f"Свободное время на ближайшие дни:\n{await _days_text(niche_key)}\n\n"
            f"Профиль клиента: {prof}\n\nАктивные записи клиента:\n{mine}")


async def _validate_lead(niche_key: str, args: dict, profile: dict):
    svc = i18n.find_service_any(niche_key, args.get("service", ""))
    if not svc:
        return False, "Такой услуги нет в прайсе. Уточни у клиента название из списка."
    try:
        d = date.fromisoformat(str(args.get("date", "")))
    except ValueError:
        return False, "Дата должна быть в формате YYYY-MM-DD."
    t = str(args.get("time", "")).strip()
    if d not in upcoming_days():
        return False, "Дата вне доступного диапазона. Предложи дату из списка свободных."
    try:
        free = await booking.free_slots(niche_key, svc[1][0], d)
    except BookingError as e:
        return False, str(e)
    if t not in free:
        return False, (f"Время {t} на {d.isoformat()} недоступно. Свободно: {', '.join(free) or 'ничего'}. "
                       "Предложи клиенту другое.")
    name = str(args.get("name") or profile.get("name") or "").strip()[:60]
    phone = str(args.get("phone") or profile.get("phone") or "").strip()[:30]
    if len(name) < 2 or sum(ch.isdigit() for ch in phone) < 7:
        return False, "Нужны корректные имя и телефон клиента (в профиле их нет). Спроси их."
    return True, {
        "service": svc[1][0], "price": svc[1][1], "date": d.isoformat(), "time": t,
        "name": name, "phone": phone, "comment": str(args.get("comment", ""))[:200],
    }


async def _run_tool(niche_key: str, name: str, args: dict, actions, profile: dict):
    """Выполняет инструмент. Возвращает (текст для модели, это ошибка?)."""
    try:
        if name == "create_lead":
            if actions.lead_id:
                return "Запись уже создана.", True
            ok, data = await _validate_lead(niche_key, args, profile)
            if not ok:
                return data, True
            actions.lead_id = await actions.create_lead(data)
            return f"Запись №{actions.lead_id} создана и отправлена владельцу. Она видна в личном кабинете.", False
        if name == "show_cabinet":
            actions.show_cabinet = True
            return "Личный кабинет будет отправлен клиенту отдельным сообщением. Коротко скажи об этом.", False
        if name == "update_profile":
            return await actions.update_profile(args.get("name"), args.get("phone")), False
        if name == "cancel_booking":
            return await actions.cancel_booking(int(args.get("booking_id", 0))), False
        if name == "leave_review":
            return await actions.leave_review(int(args.get("rating", 0)), str(args.get("text", ""))[:500]), False
        if name == "set_language":
            lang = str(args.get("lang", "")).lower()
            if lang not in i18n.LANGS:
                return "Доступны языки: ru, uk, en.", True
            await actions.set_language(lang)
            profile["lang"] = lang
            return i18n.t("ru", "lang_tool_ok", name=i18n.lang_name_ru(lang)), False
        if name == "ask_owner":
            return await actions.ask_owner(str(args.get("reason", ""))[:200], str(args.get("details", ""))[:600]), False
    except BookingError as e:
        return f"Не удалось: {e}", True
    except ValueError as e:
        return str(e), True
    return "Неизвестный инструмент.", True


_BOOKED_RE = re.compile(
    r"(вы записаны|ви записані|записал[аи]? вас|записав вас|записала вас|запись (создана|оформлена|подтверждена)"
    r"|запис (створено|оформлено|підтверджено)|you are booked|you're booked|booking (is )?confirmed)", re.I)

NO_LEAD_NOTE = ("[Служебная пометка, клиент её не видит] Запись НЕ создана: ты не вызвал create_lead. "
                "Если клиент уже подтвердил услугу, дату, время, имя и телефон, вызови create_lead сейчас. "
                "Если чего-то не хватает, спроси это. Не пиши, что клиент записан, пока инструмент не вернул номер записи. "
                "Если ты говорил о записи, которая уже есть в списке активных записей клиента, новую не создавай: повтори ответ.")


NO_LEAD_FALLBACK = {
    "ru": "Секунду, сверю запись с администратором и подтвержу здесь.",
    "uk": "Секунду, звірю запис з адміністратором і підтверджу тут.",
    "en": "One moment, I'll double-check the booking with the administrator and confirm here.",
}


def claims_booking(text: str) -> bool:
    """Ответ звучит как подтверждение записи."""
    return bool(_BOOKED_RE.search(text or ""))


async def _get_client():
    global client
    if client is None:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return client


def reset(user_id: int):
    for k in [k for k in _history if k[0] == user_id]:
        _history.pop(k, None)


def recent(user_id: int, niche_key: str, n: int = 4) -> list:
    """Последние реплики диалога (для сообщения владельцу)."""
    return _history.get((user_id, niche_key), [])[-n:]


async def ask(user_id: int, niche_key: str, text: str, image: bytes | None, actions,
              profile: dict, bookings: list) -> str:
    """Один ход диалога. Побочные действия идут через actions, возвращается текст ответа клиенту."""
    lock = _locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        key = (user_id, niche_key)
        hist = _history.setdefault(key, [])
        if image:
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(image).decode()}},
                {"type": "text", "text": text or "Клиент прислал фото без подписи. Пойми, чего он хочет, "
                                                  "и ответь по правилам компании."},
            ]
            memo = "[фото] " + (text or "")
        else:
            content, memo = text, text
        messages = hist + [{"role": "user", "content": content}]
        system = [
            {"type": "text", "text": static_system(niche_key), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": await dynamic_system(niche_key, profile, bookings)},
        ]
        c = await _get_client()
        answer = ""
        checked = False
        for _ in range(7):
            resp = await c.messages.create(
                model=config.CLAUDE_MODEL, max_tokens=700, system=system, tools=TOOLS, messages=messages)
            if resp.stop_reason != "tool_use":
                answer = "".join(b.text for b in resp.content if b.type == "text").strip()
                # Модель иногда пишет «вы записаны», не вызвав create_lead. Такой ответ клиенту не отдаём:
                # один раз возвращаем модели с пометкой, чтобы она создала запись или честно уточнила данные.
                if not checked and not actions.lead_id and claims_booking(answer):
                    checked = True
                    log.warning("ИИ подтвердил запись без create_lead (user %s): %s", user_id, answer[:120])
                    messages += [{"role": "assistant", "content": resp.content},
                                 {"role": "user", "content": NO_LEAD_NOTE}]
                    answer = ""
                    continue
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                res, is_err = await _run_tool(niche_key, b.name, b.input, actions, profile)
                log.info("инструмент %s (user %s): %s%s", b.name, user_id, "ошибка: " if is_err else "", res[:120])
                r = {"type": "tool_result", "tool_use_id": b.id, "content": res}
                if is_err:
                    r["is_error"] = True
                results.append(r)
            messages.append({"role": "user", "content": results})
        if checked and not actions.lead_id and claims_booking(answer):
            # второй раз подряд «записан» без записи: клиенту честно, владельцу — диалог для ручной записи
            log.error("ИИ снова подтвердил запись без create_lead (user %s): %s", user_id, answer[:120])
            answer = NO_LEAD_FALLBACK.get(i18n.resolve(profile), NO_LEAD_FALLBACK["ru"])
            try:
                await actions.ask_owner("ИИ не смог оформить запись", f"Сообщение клиента: {memo}"[:600])
            except Exception:
                log.exception("не удалось передать владельцу несостоявшуюся запись")
        if not answer:
            answer = "✅" if (actions.lead_id or actions.show_cabinet) else \
                i18n.t(i18n.resolve(profile), "handover_ok")
        hist.extend([{"role": "user", "content": memo}, {"role": "assistant", "content": answer}])
        del hist[:-10]
        return answer
