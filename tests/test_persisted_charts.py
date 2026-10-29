from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.registration import build_tool_registry


def test_scatter_preserves_declared_axis_units_in_saved_result(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"revenue;share\n10;0.25\n20;0.5\n")
    try:
        registry = build_tool_registry(catalog, sources)
        chart = registry.execute("build_chart", {
            "definition": {
                "type": "scatter", "title": "Revenue and share",
                "x": {"source_id": source.source_id, "field": "revenue", "label": "Выручка",
                      "format": {"type": "currency", "currency": "RUB", "decimals": 2}},
                "y": {"source_id": source.source_id, "field": "share", "label": "Доля",
                      "format": {"type": "percent", "decimals": 1}},
            },
        })

        assert chart.ok and chart.data["success"], chart.error or chart.data
        result = chart.data["result"]
        assert result["x"]["label"] == "Выручка"
        assert result["x"]["format"]["currency"] == "RUB"
        assert result["y"]["label"] == "Доля"
        assert result["y"]["format"]["type"] == "percent"
        assert len(result["points"]) == 2
    finally:
        catalog.close()


def test_saved_chart_rebuild_honors_its_persisted_filters(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv("sales.csv", b"month;revenue\nJan;10\nFeb;20\n")
    try:
        registry = build_tool_registry(catalog, sources)
        chart = registry.execute("build_chart", {
            "definition": {
                "type": "kpi",
                "title": "January revenue",
                "field": {"source_id": source.source_id, "field": "revenue"},
                "aggregate": "sum",
                "filters": [{
                    "field": {"source_id": source.source_id, "field": "month"},
                    "operator": "eq",
                    "value": "Jan",
                }],
            },
            "filters": [],
        })
        assert chart.ok and chart.data["success"], chart.error or chart.data
        assert float(chart.data["result"]["value"]) == 10

        from app.charts.executor import ChartExecutor
        from app.charts.repositories import ChartRepository
        reopened = ChartExecutor.build_executor(sources, catalog, ChartRepository(catalog.session_factory))
        assert float(reopened.execute(chart.data["chart_id"])["value"]) == 10
    finally:
        catalog.close()


def test_chart_and_dashboard_are_persisted_from_tool_results(tmp_path):
    """A saved chart can be attached to a saved dashboard in one registry."""
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    source = sources.register_csv(
        "sales.csv",
        b"month;revenue\n2026-01;120,5\n2026-02;180.5\n",
    )
    try:
        registry = build_tool_registry(catalog, sources)
        chart = registry.execute("build_chart", {
            "definition": {
                "type": "kpi",
                "title": "Выручка",
                "field": {"source_id": source.source_id, "field": "revenue"},
                "aggregate": "sum",
            },
            "filters": [],
        })

        assert chart.ok, chart.error
        assert chart.data["success"], chart.data

        dashboard = registry.execute("compose_dashboard", {
            "title": "Продажи",
            "summary": None,
            "chart_ids": [chart.data["chart_id"]],
        })

        assert dashboard.ok, dashboard.error
        assert dashboard.data["success"], dashboard.data
        assert dashboard.data["dashboard"]["charts"] == [
            {"chart_id": chart.data["chart_id"], "position": 0},
        ]

        reopened = registry.execute("get_dashboard", {
            "dashboard_id": dashboard.data["dashboard"]["id"],
        })

        assert reopened.ok, reopened.error
        assert reopened.data["success"] is True
        assert reopened.data["charts"][0]["chart"]["definition"] == chart.data["definition"]
        current_name = registry.execute("get_dashboard_info", {
            "dashboard_id": dashboard.data["dashboard"]["id"],
        })
        assert current_name.ok and current_name.data == reopened.data
    finally:
        catalog.close()
