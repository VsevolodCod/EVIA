import pytest

from app.config import Settings
from app.models import DataSource


def test_postgresql_settings_are_optional_and_parse_strict_allowlist(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://reader:secret@db.example/analytics")
    monkeypatch.setenv("POSTGRES_ALLOWED_TABLES", "public.orders, analytics.events")

    settings = Settings()

    assert settings.postgres.enabled is True
    assert settings.postgres.allowed_tables == frozenset({("public", "orders"), ("analytics", "events")})
    assert "secret" not in settings.public_settings()


def test_remote_source_serializes_only_object_identity():
    source = DataSource(
        source_id="postgresql:public:orders",
        name="public.orders",
        source_type="postgresql",
        schema_name="public",
        table_name="orders",
    )

    assert source.schema_name == "public"
    assert source.table_name == "orders"
    assert "postgresql://" not in source.model_dump_json()


def test_discovery_returns_only_allowlisted_tables_and_uses_readonly_transaction():
    from app.config import PostgresSettings
    from app.data_sources.postgresql_adapter import PostgreSQLAdapter

    class Cursor:
        def __init__(self):
            self.executed = []

        def execute(self, query, params=None):
            self.executed.append((str(query), params))

        def fetchall(self):
            return [
                ("public", "orders", "id", "integer", "NO"),
                ("public", "orders", "amount", "numeric", "YES"),
                ("private", "payroll", "salary", "numeric", "NO"),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.executed = []
            self.read_only = False

        def execute(self, query, params=None):
            self.executed.append((str(query), params))

        def cursor(self):
            return self.cursor_instance

        def close(self):
            pass

    connection = Connection()
    adapter = PostgreSQLAdapter(
        PostgresSettings(
            dsn="postgresql://reader:secret@db.example/analytics",
            allowed_tables=frozenset({("public", "orders")}),
            connect_timeout_seconds=5,
            statement_timeout_ms=10_000,
        ),
        connect=lambda *_args, **_kwargs: connection,
    )

    discovered = adapter.discover()

    assert [(source.schema_name, source.table_name) for source in discovered] == [("public", "orders")]
    assert connection.read_only is True
    assert not any("BEGIN READ ONLY" in query for query, _params in connection.executed)
    assert "secret" not in repr(discovered)


def test_forbidden_object_never_reaches_the_driver():
    import pytest

    from app.config import PostgresSettings
    from app.data_sources.postgresql_adapter import PostgresSourceError, PostgreSQLAdapter

    called = False

    def connect(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("forbidden source must not connect")

    adapter = PostgreSQLAdapter(
        PostgresSettings(
            dsn="postgresql://reader:secret@db.example/analytics",
            allowed_tables=frozenset({("public", "orders")}),
            connect_timeout_seconds=5,
            statement_timeout_ms=10_000,
        ),
        connect=connect,
    )

    with pytest.raises(PostgresSourceError) as caught:
        adapter.preview("private", "payroll", limit=10)

    assert caught.value.code == "SOURCE_FORBIDDEN"
    assert called is False


def test_postgresql_executor_rejects_write_multistatement_and_external_functions_before_connection():
    import pytest

    from app.config import PostgresSettings
    from app.data_sources.postgresql_adapter import PostgreSQLAdapter
    from app.postgresql_sql import PostgresQueryError

    adapter = PostgreSQLAdapter(
        PostgresSettings(
            dsn="postgresql://reader:secret@db.example/analytics",
            allowed_tables=frozenset({("public", "orders")}),
            connect_timeout_seconds=5,
            statement_timeout_ms=10_000,
        ),
        connect=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsafe SQL must not connect")),
    )
    source = adapter._source("public", "orders")

    for statement in (
        "DELETE FROM source",
        "SELECT 1; DROP TABLE source",
        "SELECT pg_read_file('/etc/passwd') FROM source",
        "SELECT * FROM private.payroll",
    ):
        with pytest.raises(PostgresQueryError) as caught:
            adapter.query(source, statement)
        assert caught.value.code == "QUERY_REJECTED"
        assert "secret" not in str(caught.value)


def test_source_service_dispatches_live_postgresql_without_changing_csv(tmp_path):
    from app.models import SchemaObject, SourceSchema
    from app.schema_catalog import SchemaCatalog
    from app.source_service import SourceService

    remote = DataSource(
        source_id="postgresql:public:orders",
        name="public.orders",
        source_type="postgresql",
        schema_name="public",
        table_name="orders",
        status="available",
    )

    class RemoteAdapter:
        def discover(self):
            return [remote]

        def introspect_schema(self, source):
            return SourceSchema(
                source_id=source.source_id,
                objects=[SchemaObject(object_id=f"{source.source_id}:table", name="public.orders")],
            )

        def preview(self, source, _object_name=None, limit=10):
            assert source.source_id == remote.source_id
            return [{"id": 1, "amount": 10}][:limit]

        def profile(self, source, _object_name=None):
            assert source.source_id == remote.source_id
            return {"sample_size": 1, "sample_limit": 1, "columns": {}, "note": "bounded sample"}

    catalog = SchemaCatalog(tmp_path / "catalog.db")
    try:
        service = SourceService(tmp_path / "data", catalog, postgres_adapter=RemoteAdapter())
        assert service.register_postgresql_sources() == [remote]
        assert service.preview(remote.source_id) == [{"id": 1, "amount": 10}]
        assert service.profile(remote.source_id)["note"] == "bounded sample"
        assert service.register_csv("sales.csv", b"id\n001\n").source_type == "csv"
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_postgresql_status_endpoint_is_secret_free_when_unconfigured():
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/sources/postgresql/status")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "connected": False}
    assert "postgresql://" not in response.text


def test_query_tool_returns_only_postgresql_stable_error_code(tmp_path):
    from app.config import PostgresSettings
    from app.data_sources.postgresql_adapter import PostgreSQLAdapter
    from app.schema_catalog import SchemaCatalog
    from app.source_service import SourceService
    from app.tools import build_tool_registry

    source = PostgreSQLAdapter(
        PostgresSettings(
            dsn="postgresql://reader:secret@db.example/analytics",
            allowed_tables=frozenset({("public", "orders")}),
            connect_timeout_seconds=5,
            statement_timeout_ms=10_000,
        )
    )._source("public", "orders")
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    try:
        service = SourceService(tmp_path / "data", catalog, postgres_adapter=PostgreSQLAdapter(
            PostgresSettings(
                dsn="postgresql://reader:secret@db.example/analytics",
                allowed_tables=frozenset({("public", "orders")}),
                connect_timeout_seconds=5,
                statement_timeout_ms=10_000,
            )
        ))
        catalog.upsert_source(source)
        result = build_tool_registry(catalog, service).execute(
            "query_data", {"source_id": source.source_id, "sql": "DELETE FROM source"}
        )
        assert result.ok is False
        assert result.error == "QUERY_REJECTED"
    finally:
        catalog.close()
