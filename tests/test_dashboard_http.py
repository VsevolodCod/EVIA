"""Read and rebuild persisted charts through the public HTTP contract."""

import importlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.contracts.v1 import AgentResponse
from app.charts.engine import DashboardEngine
from app.charts.executor import ChartExecutor
from app.charts.models import ChartModel, ChartReference, DashboardModel
from app.charts.repositories import ChartRepository, DashboardRepository
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.registration import build_tool_registry


@pytest.mark.asyncio
async def test_saved_dashboard_can_be_listed_reopened_and_built(tmp_path, monkeypatch):
    module = importlib.import_module("app.main")
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"month;revenue\nJan;10\nFeb;20\n")
    charts = ChartRepository(catalog.session_factory)
    dashboards = DashboardRepository(catalog.session_factory)
    registry = build_tool_registry(catalog, sources)

    chart = registry.execute("build_chart", {
        "definition": {
            "type": "kpi",
            "title": "Revenue",
            "field": {"source_id": source.source_id, "field": "revenue"},
            "aggregate": "sum",
        },
        "filters": [],
    })
    assert chart.ok and chart.data["success"], chart.error or chart.data
    chart_id = chart.data["chart_id"]
    dashboard = registry.execute("compose_dashboard", {
        "title": "Sales",
        "chart_ids": [chart_id],
    })
    assert dashboard.ok and dashboard.data["success"], dashboard.error or dashboard.data
    dashboard_id = dashboard.data["dashboard"]["id"]
    second_dashboard = registry.execute("compose_dashboard", {
        "title": "Sales copy", "chart_ids": [chart_id],
    })
    assert second_dashboard.ok and second_dashboard.data["success"]
    second_dashboard_id = second_dashboard.data["dashboard"]["id"]

    monkeypatch.setattr(module, "chart_repository", charts)
    monkeypatch.setattr(module, "dashboard_repository", dashboards)
    monkeypatch.setattr(module, "dashboard_engine", DashboardEngine(charts, dashboards))
    monkeypatch.setattr(module, "chart_executor", ChartExecutor.build_executor(sources, catalog, charts))
    try:
        dashboards.set_origin_chat(dashboard_id, "chat-1")
        dashboards.set_origin_chat(dashboard_id, "chat-2")
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
            ids = await client.get("/dashboards/ids")
            assert ids.status_code == 200
            assert dashboard_id in ids.json()["dashboard_ids"]
            first_page = await client.get("/dashboards/ids?limit=1&offset=0")
            second_page = await client.get("/dashboards/ids?limit=1&offset=1")
            assert {first_page.json()["dashboard_ids"][0], second_page.json()["dashboard_ids"][0]} == {dashboard_id, second_dashboard_id}
            assert (await client.get("/dashboards/ids?limit=1&offset=2")).json()["dashboard_ids"] == []

            definition = await client.get(f"/dashboards/{dashboard_id}")
            assert definition.status_code == 200
            assert definition.json()["dashboard"]["charts"] == [{"chart_id": chart_id, "position": 0}]
            assert definition.json()["origin_chat_id"] == "chat-1"

            chart_definition = await client.get(f"/charts/{chart_id}")
            assert chart_definition.status_code == 200
            assert chart_definition.json()["id"] == chart_id
            assert chart_definition.json()["chart_id"] == chart_id

            chart_result = await client.get(f"/charts/{chart_id}/build")
            assert chart_result.status_code == 200
            assert chart_result.json()["success"] is True
            assert chart_result.json()["chart_id"] == chart_id

            dashboard_result = await client.get(f"/dashboards/{dashboard_id}/build")
            assert dashboard_result.status_code == 200
            assert dashboard_result.json()["success"] is True
            assert dashboard_result.json()["charts"][0]["chart_id"] == chart_id

            assert (await client.get("/dashboards/missing")).status_code == 404
            assert (await client.get("/charts/missing")).status_code == 404
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_dashboard_order_and_delete_are_persisted_and_validated(tmp_path, monkeypatch):
    module = importlib.import_module("app.main")
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"month,revenue\nJan,10\nFeb,20\n")
    registry = build_tool_registry(catalog, sources)
    chart_ids = []
    for title, aggregate in (("Revenue", "sum"), ("Rows", "count")):
        built = registry.execute("build_chart", {"definition": {
            "type": "kpi", "title": title,
            "field": {"source_id": source.source_id, "field": "revenue"},
            "aggregate": aggregate,
        }, "filters": []})
        assert built.ok and built.data["success"]
        chart_ids.append(built.data["chart_id"])
    created = registry.execute("compose_dashboard", {"title": "Sales", "chart_ids": chart_ids})
    assert created.ok and created.data["success"]
    dashboard_id = created.data["dashboard"]["id"]
    repository = DashboardRepository(catalog.session_factory)
    monkeypatch.setattr(module, "dashboard_repository", repository)
    try:
        async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
            url = f"/dashboards/{dashboard_id}/order"
            assert (await client.put(url, json={"chart_ids": chart_ids[:1], "expected_version": 1})).status_code == 400
            saved = await client.put(url, json={"chart_ids": chart_ids[::-1], "expected_version": 1})
            assert saved.status_code == 200
            assert saved.json()["dashboard"]["version"] == 2
            assert [ref["chart_id"] for ref in saved.json()["dashboard"]["charts"]] == chart_ids[::-1]
            assert (await client.put(url, json={"chart_ids": chart_ids, "expected_version": 1})).status_code == 409
            assert [ref.chart_id for ref in repository.get_by_id(dashboard_id).charts] == chart_ids[::-1]
            deleted = await client.delete(f"/dashboards/{dashboard_id}")
            assert deleted.status_code == 200 and deleted.json() == {"success": True}
            assert repository.get_by_id(dashboard_id) is None
            assert (await client.delete(f"/dashboards/{dashboard_id}")).status_code == 404
    finally:
        catalog.close()


