"""Человек не отвечает боту SILENCE_CALL_MIN минут → звонок: голосовой ИИ, карточка «Позвонить» или просьба оставить
номер. Telegram и ElevenLabs подменены. Запуск: python -m tests.test_silence"""
import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta

os.environ.update({
    "DATA_DIR": tempfile.mkdtemp(), "SALES_CHAT_ID": "-100500", "SALES_STAFF_IDS": "777", "LEAD_API_SECRET": "sek",
    "ANTHROPIC_API_KEY": "k", "SALES_DAYS": "1,2,3,4,5,6,7", "CONTACT_HOURS": "09:00-20:00", "GA4_API_SECRET": "",
    "BOT_USERNAME": "adr_sales_bot", "SILENCE_CALL_MIN": "30",
})
import httpx  # noqa: E402
from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import Chat, Contact, Message, Update, User  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from app import agent, config, core, db, elevenlabs, scheduler, web  # noqa: E402
from app.tg import router  # noqa: E402
from tests.fakes import ScriptedClient, say  # noqa: E402

GROUP = -100500
SENT, CALLS = [], []
_mid = [100]


class FakeTG(BaseSession):
    async def close(self): pass

    async def make_request(self, bot, method, timeout=None):
        SENT.append(dict(m=type(method).__name__, chat=getattr(method, "chat_id", None),
                         text=getattr(method, "text", None), markup=getattr(method, "reply_markup", None)))
        _mid[0] += 1
        return Message(message_id=_mid[0], date=datetime.now(), chat=Chat(id=1, type="private"), text="x")

    async def stream_content(self, *a, **k):
        yield b""


def to(chat, contains=None):
    return [s for s in SENT if s["chat"] == chat and s["m"] == "SendMessage" and (contains or "") in (s["text"] or "")]


_u = [0]


def msg(user, text=None, **kw):
    _u[0] += 1
    return Update(update_id=_u[0], message=Message(message_id=_u[0], date=datetime.now(),
                                                   chat=Chat(id=user.id, type="private"), from_user=user, text=text,
                                                   **kw))


def day_at(h: int, m: int = 0) -> datetime:
    """Рабочее время сегодня (тесты не зависят от того, когда их запускают)."""
    return db.now().replace(hour=h, minute=m, second=0, microsecond=0)


async def make_lead(http, feed, user, contact, page="/ai-admin"):
    r = await http.post("/api/lead", json={"name": user.first_name, "contact": contact, "service": "AI-адміністратор",
                                           "page": page},
                        headers={"X-Lead-Secret": "sek"})
    token = (await r.json())["token"]
    await feed(msg(user, f"/start l_{token}"))                      # открыл бота, бот поздоровался
    return await db.lead_by_token(token)


async def set_times(lead_id, out: datetime, inn: datetime | None = None):
    await db.update_lead(lead_id, last_out=db.iso(out), last_in=db.iso(inn) if inn else None)


