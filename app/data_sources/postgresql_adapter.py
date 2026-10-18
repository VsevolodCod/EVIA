
from __future__ import annotations

from collections.abc import Callable
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
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import SQLAlchemyError

from app.connection_manager import ConnectionManager
from app.data_sources.base import DataSourceAdapter
from app.models import (
    DataSource,
    SchemaField,
    SchemaObject,
    SchemaRelation,
    SourceSchema,
    PostgreSQLProperties
)


def inspect_postgresql_connection(
    properties: PostgreSQLProperties,
) -> list[tuple[str, str]]:
    url = URL.create(
        "postgresql+psycopg",
        username=properties.username,
        password=properties.password.get_secret_value(),
        host=properties.host,
        port=properties.port,
        database=properties.database,
        query={"sslmode": properties.sslmode},
    )

    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")

        inspector = inspect(engine)
        objects: list[tuple[str, str]] = []

        excluded_schemas = {
            "information_schema",
            "pg_catalog",
        }

        for schema in inspector.get_schema_names():
            if schema in excluded_schemas or schema.startswith("pg_toast"):
                continue

            for table in inspector.get_table_names(schema=schema):
                objects.append((schema, table))

            for view in inspector.get_view_names(schema=schema):
                objects.append((schema, view))

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
        properties = self.connection_manger.get_connection(source.connection_id).properties

        # Превращаем информацию о подключении в структурированный URL.
        url = URL.create(
            "postgresql+psycopg",
            username=properties.username,
            password=properties.password.get_secret_value(),
            host=properties.host,
            port=properties.port,
            database=properties.database,
            query={"sslmode": properties.sslmode},
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
            connect_args={"connect_timeout": 5},
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
        """
        Читает структуру БД и преобразует её в наши модели.

        В PostgreSQL:\n
        - schema — пространство имён, например public;\n
        - table — таблица внутри схемы;\n
        - column — колонка таблицы;\n
        - foreign key — объявленная связь между таблицами.
        """
        engine = self._create_engine(source)

        try:
            # Inspector умеет запрашивать системные метаданные БД.
            inspector = inspect(engine)

            # Эти списки в итоге попадут в SourceSchema.
            objects: list[SchemaObject] = []
            relations: list[SchemaRelation] = []

            # Например, обычно это public.
            default_schema = inspector.default_schema_name

            # PostgreSQL может содержать несколько схем.
            for schema_name in inspector.get_schema_names():

                # Это системные схемы PostgreSQL, а не пользовательские таблицы, которые мы хотим показывать аналитику.
                if schema_name in {
                    "information_schema",
                    "pg_catalog",
                    "pg_toast",
                }:
                    continue

                # Таблицы и представления — разные объекты.
                table_names = inspector.get_table_names(
                    schema=schema_name
                )
                view_names = inspector.get_view_names(
                    schema=schema_name
                )

                # Обрабатываем и таблицы, и представления.
                # set убирает дубликаты, если они есть.
                for table_name in sorted(
                    set(table_names) | set(view_names)
                ):
                    is_view = table_name in view_names

                    # Получаем описание колонок: имена, типы, возможность NULL и значения по умолчанию.
                    columns = inspector.get_columns(
                        table_name,
                        schema=schema_name,
                    )

                    # Первичный ключ помогает распознать идентификаторы.
                    pk_info = inspector.get_pk_constraint(
                        table_name,
                        schema=schema_name,
                    )
                    primary_keys = set(
                        pk_info.get("constrained_columns") or []
                    )

                    object_id = self._make_object_id(
                        source.source_id,
                        schema_name,
                        table_name,
                    )

                    fields: list[SchemaField] = []

                    for column in columns:
                        column_name = column["name"]

                        # Это лишь эвристика для подсказки аналитику. Она не доказывает, что поле действительно ID.
                        is_identifier = (
                            column_name in primary_keys
                            or column_name.lower() in {
                                "id", "uuid", "guid"
                            }
                            or column_name.lower().endswith("_id")
                        )

                        fields.append(
                            SchemaField(
                                name=column_name,
                                inferred_type=str(column["type"]),
                                nullable=column.get("nullable"),
                                is_identifier_candidate=is_identifier,
                                description=None,
                            )
                        )

                    # Представляем объект в формате приложения, а не в формате специфичных метаданных PostgreSQL.
                    objects.append(
                        SchemaObject(
                            object_id=object_id,
                            name=f"{schema_name}.{table_name}",
                            object_type=(
                                "view" if is_view else "table"
                            ),
                            fields=fields,
                            # Не делаем COUNT(*) для каждой таблицы во время чтения схемы: это может быть дорого.
                            row_count=None,
                        )
                    )

                    # Получаем внешние ключи именно этой таблицы.
                    foreign_keys = inspector.get_foreign_keys(
                        table_name,
                        schema=schema_name,
                    )

                    for foreign_key in foreign_keys:
                        target_table = foreign_key.get(
                            "referred_table"
                        )

                        target_schema = (
                            foreign_key.get("referred_schema")
                            or default_schema
                        )

                        local_columns = (
                            foreign_key.get("constrained_columns")
                            or []
                        )
                        target_columns = (
                            foreign_key.get("referred_columns")
                            or []
                        )

                        # Если сведения о целевой таблице отсутствуют, полноценную связь построить нельзя.
                        if not target_table:
                            continue

                        # Внешний ключ может включать несколько колонок.
                        # Каждая пара колонок становится отдельной связью.
                        for local_column, target_column in zip(
                            local_columns,
                            target_columns,
                        ):
                            relations.append(
                                SchemaRelation(
                                    left_object_id=object_id,
                                    left_field=local_column,
                                    right_object_id=self._make_object_id(
                                        source.source_id,
                                        target_schema,
                                        target_table,
                                    ),
                                    right_field=target_column,
                                    discovery_method="foreign_key",
                                    confidence=1.0,
                                )
                            )

            # Приводим всё к моделям, используемым каталогом схем.
            return SourceSchema(
                source_id=source.source_id,
                version=source.schema_version,
                objects=objects,
                relations=relations,
            )

        finally:
            engine.dispose()

    def _reflect_table(
        self,
        engine: Engine,
        object_name: str,
    ) -> Table:
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
