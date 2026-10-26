from __future__ import annotations

from typing import Any

from app.charts.aggregation import (
    aggregate_expression,
    normalize_sql_value,
    quote_identifier,
    where_clause,
)
from app.charts.errors import ChartExecutionError
from app.charts.implementations.base import ChartImplementation
from app.charts.models import DashboardFilter, KPICard, ChartDefinition


class KPIImplementation(ChartImplementation):
    def supports(self, card: ChartDefinition) -> bool:
        return isinstance(card, KPICard)

    def execute(
        self,
        card: ChartDefinition,
        filters: list[DashboardFilter],
    ) -> dict[str, Any]:
        if not isinstance(card, KPICard):
            raise TypeError("KPIImplementation only supports KPI cards")

        plan = self.planner.plan(card, filters)

        expression = aggregate_expression(
            card.aggregate,
            card.field.field,
        )

        sql = (
            f"SELECT {expression} AS {quote_identifier('value')}, "
            f"COUNT(*) AS {quote_identifier('row_count')} "
            f"FROM {plan.table_name}"
            f"{where_clause(filters)}"
        )

        result = self.sources.query(
            plan.source_id,
            sql,
            row_limit=1,
        )

        if not result.rows:
            raise ChartExecutionError("KPI query returned no result row")

        raw_value = result.rows[0][0]
        row_count = result.rows[0][1]

        return {
            "value": normalize_sql_value(raw_value),
            "format": card.format.model_dump(mode="json"),
            "aggregate": card.aggregate,
            "empty": row_count == 0,
            "provenance": [
                item.model_dump(mode="json")
                for item in result.provenance
            ],
        }
