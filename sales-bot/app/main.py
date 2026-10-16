import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

from . import config, core, db, scheduler
from . import web as http
from .tg import router


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        sys.exit("Укажите TELEGRAM_BOT_TOKEN бота продаж (Railway → Variables)")
    for name, ok in (("ANTHROPIC_API_KEY", config.ANTHROPIC_API_KEY), ("SALES_CHAT_ID", config.SALES_CHAT_ID),
                     ("LEAD_API_SECRET", config.LEAD_API_SECRET)):
        if not ok:
            logging.warning("%s не задан — часть функций выключена (см. README)", name)
    logging.info("WhatsApp: %s · Google Calendar: %s · автоматика: %s",
                 "вкл" if config.wa_enabled() else "выкл", "вкл" if config.gcal_enabled() else "выкл",
                 "вкл" if config.AUTOMATION else "выкл")
    await db.init()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    core.bot = bot
    core.bot_username = config.BOT_USERNAME or (await bot.get_me()).username
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    runner = web.AppRunner(http.app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    logging.info("HTTP на порту %s: /api/lead, /wa/webhook, /health · бот @%s", config.PORT, core.bot_username)
    task = asyncio.create_task(scheduler.loop())
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
