"""Поиск в интернете и чтение страниц.

Два режима поиска:
- есть TAVILY_API_KEY -> свой инструмент web_search через Tavily;
- ключа нет -> встроенный серверный web_search от Anthropic (см. tools/__init__.py).
"""
import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from app.config import TAVILY_API_KEY
from app.tools.base import ToolContext

MAX_PAGE_CHARS = 15000
MAX_REDIRECTS = 3
UA = {"User-Agent": "Mozilla/5.0 (compatible; ClaudeTelegramBot/1.0)"}


# ---------- поиск через Tavily ----------

SEARCH_SCHEMA = {
    "name": "web_search",
    "description": "Поиск в интернете. Возвращает список результатов: заголовок, ссылка, фрагмент.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}


async def web_search(ctx: ToolContext, query: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": query, "max_results": 6},
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            return f"Ошибка поиска: {e}"
    results = r.json().get("results", [])
    if not results:
        return "Ничего не найдено."
    return "\n\n".join(
        f"{i}. {x.get('title')}\n{x.get('url')}\n{(x.get('content') or '')[:500]}"
        for i, x in enumerate(results, 1)
    )


# ---------- чтение страницы ----------

FETCH_SCHEMA = {
    "name": "fetch_url",
    "description": "Скачивает веб-страницу по ссылке и возвращает её текст (без HTML).",
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
}


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip() + " ")


def _is_public_host(host: str) -> bool:
    """Защита от SSRF: не ходим на localhost, внутренние сети и метаданные облака."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return False
    return True


async def fetch_url(ctx: ToolContext, url: str) -> str:
    async with httpx.AsyncClient(timeout=20, headers=UA, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            p = urlparse(url)
            if p.scheme not in ("http", "https") or not p.hostname:
                return "Ошибка: поддерживаются только ссылки http и https."
            if not await asyncio.to_thread(_is_public_host, p.hostname):
                return "Ошибка: этот адрес недоступен."
            try:
                r = await client.get(url)
            except httpx.HTTPError as e:
                return f"Ошибка загрузки: {e}"
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            break
        else:
            return "Ошибка: слишком много перенаправлений."

    if r.status_code >= 400:
        return f"Ошибка: сайт ответил кодом {r.status_code}."
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        return f"Ошибка: тип содержимого {ctype} не поддерживается."
    parser = _TextExtractor()
    parser.feed(r.text)
    text = re.sub(r"\n\s*\n+", "\n", "".join(parser.parts)).strip()
    return text[:MAX_PAGE_CHARS] or "Страница пустая."
