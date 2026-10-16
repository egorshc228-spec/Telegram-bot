"""AI-агент продаж: отвечает лиду в Telegram или WhatsApp и доводит до записи на 20-минутный звонок с Даниилом.

Агент не выдумывает: цены и условия — только из FACTS, время — только из свободных окон. Всё, чего нет в данных,
передаёт Даниилу (handoff). Честно представляется AI-ассистентом."""
import logging
from datetime import datetime
from types import SimpleNamespace

from . import config, db, slots
from .texts import WD, when

log = logging.getLogger("agent")
client = None            # AsyncAnthropic; в тестах подменяется

FACTS = """\
ADrenaline — Даниил Сулим, growth-маркетолог из Одессы, работает с бизнесами по всей Украине. Сайт adrenalinegrowth.com.
Что делаем: Google Ads и веб-аналитика (заявки считаются до звонка/записи), AI-администратор для директа/Telegram/сайта,
пакеты «реклама + быстрый ответ на заявки». Команда: Даниил (реклама, аналитика, продажи) и разработчики AI-ботов.

Цены (как на сайте, в долларах):
- Google Ads + аналитика: «Старт» $600/мес, запуск $300 (1 направление, 1 город, рекламный бюджет до $1 500);
  «Рост» $900/мес, запуск $450 (до 3 направлений или 2 городов, бюджет до $4 000); «Магазин» $1 200/мес, запуск $600
  (фид Merchant Center или бюджет от $4 000). При договоре от 3 месяцев запуск $0. Рекламный бюджет оплачивается отдельно.
- AI-администратор / AI-директ-менеджер: запуск $800, дальше $160/мес вместе с сервером и ИИ (до 1 000 диалогов);
  первая версия за неделю, 14 дней донастройки на реальных диалогах. Второй канал +$150 и +$30/мес, интеграция с CRM +$200.
- Пакет «AI-стек» (AI-директ + сообщение после пропущенного звонка + отзывы): $1 250 запуск + $260/мес.
- Пакеты с рекламой: «Поток заявок» $650/мес, «Заявка → клиент» $760/мес ($685 при договоре на 6 месяцев),
  «Полный цикл» $1 000/мес (цены пакетов — для тарифа «Старт»).
- Аудит рекламного кабинета $150, сумма засчитывается в запуск, если продолжаем.
- Веб-аналитика отдельно $250 (магазин $450), Google Карты $350/мес.
Гарантия: если согласованная цена заявки не достигнута за 1,5 месяца — следующий месяц работы бесплатно. Целевую цену
заявки фиксируем в договоре через две недели работы на данных клиента. Возвратов и бесплатных пилотов нет.
Кейсы (без названий клиентов): клиника — цена заявки −12% после починки учёта записей; магазин одежды с AI-директом —
медиана ответа 4 ч 23 мин → 36 секунд, ответы за 5 минут 21% → 77%, 45% диалогов бот довёл сам.
Звонок с Даниилом: 20 минут, бесплатно; Даниил смотрит, откуда сейчас заявки, что мешает и что исправить первым."""

