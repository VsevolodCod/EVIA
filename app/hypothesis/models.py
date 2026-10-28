from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


Scalar: TypeAlias = str | int | float | bool


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataFilter(StrictModel):
    """Одно условие отбора строк источника."""

    field: str = Field(min_length=1)
    operator: Literal[
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "is_null",
        "not_null",
        "between"
    ]
    value: Scalar | list[Scalar] | None = None

    @model_validator(mode="after")
    def validate_value(self) -> "DataFilter":
        if self.operator in {"is_null", "not_null"}:
            if self.value is not None:
                raise ValueError(
                    f"Operator '{self.operator}' does not accept a value"
                )
            return self

        if self.value is None:
            raise ValueError(
                f"Operator '{self.operator}' requires a value"
            )

        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(
                    f"Operator '{self.operator}' requires a non-empty list"
                )
        elif self.operator == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError(
                    "Operator 'between' requires exactly two values"
                )

        elif isinstance(self.value, list):
            raise ValueError(
                f"Operator '{self.operator}' requires a scalar value"
            )

        return self


class MetricSpec(StrictModel):
    """Агрегированная метрика одного источника."""

    source_id: str = Field(min_length=1)
    aggregation: Literal[
        "sum",
        "count",
        "count_distinct",
        "avg",
        "min",
        "max",
    ]
    field: str | None = None

    @model_validator(mode="after")
    def validate_field(self) -> "MetricSpec":
        if self.aggregation == "count":
            return self

        if not self.field:
            raise ValueError(
                f"Aggregation '{self.aggregation}' requires a field"
            )

        return self


class ComparisonGroup(StrictModel):
    """Одна из двух сравниваемых групп."""

    label: str = Field(min_length=1, max_length=100)
    filters: list[DataFilter] = Field(default_factory=list)


class MetricExpression(StrictModel):
    """Агрегируемая метрика для анализа связи."""

    aggregation: Literal[
        "sum",
        "count",
        "count_distinct",
        "avg",
        "min",
        "max",
    ]
    field: str | None = None

    @model_validator(mode="after")
    def validate_field(self) -> "MetricExpression":
        if self.aggregation != "count" and not self.field:
            raise ValueError(
                f"Aggregation '{self.aggregation}' requires a field"
            )
        return self


class GroupBySpec(StrictModel):
    """Поле группировки, при необходимости — временная гранулярность."""

    field: str = Field(min_length=1)
    granularity: Literal[
        "day",
        "week",
        "month",
        "quarter",
        "year",
    ] | None = None


class CheckBase(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    description: str = ""


class CompareCheck(CheckBase):
    method: Literal["compare"] = "compare"

    metric: MetricSpec
    left: ComparisonGroup
    right: ComparisonGroup
    expected: Literal[
        "increase",
        "decrease",
        "no_change",
        "any",
    ] = "any"


class RelationshipCheck(StrictModel):
    method: Literal["relationship"] = "relationship"
    source_id: str = Field(min_length=1)

    x_metric: MetricExpression
    y_metric: MetricExpression
    group_by: list[GroupBySpec] = Field(min_length=1, max_length=3)
    filters: list[DataFilter] = Field(default_factory=list)

    relationship: Literal["correlation"] = "correlation"
    correlation_method: Literal["pearson"] = "pearson"
    alpha: float = Field(default=0.05, gt=0, lt=1)
    confidence_level: float = Field(default=0.95, gt=0, lt=1)


HypothesisCheck: TypeAlias = Annotated[
    CompareCheck | RelationshipCheck,
    Field(discriminator="method"),
]


class HypothesisRequest(StrictModel):
    statement: str = Field(min_length=1, max_length=2000)
    checks: list[HypothesisCheck] = Field(min_length=1, max_length=20)


class CheckResult(BaseModel):
    id: str
    method: str
    status: Literal["completed", "error"]
    data: dict = Field(default_factory=dict)
    error: str | None = None


class HypothesisResult(BaseModel):
    statement: str
    results: list[CheckResult]
