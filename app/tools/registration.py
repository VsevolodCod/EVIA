from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.base import ToolRegistry
from app.tools.charts import register_chart_tools
from app.tools.data import register_data_tools


def build_tool_registry(
    catalog: SchemaCatalog,
    sources: SourceService,
) -> ToolRegistry:
    registry = ToolRegistry()

    register_data_tools(registry, catalog, sources)
    register_chart_tools(registry, catalog, sources)

    return registry
