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
    ChartDefinition,
    DashboardFilter,
    FieldRef,
    KPICard,
    LineCard,
)
from app.models import SourceSchema
from app.schema_catalog import SchemaCatalog


NUMERIC_TYPES = {
    "int", "integer", "bigint", "smallint", "tinyint",
    "float", "double", "real", "decimal", "numeric",
    "number", "long", "unsigned",
}

ORDERABLE_TYPES = NUMERIC_TYPES | {
    "string", "varchar", "char", "text",
    "date", "datetime", "timestamp", "time",
    "bool", "boolean",
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
    """Проверяет определения чартов и строит планы запросов."""

    def __init__(self, catalog: SchemaCatalog):
        self.catalog = catalog

    def _schema(self, source_id: str) -> SourceSchema:
        """Возвращает зарегистрированную схему источника."""

        schema = self.catalog.get_schema(source_id)

        if schema is None:
            raise UnknownSourceError(
                f"Schema is not registered for source '{source_id}'"
            )

        return schema

    def resolve_field(self, ref: FieldRef) -> ResolvedField:
        """Проверяет существование источника и поля."""

        source = self.catalog.get_source(ref.source_id)
        if source is None:
            raise UnknownSourceError(
                f"Source '{ref.source_id}' is not registered"
            )

        schema = self._schema(ref.source_id)

        matches = [
            field
            for obj in schema.objects
            for field in obj.fields
            if field.name == ref.field
        ]

        if not matches:
            raise UnknownFieldError(
                f"Field '{ref.field}' does not exist "
                f"in source '{ref.source_id}'"
            )

        # FieldRef не указывает объект/таблицу. Если одно имя поля
        # встречается в нескольких объектах, однозначно выбрать его нельзя.
        if len(matches) > 1:
            raise UnsupportedJoinError(
                f"Field '{ref.field}' is ambiguous in source "
                f"'{ref.source_id}'; FieldRef must identify its table"
            )

        field = matches[0]

        return ResolvedField(
            source_id=ref.source_id,
            field_name=field.name,
            inferred_type=(field.inferred_type or "unknown").lower(),
            nullable=field.nullable,
        )

    @staticmethod
    def _is_type(
        field_type: str,
        candidates: set[str],
    ) -> bool:
        """Проверяет тип с учётом распространённых SQL-типов."""

        normalized = field_type.lower().strip()

        if normalized in candidates:
            return True

        # Поддерживает типы наподобие INTEGER UNSIGNED и DOUBLE PRECISION.
        return any(
            normalized.startswith(candidate + " ")
            for candidate in candidates
        )

    @classmethod
    def _validate_filter_value(
        cls,
        field: ResolvedField,
        value: object,
    ) -> None:
        """Проверяет тип значения фильтра относительно типа поля."""

        if value is None:
            return

        field_type = field.inferred_type

        if cls._is_type(field_type, NUMERIC_TYPES):
            values = value if isinstance(value, list) else [value]

            if any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                for item in values
            ):
                raise InvalidFilterError(
                    f"Filter value for numeric field "
                    f"'{field.field_name}' must be numeric"
                )

        elif cls._is_type(field_type, {"bool", "boolean"}):
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
        """Проверяет поля, источники и значения фильтров."""

        for item in filters:
            resolved = self.resolve_field(item.field)

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
                if not isinstance(item.value, (list, tuple)) or len(item.value) != 2:
                    raise InvalidFilterError(
                        "'between' requires exactly two values"
                    )

                low, high = item.value

                if type(low) is not type(high):
                    raise InvalidFilterError(
                        "Both 'between' values must have the same type"
                    )

            if item.operator not in {"is_null", "is_not_null"}:
                self._validate_filter_value(resolved, item.value)

    @classmethod
    def _validate_aggregate(
        cls,
        aggregate: Aggregate,
        field: ResolvedField,
    ) -> None:
        """Проверяет совместимость агрегатной функции с типом поля."""

        field_type = field.inferred_type

        if aggregate in {"sum", "avg"}:
            if not cls._is_type(field_type, NUMERIC_TYPES):
                raise UnsupportedTypeError(
                    f"Aggregate '{aggregate}' requires a numeric field; "
                    f"'{field.field_name}' has type '{field_type}'"
                )

        if aggregate in {"min", "max"}:
            if not cls._is_type(field_type, ORDERABLE_TYPES):
                raise UnsupportedTypeError(
                    f"Aggregate '{aggregate}' is not supported for "
                    f"field type '{field_type}'"
                )

    @staticmethod
    def _get_card_fields(
        definition: ChartDefinition,
    ) -> tuple[list[FieldRef], Aggregate, ResolvedField | None]:
        """Возвращает поля и агрегат, необходимые для конкретного чарта."""

        if isinstance(definition, KPICard):
            return [definition.field], definition.aggregate, None

        if isinstance(definition, LineCard):
            refs = [definition.x.field, definition.y.field]

            if definition.series is not None:
                refs.append(definition.series)

            return refs, definition.y.aggregate, None

        raise UnsupportedTypeError(
            f"Unsupported chart type: {getattr(definition, 'type', type(definition).__name__)}"
        )

    def plan(
        self,
        definition: ChartDefinition,
        filters: list[DashboardFilter] | None = None,
    ) -> QueryPlan:
        """Валидирует чарт и формирует план выполнения запроса."""

        filters = filters or []

        if isinstance(definition, KPICard):
            refs = [definition.field]
            aggregate = definition.aggregate

        elif isinstance(definition, LineCard):
            refs = [definition.x.field, definition.y.field]

            if definition.series is not None:
                refs.append(definition.series)

            aggregate = definition.y.aggregate

        else:
            raise UnsupportedTypeError(
                f"Unsupported chart type: "
                f"{getattr(definition, 'type', type(definition).__name__)}"
            )

        resolved_fields = [self.resolve_field(ref) for ref in refs]
        source_ids = {field.source_id for field in resolved_fields}

        if len(source_ids) != 1:
            raise UnsupportedJoinError(
                "All fields in a card must belong to the same source"
            )

        source_id = next(iter(source_ids))
        source = self.catalog.get_source(source_id)

        if source is None:
            raise UnknownSourceError(
                f"Source '{source_id}' is not registered"
            )

        self.validate_filters(filters, source_id)

        if isinstance(definition, KPICard):
            self._validate_aggregate(aggregate, resolved_fields[0])

        elif isinstance(definition, LineCard):
            y_field = resolved_fields[1]
            self._validate_aggregate(aggregate, y_field)

            if aggregate != "count":
                if not self._is_type(
                    y_field.inferred_type,
                    NUMERIC_TYPES,
                ):
                    raise UnsupportedTypeError(
                        f"Line chart requires a numeric Y field; "
                        f"'{y_field.field_name}' has type "
                        f"'{y_field.inferred_type}'"
                    )

        return QueryPlan(
            source_id=source_id,
            table_name=(
                "source_typed"
                if source.source_type == "csv" and source.import_report
                else "source"
            ),
            fields={
                f"{field.source_id}.{field.field_name}": field
                for field in resolved_fields
            },
            filters=filters,
        )
