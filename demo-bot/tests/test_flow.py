"""Прогон обработчиков через настоящий Dispatcher aiogram с подменой сети. python -m tests.test_flow"""
import asyncio, os, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp()
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import Update, User, Chat, Message, CallbackQuery
from app import db
from app.bot import router

SENT = []

class Fake(BaseSession):
    async def close(self): pass
    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        SENT.append((type(method).__name__, getattr(method, "text", None) or getattr(method, "caption", None)))
        name = type(method).__name__
        if name in ("SendMessage", "EditMessageText"):
            return Message(message_id=1, date=datetime.now(), chat=Chat(id=1, type="private"), text="x")
        if name == "SendDocument":
            return Message(message_id=2, date=datetime.now(), chat=Chat(id=1, type="private"))
        return True
    async def stream_content(self, *a, **k): yield b""

U = User(id=1, is_bot=False, first_name="T", username="tester")
C = Chat(id=1, type="private")
uid = 0
def msg(text):
    global uid; uid += 1
    return Update(update_id=uid, message=Message(message_id=uid, date=datetime.now(), chat=C, from_user=U, text=text))
def cbq(data):
    global uid; uid += 1
    m = Message(message_id=uid, date=datetime.now(), chat=C, from_user=User(id=99, is_bot=True, first_name="b"), text="m")
    return Update(update_id=uid, callback_query=CallbackQuery(id=str(uid), from_user=U, chat_instance="c", message=m, data=data))

async def main():
    await db.init_db()
    bot = Bot("1:AAA", session=Fake(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage()); dp.include_router(router)
    from app import ai
    d = ai.upcoming_days()
    from app.niches import free_slots
    j = next(i for i, x in enumerate(d) if free_slots("salon", x))
    t = free_slots("salon", d[j])[0].replace(":", "")
    flow = [msg("/start"), cbq("n:salon"), cbq("p:salon"), cbq("h:salon"), cbq("f:salon"), cbq("fq:salon:0"),
            cbq("b:salon"), cbq("bs:salon:0"), cbq(f"bd:salon:0:{j}"), cbq(f"bt:salon:0:{j}:{t}"),
            msg("Анна"), msg("0501234567"), cbq("ow:salon"), cbq("xl:salon"), cbq("ok:1"), cbq("call:1"),
            cbq("how"), cbq("want"), msg("У меня кафе, @tester"), cbq("ai:salon"), msg("привет"), msg("/start")]
    for u in flow:
        await dp.feed_update(bot, u)
    for n in ["salon", "auto", "shop", "dental"]:
        await dp.feed_update(bot, cbq(f"n:{n}")); await dp.feed_update(bot, cbq(f"b:{n}"))
    names = [s[0] for s in SENT]
    assert "SendDocument" in names, names
    l = await db.get_lead(1)
    assert l and l["status"] == "ok" and l["name"] == "Анна", l
    texts = " ".join(str(s[1]) for s in SENT)
    assert "Заявка №1 принята" in texts and "Подтверждена" in texts
    print("поток кнопок работает, отправок:", len(SENT))

asyncio.run(main())
