from __future__ import annotations

from typing import Any

from app.charts.aggregation import normalize_sql_value, quote_identifier, where_clause
from app.charts.implementations.base import ChartImplementation
from app.charts.models import ChartDefinition, DashboardFilter, TableCard


class TableImplementation(ChartImplementation):
    def supports(self, card: ChartDefinition) -> bool:
        return isinstance(card, TableCard)

    def execute(self, card: ChartDefinition, filters: list[DashboardFilter]) -> dict[str, Any]:
        if not isinstance(card, TableCard):
            raise TypeError("TableImplementation only supports table cards")
        plan = self.planner.plan(card, filters)
        columns = [ref.field for ref in card.fields]
        select = ", ".join(quote_identifier(name) for name in columns)
        sql = f"SELECT {select} FROM {plan.table_name}{where_clause(filters)}"
        sql += f" ORDER BY {select} LIMIT {card.limit}"
        result = self.sources.query(plan.source_id, sql, row_limit=card.limit)
        rows = [{name: normalize_sql_value(value) for name, value in zip(columns, row)}
                for row in result.rows]
        return {
            "columns": columns,
            "rows": rows,
            "limit": card.limit,
            "limit_reached": len(rows) == card.limit,
            "source_id": plan.source_id,
            "provenance": [item.model_dump(mode="json") for item in result.provenance],
        }
