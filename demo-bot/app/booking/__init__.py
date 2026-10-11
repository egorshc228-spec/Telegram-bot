"""Фасад расписания. Бот не знает, откуда берутся слоты: демо, Altegio или другая CRM.

Настройки по компаниям: переменная BOOKING_CONFIG (JSON) или файл booking.json
(в корне проекта или в DATA_DIR). Подробности в README и booking.example.json.
Без настроек для компании используется демо-расписание.
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

from .. import config
from ..niches import NICHES
from .altegio import AltegioProvider
from .base import Booking, BookingError, Provider, Slot  # noqa: F401
from .demo import DemoProvider
from .generic import GenericProvider

log = logging.getLogger("booking")

CACHE_TTL = 45          # секунд: бережём лимит API (у Altegio 5 запросов в секунду)
_cache: dict = {}
_sem = asyncio.Semaphore(3)
_providers: dict = {}


def _resolve_env(obj):
    """Строки вида env:NAME заменяются значением переменной окружения (чтобы ключи не лежали в файле)."""
    if isinstance(obj, str):
        def repl(m):
            val = os.getenv(m.group(1), "")
            if not val:
                log.warning("Переменная окружения %s не задана", m.group(1))
            return val
        return re.sub(r"env:([A-Za-z0-9_]+)", repl, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env(v) for v in obj]
    return obj


def _load_config() -> dict:
    raw = os.getenv("BOOKING_CONFIG", "").strip()
    if raw:
        return json.loads(raw)
    for p in (config.BASE_DIR / "booking.json", config.DATA_DIR / "booking.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _build(niche_key: str, cfg: dict) -> Provider:
    kind = cfg.get("provider", "demo")
    cfg = _resolve_env(cfg)
    if kind == "altegio":
        return AltegioProvider(cfg)
    if kind == "generic":
        return GenericProvider(cfg)
    if kind == "demo":
        return DemoProvider(niche_key)
    raise ValueError(f"Неизвестный provider «{kind}» для {niche_key}")


def setup(cfg: dict | None = None):
    """Читает настройки и создаёт провайдеры. Вызывается при старте (и в тестах)."""
    _providers.clear()
    _cache.clear()
    cfg = _load_config() if cfg is None else cfg
    for key in NICHES:
        _providers[key] = _build(key, cfg[key]) if key in cfg else DemoProvider(key)
    # предупреждаем о недостающих услугах в таблице соответствия
    for key, p in _providers.items():
        mapping = getattr(p, "services", None)
        if mapping is not None:
            missing = [s[0] for s in NICHES[key].services if s[0].lower() not in mapping]
            if missing:
                log.warning("%s: в настройках нет ID услуг: %s", key, ", ".join(missing))


def provider(niche_key: str) -> Provider:
    if not _providers:
        setup()
    return _providers[niche_key]


def describe() -> str:
    if not _providers:
        setup()
    return ", ".join(f"{k}: {p.name}" for k, p in _providers.items())


def is_live(niche_key: str) -> bool:
    return not isinstance(provider(niche_key), DemoProvider)


async def _slots(niche_key: str, service, d: date) -> list:
    key = (niche_key, (service or "").lower(), d.isoformat())
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    async with _sem:
        slots = await provider(niche_key).slots(service, d)
    _cache[key] = (time.monotonic(), slots)
    return slots


async def free_slots(niche_key: str, service, d: date) -> list:
    """Список свободного времени 'HH:MM'. Бросает BookingError, если расписание недоступно."""
    return [s.time for s in await _slots(niche_key, service, d)]


async def free_slots_days(niche_key: str, service, days: list) -> dict:
    """{date: [время,...]} для нескольких дней сразу. Ошибка одного дня не ломает остальные."""
    results = await asyncio.gather(*[free_slots(niche_key, service, d) for d in days], return_exceptions=True)
    out, errors = {}, []
    for d, r in zip(days, results):
        if isinstance(r, BookingError):
            errors.append(r)
        elif isinstance(r, Exception):
            raise r
        else:
            out[d] = r
    if not out and errors:
        raise errors[0]
    return out


async def create(niche_key: str, service: str, d: date, t: str, name: str, phone: str,
                 comment: str = "") -> Booking | None:
    """Создаёт запись в CRM (для демо ничего не делает). Бросает BookingError."""
    b = await provider(niche_key).create(service, d, t, name, phone, comment)
    for k in [k for k in _cache if k[0] == niche_key]:
        _cache.pop(k, None)           # слот занят, кэш больше не верен
    return b
