# Reproducible Local Model Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evaluate two or more local Ollama models against the versioned `evals/v1` CSV corpus and save comparable, fail-closed measurements.

**Architecture:** Keep benchmark logic independent of argparse in `app/model_benchmark.py`. The runner imports each synthetic fixture through `SourceService`, calls the production `AgentRuntime` once per case, and turns typed responses into serialisable case records. A thin CLI owns Ollama discovery/unload, environment construction, JSON output and an optional Markdown summary. Unit tests use scripted agents and a fake Ollama HTTP transport, so CI never needs a model.

**Tech Stack:** Python 3.11, asyncio, Pydantic contracts, DuckDB through `SourceService`, httpx, pytest.

---

### Task 1: Typed result comparison and metric aggregation

**Files:**
- Create: `app/model_benchmark.py`
- Test: `tests/test_model_benchmark.py`

- [ ] **Step 1: Write failing tests for computed, safe, and failed outcomes**

```python
def test_computed_case_requires_matching_typed_result():
    outcome = score_response(case, answered_response(rows=[["450.00"]]))
    assert outcome.exact_match is True
    assert outcome.valid_sql is True
    assert outcome.json_valid is True

def test_safe_case_requires_clarification_without_sql():
    outcome = score_response(safe_case, clarification_response())
    assert outcome.exact_match is True
    assert outcome.valid_sql is None

def test_validation_error_is_an_invalid_json_plan():
    outcome = score_response(case, validation_error_response())
    assert outcome.exact_match is False
    assert outcome.json_valid is False
```

- [ ] **Step 2: Run the focused tests and confirm import failure**

Run: `pytest tests/test_model_benchmark.py -q`

Expected: failure because `app.model_benchmark` does not exist.

- [ ] **Step 3: Implement immutable `CaseOutcome`, `RunSummary`, `score_response`, and `summarize_runs`**

```python
@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    expected_kind: str
    mode: Literal["cold", "warm"]
    exact_match: bool
    json_valid: bool
    valid_sql: bool | None
    status: str
    error_code: str | None
    elapsed_ms: float

def score_response(case: EvaluationCase, response: AgentResponse, mode: str) -> CaseOutcome:
    # computed: match columns/rows using Decimal tolerance from app.evaluation
    # safe: only status=clarification and analysis.sql is None succeeds
    # VALIDATION_ERROR and unavailable/incomplete outputs are never JSON-valid
```

Expose a non-private `rows_match` helper from `app.evaluation` instead of duplicating Decimal/NULL/order comparison. Count all outcomes in EX and JSON denominators, count SQL only for computed cases, and calculate percentiles with nearest-rank semantics for deterministic one-item samples.

- [ ] **Step 4: Run the focused tests and confirm they pass**

Run: `pytest tests/test_model_benchmark.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the metric foundation**

```bash
git add app/evaluation.py app/model_benchmark.py tests/test_model_benchmark.py
git commit -m "feat(evals): score local model benchmark outcomes"
```

### Task 2: Corpus runner and model metadata client

**Files:**
- Modify: `app/model_benchmark.py`
- Test: `tests/test_model_benchmark.py`

- [ ] **Step 1: Write failing async tests for equal inputs and cold unload**

```python
@pytest.mark.asyncio
async def test_runner_imports_each_fixture_and_runs_each_case_for_every_model(tmp_path):
    report = await runner.run(["first", "second"], modes=["warm"])
    assert [item.case_id for item in report.models[0].outcomes] == CASE_IDS
    assert [item.case_id for item in report.models[1].outcomes] == CASE_IDS

@pytest.mark.asyncio
async def test_cold_mode_marks_run_invalid_when_ollama_does_not_confirm_unload():
    report = await runner.run(["first"], modes=["cold"])
    assert report.models[0].outcomes[0].error_code == "MODEL_UNLOAD_FAILED"
```

- [ ] **Step 2: Run the focused tests and confirm the missing runner behaviour fails**

Run: `pytest tests/test_model_benchmark.py -q`

Expected: FAIL because `BenchmarkRunner` and cold-mode unload handling are absent.

- [ ] **Step 3: Implement `OllamaMetadataClient` and `BenchmarkRunner`**

```python
class OllamaMetadataClient:
    async def describe(self, model: str) -> dict[str, Any]: ...
    async def unload(self, model: str) -> bool:
        # POST /api/generate {"model": model, "keep_alive": 0}, then poll /api/ps.
        # HTTP success alone is insufficient: success means the tag is absent from /api/ps.

