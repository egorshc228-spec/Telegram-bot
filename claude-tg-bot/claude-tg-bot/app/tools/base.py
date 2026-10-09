from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ToolContext:
    """Живёт один запрос пользователя. Инструменты читают из него выбранный формат
    и кладут в него готовые файлы, которые бот потом отправит в Telegram."""

    user_id: int
    target: str = "text"                                   # text | xlsx | docx | pptx | pdf | png
    images: list[bytes] = field(default_factory=list)      # изображения, присланные с запросом
    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)         # предупреждения для пользователя
    rejected: str | None = None                            # причина отказа, если запрос не подходит
