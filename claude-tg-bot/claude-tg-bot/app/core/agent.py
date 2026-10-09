"""Главный цикл: сообщение -> Claude -> (инструменты)* -> ответ."""
import asyncio
import base64
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOOL_ROUNDS
from app.core import memory
from app.core.prompts import SYSTEM_PROMPT, format_rules
from app.tools import HANDLERS, ToolContext, tools_for

log = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Один пользователь = одна очередь, чтобы реплики не перемешивались в памяти.
_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


@dataclass
class AgentResult:
    text: str
    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rejected: bool = False


def _text_of(content) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


async def run_agent(user_id: int, text: str, images: list[dict] | None = None, target: str = "text",
                    memory_text: str | None = None) -> AgentResult:
    """target: text | xlsx | docx | pptx | pdf | png.
    memory_text: что записать в память вместо полного text (например, без содержимого файла)."""
    images = images or []
    async with _locks[user_id]:
        history = await memory.load_history(user_id)
        prompt = text.strip() or ("Опиши это фото." if images else "")
        user_content = [*images, {"type": "text", "text": prompt}]
        messages = history + [{"role": "user", "content": user_content}]
        ctx = ToolContext(user_id=user_id, target=target,
                          images=[base64.b64decode(b["source"]["data"]) for b in images])
        system = [
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": format_rules(target)},
        ]
        tools = tools_for(target)

        final_text = ""
        for _ in range(MAX_TOOL_ROUNDS):
            resp = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8192,
                system=system,
                tools=tools,
                messages=messages,
            )

            if resp.stop_reason == "pause_turn":
                # серверный инструмент (веб-поиск) просит продолжить
                messages.append({"role": "assistant", "content": resp.content})
                continue

            if resp.stop_reason != "tool_use":
                final_text = _text_of(resp.content)
                break

            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                handler = HANDLERS.get(block.name)
                if handler is None:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Неизвестный инструмент {block.name}", "is_error": True})
                    continue
                try:
                    out = await handler(ctx, **block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(out)})
                except Exception as e:
                    log.exception("tool %s failed", block.name)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Ошибка инструмента: {e}", "is_error": True})
            messages.append({"role": "user", "content": results})

            if ctx.rejected:       # запрос не подходит под выбранный формат: сразу отвечаем отказом
                reason = ctx.rejected.rstrip()
                reason = reason if reason[-1:] in ".!?" else reason + "."
                final_text = f"❌ Недопустимый файл к вашему запросу: {reason}"
                ctx.files.clear()
                break
        else:
            final_text = "Не удалось завершить запрос за разумное число шагов. Попробуйте сформулировать проще."

        final_text = final_text or "Готово."

        # В память пишем текст; пометки о фото и файлах помогают потом ссылаться на них.
        saved_user = ("[пользователь прислал фото] " if images else "") + (memory_text if memory_text is not None else prompt)
        saved_user = f"[выбран формат: {target}] " + saved_user
        saved_bot = final_text
        if ctx.files:
            saved_bot += "\n[отправлены файлы: " + ", ".join(p.name for p in ctx.files) + "]"
        await memory.save_turn(user_id, saved_user, saved_bot)

        return AgentResult(text=final_text, files=ctx.files, notes=ctx.notes, rejected=bool(ctx.rejected))
