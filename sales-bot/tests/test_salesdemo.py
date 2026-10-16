"""Демо «AI-менеджер продаж»: стартовый экран → заявка «с сайта» → приветствие и окна → запись кнопками и через ИИ →
глазами менеджера → переход к воронке ADrenaline. Telegram и Claude подменены. python -m tests.test_salesdemo"""
import asyncio
import os
import re
import tempfile

os.environ["GA4_API_SECRET"] = ""
os.environ["DATA_DIR"] = tempfile.mkdtemp()
from datetime import datetime  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Contact, Message, Update, User  # noqa: E402

from app import ai, booking, config, db, funnel, sales, salesdemo  # noqa: E402
from app.bot import router  # noqa: E402
from app.salesdemo_texts import ST  # noqa: E402
from tests.fakes import ScriptedClient, say, tool  # noqa: E402

SENT = []


class Fake(BaseSession):
    async def close(self): pass

    async def make_request(self, bot, method, timeout=None):
        n = type(method).__name__
        SENT.append(dict(m=n, chat=getattr(method, "chat_id", None), text=getattr(method, "text", None),
                         alert=getattr(method, "show_alert", None), markup=getattr(method, "reply_markup", None)))
        if n in ("SendMessage", "EditMessageText"):
            return Message(message_id=1, date=datetime.now(), chat=Chat(id=getattr(method, "chat_id", None) or 1,
                                                                         type="private"), text="x")
        return True

    async def stream_content(self, *a, **k):
        yield b""


_id = [0]


def msg(text, user, **kw):
    _id[0] += 1
    return Update(update_id=_id[0], message=Message(message_id=_id[0], date=datetime.now(),
                                                    chat=Chat(id=user.id, type="private"), from_user=user, text=text, **kw))


def cbq(data, user):
    _id[0] += 1
    m = Message(message_id=_id[0], date=datetime.now(), chat=Chat(id=user.id, type="private"),
                from_user=User(id=1, is_bot=True, first_name="b"), text="m")
    return Update(update_id=_id[0], callback_query=CallbackQuery(id=str(_id[0]), from_user=user, chat_instance="c",
                                                                 message=m, data=data))


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


def first_data(chat, prefix):
    for s in reversed(to(chat)):
        for _, d in buttons(s):
            if d and d.startswith(prefix):
                return d
    raise AssertionError(f"нет кнопки {prefix}")


SALES = 777
OL = User(id=60, is_bot=False, first_name="Олена", username="olena_dim", language_code="uk")
IV = User(id=61, is_bot=False, first_name="Иван", language_code="ru")
JO = User(id=62, is_bot=False, first_name="John", language_code="en")
PH = User(id=63, is_bot=False, first_name="Петро", language_code="uk")


def check_texts():
    """Все тексты демо есть на трёх языках и собираются без пустых {полей}."""
    for key, v in ST.items():
        assert set(v) >= {"uk", "ru", "en"}, f"{key}: нет языка"
        for lang in ("uk", "ru", "en"):
            val = salesdemo.tx(lang, key, name="N", svc="S", day="D", when="W", fmt="F", next="X", n=1001, src="s",
                               contact="c", campaign="c", plan="p", x="x")
            parts = val.values() if isinstance(val, dict) else [val]
            for p in parts:
                if isinstance(p, dict):
                    p = " ".join(p.values())
                left = set(re.findall(r"\{[a-z_]+\}", p)) - {"{phone}", "{x}"}
                assert not left, f"{key}/{lang}: {left}"
    r = salesdemo.rules()
    assert "Марины" in r and "Промінь Енерджі" in r and "$8 200" in r and "{" not in r


