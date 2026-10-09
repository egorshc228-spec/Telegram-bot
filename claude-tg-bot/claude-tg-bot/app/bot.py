"""Telegram-часть: приём запросов, выбор формата кнопкой, конвертация файлов."""
import asyncio
import io
import logging
import re
import uuid
from pathlib import Path

import anthropic
from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.chat_action import ChatActionSender

from app import pending
from app.config import ALLOWED_USER_IDS, UPLOAD_DIR
from app.convert import NeedsAI, convert, render, safe_stem
from app.convert.readers import READERS
from app.core import memory
from app.core.agent import run_agent
from app.docmodel import doc_to_markdown
from app.formats import KIND_NAMES, LABELS, NAMES, FormatError, kind_of
from app.media.images import image_block
from app.pending import Pending

log = logging.getLogger(__name__)
router = Router()

TG_LIMIT = 4000                       # у Telegram предел 4096 символов, берём с запасом
MAX_DOWNLOAD = 20 * 1024 * 1024       # бот не может скачать файл больше 20 МБ
MAX_SEND = 49 * 1024 * 1024           # и отправить больше 50 МБ

HELP = (
    "Я ассистент на Claude: отвечаю, ищу в интернете, анализирую фото и файлы и "
    "присылаю результат в нужном формате.\n\n"
    "Как пользоваться:\n"
    "1. Напишите запрос. Я спрошу, в каком формате прислать: текст, Excel, Word, PowerPoint, PDF или PNG.\n"
    "   Быстрее: начните сообщение с формата, например «/xlsx сравни цены на ноутбуки».\n"
    "2. Фото или файл с подписью: подпись станет заданием («сделай краткий конспект»), результат придёт в выбранном формате.\n"
    "3. Фото или файл без подписи: конвертация. Выберите формат, в который перенести.\n\n"
    "Принимаю файлы: docx, xlsx, csv, pptx, pdf, txt, png, jpg, webp (до 20 МБ).\n"
    "Для презентаций можно задать оформление словами: «тёмная тема», «акцентный цвет #D9480F», «шрифт Georgia».\n\n"
    "/formats — что в какой формат можно\n"
    "/reset — очистить память диалога"
)

FORMATS_HELP = (
    "Что в какой формат можно превратить:\n\n"
    "📊 Excel — только таблицы: из CSV, Word, PowerPoint и PDF с таблицами, из фото таблицы. "
    "Фото без таблицы, рассказ или эссе в Excel нельзя.\n"
    "📝 Word — любые запросы и файлы (в том числе презентации, PDF, таблицы, изображения).\n"
    "📽 PowerPoint — любые запросы и файлы. Оформление задаётся словами в запросе.\n"
    "📄 PDF — Word, Excel, PowerPoint, изображения, текст, CSV.\n"
    "🖼 PNG — изображения, Word, PDF, Excel, PowerPoint (страницы как картинки, до 10 шт.), "
    "графики и страницы с текстом по запросу.\n\n"
    "Если содержимое не подходит, я отвечу: «❌ Недопустимый файл к вашему запросу: …»."
)

_ALIASES = {"txt": "text", "excel": "xlsx", "word": "docx", "ppt": "pptx", "powerpoint": "pptx"}
_PREFIX = re.compile(r"^\s*[/#](text|txt|xlsx|excel|docx|word|pptx|ppt|powerpoint|pdf|png)(?:@\w+)?\b[:,]?\s*", re.I)


def split_prefix(text: str) -> tuple[str | None, str]:
    """'/xlsx сравни цены' -> ('xlsx', 'сравни цены'). Без префикса -> (None, text)."""
    m = _PREFIX.match(text or "")
    if not m:
        return None, (text or "").strip()
    fmt = m.group(1).lower()
    return _ALIASES.get(fmt, fmt), text[m.end():].strip()


# ---------- доступ ----------


class AccessMiddleware(BaseMiddleware):
    """Пускает только пользователей из ALLOWED_USER_IDS (если список задан)."""

    async def __call__(self, handler, event, data):
        user = event.from_user
        if ALLOWED_USER_IDS and (user is None or user.id not in ALLOWED_USER_IDS):
            note = f"Нет доступа. Ваш ID: {user.id if user else '?'}"
            if isinstance(event, CallbackQuery):
                await event.answer(note, show_alert=True)
            else:
                await event.answer(note)
            return None
        return await handler(event, data)


router.message.middleware(AccessMiddleware())
router.callback_query.middleware(AccessMiddleware())


# ---------- кнопки ----------


