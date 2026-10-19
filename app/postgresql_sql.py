"""Guarded analytical SELECT execution for PostgreSQL sources."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import json
from time import perf_counter
from typing import Any, Callable, ContextManager
from uuid import uuid4

import sqlglot
from sqlglot import exp

from app.contracts.v1 import Provenance, QueryResult, ResultColumn


class PostgresQueryError(Exception):
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
    "NULLIF", "ROUND", "RPAD", "RTRIM", "SUBSTRING", "SUM", "TRIM",
    "UPPER",
}
_SELECT_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)
_BLOCKED_NODE_NAMES = {
    "ALTER", "ANALYZE", "ATTACH", "CACHE", "COMMAND", "COPY", "CREATE",
    "DELETE", "DESCRIBE", "DETACH", "DROP", "GRANT", "INSERT", "INSTALL",
    "LOAD", "LOCK", "MERGE", "PRAGMA", "REPLACE", "REVOKE", "TRANSACTION", "TRUNCATE",
    "UNLOAD", "UPDATE", "USE", "VACUUM",
}


class PostgresQueryExecutor:
    """Validate one logical-table query and execute it in a supplied session."""

    def __init__(
        self,
        session: Callable[[], ContextManager[Any]],
        *,
        default_row_limit: int = 1_000,
        max_row_limit: int = 10_000,
        max_result_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self._session = session
        self.default_row_limit = default_row_limit
        self.max_row_limit = max_row_limit
        self.max_result_bytes = max_result_bytes

    def execute(
        self,
        sql: str,
        *,
        schema_name: str,
        table_name: str,
        provenance: Provenance,
        row_limit: int | None = None,
    ) -> QueryResult:
        limit = self.default_row_limit if row_limit is None else row_limit
        if not isinstance(limit, int) or not 1 <= limit <= self.max_row_limit:
            raise PostgresQueryError("QUERY_REJECTED")
        statement = self._validated_statement(sql, schema_name, table_name)
        bounded_sql = f"SELECT * FROM ({statement.sql(dialect='postgres')}) AS __evia_result LIMIT {limit + 1}"
        started = perf_counter()
        try:
            with self._session() as connection:
                cursor = connection.execute(bounded_sql)
                names = [column.name for column in cursor.description]
                types = [getattr(column, "type_code", None) for column in cursor.description]
                payload_bytes = len(
                    json.dumps({"columns": names, "rows": []}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                )
                rows: list[list[Any]] = []
                truncated = False
                while True:
                    raw_row = cursor.fetchone()
                    if raw_row is None:
                        break
                    if len(rows) == limit:
                        truncated = True
                        break
                    row = [_json_value(value) for value in raw_row]
                    row_bytes = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                    if rows:
                        row_bytes += 1
                    if payload_bytes + row_bytes > self.max_result_bytes:
                        raise PostgresQueryError("QUERY_REJECTED")
                    rows.append(row)
                    payload_bytes += row_bytes
        except PostgresQueryError:
            raise
        except Exception as exc:
            if getattr(exc, "code", None) == "QUERY_TIMEOUT":
                raise PostgresQueryError("QUERY_TIMEOUT") from None
            if "timeout" in type(exc).__name__.lower() or "cancel" in type(exc).__name__.lower():
                raise PostgresQueryError("QUERY_TIMEOUT") from None
            raise PostgresQueryError("INTERNAL_ERROR") from None
        return QueryResult(
            result_id=uuid4().hex,
            columns=[ResultColumn(name=name, data_type=_contract_type(type_code), nullable=True) for name, type_code in zip(names, types)],
            rows=rows,
            returned_rows=len(rows),
            row_limit=limit,
            truncated=truncated,
            elapsed_ms=(perf_counter() - started) * 1_000,
            provenance=[provenance],
        )

    @staticmethod
    def _validated_statement(sql: str, schema_name: str, table_name: str) -> exp.Expression:
        if not isinstance(sql, str) or not sql.strip():
            raise PostgresQueryError("QUERY_REJECTED")
        try:
            statements = [item for item in sqlglot.parse(sql, read="postgres") if item is not None]
        except Exception:
            raise PostgresQueryError("QUERY_REJECTED") from None
        if len(statements) != 1 or not isinstance(statements[0], _SELECT_ROOTS):
            raise PostgresQueryError("QUERY_REJECTED")
        statement = statements[0]
        if any(type(node).__name__.upper() in _BLOCKED_NODE_NAMES for node in statement.walk()):
            raise PostgresQueryError("QUERY_REJECTED")
        for function in statement.find_all(exp.Func):
            if function.sql_name().upper() not in _SAFE_FUNCTIONS:
                raise PostgresQueryError("QUERY_REJECTED")
        cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
        has_source_table = False
        for table in statement.find_all(exp.Table):
            if not isinstance(table.this, exp.Identifier) or table.args.get("db") is not None or table.args.get("catalog") is not None:
                raise PostgresQueryError("QUERY_REJECTED")
            if table.name in cte_names:
                continue
            if table.name != "source":
                raise PostgresQueryError("QUERY_REJECTED")
            table.set("this", exp.to_identifier(table_name, quoted=True))
            table.set("db", exp.to_identifier(schema_name, quoted=True))
            has_source_table = True
        if not has_source_table:
            raise PostgresQueryError("QUERY_REJECTED")
        return statement


def _contract_type(type_code: Any) -> str:
    postgres_type_codes = {
        16: "boolean",
        20: "integer",
        21: "integer",
        23: "integer",
        700: "number",
        701: "number",
        1082: "date",
        1114: "datetime",
        1184: "datetime",
        1700: "decimal",
    }
    if type_code in postgres_type_codes:
        return postgres_type_codes[type_code]
    name = str(type_code).upper()
    if "INT" in name:
        return "integer"
    if any(token in name for token in ("NUMERIC", "DECIMAL")):
        return "decimal"
    if any(token in name for token in ("FLOAT", "DOUBLE", "REAL")):
        return "number"
    if "BOOL" in name:
        return "boolean"
    if "TIMESTAMP" in name:
        return "datetime"
    if "DATE" in name:
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
