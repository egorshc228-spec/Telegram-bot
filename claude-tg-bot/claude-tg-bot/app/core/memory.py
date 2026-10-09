"""Память диалога в SQLite.

Сохраняем только текст реплик (пользователь и ассистент). Картинки в историю не
кладём (они тяжёлые), вместо них остаётся пометка. Блоки tool_use в историю не
попадают: так не возникает «осиротевших» вызовов инструментов, которые API
отвергает.
"""
import aiosqlite

from app.config import DB_PATH, MEMORY_MESSAGES

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def load_history(user_id: int) -> list[dict]:
    """Последние N реплик в формате Claude API. Первой всегда идёт реплика user."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT role, text FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, MEMORY_MESSAGES),
        )
        rows = await cur.fetchall()
    rows.reverse()
    while rows and rows[0][0] != "user":
        rows.pop(0)
    return [{"role": r, "content": t} for r, t in rows]


async def save_turn(user_id: int, user_text: str, assistant_text: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO messages(user_id, role, text) VALUES (?, ?, ?)",
            [(user_id, "user", user_text), (user_id, "assistant", assistant_text)],
        )
        await db.commit()


async def clear_history(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
        await db.commit()
