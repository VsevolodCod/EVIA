"""Opt-in acceptance checks against a disposable PostgreSQL instance."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from app.config import PostgresSettings
from app.data_sources.postgresql_adapter import PostgresSourceError, PostgreSQLAdapter
from app.models import DataSource
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService

pytestmark = pytest.mark.postgres_integration


@pytest.fixture
def postgres_service(tmp_path: Path):
    reader_dsn = os.getenv("POSTGRES_TEST_DSN")
    admin_dsn = os.getenv("POSTGRES_TEST_ADMIN_DSN")
    if not reader_dsn or not admin_dsn:
        pytest.skip("POSTGRES_TEST_DSN and POSTGRES_TEST_ADMIN_DSN are required")
    settings = PostgresSettings(
        dsn=reader_dsn,
        allowed_tables=frozenset({("public", "orders")}),
        connect_timeout_seconds=5,
        statement_timeout_ms=10_000,
    )
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    service = SourceService(
        tmp_path / "data",
        catalog,
        postgres_adapter=PostgreSQLAdapter(settings),
    )
    try:
        yield service, admin_dsn
    finally:
        catalog.close()


def test_readonly_source_reflects_external_update_and_rejects_forbidden_table(postgres_service):
    service, admin_dsn = postgres_service
    source = service.register_postgresql_sources()[0]

    assert service.query(source.source_id, "SELECT id, amount FROM source ORDER BY id", row_limit=1).rows == [[1, 10]]
    with psycopg.connect(admin_dsn) as admin:
        admin.execute("UPDATE public.orders SET amount = 20 WHERE id = 1")
        admin.commit()
    assert service.query(source.source_id, "SELECT id, amount FROM source ORDER BY id", row_limit=1).rows == [[1, 20]]

    forbidden = DataSource(
        source_id="postgresql:private:payroll",
        name="private.payroll",
        source_type="postgresql",
        schema_name="private",
        table_name="payroll",
        status="available",
    )
    service.catalog.upsert_source(forbidden)
    with pytest.raises(PostgresSourceError) as caught:
        service.preview(forbidden.source_id)
    assert caught.value.code == "SOURCE_FORBIDDEN"


def test_bad_password_and_timeout_do_not_leak_details_or_poison_next_query(postgres_service):
    service, _admin_dsn = postgres_service
    source = service.register_postgresql_sources()[0]
    bad_password = PostgreSQLAdapter(
        PostgresSettings(
            dsn=os.environ["POSTGRES_TEST_DSN"].replace("evia_test_only", "incorrect"),
            allowed_tables=frozenset({("public", "orders")}),
            connect_timeout_seconds=1,
            statement_timeout_ms=10_000,
        )
    )
    assert bad_password.connection_status() is False

    timeout_adapter = PostgreSQLAdapter(
        PostgresSettings(
            dsn=os.environ["POSTGRES_TEST_DSN"],
            allowed_tables=frozenset({("public", "orders")}),
            connect_timeout_seconds=5,
            statement_timeout_ms=1,
        )
    )
    with pytest.raises(Exception) as caught:
        timeout_adapter.query(
            source,
            "SELECT COUNT(*) FROM source a CROSS JOIN source b CROSS JOIN source c",
        )
    assert "postgresql://" not in str(caught.value)
    assert service.query(source.source_id, "SELECT COUNT(*) AS count FROM source").rows == [[500]]
