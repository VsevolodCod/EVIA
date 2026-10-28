# Dashboard chart variety implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support server-validated line, bar, scatter and table charts in generated and saved EVIA dashboards.

**Architecture:** Extend the existing discriminated chart definitions and executor registry. Reuse grouped aggregation for bar, add bounded raw scatter/table implementations, let the dashboard agent select appropriate types, and render each type in the shared React dashboard component.

**Tech Stack:** Python 3, Pydantic, DuckDB/SourceService, pytest; React/TypeScript, Vitest; GitHub Actions and Railway.

---

### Task 1: Chart definitions and execution

**Files:** `app/charts/models.py`, `app/charts/query_planner.py`, `app/charts/implementations/`, `app/charts/engine.py`, `tests/test_charts.py`.

- [ ] Add failing tests for bar grouping, scatter numeric pairs, table rows, type rejection, NULL/order/limit behavior.
- [ ] Verify RED in hosted CI; no local app/test run.
- [ ] Implement the minimal declarative definitions, validation and implementations.
- [ ] Verify GREEN in hosted CI and inspect SQL/data against fixtures.

### Task 2: Dashboard agent selection

**Files:** `app/dashboard_query_agent.py`, `tests/test_agent.py`.

- [ ] Add failing tests for date, category, two-number and text-only schemas plus a model-selected chart.
- [ ] Verify RED in hosted CI.
- [ ] Expand draft validation, prompt and deterministic fallback; reject fabricated fields.
- [ ] Verify GREEN in hosted CI.

### Task 3: Frontend and saved dashboards

**Files:** `frontend/src/features/results/GeneratedDashboard.tsx`, `SavedDashboard.tsx`, CSS and component tests.

- [ ] Add failing tests that generated and saved bar/scatter/table cards render their real data, with accessible labels and explicit limits.
- [ ] Verify RED in hosted CI.
- [ ] Implement rendering using the existing SVG/table conventions.
- [ ] Verify GREEN in hosted CI.

### Task 4: Review, release and issue acceptance

- [ ] Review changes against #26 and #29 criteria, request an independent code review.
- [ ] Run full hosted CI on the PR and `main` after merge.
- [ ] Verify Railway deployment and live dashboard creation/reopen for synthetic schemas.
- [ ] Close only issues whose full acceptance criteria have evidence; document remaining gaps.
