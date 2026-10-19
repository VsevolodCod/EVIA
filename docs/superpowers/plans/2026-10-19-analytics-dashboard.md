# EVIA analytics dashboard implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dense source overview with a calm, DataLens-inspired dashboard based only on rows received from EVIA APIs, with user-controlled chart palettes and print-to-PDF.

**Architecture:** A pure dashboard-model module infers safe, generic visualizations from the bounded source preview or successful tabular tool result. React chart components render that model as accessible SVG and accept a validated local palette. `SourceInspector` owns loading and selects the dashboard without changing backend contracts.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, native SVG, browser print API.

---

### Task 1: Data model for actual rows

**Files:**
- Create: `frontend/src/features/analytics/dashboardModel.ts`
- Create: `frontend/src/features/analytics/dashboardModel.test.ts`

- [x] **Step 1: Write failing tests** for numeric summary, categorical counts, date sorting, blank values, identifiers, and no-chart datasets.
- [x] **Step 2: Run** `npm test -- --run src/features/analytics/dashboardModel.test.ts` and verify the missing-module failure.
- [x] **Step 3: Implement** a pure model that never invents business labels, excludes identifier-like fields from aggregates, and labels every calculation as applying to the returned row set.
- [x] **Step 4: Run** the focused test again and verify it passes.
- [x] **Step 5: Commit** the model and its tests.

### Task 2: Palette validation and persistence

**Files:**
- Create: `frontend/src/features/analytics/palette.ts`
- Create: `frontend/src/features/analytics/palette.test.ts`

- [x] **Step 1: Write failing tests** for presets, valid JSON/text palettes, rejected invalid colors, stable category assignment and storage fallback.
- [x] **Step 2: Run** `npm test -- --run src/features/analytics/palette.test.ts` and verify the missing-module failure.
- [x] **Step 3: Implement** validation for 2–12 `#RRGGBB` colors, deterministic assignment by series key and scoped local persistence.
- [x] **Step 4: Run** the focused test again and verify it passes.
- [x] **Step 5: Commit** the palette utilities and tests.

### Task 3: Dashboard UI and source integration

**Files:**
- Create: `frontend/src/features/analytics/Dashboard.tsx`
- Create: `frontend/src/features/analytics/PaletteEditor.tsx`
- Create: `frontend/src/features/analytics/dashboard.css`
- Create: `frontend/src/features/analytics/Dashboard.test.tsx`
- Modify: `frontend/src/features/sources/SourceInspector.tsx`
- Modify: `frontend/src/features/sources/analytics.css`

- [x] **Step 1: Write failing component tests** for rendered KPI/cards, palette edit/import rejection, data-table fallback, keyboard-visible chart values and print action.
- [x] **Step 2: Run** `npm test -- --run src/features/analytics/Dashboard.test.tsx` and verify the missing-component failure.
- [x] **Step 3: Implement** neutral cards, responsive grid, SVG charts, accessible labels/tooltips, palette panel and print styles; wire the existing source preview/profile into the overview while preserving technical tabs.
- [x] **Step 4: Run** the focused tests and then `npm test` and `npm run build` from `frontend`.
- [x] **Step 5: Commit** the UI integration.

### Task 4: Agent-result dashboard and manual acceptance

**Files:**
- Modify: `frontend/src/features/results/AnalysisResult.tsx`
- Modify: `frontend/src/features/results/ToolResults.tsx`
- Modify: `frontend/src/features/sources/SourceInspector.test.tsx`
- Modify: `docs/dashboard-agent-contract.md`

- [x] **Step 1: Write failing tests** for rendering a chartable successful tool table as an analysis dashboard and falling back to the existing table for non-tabular or failed tools.
- [x] **Step 2: Run** the focused test and verify it fails for the missing dashboard result.
- [x] **Step 3: Implement** result selection without merging unrelated tool outputs, document the proposed non-executable `DashboardSpecV1` contract, and keep current safe markdown/table behavior.
- [ ] **Step 4: Run** all frontend tests and build. Inspect 1440 px, 900 px, 390 px, palette import and a generated print PDF manually.
- [x] **Step 5: Commit**, request review, and update the draft PR without merging or closing #58.
