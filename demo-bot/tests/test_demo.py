"""Проверки без Telegram и без ключей. Запуск: python -m tests.test_demo"""
import asyncio
import io
import os
import tempfile
from types import SimpleNamespace as NS

os.environ["DATA_DIR"] = tempfile.mkdtemp()

from openpyxl import load_workbook  # noqa: E402

from app import ai, config, db  # noqa: E402
from app.bot import HOW, WELCOME, home_kb, lead_card, niche_menu_kb  # noqa: E402
from app.niches import NICHES, find_service, free_slots  # noqa: E402
from app.report import leads_to_xlsx  # noqa: E402


def test_data():
    assert len(NICHES) == 4
    for k, n in NICHES.items():
        assert n.services and n.faq and n.slots, k
        assert any(free_slots(k, d) for d in ai.upcoming_days()), k
        assert free_slots(k, ai.upcoming_days()[0]) == free_slots(k, ai.upcoming_days()[0])
        sysmsg = asyncio.run(ai.build_system(k))
        assert "Прайс" in sysmsg and n.company in sysmsg
    assert find_service("salon", "женская стрижка")[0] == 0
    assert find_service("salon", "ракета") is None


def test_callback_sizes():
    for k, n in NICHES.items():
        for row in niche_menu_kb(k).inline_keyboard:
            for b in row:
                assert len(b.callback_data.encode()) <= 64
        assert len(f"bt:{k}:{len(n.services)}:4:2000".encode()) <= 64
    for row in home_kb().inline_keyboard:
        for b in row:
            assert len(b.callback_data) <= 64
    assert len(WELCOME) < 4096 and len(HOW) < 4096


async def test_db_and_report():
    await db.init_db()
    lid = await db.add_lead(1, "u", "salon", "Женская стрижка", 700, "2026-10-11", "10:00", "Анна", "0501234567")
    l = await db.get_lead(lid)
    assert "Анна" in lead_card(l)
    await db.set_status(lid, "ok")
    assert (await db.last_lead(1, "salon"))["status"] == "ok"
    wb = load_workbook(io.BytesIO(leads_to_xlsx(await db.leads_for(1))))
    ws = wb.active
    assert ws["H2"].value == "Анна" and ws["L2"].value == "Подтверждена"
    # лимиты
    assert await db.hit(7, 2, 100) == "ok"
    assert await db.hit(7, 2, 100) == "ok"
    assert await db.hit(7, 2, 100) == "user_limit"
    assert await db.hit(8, 2, 2) == "global_limit"


class FakeClient:
    """Имитация Claude: сначала вызывает create_lead, потом отвечает текстом."""

    def __init__(self, args):
        self.args, self.calls = args, 0
        self.messages = self

    async def create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            blk = NS(type="tool_use", id="t1", name="create_lead", input=self.args)
            return NS(stop_reason="tool_use", content=[blk])
        last = kw["messages"][-1]["content"][0]
        return NS(stop_reason="end_turn", content=[NS(type="text", text="RESULT: " + last["content"])])


async def test_ai_lead_flow():
    d = ai.upcoming_days()[0]
    t = free_slots("salon", d)[0]
    good = dict(service="Женская стрижка", date=d.isoformat(), time=t, name="Иван", phone="0507654321")
    created = []

    async def on_lead(data):
        created.append(data)
        return 42

    ai.client = FakeClient(good)
    text, lid = await ai.ask(5, "salon", "запишите", None, on_lead)
    assert lid == 42 and created[0]["price"] == 700 and "создана" in text

    bad = dict(good, time="03:33")  # такого окна нет
    ai.client = FakeClient(bad)
    text, lid = await ai.ask(5, "salon", "запишите", None, on_lead)
    assert lid is None and "недоступно" in text
    bad = dict(good, phone="12")
    ai.client = FakeClient(bad)
    text, lid = await ai.ask(5, "salon", "запишите", None, on_lead)
    assert lid is None and "телефон" in text.lower()
    # фото уходит как image-блок
    ai.client = FakeClient(good)
    await ai.ask(6, "auto", "что это?", b"\xff\xd8jpeg", on_lead)


def main():
    test_data()
    test_callback_sizes()
    asyncio.run(test_db_and_report())
    asyncio.run(test_ai_lead_flow())
    print("все проверки пройдены")


if __name__ == "__main__":
    main()
