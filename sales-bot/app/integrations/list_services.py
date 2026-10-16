"""Показывает услуги вашего филиала в Altegio, чтобы заполнить ALTEGIO_SERVICE_MAP.
Запуск: python -m app.integrations.list_services   (нужны ALTEGIO_PARTNER_TOKEN и ALTEGIO_LOCATION_ID)"""
import asyncio

from .. import config
from .altegio import AltegioProvider


async def main():
    p = AltegioProvider(config.ALTEGIO_PARTNER_TOKEN, config.ALTEGIO_LOCATION_ID)
    for sid, title in await p.list_services():
        print(f"{sid}\t{title}")


if __name__ == "__main__":
    asyncio.run(main())
