# Evaluation Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe, versioned corpus of 20 gold CSV questions that can be executed and verified before benchmarking local LLMs.

**Architecture:** Store compact synthetic fixtures and case metadata under `evals/v1`. A small evaluation module will load fixtures through `SourceService`, execute approved gold SQL via the existing read-only query path, and compare typed results. A CLI emits JSON suitable for #14 and fails closed on corpus drift.

**Tech Stack:** Python 3.14, Pydantic models, DuckDB through EVIA `SourceService`, pytest.

---

### Task 1: Corpus schema and fixtures

**Files:**
- Create: `evals/v1/cases.json`
- Create: `evals/v1/fixtures/*.csv`
- Test: `tests/test_evaluation_corpus.py`

- [ ] **Step 1: Write failing corpus validation tests**

```python
def test_v1_has_twenty_unique_cases_and_fixture_hashes():
    corpus = load_corpus(CORPUS_PATH)
    assert len(corpus.cases) == 20
    assert len({case.case_id for case in corpus.cases}) == 20
    assert all(case.fixture_sha256 for case in corpus.cases)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_evaluation_corpus.py::test_v1_has_twenty_unique_cases_and_fixture_hashes`
Expected: FAIL because `load_corpus` does not exist.

- [ ] **Step 3: Define Pydantic corpus models and public synthetic fixtures**

Create models for `computed`, `clarify`, and `refuse`; reject SQL on non-computed cases. Add five source fixtures and 20 cases covering each risk declared in the design.

- [ ] **Step 4: Run validation test**

Run: `python -m pytest -q tests/test_evaluation_corpus.py::test_v1_has_twenty_unique_cases_and_fixture_hashes`
Expected: PASS.

### Task 2: Gold-query execution and comparison

**Files:**
- Create: `app/evaluation.py`
- Modify: `tests/test_evaluation_corpus.py`

- [ ] **Step 1: Write failing execution tests**

```python
def test_gold_cases_execute_through_source_service(tmp_path):
    report = verify_corpus(CORPUS_PATH, data_dir=tmp_path / "data")
    assert report.failed == []
    assert report.passed_computed == 17
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_evaluation_corpus.py::test_gold_cases_execute_through_source_service`
Expected: FAIL because `verify_corpus` does not exist.

- [ ] **Step 3: Implement the verifier**

Load each fixture with `SourceService`, compare its SHA-256 to metadata, execute `gold_sql` only through the existing safe executor, and compare ordered scalar values using `Decimal`. Return an explicit failure record instead of silently coercing invalid values.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_evaluation_corpus.py`
Expected: PASS.

### Task 3: CLI and documentation

**Files:**
- Create: `scripts/verify_eval_corpus.py`
- Modify: `README.md`
- Test: `tests/test_evaluation_corpus.py`

- [ ] **Step 1: Write failing CLI test**

```python
def test_cli_writes_machine_readable_report(tmp_path):
    completed = run_cli(tmp_path / "report.json")
    assert completed.returncode == 0
    assert json.loads((tmp_path / "report.json").read_text())["failed"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_evaluation_corpus.py::test_cli_writes_machine_readable_report`
Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement CLI and README command**

Use `--output` for JSON, print a compact summary, and exit nonzero on every corpus failure. Document that fixtures are synthetic and explain how #14 consumes the report.

- [ ] **Step 4: Verify the full suite**

Run: `python -m pytest -q && npm --prefix frontend test -- --run && npm --prefix frontend run build`
Expected: all tests and build pass.
