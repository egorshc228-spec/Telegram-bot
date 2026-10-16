"""Общие заглушки для тестов: сценарный «Claude»."""
from types import SimpleNamespace as NS


def say(text):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=text)])


def tool(tool_name, /, **inp):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=f"t_{tool_name}", name=tool_name, input=inp)])


class ScriptedClient:
    """Отдаёт заранее заданные ответы по очереди и запоминает запросы."""

    def __init__(self, *script, error=None):
        self.script, self.calls, self.error = list(script), [], error
        self.messages = self

    async def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.script.pop(0)
