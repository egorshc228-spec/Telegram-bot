"""Голосовой ИИ в боте: «пора звонить» → звонок агента ElevenLabs → инструменты окон и записи → подписанный вебхук
итога → группа, повтор, сторож, «не звоните». ElevenLabs и Telegram подменены. Запуск: python -m tests.test_voice"""
import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timedelta

os.environ.update({
    "DATA_DIR": tempfile.mkdtemp(), "SALES_CHAT_ID": "-100500", "SALES_STAFF_IDS": "777", "LEAD_API_SECRET": "sek",
    "ANTHROPIC_API_KEY": "k", "SALES_DAYS": "1,2,3,4,5,6,7", "SALES_HOURS": "10:00-19:00", "CONTACT_HOURS": "00:00-23:59",
    "BOT_USERNAME": "adr_sales_bot", "GA4_API_SECRET": "", "SILENCE_CALL_MIN": "30",
    "VOICE_CALLS": "1", "ELEVENLABS_API_KEY": "xi-test", "ELEVENLABS_AGENT_ID": "agent_1",
    "ELEVENLABS_PHONE_NUMBER_ID": "ph_1", "ELEVENLABS_WEBHOOK_SECRET": "whsec", "VOICE_TOOL_SECRET": "tsek",
})
for k in ("WA_TOKEN", "WA_PHONE_NUMBER_ID", "GOOGLE_CALENDAR_ID", "GOOGLE_SERVICE_ACCOUNT_JSON"):
    os.environ.pop(k, None)

import httpx  # noqa: E402
from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from app import config, core, db, elevenlabs, scheduler, slots, voice, web  # noqa: E402
from app.tg import router  # noqa: E402

GROUP = -100500
SENT, CALLS = [], []
EL_DOWN = [False]
_mid, _uid = [100], [0]


class FakeTG(BaseSession):
    async def close(self): pass

    async def make_request(self, bot, method, timeout=None):
        SENT.append(dict(m=type(method).__name__, chat=getattr(method, "chat_id", None),
                         text=getattr(method, "text", None), markup=getattr(method, "reply_markup", None)))
        _mid[0] += 1
        return Message(message_id=_mid[0], date=datetime.now(),
                       chat=Chat(id=getattr(method, "chat_id", None) or 1, type="private"), text="x")

    async def stream_content(self, *a, **k):
        yield b""


def el_handler(request: httpx.Request):
    assert str(request.url) == "https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call"
    assert request.headers["xi-api-key"] == "xi-test"
    if EL_DOWN[0]:
        return httpx.Response(422, json={"detail": "agent_phone_number_id not found"})
    CALLS.append(json.loads(request.content))
    return httpx.Response(200, json={"success": True, "conversation_id": f"conv_{len(CALLS)}", "sip_call_id": "s"})


def group(contains=None):
    return [s for s in SENT if s["chat"] == GROUP and s["m"] == "SendMessage"
            and (contains is None or contains in (s["text"] or ""))]


def btns(s):
    return [] if s["markup"] is None else [b.callback_data for row in s["markup"].inline_keyboard for b in row]


def upd(**kw):
    _uid[0] += 1
    return Update(update_id=_uid[0], **kw)


def transcription(conv, outcome="", lead_id="", agent="agent_1", **dc):
    results = {k: {"data_collection_id": k, "value": v, "rationale": "."} for k, v in {"outcome": outcome, **dc}.items()}
    return {"type": "post_call_transcription", "event_timestamp": int(time.time()), "data": {
        "agent_id": agent, "conversation_id": conv, "status": "done",
        "transcript": [{"role": "agent", "message": "Добрий день!"}, {"role": "user", "message": "Здравствуйте <b>"},
                       {"role": "agent", "message": None, "tool_calls": [{"tool_name": "get_free_slots"}]}],
        "metadata": {"call_duration_secs": 95},
        "analysis": {"transcript_summary": "Короткий разговор", "data_collection_results": results},
        "conversation_initiation_client_data": {"dynamic_variables": {"lead_id": str(lead_id)}}}}


