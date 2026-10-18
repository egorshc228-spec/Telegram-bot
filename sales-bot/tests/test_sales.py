"""Бот продаж от заявки до звонка: сайт → Telegram/WhatsApp → ИИ → запись → группа → напоминания.
Telegram, WhatsApp, Google Calendar и Claude подменены. Запуск: python -m tests.test_sales"""
import asyncio
import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime, timedelta

os.environ.update({
    "DATA_DIR": tempfile.mkdtemp(), "SALES_CHAT_ID": "-100500", "SALES_STAFF_IDS": "777", "LEAD_API_SECRET": "sek",
    "WA_TOKEN": "watok", "WA_PHONE_NUMBER_ID": "123", "WA_NUMBER": "+380 44 000 00 00", "WA_VERIFY_TOKEN": "vt",
    "WA_APP_SECRET": "appsec", "ANTHROPIC_API_KEY": "k", "SALES_DAYS": "1,2,3,4,5,6,7", "SALES_HOURS": "10:00-19:00",
    "CONTACT_HOURS": "00:00-23:59", "MEET_URL": "https://meet.google.com/abc-defg-hij", "GA4_API_SECRET": "",
    "GOOGLE_CALENDAR_ID": "dan@example.com", "BOT_USERNAME": "adr_sales_bot",
    "SILENCE_CALL_MIN": "0",                     # «молчит 30 мин» проверяется в tests/test_silence.py
})
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps({
    "client_email": "bot@proj.iam.gserviceaccount.com", "token_uri": "https://oauth2.googleapis.com/token",
    "private_key": _key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()).decode()})

import httpx  # noqa: E402
from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from app import agent, config, core, db, gcal, scheduler, slots, wa, web  # noqa: E402
from app.tg import router  # noqa: E402
from tests.fakes import ScriptedClient, say, tool  # noqa: E402

GROUP = -100500
SENT, WA_SENT, GCAL = [], [], []
_mid = [100]


class FakeTG(BaseSession):
    async def close(self): pass

    async def make_request(self, bot, method, timeout=None):
        n = type(method).__name__
        SENT.append(dict(m=n, chat=getattr(method, "chat_id", None), text=getattr(method, "text", None),
                         markup=getattr(method, "reply_markup", None),
                         reply_to=getattr(method, "reply_to_message_id", None)))
        if n in ("SendMessage", "EditMessageText"):
            _mid[0] += 1
            return Message(message_id=_mid[0], date=datetime.now(),
                           chat=Chat(id=getattr(method, "chat_id", None) or 1, type="private"), text="x")
        return True

    async def stream_content(self, *a, **k):
        yield b""


def wa_handler(request: httpx.Request):
    body = json.loads(request.content)
    WA_SENT.append(body)
    if body.get("to") == "380990000000":                   # номер без WhatsApp
        return httpx.Response(400, json={"error": {"code": 131026, "message": "undeliverable"}})
    return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(WA_SENT)}"}]})


def gcal_handler(request: httpx.Request):
    url = str(request.url)
    GCAL.append((request.method, url, request.content))
    if "oauth2" in url:
        return httpx.Response(200, json={"access_token": "gtok", "expires_in": 3600})
    if url.endswith("/freeBusy"):
        tm = db.now().date() + timedelta(days=1)
        return httpx.Response(200, json={"calendars": {"dan@example.com": {"busy": [
            {"start": f"{tm}T10:00:00+03:00", "end": f"{tm}T11:00:00+03:00"}]}}})
    if request.method == "POST" and "/events" in url:
        return httpx.Response(200, json={"id": f"ev{len(GCAL)}"})
    return httpx.Response(204)


_uid = [0]


def upd(**kw):
    _uid[0] += 1
    return Update(update_id=_uid[0], **kw)


def msg(user, text=None, chat=None, **kw):
    _uid[0] += 1
    c = chat or Chat(id=user.id, type="private")
    return upd(message=Message(message_id=_uid[0], date=datetime.now(), chat=c, from_user=user, text=text, **kw))


def cbq(user, data, chat=None):
    _uid[0] += 1
    c = chat or Chat(id=user.id, type="private")
    m = Message(message_id=_uid[0], date=datetime.now(), chat=c, from_user=User(id=1, is_bot=True, first_name="b"),
                text="m")
    return upd(callback_query=CallbackQuery(id=str(_uid[0]), from_user=user, chat_instance="c", message=m, data=data))


