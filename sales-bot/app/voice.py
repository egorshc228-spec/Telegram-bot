"""Голосовой ИИ прямо в боте: звонок агента ElevenLabs через номер Zadarma, окна и запись для агента, итог звонка.
По умолчанию выключен (VOICE_CALLS=0): тогда call() возвращает False и бот ставит карточку «☎️ Позвонить».

Как это устроено:
  «пора звонить» (scheduler.call_now / need_call) → voice.call() → ElevenLabs звонит лиду.
  В разговоре агент вызывает инструменты бота: POST /voice/tools/slots и /voice/tools/book (заголовок X-Tool-Secret)
  — окна и запись те же, что в чате: календарь, напоминания, кнопка «Подтвердить».
  После звонка ElevenLabs присылает подписанный вебхук на /voice/webhook → итог в ветку карточки лида и следующий шаг.

Стадию лида звонок не меняет (человек может ответить в чате). Состояние звонка — в полях voice_*:
voice_conv — id текущего разговора; voice_next_at — когда проверить: итог не пришёл → «не дозвонились», либо повтор."""
import html
import logging
import re
from datetime import datetime, timedelta

from . import config, core, db, elevenlabs, slots
from .texts import WD, when

log = logging.getLogger("voice")
esc = html.escape

MANAGER, MANAGER_INS = "Даниил", "Даниилом"
OUTCOMES = {"booked", "callback", "manager_needed", "not_target", "do_not_call", "no_answer"}
LABELS = {"booked": "✅ записался на звонок", "callback": "⏰ просит перезвонить", "manager_needed": "🙋 нужен Даниил",
          "not_target": "🚫 не целевой", "do_not_call": "🔕 просит больше не звонить", "no_answer": "📵 не дозвонились"}
FAILURES = {"busy": "занято", "no-answer": "не взял трубку", "unknown": "звонок не прошёл"}
CLOSED = ("taken", "lost", "opted_out")       # лида ведёт человек или он закрыт — сами не звоним, стадию не трогаем
PHONE_RE = re.compile(r"^\+\d{10,15}$")
TG_LIMIT = 4000                               # сообщение Telegram — до 4096 символов
CLEAR = {"voice_conv": None, "voice_next_at": None}


def enabled() -> bool:
    return config.voice_enabled()


def can_call(lead: dict) -> bool:
    return (enabled() and bool(PHONE_RE.fullmatch(lead.get("phone") or "")) and lead.get("stage") not in CLOSED
            and not lead.get("voice_conv") and (lead.get("voice_tries") or 0) < config.VOICE_MAX_ATTEMPTS)


def _take_rows(lead: dict):
    return [[("🙋 Беру сам", f"g:take:{lead['id']}"), ("🚫 Не целевой", f"g:lost:{lead['id']}")]]


# ================================================================ звонок

async def call(lead: dict, reason: str, at: datetime | None = None) -> bool:
    """True — агент звонит. False — звонить нельзя или не получилось (ночь, нет номера, лимит попыток, ошибка
    ElevenLabs): вызывающий ставит обычную карточку «☎️ Позвонить»."""
    if not can_call(lead):
        return False
    at = at or db.now()
    if not slots.in_contact_hours(at) or await db.active_call(lead["id"]):
        return False
    payload = elevenlabs.call_payload(lead["phone"], lead_id=lead["id"], name=lead.get("name") or "",
                                      service=lead.get("service") or "", lang=core.lead_lang(lead), at=at,
                                      chat=await _chat(lead))
    try:
        conv = await elevenlabs.outbound_call(payload)
    except elevenlabs.ElevenLabsError as e:
        log.warning("лид %s: голосовой звонок не запустился: %s", lead["id"], e)
        await core.note(lead, f"⚠️ AI-звонок не запустился: {esc(str(e))}", silent=True)
        return False
    await db.update_lead(lead["id"], voice_conv=conv, voice_tries=(lead.get("voice_tries") or 0) + 1,
                         voice_at=db.iso(at),
                         voice_next_at=db.iso(at + timedelta(minutes=config.VOICE_RESULT_TIMEOUT_MIN)))
    log.info("лид %s: AI-звонок %s (%s)", lead["id"], conv, reason)
    return True


async def _chat(lead: dict, limit: int = 700) -> str:
    """Последние сообщения переписки с ботом — чтобы агент знал, о чём уже говорили."""
    who = {"in": "Лид", "out": "Бот"}
    text = "\n".join(f"{who.get(h['dir'], h['dir'])}: {' '.join(str(h['text'] or '').split())[:200]}"
                     for h in await db.history(lead["id"], 6))
    return text[-limit:]


async def manual(lead: dict, reason: str):
    """Обычная карточка «☎️ Позвонить вручную», когда голосом не вышло."""
    await db.update_lead(lead["id"], **CLEAR, **({} if lead.get("stage") in (*CLOSED, "booked") else
                                                 {"stage": "need_call", "next_at": None}))
    await core.note(lead, f"☎️ <b>Позвонить вручную</b>: {esc(reason)}\n📱 {esc(lead.get('phone') or lead.get('contact') or '—')}",
                    _take_rows(lead))


