"""Воронка ADrenaline: сайт → сфера → демо → глазами владельца → презентация → запись на звонок → фоллоу-апы.
Прогон через настоящий Dispatcher (Telegram и Claude подменены). python -m tests.test_funnel"""
import asyncio
import os
import tempfile

os.environ["GA4_API_SECRET"] = ""  # тесты не шлют события в настоящий GA4
os.environ["DATA_DIR"] = tempfile.mkdtemp()
from datetime import datetime, timedelta  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import Contact, User  # noqa: E402

from app import ai, booking, config, db, funnel, sales  # noqa: E402
from app.bot import router  # noqa: E402
from app.niches import free_slots  # noqa: E402
from tests.fakes import ScriptedClient, say, tool  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update  # noqa: E402

SENT = []


class Fake(BaseSession):
    async def close(self): pass

    async def make_request(self, bot, method, timeout=None):
        n = type(method).__name__
        SENT.append(dict(m=n, chat=getattr(method, "chat_id", None), text=getattr(method, "text", None)
                         or getattr(method, "caption", None), markup=getattr(method, "reply_markup", None)))
        if n in ("SendMessage", "EditMessageText", "SendDocument"):
            return Message(message_id=1, date=datetime.now(), chat=Chat(id=getattr(method, "chat_id", None) or 1,
                                                                         type="private"), text="x")
        return True

    async def stream_content(self, *a, **k):
        yield b""


uid = 0


def msg(text=None, user=None, **kw):
    global uid
    uid += 1
    return Update(update_id=uid, message=Message(message_id=uid, date=datetime.now(),
                                                 chat=Chat(id=user.id, type="private"), from_user=user, text=text, **kw))


def cbq(data, user):
    global uid
    uid += 1
    m = Message(message_id=uid, date=datetime.now(), chat=Chat(id=user.id, type="private"),
                from_user=User(id=1, is_bot=True, first_name="b"), text="m")
    return Update(update_id=uid, callback_query=CallbackQuery(id=str(uid), from_user=user, chat_instance="c",
                                                              message=m, data=data))

SALES = 777
OWNER = 999
V = User(id=50, is_bot=False, first_name="Олена", username="olena_salon", language_code="uk")
V2 = User(id=51, is_bot=False, first_name="Ivan", language_code="ru")
V3 = User(id=52, is_bot=False, first_name="Max", language_code="de")
DAN = User(id=SALES, is_bot=False, first_name="Даниил", username="conversion_wizard")


def to(chat, contains=None):
    return [s for s in SENT if s["chat"] == chat and s["m"] in ("SendMessage", "EditMessageText")
            and (contains is None or contains in (s["text"] or ""))]


def last(chat):
    return to(chat)[-1]


def buttons(s):
    m = s["markup"]
    if m is None:
        return []
    if hasattr(m, "inline_keyboard"):
        return [(b.text, b.callback_data or b.url) for row in m.inline_keyboard for b in row]
    return [(b.text, None) for row in m.keyboard for b in row]


def data_of(s, starts):
    return next(d for _, d in buttons(s) if d and d.startswith(starts))


