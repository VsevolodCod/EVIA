from collections.abc import Callable
from typing import Any

from app.models import ToolResult
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


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
        except Exception as exc:
            return ToolResult(
                tool_name=name,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )


def build_tool_registry(
    catalog: SchemaCatalog,
    sources: SourceService,
) -> ToolRegistry:

    """
    Создает объект ``ToolRegistry`` и подключает к нему все инструменты

    Принимает различные подключения для использования

    :param catalog: Каталог схем
    :param sources: Источники
    :return:
    """

    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="list_sources",
            description="List all registered data sources.",
            parameters={},
            handler=lambda: [
                source.model_dump(mode="json")
                for source in catalog.list_sources()
            ],
        )
    )

    registry.register(
        ToolDefinition(
            name="get_source_schema",
            description="Get the schema of a registered source.",
            parameters={
                "source_id": {"type": "string"},
            },
            required=["source_id"],
            handler=lambda source_id: sources.get_schema(source_id),
        )
    )

    registry.register(
        ToolDefinition(
            name="preview_data",
            description="Preview a small number of rows from a source.",
            parameters={
                "source_id": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            required=["source_id"],
            handler=lambda source_id, limit=10: sources.preview(
                source_id, limit
            ),
        )
    )

    registry.register(
        ToolDefinition(
            name="profile_data",
            description="Get basic sample-based statistics for a source.",
            parameters={
                "source_id": {"type": "string"},
            },
            required=["source_id"],
            handler=lambda source_id: sources.profile(source_id),
        )
    )

    return registry
