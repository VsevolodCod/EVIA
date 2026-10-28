from __future__ import annotations

from typing import Any

from app.hypothesis.base import (
    HypothesisImplementation,
    build_where,
    extract_rows,
    quote_identifier,
)
from app.hypothesis.models import CompareCheck


class CompareImplementation(HypothesisImplementation):
    method = "compare"
    model = CompareCheck

    @staticmethod
    def _aggregate_sql(check: CompareCheck) -> str:
        metric = check.metric
        field = (
            quote_identifier(metric.field)
            if metric.field is not None
            else None
        )

        if metric.aggregation == "count":
            return "COUNT(*)"

        if field is None:
            raise ValueError("Metric field is required")

        if metric.aggregation == "count_distinct":
            return f"COUNT(DISTINCT {field})"

        if metric.aggregation == "sum":
            return f"SUM(TRY_CAST({field} AS DOUBLE))"

        if metric.aggregation == "avg":
            return f"AVG(TRY_CAST({field} AS DOUBLE))"

        if metric.aggregation == "min":
            return f"MIN(TRY_CAST({field} AS DOUBLE))"

        if metric.aggregation == "max":
            return f"MAX(TRY_CAST({field} AS DOUBLE))"

        raise ValueError(
            f"Unsupported aggregation: {metric.aggregation}"
        )

    def _calculate(
        self,
        check: CompareCheck,
        filters: list,
    ) -> Any:
        aggregate = self._aggregate_sql(check)
        where = build_where(filters)

        sql = (
            f"SELECT {aggregate} AS metric_value "
            f"FROM source{where}"
        )

        result = self.query(
            check.metric.source_id,
            sql,
            row_limit=1,
        )
        rows = extract_rows(result)

        if not rows:
            return None

        return rows[0].get("metric_value")

    @staticmethod
    def _number(value: Any) -> float | int | None:
        if value is None:
            return None

        if isinstance(value, bool):
            raise ValueError("Boolean is not a valid metric result")

        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Metric result is not numeric"
            ) from exc

    def execute(self, check: CompareCheck) -> dict[str, Any]:
        left_value = self._number(
            self._calculate(check, check.left.filters)
        )
        right_value = self._number(
            self._calculate(check, check.right.filters)
        )

        if left_value is None or right_value is None:
            return {
                "left": {
                    "label": check.left.label,
                    "value": left_value,
                },
                "right": {
                    "label": check.right.label,
                    "value": right_value,
                },
                "delta": None,
                "change_percent": None,
                "assessment": "inconclusive",
                "reason": "One or both groups returned a NULL metric.",
            }

        delta = right_value - left_value

        change_percent = (
            (delta / abs(left_value)) * 100
            if left_value != 0
            else None
        )

        if delta > 0:
            direction = "increase"
        elif delta < 0:
            direction = "decrease"
        else:
            direction = "no_change"

        if check.expected == "any":
            assessment = "observed"
        elif check.expected == direction:
            assessment = "supports"
        else:
            assessment = "contradicts"

        return {
            "metric": check.metric.model_dump(mode="json"),
            "left": {
                "label": check.left.label,
                "value": left_value,
            },
            "right": {
                "label": check.right.label,
                "value": right_value,
            },
            "delta": delta,
            "change_percent": change_percent,
            "direction": direction,
            "expected": check.expected,
            "assessment": assessment,
            "interpretation": (
                "The result describes a difference between groups; "
                "it does not establish causation."
            ),
        }
