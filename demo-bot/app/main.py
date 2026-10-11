import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from . import booking, config, db
from .bot import router


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        sys.exit("Укажите TELEGRAM_BOT_TOKEN (в .env или в Variables на Railway)")
    if not config.ANTHROPIC_API_KEY:
        logging.warning("ANTHROPIC_API_KEY не задан: кнопки работают, ИИ-диалог и фото отключены")
    if not config.OWNER_ID:
        logging.warning("OWNER_ID не задан: вы не будете получать заявки и «Хочу такого бота»")
    await db.init_db()
    booking.setup()
    logging.info("Расписание: %s", booking.describe())
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="how", description="Как это работает"),
    ])
    logging.info("Start polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
