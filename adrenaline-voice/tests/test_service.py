"""Сервис adrenaline-voice: звонок, инструменты агента, вебхук итога. ElevenLabs и бот продаж подменены.
Запуск: python -m tests.test_service"""
import asyncio
import json
import os
import time

os.environ.update({
    "ELEVENLABS_API_KEY": "xi-test", "ELEVENLABS_AGENT_ID": "agent_1", "ELEVENLABS_PHONE_NUMBER_ID": "phnum_1",
    "ELEVENLABS_WEBHOOK_SECRET": "whsec", "SALES_BOT_URL": "https://bot.test", "VOICE_SECRET": "vsek",
    "TOOL_SECRET": "tsek", "CONTACT_HOURS": "00:00-23:59", "LANGUAGE_OVERRIDE": "0",
})

import httpx  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from voice import bot, config, elevenlabs, web  # noqa: E402

EL, BOT = [], []
EL_FAIL, BOT_FAIL = [False], [0]


def el_handler(request: httpx.Request):
    EL.append({"url": str(request.url), "key": request.headers.get("xi-api-key"), "body": json.loads(request.content)})
    if EL_FAIL[0]:
        return httpx.Response(422, json={"detail": "agent_phone_number_id not found"})
    return httpx.Response(200, json={"success": True, "message": "ok", "conversation_id": f"conv_{len(EL)}",
                                     "sip_call_id": "sip"})


def bot_handler(request: httpx.Request):
    body = json.loads(request.content)
    BOT.append({"path": request.url.path, "secret": request.headers.get("X-Voice-Secret"), "body": body})
    if BOT_FAIL[0] > 0:
        BOT_FAIL[0] -= 1
        return httpx.Response(503, text="restarting")
    if request.url.path == "/api/voice/slots":
        return httpx.Response(200, json={"ok": True, "text": "2026-10-19 (пн): 10:00, 12:00"})
    if request.url.path == "/api/voice/book":
        return httpx.Response(200, json={"ok": True, "text": f"Записано: {body['datetime']}"})
    return httpx.Response(200, json={"ok": True})


def transcription(conv="conv_x", agent="agent_1", outcome="booked"):
    return {"type": "post_call_transcription", "event_timestamp": int(time.time()), "data": {
        "agent_id": agent, "conversation_id": conv, "status": "done",
        "transcript": [{"role": "agent", "message": "Добрий день!", "time_in_call_secs": 0},
                       {"role": "user", "message": "Так, зручно"},
                       {"role": "agent", "message": None, "tool_calls": [{"tool_name": "get_free_slots"}]}],
        "metadata": {"call_duration_secs": 74, "termination_reason": "end_call tool"},
        "analysis": {"transcript_summary": "Записался на понедельник", "call_successful": "success",
                     "data_collection_results": {
                         "outcome": {"data_collection_id": "outcome", "value": outcome, "rationale": "..."},
                         "business": {"data_collection_id": "business", "value": "СТО, Киев", "rationale": "..."},
                         "callback_time": {"data_collection_id": "callback_time", "value": None, "rationale": "..."}}},
        "conversation_initiation_client_data": {"dynamic_variables": {"lead_id": "42", "name": "Олена"}}}}


