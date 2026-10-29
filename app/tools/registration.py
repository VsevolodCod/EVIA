from sqlalchemy.orm import sessionmaker, Session

from app.charts import ChartExecutor, QueryPlanner
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.base import ToolRegistry

from app.tools.dashboard import register_dashboard_tools, DashboardEngine
from app.tools.data import register_data_tools
from app.tools.charts import register_chart_tools

from app.charts import ChartRepository, DashboardRepository


def build_tool_registry(
    catalog: SchemaCatalog,
    sources: SourceService,
    dashboard_engine: DashboardEngine | None = None,
    executor: ChartExecutor | None = None,
    charts: ChartRepository | None = None,
) -> ToolRegistry:
    # Keep the public two-argument factory usable by integrations and scripts;
    # production can still inject its shared repositories and executors.
    if charts is None:
        charts = ChartRepository(catalog.session_factory)
    if executor is None:
        executor = ChartExecutor.build_executor(sources, catalog, charts)
    if dashboard_engine is None:
        dashboard_engine = DashboardEngine(charts, DashboardRepository(catalog.session_factory))
    registry = ToolRegistry()

    register_data_tools(registry, catalog, sources)

    register_dashboard_tools(registry, dashboard_engine)

    register_chart_tools(registry, charts, executor)

    return registry