def keyboard(p: Pending) -> InlineKeyboardMarkup:
    def btn(fmt: str, label: str | None = None):
        return InlineKeyboardButton(text=label or LABELS[fmt], callback_data=f"f:{p.token}:{fmt}")

    rows = []
    if not p.convert_mode:
        rows.append([btn("text")])
    rows += [[btn("xlsx"), btn("docx")], [btn("pptx"), btn("pdf")], [btn("png")]]
    if p.convert_mode:
        rows.append([btn("describe", "💬 Описать фото" if p.kind == "photo" else "💬 Кратко пересказать")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def question_for(p: Pending) -> str:
    if p.convert_mode:
        what = KIND_NAMES.get(p.src_kind or "", "файл")
        return f"Получил: {p.filename} ({what}). В какой формат конвертировать?"
    if p.kind == "text":
        return "В каком формате прислать ответ?"
    return "Задание принято. В каком формате прислать результат?"


# ---------- отправка ----------


def _chunks(text: str, size: int = TG_LIMIT):
    while text:
        if len(text) <= size:
            yield text
            return
        cut = text.rfind("\n", 0, size)
        cut = cut if cut > size // 2 else size
        yield text[:cut]
        text = text[cut:].lstrip("\n")


async def send_result(reply: Message, text: str, files: list[Path], notes: list[str]) -> None:
    for part in _chunks(text or ""):
        await reply.answer(part)
    for f in files:
        if f.stat().st_size > MAX_SEND:
            await reply.answer(f"Файл {f.name} слишком большой для отправки в Telegram (больше 50 МБ).")
            continue
        await reply.answer_document(FSInputFile(f))
    if notes:
        await reply.answer("ℹ️ " + "\n".join(dict.fromkeys(notes)))


# ---------- выполнение ----------

DEFAULT_DESCRIBE = {"photo": "Опиши это фото.", "file": "Кратко перескажи содержимое файла."}
TABLE_FROM_IMAGE = (
    "Извлеки с изображения таблицу (или несколько) и создай Excel-файл: сохрани заголовки, порядок "
    "строк и числа как есть. Если на изображении нет таблицы или табличных данных, вызови reject_request."
)


def file_context(p: Pending) -> tuple[str, list[dict]]:
    """Содержимое присланного файла для Claude: текст и, для сканов PDF, картинки страниц."""
    doc = READERS[p.src_kind](p.path)
    md = doc_to_markdown(doc)
    images: list[dict] = []
    if not md.strip() and p.src_kind == "pdf":
        tmp = p.path.parent / "_scan"
        files, _ = render.pdf_to_pngs(p.path, tmp, "page", dpi=110, max_pages=3)
        images = [image_block(f.read_bytes()) for f in files]
    if not md.strip() and not images:
        raise FormatError("в файле не найдено содержимого, с которым можно работать.")
    return md, images


async def run_task(reply: Message, p: Pending, target: str, instruction: str | None = None) -> None:
    """Задание для Claude (запрос, фото или файл + подпись) с результатом в формате target."""
    text = instruction if instruction is not None else p.text
    images = list(p.images)
    memory_text = None
    if p.kind == "file":
        try:
            md, extra = await asyncio.to_thread(file_context, p)
        except FormatError as e:
            await reply.answer(e.user_message())
            return
        images += extra
        body = md or "(страницы файла приложены как изображения)"
        text = f"{text}\n\n[Содержимое файла «{p.filename}»]\n{body}"
        memory_text = f"{instruction if instruction is not None else p.text} [файл: {p.filename}]"
    result = await run_agent(p.user_id, text, images, target, memory_text)
    await send_result(reply, result.text, result.files, result.notes)


async def run_convert(reply: Message, p: Pending, target: str) -> None:
    """Чистая конвертация файла без вопросов к Claude (кроме изображения -> Excel)."""
    try:
        res = await asyncio.to_thread(convert, p.path, p.src_kind, target, p.filename)
    except NeedsAI:
        result = await run_agent(p.user_id, TABLE_FROM_IMAGE, p.images, "xlsx",
                                 memory_text="[конвертация изображения в Excel]")
        await send_result(reply, result.text, result.files, result.notes)
        return
    except FormatError as e:
        await reply.answer(e.user_message())
        return
    await send_result(reply, f"✅ Готово: {p.filename} → {NAMES[target]}", res.files, res.notes)


async def dispatch(bot: Bot, reply: Message, p: Pending, fmt: str) -> None:
    """Запускает запрос в выбранном формате. fmt: text|xlsx|docx|pptx|pdf|png|describe."""
    p.busy = True
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=p.chat_id):
            if p.convert_mode and fmt in ("describe", "text"):
                await run_task(reply, p, "text", DEFAULT_DESCRIBE[p.kind])
            elif p.convert_mode:
                await run_convert(reply, p, fmt)
            else:
                await run_task(reply, p, fmt)
    except anthropic.RateLimitError:
        await reply.answer("Слишком много запросов к Claude. Подождите минуту и повторите.")
    except anthropic.APIStatusError as e:
        log.exception("Anthropic API error")
        await reply.answer(f"Ошибка Claude API ({e.status_code}). Проверьте ключ и баланс.")
    except Exception:
        log.exception("Unexpected error")
        await reply.answer("Что-то пошло не так. Попробуйте ещё раз.")
    finally:
        p.busy = False


# ---------- команды ----------


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP)


