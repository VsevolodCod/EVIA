"""Allowlisted, read-only access to a PostgreSQL analytical source."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator

import psycopg
from psycopg import sql

from app.config import PostgresSettings
from app.data_sources.base import DataSourceAdapter
from app.contracts.v1 import Provenance, QueryResult
from app.models import DataSource, SchemaField, SchemaObject, SourceSchema, utc_now
from app.postgresql_sql import PostgresQueryExecutor


class PostgresSourceError(Exception):
    """Stable source error that intentionally omits driver and DSN details."""

    _messages = {
        "CONNECTION_FAILED": "CONNECTION_FAILED: PostgreSQL is unavailable.",
        "SOURCE_FORBIDDEN": "SOURCE_FORBIDDEN: Source is not permitted.",
        "QUERY_TIMEOUT": "QUERY_TIMEOUT: Query exceeded its time limit.",
        "INTERNAL_ERROR": "INTERNAL_ERROR: PostgreSQL operation could not be completed.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._messages[code])


ConnectionFactory = Callable[..., Any]


class PostgreSQLAdapter(DataSourceAdapter):
    """Read configured PostgreSQL tables without ever persisting credentials."""

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        connect: ConnectionFactory = psycopg.connect,
        sample_size: int = 500,
    ) -> None:
        self.settings = settings
        self._connect = connect
        self.sample_size = sample_size
        self.sql_executor = PostgresQueryExecutor(self._session)

    @contextmanager
    def _session(self) -> Iterator[Any]:
        connection = None
        try:
            connection = self._connect(
                self.settings.dsn,
                connect_timeout=self.settings.connect_timeout_seconds,
            )
            connection.execute("BEGIN READ ONLY")
            connection.execute(
                "SET LOCAL statement_timeout = %s",
                (self.settings.statement_timeout_ms,),
            )
            yield connection
        except PostgresSourceError:
            raise
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower() or "cancel" in type(exc).__name__.lower():
                raise PostgresSourceError("QUERY_TIMEOUT") from None
            raise PostgresSourceError("CONNECTION_FAILED") from None
        finally:
            if connection is not None:
                connection.close()

    def _assert_allowed(self, schema_name: str, table_name: str) -> None:
        if (schema_name, table_name) not in self.settings.allowed_tables:
            raise PostgresSourceError("SOURCE_FORBIDDEN")

    @staticmethod
    def _source(schema_name: str, table_name: str) -> DataSource:
        return DataSource(
            source_id=f"postgresql:{schema_name}:{table_name}",
            name=f"{schema_name}.{table_name}",
            source_type="postgresql",
            schema_name=schema_name,
            table_name=table_name,
            status="available",
        )

    def discover(self) -> list[DataSource]:
        """Return only the configured tables that actually exist."""
        if not self.settings.enabled:
            return []
        values_sql = ", ".join(["(%s, %s)"] * len(self.settings.allowed_tables))
        parameters = [part for pair in sorted(self.settings.allowed_tables) for part in pair]
        query = f"""
            SELECT c.table_schema, c.table_name, c.column_name,
                   c.data_type, c.is_nullable
            FROM information_schema.columns AS c
            JOIN (VALUES {values_sql}) AS allowed(schema_name, table_name)
              ON c.table_schema = allowed.schema_name
             AND c.table_name = allowed.table_name
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """
        with self._session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, parameters)
                rows = cursor.fetchall()
        # Keep the application-side allowlist as a second guard: a driver or
        # mocked server response must never publish an unconfigured table.
        available = {
            (row[0], row[1])
            for row in rows
            if (row[0], row[1]) in self.settings.allowed_tables
        }
        return [self._source(schema_name, table_name) for schema_name, table_name in sorted(available)]

    def test_connection(self, source: DataSource) -> tuple[bool, str]:
        try:
            self._source_parts(source)
            with self._session() as connection:
                connection.execute("SELECT 1")
            return True, "PostgreSQL connection is available"
        except PostgresSourceError as exc:
            return False, exc.code

    def connection_status(self) -> bool:
        """Probe the configured database without exposing connection details."""
        try:
            with self._session() as connection:
                connection.execute("SELECT 1")
            return True
        except PostgresSourceError:
            return False

    def introspect_schema(self, source: DataSource) -> SourceSchema:
        schema_name, table_name = self._source_parts(source)
        query = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """
        with self._session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, (schema_name, table_name))
                rows = cursor.fetchall()
        if not rows:
            raise PostgresSourceError("SOURCE_FORBIDDEN")
        return SourceSchema(
            source_id=source.source_id,
            version=source.schema_version,
            objects=[
                SchemaObject(
                    object_id=f"{source.source_id}:table",
                    name=f"{schema_name}.{table_name}",
                    object_type="postgresql_table",
                    fields=[
                        SchemaField(
                            name=row[0],
                            inferred_type=row[1],
                            nullable=row[2] == "YES",
                        )
                        for row in rows
                    ],
                )
            ],
        )

    def preview(
        self,
        source: DataSource | str,
        object_name: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        schema_name, table_name = self._source_parts(source, object_name)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        query = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
            sql.Identifier(schema_name), sql.Identifier(table_name)
        )
        with self._session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, (limit,))
                columns = [column.name for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def query(
        self,
        source: DataSource,
        sql_text: str,
        *,
        row_limit: int | None = None,
    ) -> QueryResult:
        schema_name, table_name = self._source_parts(source)
        return self.sql_executor.execute(
            sql_text,
            schema_name=schema_name,
            table_name=table_name,
            provenance=Provenance(
                source_id=source.source_id,
                snapshot_id=source.snapshot_id or "live",
                schema_version=source.schema_version,
                tool_name="query_data",
                executed_at=utc_now(),
            ),
            row_limit=row_limit,
        )

    def profile(
        self,
        source: DataSource | str,
        object_name: str | None = None,
    ) -> dict[str, Any]:
        rows = self.preview(source, object_name, limit=min(self.sample_size, 100))
        columns: dict[str, dict[str, Any]] = {}
        for name in rows[0] if rows else []:
            values = [row[name] for row in rows]
            non_null = [value for value in values if value is not None]
            counts: dict[str, int] = {}
            for value in non_null:
                rendered = str(value)
                counts[rendered] = counts.get(rendered, 0) + 1
            columns[name] = {
                "sample_non_null_count": len(non_null),
                "sample_null_count": len(values) - len(non_null),
                "distinct_sample_values": len({str(value) for value in non_null}),
                "top_values": [
                    {"value": value, "count": count}
                    for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
                ],
            }
        return {
            "sample_size": len(rows),
            "sample_limit": min(self.sample_size, 100),
            "columns": columns,
            "note": "Column statistics use a bounded sample; counts are sampled estimates.",
        }

    def _source_parts(
        self,
        source: DataSource | str,
        object_name: str | None = None,
    ) -> tuple[str, str]:
        if isinstance(source, DataSource):
            schema_name, table_name = source.schema_name, source.table_name
        else:
            schema_name, separator, table_name = source.partition(".")
            if not separator:
                schema_name, table_name = "", ""
        if object_name is not None and object_name not in {
            f"{schema_name}.{table_name}",
            "table",
            f"postgresql:{schema_name}:{table_name}:table",
        }:
            raise PostgresSourceError("SOURCE_FORBIDDEN")
        if not schema_name or not table_name:
            raise PostgresSourceError("SOURCE_FORBIDDEN")
        self._assert_allowed(schema_name, table_name)
        return schema_name, table_name
