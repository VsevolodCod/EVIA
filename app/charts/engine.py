from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.charts.models import (
    AddChartToDashboardArgs,
    ChartModel,
    ComposeDashboardArgs,
    DashboardModel,
    DashboardToolResult,
    ChartToolResult,
    ChartReference,
    GetDashboardArgs,
    GetChartArgs,
    RemoveChartFromDashboardArgs,
    ToolError,
)

from app.charts.repositories import ChartRepository, DashboardRepository

logger = logging.getLogger(__name__)


class DashboardEngine:
    """
    Координирует операции над дашбордами и сохранёнными чартами.

    Этот класс не создаёт и не регистрирует типы чартов и не вычисляет
    их данные. Он использует репозитории, которые необходимо реализовать
    отдельно на SQLAlchemy.
    """

    def __init__(self, charts: ChartRepository, dashboards: DashboardRepository) -> None:
        self.charts = charts
        self.dashboards = dashboards

    @staticmethod
    def _parse(
        model_type: type,
        payload: dict[str, Any],
        error_message: str,
    ) -> Any:
        """Валидирует словарь по Pydantic-модели и нормализует ошибку."""

        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(error_message) from exc

    @staticmethod
    def _error(code: str, message: str) -> ToolError:
        """Создаёт безопасную для агента структурированную ошибку."""

        return ToolError(code=code, message=message)

    @staticmethod
    def _dashboard_result(
        dashboard: DashboardModel | None = None,
        error: ToolError | None = None,
    ) -> dict[str, Any]:
        """Формирует сериализуемый ответ инструмента дашбордов."""

        return DashboardToolResult(
            success=dashboard is not None and error is None,
            dashboard=dashboard,
            error=error,
        ).model_dump(mode="json")

    @staticmethod
    def _chart_result(
        chart: ChartModel | None = None,
        error: ToolError | None = None,
    ) -> dict[str, Any]:
        """Формирует сериализуемый ответ инструмента чартов."""

        return ChartToolResult(
            success=chart is not None and error is None,
            chart=chart,
            error=error,
        ).model_dump(mode="json")

    def compose_dashboard(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Создаёт дашборд из ID существующих чартов.

        Проверяет все ID до сохранения, чтобы не создавать дашборд,
        содержащий ссылки на несуществующие чарты.
        """

        try:
            args = self._parse(
                ComposeDashboardArgs,
                payload,
                "Invalid compose_dashboard arguments",
            )
        except ValueError:
            return self._dashboard_result(
                error=self._error("invalid_arguments", "Invalid dashboard arguments")
            )

        try:
            chart_models: list[ChartModel] = []
            for chart_id in args.chart_ids:
                chart = self.charts.get_by_id(chart_id)
                if chart is None:
                    return self._dashboard_result(
                        error=self._error(
                            "chart_not_found",
                            f"Chart '{chart_id}' does not exist",
                        )
                    )
                chart_models.append(chart)

            dashboard_id = str(uuid4())
            dashboard = DashboardModel(
                id=dashboard_id,
                title=args.title,
                summary=args.summary,
                charts=[
                    ChartReference(chart_id=chart.id, position=position)
                    for position, chart in enumerate(chart_models)
                ],
                version=1,
            )

            saved = self.dashboards.create(dashboard)
            return self._dashboard_result(dashboard=saved)

        except Exception:
            logger.exception("Failed to compose dashboard")
            return self._dashboard_result(
                error=self._error(
                    "dashboard_creation_failed",
                    "Failed to create dashboard",
                )
            )

    def add_chart_to_dashboard(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Добавляет сохранённый чарт в дашборд.

        Если position не передана, добавляет в конец. После вставки
        перенумеровывает позиции, чтобы они шли подряд от нуля.
        """

        try:
            args = self._parse(
                AddChartToDashboardArgs,
                payload,
                "Invalid add_chart_to_dashboard arguments",
            )
        except ValueError:
            return self._dashboard_result(
                error=self._error("invalid_arguments", "Invalid add-chart arguments")
            )

        try:
            dashboard = self.dashboards.get_by_id(args.dashboard_id)
            if dashboard is None:
                return self._dashboard_result(
                    error=self._error("dashboard_not_found", "Dashboard not found")
                )

            chart = self.charts.get_by_id(args.chart_id)
            if chart is None:
                return self._dashboard_result(
                    error=self._error("chart_not_found", "Chart not found")
                )

            if any(ref.chart_id == chart.id for ref in dashboard.charts):
                return self._dashboard_result(
                    error=self._error(
                        "chart_already_added",
                        "This chart is already on the dashboard",
                    )
                )

            refs = sorted(dashboard.charts, key=lambda ref: ref.position)
            position = len(refs) if args.position is None else args.position

            if position > len(refs):
                return self._dashboard_result(
                    error=self._error(
                        "invalid_position",
                        "Position cannot exceed the number of charts",
                    )
                )

            refs.insert(
                position,
                ChartReference(chart_id=chart.id, position=position),
            )
            normalized_refs = [
                ChartReference(chart_id=ref.chart_id, position=index)
                for index, ref in enumerate(refs)
            ]

            updated = dashboard.model_copy(
                update={
                    "charts": normalized_refs,
                    "version": dashboard.version + 1,
                }
            )
            saved = self.dashboards.update(updated)
            return self._dashboard_result(dashboard=saved)

        except Exception:
            logger.exception("Failed to add chart to dashboard")
            return self._dashboard_result(
                error=self._error(
                    "dashboard_update_failed",
                    "Failed to update dashboard",
                )
            )

    def remove_chart_from_dashboard(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Удаляет ссылку на чарт из дашборда и уплотняет позиции."""

        try:
            args = self._parse(
                RemoveChartFromDashboardArgs,
                payload,
                "Invalid remove_chart_from_dashboard arguments",
            )
        except ValueError:
            return self._dashboard_result(
                error=self._error(
                    "invalid_arguments",
                    "Invalid remove-chart arguments",
                )
            )

        try:
            dashboard = self.dashboards.get_by_id(args.dashboard_id)
            if dashboard is None:
                return self._dashboard_result(
                    error=self._error("dashboard_not_found", "Dashboard not found")
                )

            if not any(ref.chart_id == args.chart_id for ref in dashboard.charts):
                return self._dashboard_result(
                    error=self._error(
                        "chart_not_on_dashboard",
                        "The chart is not on this dashboard",
                    )
                )

            refs = sorted(
                (ref for ref in dashboard.charts if ref.chart_id != args.chart_id),
                key=lambda ref: ref.position,
            )
            normalized_refs = [
                ChartReference(chart_id=ref.chart_id, position=index)
                for index, ref in enumerate(refs)
            ]

            updated = dashboard.model_copy(
                update={
                    "charts": normalized_refs,
                    "version": dashboard.version + 1,
                }
            )
            saved = self.dashboards.update(updated)
            return self._dashboard_result(dashboard=saved)

        except Exception:
            logger.exception("Failed to remove chart from dashboard")
            return self._dashboard_result(
                error=self._error(
                    "dashboard_update_failed",
                    "Failed to update dashboard",
                )
            )

    def get_dashboard(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Возвращает сохранённый дашборд вместе с конфигурациями его чартов.

        Метод возвращает определения чартов, а не вычисленные результаты.
        Выполнение запросов данных должно оставаться в отдельном слое.
        """

        try:
            args = self._parse(
                GetDashboardArgs,
                payload,
                "Invalid get_dashboard arguments",
            )
        except ValueError:
            return {
                "success": False,
                "error": self._error(
                    "invalid_arguments",
                    "Invalid dashboard arguments",
                ).model_dump(mode="json"),
            }

        try:
            dashboard = self.dashboards.get_by_id(args.dashboard_id)
            if dashboard is None:
                return {
                    "success": False,
                    "error": self._error(
                        "dashboard_not_found",
                        "Dashboard not found",
                    ).model_dump(mode="json"),
                }

            chart_items: list[dict[str, Any]] = []
            for ref in sorted(dashboard.charts, key=lambda item: item.position):
                chart = self.charts.get_by_id(ref.chart_id)
                if chart is None:
                    chart_items.append({
                        "chart_id": ref.chart_id,
                        "position": ref.position,
                        "status": "error",
                        "error": {
                            "code": "chart_not_found",
                            "message": "Saved chart definition was not found",
                        },
                    })
                    continue

                chart_items.append({
                    "chart_id": chart.id,
                    "position": ref.position,
                    "status": "success",
                    "chart": chart.model_dump(mode="json"),
                })

            return {
                "success": True,
                "dashboard": dashboard.model_dump(mode="json"),
                "charts": chart_items,
            }

        except Exception:
            logger.exception("Failed to retrieve dashboard")
            return {
                "success": False,
                "error": self._error(
                    "dashboard_read_failed",
                    "Failed to retrieve dashboard",
                ).model_dump(mode="json"),
            }

    def get_chart(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Возвращает конфигурацию сохранённого чарта по ID."""

        try:
            args = self._parse(
                GetChartArgs,
                payload,
                "Invalid get_chart arguments",
            )
        except ValueError:
            return self._chart_result(
                error=self._error("invalid_arguments", "Invalid chart arguments")
            )

        try:
            chart = self.charts.get_by_id(args.chart_id)
            if chart is None:
                return self._chart_result(
                    error=self._error("chart_not_found", "Chart not found")
                )
            return self._chart_result(chart=chart)

        except Exception:
            logger.exception("Failed to retrieve chart")
            return self._chart_result(
                error=self._error(
                    "chart_read_failed",
                    "Failed to retrieve chart",
                )
            )