async def main():
    await db.init()
    bot = Bot("1:AAA", session=FakeTG(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    core.bot, core.bot_username = bot, "adr_sales_bot"
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    feed = lambda u: dp.feed_update(bot, u)  # noqa: E731
    http = TestClient(TestServer(web.app()))
    await http.start_server()
    noon = day_at(12)

    # 1. есть номер, голосового ИИ нет: молчит 29 мин — ничего; 30 мин — карточка «☎️ Позвонить», один раз
    A = User(id=601, is_bot=False, first_name="Олена", language_code="uk")
    la = await make_lead(http, feed, A, "+380671112233")
    assert la["stage"] == "talking" and la["last_out"] and not la["last_in"]
    await set_times(la["id"], noon)
    assert (await scheduler.run_once(noon + timedelta(minutes=29)))["silence"] == 0
    assert (await scheduler.run_once(noon + timedelta(minutes=31)))["silence"] == 1
    card = to(GROUP, "Позвонить")[-1]
    assert "не отвечает в чате 30 мин" in card["text"] and "+380671112233" in card["text"]
    assert [b.callback_data for row in card["markup"].inline_keyboard for b in row] == [f"g:take:{la['id']}",
                                                                                         f"g:lost:{la['id']}"]
    la = await db.get_lead(la["id"])
    assert la["silence_done"] == 1 and la["stage"] == "talking"     # стадия та же: может ответить в чате
    assert (await scheduler.run_once(noon + timedelta(hours=2)))["silence"] == 0

    # 2. человек ответил (последним писал он) — не звоним
    B = User(id=602, is_bot=False, first_name="Іван", language_code="uk")
    lb = await make_lead(http, feed, B, "+380671112244")
    await set_times(lb["id"], noon, noon + timedelta(minutes=5))
    assert (await scheduler.run_once(noon + timedelta(hours=1)))["silence"] == 0

    # 3. ночью не звоним: бот написал в 19:50, в 20:20 тишина, утром в 9:00 — карточка
    C = User(id=603, is_bot=False, first_name="Марко", language_code="uk")
    lc = await make_lead(http, feed, C, "0501112255")
    await set_times(lc["id"], day_at(19, 50))
    await db.update_lead(lc["id"], next_at=None)    # без «напоминания через 20 ч»: иначе тест зависит от часа запуска
    assert (await scheduler.run_once(day_at(20, 30)))["silence"] == 0
    assert (await db.get_lead(lc["id"]))["silence_done"] == 0
    assert (await scheduler.run_once(day_at(9, 1) + timedelta(days=1)))["silence"] == 1
    assert to(GROUP, "+380501112255")

    # 4. уже записан на звонок — карточки нет
    D = User(id=604, is_bot=False, first_name="Ліна", language_code="uk")
    ld = await make_lead(http, feed, D, "+380671112266")
    slot = db.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=2)
    await db.add_call(ld["id"], slot.replace(hour=12), "meet")
    await set_times(ld["id"], noon)
    n = len(to(GROUP, "Позвонить"))
    await scheduler.run_once(noon + timedelta(minutes=40))
    assert len(to(GROUP, "Позвонить")) == n and (await db.get_lead(ld["id"]))["silence_done"] == 1

    # 5. номера нет (только @ник): бот один раз просит номер, в группе «номера нет — написать @ник»
    E = User(id=605, is_bot=False, first_name="Оксана", username="oksana_x", language_code="uk")
    le = await make_lead(http, feed, E, "@oksana_x")
    await set_times(le["id"], noon)
    await scheduler.run_once(noon + timedelta(minutes=35))
    assert "Напишіть, будь ласка, номер телефону" in to(E.id)[-1]["text"]
    g = to(GROUP, "номера нет")[-1]["text"]
    assert "бот попросил номер" in g and "@oksana_x" in g
    assert (await db.get_lead(le["id"]))["pending"] == "callphone"
    #    ответила номером → номер сохранён, «скоро наберём», в группе «☎️ Позвонить: оставил номер»
    await feed(msg(E, "067 999 88 77"))
    assert "Скоро вам наберемо" in to(E.id)[-1]["text"]
    le = await db.get_lead(le["id"])
    assert le["phone"] == "+380679998877" and not le["pending"]
    assert "оставил номер, просит набрать" in to(GROUP, "Позвонить")[-1]["text"]

    # 6. номера нет, человек ответил не номером → обычный ответ ИИ, просьба снята
    F = User(id=606, is_bot=False, first_name="Петро", username="petro_x", language_code="uk")
    lf = await make_lead(http, feed, F, "@petro_x")
    await set_times(lf["id"], noon)
    await scheduler.run_once(noon + timedelta(minutes=35))
    agent.client = ScriptedClient(say("AI-адміністратор: запуск $800, далі $160/міс."))
    await feed(msg(F, "А скільки коштує?"))
    assert "$800" in to(F.id)[-1]["text"] and not (await db.get_lead(lf["id"]))["pending"]
    #    номер контактом из Telegram тоже подходит
    G = User(id=607, is_bot=False, first_name="Яна", username="yana_x", language_code="ru")
    lg = await make_lead(http, feed, G, "@yana_x", page="/ru/ai-admin")
    await set_times(lg["id"], noon)
    await scheduler.run_once(noon + timedelta(minutes=35))
    assert "Напишите, пожалуйста, номер телефона" in to(G.id)[-1]["text"]
    await feed(msg(G, contact=Contact(phone_number="380631234567", first_name="Яна", user_id=G.id)))
    assert "Скоро вам наберём" in to(G.id)[-1]["text"] and (await db.get_lead(lg["id"]))["phone"] == "+380631234567"

    # 7. голосовой ИИ подключён: звонит агент ElevenLabs с данными лида и перепиской; при ошибке — карточка
    def el_ok(request: httpx.Request):
        CALLS.append(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "conversation_id": f"conv_{len(CALLS)}"})

    elevenlabs.transport = httpx.MockTransport(el_ok)
    config.VOICE_CALLS = True
    config.ELEVENLABS_API_KEY, config.ELEVENLABS_AGENT_ID, config.ELEVENLABS_PHONE_NUMBER_ID = "xi", "agent_1", "ph_1"
    config.ELEVENLABS_WEBHOOK_SECRET, config.VOICE_TOOL_SECRET = "whsec", "tsek"
    H = User(id=608, is_bot=False, first_name="Тарас", language_code="uk")
    lh = await make_lead(http, feed, H, "+380671112277")
    await set_times(lh["id"], noon)
    await scheduler.run_once(noon + timedelta(minutes=31))
    body = CALLS[-1]
    dyn = body["conversation_initiation_client_data"]["dynamic_variables"]
    assert body["to_number"] == "+380671112277" and body["agent_id"] == "agent_1" and dyn["name"] == "Тарас"
    assert dyn["service"] == "AI-адміністратор" and dyn["lead_id"] == str(lh["id"]) and "Бот: Вітаю" in dyn["chat"]
    assert to(GROUP, "Запущен AI-звонок") and "30 мин" in to(GROUP, "Запущен AI-звонок")[-1]["text"]
    assert (await db.get_lead(lh["id"]))["voice_conv"] == f"conv_{len(CALLS)}"

    elevenlabs.transport = httpx.MockTransport(lambda r: httpx.Response(500, text="down"))
    I = User(id=609, is_bot=False, first_name="Ірина", language_code="uk")
    li = await make_lead(http, feed, I, "+380671112288")
    await set_times(li["id"], noon)
    await scheduler.run_once(noon + timedelta(minutes=31))
    assert "+380671112288" in to(GROUP, "Позвонить")[-1]["text"] and to(GROUP, "AI-звонок не запустился")
    config.VOICE_CALLS = False

    # 8. SILENCE_CALL_MIN=0 выключает; лид, которого взял человек, не трогаем
    config.SILENCE_CALL_MIN = 0
    J = User(id=610, is_bot=False, first_name="Олег", language_code="uk")
    lj = await make_lead(http, feed, J, "+380671112299")
    await set_times(lj["id"], noon)
    assert (await scheduler.run_once(noon + timedelta(minutes=40)))["silence"] == 0
    config.SILENCE_CALL_MIN = 30
    await db.update_lead(lj["id"], stage="taken")
    assert (await scheduler.run_once(noon + timedelta(minutes=40)))["silence"] == 0
    #    старше суток — не трогаем (например, старые лиды после обновления бота)
    await db.update_lead(lj["id"], stage="talking")
    assert (await scheduler.run_once(noon + timedelta(hours=25)))["silence"] == 0

    await http.close()
    print("молчит после сообщения бота → звонок: все проверки пройдены")


if __name__ == "__main__":
    asyncio.run(main())
