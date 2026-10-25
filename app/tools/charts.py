from __future__ import annotations

from typing import Any

from app.charts.engine import DashboardEngine
from app.charts.models import DashboardSpec
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.base import ToolDefinition, ToolRegistry


def _resolve_refs(value: Any, definitions: dict[str, Any]) -> Any:
    """Раскрывает локальные Pydantic $ref для схемы текущего ToolRegistry."""
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

        # Сохраняем дополнительные ограничения, если они есть рядом с $ref.
        siblings = {
            key: item for key, item in value.items() if key != "$ref"
        }
        if siblings:
            resolved = {**resolved, **_resolve_refs(siblings, definitions)}

        return resolved

    return {
        key: _resolve_refs(item, definitions)
        for key, item in value.items()
    }


def register_chart_tools(
    registry: ToolRegistry,
    catalog: SchemaCatalog,
    sources: SourceService,
) -> None:
    engine = DashboardEngine(catalog, sources)

    schema = DashboardSpec.model_json_schema()
    definitions = schema.pop("$defs", {})
    parameters = _resolve_refs(schema["properties"], definitions)

    registry.register(
        ToolDefinition(
            name="create_dashboard",
            description=(
                "Create and compute a dashboard using registered data sources. "
                "Supported card types are kpi and line only. Use actual "
                "source IDs and field names. KPI supports count, sum, avg, "
                "min and max. Line supports grouping, optional series, "
                "filters, sorting and limits. Do not provide SQL, code, "
                "or invented result values. Cross-source joins are not "
                "supported. The backend computes all card values."
            ),
            parameters=parameters,
            required=schema.get("required", []),
            handler=lambda **payload: engine.create_dashboard(payload),
        )
    )
