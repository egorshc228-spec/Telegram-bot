"""ElevenLabs: исходящий звонок агента через SIP-транк (номер Zadarma) и проверка подписи post-call webhook.

Звонок: POST /v1/convai/sip-trunk/outbound-call (agent_id, agent_phone_number_id, to_number).
Данные лида уходят агенту как dynamic variables: {{name}}, {{service}}, {{now}}, {{lead_id}}, {{chat}} (последние
сообщения из Telegram/WhatsApp, если человек уже переписывался с ботом).
Подпись вебхука — как в официальном SDK (webhooks.construct_event): заголовок ElevenLabs-Signature вида
«t=<unix>,v0=<hex>», где hex = HMAC-SHA256(секрет, "<t>.<тело запроса>"); запросы старше 30 минут отклоняются."""
import hashlib
import hmac
import json
import time
from datetime import datetime

import httpx

from . import config, db

transport = None          # в тестах подменяется на httpx.MockTransport
TOLERANCE_SECS = 30 * 60
WD = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


class ElevenLabsError(Exception):
    pass


class BadSignature(Exception):
    pass


def now_text(at: datetime | None = None) -> str:
    at = at or db.now()
    return f"{at:%Y-%m-%d %H:%M}, {WD[at.weekday()]}"


def call_payload(to_number: str, *, lead_id, name: str, service: str, lang: str, at: datetime | None = None,
                 chat: str = "") -> dict:
    client_data: dict = {"dynamic_variables": {
        "name": name or "", "service": service or "не указано", "now": now_text(at), "lead_id": str(lead_id),
        "chat": chat or "переписки не было"}}
    if config.VOICE_LANGUAGE_OVERRIDE and lang in ("ru", "en"):
        client_data["conversation_config_override"] = {"agent": {"language": lang}}
    return {"agent_id": config.ELEVENLABS_AGENT_ID, "agent_phone_number_id": config.ELEVENLABS_PHONE_NUMBER_ID,
            "to_number": to_number, "conversation_initiation_client_data": client_data,
            "telephony_call_config": {"ringing_timeout_secs": config.VOICE_RINGING_SECS}}


async def outbound_call(payload: dict) -> str:
    """Запускает звонок. Возвращает conversation_id."""
    try:
        async with httpx.AsyncClient(timeout=30, transport=transport) as c:
            r = await c.post(f"{config.ELEVENLABS_API_URL}/v1/convai/sip-trunk/outbound-call", json=payload,
                             headers={"xi-api-key": config.ELEVENLABS_API_KEY})
    except httpx.HTTPError as e:
        raise ElevenLabsError(f"ElevenLabs недоступен ({e.__class__.__name__})") from e
    try:
        d = r.json()
    except ValueError:
        d = {}
    if r.status_code >= 400 or not d.get("success") or not d.get("conversation_id"):
        detail = d.get("message") or d.get("detail") or r.text
        raise ElevenLabsError(f"{r.status_code}: {str(detail)[:300]}")
    return str(d["conversation_id"])


def sign(raw: bytes, secret: str, ts: int | None = None) -> str:
    """Подпись в формате ElevenLabs (нужна тестам и для ручной проверки)."""
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={ts},v0={mac}"


def verify(raw: bytes, header: str | None, secret: str, now: float | None = None) -> dict:
    """Проверяет подпись и возвращает событие. Ошибка — BadSignature."""
    if not secret:
        raise BadSignature("не задан ELEVENLABS_WEBHOOK_SECRET")
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    ts, sig = parts.get("t", ""), parts.get("v0", "")
    if not ts.isdigit() or not sig:
        raise BadSignature("нет подписи")
    if int(ts) < (time.time() if now is None else now) - TOLERANCE_SECS:
        raise BadSignature("подпись устарела")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise BadSignature("подпись не совпадает")
    try:
        event = json.loads(raw)
    except ValueError as e:
        raise BadSignature("тело не JSON") from e
    if not isinstance(event, dict):
        raise BadSignature("тело не объект")
    return event


def _value(results: dict, key: str) -> str:
    item = results.get(key)
    val = item.get("value") if isinstance(item, dict) else item
    return "" if val is None else str(val).strip()


def to_result(event: dict) -> dict | None:
    """Событие post-call webhook → итог для бота продаж. None — событие нам не нужно (например, аудио)."""
    kind, d = event.get("type"), event.get("data") or {}
    dyn = ((d.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {})
    base = {"conversation_id": str(d.get("conversation_id") or ""), "lead_id": str(dyn.get("lead_id") or "")}
    if kind == "call_initiation_failure":
        return {**base, "kind": "failure", "failure_reason": str(d.get("failure_reason") or "unknown")}
    if kind != "post_call_transcription":
        return None
    analysis, meta = d.get("analysis") or {}, d.get("metadata") or {}
    dc = analysis.get("data_collection_results") or {}
    turns = [{"role": t.get("role"), "message": t.get("message")}
             for t in d.get("transcript") or [] if isinstance(t, dict) and t.get("message")]
    return {**base, "kind": "transcript",
            **{k: _value(dc, k) for k in ("outcome", "callback_time", "business", "request", "for_manager")},
            "summary": str(analysis.get("transcript_summary") or "")[:600],
            "duration": meta.get("call_duration_secs"), "transcript": turns[-60:]}
