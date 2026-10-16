"""Универсальный адаптер: любая CRM или своя таблица, которая по HTTP отдаёт JSON со свободным временем.

Настройки (см. .env.example):
  CRM_SLOTS_URL   адрес с подстановками {date} (YYYY-MM-DD), {service} (название), {service_id}
  CRM_HEADERS     JSON с заголовками авторизации
  CRM_SLOTS_PATH  путь к списку в ответе, через точку ("data", "result.slots", "" = корень)
  CRM_TIME_KEY    ключ времени, если слоты приходят объектами {"time": "10:30"}
  CRM_SERVICE_MAP JSON {"услуга из прайса": "id в CRM"}
Элементы списка могут быть строками "10:30" или объектами. Время вида "2026-10-12T10:30:00" тоже понимается.
"""
import json
import re
from datetime import date
from urllib.parse import quote

import httpx

from .base import SlotProvider, SlotsUnavailable, norm, parse_map

_TIME = re.compile(r"(\d{1,2}):(\d{2})")


def _to_hhmm(v) -> str | None:
    m = _TIME.search(str(v))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


class GenericProvider(SlotProvider):
    name = "generic"
    is_real = True

    def __init__(self, url: str, headers: str | dict = "", path: str = "data", time_key: str = "time",
                 service_map: str | dict = "", client: httpx.AsyncClient | None = None):
        if not url:
            raise ValueError("для generic нужен CRM_SLOTS_URL")
        self.url, self.path, self.time_key = url, path.strip(), time_key
        self.headers = json.loads(headers) if isinstance(headers, str) and headers.strip() else (headers or {})
        self.service_map = parse_map(service_map) if isinstance(service_map, str) else {norm(k): v for k, v in service_map.items()}
        self._client = client

    async def free_slots(self, niche_key: str, service: str, d: date) -> list:
        sid = self.service_map.get(norm(service), "")
        url = self.url.format(date=d.isoformat(), service=quote(service), service_id=quote(str(sid)))
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=8.0)
            r = await self._client.get(url, headers=self.headers)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SlotsUnavailable(f"CRM: {type(e).__name__}") from e
        for key in [k for k in self.path.split(".") if k]:
            data = data.get(key) if isinstance(data, dict) else None
        if not isinstance(data, list):
            raise SlotsUnavailable("CRM: в ответе нет списка слотов по пути " + (self.path or "(корень)"))
        out = set()
        for item in data:
            raw = item.get(self.time_key) if isinstance(item, dict) else item
            t = _to_hhmm(raw)
            if t:
                out.add(t)
        return sorted(out)
