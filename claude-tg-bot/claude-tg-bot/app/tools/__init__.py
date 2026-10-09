"""Реестр инструментов. Чтобы добавить свой: функция + JSON-схема + строка в HANDLERS и tools_for."""
from app.config import TAVILY_API_KEY
from app.tools import files, web
from app.tools.base import ToolContext

# Серверный веб-поиск Anthropic: Claude ищет сам, наш код его не вызывает.
SERVER_WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

HANDLERS = {
    "make_file": files.make_file,
    "reject_request": files.reject_request,
    "fetch_url": web.fetch_url,
}
if TAVILY_API_KEY:
    HANDLERS["web_search"] = web.web_search


def tools_for(target: str) -> list[dict]:
    """Набор инструментов зависит от выбранного формата ответа."""
    tools = [web.FETCH_SCHEMA, web.SEARCH_SCHEMA if TAVILY_API_KEY else SERVER_WEB_SEARCH]
    if target != "text":
        tools += [files.make_file_schema(target), files.REJECT_SCHEMA]
    return tools


__all__ = ["HANDLERS", "tools_for", "ToolContext"]
