"""Versioned, synthetic gold cases for evaluating the CSV agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


class EvaluationCase(BaseModel):
    case_id: str = Field(pattern=r"^[a-z0-9-]+$")
    fixture: str
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    question: str = Field(min_length=1)
    expected_kind: Literal["computed", "clarify", "refuse"]
    gold_sql: str | None = None
    expected_columns: list[str] = Field(default_factory=list)
    expected_rows: list[list[Any]] = Field(default_factory=list)
    numeric_tolerance: str = "0"
    safe_reason: str | None = None

    @model_validator(mode="after")
    def validate_expected_result(self) -> "EvaluationCase":
        if Path(self.fixture).name != self.fixture or not self.fixture.endswith(".csv"):
            raise ValueError("fixture must be a CSV filename without a path")
        if self.expected_kind == "computed":
            if not self.gold_sql or not self.expected_columns:
                raise ValueError("computed case requires gold_sql and expected_columns")
            if self.safe_reason is not None:
                raise ValueError("computed case cannot have safe_reason")
        elif self.gold_sql is not None or self.expected_columns or self.expected_rows:
            raise ValueError("safe case cannot define a query result")
        elif not self.safe_reason:
            raise ValueError("safe case requires safe_reason")
        try:
            if Decimal(self.numeric_tolerance) < 0:
                raise ValueError("numeric_tolerance must be non-negative")
        except InvalidOperation as exc:
            raise ValueError("numeric_tolerance must be decimal") from exc
        return self


@dataclass(frozen=True)
class EvaluationCorpus:
    root: Path
    version: int
    cases: list[EvaluationCase]

    def fixture_path(self, case: EvaluationCase) -> Path:
        return self.root / "fixtures" / case.fixture

    def verify_fixture_hashes(self) -> list[str]:
        failures: list[str] = []
        for case in self.cases:
            path = self.fixture_path(case)
            if not path.is_file():
                failures.append(f"{case.case_id}: fixture is missing")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != case.fixture_sha256:
                failures.append(f"{case.case_id}: fixture SHA-256 does not match")
        return failures


@dataclass(frozen=True)
class EvaluationFailure:
    case_id: str
    reason: str


@dataclass
class EvaluationReport:
    corpus_version: int
    passed_computed: int = 0
    passed_safe: int = 0
    failed: list[EvaluationFailure] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus_version": self.corpus_version,
            "passed_computed": self.passed_computed,
            "passed_safe": self.passed_safe,
            "failed": [failure.__dict__ for failure in self.failed],
        }


def load_corpus(root: Path) -> EvaluationCorpus:
    root = Path(root).resolve()
    payload = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("Unsupported evaluation corpus version")
    cases = [EvaluationCase.model_validate(item) for item in payload.get("cases", [])]
    if len(cases) != len({case.case_id for case in cases}):
        raise ValueError("Evaluation case IDs must be unique")
    return EvaluationCorpus(root=root, version=1, cases=cases)


def _cell_matches(actual: Any, expected: Any, tolerance: Decimal) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return abs(Decimal(str(actual)) - Decimal(str(expected))) <= tolerance
        except (InvalidOperation, TypeError, ValueError):
            return False
    return actual == expected


def _rows_match(actual: list[list[Any]], expected: list[list[Any]], tolerance: Decimal) -> bool:
    if len(actual) != len(expected):
        return False
    return all(
        len(actual_row) == len(expected_row)
        and all(_cell_matches(value, wanted, tolerance) for value, wanted in zip(actual_row, expected_row))
        for actual_row, expected_row in zip(actual, expected)
    )


def verify_corpus(root: Path, *, data_dir: Path) -> EvaluationReport:
    """Execute every public gold query through the production CSV path."""
    corpus = load_corpus(root)
    report = EvaluationReport(corpus_version=corpus.version)
    bad_hash_cases = {message.split(":", 1)[0]: message for message in corpus.verify_fixture_hashes()}
    catalog = SchemaCatalog(Path(data_dir) / "catalog.sqlite3")
    try:
        sources = SourceService(Path(data_dir) / "sources", catalog)
        for case in corpus.cases:
            if case.case_id in bad_hash_cases:
                report.failed.append(EvaluationFailure(case.case_id, bad_hash_cases[case.case_id]))
                continue
            if case.expected_kind != "computed":
                report.passed_safe += 1
                continue
            try:
                source = sources.register_csv(case.fixture, corpus.fixture_path(case).read_bytes())
                result = sources.query(source.source_id, case.gold_sql or "")
                tolerance = Decimal(case.numeric_tolerance)
                actual_columns = [column.name for column in result.columns]
                if actual_columns != case.expected_columns:
                    raise ValueError(f"columns differ: {actual_columns!r}")
                if not _rows_match(result.rows, case.expected_rows, tolerance):
                    raise ValueError(f"rows differ: {result.rows!r}")
            except Exception as exc:
                report.failed.append(EvaluationFailure(case.case_id, str(exc)))
            else:
                report.passed_computed += 1
    finally:
        catalog.close()
    return report
