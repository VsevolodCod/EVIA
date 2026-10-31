# EVIA — defense preparation

[English README](../../README.en.md) · [Русский](DEFENSE.md) · [Demonstration guide](EXPERT_GUIDE.en.md) · [Architecture](ARCHITECTURE.en.md)

## Short introduction

EVIA is a web application for exploring tabular data with an AI assistant. A user uploads CSV or selects a preconfigured PostgreSQL table, inspects its structure and quality, asks questions in natural language, and reviews a table, chart or SQL result. Selected answers can be included in a PDF and created dashboards can be saved and reopened.

These are supported capabilities, not a guarantee that the model always answers correctly. Demonstrate an actual checked result on a prepared source.

## A 3–4 minute demonstration

1. **Problem.** Explain the unified interface for data, questions and inspectable results.
2. **Source.** Upload the synthetic CSV in the [guide](EXPERT_GUIDE.en.md#1-preparation) and show the overview and fields: three rows and `period`, `revenue`, `segment`.
3. **Quality.** Open Columns, Quality and Data. Explain preview versus the full source. Empty strings and NULL can currently be counted differently in the overview and PDF: [#152](https://github.com/VsevolodCod/EVIA/issues/152).
4. **Question.** Ask for the sum of `revenue`; for the example the result is **600**. Open the result and explain how to check SQL and returned values. If the model fails, show the error honestly and use a previously saved example.
5. **Visualization and report.** Show a previously checked chart or saved dashboard. Open the PDF report builder, select available answers and show the document contents. The browser's print dialog saves the PDF.
6. **Architecture.** Name React, FastAPI, the agent and tools, DuckDB and the configured LLM API; mention read-only PostgreSQL and account/history storage.

## Common questions

**How is EVIA different from a generic model chat?**
It has a selected source, schema and profile, server-side calculation tools, SQL restrictions, saved results and visualizations. The model helps select actions; numerical results should be checked against the data and tool output.

**How is data connected?**
CSV is imported as a source with a schema and snapshot. An administrator configures PostgreSQL using a DSN and table allowlist; arbitrary end-user connection setup is not claimed.

**How is data protected?**
When enabled, the server checks user sessions and ownership. Passwords are hashed with Argon2. PostgreSQL access is read-only and table-restricted; CSV SQL is constrained. Database permissions, safe secret storage and backups remain necessary.

**What does the language model do?**
Depending on the question, the agent calls a configured model and tools. Provider and model are server settings; `mock` is a demonstration mode. Do not claim every request is understood correctly or that mock tests establish real-model quality.

**Is a preview a full calculation?**
No. Preview rows and their charts can cover only part of the data. Check scope, SQL, row counts and truncation. A profile can cover the full source or a sample.

**Can a chart or hypothesis be trusted automatically?**
Check fields, aggregation, filters, scales and result data. An anomaly does not prove an error, and correlation does not establish causation. Numbers should be backed by an executed tool.

**What happens when data changes?**
Opening a dashboard displays the saved result. Explicit refresh recalculates it; a failed refresh preserves the old result. CSV snapshot staleness can be detected; PostgreSQL row changes without schema changes are not always detected automatically.

**Why email, and where are passwords stored?**
Email and password are used to sign in; passwords are stored as hashes. Code-based recovery requires a configured email provider. When authentication is enabled, accounts and sessions are stored in PostgreSQL.

**What are the limitations?**
The model, network and storage affect availability; arbitrary text-to-SQL and dashboard generation are not guaranteed; previews and results are limited; empty strings and NULL have inconsistent treatment ([#152](https://github.com/VsevolodCod/EVIA/issues/152)). Work such as arbitrary PostgreSQL setup and versioned business metrics is tracked in [issues](https://github.com/VsevolodCod/EVIA/issues).

**Do all tests pass?**
Do not claim this without a fresh check. In the [CI run used for this documentation](https://github.com/VsevolodCod/EVIA/actions/runs/41166332811), frontend and browser passed; backend had 16 failures. Check the latest run before presenting.

## Before presenting

- [ ] Confirm the site opens, login works and the deployment matches the commit being presented.
- [ ] Check free storage and model availability; `/health` checks the application, not model quality.
- [ ] On a test account, upload the synthetic CSV and verify schema, quality, sum **600**, chart and PDF.
- [ ] Prepare a saved dashboard and a backup screenshot or recording; do not represent a recording as a live run.
- [ ] Check password recovery only if email delivery is configured and available.
- [ ] Review current CI and open issues; do not describe incomplete criteria as complete.
- [ ] Confirm team roles, demo responsibilities and the license answer with the team.
