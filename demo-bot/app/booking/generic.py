"""Универсальный адаптер для любой CRM/системы записи с REST API (в том числе CleverBox, когда у вас
будет документация и ключ от их поддержки). Эндпоинты, заголовки и поля описываются в booking.json,
код менять не нужно.

Шаблоны в строках: {date} {time} {service_id} {staff_id} {name} {phone} {comment}
"""
import logging
import re
from datetime import date

import httpx

from .base import Booking, BookingError, Provider, Slot, normalize_phone, norm_time

log = logging.getLogger("generic-crm")


def _fill(obj, values: dict):
    if isinstance(obj, str):
        return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), obj)
    if isinstance(obj, dict):
        return {k: _fill(v, values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill(v, values) for v in obj]
    return obj


def _dig(obj, path: str):
    for part in [p for p in (path or "").split(".") if p]:
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


class GenericProvider(Provider):
    def __init__(self, cfg: dict):
        self.name = cfg.get("title", "CRM")
        self.base = cfg["base_url"].rstrip("/")
        self.headers = cfg.get("headers", {})
        self.slots_cfg = cfg["slots"]
        self.booking_cfg = cfg.get("booking")
        self.services = {k.lower(): str(v) for k, v in (cfg.get("services") or {}).items()}
        self.staff_id = str(cfg.get("staff_id", ""))
        self.country_code = str(cfg.get("country_code", "38"))
        self.transport = None

    def _client(self):
        return httpx.AsyncClient(timeout=10, transport=self.transport, headers=self.headers)

    async def _call(self, spec: dict, values: dict):
        url = self.base + _fill(spec["path"], values)
        try:
            async with self._client() as c:
                r = await c.request(spec.get("method", "GET"), url,
                                    params=_fill(spec.get("query"), values) or None,
                                    json=_fill(spec.get("body"), values) if spec.get("body") is not None else None)
        except httpx.HTTPError as e:
            log.error("CRM запрос %s: %s", url, e)
            raise BookingError("Не удалось связаться с системой записи, попробуйте позже.") from e
        if r.status_code >= 400:
            log.error("CRM %s -> %s: %s", url, r.status_code, r.text[:300])
            raise BookingError("Система записи вернула ошибку. Попробуйте другое время или позже.")
        try:
            return r.json()
        except ValueError:
            return {}

    def _values(self, service, d: date, **extra):
        sid = ""
        if service is not None:
            sid = self.services.get(service.lower())
            if sid is None:
                raise BookingError("Эта услуга пока не подключена к расписанию, уточните у администратора.")
        return {"date": d.isoformat(), "service_id": sid or "", "staff_id": self.staff_id, **extra}

    async def slots(self, service, d: date) -> list:
        data = await self._call(self.slots_cfg, self._values(service, d))
        rows = _dig(data, self.slots_cfg.get("result_path", "")) if self.slots_cfg.get("result_path") else data
        field = self.slots_cfg.get("time_field", "")
        out = []
        for row in rows or []:
            raw = row.get(field) if (field and isinstance(row, dict)) else row
            t = norm_time(raw)
            if t:
                out.append(Slot(t))
        return out

    async def create(self, service, d: date, time: str, name: str, phone: str, comment: str):
        if not self.booking_cfg:
            return None                                   # только чтение расписания
        if time not in [s.time for s in await self.slots(service, d)]:
            raise BookingError("Это время только что заняли. Выберите другое.")
        values = self._values(service, d, time=time, name=name, comment=comment or "Запись из Telegram-бота",
                              phone=normalize_phone(phone, self.country_code))
        data = await self._call(self.booking_cfg, values)
        rec = _dig(data, self.booking_cfg.get("id_path", "")) if self.booking_cfg.get("id_path") else ""
        return Booking(str(rec or ""), self.name)
