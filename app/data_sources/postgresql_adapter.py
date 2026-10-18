
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
    SchemaField,
    SchemaObject,
    SchemaRelation,
    SourceSchema,
    PostgreSQLProperties, PostgreSQLConnection
)

logger = logging.getLogger(__name__)


def inspect_postgresql_connection(
    properties: PostgreSQLProperties,
) -> list[tuple[str, str]]:
    """
    Проверяет подключение и возвращает список доступных
    таблиц и представлений в базе PostgresSQL.

    Результат:
        [
            ("default", "users"),
            ("analytics", "events"),
        ]
    """
    url = URL.create(
        "postgresql+psycopg",
        username=properties.username,
        password=properties.password.get_secret_value(),
        host=properties.host,
        port=properties.port,
        database=properties.database,
        query={"sslmode": properties.sslmode, "channel_binding": "require"},
    )
    logger.info(f"Connection url: '{url}'")

    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "prepare_threshold": None,},
    )

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

            inspector = inspect(connection)
            objects: list[tuple[str, str]] = []

            excluded_schemas = {
                "information_schema",
                "pg_catalog",
            }
            for schema in inspector.get_schema_names():
                if schema in excluded_schemas or schema.startswith("pg_toast"):
                    continue

                logger.info("Inspecting schema: %s", schema)

                try:
                    tables = inspector.get_table_names(schema=schema)
                    logger.info(
                        "Found %d tables in schema %s",
                        len(tables),
                        schema,
                    )

                    views = inspector.get_view_names(schema=schema)
                    logger.info(
                        "Found %d views in schema %s",
                        len(views),
                        schema,
                    )

                except Exception:
                    logger.exception(
                        "Failed to inspect schema: %s",
                        schema,
                    )
                    raise

                objects.extend((schema, table) for table in tables)
                objects.extend((schema, view) for view in views)

        # for schema in inspector.get_schema_names():
        #     if schema in excluded_schemas or schema.startswith("pg_toast"):
        #         continue
        #
        #     for table in inspector.get_table_names(schema=schema):
        #         objects.append((schema, table))
        #
        #     for view in inspector.get_view_names(schema=schema):
        #         objects.append((schema, view))

        if not objects:
            raise ValueError(
                "Подключение успешно, но доступных таблиц и представлений нет"
            )

        return objects

    except SQLAlchemyError:
        # Вызывающий код обработает ошибку.
        raise

    finally:
        engine.dispose()


