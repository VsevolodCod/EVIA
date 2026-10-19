# PostgreSQL source connector design

## Goal

Add issue #23 support for reading an allowlisted PostgreSQL table directly, without CSV export, while preserving every existing CSV workflow and keeping credentials out of the application’s public data.

## Scope and choices

Three options were considered:

1. Extend the CSV/DuckDB service until it also accepts remote connection strings. This is small initially, but mixes immutable CSV snapshots with live database access and caused the regressions in `integration/db_sources`.
2. Implement PostgreSQL, SQLite and ClickHouse through a common connection manager now. This creates a broad abstraction before the first production connector is proven and combines #23 with optional #40.
3. **Chosen:** add one focused PostgreSQL adapter behind an explicit source-type dispatch. The CSV path remains unchanged; PostgreSQL has its own connection, introspection, profile, preview and safe executor. SQLite and ClickHouse remain separate issues.

## Public behaviour

A deployment configures PostgreSQL through environment variables. The raw DSN exists only in process configuration; it is never saved in `SchemaCatalog`, returned from an endpoint, sent to the LLM, exported, or logged. The deployment config also names allowed schemas and tables.

At startup, the adapter discovers only the configured allowed tables and registers them as `DataSource(source_type="postgresql")`. A source is a live table, not a CSV snapshot. Preview, profile and analytical `query_data` access open a new read-only database transaction, so an external `UPDATE` is observable by the next request.

The existing UI does not need to expose a password form for #23. Issue #24 will add the connection UI. The existing hosted EVIA backend can use Railway’s private PostgreSQL hostname through `POSTGRES_DSN` / a variable reference; browsers continue to call only EVIA over HTTPS.

## Components

- `app/data_sources/postgresql_adapter.py` owns connection creation, allowlist validation, batched schema discovery, bounded preview/profile, and mapping PostgreSQL rows to existing models.
- `app/postgresql_sql.py` owns PostgreSQL-specific guarded `SELECT` execution. It reuses the parser policy from #9 conceptually but does not make DuckDB depend on psycopg.
- `app/source_service.py` dispatches source actions by `source_type`. Its CSV methods and constructor stay compatible with all existing tests.
- `app/config.py` parses PostgreSQL setup; no secret-bearing setting is rendered by `/health`.
- `app/main.py` registers configured PostgreSQL sources at startup and exposes the existing source/schema/preview/profile paths for them. A narrow connection check endpoint returns status only, never DSN details.

## Safety and resource bounds

Every operation uses a fresh `psycopg` connection. It sets a read-only transaction, a server-side `statement_timeout`, a client connection timeout, bounded rows, and a maximum serialized result budget. The executor accepts one parsed `SELECT`/CTE/set operation, rewrites only logical allowlisted table names, and rejects DDL/DML, multiple statements, table functions, schemas outside the allowlist and unknown tables.

Schema discovery queries `information_schema` in bounded batches instead of creating an inspector/query sequence for every object. Profiling samples a fixed number of rows and returns counts as sampled estimates with an explicit note; it does not scan an unbounded remote table.

Public errors use stable codes (`CONNECTION_FAILED`, `SOURCE_FORBIDDEN`, `QUERY_REJECTED`, `QUERY_TIMEOUT`, `INTERNAL_ERROR`). Internal logs record codes and source IDs only. DSNs, passwords, database error strings and generated SQL are not included in responses or tool results.

## Verification

Unit tests cover allowlist enforcement, stable secret-free errors, CSV regression protection, SQL validation, result caps, disconnect handling and fresh-query semantics through a fake driver boundary. A Docker PostgreSQL integration fixture creates a read-only role and a previously unknown table; its acceptance script verifies discovery, forbidden schema, bad credentials, a fresh query after an external update and a timeout followed by a successful query.

## Out of scope

This work does not add ClickHouse, SQLite, a browser password form, credential persistence, dashboard persistence, or a generic multi-database framework.
