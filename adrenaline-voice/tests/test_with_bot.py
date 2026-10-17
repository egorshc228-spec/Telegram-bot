"""Сквозной тест (нужна папка бота продаж рядом: ../sales-bot, или SALES_BOT_DIR=путь).
Запуск из папки adrenaline-voice: python -m tests.test_with_bot

Сквозной тест: бот продаж и adrenaline-voice работают вместе по настоящему HTTP, подменён только ElevenLabs.
Сценарий: заявка → нет ответа в мессенджерах → бот просит сервис позвонить → «ElevenLabs» звонит, агент
вызывает get_free_slots и book_call через сервис → запись в боте → подписанный вебхук → итог в группе."""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # папка adrenaline-voice
# в общем репозитории бот лежит рядом: ../sales-bot (в шаблоне — ../sales-template); или SALES_BOT_DIR=путь
BOT_DIR = os.path.abspath(os.getenv("SALES_BOT_DIR") or next(
    (os.path.join(HERE, "..", d) for d in ("sales-bot", "sales-template") if os.path.isdir(os.path.join(HERE, "..", d))),
    os.path.join(HERE, "..", "sales-bot")))
if not os.path.isdir(os.path.join(BOT_DIR, "app")):
    sys.exit(f"Нужна папка бота продаж с доработкой для голоса: {BOT_DIR} (или укажите SALES_BOT_DIR)")
sys.path[:0] = [BOT_DIR, HERE]
os.chdir(BOT_DIR)
os.environ.update({
    "DATA_DIR": tempfile.mkdtemp(), "CLIENT_FILE": "clients/adrenaline.json", "SALES_CHAT_ID": "-100500",
    "LEAD_API_SECRET": "sek", "ANTHROPIC_API_KEY": "k", "SALES_DAYS": "1,2,3,4,5,6,7", "SALES_HOURS": "10:00-19:00",
    "CONTACT_HOURS": "00:00-23:59", "BOT_USERNAME": "adr_sales_bot", "VOICE_CALLS": "1", "VOICE_SECRET": "shared",
    "VOICE_SERVICE_URL": "http://placeholder",
    "ELEVENLABS_API_KEY": "xi", "ELEVENLABS_AGENT_ID": "agent_1", "ELEVENLABS_PHONE_NUMBER_ID": "ph_1",
    "ELEVENLABS_WEBHOOK_SECRET": "whsec", "SALES_BOT_URL": "http://placeholder", "TOOL_SECRET": "tool",
})

import httpx  # noqa: E402
from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.types import Chat, Message  # noqa: E402
from aiohttp.test_utils import TestServer  # noqa: E402

from app import config as bot_config, core, db, scheduler, web as bot_web  # noqa: E402
from voice import config as v_config, elevenlabs, web as v_web  # noqa: E402

SENT, CONVS = [], []


class FakeTG(BaseSession):
    async def close(self): pass

    async def make_request(self, bot, method, timeout=None):
        SENT.append(getattr(method, "text", None) or "")
        return Message(message_id=len(SENT), date=datetime.now(), chat=Chat(id=1, type="private"), text="x")

    async def stream_content(self, *a, **k):
        yield b""


async def main():
    await db.init()
    core.bot = Bot("1:AAA", session=FakeTG(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot_srv, v_srv = TestServer(bot_web.app()), TestServer(v_web.app())
    await bot_srv.start_server()
    await v_srv.start_server()
    bot_config.VOICE_SERVICE_URL = str(v_srv.make_url("")).rstrip("/")
    v_config.SALES_BOT_URL = str(bot_srv.make_url("")).rstrip("/")
    tasks = []

    async def conversation(payload: dict):
        """«ElevenLabs»: агент говорит с лидом, вызывает инструменты сервиса, потом шлёт подписанный вебхук."""
        dyn = payload["conversation_initiation_client_data"]["dynamic_variables"]
        conv = f"conv_{len(CONVS) - 1}"
        async with httpx.AsyncClient(base_url=bot_config.VOICE_SERVICE_URL, headers={"X-Tool-Secret": "tool"}) as c:
            slots_text = (await c.post("/tools/slots", json={"lead_id": dyn["lead_id"]})).json()["result"]
            day, times = slots_text.split("\n")[1].split(" (")[0], slots_text.split("\n")[1].split(": ")[1]
            pick = f"{day}T{times.split(', ')[1]}"
            booked = (await c.post("/tools/book", json={"lead_id": dyn["lead_id"], "datetime": pick})).json()["result"]
            assert booked.startswith("Записано"), booked
            event = {"type": "post_call_transcription", "event_timestamp": 1, "data": {
                "agent_id": "agent_1", "conversation_id": conv,
                "transcript": [{"role": "agent", "message": f"Добрий день, {dyn['name']}!"},
                               {"role": "user", "message": "Давайте завтра"},
                               {"role": "agent", "message": booked}],
                "metadata": {"call_duration_secs": 61},
                "analysis": {"transcript_summary": "Записался",
                             "data_collection_results": {"outcome": {"value": "booked"},
                                                         "request": {"value": "больше заявок"}}},
                "conversation_initiation_client_data": {"dynamic_variables": dyn}}}
            raw = json.dumps(event, ensure_ascii=False).encode()
            r = await c.post("/webhooks/elevenlabs", content=raw,
                             headers={"ElevenLabs-Signature": elevenlabs.sign(raw, "whsec")})
            assert r.status_code == 200, r.text

    def fake_elevenlabs(request: httpx.Request):
        payload = json.loads(request.content)
        CONVS.append(payload)
        tasks.append(asyncio.get_running_loop().create_task(conversation(payload)))
        return httpx.Response(200, json={"success": True, "conversation_id": f"conv_{len(CONVS) - 1}"})

    elevenlabs.transport = httpx.MockTransport(fake_elevenlabs)

    async with httpx.AsyncClient(base_url=str(bot_srv.make_url("")).rstrip("/")) as c:
        r = await c.post("/api/lead", headers={"X-Lead-Secret": "sek"},
                         json={"name": "Олена", "contact": "067 111 22 33", "service": "AI-адміністратор"})
        lead = await db.lead_by_token(r.json()["token"])

    await scheduler.run_once(db.now() + timedelta(minutes=4))     # нет WhatsApp → голосовой звонок
    for _ in range(50):                                            # ждём разговор и доставку итога в бот
        await asyncio.gather(*tasks)
        await asyncio.gather(*list(v_web._tasks))
        if (await db.get_lead(lead["id"]))["voice_conv"] is None:
            break
        await asyncio.sleep(0.05)

    lead = await db.get_lead(lead["id"])
    call = await db.active_call(lead["id"])
    p = CONVS[0]
    assert p["to_number"] == "+380671112233" and p["agent_phone_number_id"] == "ph_1"
    assert p["conversation_initiation_client_data"]["dynamic_variables"]["service"] == "AI-адміністратор"
    assert lead["stage"] == "booked" and lead["voice_conv"] is None and lead["request"] == "больше заявок"
    assert call and call["format"] == "phone" and call["phone"] == "+380671112233"
    joined = "\n".join(SENT)
    for s in ("Звонит голосовой AI", "Записался на звонок", "Итог голосового звонка", "записался на звонок",
              "Давайте завтра", "1:01"):
        assert s in joined, s
    assert "Позвонить вручную" not in joined and "потом звонит голосовой AI" in joined
    await bot_srv.close()
    await v_srv.close()
    print("сквозной тест бот ↔ adrenaline-voice: пройден · звонок → окна → запись → итог в группе")


if __name__ == "__main__":
    asyncio.run(main())
