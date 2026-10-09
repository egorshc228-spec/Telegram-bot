"""Конвертация файлов: проверка правил -> чтение в Doc -> запись в нужный формат."""
import logging
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.config import OUTPUT_DIR
from app.convert import render
from app.convert.readers import READERS
from app.convert.writers import write
from app.formats import AI_TABLE, TABLES, FormatError, no_tables_error, rule_for

log = logging.getLogger(__name__)

OFFICE_KINDS = {"docx", "xlsx", "pptx"}

__all__ = ["NeedsAI", "ConvResult", "convert", "new_job_dir", "safe_stem", "render"]


class NeedsAI(Exception):
    """Источник годится, но содержимое нужно достать с помощью Claude (изображение -> таблица)."""


@dataclass
class ConvResult:
    files: list[Path]
    notes: list[str] = field(default_factory=list)


def new_job_dir() -> Path:
    d = OUTPUT_DIR / uuid.uuid4().hex[:8]
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_stem(name: str) -> str:
    stem = re.sub(r"[^\w\-]+", "_", Path(name).stem, flags=re.UNICODE).strip("_")[:50]
    return stem or "file"


def _empty_error(kind: str) -> FormatError:
    if kind == "pdf":
        return FormatError("в PDF нет текста и таблиц (похоже, это скан). Отправьте его как изображение.")
    return FormatError("в файле не найдено содержимого, которое можно перенести.")


def convert(src: Path, kind: str, target: str, display_name: str | None = None) -> ConvResult:
    """Конвертирует src (вид kind) в target. Бросает FormatError, если нельзя."""
    name = display_name or src.name
    rule = rule_for(kind, target, name)
    if rule == AI_TABLE:
        raise NeedsAI()
    stem = safe_stem(name)
    job = new_job_dir()
    notes: list[str] = []

    # --- быстрые пути без модели документа ---
    if kind == "image" and target in ("png", "pdf"):
        try:
            img = Image.open(src)
            img.load()
        except Exception:
            raise FormatError("не удалось открыть изображение.")
        out = job / f"{stem}.{target}"
        if target == "png":
            img.save(out, "PNG")
        else:
            img.convert("RGB").save(out, "PDF", resolution=150)
        return ConvResult([out])

    if kind == "pdf" and target == "png":
        try:
            files, total = render.pdf_to_pngs(src, job, stem)
        except Exception:
            raise FormatError("PDF не открывается: он повреждён или защищён паролем.")
        if total > len(files):
            notes.append(f"Показаны первые {len(files)} страниц из {total}.")
        return ConvResult(files, notes)

    # --- Word/Excel/PowerPoint -> PDF/PNG через LibreOffice (точное оформление) ---
    if kind in OFFICE_KINDS and target in ("pdf", "png") and render.libreoffice_path():
        tmp = job / "_lo"
        try:
            pdf = render.office_to_pdf(src, tmp)
            if target == "pdf":
                out = job / f"{stem}.pdf"
                shutil.move(str(pdf), out)
                return ConvResult([out])
            files, total = render.pdf_to_pngs(pdf, job, stem)
            if kind == "xlsx":
                for f in files:
                    render.trim_whitespace(f)
            if total > len(files):
                notes.append(f"Показаны первые {len(files)} страниц из {total}.")
            return ConvResult(files, notes)
        except Exception as e:
            log.warning("LibreOffice не справился (%s), использую упрощённый путь", e)
            notes.append("Точное оформление недоступно, файл собран в упрощённом виде.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # --- общий путь: читаем в Doc и пишем в нужный формат ---
    doc = READERS[kind](src)
    if rule == TABLES and not doc.tables:
        raise no_tables_error(target, kind)
    if not doc.has_content:
        raise _empty_error(kind)
    files = write(doc, target, job, stem)
    if target == "png" and kind in ("xlsx", "csv"):
        for f in files:
            render.trim_whitespace(f)
    notes = doc.notes + notes
    if kind in OFFICE_KINDS and target in ("pdf", "png") and not render.libreoffice_path():
        notes.append("Оформление упрощено: на сервере не установлен LibreOffice.")
    return ConvResult(files, notes)
