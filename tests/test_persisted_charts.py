from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.registration import build_tool_registry


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
    finally:
        catalog.close()
