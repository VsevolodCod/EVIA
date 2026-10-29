from __future__ import annotations

from uuid import uuid4
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker, selectinload, Session

from app.charts.models import (
    ChartDefinition,
    ChartModel,
    ChartReference,
    DashboardModel,
)
from app.db.catalog import DashboardORM, DashboardOriginORM, DashboardChartRefORM, ChartORM
from app.ownership import owner_id


SessionMaker = sessionmaker[Session]


class RepositoryError(Exception):
    """Базовая ошибка репозитория."""


class EntityNotFoundError(RepositoryError):
    """Запрошенная сущность не найдена."""


class InvalidStoredDataError(RepositoryError):
    """Данные из БД не соответствуют Pydantic-контракту."""


class ChartRepository:
    """Репозиторий сохранённых чартов."""

    def __init__(self, session_maker: SessionMaker) -> None:
        # Фабрика создаёт отдельную сессию для каждого метода.
        self.session_maker = session_maker

    @staticmethod
    def _to_model(orm: ChartORM) -> ChartModel:
        """Преобразует ORM-сущность в Pydantic-модель."""

        try:
            definition = TypeAdapter(ChartDefinition).validate_python(
                orm.definition
            )
            return ChartModel(
                chart_id=orm.chart_id,
                definition=definition,
                version=orm.version,
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidStoredDataError(
                f"Stored chart '{orm.chart_id}' has an invalid definition"
            ) from exc

    @staticmethod
    def _to_orm(chart: ChartModel) -> ChartORM:
        """Преобразует Pydantic-модель в ORM-сущность."""

        return ChartORM(
            chart_id=chart.chart_id,
            definition=chart.definition.model_dump(mode="json"),
            version=chart.version,
            owner_id=owner_id(),
        )

    def create(self, chart: ChartModel) -> ChartModel:
        """Создаёт и сохраняет новый чарт."""

        with self.session_maker() as session:
            with session.begin():
                orm = self._to_orm(chart)
                session.add(orm)
                session.flush()
                result = self._to_model(orm)

            return result

    def create_from_definition(
        self,
        definition: dict[str, Any],
        *,
        chart_id: str | None = None,
        version: int = 1,
    ) -> ChartModel:
        """Создаёт чарт из словаря конфигурации."""

        try:
            parsed_definition = TypeAdapter(
                ChartDefinition
            ).validate_python(definition)
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidStoredDataError(
                "Chart definition does not match a supported chart type"
            ) from exc

        chart = ChartModel(
            chart_id=chart_id or str(uuid4()),
            definition=parsed_definition,
            version=version,
        )
        return self.create(chart)

    def get_by_id(self, chart_id: str) -> ChartModel | None:
        """Возвращает чарт по ID либо None."""

        with self.session_maker() as session:
            statement = select(ChartORM).where(
                ChartORM.chart_id == chart_id
            )
            if owner_id() is not None:
                statement = statement.where(ChartORM.owner_id == owner_id())
            orm = session.scalar(statement)

            if orm is None:
                return None

            return self._to_model(orm)

    def list_all(self, limit: int = 100) -> list[ChartModel]:
        """Возвращает список сохранённых чартов."""

        if limit < 1:
            raise ValueError("limit must be greater than zero")

        with self.session_maker() as session:
            statement = (
                select(ChartORM)
                .order_by(ChartORM.chart_id)
                .limit(limit)
            )
            if owner_id() is not None:
                statement = statement.where(ChartORM.owner_id == owner_id())
            result = session.scalars(statement)
            return [self._to_model(orm) for orm in result.all()]

    def delete(self, chart_id: str) -> bool:
        """Удаляет чарт, если он существует."""

        with self.session_maker() as session:
            with session.begin():
                orm = session.get(ChartORM, chart_id)

                if orm is None or (owner_id() is not None and orm.owner_id != owner_id()):
                    return False

                session.delete(orm)
                session.flush()
                return True


class DashboardRepository:
    """Репозиторий дашбордов и ссылок на сохранённые чарты."""

    def __init__(self, session_maker: SessionMaker) -> None:
        self.session_maker = session_maker

    @staticmethod
    def _to_model(orm: DashboardORM) -> DashboardModel:
        """Преобразует ORM-сущность дашборда в Pydantic-модель."""

        try:
            return DashboardModel(
                id=orm.dashboard_id,
                title=orm.title,
                summary=orm.summary,
                version=orm.version,
                charts=[
                    ChartReference(
                        chart_id=ref.chart_id,
                        position=ref.position,
                    )
                    for ref in sorted(
                        orm.chart_refs,
                        key=lambda item: item.position,
                    )
                ],
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidStoredDataError(
                f"Stored dashboard '{orm.dashboard_id}' is invalid"
            ) from exc

    def create(self, dashboard: DashboardModel) -> DashboardModel:
        """Создаёт дашборд вместе со ссылками на чарты."""

        with self.session_maker() as session:
            with session.begin():
                orm = DashboardORM(
                    dashboard_id=dashboard.id,
                    title=dashboard.title,
                    summary=dashboard.summary,
                    version=dashboard.version,
                    owner_id=owner_id(),
                    chart_refs=[
                        DashboardChartRefORM(
                            chart_id=ref.chart_id,
                            position=ref.position,
                        )
                        for ref in dashboard.charts
                    ],
                )

                session.add(orm)
                session.flush()
                result = self._to_model(orm)

            return result

    def get_by_id(self, dashboard_id: str) -> DashboardModel | None:
        """Возвращает дашборд вместе с упорядоченными ссылками."""

        with self.session_maker() as session:
            statement = (
                select(DashboardORM)
                .where(DashboardORM.dashboard_id == dashboard_id)
                .options(selectinload(DashboardORM.chart_refs))
            )
            if owner_id() is not None:
                statement = statement.where(DashboardORM.owner_id == owner_id())
            orm = session.scalar(statement)

            if orm is None:
                return None

            return self._to_model(orm)

    def origin_chat_id(self, dashboard_id: str) -> str | None:
        """Only reveal an origin for a dashboard visible to the current owner."""
        with self.session_maker() as session:
            statement = (
                select(DashboardOriginORM.chat_id)
                .join(DashboardORM, DashboardORM.dashboard_id == DashboardOriginORM.dashboard_id)
                .where(DashboardORM.dashboard_id == dashboard_id)
            )
            if owner_id() is not None:
                statement = statement.where(DashboardORM.owner_id == owner_id())
            return session.scalar(statement)

    def set_origin_chat(self, dashboard_id: str, chat_id: str) -> None:
        """Record the first originating chat; later edits do not replace it."""
        with self.session_maker() as session:
            with session.begin():
                dashboard = session.get(DashboardORM, dashboard_id)
                if dashboard is None or (owner_id() is not None and dashboard.owner_id != owner_id()):
                    raise EntityNotFoundError("Dashboard not found")
                if session.get(DashboardOriginORM, dashboard_id) is None:
                    session.add(DashboardOriginORM(dashboard_id=dashboard_id, chat_id=chat_id))

    def update(self, dashboard: DashboardModel) -> DashboardModel:
        """Обновляет метаданные и полный список ссылок дашборда."""

        with self.session_maker() as session:
            with session.begin():
                statement = (
                    select(DashboardORM)
                    .where(DashboardORM.dashboard_id == dashboard.id)
                    .options(selectinload(DashboardORM.chart_refs))
                )
                if owner_id() is not None:
                    statement = statement.where(DashboardORM.owner_id == owner_id())
                orm = session.scalar(statement)

                if orm is None:
                    raise EntityNotFoundError(
                        f"Dashboard '{dashboard.id}' does not exist"
                    )

                orm.title = dashboard.title
                orm.summary = dashboard.summary
                orm.version = dashboard.version

                orm.chart_refs = [
                    DashboardChartRefORM(
                        dashboard_id=dashboard.id,
                        chart_id=ref.chart_id,
                        position=ref.position,
                    )
                    for ref in dashboard.charts
                ]

                session.flush()
                result = self._to_model(orm)

            return result

    def delete(self, dashboard_id: str) -> bool:
        """Удаляет дашборд; его ссылки удаляются каскадно."""

        with self.session_maker() as session:
            with session.begin():
                orm = session.get(DashboardORM, dashboard_id)

                if orm is None or (owner_id() is not None and orm.owner_id != owner_id()):
                    return False

                origin = session.get(DashboardOriginORM, dashboard_id)
                if origin is not None:
                    session.delete(origin)
                session.delete(orm)
                session.flush()
                return True

    def reorder(self, dashboard_id: str, chart_ids: list[str], expected_version: int) -> DashboardModel | None:
        """Change positions in one transaction without replacing chart-reference rows."""
        with self.session_maker() as session:
            with session.begin():
                statement = (
                    select(DashboardORM)
                    .where(DashboardORM.dashboard_id == dashboard_id)
                    .options(selectinload(DashboardORM.chart_refs))
                    .with_for_update()
                )
                if owner_id() is not None:
                    statement = statement.where(DashboardORM.owner_id == owner_id())
                orm = session.scalar(statement)
                if orm is None:
                    return None
                if orm.version != expected_version:
                    raise ValueError("version_conflict")
                current_ids = {ref.chart_id for ref in orm.chart_refs}
                if len(chart_ids) != len(orm.chart_refs) or set(chart_ids) != current_ids:
                    raise ValueError("invalid_chart_order")
                positions = {chart_id: index for index, chart_id in enumerate(chart_ids)}
                for ref in orm.chart_refs:
                    ref.position = positions[ref.chart_id]
                orm.version += 1
                session.flush()
                return self._to_model(orm)

    def list_all(self, limit: int = 100, offset: int = 0) -> list[DashboardModel]:
        """Возвращает дашборды вместе с их ссылками на чарты."""

        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must not be negative")

        with self.session_maker() as session:
            statement = (
                select(DashboardORM)
                .options(selectinload(DashboardORM.chart_refs))
                .order_by(DashboardORM.dashboard_id)
                .limit(limit)
                .offset(offset)
            )
            if owner_id() is not None:
                statement = statement.where(DashboardORM.owner_id == owner_id())
            result = session.scalars(statement)
            return [self._to_model(orm) for orm in result.all()]
