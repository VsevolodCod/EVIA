from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import BaseModel, Field, TypeAdapter, create_model

from app.charts.executor import ChartExecutor
from app.charts.models import (
    ChartDefinition,
    DashboardFilter,
)
from app.charts.repositories import ChartRepository
from app.tools.base import ToolDefinition, ToolRegistry


def _resolve_refs(value: Any, definitions: dict[str, Any]) -> Any:
    """Раскрывает локальные Pydantic $ref для схемы ToolRegistry."""

    if isinstance(value, list):
        return [_resolve_refs(item, definitions) for item in value]

    if not isinstance(value, dict):
        return value

    ref = value.get("$ref")
    if ref is not None:
        prefix = "#/$defs/"
        if not ref.startswith(prefix):
            raise ValueError(f"Unsupported schema reference: {ref}")

        name = ref[len(prefix):]
        if name not in definitions:
            raise ValueError(f"Unknown schema definition: {name}")

        resolved = _resolve_refs(definitions[name], definitions)

        siblings = {
            key: item for key, item in value.items() if key != "$ref"
        }
        if siblings:
            resolved = {
                **resolved,
                **_resolve_refs(siblings, definitions),
            }

        return resolved

    return {
        key: _resolve_refs(item, definitions)
        for key, item in value.items()
    }


def _build_parameters(model: type[BaseModel]) -> tuple[dict[str, Any], list[str]]:
    """Строит схему параметров инструмента из Pydantic-модели."""

    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    parameters = _resolve_refs(schema["properties"], definitions)
    required = schema.get("required", [])

    return parameters, required


def _get_chart_models() -> dict[str, type[BaseModel]]:
    """
    Возвращает доступные модели чартов.

    Ключ — значение discriminator-поля type, например 'kpi' или 'line'.
    Значение — соответствующая Pydantic-модель.
    """

    chart_type = get_args(ChartDefinition)[0]
    model_types = get_args(chart_type)

    result: dict[str, type[BaseModel]] = {}

    for model in model_types:
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            continue

        type_field = model.model_fields.get("type")
        if type_field is None:
            continue

        # В моделях с discriminator ожидается Literal в поле type.
        values = get_args(type_field.annotation)

        for value in values:
            if isinstance(value, str):
                result[value] = model

    if not result:
        raise RuntimeError(
            "Could not discover chart models from ChartDefinition"
        )

    return result


def _get_model_info(model_name: str) -> dict[str, Any]:
    """Возвращает JSON Schema и описание конкретного типа чарта."""

    models = _get_chart_models()
    model = models.get(model_name)

    if model is None:
        raise ValueError(
            f"Unknown chart model '{model_name}'. "
            f"Available models: {', '.join(sorted(models))}"
        )

    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    schema = _resolve_refs(schema, definitions)

    return {
        "type": model_name,
        "name": model.__name__,
        "description": model.__doc__ or "",
        "schema": schema,
    }


class GetChartModelInfoArgs(BaseModel):
    """Аргументы запроса информации о модели чарта."""

    model_name: str = Field(
        description=(
            "Тип чарта, полученный через list_chart_models, "
            "например 'kpi' или 'line'."
        )
    )


def _build_chart_args_model() -> type[BaseModel]:
    """
    Создаёт универсальную модель аргументов для построения чарта.

    Поле definition принимает любой тип из ChartDefinition.
    При добавлении нового типа отдельная схема инструмента не нужна.
    """

    return create_model(
        "BuildChartArgs",
        definition=(
            ChartDefinition,
            Field(
                description=(
                    "Полное определение чарта согласно одной из моделей, "
                    "возвращаемых инструментом get_chart_model_info. "
                    "Обязательно укажи поле type и все обязательные поля "
                    "выбранного типа."
                )
            ),
        ),
        filters=(
            list[DashboardFilter],
            Field(
                default_factory=list,
                description=(
                    "Дополнительные фильтры для вычисления данных чарта. "
                    "Если фильтры не нужны, передай пустой список."
                ),
            ),
        ),
    )


def register_chart_tools(
    registry: ToolRegistry,
    charts: ChartRepository,
    executor: ChartExecutor,
) -> None:
    """Регистрирует инструменты просмотра моделей и построения чартов."""

    def list_chart_models(**_: Any) -> dict[str, Any]:
        """Возвращает доступные типы чартов и краткие описания."""

        models = _get_chart_models()

        return {
            "models": [
                {
                    "type": name,
                    "name": model.__name__,
                    "description": model.__doc__ or "",
                }
                for name, model in sorted(models.items())
            ]
        }

    registry.register(
        ToolDefinition(
            name="list_chart_models",
            description=(
                "List all available chart models and their purposes. "
                "Call this before creating a chart if you are unsure "
                "which chart types are supported. This tool only lists "
                "models; it does not create or execute charts."
            ),
            parameters={},
            required=[],
            handler=list_chart_models,
        )
    )

    info_parameters, info_required = _build_parameters(
        GetChartModelInfoArgs
    )

    registry.register(
        ToolDefinition(
            name="get_chart_model_info",
            description=(
                "Get the exact schema for a specific chart type. "
                "Returns the required and optional fields, their types, "
                "and any available descriptions. Call this before "
                "build_chart when you need to know the configuration "
                "requirements for a particular chart type."
            ),
            parameters=info_parameters,
            required=info_required,
            handler=lambda **payload: _get_model_info(
                payload["model_name"]
            ),
        )
    )

    build_args_model = _build_chart_args_model()
    build_parameters, build_required = _build_parameters(build_args_model)

    def build_chart(**payload: Any) -> dict[str, Any]:
        """
        Валидирует определение, сохраняет чарт и вычисляет его данные.

        Сначала сохраняем конфигурацию, чтобы у чарта появился ID.
        Затем выполняем его через ChartExecutor.
        """

        definition = payload["definition"]
        filters = payload.get("filters", [])

        # ChartDefinition уже валидируется Pydantic-схемой инструмента,
        # но повторная проверка защищает от прямых вызовов handler.
        parsed_definition = TypeAdapter(
            ChartDefinition
        ).validate_python(definition)

        chart = charts.create_from_definition(
            parsed_definition.model_dump(mode="json")
        )

        try:
            result = executor.execute(
                chart_id=chart.chart_id,
                filters=filters,
            )
        except Exception:
            # A failed attempt must not leave an artifact that a retry can add
            # to a dashboard. Error details can contain schema names, so keep
            # the public response stable and log-free of source internals.
            charts.delete(chart.id)
            return {
                "success": False,
                "chart_type": parsed_definition.type,
                "error": "Не удалось построить график по выбранным полям.",
            }

        return {
            "success": True,
            "chart_id": chart.chart_id,
            "chart_type": parsed_definition.type,
            "definition": parsed_definition.model_dump(mode="json"),
            "result": result,
        }

    registry.register(
        ToolDefinition(
            name="build_chart",
            description=(
                "Build and save a chart from a generic chart definition, "
                "then execute it and return its data. The definition must "
                "match one of the chart models supported by ChartDefinition. "
                "Use list_chart_models to discover supported types and "
                "get_chart_model_info to inspect a type's exact schema. "
                "Do not invent fields or aggregate operations. "
                "This tool creates one chart, not a dashboard."
            ),
            parameters=build_parameters,
            required=build_required,
            handler=build_chart,
        )
    )
