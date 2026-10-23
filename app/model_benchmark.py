"""Scoring primitives for reproducible local-model evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any, Awaitable, Callable, Literal, Protocol, Sequence

import asyncio
import inspect

import httpx

from app.evaluation import EvaluationCase, rows_match
from app.evaluation import EvaluationCorpus
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


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


@dataclass(frozen=True)
class ModelBenchmark:
    model: str
    metadata: dict[str, Any]
    outcomes: list[CaseOutcome]
    summary: RunSummary
    modes: dict[str, RunSummary]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "metadata": self.metadata,
            "outcomes": [outcome.as_dict() for outcome in self.outcomes],
            "summary": self.summary.as_dict(),
            "modes": {name: summary.as_dict() for name, summary in self.modes.items()},
        }


@dataclass(frozen=True)
class BenchmarkReport:
    schema_version: int
    corpus_version: int
    models: list[ModelBenchmark]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_version": self.corpus_version,
            "models": [model.as_dict() for model in self.models],
        }


class ModelMetadataClient(Protocol):
    async def describe(self, model: str) -> dict[str, Any]: ...

    async def unload(self, model: str) -> bool: ...


class OllamaMetadataClient:
    """Minimal Ollama control surface used by the offline evaluator."""

    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30, trust_env=False, transport=self.transport) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

    async def describe(self, model: str) -> dict[str, Any]:
        tags = (await self._request("GET", "/api/tags")).json().get("models", [])
        tag = next((item for item in tags if item.get("name") == model), None)
        if tag is None:
            raise ValueError(f"Model is not downloaded locally: {model}")
        show = (await self._request("POST", "/api/show", json={"model": model})).json()
        version = (await self._request("GET", "/api/version")).json()
        return {
            "name": model,
            "digest": tag.get("digest"),
            "size_bytes": tag.get("size"),
            "modified_at": tag.get("modified_at"),
            "details": tag.get("details", {}),
            "model_info": show.get("model_info", {}),
            "ollama_version": version.get("version"),
        }

    async def unload(self, model: str) -> bool:
        await self._request("POST", "/api/generate", json={"model": model, "keep_alive": 0})
        for attempt in range(5):
            loaded = (await self._request("GET", "/api/ps")).json().get("models", [])
            if not any(item.get("name") == model for item in loaded):
                return True
            if attempt < 4:
                await asyncio.sleep(0.1)
        return False


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


AgentFactory = Callable[[str, SourceService], Any | Awaitable[Any]]


class BenchmarkRunner:
    """Run the public corpus through production source and agent components."""

    def __init__(
        self,
        corpus: EvaluationCorpus,
        work_dir: Path,
        agent_factory: AgentFactory,
        metadata: ModelMetadataClient,
    ) -> None:
        self.corpus = corpus
        self.work_dir = Path(work_dir)
        self.agent_factory = agent_factory
        self.metadata = metadata

    async def run(self, models: Sequence[str], *, warm_repeats: int, cold: bool) -> BenchmarkReport:
        if not models:
            raise ValueError("At least one model is required")
        if warm_repeats < 0:
            raise ValueError("warm_repeats must be non-negative")
        failures = self.corpus.verify_fixture_hashes()
        if failures:
            raise ValueError("Evaluation corpus verification failed: " + "; ".join(failures))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        results: list[ModelBenchmark] = []
        for model in models:
            metadata = await self.metadata.describe(model)
            outcomes: list[CaseOutcome] = []
            if cold:
                for case in self.corpus.cases:
                    if not await self.metadata.unload(model):
                        outcomes.append(self._system_failure(case, mode="cold", code="MODEL_UNLOAD_FAILED"))
                    else:
                        outcomes.append(await self._run_case(model, case, mode="cold"))
            for _ in range(warm_repeats):
                for case in self.corpus.cases:
                    outcomes.append(await self._run_case(model, case, mode="warm"))
            grouped = {
                mode: summarize_runs([outcome for outcome in outcomes if outcome.mode == mode])
                for mode in ("cold", "warm")
                if any(outcome.mode == mode for outcome in outcomes)
            }
            results.append(ModelBenchmark(
                model=model,
                metadata=metadata,
                outcomes=outcomes,
                summary=summarize_runs(outcomes),
                modes=grouped,
            ))
        return BenchmarkReport(schema_version=1, corpus_version=self.corpus.version, models=results)

    async def _run_case(self, model: str, case: EvaluationCase, *, mode: BenchmarkMode) -> CaseOutcome:
        started = perf_counter()
        try:
            with TemporaryDirectory(dir=self.work_dir, prefix="evia-benchmark-") as folder:
                root = Path(folder)
                catalog = SchemaCatalog(root / "catalog.sqlite3")
                try:
                    sources = SourceService(root / "sources", catalog)
                    source = sources.register_csv(case.fixture, self.corpus.fixture_path(case).read_bytes())
                    agent = self.agent_factory(model, sources)
                    if inspect.isawaitable(agent):
                        agent = await agent
                    response = await agent.ask(case.question, [source.source_id])
                finally:
                    catalog.close()
        except Exception:
            return self._system_failure(case, mode=mode, code="BENCHMARK_EXCEPTION", elapsed_ms=(perf_counter() - started) * 1000)
        outcome = score_response(case, response, mode=mode)
        if outcome.elapsed_ms == 0:
            return CaseOutcome(**{**outcome.__dict__, "elapsed_ms": (perf_counter() - started) * 1000})
        return outcome

    @staticmethod
    def _system_failure(
        case: EvaluationCase,
        *,
        mode: BenchmarkMode,
        code: str,
        elapsed_ms: float = 0,
    ) -> CaseOutcome:
        return CaseOutcome(
            case_id=case.case_id,
            expected_kind=case.expected_kind,
            mode=mode,
            exact_match=False,
            json_valid=False,
            valid_sql=False if case.expected_kind == "computed" else None,
            status="error",
            error_code=code,
            elapsed_ms=elapsed_ms,
            sql=None,
        )