RULES = """\
Ты — AI-ассистент Даниила из ADrenaline. Человек оставил заявку (или написал сам), твоя цель — записать его на 20-минутный
звонок с Даниилом. Это продажа через пользу, не давление.

Как общаться:
- Пиши как живой менеджер: 1–3 коротких предложения, без markdown (никаких **, #, списков со звёздочками), максимум одно эмодзи.
- Отвечай на языке человека (украинский или русский; язык лида указан ниже). Обращайся на «вы».
- Если спрашивают, бот ли ты — честно: ты AI-ассистент Даниила, Даниил лично проведёт звонок.
- На вопрос отвечай по сути из фактов, потом мягко веди к звонку. Не задавай больше одного вопроса за раз.
- Если о бизнесе ничего не известно, можно один раз уточнить сферу и город — это поможет Даниилу подготовиться (save_info).
- Не выдумывай цены, сроки, кейсы, обещания результата. Нет в фактах — «уточню у Даниила» и handoff.

Запись:
- Чтобы показать человеку кнопки со свободным временем, вызови show_slots. Время называй только из списка свободных окон.
- Если человек сам назвал день и время, и оно есть в свободных окнах, и понятен формат — вызови book_call.
  Форматы: tg (звонок в Telegram, только если канал Telegram), wa (звонок в WhatsApp, только если канал WhatsApp),
  meet (Google Meet), phone (обычный звонок — нужен номер). Формат не назван — спроси или покажи кнопки (show_slots).
- «Сегодня», «завтра», «в четверг» — считай от текущей даты ниже; день недели — ближайший такой день в будущем.
- После успешного book_call подтверждение с деталями уходит отдельным сообщением: не повторяй детали, ответь одной фразой.

Когда звать Даниила (handoff): просит живого человека, сложный или нестандартный вопрос, торг/скидки, жалоба, партнёрство,
вопрос не по теме ADrenaline. Скажи, что Даниил ответит здесь лично.
Если человек прямо говорит, что неинтересно / не пишите — вызови stop_contact и вежливо попрощайся."""

TOOLS = [
    {"name": "show_slots", "description": "Показать человеку кнопки со свободными днями и временем звонка.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "book_call", "description": "Записать на звонок, когда известны время из свободных окон и формат.",
     "input_schema": {"type": "object", "properties": {
         "datetime": {"type": "string", "description": "YYYY-MM-DDTHH:MM по Киеву"},
         "format": {"type": "string", "enum": ["tg", "wa", "meet", "phone"]},
         "phone": {"type": "string", "description": "Номер для формата phone, если человек его назвал"}},
         "required": ["datetime", "format"]}},
    {"name": "save_info", "description": "Сохранить то, что человек рассказал: имя, телефон, бизнес, запрос.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "phone": {"type": "string"},
         "business": {"type": "string", "description": "Сфера и город"},
         "request": {"type": "string", "description": "Что хочет / что болит"}}}},
    {"name": "handoff", "description": "Передать разговор Даниилу лично.",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    {"name": "stop_contact", "description": "Человек не хочет общаться: больше не писать ему.",
     "input_schema": {"type": "object", "properties": {}}},
]


async def _client():
    global client
    if client is None:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return client


async def _slots_text() -> str:
    free = await slots.free()
    if not free:
        return "Свободных окон нет — предложи передать Даниилу (handoff)."
    return "\n".join(f"- {d.isoformat()} ({WD['ru'][d.weekday()]}): " + ", ".join(f"{x:%H:%M}" for x in ts)
                     for d, ts in list(free.items())[:6])


def _lead_text(lead: dict) -> str:
    keys = [("name", "Имя"), ("phone", "Телефон"), ("contact", "Контакт из формы"), ("service", "Что интересует"),
            ("niche", "Ниша и город"), ("site", "Сайт"), ("budget", "Бюджет"), ("pain", "Проблема (квиз)"),
            ("biz", "Бизнес (из разговора)"), ("request", "Запрос (из разговора)")]
    lines = [f"{label}: {lead[k]}" for k, label in keys if lead.get(k)]
    src = {"site": "заявка с сайта", "tg": "написал боту сам", "wa": "написал в WhatsApp сам"}.get(lead.get("source"), "")
    return "\n".join([f"Источник: {src}"] + lines)


async def system(lead: dict) -> list[dict]:
    now = db.now()
    ch = {"tg": "Telegram", "wa": "WhatsApp"}.get(lead.get("channel"), "—")
    call = await db.active_call(lead["id"])
    booked = (f"Уже записан: {when(datetime.fromisoformat(call['at']), 'ru')}, формат {call['format']}. Новую запись не создавай,"
              f" перенос — через show_slots." if call else "Пока не записан.")
    dyn = (f"Сейчас {now:%Y-%m-%d %H:%M}, {WD['ru'][now.weekday()]} (Киев). Канал: {ch}. "
           f"Язык лида: {'русский' if lead.get('lang') == 'ru' else 'украинский'}.\n{booked}\n\n"
           f"Данные лида:\n{_lead_text(lead)}\n\nСвободные окна для звонка:\n{await _slots_text()}")
    return [{"type": "text", "text": RULES + "\n\nФакты:\n" + FACTS, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dyn}]


