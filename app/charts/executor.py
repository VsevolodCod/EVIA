from __future__ import annotations

from typing import Any

from app.charts.errors import UnsupportedTypeError
from app.charts.implementations.base import ChartImplementation
from app.charts.models import (
    ChartModel,
    ChartDefinition,
    DashboardFilter,
)
from app.charts.query_planner import QueryPlanner
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.charts.repositories import ChartRepository


class ChartExecutor:
    """Выполняет сохранённые чарты по их ID."""

    def __init__(
            self,
            sources: SourceService,
            planner: QueryPlanner,
            charts: ChartRepository,
            implementations: list[ChartImplementation] | None = None,
    ) -> None:
        self.sources = sources
        self.planner = planner
        self.charts = charts
        self.implementations = implementations or []

    def register(self, implementation: ChartImplementation) -> None:
        """Регистрирует реализацию типа чарта."""
        self.implementations.append(implementation)

    def execute(
            self,
            chart_id: str,
            filters: list[DashboardFilter] | None = None,
    ) -> dict[str, Any]:
        """Загружает сохранённый чарт и выполняет его."""

        chart = self.charts.get_by_id(chart_id)
        if chart is None:
            raise ValueError(f"Chart '{chart_id}' does not exist")

        definition = chart.definition
        effective_filters = [*definition.filters, *(filters or [])]

        for implementation in self.implementations:
            if implementation.supports(definition):
                return implementation.execute(definition, effective_filters)

        raise UnsupportedTypeError(
            f"Chart type '{definition.type}' is not implemented"
        )

    @staticmethod
    def build_executor(
            sources: SourceService,
            catalog: SchemaCatalog,
            charts: ChartRepository
    ) -> ChartExecutor:
        planner = QueryPlanner(catalog)

        executor = ChartExecutor(
            sources=sources,
            planner=planner,
            charts=charts
        )
        from app.charts.implementations import charts_implementations

        for chart_class in charts_implementations:
            chart = chart_class(sources, planner)
            executor.register(chart)

        return executor
