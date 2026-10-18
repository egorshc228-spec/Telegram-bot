"""Настройки бота продаж ADrenaline. Всё задаётся переменными окружения (Railway → Variables).
Секреты (токены, ключи) — только в переменных, не в коде и не в чатах."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "")


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "sales.db"
TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")

# ---- Telegram: отдельный бот продаж (создаётся в @BotFather) ----
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@")      # если пусто — узнаём у Telegram при старте
# Группа «ADrenaline · Заявки» (отрицательный ID) или личный ID Даниила: карточки лидов, записи, ответы через бота
SALES_CHAT_ID = int(os.getenv("SALES_CHAT_ID") or 0)
# Кто ещё может жать кнопки карточек в личке с ботом (Telegram ID через запятую)
SALES_STAFF_IDS = {int(x) for x in os.getenv("SALES_STAFF_IDS", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()}
SALES_TG = os.getenv("SALES_TG", "conversion_wizard").lstrip("@")   # ник Даниила для кнопки «Написать напрямую»

# ---- ИИ ----
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")    # агент продаж: качество важнее копеек
AI_DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT") or 40)           # ответов ИИ одному лиду в сутки (защита баланса)

# ---- Приём заявок с сайта ----
# Общий секрет с Cloudflare (переменная SALES_BOT_SECRET там же): без него /api/lead не принимает заявки
LEAD_API_SECRET = os.getenv("LEAD_API_SECRET", "")
PORT = int(os.getenv("PORT") or 8080)
SITE_URL = os.getenv("SITE_URL", "https://adrenalinegrowth.com").rstrip("/")

# ---- WhatsApp Cloud API (Meta). Без WA_TOKEN и WA_PHONE_NUMBER_ID канал просто выключен ----
WA_TOKEN = os.getenv("WA_TOKEN", "")                     # постоянный токен системного пользователя Meta Business
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")  # ID номера в WhatsApp Manager (не сам номер)
WA_NUMBER = "".join(ch for ch in os.getenv("WA_NUMBER", "") if ch.isdigit())   # сам номер для ссылки wa.me, 380…
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "")       # любая строка; та же вписывается в настройках вебхука Meta
WA_APP_SECRET = os.getenv("WA_APP_SECRET", "")           # App secret приложения Meta: проверка подписи вебхука
WA_API_VERSION = os.getenv("WA_API_VERSION", "v23.0")
WA_TEMPLATE = os.getenv("WA_TEMPLATE", "lead_followup")  # утвержденный шаблон первого сообщения, {{1}} = имя
WA_TEMPLATE_LANGS = {k: v for k, v in (x.split(":", 1) for x in
                     os.getenv("WA_TEMPLATE_LANGS", "uk:uk,ru:ru").replace(" ", "").split(",") if ":" in x)}
WA_REMINDER_TEMPLATE = os.getenv("WA_REMINDER_TEMPLATE", "")   # шаблон напоминания о звонке ({{1}} имя, {{2}} время)

# ---- Окна для звонков с Даниилом ----
SALES_DAYS = os.getenv("SALES_DAYS", "1,2,3,4,5")          # 1 = понедельник
SALES_HOURS = os.getenv("SALES_HOURS", "10:00-19:00")
SALES_SLOT_MIN = int(os.getenv("SALES_SLOT_MIN") or 30)
CALL_MIN = int(os.getenv("CALL_MIN") or 20)                 # длительность звонка в календаре
SALES_DAYS_AHEAD = int(os.getenv("SALES_DAYS_AHEAD") or 7)
SALES_MIN_LEAD_HOURS = float(os.getenv("SALES_MIN_LEAD_HOURS") or 1)
MEET_URL = os.getenv("MEET_URL", "").strip()                # постоянная комната Google Meet Даниила

# ---- Google Calendar Даниила (необязательно): занятость и события звонков ----
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "")    # обычно email Даниила
try:
    GOOGLE_SERVICE_ACCOUNT = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or "{}")
except json.JSONDecodeError:
    GOOGLE_SERVICE_ACCOUNT = {}

# ---- Автоматика касаний ----
AUTOMATION = _flag("AUTOMATION")
TG_WAIT_MIN = int(os.getenv("TG_WAIT_MIN") or 3)          # ждём, не откроет ли человек Telegram/WhatsApp сам
NO_REPLY_MIN = int(os.getenv("NO_REPLY_MIN") or 20)       # нет ответа на WhatsApp → карточка «позвонить вручную»
NUDGE_HOURS = int(os.getenv("NUDGE_HOURS") or 20)          # общался, но не записался → одно напоминание
CONTACT_HOURS = os.getenv("CONTACT_HOURS", "09:00-20:00")  # сами пишем и просим позвонить только в эти часы
CHECK_SECONDS = int(os.getenv("CHECK_SECONDS") or 30)
# Бот написал в чате, человек молчит SILENCE_CALL_MIN минут → звонок (один раз на лида, только в CONTACT_HOURS).
# Пока голосового ИИ нет — карточка «☎️ Позвонить» в группу; без номера бот просит номер. 0 = выключить
SILENCE_CALL_MIN = int(os.getenv("SILENCE_CALL_MIN") if os.getenv("SILENCE_CALL_MIN") is not None else 30)

# ---- Голосовой ИИ (ElevenLabs, номер Zadarma). По умолчанию выключен: VOICE_CALLS=0 — вместо звонка карточка ----
# Включён: когда пора звонить (молчит после сообщения бота, нет ответа в WhatsApp, нет WhatsApp), звонит агент
# ElevenLabs. Он сам смотрит свободные окна и записывает на звонок через этого бота; итог приходит в группу.
VOICE_CALLS = os.getenv("VOICE_CALLS", "0").strip().lower() not in ("0", "false", "no", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")                 # ключ API (аккаунт компании)
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "")               # id агента «ADrenaline · обзвон заявок»
ELEVENLABS_PHONE_NUMBER_ID = os.getenv("ELEVENLABS_PHONE_NUMBER_ID", "") # id номера Zadarma, импортированного в ElevenLabs
ELEVENLABS_WEBHOOK_SECRET = os.getenv("ELEVENLABS_WEBHOOK_SECRET", "")   # секрет post-call webhook (подпись итога звонка)
ELEVENLABS_API_URL = os.getenv("ELEVENLABS_API_URL", "https://api.elevenlabs.io").rstrip("/")
VOICE_TOOL_SECRET = os.getenv("VOICE_TOOL_SECRET", "")    # заголовок X-Tool-Secret в инструментах агента
VOICE_LANGUAGE_OVERRIDE = os.getenv("VOICE_LANGUAGE_OVERRIDE", "0") == "1"   # 1 — лидам с /ru агент начинает по-русски
VOICE_RINGING_SECS = int(os.getenv("VOICE_RINGING_SECS") or 30)              # сколько ждать, пока возьмут трубку
VOICE_MAX_ATTEMPTS = int(os.getenv("VOICE_MAX_ATTEMPTS") or 2)               # звонок + один повтор (гайд)
VOICE_RETRY_MIN = int(os.getenv("VOICE_RETRY_MIN") or 30)                    # повтор, если не дозвонились
VOICE_RESULT_TIMEOUT_MIN = int(os.getenv("VOICE_RESULT_TIMEOUT_MIN") or 20)  # итог не пришёл — «не дозвонились»

# ---- GA4 Measurement Protocol (необязательно): call_booked к тому же посетителю сайта ----
GA4_MEASUREMENT_ID = os.getenv("GA4_MEASUREMENT_ID", "G-SB7Y07ZZB7")
GA4_API_SECRET = os.getenv("GA4_API_SECRET", "")


def wa_enabled() -> bool:
    return bool(WA_TOKEN and WA_PHONE_NUMBER_ID)


def gcal_enabled() -> bool:
    return bool(GOOGLE_CALENDAR_ID and GOOGLE_SERVICE_ACCOUNT.get("private_key"))


VOICE_REQUIRED = ("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID",
                  "ELEVENLABS_WEBHOOK_SECRET", "VOICE_TOOL_SECRET")


def voice_missing() -> list[str]:
    """Каких переменных не хватает голосовому ИИ. Без секретов агент не смог бы записать и прислать итог."""
    return [k for k in VOICE_REQUIRED if not globals().get(k)]


def voice_enabled() -> bool:
    return bool(VOICE_CALLS) and not voice_missing()
