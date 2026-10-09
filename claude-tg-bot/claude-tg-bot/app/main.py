import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.bot import router
from app.cleanup import cleanup_loop
from app.config import ALLOWED_USER_IDS, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN
from app.convert.render import libreoffice_path
from app.core.memory import init_db


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not TELEGRAM_BOT_TOKEN or not ANTHROPIC_API_KEY:
        sys.exit("Заполните TELEGRAM_BOT_TOKEN и ANTHROPIC_API_KEY в файле .env")
    if not ALLOWED_USER_IDS:
        logging.warning("ALLOWED_USER_IDS пуст: бот отвечает ВСЕМ и тратит ваш баланс API")
    if not libreoffice_path():
        logging.warning("LibreOffice не найден: Word/Excel/PowerPoint -> PDF/PNG будут в упрощённом оформлении")

    await init_db()
    bot = Bot(TELEGRAM_BOT_TOKEN)
    await bot.set_my_commands([
        BotCommand(command="formats", description="Что в какой формат можно превратить"),
        BotCommand(command="reset", description="Очистить память диалога"),
        BotCommand(command="help", description="Как пользоваться"),
    ])
    dp = Dispatcher()
    dp.include_router(router)
    cleaner = asyncio.create_task(cleanup_loop())
    try:
        await dp.start_polling(bot)
    finally:
        cleaner.cancel()


if __name__ == "__main__":
    asyncio.run(main())
