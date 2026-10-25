from __future__ import annotations

from typing import Any

from app.charts.engine import DashboardEngine
from app.charts.models import (
    AddChartToDashboardArgs,
    ComposeDashboardArgs,
)
from app.tools.base import ToolDefinition, ToolRegistry


def _resolve_refs(value: Any, definitions: dict[str, Any]) -> Any:
    """Раскрывает локальные Pydantic $ref для схемы ToolRegistry."""

    if isinstance(value, list):
        return [_resolve_refs(item, definitions) for item in value]

    if not isinstance(value, dict):
        return value

    ref = value.get("$ref")
    if ref is not None:
        prefix = "#/$defs/"
        if not ref.startswith(prefix):
            raise ValueError(f"Unsupported schema reference: {ref}")

        name = ref[len(prefix):]
        if name not in definitions:
            raise ValueError(f"Unknown schema definition: {name}")

        resolved = _resolve_refs(definitions[name], definitions)

        siblings = {
            key: item for key, item in value.items() if key != "$ref"
        }
        if siblings:
            resolved = {
                **resolved,
                **_resolve_refs(siblings, definitions),
            }

        return resolved

    return {
        key: _resolve_refs(item, definitions)
        for key, item in value.items()
    }


def _build_parameters(model: type) -> tuple[dict[str, Any], list[str]]:
    """Строит JSON Schema параметров инструмента из Pydantic-модели."""

    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    parameters = _resolve_refs(schema, definitions)
    return parameters, schema.get("required", [])


def register_dashboard_tools(
    registry: ToolRegistry,
    engine: DashboardEngine,
) -> None:
    """Регистрирует инструменты сборки дашбордов из сохранённых чартов."""

    compose_parameters, compose_required = _build_parameters(
        ComposeDashboardArgs
    )

    registry.register(
        ToolDefinition(
            name="compose_dashboard",
            description=(
                "Create a dashboard from existing saved chart IDs. "
                "Provide a title, an optional summary, and chart_ids in "
                "the desired display order. Every chart ID must refer to "
                "an existing chart. This tool does not create charts."
            ),
            parameters=compose_parameters,
            required=compose_required,
            handler=lambda **payload: engine.compose_dashboard(payload),
        )
    )

    add_parameters, add_required = _build_parameters(
        AddChartToDashboardArgs
    )

    registry.register(
        ToolDefinition(
            name="add_charts_to_dashboard",
            description=(
                "Add an existing saved chart to a dashboard by ID. "
                "Provide dashboard_id and chart_id. Optionally provide "
                "position; if omitted, the chart is appended to the end. "
                "Call this tool once per chart. The same chart cannot be "
                "added to the same dashboard more than once."
            ),
            parameters=add_parameters,
            required=add_required,
            handler=lambda **payload: engine.add_chart_to_dashboard(payload),
        )
    )