async def main():
    check_texts()
    await db.init_db()
    await sales.init()
    booking.setup({})
    config.SALES_CHAT_ID, config.OWNER_ID, config.ANTHROPIC_API_KEY = SALES, 999, "k"
    config.USER_DAILY_LIMIT, config.GLOBAL_DAILY_LIMIT = 100, 1000
    config.FUNNEL_ENABLED = config.DEMO_MODE = True
    bot = Bot("1:AAA", session=Fake(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(funnel.router)
    dp.include_router(salesdemo.router)
    dp.include_router(router)
    feed = lambda u: dp.feed_update(bot, u)  # noqa: E731

    # 1. стартовый экран: есть кнопка бота продаж и подсказка о ней
    await feed(msg("/start ai_1-2", OL))
    s = last(OL.id)
    assert ("🤝 Бот продажів (заявки з сайту)", "fn:salesbot") in buttons(s) and "Бот продажів" in s["text"]

    # 2. выбор → объяснение и роль клиента «Промінь Енерджі», три услуги
    await feed(cbq("fn:salesbot", OL))
    s = last(OL.id)
    assert "AI-менеджер продажів" in s["text"] and "Промінь Енерджі" in s["text"]
    assert [d for _, d in buttons(s)] == ["sd:svc:0", "sd:svc:1", "sd:svc:2"]
    assert (await db.get_user(OL.id))["niche"] == "salesbot" and (await sales.get(OL.id))["biz"] == "salesbot"

    # 3. «отправил форму»: сообщение про сайт с клавиатурой, приветствие бота продаж с окнами, подсказка
    n0 = len(to(OL.id))
    await feed(cbq("sd:svc:1", OL))
    new = to(OL.id)[n0:]
    assert "Заявку з сайту відправлено" in new[0]["text"]
    kb = [t for t, _ in buttons(new[0])]
    assert "👀 Очима менеджера" in kb and "📅 Дзвінок з ADrenaline" in kb and "Чи є розстрочка?" in kb
    hello = new[1]["text"]
    assert "Вітаю, Олена!" in hello and "AI-асистент Марини" in hello and "«Сонячна станція для дому»" in hello
    assert "Марина за 15 хвилин" in hello and first_data(OL.id, "sd:d:")

    # 4. запись кнопками: день → время → Google Meet → подтверждение + глазами менеджера + сигнал команде
    await feed(cbq(first_data(OL.id, "sd:d:"), OL))
    assert "оберіть час" in last(OL.id)["text"]
    t = first_data(OL.id, "sd:t:")
    await feed(cbq(t, OL))
    assert "Як зручніше поговорити?" in last(OL.id)["text"]
    n0 = len(to(OL.id))
    await feed(cbq(first_data(OL.id, "sd:f:meet:"), OL))
    new = to(OL.id)[n0:]
    texts = [x["text"] for x in new]
    assert texts[0].startswith("✅ Готово! Дзвінок з Мариною") and "Google Meet" in texts[0]
    assert any("Ви щойно записалися як клієнт" in x for x in texts)
    card = next(x for x in new if "Лід #" in (x["text"] or ""))
    assert "заявка з сайту" in card["text"] and "@olena_dim" in card["text"] and "Сонячна станція" in card["text"]
    assert [d for _, d in buttons(card)] == ["sd:mg:take", "sd:mg:msg", "sd:mg:lost"]
    feed_msg = next(x for x in new if "Стрічка по ліду" in (x["text"] or ""))
    assert "Клієнт відкрив Telegram-бота" in feed_msg["text"] and "Записався на дзвінок" in feed_msg["text"]
    assert "Надіслати посилання на Meet" in feed_msg["text"] and ("✅ Підтвердити", "sd:mg:ok") in buttons(feed_msg)
    expl = next(x for x in new if "Що ще робить бот продажів" in (x["text"] or ""))
    assert {"fpn:0", "fb:go", "sd:restart"} <= {d for _, d in buttons(expl)}
    assert to(SALES, "демо <b>бота продаж</b>") and "Бот продаж (демо" in last(SALES)["text"]
    p = await sales.get(OL.id)
    assert p["demo_booked"] == 1 and p["owner_seen"] == 1 and p["stage"] == "owner"

    # 5. кнопки менеджера в демо объясняют, что они делают в настоящем боте
    await feed(cbq("sd:mg:take", OL))
    a = [x for x in SENT if x["m"] == "AnswerCallbackQuery"][-1]
    assert a["alert"] and "ІІ і автоматика" in a["text"]

    # 6. вопрос → ИИ отвечает по фактам; повторный выбор времени — «уже есть дзвінок»
    ai.client = ScriptedClient(say("Гібридна станція на 10 кВт — від $8 200 під ключ, монтаж 2–3 дні."))
    await feed(msg("Скільки коштує станція на 10 кВт?", OL))
    assert "$8 200" in last(OL.id)["text"]
    call = ai.client.calls[0]
    assert "AI-ассистент Марины" in call["system"][0]["text"] and "Уже записан" in call["system"][1]["text"]
    assert call["messages"][-1] == {"role": "user", "content": "Скільки коштує станція на 10 кВт?"}
    await feed(cbq(t, OL))
    assert "У вас уже є дзвінок" in last(OL.id)["text"]
    await feed(msg("👀 Очима менеджера", OL))
    assert to(OL.id, "💬 Скільки коштує станція на 10 кВт?")

    # 7. перенос и отмена
    await feed(cbq("sd:x", OL))
    assert "Дзвінок скасовано" in last(OL.id)["text"] and not (await salesdemo.load(OL.id))["call"]

    # 8. русский: пишет сам, без заявки → ИИ записывает фразой «завтра в 12 в мит» (book_call)
    await feed(msg("/start", IV))
    await feed(cbq("fn:salesbot", IV))
    slot = next(x for ts in salesdemo.free().values() for x in ts)
    ai.client = ScriptedClient(tool("save_info", business="дом, Буча", request="резерв на отключения"),
                               tool("book_call", datetime=f"{slot:%Y-%m-%dT%H:%M}", format="meet"),
                               say("Записала вас, до встречи!"))
    n0 = len(to(IV.id))
    await feed(msg("Здравствуйте, нужен резерв для дома в Буче, давайте в мит", IV))
    texts = [x["text"] for x in to(IV.id)[n0:]]
    assert texts[0].startswith("✅ Готово! Звонок с Мариной") and texts[1] == "Записала вас, до встречи!"
    assert any("Вы только что записались как клиент" in x for x in texts)
    assert any("написал боту сам" in x for x in texts) and any("Бот узнал: дом, Буча" in x for x in texts)
    d = await salesdemo.load(IV.id)
    assert d["call"]["fmt"] == "meet" and d["biz"] == "дом, Буча"

    # 9. handoff: скидка → менеджер, пометка про демо, в ленте «Нужна Марина»
    ai.client = ScriptedClient(tool("handoff", reason="просит скидку"), say("Уточню у Марины, она ответит здесь."))
    await feed(msg("А скидку дадите?", IV))
    assert "в настоящем боте здесь ИИ замолкает" in last(IV.id)["text"]
    await feed(msg("👀 Глазами менеджера", IV))
    assert to(IV.id, "Нужна Марина</b>: просит скидку")

    # 10. второй записи ИИ не создаёт
    ai.client = ScriptedClient(tool("book_call", datetime=f"{slot:%Y-%m-%dT%H:%M}", format="tg"), say("Вы уже записаны."))
    await feed(msg("Запишите ещё раз", IV))
    assert "уже записан" in ai.client.calls[1]["messages"][-1]["content"][0]["content"]

    # 11. английский и формат «телефоном»: номер текстом
    await feed(msg("/start", JO))
    await feed(msg("Hello, I want to see the sales bot please", JO))      # язык стартового экрана → en
    await feed(cbq("fn:salesbot", JO))
    assert "AI sales manager" in last(JO.id)["text"]
    await feed(cbq("sd:svc:0", JO))
    assert to(JO.id, "Hello, John! I'm Maryna's AI assistant at \"Promin Energy\"")
    await feed(cbq(first_data(JO.id, "sd:d:"), JO))
    await feed(cbq(first_data(JO.id, "sd:t:"), JO))
    await feed(cbq(first_data(JO.id, "sd:f:phone:"), JO))
    assert "Send the number to call" in last(JO.id)["text"]
    await feed(msg("abc", JO))
    assert "doesn't look like a phone number" in last(JO.id)["text"]
    await feed(msg("+380 67 123 45 67", JO))
    assert to(JO.id, "Maryna will call +380671234567") and to(JO.id, "☎️ Call +380671234567")

    # 12. контакт кнопкой на шаге номера
    await feed(msg("/start", PH))
    await feed(cbq("fn:salesbot", PH))
    await feed(cbq("sd:svc:2", PH))
    await feed(cbq(first_data(PH.id, "sd:d:"), PH))
    await feed(cbq(first_data(PH.id, "sd:t:"), PH))
    await feed(cbq(first_data(PH.id, "sd:f:phone:"), PH))
    await feed(msg(None, PH, contact=Contact(phone_number="380501112233", first_name="Петро", user_id=PH.id)))
    assert to(PH.id, "Марина подзвонить на +380501112233")

    # 13. «Глазами менеджера» до заявки — просит оставить заявку
    U = User(id=64, is_bot=False, first_name="Оля", language_code="uk")
    await feed(msg("/start", U))
    await feed(cbq("fn:salesbot", U))
    await feed(msg("👀 Очима менеджера", U))
    assert "Спершу залиште тестову заявку" in last(U.id)["text"]

    # 13b. ИИ записывает только в свободное окно
    ai.client = ScriptedClient(tool("book_call", datetime="2020-01-01T03:00", format="meet"), say("Этот час зайнятий."))
    await feed(msg("Запишіть на 3 ночі", U))
    assert "недоступно" in ai.client.calls[1]["messages"][-1]["content"][0]["content"]
    assert not (await salesdemo.load(U.id))["call"]

    # 14. лимит ИИ: вежливый ответ, в ленте пометка для команды
    config.USER_DAILY_LIMIT = 0
    await feed(msg("Є розстрочка?", U))
    assert "Марина відповість вам тут особисто" in last(U.id)["text"]
    config.USER_DAILY_LIMIT = 100

    # 15. другая сфера выключает демо продаж: текст снова идёт AI-администратору салона
    await feed(cbq("fn:salon", OL))
    assert (await db.get_user(OL.id))["niche"] == "salon"
    ai.client = ScriptedClient(say("Жіноча стрижка коштує 700 ₴."))
    await feed(msg("Скільки коштує стрижка?", OL))
    assert "700 ₴" in last(OL.id)["text"] and "Лаванда" in ai.client.calls[0]["system"][0]["text"]

    # 16. «Пройти ещё раз» — новый номер лида, кнопка звонка ADrenaline ведёт в обычную запись
    await feed(cbq("sd:restart", IV))
    assert (await salesdemo.load(IV.id))["n"] == d["n"] + 1
    await feed(msg("📅 Звонок с ADrenaline", IV))
    assert "fq:v:0" in [x for _, x in buttons(last(IV.id))]

    print(f"демо бота продаж: все проверки пройдены, отправок: {len(SENT)}")


if __name__ == "__main__":
    asyncio.run(main())
