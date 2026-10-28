# Email accounts and profile implementation plan

**Goal:** Add email/password accounts, a small profile, and email-code password recovery on Railway without exposing one user's sources, chats, charts, or dashboards to another.

**Architecture:** PostgreSQL stores users, hashed sessions, throttling, and reset codes. Existing catalog and chat SQLite databases retain analytical data with owner columns; request context scopes every repository read/write. An explicit Railway bootstrap email/password claims legacy records on first deployment. Same-origin HttpOnly cookies authenticate the React UI.

**Tech Stack:** FastAPI, SQLAlchemy, psycopg, pwdlib Argon2, React, Vitest, pytest, GitHub Actions.

---

### Task 1: Auth contracts and persistence
- [ ] Add failing hosted tests for registration, login, logout, profile, reset codes, throttling, and session expiry.
- [ ] Implement PostgreSQL-backed auth store and HTTP routes.
- [ ] Add HTTPS email delivery through Resend and explicit unavailable state when not configured.

### Task 2: Tenant isolation
- [ ] Add failing hosted tests for cross-user source, chat, chart, dashboard and agent access.
- [ ] Add owner columns and migrations to existing SQLite databases.
- [ ] Scope repositories and protect API routes using request identity.
- [ ] Assign legacy data to the explicit bootstrap account only.

### Task 3: Interface
- [ ] Add failing frontend tests for account gate, profile, logout, password reset.
- [ ] Add compact login/register/recovery UI and profile controls in existing visual style.
- [ ] Remove browser state when switching accounts.

### Task 4: Deploy and verify
- [ ] Run hosted CI on draft PR, correct failures, and obtain review.
- [ ] Configure Railway PostgreSQL reference and bootstrap credentials, then merge.
- [ ] Confirm deployment, anonymous protection, first login, account isolation, and email delivery when SMTP credentials are available.
