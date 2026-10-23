
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.charts.aggregation import filter_expression, quote_identifier
from app.charts.engine import DashboardEngine
from app.charts.errors import (
    UnknownFieldError,
    UnsupportedJoinError,
)
from app.charts.implementations.kpi import KPIImplementation
from app.charts.implementations.line import LineImplementation
from app.charts.models import (
    DashboardFilter,
    DashboardSpec,
    FieldRef,
)
from app.charts.query_planner import QueryPlanner
from app.models import (
    DataSource,
    SchemaField,
    SchemaObject,
    SourceSchema,
)


# ---------------------------------------------------------------------
# Тестовые зависимости
# ---------------------------------------------------------------------

@dataclass
class FakeQueryResult:
    rows: list[tuple]
    provenance: list


class FakeCatalog:
    """Минимальная реализация интерфейса каталога для тестов."""

    def __init__(self):
        self.sources = {
            "sales": DataSource(
                source_id="sales",
                name="Sales",
                source_type="sqlite",
                status="available",
            ),
            "other": DataSource(
                source_id="other",
                name="Other",
                source_type="sqlite",
                status="available",
            ),
        }

        self.schemas = {
            "sales": SourceSchema(
                source_id="sales",
                objects=[
                    SchemaObject(
                        object_id="sales",
                        name="sales",
                        fields=[
                            SchemaField(
                                name="id",
                                inferred_type="integer",
                                nullable=False,
                            ),
                            SchemaField(
                                name="month",
                                inferred_type="string",
                            ),
                            SchemaField(
                                name="revenue",
                                inferred_type="number",
                            ),
                            SchemaField(
                                name="category",
                                inferred_type="string",
                            ),
                        ],
                    )
                ],
            ),
            "other": SourceSchema(
                source_id="other",
                objects=[
                    SchemaObject(
                        object_id="other",
                        name="other",
                        fields=[
                            SchemaField(
                                name="id",
                                inferred_type="integer",
                            ),
                        ],
                    )
                ],
            ),
        }

    def get_source(self, source_id):
        return self.sources.get(source_id)

    def get_schema(self, source_id):
        return self.schemas.get(source_id)


class FakeSourceService:
    """
    Исполняет SQL в настоящем SQLite in-memory.

    Это позволяет проверять реальные результаты KPI и line,
    не подключаясь к внешней базе и не мокая SQL-вычисления.
    """

    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = None

        self.connection.execute(
            """
            CREATE TABLE source (
                id INTEGER PRIMARY KEY,
                month TEXT,
                revenue REAL,
                category TEXT
            )
            """
        )
        self.connection.executemany(
            """
            INSERT INTO source (id, month, revenue, category)
            VALUES (?, ?, ?, ?)
            """,
            [
                (1, "2026-01", 100.0, "A"),
                (2, "2026-01", 150.0, "B"),
                (3, "2026-02", 200.0, "A"),
                (4, "2026-03", None, "B"),
            ],
        )
        self.connection.commit()

        self.queries = []

    def query(self, source_id, sql, row_limit=None, **kwargs):
        self.queries.append((source_id, sql, row_limit))

        cursor = self.connection.execute(sql)
        rows = cursor.fetchmany(row_limit) if row_limit else cursor.fetchall()

        return FakeQueryResult(
            rows=rows,
            provenance=[],
        )

    def close(self):
        self.connection.close()


@pytest.fixture
def catalog():
    return FakeCatalog()


@pytest.fixture
def sources():
    service = FakeSourceService()
    yield service
    service.close()


@pytest.fixture
def planner(catalog):
    return QueryPlanner(catalog)


# ---------------------------------------------------------------------
# 1. Модели и валидация спецификации
# ---------------------------------------------------------------------

def test_dashboard_spec_accepts_kpi_and_line():
    spec = DashboardSpec.model_validate(
        {
            "version": 1,
            "title": "Продажи",
            "cards": [
                {
                    "id": "total",
                    "type": "kpi",
                    "title": "Выручка",
                    "field": {
                        "source_id": "sales",
                        "field": "revenue",
                    },
                    "aggregate": "sum",
                },
                {
                    "id": "monthly",
                    "type": "line",
                    "title": "Выручка по месяцам",
                    "x": {
                        "source_id": "sales",
                        "field": "month",
                        "type": "temporal",
                    },
                    "y": {
                        "source_id": "sales",
                        "field": "revenue",
                        "aggregate": "sum",
                    },
                },
            ],
        }
    )

    assert len(spec.cards) == 2
    assert spec.cards[0].type == "kpi"
    assert spec.cards[1].type == "line"


