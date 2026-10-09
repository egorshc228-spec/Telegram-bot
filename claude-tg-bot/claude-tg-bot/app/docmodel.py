"""Единая модель документа. Любой источник (Word, Excel, PDF, ответ Claude...)
читается в Doc, а из Doc пишется любой результат. Поэтому пар «из - в» много,
а кода конвертации мало.
"""
import re
from dataclasses import dataclass, field

MAX_TABLE_ROWS = 5000
MAX_COLS = 60


@dataclass
class Block:
    kind: str                       # h1 h2 h3 p bullet table image
    text: str = ""
    headers: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    image: bytes | None = None
    name: str = ""                  # имя таблицы/листа или подпись картинки


@dataclass
class Slide:
    layout: str = "bullets"         # title section bullets table image
    title: str = ""
    subtitle: str = ""
    bullets: list = field(default_factory=list)
    table: Block | None = None
    image: bytes | None = None
    notes: str = ""


@dataclass
class Design:
    """Оформление презентации. Пустые поля берутся из темы."""
    theme: str = "corporate_blue"
    accent: str | None = None       # hex без #
    background: str | None = None
    text_color: str | None = None
    font: str | None = None


@dataclass
class Doc:
    title: str = ""
    blocks: list[Block] = field(default_factory=list)
    slides: list[Slide] | None = None      # если заданы явно (презентация от Claude)
    design: Design = field(default_factory=Design)
    notes: list[str] = field(default_factory=list)   # предупреждения пользователю

    @property
    def tables(self) -> list[Block]:
        found = [b for b in self.blocks if b.kind == "table"]
        for s in self.slides or []:
            if s.table is not None:
                found.append(s.table)
        return found

    @property
    def has_content(self) -> bool:
        return bool(self.blocks or self.slides)


# ---------- таблицы ----------


def make_table(headers, rows, name: str = "") -> Block:
    headers = ["" if h is None else str(h) for h in (headers or [])][:MAX_COLS]
    clean = []
    for r in list(rows or [])[:MAX_TABLE_ROWS]:
        r = list(r) if isinstance(r, (list, tuple)) else [r]
        clean.append(r[:MAX_COLS])
    width = max([len(headers)] + [len(r) for r in clean] + [1])
    headers = headers + [""] * (width - len(headers))
    clean = [r + [None] * (width - len(r)) for r in clean]
    return Block(kind="table", headers=headers, rows=clean, name=name or "")


# ---------- markdown -> блоки ----------

_NUM = re.compile(r"^\s*\d+[.)]\s+")


def _is_sep_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells if c.strip()) and any(cells)


def markdown_to_blocks(content: str) -> list[Block]:
    """# заголовки, - списки, 1. нумерация, | таблицы |, **жирный**, абзацы."""
    blocks: list[Block] = []
    para: list[str] = []
    table_lines: list[str] = []

    def flush_para():
        if para:
            blocks.append(Block("p", " ".join(para).strip()))
            para.clear()

    def flush_table():
        if not table_lines:
            return
        rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in table_lines]
        rows = [r for r in rows if not _is_sep_row(r)]
        table_lines.clear()
        if len(rows) >= 1:
            blocks.append(make_table(rows[0], rows[1:]))

    for raw in (content or "").splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("|"):
            flush_para()
            table_lines.append(line)
            continue
        flush_table()
        if not line.strip():
            flush_para()
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            flush_para()
            blocks.append(Block(f"h{len(m.group(1))}", m.group(2).strip()))
            continue
        m = re.match(r"^\s*[-*•]\s+(.*)$", line)
        if m:
            flush_para()
            blocks.append(Block("bullet", m.group(1).strip()))
            continue
        if _NUM.match(line):          # каждый пункт нумерации — отдельная строка
            flush_para()
            blocks.append(Block("p", line.strip()))
            continue
        para.append(line.strip())
    flush_para()
    flush_table()
    return blocks


def strip_md(text: str) -> str:
    return text.replace("**", "")


def doc_to_markdown(doc: Doc, max_chars: int = 60000) -> str:
    """Текстовое представление документа для Claude (режим «задание по файлу»)."""
    out: list[str] = []
    if doc.title:
        out.append(f"# {doc.title}")
    blocks = list(doc.blocks)
    if not blocks and doc.slides:
        for i, s in enumerate(doc.slides, 1):
            out.append(f"## Слайд {i}: {s.title}")
            out += [f"- {b}" for b in s.bullets]
            if s.table is not None:
                blocks.append(s.table)
    for b in blocks:
        if b.kind in ("h1", "h2", "h3"):
            out.append("#" * int(b.kind[1]) + " " + b.text)
        elif b.kind == "bullet":
            out.append("- " + b.text)
        elif b.kind == "p":
            out.append(b.text)
        elif b.kind == "table":
            if b.name:
                out.append(f"Таблица «{b.name}»:")
            out.append("| " + " | ".join(map(str, b.headers)) + " |")
            for r in b.rows[:200]:
                out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
            if len(b.rows) > 200:
                out.append(f"... (ещё {len(b.rows) - 200} строк не показано)")
        elif b.kind == "image":
            out.append("[изображение]")
    text = "\n".join(out)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (текст обрезан)"
    return text


# ---------- блоки -> слайды (для конвертации в PowerPoint) ----------


def doc_to_slides(doc: Doc, bullets_per_slide: int = 6, rows_per_slide: int = 10) -> list[Slide]:
    if doc.slides:
        return doc.slides
    blocks = list(doc.blocks)
    title = doc.title
    if not title and blocks and blocks[0].kind == "h1":
        title = blocks.pop(0).text
    slides = [Slide(layout="title", title=title or "Презентация")]
    cur: Slide | None = None

    def start(t: str) -> Slide:
        s = Slide(layout="bullets", title=t)
        slides.append(s)
        return s

    for b in blocks:
        if b.kind in ("h1", "h2"):
            cur = start(strip_md(b.text))
        elif b.kind in ("h3", "p", "bullet"):
            if cur is None:
                cur = start(title or "Содержание")
            if len(cur.bullets) >= bullets_per_slide:
                cur = start(cur.title.removesuffix(" (продолжение)") + " (продолжение)")
            cur.bullets.append(strip_md(b.text))
        elif b.kind == "table":
            chunks = [b.rows[i:i + rows_per_slide] for i in range(0, max(len(b.rows), 1), rows_per_slide)]
            for n, chunk in enumerate(chunks, 1):
                label = b.name or (cur.title if cur else "") or "Таблица"
                if len(chunks) > 1:
                    label = f"{label} ({n}/{len(chunks)})"
                slides.append(Slide(layout="table", title=label, table=make_table(b.headers, chunk)))
            cur = None
        elif b.kind == "image":
            slides.append(Slide(layout="image", title=b.name, image=b.image))
            cur = None
    for s in slides:
        if s.layout == "bullets" and not s.bullets:
            s.layout = "section"
    return slides
