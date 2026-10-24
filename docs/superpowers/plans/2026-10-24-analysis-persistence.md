# Analysis persistence implementation plan

> Execute with subagent-driven-development, sequential implementation and independent reviews.

**Goal:** Restore the same analysis and its source after reopening a chat.
**Architecture:** Add nullable source binding to chats and a versioned validated response payload to assistant messages. Additive SQLite migrations preserve old history. React restores existing result components from server payload.
**Stack:** FastAPI, Pydantic, SQLAlchemy/SQLite, React, Zod.

## 1. Backend and compatibility

- [ ] Add failing HTTP/repository tests in `tests/test_chat_persistence.py` for full response roundtrip, restart, old SQLite migration, source conflict before LLM, historical snapshot preservation.
- [ ] Extend `app/models.py`, `app/db/chat/models.py`, `app/db/chat/engine.py`, `app/chat_repository.py`, `app/main.py`. Contract: chat summaries/history have nullable `source_id`; assistant message has nullable `analysis_payload = {version: 1, response: AgentResponse}`. Avoid circular imports by storing JSON at model boundary and validating with AgentResponse in route/service.
- [ ] Atomically bind source before generation; reject changed source with HTTP 409. Existing unbound chats remain readable and bind only following explicit user action. Store assistant text and payload in same transaction, preserve them as immutable records.
- [ ] Run focused tests, then backend suite. Use `/Users/vsevolod/Desktop/program/Linza-BI/.venv/bin/python -m pytest`.

## 2. Frontend restoration

- [ ] Add failing tests in `frontend/src/App.test.tsx` and `frontend/src/api.test.ts` for empty localStorage, server binding overriding stale cache, preserved results and legacy history.
- [ ] Extend Zod schemas with optional nullable source_id and versioned analysis_payload; unsupported payload versions fall back to text with a clear missing-details notice.
- [ ] Update App history restoration to reuse original response and timing. Show archived history if source is missing, disable new calculations. Keep unknown-source legacy chats readable and require explicit source choice to continue.
- [ ] Run `npm --prefix frontend test` and `npm --prefix frontend run build`.

## 3. Delivery

- [ ] Independent spec review, then code quality review; resolve findings.
- [ ] Browser check reload and source restoration, add reproducible test where practical.
- [ ] Document migrations, limits, results and related GitHub issues. Commit and open PR linked to the narrow persistence issue; do not close broader metrics/dashboard issues on partial delivery.
