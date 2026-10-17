"""Бот продаж: свободные окна, запись и итог звонка. Вся логика записи живёт в боте (одна на чат и голос),
сервис только передаёт запросы. Авторизация — общий секрет VOICE_SECRET в заголовке X-Voice-Secret."""
import asyncio
import logging

import httpx

from . import config

log = logging.getLogger("bot")
transport = None          # в тестах подменяется
RETRY_DELAYS = (2, 10, 30, 120)     # повторы доставки итога, секунды (бот мог перезапускаться)


class BotError(Exception):
    pass


async def post(path: str, body: dict, timeout: float = 8) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as c:
            r = await c.post(f"{config.SALES_BOT_URL}{path}", json=body,
                             headers={"X-Voice-Secret": config.VOICE_SECRET})
    except httpx.HTTPError as e:
        raise BotError(f"бот недоступен ({e.__class__.__name__})") from e
    try:
        d = r.json()
    except ValueError:
        d = {}
    if r.status_code in (401, 403) or r.status_code >= 500:
        raise BotError(f"бот ответил {r.status_code}")
    if not isinstance(d, dict):
        raise BotError("бот вернул не JSON")
    d["_status"] = r.status_code
    return d


async def send_result(result: dict) -> bool:
    """Доставляет итог звонка с повторами. 404 (лид не найден) не повторяем."""
    for i, delay in enumerate((0, *RETRY_DELAYS)):
        if delay:
            await asyncio.sleep(delay)
        try:
            d = await post("/api/voice/result", result, timeout=15)
            if d["_status"] == 404:
                log.warning("итог звонка %s: лид не найден в боте", result.get("conversation_id"))
                return False
            return True
        except BotError as e:
            log.warning("итог звонка %s не доставлен (попытка %s): %s", result.get("conversation_id"), i + 1, e)
    log.error("итог звонка %s потерян: бот недоступен. Сторож бота сам поставит повтор звонка.",
              result.get("conversation_id"))
    return False
