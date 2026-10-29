from __future__ import annotations

import math
from typing import Any

from scipy.stats import pearsonr

from app.hypothesis.base import (
    HypothesisImplementation,
    build_where,
    extract_rows,
    quote_identifier,
)
from app.hypothesis.models import (
    GroupBySpec,
    MetricExpression,
    RelationshipCheck,
)


class RelationshipImplementation(HypothesisImplementation):
    method = "relationship"
    model = RelationshipCheck

    # SourceService caps a query at 10_000 rows; reserve one sentinel row
    # to detect that a grouping exceeded the supported size.
    MAX_GROUPS = 9_999
    PREVIEW_GROUPS = 20

    @staticmethod
    def _aggregate_sql(metric: MetricExpression) -> str:
        field = (
            quote_identifier(metric.field)
            if metric.field is not None
            else None
        )

        if metric.aggregation == "count":
            return "COUNT(*)"

        if field is None:
            raise ValueError(
                f"Aggregation '{metric.aggregation}' requires a field"
            )

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

    @staticmethod
    def _group_expression(group: GroupBySpec) -> str:
        field = quote_identifier(group.field)

        if group.granularity is None:
            return field

        granularity = group.granularity

        return (
            f"DATE_TRUNC("
            f"'{granularity}', "
            f"TRY_CAST({field} AS TIMESTAMP)"
            f")"
        )

    def _build_sql(self, check: RelationshipCheck) -> str:
        group_expressions = [
            self._group_expression(group)
            for group in check.group_by
        ]

        selected_groups = [
            f"{expression} AS group_{index}"
            for index, expression in enumerate(group_expressions)
        ]

        x_expression = (
            f"{self._aggregate_sql(check.x_metric)} AS x_value"
        )
        y_expression = (
            f"{self._aggregate_sql(check.y_metric)} AS y_value"
        )

        select_expressions = [
            *selected_groups,
            x_expression,
            y_expression,
        ]

        where = build_where(check.filters)
        group_by = ", ".join(group_expressions)

        return (
            f"SELECT {', '.join(select_expressions)} "
            f"FROM source"
            f"{where} "
            f"GROUP BY {group_by} "
            f"ORDER BY {group_by} "
            f"LIMIT {self.MAX_GROUPS + 1}"
        )

    @staticmethod
    def _numeric(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None

        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        return number if math.isfinite(number) else None

    @staticmethod
    def _strength(value: float | None) -> str:
        if value is None:
            return "undefined"

        absolute = abs(value)

        if absolute < 0.3:
            return "weak"
        if absolute < 0.7:
            return "moderate"
        return "strong"

    def execute(
        self,
        check: RelationshipCheck,
    ) -> dict[str, Any]:
        sql = self._build_sql(check)

        result = self.query(
            check.source_id,
            sql,
            row_limit=self.MAX_GROUPS + 1,
        )
        rows = extract_rows(result)

        if len(rows) > self.MAX_GROUPS:
            raise ValueError(
                f"Relationship check produced more than "
                f"{self.MAX_GROUPS} groups. Narrow the filters "
                "or use a coarser grouping granularity."
            )

        pairs: list[tuple[float, float]] = []
        preview: list[dict[str, Any]] = []
        excluded_groups = 0

        for row in rows:
            x = self._numeric(row.get("x_value"))
            y = self._numeric(row.get("y_value"))

            if x is None or y is None:
                excluded_groups += 1
                continue

            pairs.append((x, y))

            if len(preview) < self.PREVIEW_GROUPS:
                preview.append({
                    "group": {
                        group.field: row.get(f"group_{index}")
                        for index, group in enumerate(check.group_by)
                    },
                    "x": x,
                    "y": y,
                })

        xs = [pair[0] for pair in pairs]
        ys = [pair[1] for pair in pairs]
        sample_size = len(pairs)

        correlation: float | None = None
        p_value: float | None = None
        confidence_interval: dict[str, float] | None = None
        statistically_significant: bool | None = None
        warnings: list[str] = []

        if sample_size < 3:
            warnings.append(
                "At least 3 valid groups are needed for this "
                "implementation to report inferential statistics."
            )
        elif len(set(xs)) < 2 or len(set(ys)) < 2:
            warnings.append(
                "Correlation is undefined because one metric "
                "has no variation across groups."
            )
        else:
            test = pearsonr(xs, ys)

            correlation = float(test.statistic)
            p_value = float(test.pvalue)
            statistically_significant = p_value < check.alpha

            if sample_size >= 4:
                interval = test.confidence_interval(
                    confidence_level=check.confidence_level
                )

                if (
                    math.isfinite(interval.low)
                    and math.isfinite(interval.high)
                ):
                    confidence_interval = {
                        "level": check.confidence_level,
                        "low": float(interval.low),
                        "high": float(interval.high),
                    }
            else:
                warnings.append(
                    "At least 4 valid groups are needed for a "
                    "finite confidence interval in this implementation."
                )

        if excluded_groups:
            warnings.append(
                f"{excluded_groups} groups were excluded because "
                "one or both aggregated metrics were NULL or non-finite."
            )

        if statistically_significant is False:
            interpretation = (
                "The observed linear correlation is not statistically "
                "significant at the selected alpha level. This does "
                "not prove that no relationship exists."
            )
        elif statistically_significant is True:
            interpretation = (
                "The observed linear correlation is statistically "
                "significant at the selected alpha level. This does "
                "not establish causation."
            )
        else:
            interpretation = (
                "The available data are insufficient to make a "
                "statistical significance assessment."
            )

        return {
            "source_id": check.source_id,
            "x_metric": check.x_metric.model_dump(mode="json"),
            "y_metric": check.y_metric.model_dump(mode="json"),
            "group_by": [
                group.model_dump(mode="json")
                for group in check.group_by
            ],
            "relationship": check.relationship,
            "correlation_method": check.correlation_method,
            "sample_size": sample_size,
            "correlation": correlation,
            "strength": self._strength(correlation),
            "p_value": p_value,
            "alpha": check.alpha,
            "statistically_significant": statistically_significant,
            "confidence_interval": confidence_interval,
            "interpretation": interpretation,
            "limitations": [
                "Correlation does not establish causation.",
                "The p-value and confidence interval assume "
                "independent observations and the statistical "
                "assumptions of Pearson correlation.",
                "Time-series observations may be autocorrelated; "
                "the reported p-value may then be unreliable.",
            ],
            "excluded_groups": excluded_groups,
            "preview": preview,
            "preview_limit": self.PREVIEW_GROUPS,
            "warnings": warnings,
        }
