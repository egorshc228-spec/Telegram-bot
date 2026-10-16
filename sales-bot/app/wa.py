"""WhatsApp Cloud API (Meta): отправка шаблона, текста, кнопок и списков; разбор входящего вебхука.

Правила WhatsApp, которые важны для логики:
- первым писать человеку можно только утверждённым шаблоном (WA_TEMPLATE), это платное сообщение;
- после ответа человека 24 часа открыто «окно обслуживания»: обычный текст, кнопки (до 3) и списки (до 10 строк);
- после 24 часов тишины снова только шаблон (напоминание о звонке — WA_REMINDER_TEMPLATE, если задан)."""
import hashlib
import hmac
import logging
import re
from datetime import datetime, timedelta

import httpx

from . import config, db

log = logging.getLogger("wa")
transport = None           # в тестах подменяется на httpx.MockTransport


class WAError(Exception):
    pass


def phone_to_wa(phone: str) -> str:
    return "".join(ch for ch in phone or "" if ch.isdigit())


def _url() -> str:
    return f"https://graph.facebook.com/{config.WA_API_VERSION}/{config.WA_PHONE_NUMBER_ID}/messages"


async def _post(payload: dict) -> str:
    payload = {"messaging_product": "whatsapp", **payload}
    async with httpx.AsyncClient(timeout=15, transport=transport) as c:
        r = await c.post(_url(), json=payload, headers={"Authorization": f"Bearer {config.WA_TOKEN}"})
    if r.status_code >= 400:
        raise WAError(f"{r.status_code}: {r.text[:300]}")
    try:
        return r.json()["messages"][0]["id"]
    except (KeyError, IndexError, ValueError):
        return ""


def window_open(lead: dict) -> bool:
    """Открыто ли 24-часовое окно: человек писал нам в WhatsApp меньше 24 часов назад."""
    if not lead.get("last_in") or lead.get("channel") != "wa":
        return False
    return db.now() - datetime.fromisoformat(lead["last_in"]) < timedelta(hours=23, minutes=50)


def to_wa_markup(html_text: str) -> str:
    """HTML Telegram → разметка WhatsApp: <b>x</b> → *x*, остальные теги убираем."""
    s = re.sub(r"</?b>", "*", html_text or "")
    s = re.sub(r"<[^>]+>", "", s)
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


async def send_template(to: str, name: str, lang: str, params: list[str]) -> str:
    comp = [{"type": "body", "parameters": [{"type": "text", "text": p[:60] or "—"} for p in params]}] if params else []
    return await _post({"to": to, "type": "template",
                        "template": {"name": name, "language": {"code": lang}, "components": comp}})


async def send_text(to: str, text: str) -> str:
    return await _post({"to": to, "type": "text", "text": {"body": to_wa_markup(text)[:4000],
                                                             "preview_url": False}})


async def send_options(to: str, text: str, options: list[tuple[str, str, str]], button: str) -> str:
    """options: [(id, заголовок, описание)]. До 3 коротких — кнопки, иначе список (до 10 строк)."""
    body = to_wa_markup(text)[:1024]
    if len(options) <= 3 and all(len(o[1]) <= 20 for o in options):
        btns = [{"type": "reply", "reply": {"id": i, "title": title}} for i, title, _ in options]
        return await _post({"to": to, "type": "interactive",
                            "interactive": {"type": "button", "body": {"text": body}, "action": {"buttons": btns}}})
    rows = [{"id": i, "title": title[:24], **({"description": d[:72]} if d else {})} for i, title, d in options[:10]]
    return await _post({"to": to, "type": "interactive",
                        "interactive": {"type": "list", "body": {"text": body},
                                        "action": {"button": button[:20], "sections": [{"title": button[:24],
                                                                                        "rows": rows}]}}})


def valid_signature(raw: bytes, header: str | None) -> bool:
    if not config.WA_APP_SECRET:
        return False
    expected = "sha256=" + hmac.new(config.WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")


def parse(payload: dict) -> tuple[list[dict], list[dict]]:
    """Вебхук → (входящие сообщения, статусы доставки). Сообщение: {wa_id, name, text, choice}."""
    msgs, statuses = [], []
    for e in payload.get("entry", []):
        for ch in e.get("changes", []):
            v = ch.get("value", {})
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name", "") for c in v.get("contacts", [])}
            for m in v.get("messages", []):
                item = {"wa_id": m.get("from", ""), "name": names.get(m.get("from"), ""), "text": "", "choice": "",
                        "contact_phone": ""}
                typ = m.get("type")
                if typ == "text":
                    item["text"] = m.get("text", {}).get("body", "")
                elif typ == "interactive":
                    it = m.get("interactive", {})
                    rep = it.get("list_reply") or it.get("button_reply") or {}
                    item["choice"], item["text"] = rep.get("id", ""), rep.get("title", "")
                elif typ == "button":                                  # кнопка быстрого ответа в шаблоне
                    item["text"] = m.get("button", {}).get("text", "")
                    item["choice"] = m.get("button", {}).get("payload", "") if ":" in m.get("button", {}).get(
                        "payload", "") else ""
                elif typ == "contacts":
                    phones = (m.get("contacts") or [{}])[0].get("phones") or [{}]
                    item["contact_phone"] = phones[0].get("phone", "")
                else:
                    item["text"] = f"[{typ}]"
                msgs.append(item)
            for s in v.get("statuses", []):
                statuses.append({"wa_id": s.get("recipient_id", ""), "status": s.get("status", ""),
                                 "errors": s.get("errors", [])})
    return msgs, statuses
