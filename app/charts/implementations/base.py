from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.charts.models import ChartDefinition, DashboardFilter
from app.charts.query_planner import QueryPlanner
from app.source_service import SourceService


class ChartImplementation(ABC):
    """Базовый класс реализации типа сохранённого чарта."""

    def __init__(
        self,
        sources: SourceService,
        planner: QueryPlanner,
    ) -> None:
        self.sources = sources
        self.planner = planner

    @abstractmethod
    def supports(self, definition: ChartDefinition) -> bool:
        """Проверяет, может ли реализация обработать определение чарта."""

    @abstractmethod
    def execute(
        self,
        definition: ChartDefinition,
        filters: list[DashboardFilter],
    ) -> dict[str, Any]:
        """Валидирует конфигурацию и вычисляет данные чарта."""
