from datetime import datetime, UTC

import pytest

from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


@pytest.fixture
def service_and_source(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    service = SourceService(tmp_path / "data", catalog)
    try:
        source = service.register_csv(
            "sales.csv",
            b"id,revenue\n001,10\n002,20\n003,30\n",
        )
        yield service, source
    finally:
        catalog.close()


def test_readonly_query_returns_bounded_typed_result(service_and_source):
    service, source = service_and_source
    table = service.data_engine.table_name(source)

    result = service.query(
        source.source_id,
        'SELECT COUNT(*) AS "orders", SUM(TRY_CAST("revenue" AS BIGINT)) AS "revenue" FROM source',
        row_limit=10,
    )

    assert result.returned_rows == 1
    assert result.rows == [[3, 60]]
    assert [column.name for column in result.columns] == ["orders", "revenue"]
    assert result.provenance[0].source_id == source.source_id
    assert result.provenance[0].snapshot_id == source.snapshot_id


def test_cte_cannot_shadow_physical_source_even_with_different_case(service_and_source):
    from app.safe_sql import SafeQueryError

    service, source = service_and_source
    for alias in ("source", "SOURCE"):
        with pytest.raises(SafeQueryError) as caught:
            service.query(source.source_id,
                f'WITH {alias} AS (SELECT COUNT(*) AS revenue) SELECT SUM(revenue) AS total FROM {alias}')
        assert caught.value.code == "QUERY_REJECTED"


def test_cte_derived_from_physical_source_remains_usable(service_and_source):
    service, source = service_and_source
    result = service.query(source.source_id,
        'WITH amounts AS (SELECT TRY_CAST("revenue" AS BIGINT) AS amount FROM source) '
        'SELECT SUM(amount) AS total FROM amounts')
    assert result.rows == [[60]]


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO anything VALUES (1)",
        "CREATE TABLE x AS SELECT 1",
        "SELECT 1; DROP TABLE anything",
        "ATTACH 'outside.duckdb' AS outside",
        "COPY (SELECT 1) TO '/tmp/leak.csv'",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        'SELECT * FROM "someone_else_table"',
    ],
)
def test_readonly_query_rejects_unsafe_sql_without_echoing_it(service_and_source, sql):
    from app.safe_sql import SafeQueryError

    service, source = service_and_source
    with pytest.raises(SafeQueryError) as caught:
        service.query(source.source_id, sql)

    assert caught.value.code == "QUERY_REJECTED"
    assert sql not in str(caught.value)


def test_cte_comments_and_quoted_column_names_are_allowed(service_and_source):
    service, source = service_and_source
    table = service.data_engine.table_name(source)

    result = service.query(
        source.source_id,
        f'''-- expected analytical query
        WITH "daily totals" AS (
            SELECT "revenue" FROM "{table}"
        )
        SELECT SUM(TRY_CAST("revenue" AS BIGINT)) AS "total" FROM "daily totals"''',
    )

    assert result.rows == [[60]]


def test_row_limit_marks_result_as_truncated(service_and_source):
    service, source = service_and_source
    table = service.data_engine.table_name(source)

    result = service.query(
        source.source_id,
        f'SELECT "id" FROM "{table}" ORDER BY "id"',
        row_limit=2,
    )

    assert result.rows == [["001"], ["002"]]
    assert result.returned_rows == 2
    assert result.truncated is True