def failure(conv, reason="no-answer"):
    return {"type": "call_initiation_failure", "event_timestamp": int(time.time()), "data": {
        "agent_id": "agent_1", "conversation_id": conv, "failure_reason": reason,
        "metadata": {"type": "sip", "body": {"sip_status_code": 480}}}}


async def main():
    await db.init()
    elevenlabs.transport = httpx.MockTransport(el_handler)
    bot = Bot("1:AAA", session=FakeTG(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    core.bot, core.bot_username = bot, "adr_sales_bot"
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    http = TestClient(TestServer(web.app()))
    await http.start_server()
    T = {"X-Tool-Secret": "tsek"}
    tomorrow = db.now().date() + timedelta(days=1)

    async def new_lead(name, contact, **kw):
        r = await http.post("/api/lead", headers={"X-Lead-Secret": "sek"}, json={"name": name, "contact": contact, **kw})
        return await db.lead_by_token((await r.json())["token"])

    async def hook(event, secret="whsec", ts=None):
        raw = json.dumps(event, ensure_ascii=False).encode()
        r = await http.post("/voice/webhook", data=raw, headers={
            "ElevenLabs-Signature": elevenlabs.sign(raw, secret, ts), "Content-Type": "application/json"})
        await asyncio.gather(*list(web._tasks))
        return r.status, await r.json()

    async def tool(path, body, headers=T):
        r = await http.post(path, json=body, headers=headers)
        return r.status, await r.json()

    async def called(name, contact, **kw):
        lead = await new_lead(name, contact, **kw)
        await scheduler.run_once(db.now() + timedelta(minutes=4))
        return await db.get_lead(lead["id"])

    # 1. нет WhatsApp и лид не открыл чат → вместо карточки «Позвонить вручную» звонит агент ElevenLabs
    A = await called("Олена", "067 111 22 33", service="Google Ads", page="/ru/google-ads")
    b = CALLS[-1]
    dyn = b["conversation_initiation_client_data"]["dynamic_variables"]
    assert b["agent_id"] == "agent_1" and b["agent_phone_number_id"] == "ph_1" and b["to_number"] == "+380671112233"
    assert dyn["name"] == "Олена" and dyn["service"] == "Google Ads" and dyn["lead_id"] == str(A["id"])
    assert dyn["now"][:4].isdigit() and dyn["chat"] == "переписки не было"
    assert b["telephony_call_config"] == {"ringing_timeout_secs": 30}
    assert "conversation_config_override" not in b["conversation_initiation_client_data"]
    assert A["voice_conv"] == "conv_1" and A["voice_tries"] == 1 and A["voice_next_at"] and A["stage"] == "need_call"
    assert group("Запущен AI-звонок") and not group("Позвонить вручную")

    # 2. инструменты агента: секрет обязателен; окна на 3 дня; запись через ядро бота, как в чате
    assert (await tool("/voice/tools/slots", {}, headers={}))[0] == 403
    assert (await tool("/voice/tools/book", {}, headers={"X-Tool-Secret": "nope"}))[0] == 403
    st, d = await tool("/voice/tools/slots", {"lead_id": A["id"]})
    assert st == 200 and tomorrow.isoformat() in d["result"] and "book_call" in d["result"]
    assert d["result"].count("\n") <= 5
    assert "формат" in (await tool("/voice/tools/book", {"lead_id": A["id"], "datetime": "завтра"}))[1]["result"]
    d = (await tool("/voice/tools/book", {"lead_id": A["id"], "datetime": f"{tomorrow}T03:00"}))[1]
    assert not d["ok"] and "недоступно" in d["result"] and tomorrow.isoformat() in d["result"]
    assert "Даниил перезвонит" in (await tool("/voice/tools/book", {"lead_id": 9999, "datetime": "x"}))[1]["result"]
    d = (await tool("/voice/tools/book", {"lead_id": str(A["id"]), "datetime": f"{tomorrow}T12:00"}))[1]
    assert d["ok"] and "12:00" in d["result"], d
    call = await db.active_call(A["id"])
    assert call and call["format"] == "phone" and call["phone"] == "+380671112233"
    assert (await db.get_lead(A["id"]))["stage"] == "booked" and group("Записался на звонок")
    assert slots.parse_stamp(f"{tomorrow:%Y%m%d}1200") not in (await slots.free()).get(tomorrow, [])
    assert "уже записан" in (await tool("/voice/tools/book", {"lead_id": A["id"], "datetime": f"{tomorrow}T13:00"}))[1]["result"]

    # 3. вебхук итога: подпись обязательна; «записался» → отчёт с разговором; повтор доставки не дублирует
    ev = transcription("conv_1", "booked", A["id"], business="салон, Одесса", request="больше записей")
    assert (await http.post("/voice/webhook", data=json.dumps(ev).encode())).status == 401
    assert (await hook(ev, secret="wrong"))[0] == 401
    assert (await hook(ev, ts=int(time.time()) - 31 * 60))[0] == 401
    assert (await hook(ev)) == (200, {"ok": True})
    rep = group("Итог AI-звонка")[-1]["text"]
    assert "записался" in rep and "1:35" in rep and "Здравствуйте &lt;b&gt;" in rep and "conv_1" in rep, rep
    A = await db.get_lead(A["id"])
    assert A["stage"] == "booked" and A["voice_conv"] is None and A["voice_next_at"] is None and A["biz"] == "салон, Одесса"
    n = len(group("Итог AI-звонка"))
    await hook(ev)
    assert len(group("Итог AI-звонка")) == n
    assert (await hook(transcription("conv_x", "booked", agent="agent_other")))[1]["skipped"] == "other_agent"
    assert (await hook({"type": "post_call_audio", "data": {"agent_id": "agent_1", "conversation_id": "c",
                                                            "full_audio": "AAAA"}}))[1]["skipped"] == "post_call_audio"

    # 4. не дозвонились: повтор через VOICE_RETRY_MIN, второй раз не ответил → карточка «позвонить вручную»
    B = await called("Тихий", "0502223344")
    assert B["voice_conv"] == "conv_2"
    await hook(failure("conv_2"))
    B = await db.get_lead(B["id"])
    assert B["voice_conv"] is None and B["voice_next_at"] and group("Повтор около")
    assert "не взял трубку" in group("Итог AI-звонка")[-1]["text"]
    await scheduler.run_once(db.now() + timedelta(minutes=10))
    assert len(CALLS) == 2                                          # повтор ещё не наступил
    await scheduler.run_once(db.now() + timedelta(minutes=config.VOICE_RETRY_MIN + 1))
    B = await db.get_lead(B["id"])
    assert len(CALLS) == 3 and B["voice_conv"] == "conv_3" and B["voice_tries"] == 2 and group("Повторный AI-звонок")
    await hook(transcription("conv_3", "no_answer", B["id"]))
    B = await db.get_lead(B["id"])
    card = group("Позвонить вручную")[-1]
    assert B["stage"] == "need_call" and B["voice_conv"] is None and B["voice_next_at"] is None
    assert "Тихий" in card["text"] and "попыток: 2" in card["text"] and f"g:take:{B['id']}" in btns(card)
    await scheduler.run_once(db.now() + timedelta(hours=3))
    assert len(CALLS) == 3                                          # третьего звонка нет

    # 5. итог не пришёл (сбой вебхука) → сторож: «не дозвонились» и повтор; поздний итог только заметкой
    C = await called("Сторож", "0631112233")
    await scheduler.run_once(db.now() + timedelta(minutes=4 + config.VOICE_RESULT_TIMEOUT_MIN + 1))
    C = await db.get_lead(C["id"])
    assert C["voice_conv"] is None and C["voice_next_at"] and group("итог звонка не пришёл")
    await hook(transcription("conv_4", "callback", C["id"]))
    assert (await db.get_lead(C["id"]))["stage"] == "need_call" and not group("Итог AI-звонка")[-1]["markup"]

    # 6. «не звоните» → opted_out: никаких звонков, автосообщений и записи
    D = await called("Нет", "0671234567")
    await hook(transcription(D["voice_conv"], "do_not_call", D["id"]))
    D = await db.get_lead(D["id"])
    assert D["stage"] == "opted_out" and D["next_at"] is None and D["silence_done"] == 1 and not voice.can_call(D)
    assert not (await tool("/voice/tools/book", {"lead_id": D["id"], "datetime": f"{tomorrow}T15:00"}))[1]["ok"]

    # 7. «перезвоните вечером» → карточка с кнопками; «записал», но записи нет → нужен Даниил; непонятный итог → тоже
    E = await called("Вечером", "0681234567")
    await hook(transcription(E["voice_conv"], "callback", E["id"], callback_time="после 18:00"))
    rep = group("Итог AI-звонка")[-1]
    assert (await db.get_lead(E["id"]))["stage"] == "need_call" and "после 18:00" in rep["text"]
    assert f"g:take:{E['id']}" in btns(rep)
    F = await called("Странный", "0691234567")
    await hook(transcription(F["voice_conv"], "booked", F["id"]))
    assert "записи нет" in group("Итог AI-звонка")[-1]["text"]
    F2 = await called("Непонятный", "0691234500")
    await hook(transcription(F2["voice_conv"], "???", F2["id"]))
    assert "нужен Даниил" in group("Итог AI-звонка")[-1]["text"]

    # 8. ElevenLabs отказал → сразу карточка «позвонить вручную» с причиной, лид не теряется
    EL_DOWN[0] = True
    G = await called("Сбой", "0991112233")
    assert G["stage"] == "need_call" and "not found" in group("AI-звонок не запустился")[-1]["text"]
    assert "Сбой" in group("Позвонить вручную")[-1]["text"]
    EL_DOWN[0] = False

    # 9. в заявке только @ник — звонить некуда: карточка
    n_calls = len(CALLS)
    H = await called("Ник", "@nick_only")
    assert len(CALLS) == n_calls and H["stage"] == "need_call"

    # 10. ночью агент не звонит (повтор переносится на утро)
    config.CONTACT_HOURS = "09:00-20:00"
    night = datetime.combine(tomorrow, datetime.min.time(), db.TZ).replace(hour=23)
    I = await new_lead("Ночной", "0661112233")
    assert not await voice.call(await db.get_lead(I["id"]), "тест", at=night)
    await db.update_lead(I["id"], voice_next_at=db.iso(night - timedelta(minutes=1)))
    await voice.due(await db.get_lead(I["id"]), night)
    assert datetime.fromisoformat((await db.get_lead(I["id"]))["voice_next_at"]).hour == 9 and len(CALLS) == n_calls
    config.CONTACT_HOURS = "00:00-23:59"

    # 11. лид сам ответил в чате, пока ждал повтора → повтор отменяется
    J = await called("Сам", "0661112244")
    await hook(failure(J["voice_conv"], "busy"))
    await db.update_lead(J["id"], last_in=db.iso(db.now() + timedelta(minutes=10)))
    n_calls = len(CALLS)
    await scheduler.run_once(db.now() + timedelta(minutes=config.VOICE_RETRY_MIN + 5))
    J = await db.get_lead(J["id"])
    assert len(CALLS) == n_calls and J["voice_next_at"] is None

    # 12. «Беру сам» во время звонка: итог приходит заметкой, стадию не меняет
    K = await called("Взяли", "0661112255")
    DAN = User(id=777, is_bot=False, first_name="Dan", username="conversion_wizard")
    m = Message(message_id=1, date=datetime.now(), chat=Chat(id=GROUP, type="supergroup"),
                from_user=User(id=1, is_bot=True, first_name="b"), text="m")
    await dp.feed_update(bot, upd(callback_query=CallbackQuery(id="1", from_user=DAN, chat_instance="c", message=m,
                                                               data=f"g:take:{K['id']}")))
    st, d = await hook(transcription(K["voice_conv"], "callback", K["id"]))
    assert (await db.get_lead(K["id"]))["stage"] == "taken"

    # 13. флаг выключен → как раньше: карточка без звонка
    config.VOICE_CALLS = False
    n_calls = len(CALLS)
    L = await called("Без голоса", "0671119999")
    assert len(CALLS) == n_calls and L["stage"] == "need_call" and "Без голоса" in group("Позвонить вручную")[-1]["text"]
    config.VOICE_CALLS = True

    await http.close()
    print("голосовой ИИ в боте: все проверки пройдены · звонков", len(CALLS), "· сообщений в группу", len(group()))


if __name__ == "__main__":
    asyncio.run(main())
