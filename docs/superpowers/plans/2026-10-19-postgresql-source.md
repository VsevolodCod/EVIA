# PostgreSQL Source Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect EVIA to allowlisted PostgreSQL tables directly with read-only, bounded schema/profile/preview/query operations.

**Architecture:** PostgreSQL is a separate `DataSourceAdapter` and a separate guarded SQL executor; `SourceService` dispatches by `DataSource.source_type`, preserving the existing CSV/DuckDB route. A single optional deployment connection is configured from environment variables and registers one `DataSource` for each allowlisted table. Credentials remain only in `Settings` and driver connections.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, SQLGlot, PostgreSQL 16 Docker image, pytest.

---

## File structure

- Create `app/data_sources/postgresql_adapter.py`: read-only connection, allowlist discovery, schema, preview and bounded sampled profile.
- Create `app/postgresql_sql.py`: PostgreSQL guarded analytical `SELECT` execution and stable public errors.
- Modify `app/config.py`: parse optional PostgreSQL DSN, allowlist and safe connection/query budgets.
- Modify `app/models.py`: add non-secret remote object metadata to `DataSource`.
- Modify `app/source_service.py`: register remote sources and dispatch source operations without changing CSV behaviour.
- Modify `app/main.py`: initialize configured PostgreSQL sources at startup and expose a status-only connection check.
- Modify `app/tools/base.py`: route `query_data` through remote source dispatch and keep public errors stable.
- Modify `requirements.txt`: add `psycopg[binary]`.
- Create `tests/test_postgresql_adapter.py`: adapter/executor unit tests using a fake psycopg boundary.
- Create `tests/test_postgresql_integration.py`: opt-in integration checks against `POSTGRES_TEST_DSN`.
- Create `docker-compose.postgres-test.yml` and `scripts/verify_postgresql_source.sh`: disposable test database and acceptance runner.
- Create `docs/postgresql-source.md`: Railway configuration and safety contract.

### Task 1: Configuration and secret-free source metadata

**Files:**
- Modify: `app/config.py`
- Modify: `app/models.py`
- Test: `tests/test_postgresql_adapter.py`

- [ ] **Step 1: Write failing configuration and model tests**

```python
def test_postgresql_settings_are_optional_and_do_not_expose_dsn(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://reader:secret@db.example/analytics")
    monkeypatch.setenv("POSTGRES_ALLOWED_TABLES", "public.orders")
    settings = Settings()
    assert settings.postgres.enabled is True
    assert settings.postgres.allowed_tables == {("public", "orders")}
    assert "secret" not in settings.public_model_dump()


def test_remote_source_persists_only_object_identity():
    source = DataSource(
        source_id="postgresql:public:orders", name="public.orders",
        source_type="postgresql", schema_name="public", table_name="orders",
    )
    assert "postgresql://" not in source.model_dump_json()
```

- [ ] **Step 2: Run the targeted test and verify it fails**

Run: `python -m pytest tests/test_postgresql_adapter.py -q`
Expected: failure because `Settings.postgres` and remote source fields do not exist.

- [ ] **Step 3: Add minimum model/configuration types**

```python
@dataclass(frozen=True)
class PostgresSettings:
    dsn: str
    allowed_tables: frozenset[tuple[str, str]]
    connect_timeout_seconds: int = 5
    statement_timeout_ms: int = 10_000

    @property
    def enabled(self) -> bool:
        return bool(self.dsn and self.allowed_tables)
```

Parse comma-separated `POSTGRES_ALLOWED_TABLES` entries strictly as `schema.table`; reject malformed entries at startup. Add nullable `schema_name` and `table_name` to `DataSource`; never add DSN, username or password fields.

- [ ] **Step 4: Run the targeted test and verify it passes**

Run: `python -m pytest tests/test_postgresql_adapter.py -q`
Expected: configuration/model tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/models.py tests/test_postgresql_adapter.py
git commit -m "feat(postgres): add safe connection configuration"
```

### Task 2: Read-only adapter and bounded discovery

**Files:**
- Create: `app/data_sources/postgresql_adapter.py`
- Modify: `requirements.txt`
- Test: `tests/test_postgresql_adapter.py`

- [ ] **Step 1: Write failing adapter tests**

```python
def test_discovery_returns_only_allowlisted_tables(fake_postgres):
    adapter = PostgreSQLAdapter(settings=fake_postgres.settings, connect=fake_postgres.connect)
    assert adapter.discover() == [("public", "orders")]


def test_forbidden_object_never_reaches_the_driver(fake_postgres):
    adapter = PostgreSQLAdapter(settings=fake_postgres.settings, connect=fake_postgres.connect)
    with pytest.raises(PostgresSourceError, match="SOURCE_FORBIDDEN"):
        adapter.preview("private", "payroll", limit=10)
    assert fake_postgres.executed == []


