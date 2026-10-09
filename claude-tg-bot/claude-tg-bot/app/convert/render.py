"""Рендер: офисный файл -> PDF (LibreOffice), PDF -> PNG-страницы (pdfium).

LibreOffice нужен для точной передачи оформления Word, Excel и PowerPoint.
Если его нет, конвертер использует упрощённый путь через модель документа.
"""
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_LO_LOCK = threading.Lock()      # LibreOffice плохо переносит параллельные запуски
LO_TIMEOUT = 180


def libreoffice_path() -> str | None:
    if os.getenv("DISABLE_LIBREOFFICE") == "1":
        return None
    return shutil.which("soffice") or shutil.which("libreoffice")


def office_to_pdf(src: Path, out_dir: Path) -> Path:
    exe = libreoffice_path()
    if not exe:
        raise RuntimeError("LibreOffice не найден")
    out_dir.mkdir(parents=True, exist_ok=True)
    with _LO_LOCK, tempfile.TemporaryDirectory() as profile:
        cmd = [
            exe, f"-env:UserInstallation=file://{profile}", "--headless", "--norestore",
            "--convert-to", "pdf", "--outdir", str(out_dir), str(src),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=LO_TIMEOUT, text=True)
        except subprocess.TimeoutExpired:
            raise RuntimeError("LibreOffice не успел за отведённое время")
    pdf = out_dir / (src.stem + ".pdf")
    if proc.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"LibreOffice не смог конвертировать: {proc.stderr[:200]}")
    return pdf


def trim_whitespace(path: Path, pad: int = 40) -> None:
    """Обрезает белые поля у PNG (для таблиц: маленькая таблица на целой странице A4 выглядит пусто)."""
    from PIL import Image, ImageChops

    with Image.open(path) as im:
        rgb = im.convert("RGB")
        bbox = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255))).getbbox()
        if not bbox:
            return
        box = (max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
               min(bbox[2] + pad, rgb.width), min(bbox[3] + pad, rgb.height))
        cropped = rgb.crop(box)
    cropped.save(path, format="PNG")


def pdf_to_pngs(pdf: Path, out_dir: Path, base: str, dpi: int = 130, max_pages: int = 10) -> tuple[list[Path], int]:
    """Возвращает (файлы PNG, всего страниц в PDF)."""
    import pypdfium2 as pdfium

    out_dir.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(pdf))
    try:
        total = len(document)
        files = []
        for i in range(min(total, max_pages)):
            page = document[i]
            img = page.render(scale=dpi / 72).to_pil().convert("RGB")
            name = f"{base}.png" if total == 1 else f"{base}_p{i + 1}.png"
            path = out_dir / name
            img.save(path, format="PNG")
            files.append(path)
            page.close()
        return files, total
    finally:
        document.close()
