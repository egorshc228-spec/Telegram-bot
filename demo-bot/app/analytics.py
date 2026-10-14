"""События воронки бота в GA4 через Measurement Protocol (необязательно).

Если сайт передал в ссылке client_id GA (t.me/CladchatBot?start=ai_123-456), события бота попадают к тому же
посетителю, что и клик на сайте: видно, какая страница и какое объявление привели к записи на звонок.
Без GA4_MEASUREMENT_ID и GA4_API_SECRET модуль ничего не делает. Ошибки сети не мешают боту."""
import asyncio
import logging

import httpx

from . import config

log = logging.getLogger("analytics")
URL = "https://www.google-analytics.com/mp/collect"
_tasks: set = set()


def enabled() -> bool:
    return bool(config.GA4_MEASUREMENT_ID and config.GA4_API_SECRET)


async def _send(client_id: str, user_id: int, name: str, params: dict):
    body = {"client_id": client_id, "user_id": f"tg{user_id}",
            "events": [{"name": name, "params": {**params, "engagement_time_msec": 1}}]}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(URL, params={"measurement_id": config.GA4_MEASUREMENT_ID,
                                      "api_secret": config.GA4_API_SECRET}, json=body)
    except Exception:
        log.warning("GA4: событие %s не отправлено", name, exc_info=True)


def track(prospect: dict | None, user_id: int, name: str, **params):
    """Отправляет событие в фоне. client_id — из ссылки с сайта, иначе стабильный id по Telegram."""
    if not enabled():
        return
    p = prospect or {}
    client_id = p.get("cid") or f"{user_id}.1"
    params = {"source": p.get("source") or "direct", **{k: v for k, v in params.items() if v is not None}}
    task = asyncio.create_task(_send(client_id, user_id, name, params))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
