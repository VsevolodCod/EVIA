from __future__ import annotations

from typing import Any

from app.charts.aggregation import (
    aggregate_expression,
    normalize_sql_value,
    quote_identifier,
    where_clause,
)
from app.charts.implementations.base import ChartImplementation
from app.charts.models import BarCard, ChartDefinition, DashboardFilter, LineCard


class LineImplementation(ChartImplementation):
    def supports(self, card: ChartDefinition) -> bool:
        return isinstance(card, LineCard) and card.type == "line"

    def execute(
        self,
        card: ChartDefinition,
        filters: list[DashboardFilter],
    ) -> dict[str, Any]:
        if not isinstance(card, (LineCard, BarCard)):
            raise TypeError("LineImplementation only supports line cards")

        plan = self.planner.plan(card, filters)

        x_field = quote_identifier(card.x.field)
        if card.x.time_grain is not None:
            # The unit is a validated enum, never a model-supplied SQL fragment.
            # DATE_TRUNC works in both DuckDB and PostgreSQL. Group on the full
            # bucket start, so quarters/months from different years stay apart.
            x_field = f"DATE_TRUNC('{card.x.time_grain}', {x_field})"
        y_expression = aggregate_expression(
            card.y.aggregate,
            card.y.field,
        )

        select_parts = [
            f"{x_field} AS {quote_identifier('x_value')}",
            f"{y_expression} AS {quote_identifier('y_value')}",
        ]
        group_parts = [x_field]

        series_field = None
        if card.series is not None:
            series_field = quote_identifier(card.series.field)
            select_parts.append(
                f"{series_field} AS {quote_identifier('series_value')}"
            )
            group_parts.append(series_field)

        # Сортируем именно по исходному значению X, а не по
        # форматированной подписи. label_* здесь также сортирует
        # по исходному полю: отдельного display-label в данных нет.
        direction = "DESC" if card.x.sort in {"desc", "label_desc"} else "ASC"

        sql = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {plan.table_name}"
            f"{where_clause(filters)} "
            f"GROUP BY {', '.join(group_parts)} "
            f"ORDER BY {x_field} {direction}"
        )

        if series_field is not None:
            # Для одинаковых X сохраняем стабильный порядок серий.
            sql += f", {series_field} ASC"

        sql += f" LIMIT {card.limit}"

        result = self.sources.query(
            plan.source_id,
            sql,
            row_limit=card.limit,
        )

        points: list[dict[str, Any]] = []

        for row in result.rows:
            point = {
                "x": normalize_sql_value(row[0]),
                "y": normalize_sql_value(row[1]),
            }

            if card.series is not None:
                point["series"] = normalize_sql_value(row[2])

            points.append(point)

        return {
            "x": {
                "field": card.x.field,
                "label": card.x.label or card.x.field,
                "type": card.x.type,
                "time_grain": card.x.time_grain,
            },
            "y": {
                "field": card.y.field,
                "label": card.y.label or card.y.field,
                "aggregate": card.y.aggregate,
                "format": card.y.format.model_dump(mode="json"),
            },
            "series_field": (
                card.series.field if card.series is not None else None
            ),
            "points": points,
            "source_id": plan.source_id,
            "limit": card.limit,
            # Это флаг достижения лимита, а не доказательство
            # наличия дополнительных точек.
            "limit_reached": len(points) == card.limit,
            "provenance": [
                item.model_dump(mode="json")
                for item in result.provenance
            ],
        }