def test_timeout_interrupts_query_and_next_query_succeeds(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    service = SourceService(tmp_path / "data", catalog)
    try:
        rows = b"id,value\n" + b"1,1\n" * 500
        source = service.register_csv("large.csv", rows)
        table = service.data_engine.table_name(source)
        heavy_sql = (
            f'SELECT SUM(TRY_CAST(a."value" AS BIGINT)) FROM "{table}" a '
            f'CROSS JOIN "{table}" b CROSS JOIN "{table}" c'
        )
        from app.safe_sql import SafeQueryError
        with pytest.raises(SafeQueryError, match="QUERY_TIMEOUT") as caught:
            service.query(source.source_id, heavy_sql, timeout_seconds=0.001)
        assert caught.value.code == "QUERY_TIMEOUT"

        next_result = service.query(
            source.source_id,
            f'SELECT COUNT(*) AS "count" FROM "{table}"',
        )
        assert next_result.rows == [[500]]
    finally:
        catalog.close()


def test_query_tool_exposes_only_guarded_executor(service_and_source):
    from app.tools import build_tool_registry

    service, source = service_and_source
    registry = build_tool_registry(service.catalog, service)
    table = service.data_engine.table_name(source)

    allowed = registry.execute(
        "query_data",
        {"source_id": source.source_id, "sql": 'SELECT COUNT(*) AS "count" FROM source'},
    )
    blocked = registry.execute(
        "query_data",
        {"source_id": source.source_id, "sql": "SELECT * FROM read_csv_auto('/etc/passwd')"},
    )

    assert allowed.ok is True
    assert allowed.data.rows == [[3]]
    assert blocked.ok is False
    assert blocked.error == "QUERY_REJECTED"


def test_result_byte_budget_is_enforced_before_tool_output(service_and_source):
    from app.safe_sql import SafeQueryError

    service, source = service_and_source
    service.sql_executor.max_result_bytes = 4
    with pytest.raises(SafeQueryError) as caught:
        service.query(source.source_id, 'SELECT "id" FROM source')

    assert caught.value.code == "QUERY_REJECTED"


def test_result_byte_budget_stops_before_fetching_entire_result(monkeypatch, tmp_path):
    """A result budget is enforced while rows are streamed from DuckDB."""
    from app.contracts.v1 import Provenance
    from app.safe_sql import SafeQueryError, SafeQueryExecutor

    class Cursor:
        description = [("id", "VARCHAR")]

        def __init__(self):
            self.rows = iter([("001",), ("002",)])
            self.fetchall_called = False

        def fetchone(self):
            return next(self.rows, None)

        def fetchall(self):
            self.fetchall_called = True
            return [("001",), ("002",)]

    class Connection:
        def __init__(self):
            self.cursor = Cursor()

        def execute(self, _sql):
            return self.cursor

        def interrupt(self):
            pass

        def close(self):
            pass

    connection = Connection()
    monkeypatch.setattr("app.safe_sql.duckdb.connect", lambda *_args, **_kwargs: connection)
    executor = SafeQueryExecutor(tmp_path / "data.duckdb", max_result_bytes=4)

    with pytest.raises(SafeQueryError) as caught:
        executor.execute(
            "SELECT id FROM source",
            allowed_tables={"source": "physical_source"},
            provenance=Provenance(
                source_id="source",
                snapshot_id="snapshot",
                schema_version=1,
                tool_name="query_data",
                executed_at=datetime.now(UTC),
            ),
        )

    assert caught.value.code == "QUERY_REJECTED"
    assert connection.cursor.fetchall_called is False


def test_database_open_failure_is_an_internal_error(service_and_source, tmp_path):
    from app.safe_sql import SafeQueryError

    service, source = service_and_source
    service.sql_executor.database_path = tmp_path / "missing.duckdb"

    with pytest.raises(SafeQueryError) as caught:
        service.query(source.source_id, "SELECT 1 FROM source")

    assert caught.value.code == "INTERNAL_ERROR"


def test_elapsed_timeout_is_reported_after_a_query_completes(service_and_source):
    from app.safe_sql import SafeQueryError

    service, source = service_and_source

    with pytest.raises(SafeQueryError) as caught:
        service.query(source.source_id, "SELECT 1 FROM source", timeout_seconds=1e-9)

    assert caught.value.code == "QUERY_TIMEOUT"


def test_truncation_sentinel_does_not_consume_the_returned_result_budget(monkeypatch, tmp_path):
    from app.contracts.v1 import Provenance
    from app.safe_sql import SafeQueryExecutor

    class Cursor:
        description = [("value", "VARCHAR")]

        def __init__(self):
            self.rows = iter([("ok",), ("x" * 1_000_000,)])

        def fetchone(self):
            return next(self.rows, None)

    class Connection:
        def __init__(self):
            self.cursor = Cursor()

        def execute(self, _sql):
            return self.cursor

        def interrupt(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("app.safe_sql.duckdb.connect", lambda *_args, **_kwargs: Connection())
    executor = SafeQueryExecutor(tmp_path / "data.duckdb", max_result_bytes=100)

    result = executor.execute(
        "SELECT value FROM source",
        allowed_tables={"source": "physical_source"},
        provenance=Provenance(
            source_id="source",
            snapshot_id="snapshot",
            schema_version=1,
            tool_name="query_data",
            executed_at=datetime.now(UTC),
        ),
        row_limit=1,
    )

    assert result.rows == [["ok"]]
    assert result.truncated is True
