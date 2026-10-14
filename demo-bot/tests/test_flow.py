"""Полный прогон через настоящий Dispatcher aiogram: Telegram и Claude подменены. python -m tests.test_flow"""
import asyncio
import os
import tempfile

os.environ["GA4_API_SECRET"] = ""  # тесты не шлют события в настоящий GA4
os.environ["DATA_DIR"] = tempfile.mkdtemp()
from datetime import datetime  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery, Chat, File, Message, PhotoSize, Update, User, Voice  # noqa: E402

from app import ai, booking, config, db  # noqa: E402
from app.bot import router  # noqa: E402
from app.niches import free_slots  # noqa: E402
from tests.fakes import ScriptedClient, say, tool  # noqa: E402

SENT = []
OWNER_ID = 999


class Fake(BaseSession):
    async def close(self): pass

    async def make_request(self, bot, method, timeout=None):
        n = type(method).__name__
        SENT.append(dict(m=n, chat=getattr(method, "chat_id", None), text=getattr(method, "text", None)
                         or getattr(method, "caption", None), markup=getattr(method, "reply_markup", None)))
        if n in ("SendMessage", "EditMessageText", "SendDocument"):
            return Message(message_id=1, date=datetime.now(), chat=Chat(id=1, type="private"), text="x")
        if n == "GetFile":
            return File(file_id="f", file_unique_id="u", file_path="p.jpg")
        return True

    async def stream_content(self, *a, **k):
        yield b"\xff\xd8img"


CLIENT = User(id=1, is_bot=False, first_name="C", username="client")
CLIENT2 = User(id=2, is_bot=False, first_name="D", username="second")
CLIENT3 = User(id=3, is_bot=False, first_name="E", username="third", language_code="uk")
OWNER = User(id=OWNER_ID, is_bot=False, first_name="O", username="owner")
uid = 0


def _chat(u):
    return Chat(id=u.id, type="private")


def msg(text=None, user=CLIENT, **kw):
    global uid
    uid += 1
    return Update(update_id=uid, message=Message(message_id=uid, date=datetime.now(), chat=_chat(user),
                                                 from_user=user, text=text, **kw))


def photo(caption=None, user=CLIENT):
    return msg(None, user, caption=caption, photo=[PhotoSize(file_id="f", file_unique_id="u", width=9, height=9)])


def cbq(data, user=OWNER):
    global uid
    uid += 1
    m = Message(message_id=uid, date=datetime.now(), chat=_chat(user),
                from_user=User(id=1, is_bot=True, first_name="b"), text="m")
    return Update(update_id=uid, callback_query=CallbackQuery(id=str(uid), from_user=user, chat_instance="c",
                                                              message=m, data=data))


def to(chat, contains=None):
    """Сообщения, отправленные боту-в-чат chat (и содержащие текст)."""
    return [s for s in SENT if s["chat"] == chat and s["m"] == "SendMessage" and (contains is None or contains in (s["text"] or ""))]


