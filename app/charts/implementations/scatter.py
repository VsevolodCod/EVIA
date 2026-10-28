from __future__ import annotations

from typing import Any

from app.charts.aggregation import normalize_sql_value, quote_identifier, where_clause
from app.charts.implementations.base import ChartImplementation
from app.charts.models import ChartDefinition, DashboardFilter, ScatterCard


class ScatterImplementation(ChartImplementation):
    def supports(self, card: ChartDefinition) -> bool:
        return isinstance(card, ScatterCard)

    def execute(self, card: ChartDefinition, filters: list[DashboardFilter]) -> dict[str, Any]:
        if not isinstance(card, ScatterCard):
            raise TypeError("ScatterImplementation only supports scatter cards")
        plan = self.planner.plan(card, filters)
        x = quote_identifier(card.x.field)
        y = quote_identifier(card.y.field)
        conditions = [f"{x} IS NOT NULL", f"{y} IS NOT NULL"]
        sql = f"SELECT {x} AS x_value, {y} AS y_value FROM {plan.table_name}"
        sql += where_clause(filters)
        sql += (" AND " if filters else " WHERE ") + " AND ".join(conditions)
        sql += f" ORDER BY {x} ASC, {y} ASC LIMIT {card.limit}"
        result = self.sources.query(plan.source_id, sql, row_limit=card.limit)
        points = [{"x": normalize_sql_value(row[0]), "y": normalize_sql_value(row[1])}
                  for row in result.rows]
        return {
            "x": {"field": card.x.field, "label": card.x.label or card.x.field,
                  "type": "number", "format": card.x.format.model_dump(mode="json")},
            "y": {"field": card.y.field, "label": card.y.label or card.y.field,
                  "type": "number", "format": card.y.format.model_dump(mode="json")},
            "points": points,
            "limit": card.limit,
            "limit_reached": len(points) == card.limit,
            "source_id": plan.source_id,
            "provenance": [item.model_dump(mode="json") for item in result.provenance],
        }
