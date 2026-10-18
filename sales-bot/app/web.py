"""HTTP: приём заявок с сайта (/api/lead), вебхук WhatsApp (/wa/webhook), проверка живости (/health)."""
import asyncio
import hmac
import json
import logging
import re

from aiohttp import web

from . import config, core, db, wa
from .texts import guess_lang

log = logging.getLogger("web")
TOKEN_RE = re.compile(r"#([a-z0-9]{6,12})\b", re.I)
_tasks: set = set()


def _bg(coro):
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


# ================================================================ заявка с сайта

async def api_lead(request: web.Request):
    if not config.LEAD_API_SECRET or not hmac.compare_digest(request.headers.get("X-Lead-Secret", ""),
                                                             config.LEAD_API_SECRET):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"ok": False}, status=400)
    if not isinstance(body, dict) or body.get("company"):            # honeypot формы
        return web.json_response({"ok": True})
    if not str(body.get("name", "")).strip() or not str(body.get("contact", "")).strip():
        return web.json_response({"ok": False, "error": "missing_fields"}, status=400)
    lead = await core.site_lead(body)
    return web.json_response({"ok": True, **core.links(lead)})


# ================================================================ WhatsApp

async def wa_verify(request: web.Request):
    q = request.query
    if q.get("hub.mode") == "subscribe" and config.WA_VERIFY_TOKEN and q.get("hub.verify_token") == config.WA_VERIFY_TOKEN:
        return web.Response(text=q.get("hub.challenge", ""))
    return web.Response(status=403)


async def wa_hook(request: web.Request):
    raw = await request.read()
    if not wa.valid_signature(raw, request.headers.get("X-Hub-Signature-256")):
        return web.Response(status=403)
    try:
        msgs, statuses = wa.parse(json.loads(raw))
    except ValueError:
        return web.Response(status=400)
    _bg(process_wa(msgs, statuses))                 # Meta ждёт быстрый 200, обработка — в фоне
    return web.Response(text="ok")


async def process_wa(msgs: list[dict], statuses: list[dict]):
    for m in msgs:
        try:
            await wa_message(m)
        except Exception:
            log.exception("входящее WhatsApp от %s", m.get("wa_id"))
    for s in statuses:
        try:
            await wa_status(s)
        except Exception:
            log.exception("статус WhatsApp")


async def wa_message(item: dict):
    wa_id, text = item["wa_id"], (item.get("text") or "").strip()
    tok = TOKEN_RE.search(text)
    lead = await db.lead_by_token(tok[1]) if tok else None
    by_token = bool(lead)
    lead = lead or await db.lead_by_wa(wa_id) or await db.lead_by_phone("+" + wa_id)
    if not lead:
        lead = await db.create_lead(source="wa", lang=guess_lang(text), name=item.get("name") or "",
                                    contact="+" + wa_id, phone="+" + wa_id, wa_id=wa_id, channel="wa",
                                    stage="new")
        await core.post_card(lead)
    elif lead.get("channel") != "wa" or lead.get("wa_id") != wa_id:
        lead = await core.link_channel(lead, "wa", wa_id=wa_id)
    if by_token:                                    # человек нажал кнопку WhatsApp на сайте: приветствие + окна
        await db.log(lead["id"], "in", "wa", text)
        return await core.greet(await db.get_lead(lead["id"]))
    if item.get("choice"):
        await db.log(lead["id"], "in", "wa", item.get("text") or item["choice"])
        return await core.on_choice(await db.get_lead(lead["id"]), item["choice"])
    if item.get("contact_phone"):
        text = core.normalize_phone(item["contact_phone"]) or item["contact_phone"]
    await core.incoming(lead, text or "[вкладення без тексту]")


async def wa_status(s: dict):
    if s.get("status") != "failed" or not s.get("wa_id"):
        return
    lead = await db.lead_by_wa(s["wa_id"])
    if lead and lead.get("stage") == "wa_sent":
        from . import scheduler
        codes = ", ".join(str(e.get("code")) for e in s.get("errors", []))
        await scheduler.need_call(lead, f"WhatsApp не доставлен (код {codes or '—'}): скорее всего, у номера нет WhatsApp")


# ================================================================ голосовой ИИ (ElevenLabs)

def _tool_ok(request: web.Request) -> bool:
    return bool(config.VOICE_TOOL_SECRET) and hmac.compare_digest(request.headers.get("X-Tool-Secret", ""),
                                                                  config.VOICE_TOOL_SECRET)


async def _tool_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


async def _tool_lead(body: dict) -> dict | None:
    lid = str(body.get("lead_id") or "").strip()
    return await db.get_lead(int(lid)) if lid.isdigit() else None


NO_LEAD = "Не удалось найти заявку. Не называй окна и не упоминай технические детали: скажи, что Даниил перезвонит."


async def voice_slots(request: web.Request):
    """Инструмент агента get_free_slots: свободные окна текстом. Ответ всегда 200 — агенту нужна понятная подсказка."""
    from . import voice
    if not _tool_ok(request):
        return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"result": await voice.slots_text()})


async def voice_book(request: web.Request):
    """Инструмент агента book_call: {lead_id, datetime} → запись на звонок по телефону."""
    from . import voice
    if not _tool_ok(request):
        return web.json_response({"error": "forbidden"}, status=403)
    body = await _tool_body(request)
    lead = await _tool_lead(body)
    if not lead:
        return web.json_response({"result": NO_LEAD})
    ok, text = await voice.book(lead, body.get("datetime"))
    return web.json_response({"result": text, "ok": ok})


async def voice_webhook(request: web.Request):
    """Post-call webhook ElevenLabs: подпись ElevenLabs-Signature, итог звонка → группа «Заявки»."""
    from . import elevenlabs, voice
    raw = await request.read()
    try:
        event = elevenlabs.verify(raw, request.headers.get("ElevenLabs-Signature"), config.ELEVENLABS_WEBHOOK_SECRET)
    except elevenlabs.BadSignature as e:
        log.warning("вебхук ElevenLabs отклонён: %s", e)
        return web.json_response({"ok": False, "error": "bad_signature"}, status=401)
    agent_id = (event.get("data") or {}).get("agent_id")
    if config.ELEVENLABS_AGENT_ID and agent_id and agent_id != config.ELEVENLABS_AGENT_ID:
        return web.json_response({"ok": True, "skipped": "other_agent"})
    result = elevenlabs.to_result(event)
    if result is None or not result.get("conversation_id"):
        return web.json_response({"ok": True, "skipped": event.get("type")})
    _bg(voice.on_result(result))                    # ElevenLabs ждёт быстрый 200, обработка — в фоне
    return web.json_response({"ok": True})


# ================================================================ приложение

async def health(_):
    return web.json_response({"ok": True})


def app() -> web.Application:
    a = web.Application(client_max_size=4 * 1024 * 1024)     # итог звонка с текстом разговора бывает большим
    a.router.add_post("/api/lead", api_lead)
    a.router.add_get("/wa/webhook", wa_verify)
    a.router.add_post("/wa/webhook", wa_hook)
    a.router.add_get("/health", health)
    a.router.add_post("/voice/tools/slots", voice_slots)
    a.router.add_post("/voice/tools/book", voice_book)
    a.router.add_post("/voice/webhook", voice_webhook)
    return a