def test_profile_has_a_bounded_sample_and_marks_its_counts_as_sampled(fake_postgres):
    profile = adapter.profile("public", "orders")
    assert profile["sample_size"] <= adapter.sample_size
    assert "bounded sample" in profile["note"]
```

- [ ] **Step 2: Run and verify failures**

Run: `python -m pytest tests/test_postgresql_adapter.py -q`
Expected: import failure for `PostgreSQLAdapter`.

- [ ] **Step 3: Implement the adapter**

Use `psycopg.connect(dsn, connect_timeout=...)` per operation. Immediately run `BEGIN READ ONLY`, `SET LOCAL statement_timeout = %s`, and close the connection in `finally`. Validate `(schema_name, table_name)` against `PostgresSettings.allowed_tables` before composing identifiers with `psycopg.sql.Identifier`.

Implement discovery with one `information_schema.columns` query constrained by `VALUES` of allowed pairs, grouping columns into `SourceSchema`. Implement preview as `SELECT * FROM schema.table LIMIT %s`. Profile only `sample_size` rows from a `LIMIT` subquery, calculate counts/top values in Python, and return `sample_size`, `sample_limit` and a note stating the values are sampled.

Map driver failures to `CONNECTION_FAILED`, `QUERY_TIMEOUT` or `INTERNAL_ERROR` without including exception text.

- [ ] **Step 4: Run adapter tests**

Run: `python -m pytest tests/test_postgresql_adapter.py -q`
Expected: all unit tests pass; no test inspects DSN/password values.

- [ ] **Step 5: Commit**

```bash
git add app/data_sources/postgresql_adapter.py requirements.txt tests/test_postgresql_adapter.py
git commit -m "feat(postgres): add allowlisted read-only adapter"
```

### Task 3: Guarded PostgreSQL query executor

**Files:**
- Create: `app/postgresql_sql.py`
- Test: `tests/test_postgresql_adapter.py`

- [ ] **Step 1: Write failing query tests**

```python
@pytest.mark.parametrize("sql", [
    "DELETE FROM source", "SELECT 1; DROP TABLE source",
    "SELECT * FROM private.payroll", "SELECT * FROM pg_read_file('/etc/passwd')",
])
def test_executor_rejects_unsafe_or_unallowlisted_sql(adapter, sql):
    with pytest.raises(PostgresQueryError, match="QUERY_REJECTED"):
        adapter.query("public", "orders", sql)


def test_executor_limits_rows_and_next_query_survives_timeout(adapter):
    with pytest.raises(PostgresQueryError, match="QUERY_TIMEOUT"):
        adapter.query("public", "orders", "SELECT pg_sleep(1) FROM source", timeout_seconds=0.001)
    assert adapter.query("public", "orders", "SELECT count(*) FROM source").rows == [[2]]
```

- [ ] **Step 2: Run and verify failures**

Run: `python -m pytest tests/test_postgresql_adapter.py -q`
Expected: `PostgreSQLAdapter.query` is missing.

- [ ] **Step 3: Implement `PostgresQueryExecutor`**

Parse with `sqlglot.parse(..., read="postgres")`. Permit exactly one `SELECT`/CTE/set-operation expression; reject node/function classes outside the #9 allowlist. Rewrite only the logical table `source` to an already validated schema/table identifier. Execute `SELECT * FROM (<query>) AS __evia_result LIMIT %s` in the adapter’s read-only transaction. Fetch one row at a time, enforce row/result-byte limits before append, return `QueryResult` with source provenance, and report only stable codes.

- [ ] **Step 4: Run query tests**

Run: `python -m pytest tests/test_postgresql_adapter.py -q`
Expected: unsafe SQL is rejected; timeout does not poison the next fresh query.

- [ ] **Step 5: Commit**

```bash
git add app/postgresql_sql.py tests/test_postgresql_adapter.py
git commit -m "feat(postgres): guard remote analytical queries"
```

### Task 4: Source-service and API integration without CSV regressions

**Files:**
- Modify: `app/source_service.py`
- Modify: `app/main.py`
- Modify: `app/tools/base.py`
- Test: `tests/test_postgresql_adapter.py`
- Test: `tests/test_csv_formats.py`
- Test: `tests/test_api_workspace.py`

- [ ] **Step 1: Write failing service/API tests**

```python
def test_registered_postgresql_source_uses_live_adapter_and_csv_stays_unchanged(service):
    remote = service.register_postgresql_sources()[0]
    assert service.preview(remote.source_id) == [{"id": 1, "amount": 10}]
    assert service.register_csv("sales.csv", b"id\n001\n").source_type == "csv"


def test_connection_status_endpoint_does_not_return_credentials(client):
    response = client.get("/sources/postgresql/status")
    assert response.json() == {"configured": True, "connected": True}
    assert "postgresql://" not in response.text
