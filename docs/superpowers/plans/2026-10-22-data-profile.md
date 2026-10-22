# Достоверный профиль датасета — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** дать продукту и агенту точный паспорт конкретной версии CSV без смешения полных и выборочных результатов.

**Architecture:** DuckDB выполняет полные агрегаты над raw- и typed-таблицами в одном согласованном соединении. Результат описывается расширенным контрактом профиля, возвращается через текущий endpoint и отображается в существующих разделах аналитики. Выборочные топ-значения остаются отдельным полем с явным охватом.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, DuckDB, React, TypeScript, Zod, pytest, Vitest.

---

### Task 1: Контракт полного и выборочного профиля

**Files:**
- Modify: `app/contracts/v1.py`
- Modify: `frontend/src/api.ts`
- Test: `tests/test_contracts.py`
- Test: `frontend/src/api.test.ts`

- [ ] **Step 1: Write the failing Python contract tests**

```python
def test_profile_accepts_exact_column_statistics():
    profile = Profile.model_validate({
        "sample_size": 5, "sample_limit": 500, "processed_rows": 12,
        "coverage": "full", "columns": {"amount": {
            "non_null_count": 10, "null_count": 1, "empty_count": 1,
            "distinct_count": 8, "uniqueness_ratio": 0.8,
            "top_values": [], "top_values_coverage": "sample",
            "numeric": {"count": 10, "minimum": "-2.5", "maximum": "9", "sum": "20", "average": "2"},
        }}, "note": "Exact statistics use the full snapshot.",
    })
    assert profile.coverage == "full"
```

- [ ] **Step 2: Run the targeted test and confirm it fails because the new fields are absent**

Run: `python -m pytest tests/test_contracts.py -q -k exact_column_statistics`

- [ ] **Step 3: Add Pydantic models for coverage, exact counts, numeric/date ranges and identifier candidacy**

```python
class NumericProfile(BaseModel):
    count: int = Field(ge=0)
    minimum: str | None = None
    maximum: str | None = None
    total: str | None = None
    average: str | None = None

class ColumnProfile(BaseModel):
    non_null_count: int = Field(ge=0)
    null_count: int = Field(ge=0)
    empty_count: int = Field(ge=0)
    distinct_count: int = Field(ge=0)
    uniqueness_ratio: float = Field(ge=0, le=1)
    top_values_coverage: Literal["sample"]
```

- [ ] **Step 4: Mirror the validated fields in the Zod API schema and add an API parsing test**

Run: `npm test -- --run src/api.test.ts`

- [ ] **Step 5: Run both contract test files and commit**

Run: `python -m pytest tests/test_contracts.py -q && npm test -- --run src/api.test.ts`

Commit: `git commit -am "feat(profile): define exact snapshot statistics contract"`

### Task 2: Точные агрегаты DuckDB

**Files:**
- Modify: `app/data_engine.py`
- Test: `tests/test_duckdb_engine.py`

- [ ] **Step 1: Write failing tests for exact counts and numeric/date boundaries**

```python
def test_profile_separates_null_empty_and_zero_and_uses_full_table(engine, source, csv_path):
    engine.import_csv(source, csv_path, delimiter=",", typed_sql_types={"amount": "DECIMAL(38,2)", "day": "DATE"})
    profile = engine.profile(source)
    assert profile["processed_rows"] == 4
    assert profile["columns"]["amount"]["null_count"] == 1
    assert profile["columns"]["amount"]["empty_count"] == 1
    assert profile["columns"]["amount"]["numeric"]["total"] == "0.50"
```

- [ ] **Step 2: Run the test and confirm it fails because the current profile samples rows only**

Run: `python -m pytest tests/test_duckdb_engine.py -q -k full_table`

- [ ] **Step 3: Implement one full-table aggregation per column with raw/typed semantics**

```python
raw = self._quote_identifier(self.table_name(source))
typed = self._quote_identifier(self.typed_table_name(source))
# raw counts preserve empty strings; typed values supply numeric/date aggregates.
```

- [ ] **Step 4: Add exact ID candidate detection and sample-only top values**

```python
is_identifier_candidate = (
    non_null_count == processed_rows
    and empty_count == 0
    and distinct_count == processed_rows
)
```

