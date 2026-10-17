"""Настройки сервиса adrenaline-voice. Всё задаётся переменными окружения (Railway → Variables).
Секреты (ключи, токены) — только в переменных: не в коде, не в Telegram, не на скриншотах. Список — в README."""
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "")


# ---- ElevenLabs ----
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")               # ключ API (Developers → API Keys)
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "")             # id агента «ADrenaline · обзвон заявок»
ELEVENLABS_PHONE_NUMBER_ID = os.getenv("ELEVENLABS_PHONE_NUMBER_ID", "")   # id номера Zadarma, импортированного в ElevenLabs
ELEVENLABS_WEBHOOK_SECRET = os.getenv("ELEVENLABS_WEBHOOK_SECRET", "")     # секрет post-call webhook (подпись запросов)
ELEVENLABS_API_URL = os.getenv("ELEVENLABS_API_URL", "https://api.elevenlabs.io").rstrip("/")
RINGING_TIMEOUT_SECS = int(os.getenv("RINGING_TIMEOUT_SECS") or 30)    # сколько гудков ждать, пока возьмут трубку
# 1 — для лидов с русских страниц сайта агент начинает по-русски. Нужно разрешить переопределение языка в агенте
# (Security → Overrides → Language), иначе ElevenLabs отклонит звонок. 0 — всегда начинает по-украински.
LANGUAGE_OVERRIDE = _flag("LANGUAGE_OVERRIDE", "0")

# ---- Бот продаж ----
SALES_BOT_URL = os.getenv("SALES_BOT_URL", "").strip().rstrip("/")     # адрес бота продаж на Railway
VOICE_SECRET = os.getenv("VOICE_SECRET", "")       # общий секрет с ботом: то же значение, что VOICE_SECRET в боте
TOOL_SECRET = os.getenv("TOOL_SECRET", "")         # секрет инструментов агента (заголовок X-Tool-Secret в ElevenLabs)

MANAGER_NAME = os.getenv("MANAGER_NAME") or "Даниил"   # как агенту называть менеджера в подсказках

# ---- Правила звонков (гайд: только 09:00–20:00, как CONTACT_HOURS у бота) ----
TIMEZONE = os.getenv("TIMEZONE") or "Europe/Kyiv"
TZ = ZoneInfo(TIMEZONE)
CONTACT_HOURS = os.getenv("CONTACT_HOURS") or "09:00-20:00"
PORT = int(os.getenv("PORT") or 8080)

REQUIRED = ("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID", "ELEVENLABS_WEBHOOK_SECRET",
            "SALES_BOT_URL", "VOICE_SECRET", "TOOL_SECRET")


def missing() -> list[str]:
    """Обязательные переменные, которые не заданы."""
    return [name for name in REQUIRED if not globals().get(name)]
