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
    DataSource,
    SQLiteConnection,
    SchemaField,
    SchemaObject,
    SchemaRelation,
    SourceSchema,
)

logger = logging.getLogger(__name__)


def inspect_sqlite_connection(path: str) -> list[tuple[str, str]]:
    """
    Проверяет SQLite-файл и возвращает доступные таблицы
    и представления.

    Результат:
        [
            ("main", "users"), ("main", "orders")
        ]
    """
    url = URL.create(
        "sqlite+pysqlite",
        database=path,
    )
    engine = create_engine(url)

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
            inspector = inspect(connection)

            objects: list[tuple[str, str]] = []

            for schema_name in inspector.get_schema_names():
                if schema_name == "temp":
                    continue

                tables = inspector.get_table_names(
                    schema=schema_name,
                )
                views = inspector.get_view_names(
                    schema=schema_name,
                )

                objects.extend(
                    (schema_name, name)
                    for name in tables
                )
                objects.extend(
                    (schema_name, name)
                    for name in views
                )

            if not objects:
                raise ValueError("SQLite-файл доступен, но таблиц и представлений нет")

            return objects

    except SQLAlchemyError:
        logger.exception("Failed to inspect SQLite database")
        raise

    finally:
        engine.dispose()


class SQLiteAdapter(DataSourceAdapter):
    """
    Читает схему и данные SQLite.
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
    ) -> None:
        self.connection_manager = connection_manager

    def _create_engine(self, source: DataSource) -> Engine:
        connection = self.connection_manager.get_connection(
            source.connection_id,
        )

        if not isinstance(connection, SQLiteConnection):
            raise ValueError("Connection is not SQLite")

        if not connection.path:
            raise ValueError("SQLite path is empty")

        url = URL.create(
            "sqlite+pysqlite",
            database=connection.path,
        )

        return create_engine(
            url,
            connect_args={"timeout": 5},
        )

    def test_connection(
        self,
        source: DataSource,
    ) -> tuple[bool, str]:
        engine = None

        try:
            engine = self._create_engine(source)

            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")

            return True, "Подключение к SQLite успешно"

        except (SQLAlchemyError, ValueError, TypeError):
            logger.exception("SQLite connection test failed")
            return False, "Ошибка подключения к SQLite"

        finally:
            if engine is not None:
                engine.dispose()

    @staticmethod
    def _make_object_id(
        source_id: str,
        schema_name: str,
        table_name: str,
    ) -> str:
        return f"{source_id}:{schema_name}.{table_name}"

    def introspect_schema(
        self,
        source: DataSource,
    ) -> SourceSchema:
        if not source.table_name:
            raise ValueError("У источника не указано имя таблицы")

        engine = self._create_engine(source)

        try:
            with engine.connect() as connection:
                inspector = inspect(connection)

                schema_name = source.schema_name or "main"
                table_name = source.table_name

                if "." in table_name and not source.schema_name:
                    schema_name, table_name = table_name.split(".", 1)

                if not inspector.has_table(
                    table_name,
                    schema=schema_name,
                ):
                    raise ValueError(
                        f"Объект {schema_name}.{table_name} не найден"
                    )

                views = set(
                    inspector.get_view_names(schema=schema_name)
                )
                object_type = (
                    "view" if table_name in views else "table"
                )

                columns = inspector.get_columns(
                    table_name,
                    schema=schema_name,
                )

                primary_key = inspector.get_pk_constraint(
                    table_name,
                    schema=schema_name,
                )
                primary_key_columns = set(
                    primary_key.get("constrained_columns") or []
                )

                object_id = self._make_object_id(
                    source.source_id,
                    schema_name,
                    table_name,
                )

                fields = [
                    SchemaField(
                        name=column["name"],
                        inferred_type=str(column["type"]),
                        nullable=column.get("nullable"),
                        is_identifier_candidate=(
                            column["name"] in primary_key_columns
                        ),
                    )
                    for column in columns
                ]

                schema_object = SchemaObject(
                    object_id=object_id,
                    name=f"{schema_name}.{table_name}",
                    object_type=object_type,
                    fields=fields,
                )

                relations: list[SchemaRelation] = []
                seen_relations: set[tuple[str, str, str, str]] = set()

                def add_foreign_key(
                    fk_schema: str,
                    fk_table: str,
                    constrained_columns: list[str],
                    referred_schema: str,
                    referred_table: str,
                    referred_columns: list[str],
                ) -> None:
                    if (
                        not constrained_columns
                        or len(constrained_columns)
                        != len(referred_columns)
                    ):
                        return

                    left_id = self._make_object_id(
                        source.source_id,
                        fk_schema,
                        fk_table,
                    )
                    right_id = self._make_object_id(
                        source.source_id,
                        referred_schema,
                        referred_table,
                    )

                    for left_field, right_field in zip(
                        constrained_columns,
                        referred_columns,
                    ):
                        key = (
                            left_id,
                            left_field,
                            right_id,
                            right_field,
                        )
                        if key in seen_relations:
                            continue

                        seen_relations.add(key)
                        relations.append(
                            SchemaRelation(
                                left_object_id=left_id,
                                left_field=left_field,
                                right_object_id=right_id,
                                right_field=right_field,
                                discovery_method="foreign_key",
                                confidence=1.0,
                            )
                        )

                # Внешние ключи из выбранной таблицы.
                for fk in inspector.get_foreign_keys(
                    table_name,
                    schema=schema_name,
                ):
                    referred_table = fk.get("referred_table")
                    if not referred_table:
                        continue

                    add_foreign_key(
                        fk_schema=schema_name,
                        fk_table=table_name,
                        constrained_columns=(
                            fk.get("constrained_columns") or []
                        ),
                        referred_schema=(
                            fk.get("referred_schema") or schema_name
                        ),
                        referred_table=referred_table,
                        referred_columns=(
                            fk.get("referred_columns") or []
                        ),
                    )

                # Входящие внешние ключи из других таблиц.
                for candidate_schema in inspector.get_schema_names():
                    if candidate_schema == "temp":
                        continue

                    for candidate_table in inspector.get_table_names(
                        schema=candidate_schema,
                    ):
                        if (
                            candidate_schema == schema_name
                            and candidate_table == table_name
                        ):
                            continue

                        for fk in inspector.get_foreign_keys(
                            candidate_table,
                            schema=candidate_schema,
                        ):
                            if (
                                fk.get("referred_table") != table_name
                                or (
                                    fk.get("referred_schema")
                                    or candidate_schema
                                ) != schema_name
                            ):
                                continue

                            add_foreign_key(
                                fk_schema=candidate_schema,
                                fk_table=candidate_table,
                                constrained_columns=(
                                    fk.get("constrained_columns") or []
                                ),
                                referred_schema=schema_name,
                                referred_table=table_name,
                                referred_columns=(
                                    fk.get("referred_columns") or []
                                ),
                            )

                return SourceSchema(
                    source_id=source.source_id,
                    objects=[schema_object],
                    relations=relations,
                )

        finally:
            engine.dispose()

    @staticmethod
    def _reflect_table(engine: Engine, object_name: str) -> Table:
        parts = object_name.split(".")

        if len(parts) == 2 and all(parts):
            schema_name, table_name = parts
        elif len(parts) == 1 and parts[0]:
            schema_name = "main"
            table_name = parts[0]
        else:
            raise ValueError(
                "Имя объекта должно иметь формат table или schema.table"
            )

        inspector = inspect(engine)

        exists = (
            inspector.has_table(table_name, schema=schema_name)
            or table_name in inspector.get_view_names(
                schema=schema_name,
            )
        )

        if not exists:
            raise ValueError(f"Объект {object_name!r} не найден")

        return Table(
            table_name,
            MetaData(),
            schema=schema_name,
            autoload_with=engine,
        )

    def preview(
        self,
        source: DataSource,
        object_name: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
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
        engine = self._create_engine(source)

        try:
            table = self._reflect_table(engine, object_name)

            with engine.connect() as connection:
                row_count = connection.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()

                expressions = []

                for index, column in enumerate(table.columns):
                    expressions.append(
                        func.sum(
                            case(
                                (column.is_(None), 1),
                                else_=0,
                            )
                        ).label(f"null_{index}")
                    )

                    expressions.append(
                        func.count(
                            func.distinct(column)
                        ).label(f"distinct_{index}")
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
                    "source_type": "sqlite",
                    "table": object_name,
                    "row_count": row_count,
                    "column_count": len(table.columns),
                    "columns": columns,
                }

        finally:
            engine.dispose()
