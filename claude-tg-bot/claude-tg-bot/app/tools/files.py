"""Инструменты Claude для результата в файле: make_file и reject_request.

Формат файла выбирает пользователь (кнопкой), поэтому у make_file нет параметра
format: он зашит в запрос. Claude передаёт только содержимое.
"""
import asyncio

from app.convert import new_job_dir, safe_stem
from app.convert.writers import THEMES, make_chart_image, write
from app.docmodel import Block, Design, Doc, Slide, make_table, markdown_to_blocks
from app.formats import NAMES, FormatError
from app.tools.base import ToolContext

TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Название таблицы (в Excel это имя листа)"},
        "headers": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {"type": "array", "items": {}}},
    },
    "required": ["headers", "rows"],
}

CHART_SCHEMA = {
    "type": "object",
    "description": "График: bar (столбцы), line (линия) или pie (круговая)",
    "properties": {
        "type": {"type": "string", "enum": ["bar", "line", "pie"]},
        "labels": {"type": "array", "items": {"type": "string"}},
        "series": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["values"],
            },
        },
        "x_label": {"type": "string"},
        "y_label": {"type": "string"},
    },
    "required": ["labels", "series"],
}

CONTENT_SCHEMA = {
    "type": "string",
    "description": ("Текст в простом markdown: '# ' '## ' '### ' заголовки, '- ' списки, '1. ' нумерация, "
                    "**жирный**, абзацы через пустую строку, таблицы в виде | a | b |."),
}

ATTACHED_SCHEMA = {
    "type": "boolean",
    "description": "true, если фото пользователя из этого запроса нужно вставить в файл",
}

SLIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "layout": {"type": "string", "enum": ["title", "section", "bullets", "table", "image"],
                   "description": "title — титульный, section — разделитель, bullets — пункты, "
                                  "table — таблица, image — график (chart) или фото пользователя (attached_image)"},
        "title": {"type": "string"},
        "subtitle": {"type": "string", "description": "Только для title"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "table": TABLE_SCHEMA,
        "chart": CHART_SCHEMA,
        "attached_image": {"type": "integer", "description": "Номер (с 0) фото пользователя для слайда image"},
        "notes": {"type": "string", "description": "Заметки докладчика"},
    },
    "required": ["layout", "title"],
}

DESIGN_SCHEMA = {
    "type": "object",
    "description": "Оформление презентации. Заполняй по пожеланиям пользователя.",
    "properties": {
        "theme": {"type": "string", "enum": list(THEMES), "description": "Готовая тема оформления"},
        "accent_color": {"type": "string", "description": "Акцентный цвет, hex, например 2F5597"},
        "background_color": {"type": "string", "description": "Цвет фона слайдов, hex"},
        "text_color": {"type": "string", "description": "Цвет основного текста, hex"},
        "font": {"type": "string", "description": "Название шрифта, например Calibri, Arial, Georgia"},
    },
}


def make_file_schema(target: str) -> dict:
    props: dict = {
        "title": {"type": "string", "description": "Заголовок документа"},
        "filename": {"type": "string", "description": "Имя файла без расширения (по желанию)"},
    }
    required = ["title"]
    if target == "xlsx":
        props["tables"] = {"type": "array", "items": TABLE_SCHEMA,
                           "description": "Таблицы. Каждая таблица станет отдельным листом."}
        required.append("tables")
        what = "Excel-таблицу (.xlsx)"
    elif target == "pptx":
        props["slides"] = {"type": "array", "items": SLIDE_SCHEMA, "description": "Слайды по порядку"}
        props["design"] = DESIGN_SCHEMA
        required.append("slides")
        what = "презентацию PowerPoint (.pptx)"
    else:
        props["content"] = CONTENT_SCHEMA
        props["tables"] = {"type": "array", "items": TABLE_SCHEMA, "description": "Таблицы (выводятся после текста)"}
        props["chart"] = CHART_SCHEMA
        props["include_attached_images"] = ATTACHED_SCHEMA
        what = {"docx": "документ Word (.docx)", "pdf": "PDF-документ",
                "png": "картинку PNG (график или страницу с текстом и таблицами)"}[target]
    return {
        "name": "make_file",
        "description": f"Создаёт {what} и отправляет его пользователю. Вызывай один раз, когда данные собраны.",
        "input_schema": {"type": "object", "properties": props, "required": required},
    }


REJECT_SCHEMA = {
    "name": "reject_request",
    "description": ("Отказ: запрос нельзя разместить в выбранном формате файла (например, фото в Excel, "
                    "нетабличный текст в Excel, просьба создать или найти фотографию). Файл не создаётся. "
                    "Не используй, если запрос можно выполнить хотя бы частично."),
    "input_schema": {
        "type": "object",
        "properties": {"reason": {"type": "string", "description": "Одна короткая фраза на языке пользователя: почему нельзя"}},
        "required": ["reason"],
    },
}


