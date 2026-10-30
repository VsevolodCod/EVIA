from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator

from app.models import ToolResult
from app.postgresql_sql import PostgresQueryError
from app.safe_sql import SafeQueryError


class InvalidSourceFieldError(Exception):
    """Safe, fixed error for a requested field absent from the source schema."""


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
        self._validator = Draft202012Validator({
            "type": "object",
            "properties": self.parameters,
            "required": self.required,
            "additionalProperties": False,
        })

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

        # Validate the full nested contract server-side. Provider-side JSON
        # schemas are hints, not an authorization or validation boundary.
        if not tool._validator.is_valid(arguments):
            return ToolResult(
                tool_name=name,
                ok=False,
                error="INVALID_TOOL_ARGUMENTS",
            )

        try:
            result = tool.handler(**arguments)
            return ToolResult(
                tool_name=name,
                ok=True,
                data=result,
            )
        except InvalidSourceFieldError:
            return ToolResult(
                tool_name=name,
                ok=False,
                error="INVALID_SOURCE_FIELD",
            )
        except (SafeQueryError, PostgresQueryError) as exc:
            return ToolResult(
                tool_name=name,
                ok=False,
                error=exc.code,
            )
        except Exception:
            # Driver exceptions and validation messages can contain DSNs,
            # credentials, file paths or raw source values. Tool results are
            # also sent back to the model, so never echo exception text here.
            return ToolResult(
                tool_name=name,
                ok=False,
                error="TOOL_EXECUTION_FAILED",
            )