class PostgreSQLAdapter(DataSourceAdapter):
    """
    Читает схему и данные PostgreSQL.
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
    ) -> None:
        # Сохраняем функцию, с помощью которой узнаём,
        # как подключиться к конкретному источнику.
        self.connection_manger = connection_manager

    def _create_engine(self, source: DataSource) -> Engine:
        """
        Создаёт SQLAlchemy Engine для нужной базы.
        """
        connection = self.connection_manger.get_connection(source.connection_id)

        if not isinstance(connection, PostgreSQLConnection):
            raise ValueError("Connection is not PostgreSQL")

        properties = connection.properties

        # Превращаем информацию о подключении в структурированный URL.
        url = URL.create(
            "postgresql+psycopg",
            username=properties.username,
            password=properties.password.get_secret_value(),
            host=properties.host,
            port=properties.port,
            database=properties.database,
            query={"sslmode": properties.sslmode, "channel_binding": "require"},
        )

        # Не позволяем случайно использовать этот адаптер для SQLite или другой СУБД.
        if url.drivername not in {
            "postgresql",
            "postgresql+psycopg",
            "postgresql+psycopg2",
        }:
            raise ValueError(
                "PostgreSQLAdapter ожидает URL PostgreSQL"
            )

        return create_engine(
            url,
            # Проверять, что соединение из пула ещё работает.
            pool_pre_ping=True,
            # Не ждать свободное соединение из пула бесконечно.
            pool_timeout=10,
            # Ограничить ожидание установки подключения.
            connect_args={"connect_timeout": 5, "prepare_threshold": None,},
        )

    def test_connection(
        self,
        source: DataSource,
    ) -> tuple[bool, str]:
        """
        Проверяет, удаётся ли подключиться к базе.

        SELECT 1 ничего не изменяет: сервер просто возвращает 1.
        """
        engine = None

        try:
            engine = self._create_engine(source)

            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")

            return True, "Подключение к PostgreSQL успешно"

        except (SQLAlchemyError, ValueError, TypeError) as exc:
            # Не возвращаем полный текст исключения клиенту:
            # он может содержать адрес или другие детали подключения.
            return False, (
                "Ошибка подключения к PostgreSQL: "
                f"{type(exc).__name__}"
            )

        finally:
            # Закрываем ресурсы, даже если запрос завершился ошибкой.
            if engine is not None:
                engine.dispose()

    @staticmethod
    def _make_object_id(
        source_id: str,
        schema_name: str,
        table_name: str,
    ) -> str:
        """
        Формирует стабильный ID объекта в рамках источника.

        Например:
        source123:public.users

        Имя объекта может быть одинаковым в разных схемах,
        поэтому одной части table_name недостаточно.
        """
        return f"{source_id}:{schema_name}.{table_name}"

    def introspect_schema(
        self,
        source: DataSource,
    ) -> SourceSchema:
        if not source.table_name:
            raise ValueError("У источника не указано имя таблицы")

        engine = self._create_engine(source)

        try:
            # Все операции introspection выполняются
            # через одно явно открытое соединение.
            with engine.connect() as connection:
                inspector = inspect(connection)

                if source.schema_name:
                    schema_name = source.schema_name
                    table_name = source.table_name
                elif "." in source.table_name:
                    schema_name, table_name = source.table_name.split(".", 1)
                else:
                    schema_name = inspector.default_schema_name
                    table_name = source.table_name

                if not schema_name or not table_name:
                    raise ValueError(
                        "Не удалось определить схему и имя объекта"
                    )

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

                # materialized_views = set(
                #     inspector.get_materialized_view_names(
                #         schema=schema_name
                #     )
                # )

                # if table_name in materialized_views:
                #     object_type = "materialized_view"
                # el
                if table_name in views:
                    object_type = "view"
                else:
                    object_type = "table"

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
                seen_relations: set[
                    tuple[str, str, str, str]
                ] = set()

                def add_foreign_key(
                    fk_schema: str,
                    fk_table: str,
                    constrained_columns: list[str],
                    referred_schema: str,
                    referred_table: str,
                    referred_columns: list[str],
                ) -> None:
                    if len(constrained_columns) != len(referred_columns):
                        logger.warning(
                            "Mismatched foreign key columns: %s.%s -> %s.%s",
                            fk_schema,
                            fk_table,
                            referred_schema,
                            referred_table,
                        )
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

                # Внешние ключи выбранной таблицы.
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

                # Входящие внешние ключи из остальных таблиц.
                excluded_schemas = {
                    "information_schema",
                    "pg_catalog",
                }

                for candidate_schema in inspector.get_schema_names():
                    if (
                        candidate_schema in excluded_schemas
                        or candidate_schema.startswith("pg_toast")
                    ):
                        continue

                    for candidate_table in inspector.get_table_names(
                        schema=candidate_schema
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
                                    fk.get("referred_schema") or candidate_schema
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
        """
        Получает SQLAlchemy-описание существующей таблицы.

        object_name принимает:
            public.users
            users

        Во втором случае используем схему по умолчанию.
        """
        parts = object_name.split(".")

        if len(parts) == 2:
            schema_name, table_name = parts
        elif len(parts) == 1 and parts[0]:
            schema_name = inspect(engine).default_schema_name
            table_name = parts[0]
        else:
            raise ValueError(
                "Имя объекта должно иметь формат table или schema.table"
            )

        inspector = inspect(engine)

        # Сначала проверяем, что объект действительно существует.
        # Это также даёт понятную ошибку вместо неясной ошибки SQL.
        exists = (
            inspector.has_table(table_name, schema=schema_name)
            or table_name in inspector.get_view_names(
                schema=schema_name
            )
        )

        if not exists:
            raise ValueError(
                f"Объект {object_name!r} не найден"
            )

        # SQLAlchemy читает структуру существующей таблицы.
        # Мы не создаём таблицу и не изменяем её.
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
        """
        Возвращает первые limit строк объекта.

        object_name — именно имя таблицы, а не имя источника.
        """
        if not 1 <= limit <= 1000:
            raise ValueError("limit должен быть от 1 до 1000")

        engine = self._create_engine(source)

        try:
            table = self._reflect_table(engine, object_name)

            # select(table) означает SELECT всех колонок таблицы.
            # limit ограничивает число возвращаемых строк.
            query = select(table).limit(limit)

            with engine.connect() as connection:
                result = connection.execute(query)

                # mappings() позволяет обращаться к значениям по имени
                # колонки. dict() делает результат совместимым с JSON.
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
        Собирает базовую статистику таблицы:
        количество строк, NULL и уникальных значений по колонкам.

        Это точное профилирование, а не выборочная оценка.
        Для больших таблиц оно может быть дорогим.
        """
        engine = self._create_engine(source)

        try:
            table = self._reflect_table(engine, object_name)

            with engine.connect() as connection:

                # COUNT(*) считает все строки.
                row_count = connection.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()

                # Будем собирать несколько агрегатов в один SQL-запрос.
                expressions = []

                for index, column in enumerate(table.columns):
                    # CASE возвращает 1, если значение NULL, иначе 0.
                    # SUM складывает эти единицы и получает число пропусков.
                    expressions.append(
                        func.sum(
                            case(
                                (column.is_(None), 1),
                                else_=0,
                            )
                        ).label(f"null_{index}")
                    )

                    # COUNT(DISTINCT column) считает различные значения.
                    # Как и в большинстве СУБД, NULL сюда не входит.
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
                    "source_type": "postgresql",
                    "table": object_name,
                    "row_count": row_count,
                    "column_count": len(table.columns),
                    "columns": columns,
                }

        finally:
            engine.dispose()