def test_dashboard_spec_rejects_duplicate_card_ids():
    with pytest.raises(ValidationError):
        DashboardSpec.model_validate(
            {
                "title": "Дубликаты",
                "cards": [
                    {
                        "id": "same",
                        "type": "kpi",
                        "title": "Первый",
                        "field": {
                            "source_id": "sales",
                            "field": "revenue",
                        },
                        "aggregate": "sum",
                    },
                    {
                        "id": "same",
                        "type": "kpi",
                        "title": "Второй",
                        "field": {
                            "source_id": "sales",
                            "field": "revenue",
                        },
                        "aggregate": "sum",
                    },
                ],
            }
        )


def test_dashboard_spec_rejects_invalid_palette_color():
    with pytest.raises(ValidationError):
        DashboardSpec.model_validate(
            {
                "title": "Неверная палитра",
                "palette": ["red", "#ffffff"],
                "cards": [
                    {
                        "id": "total",
                        "type": "kpi",
                        "title": "Выручка",
                        "field": {
                            "source_id": "sales",
                            "field": "revenue",
                        },
                        "aggregate": "sum",
                    }
                ],
            }
        )


# ---------------------------------------------------------------------
# 2. Безопасное формирование SQL и фильтров
# ---------------------------------------------------------------------

def test_quote_identifier_escapes_double_quotes():
    assert quote_identifier('field"name') == '"field""name"'


def test_filter_expression_escapes_string_literal():
    item = DashboardFilter(
        field=FieldRef(source_id="sales", field="category"),
        operator="eq",
        value="A' OR 1=1 --",
    )

    expression = filter_expression(item)

    assert expression == (
        '"category" = \'A\'\' OR 1=1 --\''
    )
    # Введённая строка остаётся одним SQL-литералом.
    assert " OR 1=1 --'" in expression


def test_in_filter_generates_expected_expression():
    item = DashboardFilter(
        field=FieldRef(source_id="sales", field="category"),
        operator="in",
        value=["A", "B"],
    )

    assert filter_expression(item) == '"category" IN (\'A\', \'B\')'


def test_null_filter_does_not_need_value():
    item = DashboardFilter(
        field=FieldRef(source_id="sales", field="category"),
        operator="is_null",
    )

    assert filter_expression(item) == '"category" IS NULL'


def test_in_filter_rejects_empty_list():
    with pytest.raises(ValidationError):
        DashboardFilter(
            field=FieldRef(source_id="sales", field="category"),
            operator="in",
            value=[],
        )


# ---------------------------------------------------------------------
# 3. Проверка полей и источников в QueryPlanner
# ---------------------------------------------------------------------

def test_planner_resolves_existing_field(planner):
    field = planner.resolve_field(
        FieldRef(source_id="sales", field="revenue")
    )

    assert field.source_id == "sales"
    assert field.field_name == "revenue"
    assert field.inferred_type == "number"


def test_planner_rejects_unknown_field(planner):
    with pytest.raises(UnknownFieldError):
        planner.resolve_field(
            FieldRef(source_id="sales", field="missing_column")
        )


def test_planner_rejects_cross_source_card(catalog, planner):
    from app.charts.models import LineCard

    card = LineCard(
        id="cross-source",
        title="Неподдерживаемый график",
        x={
            "source_id": "sales",
            "field": "month",
        },
        y={
            "source_id": "other",
            "field": "id",
            "aggregate": "sum",
        },
    )

    with pytest.raises(UnsupportedJoinError):
        planner.plan(card, [])


# ---------------------------------------------------------------------
# 4. KPI: фактические вычисления
# ---------------------------------------------------------------------

def test_kpi_sum_returns_correct_value(sources, planner):
    implementation = KPIImplementation(sources, planner)

    card = {
        "id": "revenue",
        "type": "kpi",
        "title": "Выручка",
        "field": {
            "source_id": "sales",
            "field": "revenue",
        },
        "aggregate": "sum",
    }

    from app.charts.models import KPICard

    result = implementation.execute(
        KPICard.model_validate(card),
        [],
    )

    # 100 + 150 + 200; NULL в сумме не учитывается.
    assert result["value"] == pytest.approx(450.0)
    assert result["empty"] is False
    assert result["aggregate"] == "sum"


