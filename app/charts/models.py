from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]

FilterOperator = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte",
    "in", "not_in", "between", "is_null", "is_not_null",
]

Aggregate = Literal["count", "sum", "avg", "min", "max"]
SortDirection = Literal["asc", "desc", "label_asc", "label_desc"]
FormatType = Literal["number", "integer", "percent", "currency"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldRef(StrictModel):
    source_id: Identifier
    field: Identifier


class ValueFormat(StrictModel):
    type: FormatType = "number"
    decimals: int = Field(default=2, ge=0, le=6)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class DashboardFilter(StrictModel):
    field: FieldRef
    operator: FilterOperator
    value: object | None = None

    @model_validator(mode="after")
    def validate_value(self):
        if self.operator in {"is_null", "is_not_null"}:
            if self.value is not None:
                raise ValueError(
                    f"{self.operator} must not contain a value"
                )
            return self

        if self.value is None:
            raise ValueError(
                f"{self.operator} requires a non-null value"
            )

        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(
                    f"{self.operator} requires a non-empty list"
                )
            if len(self.value) > 100:
                raise ValueError("Filter lists may contain at most 100 values")

        if self.operator == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between requires exactly two values")

        return self


class CardBase(StrictModel):
    id: Identifier
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    filters: list[DashboardFilter] = Field(default_factory=list)


class KPICard(CardBase):
    type: Literal["kpi"] = "kpi"
    field: FieldRef
    aggregate: Aggregate
    format: ValueFormat = Field(default_factory=ValueFormat)


class LineXAxis(FieldRef):
    type: Literal["temporal", "category", "number"] = "category"
    label: str | None = Field(default=None, max_length=200)
    sort: SortDirection = "asc"


class LineYAxis(FieldRef):
    aggregate: Aggregate
    label: str | None = Field(default=None, max_length=200)
    format: ValueFormat = Field(default_factory=ValueFormat)


class LineCard(CardBase):
    type: Literal["line"] = "line"
    x: LineXAxis
    y: LineYAxis
    series: FieldRef | None = None
    limit: int = Field(default=100, ge=1, le=1000)


DashboardCard = Annotated[
    KPICard | LineCard,
    Field(discriminator="type"),
]


class DashboardSpec(StrictModel):
    version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    palette: list[str] | None = Field(default=None, min_length=2, max_length=12)
    filters: list[DashboardFilter] = Field(default_factory=list)
    cards: list[DashboardCard] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_dashboard(self):
        ids = [card.id for card in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError("Card IDs must be unique")

        if self.palette:
            for color in self.palette:
                if (
                    len(color) != 7
                    or not color.startswith("#")
                    or any(c not in "0123456789abcdefABCDEF" for c in color[1:])
                ):
                    raise ValueError(f"Invalid palette color: {color}")

        return self


class CardResult(StrictModel):
    id: str
    type: str
    title: str
    status: Literal["success", "error"]
    data: dict | list | None = None
    error: dict[str, str] | None = None


class DashboardResult(StrictModel):
    version: Literal[1] = 1
    title: str
    summary: str | None = None
    palette: list[str] | None = None
    cards: list[CardResult]