```

- [ ] **Step 2: Run and verify failures**

Run: `python -m pytest tests/test_postgresql_adapter.py tests/test_api_workspace.py -q`
Expected: registration and status endpoint are missing.

- [ ] **Step 3: Add source-type dispatch and status-only endpoint**

Construct `PostgreSQLAdapter` only when `settings.postgres.enabled`. Register each discovered table as `DataSource(source_type="postgresql", schema_name=..., table_name=..., status="available")`, save its live schema to the catalog, and route `get_schema`, `preview`, `profile` and `query` to the adapter. Preserve the exact constructor call `SourceService(data_dir, catalog)` so CSV tests need no new fixtures. Route `query_data` through `SourceService.query` and catch PostgreSQL stable errors just like `SafeQueryError`.

Expose `GET /sources/postgresql/status`: when unconfigured returns `{configured: false, connected: false}`; when configured returns connection status only. Do not expose DSN, host, username, table allowlist or driver exception details.

- [ ] **Step 4: Run affected tests**

Run: `python -m pytest tests/test_postgresql_adapter.py tests/test_csv_formats.py tests/test_api_workspace.py tests/test_agent.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/source_service.py app/main.py app/tools/base.py tests
git commit -m "feat(postgres): expose configured live sources"
```

### Task 5: Docker integration acceptance and operations guide

**Files:**
- Create: `docker-compose.postgres-test.yml`
- Create: `scripts/verify_postgresql_source.sh`
- Create: `tests/test_postgresql_integration.py`
- Create: `docs/postgresql-source.md`
- Modify: `README.md`

- [ ] **Step 1: Write opt-in integration tests**

```python
@pytest.mark.postgres_integration
def test_readonly_postgres_source_is_live_and_bounded(postgres_service):
    source = postgres_service.register_postgresql_sources()[0]
    assert postgres_service.preview(source.source_id)[0]["amount"] == 10
    postgres_service.test_admin_execute("UPDATE public.orders SET amount = 20 WHERE id = 1")
    assert postgres_service.preview(source.source_id)[0]["amount"] == 20
```

Add tests for a forbidden table, invalid password, disconnect and timeout followed by a fresh query. Skip only when `POSTGRES_TEST_DSN` is absent; the runner supplies it.

- [ ] **Step 2: Run and verify it is skipped without the fixture**

Run: `python -m pytest tests/test_postgresql_integration.py -q`
Expected: skipped with message requiring `POSTGRES_TEST_DSN`.

- [ ] **Step 3: Create a disposable Docker PostgreSQL setup**

`docker-compose.postgres-test.yml` uses `postgres:16-alpine`, an init SQL file that creates `evia_reader` with `CONNECT`, `USAGE` and `SELECT` only on `public.orders`, and a separate owner role for the external-update assertion. `scripts/verify_postgresql_source.sh` brings the service up, waits for `pg_isready`, exports the reader DSN, runs the marked test, and tears it down with `trap`.

Document Railway variables: `POSTGRES_DSN=${{Postgres.DATABASE_URL}}`, `POSTGRES_ALLOWED_TABLES=public.orders`; the hostname stays private in Railway. Explicitly state that no `POSTGRES_DSN` means no remote source is registered.

- [ ] **Step 4: Run acceptance, full tests and container verification**

Run:

```bash
./scripts/verify_postgresql_source.sh
python -m pytest -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
docker build -t evia-postgres-check .
```

Expected: integration suite passes with Docker; full test suite and frontend checks pass; production image builds.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.postgres-test.yml scripts/verify_postgresql_source.sh tests/test_postgresql_integration.py docs/postgresql-source.md README.md
git commit -m "docs(postgres): add Railway setup and integration verification"
```

### Task 6: Review and delivery

**Files:**
- Review: all changed files

- [ ] **Step 1: Inspect the staged diff and secret scan**

Run:

```bash
git diff origin/main...HEAD --check
rg -n "postgresql://[^$]|password=|POSTGRES_DSN=.*@" --glob '!docs/superpowers/**' .
```

Expected: no malformed diff; no committed real DSN/password.

- [ ] **Step 2: Request peer review**

Ask a non-author reviewer to validate all acceptance criteria, particularly CSV regression protection, read-only transactions and public error secrecy. Address any P1/P2 findings with a failing regression test first.

- [ ] **Step 3: Push and open a PR**

```bash
git push -u origin issue-23-postgresql-source
gh pr create --repo VsevolodCod/EVIA --base main --head issue-23-postgresql-source \
  --title "feat(postgres): add allowlisted read-only source" \
  --body-file /tmp/evia-pr-23.md
```

The PR body must include `Closes #23`, exact validation output, Railway configuration and the remaining limitation that the browser connection form belongs to #24.
