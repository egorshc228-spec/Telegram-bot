import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Haiku дешевле всех и для демо хватает
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Ваш Telegram ID: сюда приходят все заявки демо и просьбы «хочу такого бота»
OWNER_ID = int(os.getenv("OWNER_ID") or 0)

# Защита баланса API: сообщений ИИ на человека в сутки и всего в сутки
USER_DAILY_LIMIT = int(os.getenv("USER_DAILY_LIMIT") or 15)
GLOBAL_DAILY_LIMIT = int(os.getenv("GLOBAL_DAILY_LIMIT") or 300)

TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")
DB_PATH = DATA_DIR / "demo.db"

# ---- Интеграция с CRM / онлайн-записью (свободные слоты) ----
# demo — условное расписание из niches.py; altegio — настоящее расписание Altegio; generic — любая CRM по HTTP
CRM_PROVIDER = os.getenv("CRM_PROVIDER", "demo").strip().lower()
CRM_CACHE_SECONDS = int(os.getenv("CRM_CACHE_SECONDS") or 60)

# Altegio (бывш. YCLIENTS)
ALTEGIO_PARTNER_TOKEN = os.getenv("ALTEGIO_PARTNER_TOKEN", "")
ALTEGIO_LOCATION_ID = os.getenv("ALTEGIO_LOCATION_ID", "")
ALTEGIO_STAFF_ID = int(os.getenv("ALTEGIO_STAFF_ID") or 0)          # 0 = любой мастер
ALTEGIO_SERVICE_MAP = os.getenv("ALTEGIO_SERVICE_MAP", "")          # JSON: {"Название в прайсе": id_услуги_в_Altegio}

# Универсальный HTTP-адаптер для другой CRM
CRM_SLOTS_URL = os.getenv("CRM_SLOTS_URL", "")                      # например https://crm.example.com/api/slots?date={date}&service={service_id}
CRM_HEADERS = os.getenv("CRM_HEADERS", "")                          # JSON: {"Authorization": "Bearer ..."}
CRM_SLOTS_PATH = os.getenv("CRM_SLOTS_PATH", "data")                # где в JSON список слотов ("" = корень), через точку
CRM_TIME_KEY = os.getenv("CRM_TIME_KEY", "time")                    # ключ времени, если слоты объектами
CRM_SERVICE_MAP = os.getenv("CRM_SERVICE_MAP", "")                  # JSON: {"Название в прайсе": "id в CRM"}
