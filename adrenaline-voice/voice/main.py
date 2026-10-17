import asyncio
import logging

from aiohttp import web

from . import config
from . import web as http


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if config.missing():
        logging.warning("Не заданы переменные: %s — звонки не пойдут (см. README)", ", ".join(config.missing()))
    runner = web.AppRunner(http.app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    logging.info("adrenaline-voice на порту %s: /call, /tools/slots, /tools/book, /webhooks/elevenlabs, /health",
                 config.PORT)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
