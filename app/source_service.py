import csv
import io
import logging
import uuid
from pathlib import Path
from typing import Any

from app.connection_manager import ConnectionManager
from app.data_sources import CSVAdapter, PostgreSQLAdapter, ClickHouseAdapter, SQLiteAdapter
from app.data_sources.csv_format import PARSER_VERSION, csv_reader, read_header
from app.models import DataSource, SourceSchema
from app.schema_catalog import SchemaCatalog

logger = logging.getLogger(__name__)


class SourceService:
    def __init__(
            self,
            data_dir: Path,
            catalog: SchemaCatalog,
            connection_manager: ConnectionManager
    ) -> None:

        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.catalog = catalog
        self.connection_manager = connection_manager

        self.csv_adapter = CSVAdapter(self.data_dir)
        self.postgresql_adapter = PostgreSQLAdapter(self.connection_manager)
        self.clickhouse_adapter = ClickHouseAdapter(self.connection_manager)
        self.sqlite_adapter = SQLiteAdapter(self.connection_manager)

        self.adapters = {
            "csv": self.csv_adapter,
            "postgresql": self.postgresql_adapter,
            "clickhouse": self.clickhouse_adapter,
            "sqlite": self.sqlite_adapter,
        }

    def register_csv(
            self,
            filename: str,
            content: bytes,
            name: str | None = None,
    ) -> DataSource:
        logger.info("Started csv registration")

        if not filename.lower().endswith(".csv"):
            raise ValueError("Only CSV files are supported")

        if not content:
            raise ValueError("Uploaded CSV is empty")

        try:
            text = content.decode("utf-8-sig")
            reader = csv_reader(io.StringIO(text, newline=''))
            read_header(reader)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError("CSV must be valid UTF-8") from exc

        source_id = uuid.uuid4().hex
        source_name = (
                              name or Path(filename).stem or "uploaded_csv"
                      ).strip()[:120]

        source = DataSource(
            source_id=source_id,
            name=source_name,
            source_type="csv",
            status="available",
        )

        target = (self.data_dir / f"{source_id}.csv").resolve()

        if target.parent != self.data_dir:
            raise ValueError("Invalid target path")

        target.write_bytes(content)

        try:
            schema = self.csv_adapter.introspect_schema(source)
            source.schema_version = schema.version

            self.catalog.upsert_source(source)
            self.catalog.save_schema(schema)

            logger.info("Successful csv registration")

        except (csv.Error, UnicodeDecodeError) as exc:
            target.unlink(missing_ok=True)
            raise ValueError('CSV contains invalid encoding or quoting') from exc
        except Exception:
            target.unlink(missing_ok=True)
            raise

        return source

    def register_postgresql(self, connection_id: str, name_db: str, objects: list[tuple[str, str]]) -> list[DataSource]:
        logger.info("Started PostgreSQL registration")
        all_sources: list[DataSource] = []

        for i in objects:
            source_id = uuid.uuid4().hex
            source_name = ".".join([name_db, *i])

            logger.info(
                "Started table '%s' registration",
                source_name
            )

            source = DataSource(
                source_id=source_id,
                name=source_name,
                schema_name=i[0],
                table_name=i[1],
                connection_id=connection_id,
                source_type="postgresql",
                status="available"
            )
            response = self.postgresql_adapter.test_connection(source)
            if not response[0]:
                raise ConnectionError(response[1])

            try:
                schema = self.postgresql_adapter.introspect_schema(source)
                source.schema_version = schema.version
                self.catalog.upsert_source(source)
                self.catalog.save_schema(schema)
                all_sources.append(source)
            except Exception:
                raise

        logger.info(
            "Successfully registered %d PostgreSQL table objects",
            len(all_sources),
        )

        return all_sources

    def register_clickhouse(self, connection_id: str, name_db: str, objects: list[tuple[str, str]]) -> list[DataSource]:
        logger.info("Started ClickHouse registration")

        all_sources: list[DataSource] = []

        for database_name, table_name in objects:
            source_id = uuid.uuid4().hex
            source_name = f"{name_db}.{database_name}.{table_name}"

            logger.info(
                "Started ClickHouse object '%s' registration",
                source_name,
            )

            source = DataSource(
                source_id=source_id,
                name=source_name,
                schema_name=database_name,
                table_name=table_name,
                connection_id=connection_id,
                source_type="clickhouse",
                status="available",
            )

            response = self.clickhouse_adapter.test_connection(source)

            if not response[0]:
                raise ConnectionError(response[1])

            schema = self.clickhouse_adapter.introspect_schema(source)
            source.schema_version = schema.version

            self.catalog.upsert_source(source)
            self.catalog.save_schema(schema)

            all_sources.append(source)

        logger.info(
            "Successfully registered %d ClickHouse table objects",
            len(all_sources),
        )

        return all_sources

    def register_sqlite(
            self,
            connection_id: str,
            name_db: str,
            objects: list[tuple[str, str]],
    ) -> list[DataSource]:

        logger.info("Started SQLite registration")

        all_sources: list[DataSource] = []

        for schema_name, table_name in objects:
            source_id = uuid.uuid4().hex
            source_name = f"{name_db}.{schema_name}.{table_name}"

            logger.info(
                "Started SQLite object '%s' registration",
                source_name,
            )

            source = DataSource(
                source_id=source_id,
                name=source_name,
                schema_name=schema_name,
                table_name=table_name,
                connection_id=connection_id,
                source_type="sqlite",
                status="available",
            )

            response = self.sqlite_adapter.test_connection(source)

            if not response[0]:
                raise ConnectionError(response[1])

            schema = self.sqlite_adapter.introspect_schema(source)
            source.schema_version = schema.version

            self.catalog.upsert_source(source)
            self.catalog.save_schema(schema)

            all_sources.append(source)

        logger.info(
            "Successfully registered %d SQLite table objects",
            len(all_sources),
        )

        return all_sources

    def get_schema(self, source_id: str) -> SourceSchema:
        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        schema = self.catalog.get_schema(source_id)

        if schema is None or schema.parser_version < PARSER_VERSION:
            if schema is not None:
                source.schema_version = max(source.schema_version, schema.version) + 1
            schema = self.adapters[source.source_type].introspect_schema(source)
            self.catalog.save_schema(schema)
            self.catalog.upsert_source(source)

        return schema

    @staticmethod
    def _get_object_name(source: DataSource) -> str:
        if not source.table_name:
            raise ValueError("У источника не указано имя таблицы")

        if source.schema_name:
            return f"{source.schema_name}.{source.table_name}"

        return source.table_name

    def preview(
            self,
            source_id: str,
            limit: int = 10,
    ) -> list[dict[str, Any]]:

        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        source_name = self._get_object_name(source)

        return self.adapters[source.source_type].preview(source, source_name, limit)

    def profile(self, source_id: str) -> dict[str, Any]:
        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        source_name = self._get_object_name(source)

        return self.adapters[source.source_type].profile(source, source_name)