@pytest.mark.asyncio
async def test_dashboard_context_is_forwarded_only_when_requested(monkeypatch):
    module = importlib.import_module("app.main")

    class Dashboards:
        def get_by_id(self, dashboard_id):
            return DashboardModel(id=dashboard_id, title="Saved")

    class RecordingAgent:
        def __init__(self):
            self.calls = []

        async def ask(self, **kwargs):
            self.calls.append(kwargs)
            return AgentResponse(request_id="test-request", status="answered", answer="ok", steps=1)

    agent = RecordingAgent()
    monkeypatch.setattr(module, "agent", agent)
    monkeypatch.setattr(module, "dashboard_repository", Dashboards())
    async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
        plain = await client.post("/agent/ask", json={"question": "Что есть?"})
        attached = await client.post("/agent/ask", json={
            "question": "Покажи график",
            "dashboard_id": "dashboard-123",
        })

    assert plain.status_code == 200
    assert attached.status_code == 200
    assert "dashboard_id" not in agent.calls[0]
    assert agent.calls[1]["dashboard_id"] == "dashboard-123"


@pytest.mark.asyncio
async def test_unknown_attached_dashboard_is_rejected_before_model_call(monkeypatch):
    module = importlib.import_module("app.main")

    class Dashboards:
        def get_by_id(self, _dashboard_id): return None

    class Agent:
        async def ask(self, **_kwargs):
            raise AssertionError("Missing dashboard must not reach the model")

    monkeypatch.setattr(module, "dashboard_repository", Dashboards())
    monkeypatch.setattr(module, "agent", Agent())
    async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
        response = await client.post("/agent/ask", json={
            "question": "Покажи его", "dashboard_id": "does-not-exist",
        })
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_build_hides_internal_chart_errors(monkeypatch):
    module = importlib.import_module("app.main")
    dashboard = DashboardModel(
        id="dashboard-1", title="Sales", charts=[ChartReference(chart_id="chart-1", position=0)]
    )
    chart = ChartModel(id="chart-1", definition={
        "type": "kpi", "title": "Revenue", "field": {"source_id": "sales", "field": "revenue"},
        "aggregate": "sum",
    })

    class Dashboards:
        def get_by_id(self, _id): return dashboard

    class Charts:
        def get_by_id(self, _id): return chart

    class Executor:
        def execute(self, **_kwargs):
            raise RuntimeError("PRIVATE_DB_URI=/data/internal/sales.csv")

    monkeypatch.setattr(module, "dashboard_repository", Dashboards())
    monkeypatch.setattr(module, "chart_repository", Charts())
    monkeypatch.setattr(module, "chart_executor", Executor())

    async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
        response = await client.get("/dashboards/dashboard-1/build")

    assert response.status_code == 200
    assert response.json()["success"] is False
    error = response.json()["charts"][0]["error"]
    assert error["code"] == "chart_execution_failed"
    assert "PRIVATE_DB_URI" not in error["message"]
    assert "/data/internal" not in error["message"]


@pytest.mark.asyncio
async def test_chart_build_hides_internal_errors(monkeypatch):
    module = importlib.import_module("app.main")
    chart = ChartModel(id="chart-1", definition={
        "type": "kpi", "title": "Revenue", "field": {"source_id": "sales", "field": "revenue"},
        "aggregate": "sum",
    })

    class Charts:
        def get_by_id(self, _id): return chart

    class Executor:
        def execute(self, **_kwargs):
            raise ValueError("PRIVATE_DB_URI=/data/internal/sales.csv")

    monkeypatch.setattr(module, "chart_repository", Charts())
    monkeypatch.setattr(module, "chart_executor", Executor())
    async with AsyncClient(transport=ASGITransport(app=module.app), base_url="http://test") as client:
        response = await client.get("/charts/chart-1/build")

    assert response.status_code == 400
    assert "PRIVATE_DB_URI" not in response.text
    assert "/data/internal" not in response.text
