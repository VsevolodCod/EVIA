# EVIA analytics workspace — #46

Approved direction: a native React profiling workspace in EVIA green, with Overview,
Columns, Quality, Data, Schema and Result sections. The user approved implementation
on 18 October 2026. This task changes presentation of existing API data only.

## Design and boundaries

- SourceInspector owns source loading and section navigation. New profile components
  consume its existing Profile and SourceSchema responses; they never fetch separately.
- profileModel normalizes schema fields and profile columns and computes sample cell
  counts. Missing profile fields stay unavailable, never implicitly zero. A sample
  completion percentage means populated cells, not a general data quality score.
- Overview shows dataset row/column counts, sample coverage, completeness, type mix
  and fields needing attention. Quality links to filtered column details. Column
  charts show top-value counts, not invented histograms or time series.
- Current CSV profiling uses at most the first 500 rows. Every statistical view
  identifies this coverage; full dataset counts come only from schema row_count.
- Result presents the safe Markdown answer beside computed tables. Raw tool payloads
  remain accessible in closed disclosures. Existing chat Entry/API contracts remain.
- Charts include visible numeric values. Layout stacks on narrow screens and supports
  keyboard navigation. No new runtime dependencies or external assets.

## Execution checklist

- [x] Add interaction tests against SourceInspector for overview, search, quality
  drill-down, empty and partial profiles, source switch and safe result rendering.
  Run `npm --prefix frontend test -- --run src/features/sources/SourceInspector.test.tsx`
  and verify missing-feature failures before implementation.
- [x] Implement `profileModel.ts`, `ProfileOverview.tsx`, `ProfileColumns.tsx`,
  `ProfileQuality.tsx` and scoped `analytics.css`; wire sections into SourceInspector.
  Set App's default/source-selection view to overview, preserving explicit preview.
- [x] Add `AnalysisResult.tsx`, friendly table titles and collapsed technical data;
  preserve SafeMarkdown and raw tool payloads, including failure and empty states.
- [x] Update existing preview tests to select Data explicitly. Run the full frontend
  suite and `npm --prefix frontend run build`.
- [x] Extend browser acceptance for overview → quality → column → data → question →
  result, source switching, keyboard use and mobile overflow. Run against isolated
  FastAPI with mock inference. Inspect desktop and mobile screenshots.
- [x] Review the diff and run relevant checks, then create a PR with Closes #46.
  Leave a running local preview and document how to inspect it. Do not merge.

## References

- https://docs.profiling.ydata.ai/latest/examples/titanic/titanic_report.html
- https://docs.profiling.ydata.ai/latest/getting-started/quickstart/
- https://docs.profiling.ydata.ai/latest/features/custom_reports/
- https://docs.profiling.ydata.ai/latest/features/big_data/

YData can export JSON for a future profile adapter. Its Python dependency and richer
statistics belong to the data-engine contract work (#8); generated dashboard charts
and agent reasoning belong to #22/#26/#27/#29. No dependency on those issues for the
current bounded-profile UI.
