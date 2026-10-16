"""Общий интерфейс: «дай свободное время на услугу в этот день»."""
import time
from datetime import date


class SlotsUnavailable(Exception):
    """CRM не ответила или вернула непонятный ответ. Время называть нельзя."""


class SlotProvider:
    name = "base"
    is_real = False  # True, если расписание настоящее (не демо)

    async def free_slots(self, niche_key: str, service: str, d: date) -> list:
        """Список свободного времени 'HH:MM' по возрастанию. Бросает SlotsUnavailable при сбое."""
        raise NotImplementedError


class Cached(SlotProvider):
    """Короткий кэш, чтобы не долбить CRM каждым нажатием (у Altegio лимит 5 запросов/сек)."""

    def __init__(self, inner: SlotProvider, ttl: int):
        self.inner, self.ttl, self._c = inner, ttl, {}
        self.name, self.is_real = inner.name, inner.is_real

    async def free_slots(self, niche_key, service, d):
        key = (niche_key, service, d)
        hit = self._c.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return list(hit[1])
        res = await self.inner.free_slots(niche_key, service, d)
        self._c[key] = (time.monotonic(), list(res))
        if len(self._c) > 500:
            self._c.clear()
        return res


def norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def parse_map(raw: str) -> dict:
    """JSON {'название услуги': id} -> словарь с нормализованными ключами."""
    import json
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"не получилось разобрать JSON в настройках: {e}")
    if not isinstance(data, dict):
        raise ValueError("ожидался JSON-объект вида {\"услуга\": id}")
    return {norm(k): v for k, v in data.items()}
