from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools.base import ToolDefinition, ToolRegistry


def register_data_tools(
    registry: ToolRegistry,
    catalog: SchemaCatalog,
    sources: SourceService,
) -> None:
    # не нужно ему выполнять sql запросы самому
    # registry.register(
    #     ToolDefinition(
    #         name="query_data",
    #         description=(
    #             "Run one read-only analytical SELECT against a selected "
    #             "source. Refer to the selected source as the table source."
    #         ),
    #         parameters={
    #             "source_id": {"type": "string"},
    #             "sql": {"type": "string", "minLength": 1},
    #             "row_limit": {
    #                 "type": "integer",
    #                 "minimum": 1,
    #                 "maximum": 10000,
    #             },
    #         },
    #         required=["source_id", "sql"],
    #         handler=lambda source_id, sql, row_limit=None: sources.query(
    #             source_id, sql, row_limit=row_limit
    #         ),
    #     )
    # )

    registry.register(
        ToolDefinition(
            name="list_sources",
            description="List all registered data sources.",
            parameters={},
            handler=lambda: [
                source.model_dump(mode="json")
                for source in catalog.list_sources()
            ],
        )
    )

    registry.register(
        ToolDefinition(
            name="get_source_schema",
            description="Get the schema of a registered source.",
            parameters={"source_id": {"type": "string"}},
            required=["source_id"],
            handler=lambda source_id: sources.get_schema(source_id),
        )
    )

    registry.register(
        ToolDefinition(
            name="preview_data",
            description="Preview a small number of rows from a source.",
            parameters={
                "source_id": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            required=["source_id"],
            handler=lambda source_id, limit=10: sources.preview(
                source_id, limit
            ),
        )
    )

    registry.register(
        ToolDefinition(
            name="profile_data",
            description="Get basic sample-based statistics for a source.",
            parameters={"source_id": {"type": "string"}},
            required=["source_id"],
            handler=lambda source_id: sources.profile(source_id),
        )
    )
