from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
import math
from typing import Any

from app.hypothesis.models import DataFilter, HypothesisCheck


def quote_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("Invalid SQL identifier")

    return '"' + value.replace('"', '""') + '"'


def numeric_expression(field_name: str) -> str:
    """Read numeric CSV values, including decimal commas, without coercing IDs."""
    field = quote_identifier(field_name)
    return f"TRY_CAST(NULLIF(REPLACE(TRIM(CAST({field} AS VARCHAR)), ',', '.'), '') AS DOUBLE)"


def sql_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite numbers are not supported")
        return str(value)

    if isinstance(value, (date, datetime)):
        value = value.isoformat()

    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"

    raise ValueError(f"Unsupported SQL literal type: {type(value).__name__}")


def build_filter_expression(item: DataFilter) -> str:
    field = quote_identifier(item.field)
    operator = item.operator
    value = item.value

    if operator == "is_null":
        return f"{field} IS NULL"

    if operator == "not_null":
        return f"{field} IS NOT NULL"

    if operator in {"in", "not_in"}:
        if not isinstance(value, list) or not value:
            raise ValueError("IN filter requires a non-empty list")

        values = ", ".join(sql_literal(part) for part in value)
        sql_operator = "IN" if operator == "in" else "NOT IN"
        return f"{field} {sql_operator} ({values})"

    if operator == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(
                "Operator 'between' requires exactly two values"
            )

        return (
            f"{field} BETWEEN "
            f"{sql_literal(value[0])} AND {sql_literal(value[1])}"
        )

    sql_operator = {
        "eq": "=",
        "ne": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
    }[operator]

    return f"{field} {sql_operator} {sql_literal(value)}"


def build_where(filters: list[DataFilter]) -> str:
    if not filters:
        return ""

    expressions = [
        build_filter_expression(item)
        for item in filters
    ]

    return " WHERE " + " AND ".join(
        f"({expression})" for expression in expressions
    )


def extract_rows(result: Any) -> list[dict[str, Any]]:
    rows = getattr(result, "rows", None)

    if rows is None:
        raise ValueError("Query result does not contain rows")

    normalized: list[dict[str, Any]] = []

    columns = getattr(result, "columns", None)
    names = [column.name for column in columns] if columns is not None else None

    for row in rows:
        if isinstance(row, dict):
            normalized.append(row)
        elif isinstance(row, list) and names is not None and len(row) == len(names):
            normalized.append(dict(zip(names, row)))
        elif hasattr(row, "model_dump"):
            normalized.append(row.model_dump())
        else:
            raise ValueError("Unsupported query row format")

    return normalized


class HypothesisImplementation(ABC):
    """Интерфейс одной конкретной проверки гипотезы."""

    method: str
    model: type[HypothesisCheck]

    def __init__(self, sources: Any) -> None:
        self.sources = sources

    @abstractmethod
    def execute(self, check: HypothesisCheck) -> dict[str, Any]:
        """Выполняет проверку и возвращает её данные."""

    def query(
        self,
        source_id: str,
        sql: str,
        *,
        row_limit: int | None = None,
    ) -> Any:
        return self.sources.query(
            source_id,
            sql,
            row_limit=row_limit,
        )
