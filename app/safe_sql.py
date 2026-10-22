"""Guarded analytical SQL execution for the local DuckDB data engine."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import json
from pathlib import Path
from threading import Timer
from time import perf_counter
from typing import Any
from uuid import uuid4

import duckdb
import sqlglot
from sqlglot import exp

from app.contracts.v1 import Provenance, QueryResult, ResultColumn

import logging


logger = logging.getLogger(__name__)


class SafeQueryError(Exception):
    """A stable public failure that never contains SQL or engine details."""

    _messages = {
        "QUERY_REJECTED": "QUERY_REJECTED: Query is not permitted.",
        "QUERY_TIMEOUT": "QUERY_TIMEOUT: Query exceeded its time limit.",
        "INTERNAL_ERROR": "INTERNAL_ERROR: Query could not be completed.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._messages[code])


_SAFE_FUNCTIONS = {
    "ABS", "AVG", "CAST", "CEIL", "CEILING", "COALESCE", "CONCAT",
    "COUNT", "DATE", "DATE_TRUNC", "EXTRACT", "FLOOR", "GREATEST",
    "LEAST", "LENGTH", "LOWER", "LPAD", "LTRIM", "MAX", "MIN",
    "NULLIF", "ROUND", "RPAD", "RTRIM", "STRFTIME", "SUBSTRING", "SUM",
    "TRIM", "TRY_CAST", "UPPER",
}
_SELECT_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)
_BLOCKED_NODE_NAMES = {
    "ALTER", "ANALYZE", "ATTACH", "CACHE", "COMMAND", "COPY", "CREATE",
    "DELETE", "DESCRIBE", "DETACH", "DROP", "GRANT", "INSERT", "INSTALL",
    "LOAD", "MERGE", "PRAGMA", "REPLACE", "REVOKE", "TRANSACTION", "TRUNCATE",
    "UNLOAD", "UPDATE", "USE", "VACUUM",
}


class SafeQueryExecutor:
    """Validate and run one bounded analytical query over allowed tables."""

    def __init__(
        self,
        database_path: Path,
        *,
        memory_limit_mb: int = 128,
        default_timeout_seconds: float = 10,
        max_timeout_seconds: float = 60,
        default_row_limit: int = 1_000,
        max_row_limit: int = 10_000,
        max_result_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.memory_limit_mb = memory_limit_mb
        self.default_timeout_seconds = default_timeout_seconds
        self.max_timeout_seconds = max_timeout_seconds
        self.default_row_limit = default_row_limit
        self.max_row_limit = max_row_limit
        self.max_result_bytes = max_result_bytes

    def execute(
        self,
        sql: str,
        *,
        allowed_tables: dict[str, str],
        provenance: Provenance,
        row_limit: int | None = None,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        limit = row_limit if row_limit is not None else self.default_row_limit
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        if not isinstance(limit, int) or not 1 <= limit <= self.max_row_limit:
            raise SafeQueryError("QUERY_REJECTED")
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= self.max_timeout_seconds:
            raise SafeQueryError("QUERY_REJECTED")

        statement = self._validated_statement(sql, allowed_tables)
        # ``limit`` is validated above and interpolated as an integer only.
        bounded_sql = f"SELECT * FROM ({statement.sql(dialect='duckdb')}) AS __evia_result LIMIT {limit + 1}"
        started = perf_counter()
        timed_out = False
        connection = None
        timer: Timer | None = None
        try:
            connection = duckdb.connect(
                str(self.database_path),
                read_only=True,
                config={
                    "enable_external_access": "false",
                    "memory_limit": f"{self.memory_limit_mb}MB",
                },
            )

            def interrupt() -> None:
                nonlocal timed_out
                timed_out = True
                connection.interrupt()

            timer = Timer(float(timeout), interrupt)
            timer.daemon = True
            timer.start()
            cursor = connection.execute(bounded_sql)
            names = [column[0] for column in cursor.description]
            description = cursor.description
            rows: list[list[Any]] = []
            truncated = False
            # Account for the JSON envelope too.  Every following row adds a
            # comma, so this is an exact upper bound for the final payload.
            payload_bytes = len(
                json.dumps({"columns": names, "rows": []}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            while True:
                raw_row = cursor.fetchone()
                if raw_row is None:
                    break
                if len(rows) == limit:
                    # This sentinel row establishes truncation; it is never
                    # returned, so it must not count against the response
                    # budget or be converted to JSON.
                    truncated = True
                    break
                row = [_json_value(value) for value in raw_row]
                row_bytes = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                if rows:
                    row_bytes += 1
                if payload_bytes + row_bytes > self.max_result_bytes:
                    raise SafeQueryError("QUERY_REJECTED")
                rows.append(row)
                payload_bytes += row_bytes
                if timed_out or perf_counter() - started > timeout:
                    raise SafeQueryError("QUERY_TIMEOUT")
            if timed_out or perf_counter() - started > timeout:
                raise SafeQueryError("QUERY_TIMEOUT")
        except Exception as exc:
            if isinstance(exc, SafeQueryError):
                raise
            if timed_out or "interrupt" in str(exc).lower():
                raise SafeQueryError("QUERY_TIMEOUT") from None
            if isinstance(
                exc,
                (
                    duckdb.BinderException,
                    duckdb.CatalogException,
                    duckdb.ConversionException,
                    duckdb.InvalidInputException,
                    duckdb.ParserException,
                ),
            ):
                # logger.exception(
                #     "DuckDB rejected analytical query: %s: %s",
                #     type(exc).__name__,
                #     exc,
                # )
                raise SafeQueryError("QUERY_REJECTED") from None
            raise SafeQueryError("INTERNAL_ERROR") from None
        finally:
            if timer is not None:
                timer.cancel()
            if connection is not None:
                connection.close()

        columns = self._columns(names, description)
        return QueryResult(
            result_id=uuid4().hex,
            columns=columns,
            rows=rows,
            returned_rows=len(rows),
            row_limit=limit,
            truncated=truncated,
            elapsed_ms=(perf_counter() - started) * 1_000,
            provenance=[provenance],
        )

    def _validated_statement(self, sql: str, allowed_tables: dict[str, str]) -> exp.Expression:
        if not isinstance(sql, str) or not sql.strip():
            raise SafeQueryError("QUERY_REJECTED")
        try:
            statements = [statement for statement in sqlglot.parse(sql, read="duckdb") if statement is not None]
        except Exception:
            raise SafeQueryError("QUERY_REJECTED") from None
        if len(statements) != 1 or not isinstance(statements[0], _SELECT_ROOTS):
            raise SafeQueryError("QUERY_REJECTED")

        statement = statements[0]
        if any(type(node).__name__.upper() in _BLOCKED_NODE_NAMES for node in statement.walk()):
            raise SafeQueryError("QUERY_REJECTED")
        for function in statement.find_all(exp.Func):
            if function.sql_name().upper() not in _SAFE_FUNCTIONS:
                raise SafeQueryError("QUERY_REJECTED")

        cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
        for table in statement.find_all(exp.Table):
            if not isinstance(table.this, exp.Identifier):
                # Table-valued functions (read_csv, parquet_scan, httpfs, …)
                # are intentionally not an alternative route to a file/network.
                raise SafeQueryError("QUERY_REJECTED")
            if table.args.get("db") is not None or table.args.get("catalog") is not None:
                raise SafeQueryError("QUERY_REJECTED")
            if table.name in cte_names:
                continue
            physical_name = allowed_tables.get(table.name)
            if physical_name is None:
                raise SafeQueryError("QUERY_REJECTED")
            table.set("this", exp.to_identifier(physical_name, quoted=True))
        return statement

    @staticmethod
    def _columns(names: list[str], description: list[tuple[Any, ...]]) -> list[ResultColumn]:
        if len(names) != len(set(names)):
            raise SafeQueryError("QUERY_REJECTED")
        return [
            ResultColumn(name=name, data_type=_contract_type(column[1]), nullable=True)
            for name, column in zip(names, description)
        ]


def _contract_type(duckdb_type: Any) -> str:
    value = str(duckdb_type).upper()
    if "INT" in value:
        return "integer"
    if any(token in value for token in ("DECIMAL", "NUMERIC")):
        return "decimal"
    if any(token in value for token in ("DOUBLE", "FLOAT", "REAL")):
        return "number"
    if "BOOL" in value:
        return "boolean"
    if "TIMESTAMP" in value:
        return "datetime"
    if value == "DATE":
        return "date"
    return "string"


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
