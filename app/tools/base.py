from collections.abc import Callable
from typing import Any

from app.models import ToolResult
from app.postgresql_sql import PostgresQueryError
from app.safe_sql import SafeQueryError


class ToolDefinition:
    """
    Класс инструмента для хранения внутри ``ToolRegistry``.
    Без имплементации самого метода.
    """

    def __init__(
            self,
            name: str,
            description: str,
            parameters: dict[str, Any],  # Описание параметров для использования инструмента
            handler: Callable[..., Any],  # Какие из них обязательны для вызова
            required: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.required = required or []

    def public_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                    "additionalProperties": False,
                },
            },
        }


class ToolRegistry:
    """
    Хранит в себе набор доступных инструментов в формате ``ToolDefinition``
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool: {tool.name}")

        self._tools[tool.name] = tool

    def descriptions(self) -> list[dict[str, Any]]:
        return [
            tool.public_schema()
            for tool in self._tools.values()
        ]

    def fork(self) -> "ToolRegistry":
        """A request-local registry; closures must never leak between chats."""
        copied = ToolRegistry()
        copied._tools = dict(self._tools)
        return copied

    def execute(
            self,
            name: str,
            arguments: dict[str, Any],
    ) -> ToolResult:

        """
        Метод, который вызывает сами инструменты, опираясь на распаршенную ранее информацию из json
        :param name: Название инструмента
        :param arguments: Переданные аргументы
        :return:
        """

        tool = self._tools.get(name)

        if tool is None:
            return ToolResult(
                tool_name=name,
                ok=False,
                error="Unknown tool",
            )

        if not isinstance(arguments, dict):
            return ToolResult(
                tool_name=name,
                ok=False,
                error="Arguments must be an object",
            )

        unknown = set(arguments) - set(tool.parameters)
        missing = set(tool.required) - set(arguments)

        if unknown:
            return ToolResult(
                tool_name=name,
                ok=False,
                error=f"Unexpected arguments: {sorted(unknown)}",
            )

        if missing:
            return ToolResult(
                tool_name=name,
                ok=False,
                error=f"Missing arguments: {sorted(missing)}",
            )

        try:
            result = tool.handler(**arguments)
            return ToolResult(
                tool_name=name,
                ok=True,
                data=result,
            )
        except (SafeQueryError, PostgresQueryError) as exc:
            return ToolResult(
                tool_name=name,
                ok=False,
                error=exc.code,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=name,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )
