from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.charts.models import DashboardCard, DashboardFilter
from app.charts.query_planner import QueryPlanner
from app.source_service import SourceService


class ChartImplementation(ABC):
    def __init__(
        self,
        sources: SourceService,
        planner: QueryPlanner,
    ) -> None:
        self.sources = sources
        self.planner = planner

    @abstractmethod
    def supports(self, card: DashboardCard) -> bool:
        """Проверяет, может ли реализация обработать карточку."""

    @abstractmethod
    def execute(
        self,
        card: DashboardCard,
        filters: list[DashboardFilter],
    ) -> dict[str, Any]:
        """Валидирует и вычисляет данные одной карточки."""
