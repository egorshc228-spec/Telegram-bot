"""Демо-расписание: условная занятость из app/niches.py. Для реальных клиентов не используется."""
from datetime import date

from ..niches import free_slots
from .base import Provider, Slot


class DemoProvider(Provider):
    name = "Демо"

    def __init__(self, niche_key: str):
        self.niche_key = niche_key

    async def slots(self, service, d: date) -> list:
        return [Slot(t) for t in free_slots(self.niche_key, d)]