async def main():
    await db.init_db()
    booking.setup({})
    config.OWNER_ID, config.ANTHROPIC_API_KEY = OWNER_ID, "test-key"
    config.USER_DAILY_LIMIT, config.GLOBAL_DAILY_LIMIT = 100, 1000
    bot = Bot("1:AAA", session=Fake(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    feed = lambda u: dp.feed_update(bot, u)  # noqa: E731

    day = next(d for d in ai.upcoming_days() if len(free_slots("salon", d)) >= 3)
    s1, s2, s3 = free_slots("salon", day)[:3]

    # 1. старт: сначала выбор языка (кнопки только здесь), затем стартовое сообщение без кнопок
    await feed(msg("/start"))
    ch = to(1)[-1]
    assert "Choose your language" in ch["text"] and len(ch["markup"].inline_keyboard[0]) == 3
    await feed(cbq("lang:ru", CLIENT))
    assert (await db.get_user(1))["lang"] == "ru"
    w = to(1, "Какие услуги есть")[-1]
    assert "Какие услуги есть" in w["text"] and "Женская стрижка" in w["text"] and "Кнопок нет" in w["text"]
    assert w["markup"] is None

    # 2. обычное приветствие, ответ Claude без кнопок
    ai.client = ScriptedClient(say("Здравствуйте! Чем помочь?"))
    await feed(msg("привет"))
    assert to(1, "Чем помочь") and to(1)[-1]["markup"] is None

    # 3. запись текстом: профиль сохраняется, владелец получает заявку с кнопками
    ai.client = ScriptedClient(tool("create_lead", service="Женская стрижка", date=day.isoformat(), time=s1,
                                    name="Анна", phone="0501234567"), say("Записала вас!"))
    await feed(msg("запишите на стрижку, я Анна 0501234567"))
    l1 = await db.get_lead(1)
    assert l1["name"] == "Анна" and l1["source"] == "AI-диалог" and l1["status"] == "new"
    prof = await db.get_user(1)
    assert prof["name"] == "Анна" and prof["phone"] == "0501234567"
    card = to(OWNER_ID, "Демо-заявка")[-1]
    assert card["markup"] is not None and "Анна" in card["text"]

    # 4. вторая запись без имени и телефона: берутся из профиля
    ai.client = ScriptedClient(tool("create_lead", service="Укладка", date=day.isoformat(), time=s2),
                               say("Готово"))
    await feed(msg("и ещё укладку"))
    l2 = await db.get_lead(2)
    assert l2["name"] == "Анна" and l2["phone"] == "0501234567"
    assert any(b["type"] == "text" and "не спрашивай" in b["text"] for b in ai.client.calls[0]["system"])

    # 5. личный кабинет командой и словами
    await feed(msg("/cabinet"))
    cab = to(1, "Личный кабинет")[-1]["text"]
    assert "Календарь записей" in cab and "[" in cab and "Анна" in cab and "№1" in cab and "№2" in cab
    n_before = len(to(1, "Личный кабинет"))
    ai.client = ScriptedClient(tool("show_cabinet"), say("Вот ваши записи"))
    await feed(msg("покажи мои записи"))
    assert to(1, "Вот ваши записи") and len(to(1, "Личный кабинет")) == n_before + 1

    # 6. изменение профиля: командой и через Claude
    await feed(msg("/name Ольга"))
    await feed(msg("/phone 0671112233"))
    await feed(msg("/phone abc"))
    p = await db.get_user(1)
    assert p["name"] == "Ольга" and p["phone"] == "0671112233"
    await feed(msg("/profile"))
    assert "Ольга" in to(1, "Ваши данные")[-1]["text"]
    ai.client = ScriptedClient(tool("update_profile", name="Оля"), say("Сохранила"))
    await feed(msg("изменить имя на Оля"))
    assert (await db.get_user(1))["name"] == "Оля"

    # 7. вопрос вне данных: бот зовёт владельца, владелец отвечает клиенту прямо в боте
    ai.client = ScriptedClient(tool("ask_owner", reason="Просит скидку 50%", details="Хочет скидку"),
                               say("Сейчас спрошу у владельца и отвечу вам здесь"))
    await feed(msg("дайте скидку 50%"))
    assert to(1, "спрошу у владельца")
    esc_msg = to(OWNER_ID, "Нужно вмешательство")[-1]
    assert "Просит скидку" in esc_msg["text"] and "Последние сообщения" in esc_msg["text"]
    assert esc_msg["markup"].inline_keyboard[0][0].callback_data == "rp:1"
    await feed(cbq("rp:1"))
    await feed(msg("Скидку 10% сделаем", OWNER))
    assert to(1, "Скидку 10% сделаем")
    await feed(cbq("rp:1", CLIENT))                    # чужая кнопка не включает режим ответа
    ai.client = ScriptedClient(say("Принято"))
    await feed(msg("текст клиента", CLIENT))
    assert to(1, "Принято") and not to(OWNER_ID, "текст клиента")      # ушёл в Claude, а не владельцу

    # 8. отмена записи через Claude: запись отменена, владелец знает
    ai.client = ScriptedClient(tool("cancel_booking", booking_id=2), say("Отменила запись №2"))
    await feed(msg("отмени укладку"))
    assert (await db.get_lead(2))["status"] == "cancel" and to(OWNER_ID, "отменил запись")
    ai.client = ScriptedClient(tool("cancel_booking", booking_id=2), say("Эту запись уже нельзя отменить"))
    await feed(msg("отмени ещё раз"))
    assert ai.client.calls[1]["messages"][-1]["content"][0]["is_error"]

    # 9. отзыв: командой (оценка + текст) и через Claude (низкая оценка → предупреждение владельцу)
    await feed(msg("/review"))
    await feed(msg("просто отлично"))                  # без оценки: переспрашивает
    assert to(1, "оценку числом")
    await feed(msg("4/5 хорошо, но долго"))
    rv = (await db.user_reviews(1, "salon"))[0]
    assert rv["rating"] == 4 and rv["text"] == "хорошо, но долго"
    assert to(OWNER_ID, "Новый отзыв: 4/5") and to(1, "Спасибо за отзыв")
    ai.client = ScriptedClient(tool("leave_review", rating=2, text="грубо ответили"), say("Спасибо, что сказали"))
    await feed(msg("поставлю 2, грубо ответили"))
    assert to(OWNER_ID, "Низкая оценка")

    # 10. фото без подписи уходит в Claude как картинка
    ai.client = ScriptedClient(say("Это маникюр, могу записать"))
    await feed(photo())
    content = ai.client.calls[0]["messages"][-1]["content"]
    assert content[0]["type"] == "image" and to(1, "маникюр")

    # 11. демо: переключение компании, взгляд владельца, отчёт, пользователь не видит чужое
    await feed(msg("/auto"))
    assert to(1, "Мотор-Сервис")
    await feed(msg("/owner"))
    assert to(1, "Сначала запишитесь")
    await feed(msg("/salon"))
    await feed(msg("/owner"))
    assert to(1, "Так заявка выглядит")
    await feed(cbq("ok:1", CLIENT))
    assert (await db.get_lead(1))["status"] == "ok"
    await feed(cbq("ok:1", CLIENT2))                   # чужая заявка
    await feed(msg("/report"))
    assert any(s["m"] == "SendDocument" for s in SENT)

    # 12. кнопки владельца: подтверждение приходит клиенту
    await feed(cbq("no:1", OWNER))
    assert (await db.get_lead(1))["status"] == "no" and to(1, "время недоступно")

    # 13. команды владельца
    await feed(msg("/stats", OWNER))
    assert to(OWNER_ID, "Пользователей")
    await feed(msg("/reviews", OWNER))
    assert to(OWNER_ID, "Отзывы")
    n = len(SENT)
    await feed(msg("/stats", CLIENT))
    assert len(SENT) == n, "обычному клиенту /stats не отвечает"

    # 14. «хочу такого бота»: Claude передаёт владельцу
    ai.client = ScriptedClient(tool("ask_owner", reason="Хочет такого бота для бизнеса", details="кафе, @client"),
                               say("Владелец свяжется с вами"))
    await feed(msg("хочу такого бота для моего кафе"))
    assert to(OWNER_ID, "Хочет такого бота")

    # 15. сбои ИИ и лимит: вопрос уходит владельцу, клиенту «сейчас уточню у владельца»
    ai.client = ScriptedClient(error=RuntimeError("api down"))
    await feed(msg("есть ли парковка?"))
    assert to(1, "уточню у владельца")[-1] and to(OWNER_ID, "ИИ временно недоступен")
    config.USER_DAILY_LIMIT = 1
    ai.client = ScriptedClient(say("ответ"))
    await feed(msg("первый вопрос", CLIENT2))
    await feed(msg("второй вопрос", CLIENT2))
    assert to(2, "уточню у владельца") and to(OWNER_ID, "Лимит ИИ")
    config.USER_DAILY_LIMIT = 100
    config.ANTHROPIC_API_KEY = ""
    await feed(msg("вопрос без ключа"))
    assert to(OWNER_ID, "нет ключа Claude")
    config.ANTHROPIC_API_KEY = "test-key"

    # 16. прочее: неизвестная команда, голосовое
    await feed(msg("/blah"))
    assert to(1, "Не знаю такой команды")
    await feed(msg(None, voice=Voice(file_id="v", file_unique_id="vu", duration=1)))
    assert to(1, "понимаю текст и фото")

    # 17. рабочий режим клиента: без демо-команд и без переключения компаний
    config.DEMO_MODE = False
    await feed(msg("/auto"))
    assert to(1, "Просто напишите")[-1]
    n = len(SENT)
    await feed(msg("/how"))
    await feed(msg("/owner"))
    assert len(SENT) == n
    await feed(msg("/start"))
    assert "Демо-режим" not in to(1)[-1]["text"] and "Лаванда" in to(1)[-1]["text"]
    config.DEMO_MODE = True

    # 18. язык: смена командой, кабинет/профиль/приветствие на выбранном языке
    await feed(msg("/language"))
    assert to(1)[-1]["markup"] is not None
    await feed(cbq("lang:uk", CLIENT))
    assert (await db.get_user(1))["lang"] == "uk"
    await feed(msg("/cabinet"))
    assert to(1, "Особистий кабінет")
    await feed(msg("/profile"))
    assert to(1, "Ваші дані")
    await feed(msg("/start"))
    assert to(1, "Які послуги є")[-1] and "Жіноча стрижка" in to(1, "Які послуги є")[-1]["text"]
    await feed(msg("/blah"))
    assert to(1, "Не знаю такої команди")
    # Claude переключает язык по просьбе клиента и записывает по английскому названию услуги
    ai.client = ScriptedClient(tool("set_language", lang="en"),
                               tool("create_lead", service="Women's haircut", date=day.isoformat(), time=s3),
                               say("Booked, see you!"))
    await feed(msg("switch to English, book a haircut"))
    assert (await db.get_user(1))["lang"] == "en"
    l3 = await db.get_lead(3)
    assert l3["service"] == "Женская стрижка" and to(OWNER_ID, "Женская стрижка")[-1]
    # владельцу карточка на русском, клиенту подтверждение на английском
    await feed(cbq("ok:3", OWNER))
    ok_msg = to(1, "your booking is confirmed")[-1]
    assert "Women's haircut" in ok_msg["text"] and "Lavender Salon" in ok_msg["text"]
    await feed(cbq("rp:1", OWNER))
    await feed(msg("See you soon", OWNER))
    assert to(1, "Administrator")
    await feed(msg("/cabinet"))
    assert to(1, "Your account") and to(1, "Women's haircut")
    await feed(msg("/owner"))
    assert to(1, "This is how the booking looks")
    # новый клиент с украинским Telegram: без выбора язык по умолчанию украинский
    await feed(msg("/cabinet", CLIENT3))
    assert (await db.get_user(3))["tg_lang"] == "uk" and to(3, "Особистий кабінет")
    print("поток без кнопок работает, отправок:", len(SENT))


asyncio.run(main())
