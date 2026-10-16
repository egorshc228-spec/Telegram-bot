"""Google Calendar Даниила через сервисный аккаунт (необязательно).

Зачем: бот не предлагает время, когда у Даниила уже что-то стоит в календаре (в том числе звонки из демо-бота,
если он тоже пишет в этот календарь), и сам ставит событие звонка с контактами лида.
Настройка (README): сервисный аккаунт в Google Cloud → JSON-ключ в GOOGLE_SERVICE_ACCOUNT_JSON →
Даниил делится своим календарём с email сервисного аккаунта с правом «Вносить изменения в мероприятия».
Ссылку Meet сервисный аккаунт в личном календаре создать не может, поэтому в событие идёт MEET_URL."""
import base64
import json
import logging
import time
from datetime import datetime, timedelta

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from . import config

log = logging.getLogger("gcal")
API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar"
_token: dict = {"value": "", "exp": 0.0}
_busy_cache: dict = {"at": 0.0, "key": "", "value": []}
transport = None          # в тестах подменяется на httpx.MockTransport


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _assertion(sa: dict) -> str:
    now = int(time.time())
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"iss": sa["client_email"], "scope": SCOPE,
                            "aud": sa.get("token_uri", "https://oauth2.googleapis.com/token"),
                            "iat": now, "exp": now + 3600}).encode())
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{_b64(sig)}"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10, transport=transport)


async def _access_token() -> str:
    if _token["value"] and _token["exp"] - 60 > time.time():
        return _token["value"]
    sa = config.GOOGLE_SERVICE_ACCOUNT
    async with _client() as c:
        r = await c.post(sa.get("token_uri", "https://oauth2.googleapis.com/token"),
                         data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                               "assertion": _assertion(sa)})
        r.raise_for_status()
        d = r.json()
    _token.update(value=d["access_token"], exp=time.time() + int(d.get("expires_in", 3600)))
    return _token["value"]


async def busy(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Занятые интервалы календаря. Кэш на минуту. При ошибке — пустой список (бот не падает)."""
    if not config.gcal_enabled():
        return []
    key = f"{start.date()}-{end.date()}"
    if _busy_cache["key"] == key and time.time() - _busy_cache["at"] < 60:
        return _busy_cache["value"]
    try:
        tok = await _access_token()
        async with _client() as c:
            r = await c.post(f"{API}/freeBusy", headers={"Authorization": f"Bearer {tok}"},
                             json={"timeMin": start.isoformat(), "timeMax": end.isoformat(),
                                   "timeZone": config.TIMEZONE, "items": [{"id": config.GOOGLE_CALENDAR_ID}]})
            r.raise_for_status()
            cal = r.json()["calendars"].get(config.GOOGLE_CALENDAR_ID, {})
        if cal.get("errors"):
            log.warning("Календарь недоступен: %s (поделитесь календарём с сервисным аккаунтом)", cal["errors"])
            return []
        out = [(datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
                datetime.fromisoformat(b["end"].replace("Z", "+00:00"))) for b in cal.get("busy", [])]
    except Exception:
        log.warning("Google Calendar: не удалось получить занятость", exc_info=True)
        return []
    _busy_cache.update(at=time.time(), key=key, value=out)
    return out


def forget_busy():
    _busy_cache.update(at=0.0, key="")


async def add_event(at: datetime, summary: str, description: str) -> str:
    """Создаёт событие звонка. Возвращает id события или '' при ошибке."""
    if not config.gcal_enabled():
        return ""
    end = at + timedelta(minutes=config.CALL_MIN)
    body = {"summary": summary, "description": description,
            "start": {"dateTime": at.isoformat(), "timeZone": config.TIMEZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": config.TIMEZONE},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]}}
    if config.MEET_URL:
        body["location"] = config.MEET_URL
    try:
        tok = await _access_token()
        async with _client() as c:
            r = await c.post(f"{API}/calendars/{config.GOOGLE_CALENDAR_ID}/events",
                             headers={"Authorization": f"Bearer {tok}"}, json=body)
            r.raise_for_status()
            forget_busy()
            return r.json().get("id", "")
    except Exception:
        log.warning("Google Calendar: событие не создано", exc_info=True)
        return ""


async def delete_event(event_id: str):
    if not (config.gcal_enabled() and event_id):
        return
    try:
        tok = await _access_token()
        async with _client() as c:
            await c.delete(f"{API}/calendars/{config.GOOGLE_CALENDAR_ID}/events/{event_id}",
                           headers={"Authorization": f"Bearer {tok}"})
        forget_busy()
    except Exception:
        log.warning("Google Calendar: событие %s не удалено", event_id, exc_info=True)