# ---------- сборка Doc из аргументов Claude ----------


def _chart_block(chart: dict, title: str) -> Block:
    return Block("image", image=make_chart_image(chart, title), name="chart")


def _attached(ctx: ToolContext, idx: int | None = None) -> list[Block]:
    imgs = ctx.images if idx is None else ctx.images[idx:idx + 1]
    return [Block("image", image=b) for b in imgs]


def _design(raw: dict | None) -> Design:
    raw = raw or {}
    theme = raw.get("theme") if raw.get("theme") in THEMES else "corporate_blue"
    return Design(theme=theme, accent=raw.get("accent_color"), background=raw.get("background_color"),
                  text_color=raw.get("text_color"), font=raw.get("font"))


def _slide(ctx: ToolContext, s: dict, deck_title: str) -> Slide:
    layout = s.get("layout", "bullets")
    slide = Slide(layout=layout, title=s.get("title", ""), subtitle=s.get("subtitle", ""),
                  bullets=[str(b) for b in s.get("bullets", [])], notes=s.get("notes", ""))
    if layout == "table":
        t = s.get("table") or {}
        slide.table = make_table(t.get("headers"), t.get("rows"), t.get("name", ""))
        if not slide.table.headers or not slide.table.rows:
            slide.layout, slide.table = "bullets", None
    elif layout == "image":
        if s.get("chart"):
            slide.image = make_chart_image(s["chart"], s.get("title", ""))
        elif s.get("attached_image") is not None and 0 <= s["attached_image"] < len(ctx.images):
            slide.image = ctx.images[s["attached_image"]]
        if slide.image is None:
            slide.layout = "bullets"
    return slide


def build_doc(ctx: ToolContext, title: str, content: str | None = None, tables: list | None = None,
              chart: dict | None = None, slides: list | None = None, design: dict | None = None,
              include_attached_images: bool = False) -> Doc:
    target = ctx.target
    doc = Doc(title=title or "")
    if target == "xlsx":
        for i, t in enumerate(tables or [], 1):
            doc.blocks.append(make_table(t.get("headers"), t.get("rows"), t.get("name") or f"Таблица {i}"))
        if not doc.tables:
            raise FormatError("Excel принимает только таблицы, а в запросе таблицы получить нельзя.")
        return doc
    if target == "pptx":
        doc.design = _design(design)
        doc.slides = [_slide(ctx, s, title) for s in (slides or [])]
        if not doc.slides and content:
            doc.slides = None
            doc.blocks = markdown_to_blocks(content)
        if not doc.slides and not doc.blocks:
            raise ValueError("Нет слайдов: передай slides")
        return doc
    # docx, pdf, png
    doc.blocks = markdown_to_blocks(content or "")
    for i, t in enumerate(tables or [], 1):
        doc.blocks.append(make_table(t.get("headers"), t.get("rows"), t.get("name") or ""))
    if chart:
        doc.blocks.append(_chart_block(chart, title))
    if include_attached_images:
        doc.blocks += _attached(ctx)
    if not doc.blocks:
        raise ValueError("Файл пустой: передай content, tables или chart")
    return doc


def _build(ctx: ToolContext, args: dict) -> list:
    args = dict(args)
    filename = args.pop("filename", None)          # имя файла в build_doc не нужно
    doc = build_doc(ctx, **args)
    job = new_job_dir()
    stem = safe_stem(filename or args.get("title") or "file")
    files = write(doc, ctx.target, job, stem)
    ctx.notes.extend(doc.notes)
    return files


async def make_file(ctx: ToolContext, title: str, filename: str | None = None, content: str | None = None,
                    tables: list | None = None, chart: dict | None = None, slides: list | None = None,
                    design: dict | None = None, include_attached_images: bool = False, **_ignored) -> str:
    if ctx.target == "text":
        return "Пользователь выбрал ответ текстом, файлы создавать не нужно."
    args = dict(title=title, filename=filename, content=content, tables=tables, chart=chart,
                slides=slides, design=design, include_attached_images=include_attached_images)
    try:
        files = await asyncio.to_thread(_build, ctx, args)
    except FormatError as e:
        return (f"Недопустимо: {e.reason} Если запрос нельзя выполнить в формате {NAMES[ctx.target]}, "
                f"вызови reject_request.")
    except Exception as e:      # ошибка вернётся Claude, он может исправить вызов
        return f"Ошибка создания файла: {e}"
    ctx.files.extend(files)
    return f"Файл создан ({', '.join(p.name for p in files)}) и будет отправлен пользователю."


async def reject_request(ctx: ToolContext, reason: str) -> str:
    ctx.rejected = (reason or "запрос нельзя разместить в выбранном формате.").strip()
    return "Отказ принят."
