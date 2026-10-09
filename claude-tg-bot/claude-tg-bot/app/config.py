import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "outputs"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "bot.db"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
MEMORY_MESSAGES = int(os.getenv("MEMORY_MESSAGES", "30"))

ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()
}

MAX_TOOL_ROUNDS = 8          # защита от бесконечного цикла инструментов
MAX_IMAGE_SIDE = 1568        # крупнее Claude всё равно уменьшает