- [ ] **Step 5: Run DuckDB tests and commit**

Run: `python -m pytest tests/test_duckdb_engine.py -q`

Commit: `git commit -am "feat(profile): calculate exact CSV snapshot statistics"`

### Task 3: Source service, endpoint and invalidation semantics

**Files:**
- Modify: `app/source_service.py`
- Modify: `app/main.py`
- Test: `tests/test_csv_import_pipeline.py`
- Test: `tests/test_api_workspace.py`

- [ ] **Step 1: Write failing service tests for snapshot-specific profile results**

```python
def test_reimport_returns_profile_for_the_new_snapshot_only(service):
    first = service.register_csv("sales.csv", b"id,amount\n001,10\n")
    assert service.profile(first.source_id)["columns"]["amount"]["numeric"]["total"] == "10"
    service.register_csv("sales.csv", b"id,amount\n001,20\n", source_id=first.source_id)
    assert service.profile(first.source_id)["columns"]["amount"]["numeric"]["total"] == "20"
```

- [ ] **Step 2: Run the service test and confirm it fails before profile fields are propagated**

Run: `python -m pytest tests/test_csv_import_pipeline.py -q -k reimport_returns_profile`

- [ ] **Step 3: Propagate `snapshot_id`, exact coverage and processed row count through `SourceService.profile`**

```python
profile = self.data_engine.profile(source, self.csv_adapter.sample_size)
profile["snapshot_id"] = source.snapshot_id
return profile
```

- [ ] **Step 4: Add API-level assertions for the endpoint response and source snapshot**

Run: `python -m pytest tests/test_api_workspace.py -q`

- [ ] **Step 5: Commit**

Commit: `git commit -am "feat(profile): expose exact snapshot profile through API"`

### Task 4: Понятное отображение в аналитике

**Files:**
- Modify: `frontend/src/features/sources/SourceInspector.tsx`
- Modify: `frontend/src/features/analytics/Dashboard.tsx`
- Modify: `frontend/src/app.css`
- Test: `frontend/src/features/sources/SourceInspector.test.tsx`
- Test: `frontend/src/features/analytics/Dashboard.test.tsx`

- [ ] **Step 1: Write failing UI tests for full-dataset and sample labels**

```tsx
expect(await screen.findByText("Статистика по всему датасету")).toBeInTheDocument();
expect(screen.getByText("Топ-значения: выборка 500 строк")).toBeInTheDocument();
```

- [ ] **Step 2: Run the focused tests and confirm the labels are absent**

Run: `npm test -- --run src/features/sources/SourceInspector.test.tsx src/features/analytics/Dashboard.test.tsx`

- [ ] **Step 3: Render exact counts, missing-value breakdown, numeric/date intervals and candidate-ID disclaimer**

```tsx
<p className="profile-coverage">Статистика по всему датасету: {profile.processed_rows.toLocaleString("ru-RU")} строк</p>
```

- [ ] **Step 4: Render sample-only labels beside top-value lists and keep the existing responsive layout**

- [ ] **Step 5: Run focused frontend tests, production build and commit**

Run: `npm test -- --run src/features/sources/SourceInspector.test.tsx src/features/analytics/Dashboard.test.tsx && npm run build`

Commit: `git commit -am "feat(profile): distinguish exact and sample statistics in UI"`

### Task 5: Приёмочная проверка и документация

**Files:**
- Modify: `docs/issue-8-data-profile.md`
- Test: `tests/test_csv_import_pipeline.py`
- Test: `tests/test_duckdb_engine.py`

- [ ] **Step 1: Add a test that profiles the fully validated nine-file corpus without storing source rows in Git**

```python
assert profile["coverage"] == "full"
assert profile["processed_rows"] == source.import_report.accepted_rows
```

- [ ] **Step 2: Document fields, exact-vs-sample rules and query cost**

- [ ] **Step 3: Run all backend tests, frontend tests, production build and audit command**

Run: `python -m pytest -q && npm test -- --run && npm run build && python -m scripts.verify_csv_imports 'прогон таски 5' --report /tmp/evia-issue8-audit.json`

- [ ] **Step 4: Review working tree and commit documentation**

Run: `git diff --check && git status --short`

Commit: `git commit -am "docs(profile): describe trustworthy dataset passport"`
