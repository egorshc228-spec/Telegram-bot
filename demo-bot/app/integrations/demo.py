from datetime import date

from ..niches import free_slots as demo_slots
from .base import SlotProvider


class DemoProvider(SlotProvider):
    """Условное расписание (часть окон «занята» по формуле). Для показа клиентам."""
    name = "demo"
    is_real = False

    async def free_slots(self, niche_key: str, service: str, d: date) -> list:
        return demo_slots(niche_key, d)
