"""Altegio (бывш. YCLIENTS): свободные слоты через публичный API онлайн-записи.

Документация: https://developer.alteg.io/api (раздел Online Booking).
Используется метод  GET /book_times/{location_id}/{team_member_id}/{date}
с заголовком  Authorization: Bearer <partner_token>.
Partner token выдаётся в личном кабинете разработчика Altegio (developer.alteg.io).
"""
from datetime import date

import httpx

from .base import SlotProvider, SlotsUnavailable, norm, parse_map

BASE_URL = "https://api.alteg.io/api/v1"


class AltegioProvider(SlotProvider):
    name = "altegio"
    is_real = True

    def __init__(self, partner_token: str, location_id: str, staff_id: int = 0,
                 service_map: str | dict = "", client: httpx.AsyncClient | None = None):
        if not partner_token or not str(location_id).strip():
            raise ValueError("для Altegio нужны ALTEGIO_PARTNER_TOKEN и ALTEGIO_LOCATION_ID")
        self.token, self.location, self.staff = partner_token, str(location_id).strip(), int(staff_id)
        self.service_map = parse_map(service_map) if isinstance(service_map, str) else {norm(k): v for k, v in service_map.items()}
        self._client = client

    @property
    def headers(self) -> dict:
        return {
            "Accept": "application/vnd.api.v2+json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=8.0)
        return self._client

    async def _get(self, path: str, params=None):
        try:
            r = await self.client().get(BASE_URL + path, headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SlotsUnavailable(f"Altegio: {type(e).__name__}") from e
        if isinstance(data, dict) and data.get("success") is False:
            raise SlotsUnavailable("Altegio: success=false")
        return data

    async def free_slots(self, niche_key: str, service: str, d: date) -> list:
        params = {}
        sid = self.service_map.get(norm(service))
        if sid:
            params["service_ids[]"] = str(sid)
        data = await self._get(f"/book_times/{self.location}/{self.staff}/{d.isoformat()}", params)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SlotsUnavailable("Altegio: неожиданный формат ответа")
        times = sorted({str(i["time"]) for i in items if isinstance(i, dict) and i.get("time")})
        return times

    async def list_services(self) -> list:
        """Услуги филиала (id и название): нужны, чтобы заполнить ALTEGIO_SERVICE_MAP."""
        data = await self._get(f"/book_services/{self.location}")
        body = data.get("data") if isinstance(data, dict) else None
        items = body.get("services") if isinstance(body, dict) else body
        if not isinstance(items, list):
            raise SlotsUnavailable("Altegio: неожиданный формат списка услуг")
        return [(s.get("id"), s.get("title") or s.get("name")) for s in items if isinstance(s, dict)]
