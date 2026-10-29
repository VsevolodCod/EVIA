from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from scipy.stats import pearsonr

from app.hypothesis.base import (
    HypothesisImplementation,
    build_where,
    extract_rows,
    numeric_expression,
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

    @staticmethod
    def _period_index(value: Any, granularity: str) -> int:
        try:
            day = datetime.fromisoformat(str(value)).date()
        except (TypeError, ValueError) as exc:
            raise ValueError("Calendar grouping produced an invalid date") from exc
        if granularity == "day":
            return day.toordinal()
        if granularity == "week":
            return day.toordinal() // 7
        if granularity == "month":
            return day.year * 12 + day.month - 1
        if granularity == "quarter":
            return day.year * 4 + (day.month - 1) // 3
        return day.year

    @staticmethod
    def _lag_statistics(
        pairs: list[tuple[int, float, float]], check: RelationshipCheck,
    ) -> dict[str, Any]:
        xs = [x for _, x, _ in pairs]
        ys = [y for _, _, y in pairs]
        count = len(pairs)
        output: dict[str, Any] = {
            "sample_size": count, "correlation": None, "p_value": None,
            "adjusted_p_value": None, "statistically_significant": None,
            "confidence_interval": None, "differenced_correlation": None,
        }
        if count < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
            return output
        test = pearsonr(xs, ys)
        raw_p = float(test.pvalue)
        comparisons = check.max_lag + 1
        adjusted = min(1.0, raw_p * comparisons)
        output.update({
            "correlation": float(test.statistic), "p_value": raw_p,
            "adjusted_p_value": adjusted,
            "statistically_significant": adjusted < check.alpha,
        })
        if count >= 4:
            level = max(check.confidence_level, 1 - check.alpha / comparisons)
            interval = test.confidence_interval(confidence_level=level)
            if math.isfinite(interval.low) and math.isfinite(interval.high):
                output["confidence_interval"] = {
                    "level": level, "low": float(interval.low), "high": float(interval.high),
                }
        differences = [
            (pairs[index][1] - pairs[index - 1][1],
             pairs[index][2] - pairs[index - 1][2])
            for index in range(1, count)
            if pairs[index][0] == pairs[index - 1][0] + 1
        ]
        if len(differences) >= 3:
            dx, dy = zip(*differences)
            if len(set(dx)) >= 2 and len(set(dy)) >= 2:
                output["differenced_correlation"] = float(pearsonr(dx, dy).statistic)
        return output

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

        output = {
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
        if check.max_lag:
            grain = check.group_by[0].granularity
            assert grain is not None
            periods = {
                self._period_index(row.get("group_0"), grain): (
                    self._numeric(row.get("x_value")), self._numeric(row.get("y_value"))
                ) for row in rows
            }
            if periods:
                span = max(periods) - min(periods) + 1
                output["period_coverage"] = len(periods) / span
                if len(periods) < span:
                    warnings.append(f"{span - len(periods)} missing periods were excluded from lag alignment.")
            else:
                output["period_coverage"] = 0
            lag_results = []
            for lag in range(check.max_lag + 1):
                lag_pairs = [
                    (period, x, periods[period + lag][1])
                    for period, (x, _) in sorted(periods.items())
                    if x is not None and period + lag in periods
                    and periods[period + lag][1] is not None
                ]
                stats = self._lag_statistics(lag_pairs, check)
                lag_results.append({"lag": lag, **stats})
                if (stats["correlation"] is not None and abs(stats["correlation"]) >= 0.7
                        and (stats["differenced_correlation"] is None
                             or abs(stats["differenced_correlation"]) < 0.3)):
                    warnings.append(f"Lag {lag}: a shared trend may explain the raw correlation.")
            output["lag_results"] = lag_results
            output["multiple_testing"] = "Bonferroni correction across scanned lags"
            output["max_lag"] = check.max_lag
            output["statistically_significant"] = lag_results[0]["statistically_significant"]
            output["adjusted_p_value"] = lag_results[0]["adjusted_p_value"]
            output["confidence_interval"] = lag_results[0]["confidence_interval"]
            if output["statistically_significant"] is True:
                output["interpretation"] = (
                    "The lag-0 association remains statistically significant after "
                    "correction for the scanned lags. This does not establish causation."
                )
            elif output["statistically_significant"] is False:
                output["interpretation"] = (
                    "The lag-0 association is not statistically significant after "
                    "correction for the scanned lags. This does not prove no relationship."
                )
            else:
                output["interpretation"] = (
                    "The lag-0 sample is insufficient for a statistical significance assessment."
                )
            output["limitations"].append(
                "Lag alignment uses complete calendar periods; gaps reduce the paired sample."
            )
        return output