def to(chat, contains=None):
    return [s for s in SENT if s["chat"] == chat and s["m"] == "SendMessage"
            and (contains is None or contains in (s["text"] or ""))]


def last(chat):
    return to(chat)[-1]


def btns(s):
    m = s["markup"]
    if m is None or not hasattr(m, "inline_keyboard"):
        return []
    return [(b.text, b.callback_data or b.url) for row in m.inline_keyboard for b in row]


def first(s, prefix):
    return next(d for _, d in btns(s) if d and d.startswith(prefix))


def wa_to(num):
    return [w for w in WA_SENT if w.get("to") == num]


def signed(payload: dict):
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"appsec", raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


def wa_msg(frm, text=None, choice=None, name="Клієнт"):
    m = {"from": frm, "id": "x", "timestamp": "1"}
    if choice:
        kind = "list_reply" if choice.startswith("s:") else "button_reply"
        m.update(type="interactive", interactive={"type": kind, kind: {"id": choice, "title": choice}})
    else:
        m.update(type="text", text={"body": text})
    return {"entry": [{"changes": [{"value": {"contacts": [{"wa_id": frm, "profile": {"name": name}}],
                                              "messages": [m]}}]}]}


async def main():
    await db.init()
    wa.transport = httpx.MockTransport(wa_handler)
    gcal.transport = httpx.MockTransport(gcal_handler)
    bot = Bot("1:AAA", session=FakeTG(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    core.bot, core.bot_username = bot, "adr_sales_bot"
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    feed = lambda u: dp.feed_update(bot, u)  # noqa: E731
    http = TestClient(TestServer(web.app()))
    await http.start_server()

    async def hook(payload, good=True):
        raw, h = signed(payload)
        if not good:
            h["X-Hub-Signature-256"] = "sha256=bad"
        r = await http.post("/wa/webhook", data=raw, headers=h)
        await asyncio.gather(*list(web._tasks))
        return r.status

    tomorrow = db.now().date() + timedelta(days=1)

    # 1. заявка с сайта: без секрета — 403; с секретом — лид, ссылки t.me и wa.me, карточка в группе
    form = {"name": "Олена", "contact": "@olena_beauty", "service": "AI-адміністратор", "niche": "салон, Одеса",
            "budget": "$500", "attribution": {"utm_source": "google", "utm_campaign": "ai", "gclid": "x",
                                              "landing": "https://adrenalinegrowth.com/ai-admin"},
            "page": "/ai-admin", "cid": "123.456"}
    r = await http.post("/api/lead", json=form)
    assert r.status == 403
    r = await http.post("/api/lead", json=form, headers={"X-Lead-Secret": "sek"})
    d = await r.json()
    assert d["ok"] and d["tg"] == f"https://t.me/adr_sales_bot?start=l_{d['token']}" and "wa.me/380440000000" in d["wa"]
    assert f"%23{d['token']}" in d["wa"]
    card = last(GROUP)["text"]
    assert "Лид #1" in card and "Олена" in card and "AI-адміністратор" in card and "gclid" in card, card
    assert ("🙋 Беру сам", "g:take:1") in btns(last(GROUP))
    L1 = await db.lead_by_token(d["token"])
    assert L1["tg_username"] == "olena_beauty" and L1["lang"] == "uk" and L1["next_at"] and L1["cid"] == "123.456"
    r = await http.post("/api/lead", json={**form, "company": "bot"}, headers={"X-Lead-Secret": "sek"})
    assert (await r.json()) == {"ok": True}                                   # honeypot: тихо игнорируем

    # 2. человек нажал «Обрати час у Telegram» → приветствие с его заявкой и дни; группа видит переход
    OL = User(id=501, is_bot=False, first_name="Olena", username="olena_beauty", language_code="uk")
    await feed(msg(OL, f"/start l_{d['token']}"))
    g = last(OL.id)
    assert "Вітаю, Олена" in g["text"] and "AI-асистент Даниїла" in g["text"] and "«AI-адміністратор»" in g["text"]
    assert any(x and x.startswith("d:") for _, x in btns(g)) and to(GROUP, "Открыл Telegram")
    L1 = await db.get_lead(L1["id"])
    assert L1["channel"] == "tg" and L1["stage"] == "talking" and L1["tg_id"] == 501
    await scheduler.run_once(db.now() + timedelta(minutes=5))         # шаблон WhatsApp ему уже не нужен
    assert not wa_to("") and (await db.get_lead(L1["id"]))["stage"] == "talking"

    # 3. день → время (занятое в Google Calendar не предлагается) → формат → запись + событие в календаре
    await feed(cbq(OL, f"d:{tomorrow:%Y%m%d}"))
    times = [t for t, _ in btns(last(OL.id))]
    assert "10:00" not in times and "10:30" not in times and "11:00" in times, times
    await feed(cbq(OL, f"s:{tomorrow:%Y%m%d}1100"))
    fm = last(OL.id)
    assert ("Дзвінок у Telegram", f"f:tg:{tomorrow:%Y%m%d}1100") in btns(fm) and "Як зручніше" in fm["text"]
    await feed(cbq(OL, f"f:tg:{tomorrow:%Y%m%d}1100"))
    b = last(OL.id)
    assert "✅ Готово!" in b["text"] and "11:00" in b["text"] and "у Telegram" in b["text"]
    assert any(x.startswith("re:") for _, x in btns(b))
    ev = [c for c in GCAL if c[0] == "POST" and "/events" in c[1]]
    assert ev and "olena_beauty" in ev[-1][2].decode() and "meet.google.com" in ev[-1][2].decode()
    assert to(GROUP, "Записался на звонок") and "Событие в календаре создано" in to(GROUP, "Записался")[-1]["text"]
    call = await db.active_call(L1["id"])
    assert call["format"] == "tg" and call["event_id"]
    assert slots.parse_stamp(f"{tomorrow:%Y%m%d}1100") not in (await slots.free())[tomorrow]   # окно занято
    await feed(cbq(OL, f"s:{tomorrow:%Y%m%d}1130"))                          # уже записан → «перенести?»
    assert "У вас уже є дзвінок" in last(OL.id)["text"]

    # 4. Даниил подтверждает в группе; посторонний — нет
    STRANGER, DAN = User(id=9, is_bot=False, first_name="X"), User(id=777, is_bot=False, first_name="Dan",
                                                                     username="conversion_wizard")
    gchat = Chat(id=GROUP, type="supergroup")
    await feed(cbq(STRANGER, f"g:ok:{call['id']}"))
    assert (await db.get_call(call["id"]))["status"] == "booked"
    await feed(cbq(DAN, f"g:ok:{call['id']}", chat=gchat))
    assert (await db.get_call(call["id"]))["status"] == "confirmed" and "підтвердив дзвінок" in last(OL.id)["text"]

    # 5. напоминание за 2 часа: клиенту и в группу
    at = datetime.fromisoformat(call["at"])
    res = await scheduler.run_once(at - timedelta(minutes=90))
    assert res["reminders"] == 1 and "Нагадую" in last(OL.id)["text"] and to(GROUP, "Скоро звонок")

    # 6. перенос: окно освобождается, событие удаляется, снова выбор дня
    await feed(cbq(OL, f"re:{call['id']}"))
    assert (await db.get_call(call["id"]))["status"] == "resched" and to(GROUP, "Переносит звонок")
    assert any(c[0] == "DELETE" for c in GCAL) and "Оберіть день" in last(OL.id)["text"]

    # 7. человек пишет боту сам (без заявки): приветствие, вопрос → ответ ИИ из фактов, кнопки по show_slots
    IV = User(id=502, is_bot=False, first_name="Ivan", language_code="ru")
    await feed(msg(IV, "/start"))
    assert "Здравствуйте! Я AI-ассистент Даниила" in last(IV.id)["text"] and to(GROUP, "написал боту продаж")
    agent.client = ScriptedClient(tool("show_slots"), say("Запуск $800, дальше **$160** в месяц. Выберите время 👇"))
    await feed(msg(IV, "сколько стоит AI-администратор?"))
    ans = to(IV.id, "Запуск $800")[-1]["text"]
    assert "**" not in ans and "Выберите день" in last(IV.id)["text"]
    sysmsg = "".join(x["text"] for x in agent.client.calls[0]["system"])
    assert "$160/мес" in sysmsg and "Свободные окна" in sysmsg and f"{tomorrow.isoformat()}" in sysmsg
    assert agent.client.calls[0]["messages"][0]["content"] == "[человек открыл чат]"
    assert to(GROUP, "сколько стоит AI-администратор")                         # переписка видна в группе

    # 8. ИИ сам записывает по фразе «завтра в 12 в Meet» (+ сохраняет инфо о бизнесе)
    agent.client = ScriptedClient(tool("save_info", business="СТО, Киев", request="больше записей"),
                                  tool("book_call", datetime=f"{tomorrow}T12:00", format="meet"),
                                  say("Готово, до встречи!"))
    await feed(msg(IV, "давайте завтра в 12 в гугл мит, у меня СТО в Киеве"))
    bk = to(IV.id, "Готово!")[-1]["text"]
    assert "meet.google.com/abc-defg-hij" in bk and "12:00" in bk, bk
    L2 = await db.lead_by_tg(IV.id)
    assert L2["stage"] == "booked" and L2["biz"] == "СТО, Киев"
    # недоступное время ИИ не запишет: инструмент возвращает ошибку со свободными окнами
    agent.client = ScriptedClient(tool("book_call", datetime=f"{tomorrow}T10:00", format="tg"), say("Это время занято."))
    acts = agent.new_actions(lambda *a: None)
    res, err = await agent._run("book_call", {"datetime": f"{tomorrow}T10:00", "format": "tg"},
                                {**L2, "channel": "tg"}, acts)
    assert err and "недоступно" in res
    res, err = await agent._run("book_call", {"datetime": f"{tomorrow}T15:00", "format": "wa"}, L2, acts)
    assert err and "недоступен" in res                                        # WhatsApp-звонок в Telegram нельзя

    # 9. WhatsApp: лид не открыл ничего сам → через TG_WAIT_MIN шаблон на номер из формы
    r = await http.post("/api/lead", headers={"X-Lead-Secret": "sek"},
                        json={"name": "Марина", "contact": "067 111 22 33", "service": "Google Ads",
                              "page": "/ru/google-ads", "attribution": {}})
    L3 = await db.lead_by_token((await r.json())["token"])
    assert L3["phone"] == "+380671112233" and L3["wa_id"] == "380671112233" and L3["lang"] == "ru"
    await scheduler.run_once(db.now() + timedelta(minutes=1))
    assert not wa_to("380671112233")                                          # ещё ждём, вдруг откроет сам
    await scheduler.run_once(db.now() + timedelta(minutes=4))
    tpl = wa_to("380671112233")[-1]
    assert tpl["type"] == "template" and tpl["template"]["name"] == "lead_followup"
    assert tpl["template"]["language"]["code"] == "ru" and tpl["template"]["components"][0]["parameters"][0]["text"] == "Марина"
    L3 = await db.get_lead(L3["id"])
    assert L3["stage"] == "wa_sent" and to(GROUP, "первое сообщение в WhatsApp")

    # вебхук: подпись проверяется, verify-токен отвечает challenge
    r = await http.get("/wa/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"})
    assert r.status == 200 and await r.text() == "42"
    assert await hook(wa_msg("380671112233", "да"), good=False) == 403

    # ответ на шаблон → ИИ отвечает, и список ближайших окон (первый ответ — окна показываем всегда)
    agent.client = ScriptedClient(say("Отлично! Вот ближайшие окна."))
    assert await hook(wa_msg("380671112233", "Да, давайте созвонимся")) == 200
    texts = [w for w in wa_to("380671112233") if w["type"] == "text"]
    lists = [w for w in wa_to("380671112233") if w["type"] == "interactive"]
    assert texts and "Отлично" in texts[-1]["text"]["body"]
    rows = lists[-1]["interactive"]["action"]["sections"][0]["rows"]
    assert lists[-1]["interactive"]["type"] == "list" and 2 <= len(rows) <= 10 and all(len(x["title"]) <= 24 for x in rows)
    assert (await db.get_lead(L3["id"]))["stage"] == "talking"
    sid = next(x["id"] for x in rows if x["id"].startswith("s:"))
    await hook(wa_msg("380671112233", choice=sid))
    fmt = wa_to("380671112233")[-1]["interactive"]
    assert fmt["type"] == "button" and [b["reply"]["id"].split(":")[1] for b in fmt["action"]["buttons"]] == ["wa", "meet", "phone"]
    await hook(wa_msg("380671112233", choice=f"f:phone:{sid[2:]}"))
    done = wa_to("380671112233")[-1]
    assert done["type"] == "interactive" and "Готово" in done["interactive"]["body"]["text"]
    assert "+380671112233" in done["interactive"]["body"]["text"] and "*" in done["interactive"]["body"]["text"]
    assert (await db.get_lead(L3["id"]))["stage"] == "booked"

    # 10. нет ответа в WhatsApp → карточка «позвонить вручную»; номер без WhatsApp → сразу «позвонить»
    for name, phone in (("Тихий", "0502223344"), ("Безвацап", "0990000000")):
        await http.post("/api/lead", headers={"X-Lead-Secret": "sek"}, json={"name": name, "contact": phone})
    await scheduler.run_once(db.now() + timedelta(minutes=4))
    quiet, nowa = await db.lead_by_phone("+380502223344"), await db.lead_by_phone("+380990000000")
    assert quiet["stage"] == "wa_sent" and nowa["stage"] == "need_call"
    assert "Позвонить вручную" in to(GROUP, "Безвацап")[-1]["text"]
    await scheduler.run_once(db.now() + timedelta(minutes=4 + config.NO_REPLY_MIN + 1))
    assert (await db.get_lead(quiet["id"]))["stage"] == "need_call" and "нет ответа в WhatsApp" in to(GROUP, "Тихий")[-1]["text"]
    # статус «не доставлено» от Meta тоже переводит в «позвонить»
    await http.post("/api/lead", headers={"X-Lead-Secret": "sek"}, json={"name": "Сбой", "contact": "0503334455"})
    await scheduler.run_once(db.now() + timedelta(minutes=4))
    await hook({"entry": [{"changes": [{"value": {"statuses": [
        {"recipient_id": "380503334455", "status": "failed", "errors": [{"code": 131026}]}]}}]}]})
    assert (await db.lead_by_phone("+380503334455"))["stage"] == "need_call" and to(GROUP, "код 131026")

    # 11. кнопка WhatsApp на сайте: сообщение с #токеном с любого номера → лид привязан, приветствие и окна
    r = await http.post("/api/lead", headers={"X-Lead-Secret": "sek"},
                        json={"name": "Петро", "contact": "@petro", "service": "Аудит"})
    tok = (await r.json())["token"]
    await hook(wa_msg("380631230000", f"Заявка #{tok}: хочу обрати час дзвінка"))
    hi = [w for w in wa_to("380631230000") if w["type"] == "interactive"][-1]["interactive"]
    assert "Вітаю, Петро" in hi["body"]["text"] and hi["type"] == "list"
    L6 = await db.lead_by_token(tok)
    assert L6["channel"] == "wa" and L6["wa_id"] == "380631230000" and L6["stage"] == "talking"

    # 12. незнакомый номер пишет в WhatsApp сам (по-русски) → новый лид, ответ ИИ и окна
    agent.client = ScriptedClient(say("Здравствуйте! Бот стоит $800 запуск и $160 в месяц."))
    await hook(wa_msg("380971234567", "Здравствуйте, сколько стоит такой бот?", name="Сергей"))
    L7 = await db.lead_by_wa("380971234567")
    assert L7["source"] == "wa" and L7["lang"] == "ru" and L7["name"] == "Сергей"
    kinds = [w["type"] for w in wa_to("380971234567")]
    assert kinds == ["text", "interactive"], kinds
    assert to(GROUP, "написал в WhatsApp")

    # 13. Даниил отвечает через бота → уходит в канал лида, ИИ по лиду выключается
    await feed(cbq(DAN, f"g:msg:{L2['id']}", chat=gchat))
    fr = last(GROUP)
    assert "Ответьте на это сообщение" in fr["text"] and type(fr["markup"]).__name__ == "ForceReply"
    await feed(msg(DAN, "Иван, добрый день! Жду завтра 👍", chat=gchat))
    assert "Даниил, ADrenaline" in last(IV.id)["text"] and "Отправлено лиду" in last(GROUP)["text"]
    assert (await db.get_lead(L2["id"]))["stage"] == "taken"
    agent.client = ScriptedClient(say("ИИ НЕ ДОЛЖЕН ОТВЕЧАТЬ"))
    await feed(msg(IV, "а можно ещё вопрос?"))
    assert not agent.client.calls and to(GROUP, "а можно ещё вопрос")

    # 14. окно WhatsApp закрыто (человек молчит больше суток) → ответ через бота не уходит, подсказка позвонить
    await db.update_lead(L3["id"], last_in=db.iso(db.now() - timedelta(hours=30)), stage="talking")
    await feed(cbq(DAN, f"g:msg:{L3['id']}", chat=gchat))
    await feed(msg(DAN, "Марина, добрый день", chat=gchat))
    assert "Не доставлено" in last(GROUP)["text"] and "380671112233" in last(GROUP)["text"]

    # 15. «не пишите мне» → stop_contact, больше не трогаем
    agent.client = ScriptedClient(tool("stop_contact"), say("Поняла, больше не беспокоим. Хорошего дня!"))
    await hook(wa_msg("380631230000", "Не надо, мне не интересно"))
    L6 = await db.get_lead(L6["id"])
    assert L6["stage"] == "opted_out" and L6["next_at"] is None and to(GROUP, "больше не писать")

    # 16. звонок по телефону без номера: бот спрашивает номер, проверяет его и записывает
    PH = User(id=503, is_bot=False, first_name="Тарас", language_code="uk")
    await feed(msg(PH, "/start"))
    sl = (await slots.free())[tomorrow][-1]
    await feed(cbq(PH, f"f:phone:{slots.stamp(sl)}"))
    assert "Напишіть номер" in last(PH.id)["text"]
    agent.client = ScriptedClient(say("НЕ ДОЛЖЕН"))
    await feed(msg(PH, "123"))
    assert "не номер телефону" in last(PH.id)["text"] and not agent.client.calls
    await feed(msg(PH, "050 111 22 33"))
    assert "+380501112233" in last(PH.id)["text"] and "✅ Готово!" in last(PH.id)["text"]

    # 17. общался, но не записался → одно напоминание через NUDGE_HOURS; ночью не пишем
    QQ = User(id=504, is_bot=False, first_name="Q", language_code="uk")
    await feed(msg(QQ, "/start"))
    agent.client = ScriptedClient(say("Так, працюємо з магазинами."))
    await feed(msg(QQ, "а з магазинами працюєте?"))
    LQ = await db.lead_by_tg(QQ.id)
    nx = datetime.fromisoformat(LQ["next_at"])
    config.CONTACT_HOURS = "09:00-20:00"
    night = nx.replace(hour=23, minute=0) if nx.hour < 23 else nx
    await scheduler.run_once(night)
    assert datetime.fromisoformat((await db.get_lead(LQ["id"]))["next_at"]).hour == 9     # перенесли на утро
    morning = datetime.fromisoformat((await db.get_lead(LQ["id"]))["next_at"]) + timedelta(minutes=1)
    await scheduler.run_once(morning)
    assert "Підібрати зручний час" in last(QQ.id)["text"] and (await db.get_lead(LQ["id"]))["nudged"] == 1
    n_before = len(to(QQ.id))
    await scheduler.run_once(morning + timedelta(days=3))
    assert len(to(QQ.id)) == n_before
    assert slots.next_contact_time(datetime(2026, 10, 20, 22, 0, tzinfo=db.TZ)) == datetime(2026, 10, 21, 9, 0, tzinfo=db.TZ)
    assert slots.next_contact_time(datetime(2026, 10, 20, 7, 0, tzinfo=db.TZ)) == datetime(2026, 10, 20, 9, 0, tzinfo=db.TZ)
    config.CONTACT_HOURS = "00:00-23:59"

    # 18. «Беру сам» и «Не целевой» из карточки
    await feed(cbq(DAN, f"g:lost:{nowa['id']}", chat=gchat))
    assert (await db.get_lead(nowa["id"]))["stage"] == "lost"
    await feed(cbq(DAN, f"g:take:{quiet['id']}", chat=gchat))
    q = await db.get_lead(quiet["id"])
    assert q["stage"] == "taken" and q["assignee"] == "@conversion_wizard"

    # 19. /leads в группе
    await feed(msg(DAN, "/leads", chat=gchat))
    assert "Последние лиды" in last(GROUP)["text"]

    from app.texts import guess_lang
    assert guess_lang("Добрий день") == "uk" and guess_lang("Сколько стоит?") == "ru" and guess_lang("ok", None) is None
    assert guess_lang("так, давайте завтра", None) is None                   # «так» есть в обоих языках

    # 20. разметка: HTML → WhatsApp, нормализация телефонов
    assert wa.to_wa_markup("✅ <b>Готово</b> &lt;x&gt;") == "✅ *Готово* <x>"
    assert core.normalize_phone("+38 (067) 111-22-33") == "+380671112233" and core.normalize_phone("@nick") == ""

    await http.close()
    print("бот продаж: все проверки пройдены · Telegram", len(SENT), "· WhatsApp", len(WA_SENT), "· Calendar", len(GCAL))


if __name__ == "__main__":
    asyncio.run(main())
