"""Удаление старых загрузок и результатов (чужие файлы не должны копиться на диске)."""
import asyncio
import logging
import shutil
import time
from pathlib import Path

from app.config import OUTPUT_DIR, UPLOAD_DIR

log = logging.getLogger(__name__)

MAX_AGE_HOURS = 24


def cleanup_once(max_age_hours: float = MAX_AGE_HOURS) -> int:
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for base in (OUTPUT_DIR, UPLOAD_DIR):
        if not base.exists():
            continue
        for item in base.iterdir():
            if item.name.startswith("."):
                continue
            try:
                if item.stat().st_mtime < cutoff:
                    shutil.rmtree(item) if item.is_dir() else item.unlink()
                    removed += 1
            except OSError:
                log.exception("не удалось удалить %s", item)
    return removed


async def cleanup_loop(interval_seconds: int = 3600) -> None:
    while True:
        removed = await asyncio.to_thread(cleanup_once)
        if removed:
            log.info("очистка: удалено %d старых элементов", removed)
        await asyncio.sleep(interval_seconds)
