"""Интеграции с CRM на подменённом HTTP (без сети). python -m tests.test_booking"""
import asyncio, json, os, tempfile
os.environ["GA4_API_SECRET"] = ""  # тесты не шлют события в настоящий GA4
os.environ["DATA_DIR"] = tempfile.mkdtemp()
import httpx
from datetime import date

from app import ai, booking
from app.booking.base import BookingError, normalize_phone, norm_time
from app.booking.altegio import AltegioProvider
from app.booking.generic import GenericProvider

D = ai.upcoming_days()[0]
CALLS = []


def altegio_handler(request: httpx.Request) -> httpx.Response:
    CALLS.append((request.method, request.url.path, dict(request.url.params), request.headers))
    if request.method == "GET":
        assert request.url.path == f"/api/v1/book_times/777/0/{D.isoformat()}", request.url.path
        assert request.headers["authorization"] == "Bearer TOKEN"
        assert request.headers["accept"] == "application/vnd.api.v2+json"
        assert request.url.params.get("service_ids[]") == "331"
        return httpx.Response(200, json={"success": True, "data": [
            {"time": "10:00", "seance_length": 3600, "datetime": f"{D.isoformat()}T10:00:00+03:00"},
            {"time": "11:30", "seance_length": 3600, "datetime": f"{D.isoformat()}T11:30:00+03:00"}], "meta": []})
    body = json.loads(request.content)
    assert request.url.path == "/api/v1/book_record/777"
    assert body["phone"] == "+380501234567" and body["fullname"] == "Анна"
    ap = body["appointments"][0]
    assert ap["services"] == [331] and ap["staff_id"] == 0
    assert ap["datetime"] == f"{D.isoformat()}T11:30:00+03:00"
    return httpx.Response(201, json={"success": True, "data": [{"id": 1, "record_id": 2820023, "record_hash": "h"}]})


def mk_altegio(handler):
    p = AltegioProvider({"partner_token": "TOKEN", "location_id": 777,
                         "services": {"Женская стрижка": 331}})
    p.transport = httpx.MockTransport(handler)
    return p


async def test_altegio():
    p = mk_altegio(altegio_handler)
    slots = await p.slots("Женская стрижка", D)
    assert [s.time for s in slots] == ["10:00", "11:30"]
    b = await p.create("Женская стрижка", D, "11:30", "Анна", "0501234567", "")
    assert b.external_id == "2820023" and b.system == "Altegio"
    # слот, которого нет в свежем списке
    try:
        await p.create("Женская стрижка", D, "15:00", "Анна", "0501234567", "")
        assert False
    except BookingError as e:
        assert "заняли" in str(e)
    # услуга не из таблицы соответствия
    try:
        await p.slots("Неизвестная", D)
        assert False
    except BookingError as e:
        assert "не подключена" in str(e)


async def test_altegio_errors():
    def h(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"time": "10:00", "datetime": "x"}]})
        return httpx.Response(422, json={"success": False, "meta": {"code": 433, "message": "busy"}})
    p = mk_altegio(h)
    try:
        await p.create("Женская стрижка", D, "10:00", "Анна", "0501234567", "")
        assert False
    except BookingError as e:
        assert "только что заняли" in str(e)

    def down(request):
        return httpx.Response(500)
    try:
        await mk_altegio(down).slots("Женская стрижка", D)
        assert False
    except BookingError as e:
        assert "недоступно" in str(e)


def generic_cfg():
    return {"provider": "generic", "title": "CleverBox", "base_url": "https://crm.test/api",
            "headers": {"Authorization": "Bearer env:CRM_T"}, "services": {"Диагностика": "10"},
            "slots": {"path": "/slots", "query": {"date": "{date}", "service_id": "{service_id}"},
                      "result_path": "data.slots", "time_field": "time"},
            "booking": {"method": "POST", "path": "/bookings", "id_path": "data.id",
                        "body": {"service_id": "{service_id}", "start": "{date}T{time}:00",
                                 "client_phone": "{phone}", "name": "{name}"}}}


async def test_generic_and_facade():
    os.environ["CRM_T"] = "SECRET"
    seen = {}

    def h(request):
        assert request.headers["authorization"] == "Bearer SECRET"
        if request.method == "GET":
            seen["q"] = dict(request.url.params)
            return httpx.Response(200, json={"data": {"slots": [{"time": "09:30"}, {"time": "2026-10-12T12:00:00"}]}})
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"id": 55}})

    booking.setup({"auto": generic_cfg()})
    assert booking.is_live("auto") and not booking.is_live("salon")
    booking.provider("auto").transport = httpx.MockTransport(h)
    assert await booking.free_slots("auto", "Диагностика", D) == ["09:30", "12:00"]
    assert seen["q"] == {"date": D.isoformat(), "service_id": "10"}
    b = await booking.create("auto", "Диагностика", D, "09:30", "Олег", "0671112233")
    assert b.external_id == "55" and b.system == "CleverBox"
    assert seen["body"]["start"] == f"{D.isoformat()}T09:30:00" and seen["body"]["client_phone"] == "+380671112233"
    # демо-ниши не затронуты
    assert await booking.free_slots("salon", None, D)
    booking.setup({})


async def test_cache_and_days():
    n = {"c": 0}

    def h(request):
        n["c"] += 1
        return httpx.Response(200, json={"data": [{"time": "10:00", "datetime": "d"}]})

    booking.setup({"salon": {"provider": "altegio", "partner_token": "t", "location_id": 1, "services": {}}})
    booking.provider("salon").transport = httpx.MockTransport(h)
    days = ai.upcoming_days()
    res = await booking.free_slots_days("salon", None, days)
    assert len(res) == len(days) == 7 and n["c"] == 7
    await booking.free_slots_days("salon", None, days)
    assert n["c"] == 7, "второй вызов должен идти из кэша"
    # промпт ИИ получает слоты из CRM
    sysmsg = await ai.dynamic_system("salon", {}, [])
    assert "10:00" in sysmsg
    # когда CRM лежит, ИИ не выдумывает время
    booking.provider("salon").transport = httpx.MockTransport(lambda r: httpx.Response(500))
    booking._cache.clear()
    assert "недоступно" in await ai.dynamic_system("salon", {}, [])
    booking.setup({})


def test_helpers():
    assert normalize_phone("0501234567") == "+380501234567"
    assert normalize_phone("+38 (050) 123-45-67") == "+380501234567"
    assert normalize_phone("380501234567") == "+380501234567"
    assert norm_time("2026-10-12T09:05:00") == "09:05" and norm_time("9:30") == "09:30" and norm_time("x") is None


async def main():
    await test_altegio()
    await test_altegio_errors()
    await test_generic_and_facade()
    await test_cache_and_days()
    test_helpers()
    print("интеграции с CRM: все проверки пройдены")

asyncio.run(main())
