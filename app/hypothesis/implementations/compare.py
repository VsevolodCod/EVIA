from __future__ import annotations

import math
from typing import Any

from scipy.stats import t as student_t

from app.hypothesis.base import (
    HypothesisImplementation,
    build_where,
    extract_rows,
    numeric_expression,
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

        numeric = numeric_expression(metric.field)

        if metric.aggregation == "count_distinct":
            return f"COUNT(DISTINCT {field})"

        if metric.aggregation == "sum":
            return f"SUM({numeric})"

        if metric.aggregation == "avg":
            return f"AVG({numeric})"

        if metric.aggregation == "min":
            return f"MIN({numeric})"

        if metric.aggregation == "max":
            return f"MAX({numeric})"

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

        extra = ""
        if check.metric.aggregation == "avg" and check.metric.field:
            numeric = numeric_expression(check.metric.field)
            extra = (f", COUNT({numeric}) AS sample_size, "
                     f"STDDEV_SAMP({numeric}) AS stddev")
        sql = f"SELECT {aggregate} AS metric_value{extra} FROM source{where}"

        result = self.query(
            check.metric.source_id,
            sql,
            row_limit=1,
        )
        rows = extract_rows(result)

        if not rows:
            return None

        return rows[0]

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

    @staticmethod
    def _uncertainty(left: dict[str, Any], right: dict[str, Any], delta: float,
                     aggregation: str) -> dict[str, Any]:
        if aggregation != "avg":
            return {"status": "not_estimated", "reason":
                    "This aggregate is descriptive; no confidence interval was estimated."}
        try:
            left_count = int(left["sample_size"])
            right_count = int(right["sample_size"])
            left_std = float(left["stddev"])
            right_std = float(right["stddev"])
        except (KeyError, TypeError, ValueError):
            return {"status": "not_estimated", "reason":
                    "Sample sizes and variation are required for a confidence interval."}
        if (left_count < 2 or right_count < 2 or not math.isfinite(left_std)
                or not math.isfinite(right_std)):
            return {"status": "not_estimated", "reason":
                    "At least two finite observations are needed in each group."}
        left_var = left_std ** 2 / left_count
        right_var = right_std ** 2 / right_count
        standard_error = math.sqrt(left_var + right_var)
        if standard_error == 0:
            return {"status": "not_estimated", "reason":
                    "Both groups have zero estimated variation."}
        df = (left_var + right_var) ** 2 / (
            left_var ** 2 / (left_count - 1) + right_var ** 2 / (right_count - 1)
        )
        critical = float(student_t.ppf(0.975, df))
        p_value = float(2 * student_t.sf(abs(delta / standard_error), df))
        return {
            "status": "estimated", "method": "welch",
            "left_count": left_count, "right_count": right_count,
            "p_value": p_value,
            "confidence_interval": {
                "level": 0.95,
                "low": delta - critical * standard_error,
                "high": delta + critical * standard_error,
            },
            "assumptions": (
                "Welch interval assumes independent observations within each group; "
                "it does not establish causation."
            ),
        }

    def execute(self, check: CompareCheck) -> dict[str, Any]:
        left_result = self._calculate(check, check.left.filters) or {}
        right_result = self._calculate(check, check.right.filters) or {}
        left_value = self._number(left_result.get("metric_value"))
        right_value = self._number(right_result.get("metric_value"))

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
                "uncertainty": {"status": "not_estimated", "reason": "A group has no metric value."},
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
            "uncertainty": self._uncertainty(left_result, right_result, delta, check.metric.aggregation),
            "interpretation": (
                "The result describes a difference between groups; "
                "it does not establish causation."
            ),
        }
