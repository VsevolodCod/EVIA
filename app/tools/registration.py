from app.charts import ChartExecutor
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.charts import ChartRepository

from app.tools.base import ToolRegistry

from app.tools.dashboard import register_dashboard_tools, DashboardEngine
from app.tools.data import register_data_tools
from app.tools.charts import register_chart_tools
from app.tools.hypothesis import register_hypothesis_tools


def build_tool_registry(
    catalog: SchemaCatalog,
    sources: SourceService,
    dashboard_engine: DashboardEngine,
    executor: ChartExecutor,
    charts: ChartRepository
) -> ToolRegistry:
    registry = ToolRegistry()

    register_data_tools(registry, catalog, sources)

    register_hypothesis_tools(registry, sources)

    register_dashboard_tools(registry, dashboard_engine)

    register_chart_tools(registry, charts, executor)

    return registry
