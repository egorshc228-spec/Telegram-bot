"""Общий интерфейс «источника расписания»: демо, Altegio, любая CRM по REST."""
import re
from dataclasses import dataclass
from datetime import date


class BookingError(Exception):
    """Причина, понятная клиенту: слот занят, расписание недоступно и т. п."""


@dataclass
class Slot:
    time: str            # "HH:MM"
    token: str = ""      # служебное значение системы (например, datetime для Altegio)


@dataclass
class Booking:
    external_id: str     # номер записи в CRM
    system: str          # название CRM


class Provider:
    name = "base"

    async def slots(self, service: str | None, d: date) -> list:
        """Свободные окна на день. service=None: без привязки к услуге."""
        raise NotImplementedError

    async def create(self, service: str, d: date, time: str, name: str, phone: str,
                     comment: str) -> Booking | None:
        """Создаёт запись в системе. Бросает BookingError, если не вышло."""
        return None


def normalize_phone(phone: str, country_code: str = "38") -> str:
    """0501234567 -> +380501234567; 380501234567 -> +380501234567."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10 and digits.startswith("0"):
        digits = country_code + digits
    return "+" + digits


def norm_time(value) -> str | None:
    """'2026-10-12T10:00:00' / '10:00' / '9:30' -> 'HH:MM'."""
    m = re.search(r"(\d{1,2}):(\d{2})", str(value))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None
