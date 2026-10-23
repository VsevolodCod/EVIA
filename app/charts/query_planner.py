from __future__ import annotations

from dataclasses import dataclass

from app.charts.errors import (
    InvalidFilterError,
    UnknownFieldError,
    UnknownSourceError,
    UnsupportedJoinError,
    UnsupportedTypeError,
)
from app.charts.models import (
    Aggregate,
    DashboardCard,
    DashboardFilter,
    FieldRef,
)
from app.models import SchemaField, SourceSchema
from app.schema_catalog import SchemaCatalog


NUMERIC_TYPES = {
    "int", "integer", "bigint", "smallint", "tinyint",
    "float", "double", "real", "decimal", "numeric",
    "number", "long", "unsigned",
}

ORDERABLE_TYPES = NUMERIC_TYPES | {
    "string", "varchar", "char", "text",
    "date", "datetime", "timestamp", "time", "bool", "boolean",
}


@dataclass(frozen=True)
class ResolvedField:
    source_id: str
    field_name: str
    inferred_type: str
    nullable: bool | None


@dataclass(frozen=True)
class QueryPlan:
    source_id: str
    table_name: str
    fields: dict[str, ResolvedField]
    filters: list[DashboardFilter]


class QueryPlanner:
    def __init__(self, catalog: SchemaCatalog):
        self.catalog = catalog

    def _schema(self, source_id: str) -> SourceSchema:
        schema = self.catalog.get_schema(source_id)

        if schema is None:
            raise UnknownSourceError(
                f"Schema is not registered for source '{source_id}'"
            )

        return schema

    def resolve_field(self, ref: FieldRef) -> ResolvedField:
        source = self.catalog.get_source(ref.source_id)
        if source is None:
            raise UnknownSourceError(
                f"Source '{ref.source_id}' is not registered"
            )

        schema = self._schema(ref.source_id)

        for obj in schema.objects:
            for field in obj.fields:
                if field.name == ref.field:
                    return ResolvedField(
                        source_id=ref.source_id,
                        field_name=field.name,
                        inferred_type=(field.inferred_type or "unknown").lower(),
                        nullable=field.nullable,
                    )

        raise UnknownFieldError(
            f"Field '{ref.field}' does not exist in source '{ref.source_id}'"
        )

    @staticmethod
    def _validate_filter_value(
        field: ResolvedField,
        value: object,
    ) -> None:
        if value is None:
            return

        field_type = field.inferred_type.lower()

        if any(token in field_type for token in NUMERIC_TYPES):
            values = value if isinstance(value, list) else [value]

            for item in values:
                if isinstance(item, bool) or not isinstance(
                    item, (int, float)
                ):
                    raise InvalidFilterError(
                        f"Filter value for numeric field "
                        f"'{field.field_name}' must be numeric"
                    )

        elif "bool" in field_type:
            values = value if isinstance(value, list) else [value]

            if any(not isinstance(item, bool) for item in values):
                raise InvalidFilterError(
                    f"Filter value for boolean field "
                    f"'{field.field_name}' must be boolean"
                )

    def validate_filters(
        self,
        filters: list[DashboardFilter],
        source_id: str,
    ) -> None:
        for item in filters:
            resolved = self.resolve_field(item.field)

            # На текущем этапе запрос одной карточки обращается
            # только к одному источнику. Не игнорируем фильтр
            # из другого источника и не создаём JOIN автоматически.
            if resolved.source_id != source_id:
                raise UnsupportedJoinError(
                    "A filter refers to another source; cross-source "
                    "filters are not supported"
                )

            field_type = resolved.inferred_type

            if item.operator in {"gt", "gte", "lt", "lte", "between"}:
                if field_type == "unknown":
                    raise InvalidFilterError(
                        f"Cannot validate range filter for "
                        f"unknown field type '{resolved.field_name}'"
                    )

            if item.operator == "between":
                low, high = item.value
                if type(low) is not type(high):
                    raise InvalidFilterError(
                        "Both 'between' values must have the same type"
                    )
            if item.operator in {"in", "not_in", "between"}:
                self._validate_filter_value(resolved, item.value)
            elif item.operator not in {"is_null", "is_not_null"}:
                self._validate_filter_value(resolved, item.value)

    @staticmethod
    def _validate_aggregate(
        aggregate: Aggregate,
        field: ResolvedField,
    ) -> None:
        field_type = field.inferred_type.lower()

        if aggregate in {"sum", "avg"}:
            if not any(token in field_type for token in NUMERIC_TYPES):
                raise UnsupportedTypeError(
                    f"Aggregate '{aggregate}' requires a numeric field; "
                    f"'{field.field_name}' has type '{field_type}'"
                )

        if aggregate in {"min", "max"}:
            if not any(token in field_type for token in ORDERABLE_TYPES):
                raise UnsupportedTypeError(
                    f"Aggregate '{aggregate}' is not supported for "
                    f"field type '{field_type}'"
                )

    def plan(self, card: DashboardCard, filters: list[DashboardFilter]) -> QueryPlan:
        if card.type == "kpi":
            refs = [card.field]
            aggregate = card.aggregate
        elif card.type == "line":
            refs = [card.x, card.y]
            if card.series is not None:
                refs.append(card.series)
            aggregate = card.y.aggregate
        else:
            raise UnsupportedTypeError(
                f"Unsupported chart type: {card.type}"
            )

        resolved_fields = [self.resolve_field(ref) for ref in refs]
        source_ids = {field.source_id for field in resolved_fields}

        if len(source_ids) != 1:
            raise UnsupportedJoinError(
                "All fields in a card must belong to the same source"
            )

        source_id = next(iter(source_ids))
        source = self.catalog.get_source(source_id)

        # Общие фильтры и фильтры карточки работают вместе.
        self.validate_filters(filters, source_id)

        y_or_kpi = resolved_fields[0] if card.type == "kpi" else resolved_fields[1]
        self._validate_aggregate(aggregate, y_or_kpi)

        if card.type == "line" and card.y.aggregate in {"sum", "avg"}:
            self._validate_aggregate(card.y.aggregate, resolved_fields[1])

        if card.type == "line" and card.y.aggregate != "count":
            y_type = resolved_fields[1].inferred_type
            if not any(token in y_type for token in NUMERIC_TYPES):
                raise UnsupportedTypeError(
                    f"Line chart requires a numeric Y field; '{resolved_fields[1].field_name}' has type '{y_type}'"
                )

        return QueryPlan(
            source_id=source_id,
            table_name="source_typed" if source.source_type == "csv" and source.import_report else "source",
            fields={
                f"{field.source_id}.{field.field_name}": field
                for field in resolved_fields
            },
            filters=filters,
        )