@router.message(Command("formats"))
async def cmd_formats(message: Message):
    await message.answer(FORMATS_HELP)


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    await memory.clear_history(message.from_user.id)
    await message.answer("Память диалога очищена.")


# ---------- выбор формата ----------


@router.callback_query(F.data.startswith("f:"))
async def on_format(cb: CallbackQuery, bot: Bot):
    _, token, fmt = cb.data.split(":", 2)
    p = pending.get(token)
    if p is None:
        await cb.answer("Запрос устарел, отправьте его заново.", show_alert=True)
        return
    if cb.from_user.id != p.user_id:
        await cb.answer("Это чужой запрос.", show_alert=True)
        return
    if p.busy:
        await cb.answer("Уже обрабатываю, подождите…")
        return
    await cb.answer("Готовлю: " + (NAMES.get(fmt) or "ответ"))
    await dispatch(bot, cb.message, p, fmt)


# ---------- входящие сообщения ----------


async def _save_upload(bot: Bot, file_obj, filename: str) -> Path:
    folder = UPLOAD_DIR / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (safe_stem(filename) + Path(filename).suffix.lower())
    await bot.download(file_obj, destination=path)
    return path


async def _accept(message: Message, bot: Bot, p: Pending, caption: str) -> None:
    """Общая логика для фото и файлов: подпись -> задание, нет подписи -> конвертация."""
    fmt, rest = split_prefix(caption)
    p.text = rest if fmt else (caption or "").strip()
    p.convert_mode = not p.text
    pending.put(p)
    if fmt:
        await dispatch(bot, message, p, fmt)
    else:
        await message.answer(question_for(p), reply_markup=keyboard(p))


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot):
    path = await _save_upload(bot, message.photo[-1], "photo.jpg")
    block = image_block(path.read_bytes())
    p = Pending(user_id=message.from_user.id, chat_id=message.chat.id, kind="photo", images=[block],
                path=path, src_kind="image", filename="photo.jpg")
    await _accept(message, bot, p, message.caption or "")


@router.message(F.document)
async def on_document(message: Message, bot: Bot):
    doc = message.document
    name = doc.file_name or ""
    kind = kind_of(name) if name else None
    if kind is None and (doc.mime_type or "").startswith("image/"):
        name = "image" + {"image/png": ".png", "image/webp": ".webp"}.get(doc.mime_type, ".jpg")
        kind = "image"
    if kind is None:
        await message.answer("Этот тип файла не поддерживается. Принимаю: docx, xlsx, csv, pptx, pdf, txt, png, jpg, webp.")
        return
    if doc.file_size and doc.file_size > MAX_DOWNLOAD:
        await message.answer("Файл больше 20 МБ: Telegram не позволяет боту его скачать.")
        return
    path = await _save_upload(bot, doc, name)
    images, tg_kind = [], "file"
    if kind == "image":
        try:
            images = [image_block(path.read_bytes())]
        except Exception:
            await message.answer("Не удалось прочитать это изображение.")
            return
        tg_kind = "photo"
    p = Pending(user_id=message.from_user.id, chat_id=message.chat.id, kind=tg_kind, images=images,
                path=path, src_kind=kind, filename=name)
    await _accept(message, bot, p, message.caption or "")


@router.message(F.text)
async def on_text(message: Message, bot: Bot):
    fmt, rest = split_prefix(message.text)
    p = Pending(user_id=message.from_user.id, chat_id=message.chat.id, kind="text", text=rest)
    if fmt and not rest:
        await message.answer("Напишите запрос после формата, например: /xlsx сравни цены на ноутбуки")
        return
    pending.put(p)
    if fmt:
        await dispatch(bot, message, p, fmt)
    else:
        await message.answer(question_for(p), reply_markup=keyboard(p))