class BenchmarkRunner:
    async def run(self, models: Sequence[str], *, warm_repeats: int, cold: bool) -> BenchmarkReport:
        # verify corpus hashes before calls; create a temporary catalog/source for each case;
        # create the model-bound production AgentRuntime through injected factory;
        # never put fixture rows or full answers in report.
```

The report stores model tag/show metadata, `case_id`, status/error code, generated SQL, elapsed timing and aggregate metrics. It must not include CSV contents, source IDs, prompts other than the public corpus case ID, or model answer text.

- [ ] **Step 4: Run focused tests and the existing corpus tests**

Run: `pytest tests/test_model_benchmark.py tests/test_evaluation_corpus.py -q`

Expected: PASS.

- [ ] **Step 5: Commit runner implementation**

```bash
git add app/model_benchmark.py tests/test_model_benchmark.py
git commit -m "feat(evals): run versioned corpus against local models"
```

### Task 3: CLI, reports, and operational documentation

**Files:**
- Create: `scripts/benchmark_local_models.py`
- Modify: `README.md`
- Modify: `docs/local-llm-evaluation-2026-10-20.md`
- Test: `tests/test_model_benchmark.py`

- [ ] **Step 1: Write failing CLI tests for JSON and Markdown artifacts**

```python
def test_cli_writes_versioned_json_and_short_markdown_report(tmp_path, monkeypatch):
    exit_code = main([
        "first", "second", "--output", str(tmp_path / "report.json"),
        "--markdown", str(tmp_path / "report.md"), "--warm-repeats", "2",
    ])
    assert exit_code == 0
    assert json.loads((tmp_path / "report.json").read_text())['schema_version'] == 1
    assert "p95" in (tmp_path / "report.md").read_text()
```

- [ ] **Step 2: Run the focused test and confirm command is unavailable**

Run: `pytest tests/test_model_benchmark.py -q`

Expected: FAIL because `scripts.benchmark_local_models` does not exist.

- [ ] **Step 3: Add an argparse CLI and renderer**

```python
parser.add_argument("models", nargs="+", help="Downloaded Ollama tags; pass at least two")
parser.add_argument("--url", default="http://127.0.0.1:11434")
parser.add_argument("--warm-repeats", type=int, default=2)
parser.add_argument("--skip-cold", action="store_true")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--markdown", type=Path)
```

Fail before benchmark calls when fewer than two models are passed, a fixture hash is wrong, or the model is not installed. Exit non-zero when any case has error/timeout, any safety case fails, or model metadata cannot be read. Document an exact command using `qwen2.5-coder:7b` and `qwen2.5-coder:3b`, explain that results are local evidence rather than a committed universal ranking, and deprecate the two-question script.

- [ ] **Step 4: Run tests and a deterministic dry run with fake dependencies**

Run: `pytest tests/test_model_benchmark.py tests/test_evaluation_corpus.py -q`

Expected: PASS.

- [ ] **Step 5: Commit CLI and docs**

```bash
git add scripts/benchmark_local_models.py README.md docs/local-llm-evaluation-2026-10-20.md tests/test_model_benchmark.py
git commit -m "feat(evals): publish reproducible local model benchmark"
```

### Task 4: Full verification and local two-model evidence

**Files:**
- Create locally only: `/tmp/evia-model-benchmark.json`
- Create locally only: `/tmp/evia-model-benchmark.md`

- [ ] **Step 1: Run the whole backend suite**

Run: `pytest -q`

Expected: all non-optional tests pass.

- [ ] **Step 2: Run the documented benchmark against two installed models**

Run: `LLM_PROVIDER=ollama THINKING=0 MAX_TOKENS_G=512 TIMEOUT=120 python -m scripts.benchmark_local_models qwen2.5-coder:7b qwen2.5-coder:3b --output /tmp/evia-model-benchmark.json --markdown /tmp/evia-model-benchmark.md`

Expected: both artifacts record the same corpus version, every denominator, cold/warm modes, timing percentiles and per-case failures. The runner may exit non-zero if a model fails; record that finding rather than hiding it.

- [ ] **Step 3: Inspect that report has no source rows or answers**

Run: `rg -n '120,|450.00|Запрос выполнен' /tmp/evia-model-benchmark.json /tmp/evia-model-benchmark.md`

Expected: no matches.

- [ ] **Step 4: Commit the final code only**

```bash
git status --short
git add app/evaluation.py app/model_benchmark.py scripts/benchmark_local_models.py tests/test_model_benchmark.py README.md docs/local-llm-evaluation-2026-10-20.md
git commit -m "test(evals): verify local model benchmark"
```