def test_kpi_count_counts_rows_including_null_values(sources, planner):
    from app.charts.models import KPICard

    implementation = KPIImplementation(sources, planner)

    card = KPICard(
        id="count",
        title="Количество строк",
        field={
            "source_id": "sales",
            "field": "revenue",
        },
        aggregate="count",
    )

    result = implementation.execute(card, [])

    # COUNT(*) считает все четыре строки, включая revenue=NULL.
    assert result["value"] == 4
    assert result["empty"] is False


def test_kpi_applies_filter(sources, planner):
    from app.charts.models import KPICard

    implementation = KPIImplementation(sources, planner)

    card = KPICard(
        id="category-a",
        title="Выручка категории A",
        field={
            "source_id": "sales",
            "field": "revenue",
        },
        aggregate="sum",
    )
    filters = [
        DashboardFilter(
            field={
                "source_id": "sales",
                "field": "category",
            },
            operator="eq",
            value="A",
        )
    ]

    result = implementation.execute(card, filters)

    assert result["value"] == pytest.approx(300.0)


def test_kpi_empty_filtered_dataset_is_distinguished_from_zero(
    sources,
    planner,
):
    from app.charts.models import KPICard

    implementation = KPIImplementation(sources, planner)

    card = KPICard(
        id="empty",
        title="Пустой набор",
        field={
            "source_id": "sales",
            "field": "revenue",
        },
        aggregate="sum",
    )
    filters = [
        DashboardFilter(
            field={
                "source_id": "sales",
                "field": "category",
            },
            operator="eq",
            value="DOES_NOT_EXIST",
        )
    ]

    result = implementation.execute(card, filters)

    # Этот тест требует варианта KPI с дополнительным COUNT(*),
    # приведённого в предыдущем ответе.
    assert result["value"] is None
    assert result["empty"] is True


# ---------------------------------------------------------------------
# 5. Line: группировка, фильтры, сортировка и лимит
# ---------------------------------------------------------------------

def test_line_groups_and_aggregates_by_x(sources, planner):
    from app.charts.models import LineCard

    implementation = LineImplementation(sources, planner)

    card = LineCard(
        id="monthly",
        title="Выручка по месяцам",
        x={
            "source_id": "sales",
            "field": "month",
            "type": "temporal",
            "sort": "asc",
        },
        y={
            "source_id": "sales",
            "field": "revenue",
            "aggregate": "sum",
        },
        limit=100,
    )

    result = implementation.execute(card, [])

    assert result["points"] == [
        {"x": "2026-01", "y": 250.0},
        {"x": "2026-02", "y": 200.0},
        {"x": "2026-03", "y": None},
    ]


def test_line_groups_by_series(sources, planner):
    from app.charts.models import LineCard

    implementation = LineImplementation(sources, planner)

    card = LineCard(
        id="by-category",
        title="Выручка по месяцам и категориям",
        x={
            "source_id": "sales",
            "field": "month",
            "type": "temporal",
            "sort": "asc",
        },
        y={
            "source_id": "sales",
            "field": "revenue",
            "aggregate": "sum",
        },
        series={
            "source_id": "sales",
            "field": "category",
        },
    )

    result = implementation.execute(card, [])

    assert len(result["points"]) == 4
    assert {
        (point["x"], point["series"], point["y"])
        for point in result["points"]
    } == {
        ("2026-01", "A", 100.0),
        ("2026-01", "B", 150.0),
        ("2026-02", "A", 200.0),
        ("2026-03", "B", None),
    }


def test_line_applies_filter(sources, planner):
    from app.charts.models import LineCard

    implementation = LineImplementation(sources, planner)

    card = LineCard(
        id="category-a",
        title="Категория A",
        x={
            "source_id": "sales",
            "field": "month",
            "type": "temporal",
        },
        y={
            "source_id": "sales",
            "field": "revenue",
            "aggregate": "sum",
        },
    )
    filters = [
        DashboardFilter(
            field={
                "source_id": "sales",
                "field": "category",
            },
            operator="eq",
            value="A",
        )
    ]

    result = implementation.execute(card, filters)

    assert result["points"] == [
        {"x": "2026-01", "y": 100.0},
        {"x": "2026-02", "y": 200.0},
    ]


