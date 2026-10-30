import re
from typing import Any

from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.base import ToolDefinition, ToolRegistry


_SENSITIVE_FIELD = re.compile(
    r"(^|[_\s-])(id|uuid|token|secret|password|email|phone|key|код|почта|телефон)([_\s-]|$)",
    re.IGNORECASE,
)
_PRIVATE_VALUE = re.compile(
    r"(?i)(?:postgres(?:ql)?://|bearer\s+|/private/|/Users/|/home/|/app/|"
    r"(?:password|api[_-]?key|token|secret)\s*[:=])"
)


def _model_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Keep useful aggregates while withholding rare sample values from the LLM."""
    return {
        **profile,
        "columns": {
            name: {
                **column,
                "top_values": [
                    item for item in column.get("top_values", [])
                    if item.get("count", 0) >= 2
                    and not _PRIVATE_VALUE.search(str(item.get("value", "")))
                ] if not (column.get("is_identifier_candidate") or _SENSITIVE_FIELD.search(name)) else [],
            }
            for name, column in profile.get("columns", {}).items()
        },
    }


def _model_preview(sources: SourceService, source_id: str, limit: int) -> list[dict[str, Any]]:
    """Bound the model sample and mask long identifiers; the UI API stays intact."""
    rows = sources.preview(source_id, min(limit, 10))
    return [
        {
            field: "[скрыто]" if (
                isinstance(value, str) and (
                    _PRIVATE_VALUE.search(value)
                    or (len(value) > 12 and _SENSITIVE_FIELD.search(field))
                )
            ) else value[:200] if isinstance(value, str) and len(value) > 200 else value
            for field, value in row.items()
        }
        for row in rows
    ]


def register_data_tools(
    registry: ToolRegistry,
    catalog: SchemaCatalog,
    sources: SourceService,
) -> None:

    registry.register(
        ToolDefinition(
            name="list_sources",
            description="List all registered data sources.",
            parameters={},
            handler=lambda: [
                {
                    "source_id": source.source_id,
                    "name": source.name,
                    "source_type": source.source_type,
                    "schema_name": source.schema_name,
                    "table_name": source.table_name,
                    "status": source.status,
                }
                for source in sources.list_sources()
            ],
        )
    )

    registry.register(
        ToolDefinition(
            name="get_source_schema",
            description="Get the schema of a registered source.",
            parameters={"source_id": {"type": "string"}},
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
                    "maximum": 10,
                },
            },
            required=["source_id"],
            handler=lambda source_id, limit=10: _model_preview(sources, source_id, limit),
        )
    )

    registry.register(
        ToolDefinition(
            name="profile_data",
            description="Get basic sample-based statistics for a source.",
            parameters={"source_id": {"type": "string"}},
            required=["source_id"],
            handler=lambda source_id: _model_profile(sources.profile(source_id)),
        )
    )
