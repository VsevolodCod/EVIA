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