def _replied_since_call(lead: dict) -> bool:
    return bool(lead.get("last_in") and lead.get("voice_at") and lead["last_in"] > lead["voice_at"])


async def due(lead: dict, at: datetime):
    """Автоматика (scheduler): подошло voice_next_at — итог так и не пришёл, либо пора повторить звонок."""
    if lead.get("voice_conv"):
        return await _no_answer(lead, f"итог звонка не пришёл за {config.VOICE_RESULT_TIMEOUT_MIN} мин", at)
    if lead.get("stage") in CLOSED or await db.active_call(lead["id"]) or _replied_since_call(lead):
        await db.update_lead(lead["id"], **CLEAR)          # человек ответил в чате или его уже ведут — не звоним
        return
    if not slots.in_contact_hours(at):
        return await db.update_lead(lead["id"], voice_next_at=db.iso(slots.next_contact_time(at)))
    if await call(lead, "повторный звонок", at):
        tries = (await db.get_lead(lead["id"]))["voice_tries"]
        return await core.note(lead, f"🤖📞 <b>Повторный AI-звонок</b> (попытка {tries} из {config.VOICE_MAX_ATTEMPTS})"
                                     f"\n📱 {esc(lead.get('phone') or '')}", [[("🙋 Беру сам", f"g:take:{lead['id']}")]])
    await manual(await db.get_lead(lead["id"]), "AI не смог позвонить повторно")


async def _no_answer(lead: dict, why: str, at: datetime | None = None):
    at = at or db.now()
    tries = lead.get("voice_tries") or 0
    if enabled() and tries < config.VOICE_MAX_ATTEMPTS and not _replied_since_call(lead) \
            and lead.get("stage") not in CLOSED:
        nxt = at + timedelta(minutes=config.VOICE_RETRY_MIN)
        await db.update_lead(lead["id"], voice_conv=None, voice_next_at=db.iso(nxt))
        return await core.note(lead, f"📵 Не дозвонились ({esc(why)}). Повтор около {nxt:%H:%M}", silent=True)
    if lead.get("stage") in CLOSED or _replied_since_call(lead):
        return await db.update_lead(lead["id"], **CLEAR)
    await manual(lead, f"AI не дозвонился ({why}, попыток: {tries})")


# ================================================================ окна и запись (инструменты агента)

def _spread(ts: list, n: int) -> list:
    if len(ts) <= n:
        return ts
    return list(dict.fromkeys(ts[round(i * (len(ts) - 1) / (n - 1))] for i in range(n)))


async def slots_text(days: int = 3, per_day: int = 6) -> str:
    """Свободные окна текстом для голосового агента: коротко, чтобы не раздувать паузу перед ответом."""
    free = await slots.free()
    if not free:
        return f"Свободных окон в ближайшие дни нет. Скажи, что {MANAGER} напишет или перезвонит, чтобы согласовать время."
    lines = [f"{d.isoformat()} ({WD['ru'][d.weekday()]}): " + ", ".join(f"{x:%H:%M}" for x in _spread(ts, per_day))
             for d, ts in list(free.items())[:days]]
    return (f"Свободные окна для звонка с {MANAGER_INS} (время киевское):\n" + "\n".join(lines)
            + "\nДля записи вызови book_call с datetime в формате YYYY-MM-DDTHH:MM — только время из этого списка.")


async def book(lead: dict, raw_dt) -> tuple[bool, str]:
    """Запись на звонок по телефону через то же ядро, что и в чате."""
    if lead.get("stage") == "opted_out":
        return False, "Человек просил больше не звонить. Не записывай, вежливо заверши разговор."
    active = await db.active_call(lead["id"])
    if active:
        return True, (f"Человек уже записан: {when(datetime.fromisoformat(active['at']), 'ru')}. "
                      "Новую запись не создавай, просто напомни время.")
    at = slots.parse_any(str(raw_dt or ""))
    if not at:
        return False, "Неверный формат времени. Нужен YYYY-MM-DDTHH:MM из списка свободных окон."
    if not await slots.is_free(at):
        return False, f"Время {at:%Y-%m-%d %H:%M} недоступно. {await slots_text()}"
    if not await core.book(lead, at, "phone", lead.get("phone") or ""):
        return False, f"Не удалось записать: окно только что заняли. {await slots_text()}"
    return True, (f"Записано: {when(at, 'ru')} (время киевское). {MANAGER} позвонит на этот же номер. "
                  "Коротко повтори день и время, попрощайся и заверши звонок.")


# ================================================================ итог звонка

def _clean(v) -> str:
    s = str(v or "").strip()
    return "" if s.lower() in ("null", "none") else s