async def main():
    elevenlabs.transport = httpx.MockTransport(el_handler)
    bot.transport = httpx.MockTransport(bot_handler)
    bot.RETRY_DELAYS = (0.01, 0.01, 0.01)
    http = TestClient(TestServer(web.app()))
    await http.start_server()
    VS, TS = {"X-Voice-Secret": "vsek"}, {"X-Tool-Secret": "tsek"}

    async def hook(event, secret="whsec", ts=None):
        raw = json.dumps(event, ensure_ascii=False).encode()
        r = await http.post("/webhooks/elevenlabs", data=raw,
                            headers={"ElevenLabs-Signature": elevenlabs.sign(raw, secret, ts),
                                     "Content-Type": "application/json"})
        await asyncio.gather(*list(web._tasks))
        return r.status, await r.json()

    # 1. живость и настройки
    r = await http.get("/health")
    assert (await r.json()) == {"ok": True, "configured": True}

    # 2. звонок: секрет, проверка номера, тело запроса в ElevenLabs
    lead = {"lead_id": 42, "name": "Олена", "phone": "+380671112233", "service": "Google Ads", "lang": "uk"}
    assert (await http.post("/call", json=lead)).status == 403
    assert (await http.post("/call", json=lead, headers={"X-Voice-Secret": "nope"})).status == 403
    assert (await http.post("/call", json={**lead, "phone": "067 111"}, headers=VS)).status == 400
    assert (await http.post("/call", json={**lead, "lead_id": ""}, headers=VS)).status == 400
    assert (await http.post("/call", data=b"{oops", headers=VS)).status == 400
    r = await http.post("/call", json=lead, headers=VS)
    assert r.status == 200 and (await r.json()) == {"ok": True, "conversation_id": "conv_1"}
    req = EL[-1]
    assert req["url"] == "https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call" and req["key"] == "xi-test"
    b = req["body"]
    assert b["agent_id"] == "agent_1" and b["agent_phone_number_id"] == "phnum_1" and b["to_number"] == "+380671112233"
    dyn = b["conversation_initiation_client_data"]["dynamic_variables"]
    assert dyn["name"] == "Олена" and dyn["service"] == "Google Ads" and dyn["lead_id"] == "42"
    assert dyn["now"][:4].isdigit() and "," in dyn["now"]                      # «2026-10-19 10:05, понедельник»
    assert "conversation_config_override" not in b["conversation_initiation_client_data"]
    assert b["telephony_call_config"] == {"ringing_timeout_secs": 30}
    # пустая услуга → «не указано»; русский лид с LANGUAGE_OVERRIDE=1 → агент начинает по-русски
    config.LANGUAGE_OVERRIDE = True
    await http.post("/call", json={**lead, "service": "", "lang": "ru"}, headers=VS)
    cd = EL[-1]["body"]["conversation_initiation_client_data"]
    assert cd["dynamic_variables"]["service"] == "не указано"
    assert cd["conversation_config_override"] == {"agent": {"language": "ru"}}
    config.LANGUAGE_OVERRIDE = False
    # ElevenLabs отказал → 502 с причиной (бот покажет её в группе и поставит обычную карточку)
    EL_FAIL[0] = True
    r = await http.post("/call", json=lead, headers=VS)
    assert r.status == 502 and "not found" in (await r.json())["error"]
    EL_FAIL[0] = False
    # ночью не звоним, даже если бот попросит
    config.CONTACT_HOURS = "03:00-03:00"
    n = len(EL)
    r = await http.post("/call", json=lead, headers=VS)
    assert r.status == 409 and len(EL) == n
    config.CONTACT_HOURS = "00:00-23:59"
    # не заданы ключи → 503, звонок не уходит
    config.ELEVENLABS_API_KEY = ""
    r = await http.post("/call", json=lead, headers=VS)
    assert r.status == 503 and "ELEVENLABS_API_KEY" in (await r.json())["error"] and len(EL) == n
    assert (await (await http.get("/health")).json())["configured"] is False
    config.ELEVENLABS_API_KEY = "xi-test"

    # 3. инструменты агента: секрет инструмента, проксирование в бот, понятная подсказка при сбое
    assert (await http.post("/tools/slots", json={"lead_id": "42"})).status == 403
    r = await http.post("/tools/slots", json={"lead_id": "42"}, headers=TS)
    assert (await r.json()) == {"result": "2026-10-19 (пн): 10:00, 12:00"}
    assert BOT[-1] == {"path": "/api/voice/slots", "secret": "vsek", "body": {"lead_id": "42"}}
    r = await http.post("/tools/book", json={"lead_id": "42", "datetime": "2026-10-19T12:00", "extra": 1}, headers=TS)
    assert (await r.json())["result"] == "Записано: 2026-10-19T12:00"
    assert BOT[-1]["body"] == {"lead_id": "42", "datetime": "2026-10-19T12:00"}
    BOT_FAIL[0] = 1
    r = await http.post("/tools/slots", json={"lead_id": "42"}, headers=TS)
    assert r.status == 200 and "не упоминай технические" in (await r.json())["result"]

    # 4. вебхук: подпись обязательна, устаревшая подпись отклоняется
    ev = transcription("conv_9")
    raw = json.dumps(ev).encode()
    r = await http.post("/webhooks/elevenlabs", data=raw)
    assert r.status == 401
    assert (await hook(ev, secret="wrong"))[0] == 401
    assert (await hook(ev, ts=int(time.time()) - 31 * 60))[0] == 401
    n = len(BOT)
    st, d = await hook(ev)
    assert st == 200 and d == {"ok": True}
    res = BOT[-1]
    assert len(BOT) == n + 1 and res["path"] == "/api/voice/result" and res["secret"] == "vsek"
    rb = res["body"]
    assert rb["kind"] == "transcript" and rb["conversation_id"] == "conv_9" and rb["lead_id"] == "42"
    assert rb["outcome"] == "booked" and rb["business"] == "СТО, Киев" and rb["callback_time"] == ""
    assert rb["duration"] == 74 and rb["summary"] == "Записался на понедельник"
    assert rb["transcript"] == [{"role": "agent", "message": "Добрий день!"}, {"role": "user", "message": "Так, зручно"}]
    # чужой агент, аудио — пропускаем; «не дозвонились» — итог failure
    assert (await hook(transcription("conv_10", agent="agent_other")))[1]["skipped"] == "other_agent"
    assert (await hook({"type": "post_call_audio", "data": {"agent_id": "agent_1", "conversation_id": "c",
                                                            "full_audio": "AAAA"}}))[1]["skipped"] == "post_call_audio"
    st, d = await hook({"type": "call_initiation_failure", "event_timestamp": 1, "data": {
        "agent_id": "agent_1", "conversation_id": "conv_11", "failure_reason": "busy",
        "metadata": {"type": "sip", "body": {"sip_status_code": 486}}}})
    assert BOT[-1]["body"] == {"conversation_id": "conv_11", "lead_id": "", "kind": "failure", "failure_reason": "busy"}
    # бот перезапускается → итог доставляется повторно
    BOT_FAIL[0] = 2
    n = len(BOT)
    await hook(transcription("conv_12", outcome="callback"))
    assert len(BOT) == n + 3 and BOT[-1]["body"]["outcome"] == "callback"

    await http.close()
    print("adrenaline-voice: все проверки пройдены · запросов в ElevenLabs", len(EL), "· в бот", len(BOT))


if __name__ == "__main__":
    asyncio.run(main())
