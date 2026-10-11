"""Выбор источника свободных слотов по настройке CRM_PROVIDER."""
from .. import config
from .base import Cached, SlotProvider, SlotsUnavailable
from .demo import DemoProvider

__all__ = ["get_provider", "init_provider", "set_provider", "SlotsUnavailable", "SlotProvider"]

_provider: SlotProvider | None = None

CLEVERBOX_NOTE = (
    "Cleverbox: публичной документации API найти не удалось, поэтому готового адаптера нет. "
    "Запросите у поддержки Cleverbox доступ к API и описание метода «свободные окна», затем используйте "
    "CRM_PROVIDER=generic (достаточно адреса, заголовков и пути к списку времени) или напишите отдельный адаптер."
)


def build_provider() -> SlotProvider:
    name = config.CRM_PROVIDER
    if name in ("", "demo"):
        return DemoProvider()
    if name == "altegio":
        from .altegio import AltegioProvider
        inner = AltegioProvider(config.ALTEGIO_PARTNER_TOKEN, config.ALTEGIO_LOCATION_ID,
                                config.ALTEGIO_STAFF_ID, config.ALTEGIO_SERVICE_MAP)
    elif name == "generic":
        from .generic import GenericProvider
        inner = GenericProvider(config.CRM_SLOTS_URL, config.CRM_HEADERS, config.CRM_SLOTS_PATH,
                                config.CRM_TIME_KEY, config.CRM_SERVICE_MAP)
    elif name == "cleverbox":
        raise ValueError(CLEVERBOX_NOTE)
    else:
        raise ValueError(f"неизвестный CRM_PROVIDER={name!r} (допустимо: demo, altegio, generic)")
    return Cached(inner, config.CRM_CACHE_SECONDS)


def init_provider() -> SlotProvider:
    global _provider
    _provider = build_provider()
    return _provider


def set_provider(p: SlotProvider):
    global _provider
    _provider = p


def get_provider() -> SlotProvider:
    global _provider
    if _provider is None:
        _provider = DemoProvider()
    return _provider
