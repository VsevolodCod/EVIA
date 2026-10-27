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
    session_factory: sessionmaker[Session] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()

    register_data_tools(registry, catalog, sources)

    # SchemaCatalog owns the synchronous catalog session in the current
    # application. Accepting an explicit factory keeps the registry usable by
    # integrations, while the default keeps all existing callers compatible.
    sessions = session_factory or catalog.session_factory
    charts = ChartRepository(sessions)
    dashboards = DashboardRepository(sessions)
    dashboard_engine = DashboardEngine(
        charts=charts,
        dashboards=dashboards,
    )
    register_dashboard_tools(registry, dashboard_engine)

    executor = ChartExecutor.build_executor(sources, catalog, charts)
    register_chart_tools(registry, charts, executor)

    return registry
