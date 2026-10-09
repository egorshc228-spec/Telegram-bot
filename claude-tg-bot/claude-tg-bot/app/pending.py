"""Запросы, которые ждут выбора формата (нажатия кнопки). Хранятся в памяти процесса."""
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

TTL_SECONDS = 2 * 3600
MAX_ITEMS = 300


@dataclass
class Pending:
    user_id: int
    chat_id: int
    kind: str                                   # text | photo | file
    text: str = ""                              # текст запроса или подпись к файлу
    images: list[dict] = field(default_factory=list)   # блоки изображений для Claude
    path: Path | None = None                    # сохранённый файл
    src_kind: str | None = None                 # вид источника: docx, xlsx, pdf, image...
    filename: str = ""
    convert_mode: bool = False                  # файл без подписи -> просто конвертация
    token: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    created: float = field(default_factory=time.time)
    busy: bool = False


_items: dict[str, Pending] = {}


def _gc() -> None:
    now = time.time()
    for t in [t for t, p in _items.items() if now - p.created > TTL_SECONDS]:
        _items.pop(t, None)
    while len(_items) > MAX_ITEMS:
        _items.pop(next(iter(_items)))


def put(p: Pending) -> Pending:
    _gc()
    _items[p.token] = p
    return p


def get(token: str) -> Pending | None:
    _gc()
    return _items.get(token)
