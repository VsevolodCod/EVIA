from __future__ import annotations

from typing import Any

from app.charts.aggregation import (
    aggregate_expression,
    normalize_sql_value,
    quote_identifier,
    where_clause,
)
from app.charts.implementations.base import ChartImplementation
from app.charts.models import ChartDefinition, DashboardFilter, LineCard


class LineImplementation(ChartImplementation):
    def supports(self, card: ChartDefinition) -> bool:
        return isinstance(card, LineCard)

    def execute(
            self,
            card: ChartDefinition,
            filters: list[DashboardFilter],
    ) -> dict[str, Any]:
        if not isinstance(card, LineCard):
            raise TypeError("LineImplementation only supports line cards")

        plan = self.planner.plan(card, filters)

        # В рамках одного SQL-запроса все поля должны относиться
        # к одному источнику данных.
        source_ids = {
            card.x.field.source_id,
            card.y.field.source_id,
        }
        if card.series is not None:
            source_ids.add(card.series.source_id)

        source_ids.update(item.field.source_id for item in filters)
        source_ids.update(
            item.field.source_id
            for item in card.filters
        )

        if len(source_ids) != 1:
            raise ValueError(
                "Line chart fields and filters must belong to the same source"
            )

        source_id = next(iter(source_ids))

        if source_id != plan.source_id:
            raise ValueError(
                "Planned source_id does not match the chart field source_id"
            )

        # FieldRef.field содержит имя колонки, а не сам объект FieldRef.
        x_field = quote_identifier(card.x.field.field)
        y_expression = aggregate_expression(
            card.y.aggregate,
            card.y.field.field,
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

        # Сортировка выполняется по исходному значению X.
        direction = (
            "DESC"
            if card.x.sort in {"desc", "label_desc"}
            else "ASC"
        )

        # Объединяем фильтры карточки и фильтры дашборда.
        all_filters = [*card.filters, *filters]

        sql = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {plan.table_name}"
            f"{where_clause(all_filters)} "
            f"GROUP BY {', '.join(group_parts)} "
            f"ORDER BY {x_field} {direction}"
        )

        if series_field is not None:
            sql += f", {series_field} ASC"

        sql += f" LIMIT {card.limit}"

        result = self.sources.query(
            source_id,
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
                "field": card.x.field.model_dump(mode="json"),
                "label": card.x.label or card.x.field.field,
                "type": card.x.type,
            },
            "y": {
                "field": card.y.field.model_dump(mode="json"),
                "label": card.y.label or card.y.field.field,
                "aggregate": card.y.aggregate,
                "format": card.y.format.model_dump(mode="json"),
            },
            "series_field": (
                card.series.model_dump(mode="json")
                if card.series is not None
                else None
            ),
            "points": points,
            "limit": card.limit,
            "limit_reached": len(points) == card.limit,
            "provenance": [
                item.model_dump(mode="json")
                for item in result.provenance
            ],
        }
