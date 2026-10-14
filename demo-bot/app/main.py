import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from . import booking, config, db, funnel, i18n, reminders, sales
from .bot import router


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        sys.exit("Укажите TELEGRAM_BOT_TOKEN (в .env или в Variables на Railway)")
    if not config.ANTHROPIC_API_KEY:
        logging.warning("ANTHROPIC_API_KEY не задан: кнопки работают, ИИ-диалог и фото отключены")
    if config.FUNNEL_ENABLED:
        logging.info("Воронка ADrenaline включена: записи на звонок → %s", config.SALES_CHAT_ID or "не задан SALES_CHAT_ID")
    if not config.OWNER_ID:
        logging.warning("OWNER_ID не задан: вы не будете получать заявки и «Хочу такого бота»")
    await db.init_db()
    await sales.init()
    booking.setup()
    logging.info("Расписание: %s", booking.describe())
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(funnel.router)                          # воронка раньше основного: /start и её кнопки
    dp.include_router(router)
    for lang in i18n.LANGS:                                   # меню команд на языке интерфейса Telegram клиента
        cmds = list(i18n.COMMANDS[lang]) + (list(i18n.COMMANDS_DEMO[lang]) if config.DEMO_MODE else [])
        bc = [BotCommand(command=c, description=d) for c, d in cmds]
        await bot.set_my_commands(bc, language_code=lang)
        if lang == i18n.default_lang():
            await bot.set_my_commands(bc)
    task = asyncio.create_task(reminders.loop(bot)) if config.REMINDERS_ENABLED else None
    ftask = asyncio.create_task(funnel.loop(bot)) if config.FUNNEL_ENABLED else None
    logging.info("Start polling")
    try:
        await dp.start_polling(bot)
    finally:
        if task:
            task.cancel()
        if ftask:
            ftask.cancel()


if __name__ == "__main__":
    asyncio.run(main())
