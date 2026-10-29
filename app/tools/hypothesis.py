from __future__ import annotations

from typing import Any

from app.hypothesis.engine import HypothesisEngine
from app.tools.base import ToolDefinition, ToolRegistry


def _is_numeric_type(type_name: str) -> bool:
    return any(marker in type_name.strip().lower() for marker in (
        "int", "float", "double", "decimal", "numeric", "number", "real", "serial",
    ))


def register_hypothesis_tools(registry: ToolRegistry, sources: Any) -> None:
    """Expose short, flat contracts that Cloud.ru can use in one tool call."""
    engine = HypothesisEngine(sources)

    def run_one(payload: dict[str, Any]) -> dict[str, Any]:
        result = engine.run(payload)
        if result["results"][0]["status"] != "completed":
            raise ValueError("Hypothesis check failed; verify the selected source and field names.")
        return result

    def compare_groups(
        source_id: str, metric_field: str, group_field: str,
        left_value: str, right_value: str, aggregation: str = "avg",
        expected: str = "any",
    ) -> dict[str, Any]:
        return run_one({
            "statement": f"Сравнение {aggregation}({metric_field}) по {group_field}",
            "checks": [{
                "id": "comparison", "method": "compare",
                "metric": {"source_id": source_id, "field": metric_field, "aggregation": aggregation},
                "left": {"label": left_value, "filters": [{
                    "field": group_field, "operator": "eq", "value": left_value,
                }]},
                "right": {"label": right_value, "filters": [{
                    "field": group_field, "operator": "eq", "value": right_value,
                }]},
                "expected": expected,
            }],
        })

    registry.register(ToolDefinition(
        name="compare_groups",
        description=(
            "Compare a numeric metric between two values of one grouping field. "
            "Use the selected source ID and exact schema field names. "
            "Returns observed values and difference; does not prove causation."
        ),
        parameters={
            "source_id": {"type": "string"},
            "metric_field": {"type": "string"},
            "group_field": {"type": "string"},
            "left_value": {"type": "string"},
            "right_value": {"type": "string"},
            "aggregation": {"type": "string", "enum": ["sum", "avg", "min", "max", "count"]},
            "expected": {"type": "string", "enum": ["increase", "decrease", "no_change", "any"]},
        },
        required=["source_id", "metric_field", "group_field", "left_value", "right_value"],
        handler=compare_groups,
    ))

    def analyze_relationship(
        source_id: str, x_field: str, y_field: str, group_field: str,
        aggregation: str = "sum", time_grain: str | None = None, max_lag: int = 0,
    ) -> dict[str, Any]:
        return run_one({
            "statement": f"Связь {x_field} и {y_field} по {group_field}",
            "checks": [{
                "id": "relationship", "method": "relationship",
                "source_id": source_id,
                "x_metric": {"field": x_field, "aggregation": aggregation},
                "y_metric": {"field": y_field, "aggregation": aggregation},
                "group_by": [{"field": group_field, "granularity": time_grain}],
                "max_lag": max_lag,
            }],
        })

    registry.register(ToolDefinition(
        name="analyze_relationship",
        description=(
            "Calculate Pearson correlation between two numeric metrics grouped "
            "by one field of the selected source. Use exact schema field names. "
            "At least three valid groups are needed. Correlation does not imply causation."
        ),
        parameters={
            "source_id": {"type": "string"},
            "x_field": {"type": "string"},
            "y_field": {"type": "string"},
            "group_field": {"type": "string"},
            "aggregation": {"type": "string", "enum": ["sum", "avg", "min", "max"]},
            "time_grain": {"type": "string", "enum": ["day", "week", "month", "quarter", "year"]},
            "max_lag": {"type": "integer", "minimum": 0, "maximum": 6},
        },
        required=["source_id", "x_field", "y_field", "group_field"],
        handler=analyze_relationship,
    ))

    def list_available_metrics(source_id: str) -> dict[str, Any]:
        schema = sources.get_schema(source_id)
        fields = []
        for obj in schema.objects:
            for field in obj.fields:
                inferred_type = field.inferred_type or "unknown"
                aggregations = ["count_distinct"]
                if _is_numeric_type(inferred_type):
                    aggregations.extend(["sum", "avg", "min", "max"])
                fields.append({
                    "field": field.name,
                    "inferred_type": inferred_type,
                    "aggregations": aggregations,
                })
        return {"source_id": source_id, "fields": fields}

    registry.register(ToolDefinition(
        name="list_available_metrics",
        description="List exact fields and numeric aggregations for the selected source.",
        parameters={"source_id": {"type": "string"}},
        required=["source_id"],
        handler=list_available_metrics,
    ))
