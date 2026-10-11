"""Altegio (бывший YCLIENTS): свободные слоты и создание записи.

Используются методы официального Online Booking API (developer.alteg.io):
  GET  /api/v1/book_times/{location_id}/{team_member_id}/{date}   (+ service_ids[])
  POST /api/v1/book_record/{location_id}
Авторизация: заголовок  Authorization: Bearer <partner_token>.
Лимит API: 200 запросов в минуту и 5 в секунду с одного IP (поэтому слоты кэшируются).

Ограничения: если в настройках филиала включено подтверждение телефона по SMS
(phone_confirmation), создание записи без кода невозможно: отключите его для онлайн-записи.
"""
import logging
from datetime import date

import httpx

from .base import Booking, BookingError, Provider, Slot, normalize_phone, norm_time

log = logging.getLogger("altegio")

BASE = "https://api.alteg.io/api/v1"

ERRORS = {
    431: "Номер телефона указан в неверном формате. Проверьте, пожалуйста.",
    432: "Нужно подтверждение номера по SMS, онлайн-запись для этого филиала недоступна.",
    433: "Это время только что заняли. Выберите другое.",
    434: "Запись для этого номера недоступна. Свяжитесь с администратором.",
    435: "Не указано имя клиента.",
    436: "На это время нет свободного мастера. Выберите другое.",
    437: "Записи пересекаются по времени. Выберите другое.",
}


class AltegioProvider(Provider):
    name = "Altegio"

    def __init__(self, cfg: dict):
        self.token = cfg.get("partner_token", "")
        self.location_id = int(cfg["location_id"])
        self.staff_id = int(cfg.get("staff_id", 0))          # 0 = любой мастер
        self.country_code = str(cfg.get("country_code", "38"))
        self.services = {k.lower(): int(v) for k, v in (cfg.get("services") or {}).items()}
        self.transport = None                                  # подмена в тестах

    def _headers(self):
        return {"Accept": "application/vnd.api.v2+json", "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}"}

    def _client(self):
        return httpx.AsyncClient(timeout=10, transport=self.transport)

    def _service_id(self, service):
        if service is None:
            return None
        sid = self.services.get(service.lower())
        if sid is None:
            raise BookingError("Эта услуга пока не подключена к расписанию, уточните у администратора.")
        return sid

    async def slots(self, service, d: date) -> list:
        sid = self._service_id(service)
        url = f"{BASE}/book_times/{self.location_id}/{self.staff_id}/{d.isoformat()}"
        params = {"service_ids[]": sid} if sid is not None else None
        try:
            async with self._client() as c:
                r = await c.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            rows = r.json().get("data") or []
        except (httpx.HTTPError, ValueError) as e:
            log.error("Altegio book_times: %s", e)
            raise BookingError("Расписание сейчас недоступно, попробуйте чуть позже.") from e
        out = []
        for row in rows:
            t = norm_time(row.get("time", ""))
            if t:
                out.append(Slot(t, str(row.get("datetime", ""))))
        return out

    async def create(self, service, d: date, time: str, name: str, phone: str, comment: str):
        sid = self._service_id(service)
        fresh = await self.slots(service, d)                  # свежий список прямо перед записью
        slot = next((s for s in fresh if s.time == time), None)
        if not slot or not slot.token:
            raise BookingError(ERRORS[433])
        appointment = {"id": 1, "staff_id": self.staff_id, "datetime": slot.token}
        if sid is not None:
            appointment["services"] = [sid]
        body = {
            "phone": normalize_phone(phone, self.country_code),
            "fullname": name,
            "comment": comment or "Запись из Telegram-бота",
            "appointments": [appointment],
        }
        try:
            async with self._client() as c:
                r = await c.post(f"{BASE}/book_record/{self.location_id}", headers=self._headers(), json=body)
        except httpx.HTTPError as e:
            log.error("Altegio book_record: %s", e)
            raise BookingError("Не удалось связаться с системой записи, попробуйте позже.") from e
        if r.status_code >= 400:
            code = _error_code(r)
            log.error("Altegio book_record %s: %s", r.status_code, r.text[:300])
            raise BookingError(ERRORS.get(code, "Не удалось оформить запись в системе. Попробуйте другое время."))
        try:
            rec = (r.json().get("data") or [{}])[0]
        except ValueError:
            rec = {}
        return Booking(str(rec.get("record_id", "")), self.name)


def _error_code(r) -> int | None:
    """Код ошибки Altegio (431–437) из тела ответа, формат у разных ответов разный."""
    try:
        j = r.json()
    except ValueError:
        return None
    candidates = [j.get("code") if isinstance(j, dict) else None]
    meta = j.get("meta") if isinstance(j, dict) else None
    if isinstance(meta, dict):
        candidates.append(meta.get("code"))
    errors = j.get("errors") if isinstance(j, dict) else None
    if isinstance(errors, dict):
        candidates.append(errors.get("code"))
    for c in candidates:
        try:
            return int(c)
        except (TypeError, ValueError):
            continue
    return None