def _transcript(turns, limit: int) -> str:
    if limit < 200:
        return ""
    who = {"agent": "AI", "user": "Лид"}
    text = "\n".join(f"{who.get(t.get('role'), t.get('role') or '?')}: {_clean(t.get('message'))}"
                     for t in turns or [] if isinstance(t, dict) and _clean(t.get("message")))
    return ("…\n" + text[-limit:]) if len(text) > limit else text


def _report(lead: dict, outcome: str, r: dict) -> str:
    label = LABELS[outcome]
    if r.get("kind") == "failure":
        label += f" ({FAILURES.get(str(r.get('failure_reason')), 'звонок не прошёл')})"
    dur = r.get("duration")
    rows = [f"📞 <b>Итог AI-звонка</b>: {label}" + (f" · {int(dur) // 60}:{int(dur) % 60:02d}" if dur else "")]
    for key, icon in (("callback_time", "⏰ Перезвонить:"), ("for_manager", "❓"), ("business", "🏢"),
                      ("request", "🧩"), ("summary", "📝")):
        if _clean(r.get(key)):
            rows.append(f"{icon} {esc(_clean(r.get(key))[:400])}")
    tail = (f"🎧 Запись: ElevenLabs → Conversations, id <code>{esc(r['conversation_id'])}</code>"
            if r.get("conversation_id") else "")
    room = TG_LIMIT - len("\n".join(rows)) - len(tail) - len(str(lead.get("name") or "")) - 80
    tr = _transcript(r.get("transcript"), max(0, room // 2))          # esc() может удлинить текст до 2 раз
    if tr:
        rows.append(f"<blockquote expandable>{esc(tr)}</blockquote>")
    if tail:
        rows.append(tail)
    return "\n".join(rows)


async def on_result(r: dict) -> dict:
    """Итог звонка (см. elevenlabs.to_result). Повторная доставка того же звонка игнорируется."""
    conv = str(r.get("conversation_id") or "")
    if conv and await db.voice_event_seen(conv):
        return {"ok": True, "duplicate": True}
    lead = await db.lead_by_voice_conv(conv)
    if not lead and str(r.get("lead_id") or "").isdigit():
        lead = await db.get_lead(int(r["lead_id"]))
    if not lead:
        log.warning("итог звонка %s: лид не найден", conv)
        return {"ok": False, "error": "lead_not_found"}
    res = await _apply(lead, conv, r)
    if conv:                                     # только после успешной обработки
        await db.voice_event_mark(conv)
    return res


async def _apply(lead: dict, conv: str, r: dict) -> dict:
    outcome = "no_answer" if r.get("kind") == "failure" else _clean(r.get("outcome"))
    if outcome not in OUTCOMES:
        talked = any(isinstance(t, dict) and t.get("role") == "user" and _clean(t.get("message"))
                     for t in r.get("transcript") or [])
        outcome = "manager_needed" if talked else "no_answer"
    upd = {k: _clean(r.get(src))[:300] for k, src in (("biz", "business"), ("request", "request"))
           if _clean(r.get(src)) and not lead.get(k)}
    if upd:
        await db.update_lead(lead["id"], **upd)
    current = bool(conv) and lead.get("voice_conv") == conv

    if outcome == "do_not_call":                 # «Не звоните» = стоп: никаких звонков и автосообщений (гайд)
        await db.update_lead(lead["id"], stage="opted_out", next_at=None, silence_done=1, pending=None, **CLEAR)
        await core.note(lead, _report(lead, outcome, r))
        return {"ok": True, "outcome": outcome}
    if not current or lead.get("stage") in CLOSED:
        await core.note(lead, _report(lead, outcome, r), silent=True)      # поздний итог или лида ведёт человек
        return {"ok": True, "outcome": outcome, "stage_changed": False}

    if outcome == "booked" and not await db.active_call(lead["id"]):
        outcome = "manager_needed"
        r = {**r, "for_manager": "агент сказал, что записал, но записи нет — уточните время с лидом"}
    if outcome == "booked":
        await db.update_lead(lead["id"], **CLEAR)
        await core.note(lead, _report(lead, outcome, r), silent=True)
    elif outcome in ("callback", "manager_needed"):
        await db.update_lead(lead["id"], **CLEAR, **({} if lead.get("stage") == "booked" else
                                                     {"stage": "need_call", "next_at": None}))
        await core.note(lead, _report(lead, outcome, r), _take_rows(lead))
    elif outcome == "not_target":
        await db.update_lead(lead["id"], stage="lost", next_at=None, **CLEAR)
        await core.note(lead, _report(lead, outcome, r))
    else:                                         # no_answer: повтор или карточка «позвонить вручную»
        await core.note(lead, _report(lead, outcome, r), silent=True)
        await _no_answer(await db.get_lead(lead["id"]),
                         FAILURES.get(str(r.get("failure_reason")), "не ответил или автоответчик"))
    return {"ok": True, "outcome": outcome}
