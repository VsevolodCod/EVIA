from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import (
    MetaData,
    Table,
    case,
    create_engine,
    func,
    inspect,
    select,
)
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import SQLAlchemyError

from app.connection_manager import ConnectionManager
from app.data_sources.base import DataSourceAdapter
from app.models import (
    ClickHouseConnection,
    ClickHouseProperties,
    DataSource,
    SchemaField,
    SchemaObject,
    SourceSchema,
)

logger = logging.getLogger(__name__)


def inspect_clickhouse_connection(
    properties: ClickHouseProperties,
) -> list[tuple[str, str]]:
    """
    Проверяет подключение и возвращает список доступных
    таблиц и представлений в базе ClickHouse.

    Результат:
        [
            ("default", "users"),
            ("analytics", "events"),
        ]
    """
    url = URL.create(
        "clickhousedb+connect",
        username=properties.username,
        password=properties.password.get_secret_value(),
        host=properties.host,
        port=properties.port,
        database=properties.database,
        query={"secure": str(properties.secure).lower()},
    )

    engine = create_engine(url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

            inspector = inspect(connection)
            objects: list[tuple[str, str]] = []

            excluded_databases = {
                "system",
                "INFORMATION_SCHEMA",
                "information_schema",
            }

            for database in inspector.get_schema_names():
                if database in excluded_databases:
                    continue

                logger.info(
                    "Inspecting ClickHouse database: %s",
                    database,
                )

                tables = inspector.get_table_names(schema=database)
                views = inspector.get_view_names(schema=database)

                logger.info(
                    "Found %d tables and %d views in database %s",
                    len(tables),
                    len(views),
                    database,
                )

                objects.extend(
                    (database, table)
                    for table in tables
                )
                objects.extend(
                    (database, view)
                    for view in views
                )

            if not objects:
                raise ValueError("Подключение успешно, но доступных таблиц и представлений нет")

            return objects

    except SQLAlchemyError:
        logger.exception("Failed to inspect ClickHouse connection")
        raise

    finally:
        engine.dispose()


class ClickHouseAdapter(DataSourceAdapter):
    """
    Читает структуру и данные ClickHouse через SQLAlchemy Core.
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
    ) -> None:
        self.connection_manager = connection_manager

    def _create_engine(self, source: DataSource) -> Engine:
        """
        Создаёт SQLAlchemy Engine для нужного источника.
        """
        connection = self.connection_manager.get_connection(
            source.connection_id
        )

        if not isinstance(connection, ClickHouseConnection):
            raise ValueError("Connection is not ClickHouse")

        properties = connection.properties

        url = URL.create(
            "clickhousedb+connect",
            username=properties.username,
            password=properties.password.get_secret_value(),
            host=properties.host,
            port=properties.port,
            database=properties.database,
        )

        return create_engine(
            url,
            pool_pre_ping=True,
            pool_timeout=10,
        )

    def test_connection(
        self,
        source: DataSource,
    ) -> tuple[bool, str]:
        """
        Проверяет соединение простым SELECT 1.
        """
        engine = None

        try:
            engine = self._create_engine(source)

            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")

            return True, "Подключение к ClickHouse успешно"

        except (SQLAlchemyError, ValueError, TypeError):
            logger.exception("ClickHouse connection test failed")
            return False, "Ошибка подключения к ClickHouse"

        finally:
            if engine is not None:
                engine.dispose()

    @staticmethod
    def _make_object_id(
        source_id: str,
        schema_name: str,
        table_name: str,
    ) -> str:
        """
        Формирует ID объекта в рамках источника.

        В ClickHouse schema_name соответствует имени базы данных.
        """
        return f"{source_id}:{schema_name}.{table_name}"

    def introspect_schema(
        self,
        source: DataSource,
    ) -> SourceSchema:
        """
        Читает структуру выбранной таблицы или представления.

        В ClickHouse schema_name — имя базы данных.
        """
        if not source.table_name:
            raise ValueError("У источника не указано имя таблицы")

        engine = self._create_engine(source)

        try:
            with engine.connect() as connection:
                inspector = inspect(connection)

                if source.schema_name:
                    database_name = source.schema_name
                    table_name = source.table_name

                elif "." in source.table_name:
                    database_name, table_name = (
                        source.table_name.split(".", 1)
                    )

                else:
                    database_name = connection.exec_driver_sql(
                        "SELECT currentDatabase()"
                    ).scalar_one()
                    table_name = source.table_name

                if not database_name or not table_name:
                    raise ValueError(
                        "Не удалось определить базу данных "
                        "и имя объекта"
                    )

                if not inspector.has_table(
                    table_name,
                    schema=database_name,
                ):
                    raise ValueError(
                        f"Объект {database_name}.{table_name} не найден"
                    )

                views = set(
                    inspector.get_view_names(schema=database_name)
                )

                object_type = (
                    "view" if table_name in views else "table"
                )

                columns = inspector.get_columns(
                    table_name,
                    schema=database_name,
                )

                # ClickHouse не предоставляет универсальную модель
                # внешних ключей, аналогичную PostgreSQL.
                # Поэтому не объявляем колонки первичными ключами
                # и не выдумываем связи между таблицами.
                fields = [
                    SchemaField(
                        name=column["name"],
                        inferred_type=str(column["type"]),
                        nullable=column.get("nullable"),
                        is_identifier_candidate=False,
                    )
                    for column in columns
                ]

                object_id = self._make_object_id(
                    source.source_id,
                    database_name,
                    table_name,
                )

                schema_object = SchemaObject(
                    object_id=object_id,
                    name=f"{database_name}.{table_name}",
                    object_type=object_type,
                    fields=fields,
                )

                return SourceSchema(
                    source_id=source.source_id,
                    objects=[schema_object],
                    relations=[],
                )

        finally:
            engine.dispose()

    @staticmethod
    def _reflect_table(engine: Engine, object_name: str) -> Table:
        """
        Получает SQLAlchemy-описание существующего объекта.

        Поддерживаемые форматы:
            analytics.events
            events

        Для имени без базы используется текущая база соединения.
        """
        parts = object_name.split(".")

        if len(parts) == 2 and all(parts):
            database_name, table_name = parts

        elif len(parts) == 1 and parts[0]:
            table_name = parts[0]

            with engine.connect() as connection:
                database_name = connection.exec_driver_sql(
                    "SELECT currentDatabase()"
                ).scalar_one()

        else:
            raise ValueError(
                "Имя объекта должно иметь формат table "
                "или database.table"
            )

        inspector = inspect(engine)

        exists = inspector.has_table(
            table_name,
            schema=database_name,
        ) or table_name in inspector.get_view_names(
            schema=database_name
        )

        if not exists:
            raise ValueError(
                f"Объект {object_name!r} не найден"
            )

        return Table(
            table_name,
            MetaData(),
            schema=database_name,
            autoload_with=engine,
        )

    def preview(
        self,
        source: DataSource,
        object_name: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Возвращает первые limit строк объекта.
        """
        if not 1 <= limit <= 1000:
            raise ValueError("limit должен быть от 1 до 1000")

        engine = self._create_engine(source)

        try:
            table = self._reflect_table(engine, object_name)
            query = select(table).limit(limit)

            with engine.connect() as connection:
                result = connection.execute(query)

                return [
                    dict(row)
                    for row in result.mappings().all()
                ]

        finally:
            engine.dispose()

    def profile(
        self,
        source: DataSource,
        object_name: str,
    ) -> dict[str, Any]:
        """
        Собирает точную статистику по таблице:
        количество строк, NULL и уникальных значений.

        Для больших таблиц точное профилирование может быть дорогим.
        """
        engine = self._create_engine(source)

        try:
            table = self._reflect_table(engine, object_name)

            with engine.connect() as connection:
                row_count = connection.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()

                expressions = []

                for index, column in enumerate(table.columns):
                    # Считаем NULL через CASE + SUM.
                    expressions.append(
                        func.sum(
                            case(
                                (column.is_(None), 1),
                                else_=0,
                            )
                        ).label(f"null_{index}")
                    )

                    # uniqExact — точный подсчёт уникальных
                    # НЕ-NULL значений в ClickHouse.
                    expressions.append(
                        func.uniqExact(column).label(
                            f"distinct_{index}"
                        )
                    )

                if expressions:
                    stats = connection.execute(
                        select(*expressions).select_from(table)
                    ).mappings().one()
                else:
                    stats = {}

                columns: dict[str, Any] = {}

                for index, column in enumerate(table.columns):
                    null_count = stats.get(f"null_{index}") or 0
                    distinct_count = (
                        stats.get(f"distinct_{index}") or 0
                    )

                    columns[column.name] = {
                        "type": str(column.type),
                        "nullable": column.nullable,
                        "null_count": null_count,
                        "null_fraction": (
                            null_count / row_count
                            if row_count
                            else 0.0
                        ),
                        "distinct_count": distinct_count,
                    }

                return {
                    "source_type": "clickhouse",
                    "table": object_name,
                    "row_count": row_count,
                    "column_count": len(table.columns),
                    "columns": columns,
                }

        finally:
            engine.dispose()
