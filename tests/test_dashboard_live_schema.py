"""A saved live chart must not silently look current after DDL."""

from types import SimpleNamespace

import importlib
import pytest
from httpx import ASGITransport, AsyncClient

from app.charts.snapshots import source_versions
from app.charts.models import ChartReference, DashboardModel
from app.charts.repositories import ChartRepository, DashboardRepository
from app.models import DataSource, SchemaField, SchemaObject, SourceSchema
from app.schema_catalog import SchemaCatalog


def test_postgresql_schema_fingerprint_changes_only_with_structure():
    source = DataSource(
        source_id="postgresql:public:orders", name="public.orders",
        source_type="postgresql", schema_name="public", table_name="orders",
    )
    fields = [SchemaField(name="id", inferred_type="integer", nullable=False)]
    schema = SourceSchema(source_id=source.source_id, objects=[SchemaObject(
        object_id="orders", name="public.orders", object_type="postgresql_table", fields=fields,
    )])
    adapter = SimpleNamespace(introspect_schema=lambda _: schema)
    sources = SimpleNamespace(postgres_adapter=adapter)
    catalog = SimpleNamespace(get_source=lambda _: source)
    definition = {"field": {"source_id": source.source_id, "field": "id"}}

    original = source_versions(catalog, definition, sources=sources)
    assert original[source.source_id]["live_schema_fingerprint"]
    schema.discovered_at = schema.discovered_at.replace(year=2020)
    assert source_versions(catalog, definition, sources=sources) == original
    schema.objects[0].fields.append(SchemaField(name="total", inferred_type="numeric", nullable=True))
    assert source_versions(catalog, definition, sources=sources) != original


def test_unavailable_live_schema_is_marked_without_exposing_driver_error():
    source = DataSource(
        source_id="postgresql:public:orders", name="public.orders",
        source_type="postgresql", schema_name="public", table_name="orders",
    )
    def unavailable(_):
        raise RuntimeError("postgresql://reader:secret@private-db")

    catalog = SimpleNamespace(get_source=lambda _: source)
    sources = SimpleNamespace(postgres_adapter=SimpleNamespace(introspect_schema=unavailable))
    version = source_versions(catalog, {"source_id": source.source_id}, sources=sources)[source.source_id]
    assert version["schema_status"] == "unavailable"
    assert "secret" not in repr(version)


@pytest.mark.asyncio
async def test_saved_postgresql_dashboard_survives_schema_change_and_disconnect(tmp_path, monkeypatch):
    module = importlib.import_module("app.main")
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    source = DataSource(
        source_id="postgresql:public:orders", name="public.orders",
        source_type="postgresql", schema_name="public", table_name="orders",
    )
    catalog.upsert_source(source)
    fields = [SchemaField(name="amount", inferred_type="numeric", nullable=False)]
    schema = SourceSchema(source_id=source.source_id, objects=[SchemaObject(
        object_id="orders", name="public.orders", object_type="postgresql_table", fields=fields,
    )])
    adapter = SimpleNamespace(introspect_schema=lambda _: schema)
    sources = SimpleNamespace(catalog=catalog, postgres_adapter=adapter)
    charts = ChartRepository(catalog.session_factory)
    dashboards = DashboardRepository(catalog.session_factory)
    chart = charts.create_from_definition({
        "type": "kpi", "title": "Sales", "field": {"source_id": source.source_id, "field": "amount"},
        "aggregate": "sum",
    })
    dashboard = dashboards.create(DashboardModel(
        id="live-dashboard", title="Live sales", charts=[ChartReference(chart_id=chart.chart_id, position=0)],
    ))
    executor = SimpleNamespace(sources=sources, execute=lambda **_: {"value": 10})
    monkeypatch.setattr(module, "chart_repository", charts)
    monkeypatch.setattr(module, "dashboard_repository", dashboards)
    monkeypatch.setattr(module, "chart_executor", executor)
    try:
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
            url = f"/dashboards/{dashboard.id}/build"
            initial = (await client.get(url)).json()
            assert initial["charts"][0]["result"]["value"] == 10
            schema.objects[0].fields.append(SchemaField(name="discount", inferred_type="numeric", nullable=True))
            changed = (await client.get(url)).json()
            assert changed["stale"] is True
            assert changed["charts"][0]["result"] == initial["charts"][0]["result"]
            def disconnected(_):
                raise RuntimeError("postgresql://reader:secret@private-db")
            adapter.introspect_schema = disconnected
            unavailable = (await client.get(url)).json()
            assert unavailable["stale"] is True
            assert "secret" not in str(unavailable)
            failed = await client.post(f"/dashboards/{dashboard.id}/refresh")
            assert failed.status_code == 409
            assert "secret" not in failed.text
            assert (await client.get(url)).json()["charts"][0]["result"] == initial["charts"][0]["result"]
    finally:
        catalog.close()
