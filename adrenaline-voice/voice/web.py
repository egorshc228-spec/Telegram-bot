"""HTTP сервиса adrenaline-voice.

  POST /call                 — бот продаж просит позвонить лиду (X-Voice-Secret)
  POST /tools/slots          — инструмент агента get_free_slots: свободные окна (X-Tool-Secret)
  POST /tools/book           — инструмент агента book_call: запись на звонок (X-Tool-Secret)
  POST /webhooks/elevenlabs  — post-call webhook ElevenLabs: итог звонка → бот (подпись ElevenLabs-Signature)
  GET  /health               — проверка живости"""
import asyncio
import hmac
import json
import logging
import re
from datetime import datetime, time

from aiohttp import web

from . import bot, config, elevenlabs

log = logging.getLogger("web")
PHONE_RE = re.compile(r"^\+\d{10,15}$")
_tasks: set = set()


def _bg(coro):
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _secret_ok(header: str | None, secret: str) -> bool:
    return bool(secret) and hmac.compare_digest(header or "", secret)


async def _json(request: web.Request) -> dict | None:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def in_contact_hours(at: datetime | None = None) -> bool:
    at = at or datetime.now(config.TZ)
    try:
        a, b = (time.fromisoformat(x.strip()) for x in config.CONTACT_HOURS.split("-"))
    except ValueError:
        a, b = time(9), time(20)
    return a <= at.time() < b


def _err(status: int, error: str):
    return web.json_response({"ok": False, "error": error}, status=status)


# ================================================================ звонок

async def call(request: web.Request):
    if not _secret_ok(request.headers.get("X-Voice-Secret"), config.VOICE_SECRET):
        return _err(403, "forbidden")
    body = await _json(request)
    if body is None:
        return _err(400, "bad_json")
    phone = str(body.get("phone") or "").strip()
    if not PHONE_RE.fullmatch(phone):
        return _err(400, "bad_phone")
    if not str(body.get("lead_id") or "").strip():
        return _err(400, "no_lead_id")
    if not in_contact_hours():                      # гайд: звоним только в 09:00–20:00 (страховка поверх бота)
        return _err(409, "outside_contact_hours")
    if config.missing():
        return _err(503, "not_configured: " + ", ".join(config.missing()))
    payload = elevenlabs.call_payload(phone, lead_id=body["lead_id"], name=str(body.get("name") or ""),
                                      service=str(body.get("service") or ""), lang=str(body.get("lang") or "uk"))
    try:
        conv = await elevenlabs.outbound_call(payload)
    except elevenlabs.ElevenLabsError as e:
        log.warning("звонок лиду %s не запущен: %s", body["lead_id"], e)
        return _err(502, str(e))
    log.info("звонок лиду %s запущен: %s", body["lead_id"], conv)
    return web.json_response({"ok": True, "conversation_id": conv})


# ================================================================ инструменты агента

FALLBACK = ("Сейчас не получается проверить свободное время. Не называй никаких окон и не упоминай технические "
            f"детали. Скажи, что {config.MANAGER_NAME} напишет в Telegram или перезвонит, чтобы согласовать время.")


async def _tool(request: web.Request, path: str, fields: tuple[str, ...]):
    if not _secret_ok(request.headers.get("X-Tool-Secret"), config.TOOL_SECRET):
        return _err(403, "forbidden")
    body = await _json(request) or {}
    try:
        d = await bot.post(path, {k: body.get(k) for k in fields})
        text = str(d.get("text") or FALLBACK)
    except bot.BotError as e:
        log.warning("инструмент %s: %s", path, e)
        text = FALLBACK
    return web.json_response({"result": text})         # 200 всегда: агент должен получить понятную подсказку


async def tool_slots(request: web.Request):
    return await _tool(request, "/api/voice/slots", ("lead_id",))


async def tool_book(request: web.Request):
    return await _tool(request, "/api/voice/book", ("lead_id", "datetime"))


# ================================================================ итог звонка

async def webhook(request: web.Request):
    raw = await request.read()
    try:
        event = elevenlabs.verify(raw, request.headers.get("ElevenLabs-Signature"), config.ELEVENLABS_WEBHOOK_SECRET)
    except elevenlabs.BadSignature as e:
        log.warning("вебхук отклонён: %s", e)
        return _err(401, "bad_signature")
    data = event.get("data") or {}
    if config.ELEVENLABS_AGENT_ID and data.get("agent_id") and data.get("agent_id") != config.ELEVENLABS_AGENT_ID:
        return web.json_response({"ok": True, "skipped": "other_agent"})
    result = elevenlabs.to_result(event)
    if result is None or not result.get("conversation_id"):
        return web.json_response({"ok": True, "skipped": event.get("type")})
    _bg(bot.send_result(result))       # ElevenLabs ждёт быстрый 200; доставка в бот — в фоне, с повторами
    return web.json_response({"ok": True})


async def health(_):
    return web.json_response({"ok": True, "configured": not config.missing()})


def app() -> web.Application:
    a = web.Application(client_max_size=4 * 1024 * 1024)
    a.router.add_post("/call", call)
    a.router.add_post("/tools/slots", tool_slots)
    a.router.add_post("/tools/book", tool_book)
    a.router.add_post("/webhooks/elevenlabs", webhook)
    a.router.add_get("/health", health)
    return a
