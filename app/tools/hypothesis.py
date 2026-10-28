from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.hypothesis.engine import HypothesisEngine
from app.hypothesis.models import (
    CompareCheck,
    HypothesisRequest,
    RelationshipCheck,
)
from app.tools.base import ToolDefinition, ToolRegistry

import logging


logger = logging.getLogger(__name__)


CHECK_MODELS: dict[str, type[BaseModel]] = {
    "compare": CompareCheck,
    "relationship": RelationshipCheck,
}


def _resolve_refs(
    value: Any,
    definitions: dict[str, Any],
) -> Any:
    """Раскрывает локальные Pydantic $ref для ToolRegistry."""

    if isinstance(value, list):
        return [
            _resolve_refs(item, definitions)
            for item in value
        ]

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
            key: item
            for key, item in value.items()
            if key != "$ref"
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
        if key != "discriminator"
    }


def _build_parameters(
    model: type[BaseModel],
) -> tuple[dict[str, Any], list[str]]:
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    properties = _resolve_refs(
        schema.get("properties", {}),
        definitions,
    )
    required = schema.get("required", [])

    return properties, required


def _get_check_info(method: str) -> dict[str, Any]:
    model = CHECK_MODELS.get(method)

    if model is None:
        raise ValueError(
            f"Unknown check method '{method}'. "
            f"Available methods: {', '.join(sorted(CHECK_MODELS))}"
        )

    return {
        "method": method,
        "name": model.__name__,
        "description": model.__doc__ or "",
        "schema": model.model_json_schema(),
    }


class GetCheckInfoArgs(BaseModel):
    method: str = Field(
        description=(
            "Тип проверки. Сначала вызови list_hypothesis_checks, "
            "чтобы получить доступные методы."
        )
    )


class ListMetricsArgs(BaseModel):
    source_id: str = Field(
        description="ID CSV-источника, поля которого нужно изучить."
    )


def _is_numeric_type(type_name: str) -> bool:
    normalized = type_name.strip().lower()

    numeric_markers = (
        "int",
        "float",
        "double",
        "decimal",
        "numeric",
        "number",
        "real",
        "serial",
    )

    return any(marker in normalized for marker in numeric_markers)


def register_hypothesis_tools(
    registry: ToolRegistry,
    sources: Any,
) -> None:
    """Регистрирует инструменты проверки гипотез."""

    engine = HypothesisEngine(sources)

    request_parameters, request_required = _build_parameters(
        HypothesisRequest
    )

    def check_hypothesis(**payload: Any) -> dict[str, Any]:
        return engine.run(payload)

    registry.register(
        ToolDefinition(
            name="check_hypothesis",
            description=(
                "Run one or more analytical checks for a hypothesis. "
                "Pass a statement and checks with their own method-specific "
                "contracts. Supported methods are returned by "
                "list_hypothesis_checks. Each check reports its own status, "
                "so one failed check does not prevent the others from "
                "running. The results describe evidence and do not by "
                "themselves prove causation. Use get_hypothesis_check_info "
                "to get the exact input contract for one hypothesis check method"
            ),
            parameters=request_parameters,
            required=request_required,
            handler=check_hypothesis,
        )
    )

    def list_hypothesis_checks(**_: Any) -> dict[str, Any]:
        return {
            "checks": [
                {
                    "method": method,
                    "name": model.__name__,
                    "description": model.__doc__ or "",
                }
                for method, model in sorted(CHECK_MODELS.items())
            ]
        }

    registry.register(
        ToolDefinition(
            name="list_hypothesis_checks",
            description=(
                "List supported hypothesis check methods. Call this "
                "before constructing checks if you are unsure which "
                "methods are available. This tool does not execute checks."
            ),
            parameters={},
            required=[],
            handler=list_hypothesis_checks,
        )
    )

    info_parameters, info_required = _build_parameters(
        GetCheckInfoArgs
    )

    registry.register(
        ToolDefinition(
            name="get_hypothesis_check_info",
            description=(
                "Get the exact input contract for one hypothesis check "
                "method. Use list_hypothesis_checks to discover valid "
                "method names, then call this tool before constructing "
                "a complex check."
            ),
            parameters=info_parameters,
            required=info_required,
            handler=lambda **payload: _get_check_info(
                payload["method"]
            ),
        )
    )

    metrics_parameters, metrics_required = _build_parameters(
        ListMetricsArgs
    )

    def list_available_metrics(**payload: Any) -> dict[str, Any]:
        source_id = payload["source_id"]
        schema = sources.get_schema(source_id)

        fields = []

        for obj in schema.objects:
            for field in obj.fields:
                inferred_type = field.inferred_type or "unknown"
                aggregations = ["count_distinct"]

                if _is_numeric_type(inferred_type):
                    aggregations.extend(
                        ["sum", "avg", "min", "max"]
                    )

                fields.append(
                    {
                        "field": field.name,
                        "inferred_type": inferred_type,
                        "nullable": field.nullable,
                        "description": field.description,
                        "aggregations": aggregations,
                    }
                )

        return {
            "source_id": source_id,
            "metrics": [
                {
                    "field": None,
                    "aggregation": "count",
                    "description": "Количество строк источника",
                },
                *[
                    {
                        "field": item["field"],
                        "aggregations": item["aggregations"],
                        "inferred_type": item["inferred_type"],
                        "description": item["description"],
                    }
                    for item in fields
                ],
            ],
            "fields": fields,
        }

    registry.register(
        ToolDefinition(
            name="list_available_metrics",
            description=(
                "List fields and supported metric aggregations for a "
                "CSV source. Use this before creating hypothesis checks "
                "to avoid inventing column names or incompatible "
                "aggregations. Numeric fields support sum, avg, min "
                "and max; count_distinct is available for all fields."
            ),
            parameters=metrics_parameters,
            required=metrics_required,
            handler=list_available_metrics,
        )
    )
