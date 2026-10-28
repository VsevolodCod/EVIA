# Dashboard chart variety

EVIA currently persists and renders only KPI and line cards. A category such as `segment` is drawn as a line, and two numeric fields cannot form a scatter plot. The requested dashboard scenario needs several correct chart types without model-generated code.

## Decision

Use the existing declarative chart definition, `QueryPlanner`, `ChartExecutor`, chart repository and `GeneratedDashboard` path. Add bar, scatter and table as first-class variants. Bar shares line's grouped aggregate data contract but renders bars. Scatter displays raw numeric pairs, retains duplicate pairs, omits rows with NULL axes explicitly, and has a point limit. Table displays selected raw fields with a row limit. The backend validates field type and single-source compatibility before execution. Each result includes source provenance and visible limit metadata. Saved dashboards use the same renderer as newly created ones.

The dashboard agent may choose KPI, line, bar, scatter or table. It receives exact field names and types. Fallback is deterministic: numeric measure plus date → KPI and line; numeric measure plus category → KPI and bar; two numeric measures → KPI and scatter; text-only source → row count and table. A failed card is shown separately and does not fabricate a KPI.

Alternatives considered: changing only the browser visualization is faster but cannot establish a validated scatter/table artifact or persistence contract. Letting the LLM emit arbitrary chart code is harder to reproduce and unsafe. First-class declarative types fit the existing architecture.

## Acceptance

Use synthetic CSV fixtures to verify distinct numeric results for each type, invalid type/source rejection, dates, NULLs, stable ordering, point/row limits, saved reopen, and accessible rendering. Run backend, frontend and browser checks in hosted GitHub Actions. Run a small live smoke on Railway after merge. Do not run the app or model on the owner's laptop.