async def main():
    await db.init_db()
    await sales.init()
    booking.setup({})
    config.OWNER_ID, config.SALES_CHAT_ID, config.ANTHROPIC_API_KEY = OWNER, SALES, "test-key"
    config.USER_DAILY_LIMIT, config.GLOBAL_DAILY_LIMIT = 100, 1000
    config.FUNNEL_ENABLED = True
    bot = Bot("1:AAA", session=Fake(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(funnel.router)
    dp.include_router(router)
    feed = lambda u: dp.feed_update(bot, u)  # noqa: E731

    # 0. метка с сайта разбирается: источник + client_id GA
    assert sales.parse_payload("ai_123456789-1700000000") == ("ai", "123456789.1700000000")
    assert sales.parse_payload("home") == ("home", "")
    assert sales.parse_payload(None) == ("direct", "")
    assert sales.parse_payload("bad payload!!")[0] == "badpayload"

    # 1. вход с сайта: без выбора языка (uk из Telegram), сразу предложение выбрать сферу
    await feed(msg("/start ai_123456789-1700000000", V))
    s = last(V.id)
    assert "AI-адміністратора від ADrenaline" in s["text"]
    assert ("💇 Салон краси", "fn:salon") in buttons(s)
    p = await sales.get(V.id)
    assert p["source"] == "ai" and p["cid"] == "123456789.1700000000" and p["stage"] == "start"
    assert (await db.get_user(V.id))["lang"] == "uk"

    # 2. сфера → роль клиента и клавиатура с примерами и двумя кнопками
    await feed(cbq("fn:salon", V))
    s = last(V.id)
    assert "клієнт" in s["text"] and "Лаванда" in s["text"] and "««" not in s["text"] and "»»" not in s["text"]
    texts = [t for t, _ in buttons(s)]
    assert "👀 Очима власника" in texts and "📅 Дзвінок з ADrenaline" in texts and len(texts) == 5
    assert (await sales.get(V.id))["stage"] == "demo" and (await db.get_user(V.id))["niche"] == "salon"

    # 3. демо: запись как клиент → подсказка посмотреть глазами владельца
    day = next(d for d in ai.upcoming_days() if len(free_slots("salon", d)) >= 2)
    slot = free_slots("salon", day)[0]
    ai.client = ScriptedClient(tool("create_lead", service="Женская стрижка", date=day.isoformat(), time=slot,
                                    name="Олена", phone="0501234567"), say("Записала вас!"))
    await feed(msg("запишіть мене на стрижку", V))
    assert to(V.id, "Записала вас")
    assert to(V.id, "щойно записались")
    auto = to(V.id, "Так заявка приходить вам")      # его собственная заявка показывается сразу, без кнопки
    assert auto and "Олена" in auto[-1]["text"]
    p = await sales.get(V.id)
    assert p["demo_booked"] == 1 and p["demo_msgs"] == 1

    # 4. глазами владельца: реальная карточка его заявки + объяснение + кнопка презентации
    await feed(msg("👀 Очима власника", V))
    card = to(V.id, "Так заявка приходить вам")[-1]
    assert "Олена" in card["text"] and any(d and d.startswith("ok:") for _, d in buttons(card))
    expl = last(V.id)
    assert "нагадування" in expl["text"] and ("➡️ Що це дає бізнесу", "fpn:0") in buttons(expl)
    assert (await sales.get(V.id))["owner_seen"] == 1
    await feed(cbq("fo:report", V))
    assert any(x["m"] == "SendDocument" for x in SENT[-3:])

    # 4b. ИИ написал «записані», не вызвав create_lead → ответ не уходит клиенту, модель создаёт запись
    slot2 = free_slots("salon", day)[1]
    ai.client = ScriptedClient(say("Готово! Ви записані на завтра."),
                               tool("create_lead", service="Женская стрижка", date=day.isoformat(), time=slot2,
                                    name="Олена", phone="0501234567"),
                               say("Записала вас, запис №2."))
    n_before = len(to(V.id))
    await feed(msg("так, все вірно", V))
    new = [x["text"] or "" for x in to(V.id)[n_before:]]
    assert not any("Готово! Ви записані" in t for t in new) and any("№2" in t for t in new), new
    assert any("НЕ создана" in str(mm["content"]) for mm in ai.client.calls[1]["messages"])
    assert ai.claims_booking("Вы записаны на 16.10") and not ai.claims_booking("На какое время вас записать?")

    # 5. презентация: 6 экранов, калькулятор на 3-м
    await feed(cbq("fpn:0", V))
    assert "1/6" in last(V.id)["text"] and "21×" in last(V.id)["text"]
    await feed(cbq("fp:1", V))
    await feed(cbq("fp:2", V))
    s = last(V.id)
    assert "3/6" in s["text"] and ("10–30", "fc:v:1") in buttons(s)
    await feed(cbq("fc:v:1", V))                     # 10–30 в день
    assert "середній чек" in last(V.id)["text"]
    await feed(cbq("fc:c:1", V))                     # 500–1 500 ₴
    r = last(V.id)["text"]
    # 20/день × 30 = 600 → 15% = 90 → каждый пятый = 18 клиентов × 1000 ₴ = 18 000 ₴
    assert "600" in r and "90" in r and "18 000" in r and "$120" in r and "MedPlatforma" in r, r
    assert "у 3 рази менше" in r
    assert funnel.times_word(5, "uk") == "разів" and funnel.times_word(22, "uk") == "рази" and funnel.times_word(12, "ru") == "раз"
    p = await sales.get(V.id)
    assert p["volume"] == "1" and p["avg_check"] == "1" and "18 000" in p["calc"]
    for i in (3, 4, 5):
        await feed(cbq(f"fp:{i}", V))
    s = last(V.id)
    assert "6/6" in s["text"] and ("📅 Обрати час дзвінка", "fb:go") in buttons(s)
    assert any(d and "t.me/conversion_wizard" in d for _, d in buttons(s))
    assert (await sales.get(V.id))["pitch_seen"] == 5

    # 6. запись на звонок: объём уже известен из калькулятора → один вопрос, затем дни → время → формат
    await feed(cbq("fb:go", V))
    s = last(V.id)
    assert "Хто зараз відповідає" in s["text"]
    await feed(cbq("fq:h:1", V))                     # администратор
    s = last(V.id)
    assert "Оберіть день" in s["text"]
    d_data = data_of(s, "fs:d:")
    await feed(cbq(d_data, V))
    s = last(V.id)
    t_data = data_of(s, "fs:t:")
    assert "оберіть час" in s["text"]
    await feed(cbq(t_data, V))
    s = last(V.id)
    assert "Як зручніше" in s["text"]
    await feed(cbq(data_of(s, "ff:tg:"), V))
    booked = to(V.id, "Готово!")[-1]
    assert "дзвінок у Telegram" in booked["text"] and "Даниїлом" in booked["text"] and any(d and d.startswith("fb:re:") for _, d in buttons(booked))
    p = await sales.get(V.id)
    assert p["stage"] == "booked" and p["call_id"] and p["fu_next"] is None
    c = await sales.get_call(p["call_id"])
    assert c["format"] == "tg" and c["status"] == "booked"

    # 7. Даниил получает карточку со всем контекстом и подтверждает
    sc = to(SALES, "Запись на звонок")[-1]["text"]
    for part in ("olena_salon", "Салон", "10–30", "500–1 500", "Администратор", "18 000", "сайт /ai-admin",
                 "GA связан", "записался как клиент ✅", "презентация 6/6"):
        assert part in sc, (part, sc)
    await feed(cbq(f"sc:ok:{c['id']}", V))           # чужая кнопка — отказ
    assert (await sales.get_call(c["id"]))["status"] == "booked"
    await feed(cbq(f"sc:ok:{c['id']}", DAN))
    assert (await sales.get_call(c["id"]))["status"] == "confirmed"
    assert to(V.id, "підтвердив дзвінок")

    # 8. занятое окно больше не предлагается; повторная запись → «у вас уже есть звонок»
    at = datetime.fromisoformat(c["at"])
    assert at not in (await sales.free_slots()).get(at.date(), [])
    await feed(msg("/call", V))
    assert "уже є дзвінок" in last(V.id)["text"]

    # 9. Даниил пишет через бота
    await feed(cbq(f"sr:{V.id}", DAN))
    await feed(msg("Добрий день! До зв'язку завтра", DAN))
    assert to(V.id, "Даниїл, ADrenaline")

    # 10. перенос посетителем → окно освобождается, снова выбор дня
    await feed(cbq(f"fb:re:{c['id']}", V))
    assert (await sales.get_call(c["id"]))["status"] == "resched"
    assert "Оберіть день" in last(V.id)["text"] and to(SALES, "переносит звонок")
    assert at in (await sales.free_slots()).get(at.date(), [])

    # 11. второй посетитель: «хочу такого бота» в демо → кнопка записи + горячая карточка Даниилу
    await feed(msg("/start home", V2))
    assert "AI-администратора от ADrenaline" in last(V2.id)["text"]
    await feed(cbq("fn:other", V2))
    await feed(msg("фитнес-студия в Одессе", V2))
    assert to(V2.id, "Покажу на самом близком") and (await sales.get(V2.id))["biz_text"] == "фитнес-студия в Одессе"
    ai.client = ScriptedClient(tool("ask_owner", reason="Хочет такого бота для бизнеса", details="фитнес-студия"),
                               say("Отличная идея! Ниже кнопка, чтобы выбрать время звонка."))
    await feed(msg("а сколько стоит такой бот для меня?", V2))
    w = last(V2.id)
    assert "20-минутный звонок" in w["text"] and ("📅 Выбрать время звонка", "fb:go") in buttons(w)
    assert (await sales.get(V2.id))["want_bot"] == 1 and to(SALES, "Хочет такого бота")
    sysprompt = "".join(b["text"] for b in ai.client.calls[0]["system"] if b["type"] == "text")
    assert "сайта ADrenaline" in sysprompt and "$800" in sysprompt

    # 12. запись с телефоном: кнопка «поделиться номером»
    await feed(cbq("fb:go", V2))
    assert "Сколько обращений" in last(V2.id)["text"]
    await feed(cbq("fq:v:0", V2))
    await feed(cbq("fq:h:0", V2))
    s = last(V2.id)
    await feed(cbq(data_of(s, "fs:d:"), V2))
    await feed(cbq(data_of(last(V2.id), "fs:t:"), V2))
    await feed(cbq(data_of(last(V2.id), "ff:phone:"), V2))
    ask = last(V2.id)
    assert "Отправьте номер" in ask["text"] and ask["markup"].keyboard[0][0].request_contact
    await feed(msg("123", V2))
    assert "не номер телефона" in last(V2.id)["text"]
    await feed(msg(None, V2, contact=Contact(phone_number="+380671112233", first_name="Ivan", user_id=V2.id)))
    assert to(V2.id, "Готово!") and "+380671112233" in to(SALES, "по телефону")[-1]["text"]

    # 13. третий посетитель без меток, язык de → украинский по умолчанию; молчит → фоллоу-апы по расписанию
    await feed(msg("/start", V3))
    assert (await db.get_user(V3.id))["lang"] == "uk" and (await sales.get(V3.id))["source"] == "direct"
    await feed(cbq("fn:auto", V3))
    p = await sales.get(V3.id)
    last_active = datetime.fromisoformat(p["last_active"])
    nxt = datetime.fromisoformat(p["fu_next"])
    assert nxt >= last_active + timedelta(minutes=30) and 10 <= nxt.hour < 20
    n0 = len(to(V3.id))
    sent = await funnel.run_once(bot, nxt + timedelta(seconds=1))
    assert sent["followups"] >= 1 and len(to(V3.id)) == n0 + 1 and "ADrenaline" in last(V3.id)["text"]
    p = await sales.get(V3.id)
    assert p["fu_step"] == 1 and datetime.fromisoformat(p["fu_next"]) > nxt
    # следующий — про цифры, с кнопкой калькулятора
    await funnel.run_once(bot, datetime.fromisoformat(p["fu_next"]) + timedelta(seconds=1))
    assert "21×" in last(V3.id)["text"] and ("🧮 Порахувати мої втрати", "fpn:2") in buttons(last(V3.id))
    # «Не цікаво» → больше не пишем
    await feed(cbq("fu:stop", V3))
    p = await sales.get(V3.id)
    assert p["opted_out"] == 1 and "більше не пишу" in last(V3.id)["text"]
    n1 = len(to(V3.id))
    await funnel.run_once(bot, datetime.now(sales.TZ) + timedelta(days=30))
    assert len(to(V3.id)) == n1
    # записавшимся фоллоу-апы не приходят
    assert all(r["user_id"] != V2.id for r in await sales.due_followups(datetime.now(sales.TZ) + timedelta(days=30)))

    # 14. ночью не пишем: окно 10–20 по Киеву
    late = datetime(2026, 10, 20, 23, 15, tzinfo=sales.TZ)
    assert sales.in_window(late) == datetime(2026, 10, 21, 10, 0, tzinfo=sales.TZ)
    early = datetime(2026, 10, 20, 7, 0, tzinfo=sales.TZ)
    assert sales.in_window(early).hour == 10

    # 15. напоминание о звонке за 2 часа
    c2 = await sales.get_call((await sales.get(V2.id))["call_id"])
    at2 = datetime.fromisoformat(c2["at"])
    if not c2["reminded"]:
        await funnel.run_once(bot, at2 - timedelta(minutes=90))
        assert to(V2.id, "Напоминаю") and (await sales.get_call(c2["id"]))["reminded"] == 1
        assert to(SALES, "Скоро звонок")

    # 16. статистика для команды
    await feed(msg("/funnel", DAN))
    st = last(SALES)["text"]
    assert "Воронка демо" in st and "Записались" in st and "сайт /ai-admin" in st
    await feed(msg("/funnel", V3))                    # посторонним — нет
    assert "Воронка демо" not in (last(V3.id)["text"] or "")

    # 17. FUNNEL=0: старое поведение демо (выбор языка, приветствие компании)
    config.FUNNEL_ENABLED = False
    V4 = User(id=53, is_bot=False, first_name="Old")
    await feed(msg("/start", V4))
    assert "Choose your language" in last(V4.id)["text"]
    config.FUNNEL_ENABLED = True

    print("воронка ADrenaline: все проверки пройдены, отправок:", len(SENT))


if __name__ == "__main__":
    asyncio.run(main())
