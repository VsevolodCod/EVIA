"""Scoring primitives for reproducible local-model evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from typing import Any, Literal

from app.evaluation import EvaluationCase, rows_match


BenchmarkMode = Literal["cold", "warm"]


@dataclass(frozen=True)
class CaseOutcome:
    """One model answer scored against one versioned evaluation case."""

    case_id: str
    expected_kind: str
    mode: BenchmarkMode
    exact_match: bool
    json_valid: bool
    valid_sql: bool | None
    status: str
    error_code: str | None
    elapsed_ms: float
    sql: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_kind": self.expected_kind,
            "mode": self.mode,
            "exact_match": self.exact_match,
            "json_valid": self.json_valid,
            "valid_sql": self.valid_sql,
            "status": self.status,
            "error_code": self.error_code,
            "elapsed_ms": self.elapsed_ms,
            "sql": self.sql,
        }


@dataclass(frozen=True)
class RunSummary:
    run_count: int
    exact_match_rate: float
    json_validity_rate: float
    valid_sql_rate: float | None
    errors: int
    timeouts: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_count": self.run_count,
            "exact_match_rate": self.exact_match_rate,
            "json_validity_rate": self.json_validity_rate,
            "valid_sql_rate": self.valid_sql_rate,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
        }


_INVALID_JSON_CODES = {"VALIDATION_ERROR", "MODEL_OUTPUT_INCOMPLETE", "MODEL_UNAVAILABLE"}
_TIMEOUT_CODES = {"QUERY_TIMEOUT"}


def _response_error_code(response: Any) -> str | None:
    error = getattr(response, "error", None)
    return getattr(error, "code", None) if error is not None else None


def _response_sql(response: Any) -> str | None:
    analysis = getattr(response, "analysis", None)
    return getattr(analysis, "sql", None) if analysis is not None else None


def _response_elapsed_ms(response: Any) -> float:
    timing = getattr(response, "timing", None)
    value = getattr(timing, "elapsed_ms", 0) if timing is not None else 0
    return float(value or 0)


def score_response(case: EvaluationCase, response: Any, *, mode: BenchmarkMode) -> CaseOutcome:
    """Score an already-executed production agent response without reading answer prose."""
    status = str(getattr(response, "status", "error"))
    error_code = _response_error_code(response)
    sql = _response_sql(response)
    json_valid = error_code not in _INVALID_JSON_CODES and status in {"answered", "clarification"}
    valid_sql: bool | None = None
    exact_match = False

    if case.expected_kind == "computed":
        valid_sql = bool(status == "answered" and sql and not error_code)
        results = list(getattr(response, "results", []) or [])
        if valid_sql and results:
            result = results[0]
            actual_columns = [column.name for column in result.columns]
            exact_match = (
                actual_columns == case.expected_columns
                and rows_match(result.rows, case.expected_rows, Decimal(case.numeric_tolerance))
            )
    else:
        exact_match = status == "clarification" and sql is None and error_code is None

    return CaseOutcome(
        case_id=case.case_id,
        expected_kind=case.expected_kind,
        mode=mode,
        exact_match=exact_match,
        json_valid=json_valid,
        valid_sql=valid_sql,
        status=status,
        error_code=error_code,
        elapsed_ms=_response_elapsed_ms(response),
        sql=sql,
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = max(0, ceil(percentile * len(sorted_values)) - 1)
    return sorted_values[index]


def summarize_runs(outcomes: list[CaseOutcome]) -> RunSummary:
    """Aggregate records with explicit denominators; no omitted failure is a pass."""
    count = len(outcomes)
    if not count:
        return RunSummary(0, 0, 0, None, 0, 0, None, None)
    computed = [outcome for outcome in outcomes if outcome.expected_kind == "computed"]
    errors = [outcome for outcome in outcomes if outcome.status == "error"]
    return RunSummary(
        run_count=count,
        exact_match_rate=sum(item.exact_match for item in outcomes) / count,
        json_validity_rate=sum(item.json_valid for item in outcomes) / count,
        valid_sql_rate=(sum(item.valid_sql is True for item in computed) / len(computed)) if computed else None,
        errors=len(errors),
        timeouts=sum(item.error_code in _TIMEOUT_CODES for item in outcomes),
        p50_latency_ms=_percentile([item.elapsed_ms for item in outcomes], 0.50),
        p95_latency_ms=_percentile([item.elapsed_ms for item in outcomes], 0.95),
    )
