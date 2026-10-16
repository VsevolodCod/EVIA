# Fullstack Workspace Implementation Plan

> Execute issue #1 in this session, using subagent-driven-development for the bounded frontend task and sequential specification/code review. All changes stay on the issue branch.

**Goal:** CSV upload and selection, safe Markdown chat, actual tabular results and an expressive accessible mascot on the existing API.
**Architecture:** React feature modules and a typed API adapter; per-conversation source and messages in memory. Existing FastAPI remains authoritative and serves the built bundle after its API routes.
**Tech Stack:** React, TypeScript, Vite, react-markdown/GFM, Vitest/Testing Library, Python/FastAPI/pytest.

## 1. Baseline and frontend (frontend/)
- [x] Install backend dependencies into an isolated venv and run existing pytest tests.
- [x] Frontend implementer creates package.json/lock, Vite + strict TS and test setup.
- [x] Write failing tests for Markdown attack payloads, source-bound request/results, network retry and empty tables before their corresponding implementation.
- [x] Implement src/api (types, checked requests), src/features/sources (upload and metadata), src/features/chat (conversation state, Markdown, composer), src/features/results (tabular tools and data details), src/components (mascot and shared UI), App and responsive styles.
- [x] Use real /health, /sources, /sources/csv, /sources/{id}/{schema,preview,profile}, /agent/ask endpoints. Vite proxies these paths to 127.0.0.1:8000; production uses same-origin endpoints.
- [x] Run npm test and npm run build; record results and actual dependency versions.

## 2. Local integration (app/web.py, app/main.py, scripts/run.py, tests/test_web.py, tests/test_run.py)
- [x] Write failing pytest cases for built root/asset delivery, API precedence, missing build and paths outside bundle.
- [x] Implement mount_frontend(app, directory) using StaticFiles(html=True) only if index.html exists, after API registration.
- [x] Add launcher with --dev, --host and --port: use current Python interpreter, check required tools/build, launch uvicorn plus optional Vite, propagate shutdown and child failures. No downloads during launch.
- [x] Test command construction and missing-build preflight; run all pytest tests.

## 3. Documentation and real API verification
- [x] Update .gitignore for frontend/node_modules, frontend/dist, test outputs, .worktrees and logs; add only a synthetic sample-data/sales.csv with text IDs.
- [x] README documents setup, dev/production, source API shapes, mock limitations, semicolon/SQL dependencies, local history and reduced motion.
- [x] Start production launcher on a free loopback port. Check HTML/assets, upload synthetic CSV, read schema/preview/profile and ask mock provider over HTTP. Assert source IDs stay textual and API responds with the expected shape.
- [x] Run component tests covering source switching and late responses; attempt browser preview only with supported available browser tools, report unavailability if absent.

## 4. Review and delivery
- [x] Review against issue #1 and code-quality inspection; backend received independent review. Fixed the reported launcher process-group shutdown defect and added its regression test. Final independent full-stack re-review was unavailable; remaining review was performed by the primary implementer.
- [x] Verify no secrets, runtime data or source PDF in staged files; compare diff against origin/tes/pipeline_1.
- [ ] Commit, push issue branch and create PR targeting tes/pipeline_1 with Closes #1, checks and limitations. Do not merge or close issue.

## Final verification — 2026-10-16

- `npm --prefix frontend test`: 15 passed across 3 files.
- `npm --prefix frontend run build`: strict TypeScript check and Vite production build passed.
- `.venv/bin/python -m pytest -q`: 13 passed, including real HTTP checks in production and development modes, CSV upload/schema/preview/profile/mock agent, Vite proxy and shutdown of both listening ports.
- `git diff --check`: passed.
- `git fetch origin`: backend base remains current; no new commits on `origin/tes/pipeline_1` relative to the issue branch baseline.
- Native browser interaction was attempted but repeatedly interrupted by the computer-use safeguard for concurrent user changes. No visual desktop/mobile or keyboard browser acceptance is claimed. Responsive CSS, reduced-motion rules and accessible control labels were inspected in code; these do not replace visual QA.
- Windows launcher and real Ollama inference were not exercised. Full SQL execution is outside issue #1 and remains an A/B dependency.
