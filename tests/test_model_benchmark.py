from types import SimpleNamespace

import pytest

from app.evaluation import EvaluationCase
from app.evaluation import load_corpus
from app.model_benchmark import BenchmarkRunner, score_response, summarize_runs


COMPUTED = EvaluationCase(
    case_id="total",
    fixture="sales.csv",
    fixture_sha256="a" * 64,
    question="Какая сумма?",
    expected_kind="computed",
    gold_sql="SELECT SUM(amount) AS total FROM source_typed",
    expected_columns=["total"],
    expected_rows=[["450.00"]],
    numeric_tolerance="0.0001",
)
SAFE = EvaluationCase(
    case_id="outside-data",
    fixture="sales.csv",
    fixture_sha256="a" * 64,
    question="Какая погода?",
    expected_kind="clarify",
    safe_reason="В источнике нет погоды.",
)


def response(*, status="answered", rows=None, columns=None, sql="SELECT 1", error_code=None, elapsed_ms=42):
    return SimpleNamespace(
        status=status,
        analysis=SimpleNamespace(sql=sql) if sql is not None else None,
        results=[] if rows is None else [SimpleNamespace(
            columns=[SimpleNamespace(name=name) for name in (columns or ["total"])],
            rows=rows,
        )],
        error=SimpleNamespace(code=error_code) if error_code else None,
        timing=SimpleNamespace(elapsed_ms=elapsed_ms),
    )


def test_computed_case_requires_matching_typed_result():
    outcome = score_response(COMPUTED, response(rows=[["450.00"]]), mode="warm")

    assert outcome.exact_match is True
    assert outcome.valid_sql is True
    assert outcome.json_valid is True


def test_safe_case_requires_clarification_without_sql():
    outcome = score_response(SAFE, response(status="clarification", sql=None), mode="warm")

    assert outcome.exact_match is True
    assert outcome.valid_sql is None
    assert outcome.json_valid is True


def test_validation_error_is_an_invalid_json_plan():
    outcome = score_response(
        COMPUTED,
        response(status="error", sql=None, error_code="VALIDATION_ERROR"),
        mode="cold",
    )

    assert outcome.exact_match is False
    assert outcome.json_valid is False
    assert outcome.error_code == "VALIDATION_ERROR"


def test_summary_uses_all_runs_for_ex_json_errors_and_nearest_rank_latency():
    outcomes = [
        score_response(COMPUTED, response(rows=[["450.00"]], elapsed_ms=10), mode="warm"),
        score_response(COMPUTED, response(rows=[["400.00"]], elapsed_ms=20), mode="warm"),
        score_response(SAFE, response(status="clarification", sql=None, elapsed_ms=30), mode="warm"),
        score_response(COMPUTED, response(status="error", sql=None, error_code="MODEL_UNAVAILABLE", elapsed_ms=40), mode="warm"),
    ]

    summary = summarize_runs(outcomes)

    assert summary.exact_match_rate == 0.5
    assert summary.json_validity_rate == 0.75
    assert summary.valid_sql_rate == 2 / 3
    assert summary.errors == 1
    assert summary.timeouts == 0
    assert summary.p50_latency_ms == 20
    assert summary.p95_latency_ms == 40


class FakeMetadata:
    def __init__(self, unload_result=True):
        self.unload_result = unload_result
        self.described = []
        self.unloaded = []

    async def describe(self, model):
        self.described.append(model)
        return {"name": model, "digest": f"digest-{model}"}

    async def unload(self, model):
        self.unloaded.append(model)
        return self.unload_result


class FakeAgent:
    def __init__(self):
        self.questions = []

    async def ask(self, question, source_ids):
        self.questions.append((question, source_ids))
        return response(status="error", sql=None, error_code="MODEL_UNAVAILABLE")


async def _fake_agent_factory(_model, _sources):
    return FakeAgent()


@pytest.mark.asyncio
async def test_runner_imports_each_fixture_and_runs_each_case_for_every_model(tmp_path):
    corpus = load_corpus(__import__("pathlib").Path(__file__).parents[1] / "evals" / "v1")
    runner = BenchmarkRunner(corpus, tmp_path, _fake_agent_factory, FakeMetadata())

    report = await runner.run(["first", "second"], warm_repeats=1, cold=False)

    expected_ids = [case.case_id for case in corpus.cases]
    assert [item.case_id for item in report.models[0].outcomes] == expected_ids
    assert [item.case_id for item in report.models[1].outcomes] == expected_ids
    assert all(item.mode == "warm" for model in report.models for item in model.outcomes)


@pytest.mark.asyncio
async def test_cold_mode_marks_run_invalid_when_ollama_does_not_confirm_unload(tmp_path):
    corpus = load_corpus(__import__("pathlib").Path(__file__).parents[1] / "evals" / "v1")
    metadata = FakeMetadata(unload_result=False)
    runner = BenchmarkRunner(corpus, tmp_path, _fake_agent_factory, metadata)

    report = await runner.run(["first"], warm_repeats=0, cold=True)

    assert len(report.models[0].outcomes) == len(corpus.cases)
    assert {item.error_code for item in report.models[0].outcomes} == {"MODEL_UNLOAD_FAILED"}
    assert metadata.unloaded == ["first"] * len(corpus.cases)
