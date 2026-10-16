"""События бота продаж в GA4 (Measurement Protocol), необязательно.

Сайт передаёт в заявке client_id GA (cid из cookie _ga), поэтому call_booked попадает к тому же посетителю,
что и клик по рекламе: в GA4 и Google Ads видно, какое объявление привело к записи на звонок.
Без GA4_API_SECRET модуль молчит. Ошибки сети не мешают боту."""
import asyncio
import logging

import httpx

from . import config

log = logging.getLogger("analytics")
URL = "https://www.google-analytics.com/mp/collect"
_tasks: set = set()


def enabled() -> bool:
    return bool(config.GA4_MEASUREMENT_ID and config.GA4_API_SECRET)


async def _send(client_id: str, name: str, params: dict):
    body = {"client_id": client_id, "events": [{"name": name, "params": {**params, "engagement_time_msec": 1}}]}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(URL, params={"measurement_id": config.GA4_MEASUREMENT_ID,
                                      "api_secret": config.GA4_API_SECRET}, json=body)
    except Exception:
        log.warning("GA4: событие %s не отправлено", name, exc_info=True)


def track(lead: dict, name: str, **params):
    if not enabled():
        return
    client_id = lead.get("cid") or f"{lead['id']}.1"
    params = {"lead_source": lead.get("source") or "", **{k: v for k, v in params.items() if v not in (None, "")}}
    task = asyncio.create_task(_send(client_id, name, params))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
