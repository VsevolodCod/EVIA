from __future__ import annotations

from typing import Any

from app.charts.errors import UnsupportedTypeError
from app.charts.implementations.base import ChartImplementation
from app.charts.models import DashboardCard, DashboardFilter
from app.charts.query_planner import QueryPlanner
from app.source_service import SourceService


class ChartExecutor:
    def __init__(
        self,
        sources: SourceService,
        planner: QueryPlanner,
        implementations: list[ChartImplementation] | None = None,
    ) -> None:
        self.sources = sources
        self.planner = planner
        self.implementations = implementations or []

    def register(self, implementation: ChartImplementation) -> None:
        self.implementations.append(implementation)

    def execute(
        self,
        card: DashboardCard,
        filters: list[DashboardFilter],
    ) -> dict[str, Any]:
        for implementation in self.implementations:
            if implementation.supports(card):
                return implementation.execute(card, filters)

        raise UnsupportedTypeError(
            f"Chart type '{card.type}' is not implemented"
        )