def _messages(hist: list[dict]) -> list[dict]:
    out: list[dict] = []
    for h in hist:
        role = "user" if h["dir"] == "in" else "assistant"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + h["text"]
        else:
            out.append({"role": role, "content": h["text"]})
    if out and out[0]["role"] != "user":         # диалог начал бот (приветствие): даём модели этот контекст
        out.insert(0, {"role": "user", "content": "[человек открыл чат]"})
    return out


async def reply(lead: dict, actions) -> str:
    """Один ход. Последнее сообщение человека уже записано в историю. actions — колбэки ядра (core.Actions)."""
    messages = _messages(await db.history(lead["id"]))
    if not messages:
        return ""
    sysmsg = await system(lead)
    c = await _client()
    text = ""
    for _ in range(5):
        resp = await c.messages.create(model=config.CLAUDE_MODEL, max_tokens=500, system=sysmsg, tools=TOOLS,
                                       messages=messages)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if resp.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            res, err = await _run(b.name, b.input or {}, lead, actions)
            log.info("инструмент %s (лид %s): %s", b.name, lead["id"], res[:120])
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": res, **({"is_error": True} if err else {})})
        messages.append({"role": "user", "content": results})
    return text


async def _run(name: str, args: dict, lead: dict, actions) -> tuple[str, bool]:
    try:
        if name == "show_slots":
            actions.show_slots = True
            return "Кнопки со свободным временем будут показаны отдельным сообщением. Коротко подведи к выбору.", False
        if name == "book_call":
            at = slots.parse_any(str(args.get("datetime", "")))
            fmt = str(args.get("format", ""))
            if not at:
                return "Неверный формат времени. Нужен YYYY-MM-DDTHH:MM.", True
            allowed = {"tg": {"tg", "meet", "phone"}, "wa": {"wa", "meet", "phone"}}.get(lead.get("channel"), {"meet", "phone"})
            if fmt not in allowed:
                return f"Формат {fmt} недоступен в этом канале. Доступно: {', '.join(sorted(allowed))}.", True
            if not await slots.is_free(at):
                return f"Время {at:%Y-%m-%d %H:%M} недоступно. Свободно:\n{await _slots_text()}", True
            phone = str(args.get("phone") or lead.get("phone") or "")
            if fmt == "phone" and sum(ch.isdigit() for ch in phone) < 9:
                return "Для звонка по телефону нужен номер. Спроси его.", True
            ok = await actions.book(at, fmt, phone)
            return ("Запись создана, клиенту отправлено подтверждение с деталями. Ответь одной короткой фразой."
                    if ok else "Не удалось записать: окно заняли. Предложи show_slots."), not ok
        if name == "save_info":
            fields = {"name": args.get("name"), "phone": args.get("phone"), "biz": args.get("business"),
                      "request": args.get("request")}
            await db.update_lead(lead["id"], **{k: str(v)[:300] for k, v in fields.items() if v})
            lead.update({k: v for k, v in fields.items() if v})
            return "Сохранено.", False
        if name == "handoff":
            actions.handoff = str(args.get("reason", ""))[:300] or "попросил Даниила"
            return "Передано Даниилу. Скажи, что Даниил ответит здесь лично.", False
        if name == "stop_contact":
            actions.stop = True
            return "Больше не пишем. Вежливо попрощайся одной фразой.", False
    except Exception as e:                       # инструмент не должен ронять диалог
        log.exception("инструмент %s", name)
        return f"Ошибка: {e}", True
    return "Неизвестный инструмент.", True


def new_actions(book_cb) -> SimpleNamespace:
    return SimpleNamespace(show_slots=False, handoff="", stop=False, book=book_cb)
