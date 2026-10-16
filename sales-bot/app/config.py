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


# ---- Режим и личный кабинет ----
# Какая компания по умолчанию (salon, auto, shop, dental)
DEFAULT_NICHE = os.getenv("DEFAULT_NICHE", "salon")
# 1 = демонстрация: можно переключать компании, есть команды /owner /report /how и приём заявок «хочу такого бота».
# 0 = рабочий режим для реального клиента (одна компания, без демо-команд)
DEMO_MODE = os.getenv("DEMO_MODE", "1").strip().lower() not in ("0", "false", "no", "")
# Программа лояльности в кабинете: каждый N-й визит со скидкой (0 = выключить)
LOYALTY_EVERY = int(os.getenv("LOYALTY_EVERY") or 5)
LOYALTY_DISCOUNT = int(os.getenv("LOYALTY_DISCOUNT") or 10)

# ---- Язык и напоминания ----
# Язык по умолчанию, пока клиент не выбрал свой (и если язык его Telegram не ru/uk/en): ru, uk или en
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "uk").strip().lower()
# Напоминания клиентам за сутки и за 2 часа до визита (0 = выключить)
REMINDERS_ENABLED = os.getenv("REMINDERS", "1").strip().lower() not in ("0", "false", "no", "")
REMINDER_CHECK_SECONDS = int(os.getenv("REMINDER_CHECK_SECONDS") or 300)

# ---- Воронка ADrenaline для демо (переход с сайта → демо → презентация → запись на звонок) ----
# Работает только в DEMO_MODE. FUNNEL=0 возвращает старое поведение демо.
FUNNEL_ENABLED = DEMO_MODE and os.getenv("FUNNEL", "1").strip().lower() not in ("0", "false", "no", "")
# Кому приходят записи на звонок и «горячие» посетители (Telegram ID Даниила). По умолчанию OWNER_ID
# Может быть и ID группы «Заявки» (отрицательное число): тогда карточки и кнопки живут в группе
SALES_CHAT_ID = int(os.getenv("SALES_CHAT_ID") or OWNER_ID or 0)
# Telegram ID людей ADrenaline, которым можно жать кнопки карточек и /funnel в личке (через запятую)
SALES_STAFF_IDS = {int(x) for x in os.getenv("SALES_STAFF_IDS", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()}
SALES_TG = os.getenv("SALES_TG", "conversion_wizard").lstrip("@")   # ник для кнопки «Написать Даниилу»
# Постоянная ссылка на комнату Google Meet Даниила (необязательно). Если задана, бот сам отправляет её клиенту
# при записи, в подтверждении и в напоминании; без неё Даниил отправляет ссылку вручную из карточки.
MEET_URL = os.getenv("MEET_URL", "").strip()
SITE_URL = os.getenv("SITE_URL", "https://adrenalinegrowth.com").rstrip("/")
# Окна для звонков: дни недели (1 = понедельник), часы, шаг, сколько дней вперёд показывать, минимум часов до звонка
SALES_DAYS = os.getenv("SALES_DAYS", "1,2,3,4,5")
SALES_HOURS = os.getenv("SALES_HOURS", "10:00-19:00")
SALES_SLOT_MIN = int(os.getenv("SALES_SLOT_MIN") or 30)
SALES_DAYS_AHEAD = int(os.getenv("SALES_DAYS_AHEAD") or 7)
SALES_MIN_LEAD_HOURS = float(os.getenv("SALES_MIN_LEAD_HOURS") or 2)
# Фоллоу-апы тем, кто не записался: задержки от последней активности (m/h/d), окно отправки по Киеву
FOLLOWUPS_ENABLED = os.getenv("FOLLOWUPS", "1").strip().lower() not in ("0", "false", "no", "")
FOLLOWUP_DELAYS = os.getenv("FOLLOWUP_DELAYS", "30m,1d,3d,7d")
FOLLOWUP_WINDOW = os.getenv("FOLLOWUP_WINDOW", "10-20")
FUNNEL_CHECK_SECONDS = int(os.getenv("FUNNEL_CHECK_SECONDS") or 60)
# Курс для сравнения «потери vs абонплата» в калькуляторе
USD_UAH = float(os.getenv("USD_UAH") or 41.5)
# GA4 Measurement Protocol: события воронки бота в ту же аналитику, что и сайт (необязательно)
# ID потока сайта adrenalinegrowth.com публичный и указан по умолчанию.
# Секрет НЕ хранится в коде: задаётся переменной GA4_API_SECRET в Railway. Без него события просто не отправляются.
GA4_MEASUREMENT_ID = os.getenv("GA4_MEASUREMENT_ID", "G-SB7Y07ZZB7")
GA4_API_SECRET = os.getenv("GA4_API_SECRET", "")
