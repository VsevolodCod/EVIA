from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.charts.errors import InvalidFilterError
from app.charts.models import Aggregate, DashboardFilter


AGGREGATE_SQL: dict[Aggregate, str] = {
    "count": "COUNT(*)",
    "sum": "SUM",
    "avg": "AVG",
    "min": "MIN",
    "max": "MAX",
}


def quote_identifier(name: str) -> str:
    """Экранирует имя SQL-идентификатора, а не SQL-выражение."""
    if not name or "\x00" in name:
        raise ValueError("Invalid SQL identifier")

    return '"' + name.replace('"', '""') + '"'


def sql_literal(value: Any) -> str:
    """
    Преобразует одно JSON-значение в SQL-литерал.

    Идентификаторы и выражения сюда передавать нельзя.
    """
    if value is None:
        return "NULL"

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidFilterError("Filter value must be finite")
        return repr(value)

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise InvalidFilterError("Filter value must be finite")
        return format(value, "f")

    if isinstance(value, (date, datetime)):
        value = value.isoformat()

    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"

    # Сложные произвольные JSON-объекты не являются допустимыми
    # значениями скалярного фильтра.
    raise InvalidFilterError(
        f"Unsupported filter value type: {type(value).__name__}"
    )


def aggregate_expression(aggregate: Aggregate, field: str) -> str:
    if aggregate == "count":
        return "COUNT(*)"

    function = AGGREGATE_SQL[aggregate]
    return f"{function}({quote_identifier(field)})"


def filter_expression(item: DashboardFilter) -> str:
    field = quote_identifier(item.field.field)
    operator = item.operator
    value = item.value

    if operator == "is_null":
        return f"{field} IS NULL"

    if operator == "is_not_null":
        return f"{field} IS NOT NULL"

    if operator == "eq":
        return f"{field} = {sql_literal(value)}"

    if operator == "ne":
        return f"{field} <> {sql_literal(value)}"

    if operator in {"gt", "gte", "lt", "lte"}:
        sql_operator = {
            "gt": ">",
            "gte": ">=",
            "lt": "<",
            "lte": "<=",
        }[operator]
        return f"{field} {sql_operator} {sql_literal(value)}"

    if operator in {"in", "not_in"}:
        values = ", ".join(sql_literal(v) for v in value)
        sql_operator = "IN" if operator == "in" else "NOT IN"
        return f"{field} {sql_operator} ({values})"

    if operator == "between":
        low, high = value
        return (
            f"{field} BETWEEN {sql_literal(low)} "
            f"AND {sql_literal(high)}"
        )

    raise InvalidFilterError(f"Unsupported filter operator: {operator}")


def where_clause(filters: list[DashboardFilter]) -> str:
    if not filters:
        return ""

    return " WHERE " + " AND ".join(
        f"({filter_expression(item)})" for item in filters
    )


def normalize_sql_value(value: Any) -> Any:
    """Приводит типы результата к значениям, сериализуемым в JSON."""
    if isinstance(value, Decimal):
        # Decimal сериализуем строкой, чтобы не терять точность.
        return format(value, "f")

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, float) and not math.isfinite(value):
        return None

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)
