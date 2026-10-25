from __future__ import annotations

from pydantic import ValidationError

from app.charts.errors import ChartError, InvalidDashboardError
from app.charts.executor import ChartExecutor
from app.charts.implementations import (
    KPIImplementation,
    LineImplementation,
)
from app.charts.models import (
    CardResult,
    DashboardResult,
    DashboardSpec,
)
from app.charts.query_planner import QueryPlanner
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService

import logging


logger = logging.getLogger(__name__)


class DashboardEngine:
    def __init__(
        self,
        catalog: SchemaCatalog,
        sources: SourceService,
    ) -> None:
        planner = QueryPlanner(catalog)

        self.executor = ChartExecutor(
            sources=sources,
            planner=planner,
            implementations=[
                KPIImplementation(sources, planner),
                LineImplementation(sources, planner),
            ],
        )

    @staticmethod
    def parse_spec(payload: dict) -> DashboardSpec:
        try:
            return DashboardSpec.model_validate(payload)
        except ValidationError as exc:
            # Не возвращаем LLM внутреннее представление исключения.
            raise InvalidDashboardError(
                "Dashboard specification does not match version 1"
            ) from exc

    def create_dashboard(self, payload: dict) -> dict:
        spec = self.parse_spec(payload)

        results: list[CardResult] = []

        for card in spec.cards:
            filters = [*spec.filters, *card.filters]

            try:
                data = self.executor.execute(card, filters)
                results.append(
                    CardResult(
                        id=card.id,
                        type=card.type,
                        title=card.title,
                        status="success",
                        data=data,
                    )
                )
            except ChartError as exc:
                results.append(
                    CardResult(
                        id=card.id,
                        type=card.type,
                        title=card.title,
                        status="error",
                        error=exc.to_dict(),
                    )
                )
                logger.exception(
                    "Failed to execute dashboard card: card_id=%s, card_type=%s; Have a ChatError",
                    card.id,
                    card.type,
                )
            except Exception:
                # Не передаём наружу текст исключения: в нём могут
                # быть SQL, имена внутренних объектов или конфигурация.
                results.append(
                    CardResult(
                        id=card.id,
                        type=card.type,
                        title=card.title,
                        status="error",
                        error={
                            "code": "execution_error",
                            "message": "Failed to compute this card",
                        },
                    )
                )
                logger.exception(
                    "Failed to execute dashboard card: card_id=%s, card_type=%s",
                    card.id,
                    card.type,
                )

        return DashboardResult(
            title=spec.title,
            summary=spec.summary,
            palette=spec.palette,
            cards=results,
        ).model_dump(mode="json")
