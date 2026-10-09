"""Форматы и правила допустимости: что в какой формат можно превратить.

Это единственное место, где задана матрица «источник -> результат». Хотите
ужесточить или расширить правила, правьте RULES ниже.
"""
from pathlib import Path

# Порядок кнопок в Telegram
TARGETS = ["xlsx", "docx", "pptx", "pdf", "png"]

LABELS = {
    "text": "💬 Текст",
    "xlsx": "📊 Excel",
    "docx": "📝 Word",
    "pptx": "📽 PowerPoint",
    "pdf": "📄 PDF",
    "png": "🖼 PNG",
}
NAMES = {"xlsx": "Excel", "docx": "Word", "pptx": "PowerPoint", "pdf": "PDF", "png": "PNG", "text": "текст"}

# Расширение -> вид источника
EXT_KIND = {
    ".docx": "docx", ".xlsx": "xlsx", ".csv": "csv", ".pptx": "pptx", ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".txt": "txt", ".md": "txt",
}
KIND_NAMES = {
    "docx": "документ Word", "xlsx": "таблица Excel", "csv": "CSV-таблица", "pptx": "презентация",
    "pdf": "PDF", "image": "изображение", "txt": "текстовый файл",
}

# Что должно быть в источнике, чтобы он подошёл
OK = "ok"                # можно всегда
TABLES = "tables"        # можно, только если в файле есть таблицы
AI_TABLE = "ai_table"    # изображение: таблицу достаёт Claude, если её нет — отказ

_ALL = ["docx", "xlsx", "csv", "pptx", "pdf", "image", "txt"]

RULES: dict[str, dict[str, str]] = {
    # Word: принимает всё
    "docx": {k: OK for k in _ALL if k != "docx"},
    # PowerPoint: принимает всё
    "pptx": {k: OK for k in _ALL if k != "pptx"},
    # Excel: только таблицы
    "xlsx": {"csv": OK, "docx": TABLES, "pptx": TABLES, "pdf": TABLES, "image": AI_TABLE},
    # PDF: Word, PNG (изображения), Excel (+ презентации, CSV, текст)
    "pdf": {k: OK for k in _ALL if k != "pdf"},
    # PNG: изображения, Word, PDF, Excel (+ презентации, CSV, текст)
    "png": {k: OK for k in _ALL},
}

REASONS = {
    ("xlsx", "txt"): "Excel принимает только таблицы, а в текстовом файле таблиц нет.",
}


class FormatError(Exception):
    """Запрос нельзя разместить в выбранном формате."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

    def user_message(self) -> str:
        return f"❌ Недопустимый файл к вашему запросу: {self.reason}"


def kind_of(filename: str) -> str | None:
    return EXT_KIND.get(Path(filename).suffix.lower())


def rule_for(kind: str, target: str, filename: str = "") -> str:
    """Возвращает OK / TABLES / AI_TABLE или бросает FormatError."""
    ext = Path(filename).suffix.lower().lstrip(".")
    if kind == target or (kind == "image" and target == "png" and ext == "png"):
        raise FormatError(f"файл уже в формате {NAMES[target]}.")
    rule = RULES.get(target, {}).get(kind)
    if rule is None:
        reason = REASONS.get((target, kind)) or (
            f"{NAMES[target]} не принимает {KIND_NAMES.get(kind, kind)}."
        )
        raise FormatError(reason)
    return rule


def no_tables_error(target: str, kind: str) -> FormatError:
    return FormatError(
        f"{NAMES[target]} принимает только таблицы, а в этом файле "
        f"({KIND_NAMES.get(kind, kind)}) таблиц не найдено."
    )
