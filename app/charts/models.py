from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


# ---------------------------------------------------------------------------
# Общие типы и базовая модель
# ---------------------------------------------------------------------------

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]

FilterOperator = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte",
    "in", "not_in", "between", "is_null", "is_not_null",
]
Aggregate = Literal["count", "sum", "avg", "min", "max"]
SortDirection = Literal["asc", "desc", "label_asc", "label_desc"]
FormatType = Literal["number", "integer", "percent", "currency"]


class StrictModel(BaseModel):
    """Запрещает незадекларированные поля во входных данных."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Ссылки на поля и фильтры
# ---------------------------------------------------------------------------

class FieldRef(StrictModel):
    """Поле конкретного источника данных."""

    source_id: Identifier
    field: Identifier


class ValueFormat(StrictModel):
    """Формат отображения вычисленного значения."""

    type: FormatType = "number"
    decimals: int = Field(default=2, ge=0, le=6)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_currency(self) -> ValueFormat:
        if self.type != "currency" and self.currency is not None:
            raise ValueError("currency is only valid for currency format")
        return self


class DashboardFilter(StrictModel):
    """Условие фильтрации данных."""

    field: FieldRef
    operator: FilterOperator
    value: object | None = None

    @model_validator(mode="after")
    def validate_value(self) -> DashboardFilter:
        if self.operator in {"is_null", "is_not_null"}:
            if self.value is not None:
                raise ValueError(f"{self.operator} must not contain a value")
            return self

        if self.value is None:
            raise ValueError(f"{self.operator} requires a non-null value")

        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"{self.operator} requires a non-empty list")
            if len(self.value) > 100:
                raise ValueError("Filter lists may contain at most 100 values")

        if self.operator == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between requires exactly two values")

        return self


# ---------------------------------------------------------------------------
# Определения чартов. Эти модели описывают конфигурацию, но не вычисляют её.
# ---------------------------------------------------------------------------

class ChartBase(StrictModel):
    # id: Identifier
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    filters: list[DashboardFilter] = Field(default_factory=list)


class KPICard(ChartBase):
    type: Literal["kpi"] = "kpi"
    field: FieldRef
    aggregate: Aggregate
    format: ValueFormat = Field(default_factory=ValueFormat)


class LineXAxis(StrictModel):
    field: FieldRef
    type: Literal["temporal", "category", "number"] = "category"
    label: str | None = Field(default=None, max_length=200)
    sort: SortDirection = "asc"


class LineYAxis(StrictModel):
    field: FieldRef
    aggregate: Aggregate
    label: str | None = Field(default=None, max_length=200)
    format: ValueFormat = Field(default_factory=ValueFormat)


class LineCard(ChartBase):
    type: Literal["line"] = "line"
    x: LineXAxis
    y: LineYAxis
    series: FieldRef | None = None
    limit: int = Field(default=100, ge=1, le=1000)


ChartDefinition = Annotated[
    KPICard | LineCard,
    Field(discriminator="type"),
]


class ChartModel(StrictModel):
    """Чарт, сохранённый в БД. Его ID независим от ID внутри definition."""

    chart_id: Identifier
    definition: ChartDefinition
    version: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# Дашборды и ссылки на чарты
# ---------------------------------------------------------------------------

class ChartReference(StrictModel):
    """Ссылка на уже сохранённый чарт с позицией в дашборде."""

    chart_id: Identifier
    position: int = Field(ge=0)


class DashboardModel(StrictModel):
    """Дашборд хранит ссылки на чарты, а не их копии."""

    id: Identifier
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    charts: list[ChartReference] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_charts(self) -> DashboardModel:
        chart_ids = [chart.chart_id for chart in self.charts]
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("A dashboard cannot contain the same chart twice")

        positions = [chart.position for chart in self.charts]
        if len(positions) != len(set(positions)):
            raise ValueError("Chart positions must be unique")

        return self


# ---------------------------------------------------------------------------
# Входные модели инструментов агента
# ---------------------------------------------------------------------------

class ComposeDashboardArgs(StrictModel):
    """Аргументы создания дашборда из существующих chart_id."""

    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    chart_ids: list[Identifier] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_chart_ids(self) -> ComposeDashboardArgs:
        if len(self.chart_ids) != len(set(self.chart_ids)):
            raise ValueError("chart_ids must be unique")
        return self


class AddChartToDashboardArgs(StrictModel):
    """Аргументы добавления существующего чарта в дашборд."""

    dashboard_id: Identifier
    chart_id: Identifier
    position: int | None = Field(default=None, ge=0)


class RemoveChartFromDashboardArgs(StrictModel):
    """Аргументы удаления чарта из дашборда по позиции."""

    dashboard_id: Identifier
    position: int = Field(ge=0)


class GetDashboardArgs(StrictModel):
    dashboard_id: Identifier


class GetChartArgs(StrictModel):
    chart_id: Identifier


# ---------------------------------------------------------------------------
# Ответы инструментов
# ---------------------------------------------------------------------------

class ToolError(StrictModel):
    code: str
    message: str


class DashboardToolResult(StrictModel):
    success: bool
    dashboard: DashboardModel | None = None
    error: ToolError | None = None


class ChartToolResult(StrictModel):
    success: bool
    chart: ChartModel | None = None
    error: ToolError | None = None


# ---------------------------------------------------------------------------
# Результаты выполнения для интерфейса
# ---------------------------------------------------------------------------

class CardResult(StrictModel):
    id: Identifier
    type: str
    title: str
    status: Literal["success", "error"]
    data: dict | list | None = None
    error: ToolError | None = None


class DashboardResult(StrictModel):
    version: Literal[1] = 1
    id: Identifier | None = None
    title: str
    summary: str | None = None
    cards: list[CardResult] = Field(default_factory=list)