def test_line_respects_limit(sources, planner):
    from app.charts.models import LineCard

    implementation = LineImplementation(sources, planner)

    card = LineCard(
        id="limited",
        title="Первые две точки",
        x={
            "source_id": "sales",
            "field": "month",
            "type": "temporal",
            "sort": "asc",
        },
        y={
            "source_id": "sales",
            "field": "revenue",
            "aggregate": "sum",
        },
        limit=2,
    )

    result = implementation.execute(card, [])

    assert len(result["points"]) == 2
    assert result["points"] == [
        {"x": "2026-01", "y": 250.0},
        {"x": "2026-02", "y": 200.0},
    ]
    assert result["limit_reached"] is True


# ---------------------------------------------------------------------
# 6. DashboardEngine: ошибка карточки не ломает весь дашборд
# ---------------------------------------------------------------------

def test_engine_keeps_successful_cards_when_another_card_fails(
    catalog,
    sources,
):
    engine = DashboardEngine(catalog, sources)

    result = engine.create_dashboard(
        {
            "title": "Тестовый дашборд",
            "cards": [
                {
                    "id": "good",
                    "type": "kpi",
                    "title": "Корректный KPI",
                    "field": {
                        "source_id": "sales",
                        "field": "revenue",
                    },
                    "aggregate": "sum",
                },
                {
                    "id": "bad",
                    "type": "kpi",
                    "title": "Несуществующее поле",
                    "field": {
                        "source_id": "sales",
                        "field": "missing",
                    },
                    "aggregate": "sum",
                },
            ],
        }
    )

    assert result["cards"][0]["status"] == "success"
    assert result["cards"][0]["data"]["value"] == pytest.approx(450.0)

    assert result["cards"][1]["status"] == "error"
    assert result["cards"][1]["error"]["code"] == "unknown_field"


def test_dashboard_computes_kpi_and_line_from_real_csv(tmp_path):
    from app.schema_catalog import SchemaCatalog
    from app.source_service import SourceService

    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    try:
        source = sources.register_csv(
            "sales.csv",
            b"month;revenue\n2026-01;120,5\n2026-02;180.5\n",
        )
        result = DashboardEngine(catalog, sources).create_dashboard({
            "title": "Продажи",
            "cards": [
                {"id": "total", "type": "kpi", "title": "Выручка",
                 "field": {"source_id": source.source_id, "field": "revenue"}, "aggregate": "sum"},
                {"id": "monthly", "type": "line", "title": "По месяцам",
                 "x": {"source_id": source.source_id, "field": "month"},
                 "y": {"source_id": source.source_id, "field": "revenue", "aggregate": "sum"}},
            ],
        })
        assert [card["status"] for card in result["cards"]] == ["success", "success"]
        assert result["cards"][0]["data"]["value"] == "301.0"
        assert result["cards"][1]["data"]["points"] == [
            {"x": "2026-01", "y": "120.5"},
            {"x": "2026-02", "y": "180.5"},
        ]
        assert sources.preview(source.source_id, 1)[0]["revenue"] == "120,5"
    finally:
        catalog.close()


def test_line_rejects_text_aggregate_that_cannot_be_drawn(tmp_path):
    from app.schema_catalog import SchemaCatalog
    from app.source_service import SourceService

    catalog = SchemaCatalog(tmp_path / "catalog.db")
    sources = SourceService(tmp_path / "data", catalog)
    try:
        source = sources.register_csv("status.csv", b"month,status\nJan,Alpha\nFeb,Beta\n")
        result = DashboardEngine(catalog, sources).create_dashboard({
            "title": "Статусы", "cards": [{
                "id": "status", "type": "line", "title": "Статус по месяцам",
                "x": {"source_id": source.source_id, "field": "month"},
                "y": {"source_id": source.source_id, "field": "status", "aggregate": "max"},
            }],
        })
        assert result["cards"][0]["status"] == "error"
        assert result["cards"][0]["error"]["code"] == "unsupported_type"
    finally:
        catalog.close()
