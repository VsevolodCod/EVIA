from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.charts.errors import ChartExecutionError
from app.charts.implementations.line import LineImplementation
from app.charts.models import ChartDefinition, DashboardFilter, PieCard


class PieImplementation(LineImplementation):
    """Reuse guarded category aggregation, then require complete positive slices."""

    def supports(self, card: ChartDefinition) -> bool:
        return isinstance(card, PieCard)

    def execute(self, card: ChartDefinition, filters: list[DashboardFilter]) -> dict[str, Any]:
        if not isinstance(card, PieCard):
            raise TypeError("PieImplementation only supports pie cards")
        # Fetch one extra group to distinguish a complete result from a
        # truncated one. Partial categories must never be shown as 100%.
        result = super().execute(card.model_copy(update={"limit": card.limit + 1}), filters)
        if len(result["points"]) > card.limit:
            raise ChartExecutionError("Pie chart has more categories than its limit")
        total = Decimal(0)
        for point in result["points"]:
            try:
                value = Decimal(str(point["y"]))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ChartExecutionError("Pie chart contains a nonnumeric value") from exc
            if not value.is_finite() or value < 0:
                raise ChartExecutionError("Pie chart requires finite nonnegative values")
            total += value
        if total <= 0:
            raise ChartExecutionError("Pie chart requires at least one positive value")
        result["limit"] = card.limit
        result["limit_reached"] = False
        return result
