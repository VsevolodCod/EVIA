
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
    FieldRef, ChartModel, KPICard, LineCard,
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
                    "type": "kpi",
                    "title": "Выручка",
                    "field": {
                        "source_id": "sales",
                        "field": "revenue",
                    },
                    "aggregate": "sum",
                },
                {
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


def test_dashboard_spec_rejects_invalid_palette_color():
    with pytest.raises(ValidationError):
        DashboardSpec.model_validate(
            {
                "title": "Неверная палитра",
                "palette": ["red", "#ffffff"],
                "cards": [
                    {
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


class FakeChartRepository:
    def __init__(self, charts=None):
        self.charts = {
            chart.chart_id: chart
            for chart in (charts or [])
        }

    def get_by_id(self, chart_id):
        return self.charts.get(chart_id)


class FakeDashboardRepository:
    def __init__(self):
        self.dashboards = {}

    def create(self, dashboard):
        self.dashboards[dashboard.id] = dashboard
        return dashboard

    def get_by_id(self, dashboard_id):
        return self.dashboards.get(dashboard_id)

    def update(self, dashboard):
        self.dashboards[dashboard.id] = dashboard
        return dashboard


@pytest.fixture
def repositories():
    charts = FakeChartRepository([
        ChartModel(
            chart_id="chart-1",
            definition=KPICard(
                type="kpi",
                title="Выручка",
                field={
                    "source_id": "sales",
                    "field": "revenue",
                },
                aggregate="sum",
            ),
        ),
    ])

    dashboards = FakeDashboardRepository()

    return charts, dashboards


@pytest.fixture
def engine(repositories):
    charts, dashboards = repositories
    return DashboardEngine(charts, dashboards)


def test_compose_dashboard_saves_chart_references(
    engine,
    repositories,
):
    _, dashboards = repositories

    result = engine.compose_dashboard({
        "title": "Продажи",
        "summary": "Аналитика продаж",
        "chart_ids": ["chart-1"],
    })

    assert result["success"] is True

    dashboard = result["dashboard"]
    assert dashboard["title"] == "Продажи"
    assert dashboard["summary"] == "Аналитика продаж"
    assert dashboard["version"] == 1
    assert dashboard["charts"] == [
        {"chart_id": "chart-1", "position": 0},
    ]

    assert dashboard["id"] in dashboards.dashboards


def test_compose_dashboard_rejects_missing_chart(engine):
    result = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["missing-chart"],
    })

    assert result["success"] is False
    assert result["error"]["code"] == "chart_not_found"


def test_compose_dashboard_rejects_invalid_arguments(engine):
    result = engine.compose_dashboard({
        "chart_ids": ["chart-1"],
    })

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_arguments"


def test_compose_dashboard_rejects_duplicate_chart_ids(engine):
    result = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["chart-1", "chart-1"],
    })

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_arguments"


def test_get_chart_returns_saved_definition(engine):
    result = engine.get_chart({
        "chart_id": "chart-1",
    })

    assert result["success"] is True

    chart = result["chart"]
    assert chart["chart_id"] == "chart-1"
    assert chart["version"] == 1
    assert chart["definition"]["type"] == "kpi"
    assert chart["definition"]["title"] == "Выручка"
    assert chart["definition"]["field"] == {
        "source_id": "sales",
        "field": "revenue",
    }


def test_get_chart_returns_error_for_missing_chart(engine):
    result = engine.get_chart({
        "chart_id": "missing-chart",
    })

    assert result["success"] is False
    assert result["error"]["code"] == "chart_not_found"


def test_get_dashboard_returns_chart_definitions(engine):
    created = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["chart-1"],
    })

    dashboard_id = created["dashboard"]["id"]

    result = engine.get_dashboard({
        "dashboard_id": dashboard_id,
    })

    assert result["success"] is True
    assert result["dashboard"]["id"] == dashboard_id
    assert len(result["charts"]) == 1

    item = result["charts"][0]
    assert item["status"] == "success"
    assert item["chart_id"] == "chart-1"
    assert item["position"] == 0
    assert item["chart"]["definition"]["type"] == "kpi"


def test_get_dashboard_returns_error_for_missing_dashboard(engine):
    result = engine.get_dashboard({
        "dashboard_id": "missing-dashboard",
    })

    assert result["success"] is False
    assert result["error"]["code"] == "dashboard_not_found"


def test_add_chart_to_dashboard_appends_chart(
    engine,
    repositories,
):
    charts, _ = repositories

    charts.charts["chart-2"] = ChartModel(
        chart_id="chart-2",
        definition=LineCard(
            type="line",
            title="Выручка по месяцам",
            x={
                "source_id": "sales",
                "field": "month",
                "type": "category",
            },
            y={
                "source_id": "sales",
                "field": "revenue",
                "aggregate": "sum",
            },
        ),
    )

    created = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["chart-1"],
    })

    result = engine.add_chart_to_dashboard({
        "dashboard_id": created["dashboard"]["id"],
        "chart_id": "chart-2",
    })

    assert result["success"] is True

    dashboard = result["dashboard"]
    assert [ref["chart_id"] for ref in dashboard["charts"]] == [
        "chart-1",
        "chart-2",
    ]
    assert [ref["position"] for ref in dashboard["charts"]] == [0, 1]
    assert dashboard["version"] == 2


def test_add_chart_to_dashboard_inserts_at_position(
    engine,
    repositories,
):
    charts, _ = repositories

    charts.charts["chart-2"] = ChartModel(
        chart_id="chart-2",
        definition=KPICard(
            title="Количество продаж",
            field={
                "source_id": "sales",
                "field": "quantity",
            },
            aggregate="sum",
        ),
    )

    charts.charts["chart-3"] = ChartModel(
        chart_id="chart-3",
        definition=LineCard(
            title="Продажи по месяцам",
            x={
                "source_id": "sales",
                "field": "month",
            },
            y={
                "source_id": "sales",
                "field": "revenue",
                "aggregate": "sum",
            },
        ),
    )

    created = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["chart-1", "chart-2"],
    })

    result = engine.add_chart_to_dashboard({
        "dashboard_id": created["dashboard"]["id"],
        "chart_id": "chart-3",
        "position": 1,
    })

    assert result["success"] is True

    refs = result["dashboard"]["charts"]
    assert [ref["chart_id"] for ref in refs] == [
        "chart-1",
        "chart-3",
        "chart-2",
    ]
    assert [ref["position"] for ref in refs] == [0, 1, 2]


def test_add_chart_to_dashboard_rejects_duplicate(
    engine,
):
    created = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["chart-1"],
    })

    result = engine.add_chart_to_dashboard({
        "dashboard_id": created["dashboard"]["id"],
        "chart_id": "chart-1",
    })

    assert result["success"] is False
    assert result["error"]["code"] == "chart_already_added"


def test_add_chart_to_dashboard_rejects_invalid_position(
    engine,
    repositories,
):
    charts, _ = repositories

    charts.charts["chart-2"] = ChartModel(
        chart_id="chart-2",
        definition=KPICard(
            title="Количество продаж",
            field={
                "source_id": "sales",
                "field": "quantity",
            },
            aggregate="sum",
        ),
    )

    created = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["chart-1"],
    })

    result = engine.add_chart_to_dashboard({
        "dashboard_id": created["dashboard"]["id"],
        "chart_id": "chart-2",
        "position": 2,
    })

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_position"


def test_add_chart_to_dashboard_rejects_missing_dashboard(engine):
    result = engine.add_chart_to_dashboard({
        "dashboard_id": "missing-dashboard",
        "chart_id": "chart-1",
    })

    assert result["success"] is False
    assert result["error"]["code"] == "dashboard_not_found"


def test_add_chart_to_dashboard_rejects_missing_chart(engine):
    created = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["chart-1"],
    })

    result = engine.add_chart_to_dashboard({
        "dashboard_id": created["dashboard"]["id"],
        "chart_id": "missing-chart",
    })

    assert result["success"] is False
    assert result["error"]["code"] == "chart_not_found"


def test_remove_chart_from_dashboard_reindexes_remaining_charts(
    engine,
    repositories,
):
    charts, _ = repositories

    for chart_id in ("chart-2", "chart-3"):
        charts.charts[chart_id] = ChartModel(
            chart_id=chart_id,
            definition=KPICard(
                title=chart_id,
                field={
                    "source_id": "sales",
                    "field": "revenue",
                },
                aggregate="sum",
            ),
        )

    created = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["chart-1", "chart-2", "chart-3"],
    })

    result = engine.remove_chart_from_dashboard({
        "dashboard_id": created["dashboard"]["id"],
        "position": 1,
    })

    assert result["success"] is True

    dashboard = result["dashboard"]
    assert [ref["chart_id"] for ref in dashboard["charts"]] == [
        "chart-1",
        "chart-3",
    ]
    assert [ref["position"] for ref in dashboard["charts"]] == [0, 1]
    assert dashboard["version"] == 2


def test_remove_chart_from_dashboard_rejects_missing_position(engine):
    created = engine.compose_dashboard({
        "title": "Продажи",
        "chart_ids": ["chart-1"],
    })

    result = engine.remove_chart_from_dashboard({
        "dashboard_id": created["dashboard"]["id"],
        "position": 5,
    })

    assert result["success"] is False
    assert result["error"]["code"] == "chart_position_not_found"


def test_remove_chart_from_dashboard_rejects_missing_dashboard(engine):
    result = engine.remove_chart_from_dashboard({
        "dashboard_id": "missing-dashboard",
        "position": 0,
    })

    assert result["success"] is False
    assert result["error"]["code"] == "dashboard_not_found"


# ==================================================================
#                 TODO:ПОМЕНЯТЬ ДЛЯ НОВОЙ АРХИТЕКТУРЫ
# ==================================================================

# def test_bar_groups_categories_with_the_same_numeric_contract(sources, catalog):
#     result = DashboardEngine(catalog, sources).create_dashboard({
#         "title": "Categories", "cards": [{
#             "type": "bar", "title": "Revenue by category",
#             "x": {"source_id": "sales", "field": "category", "sort": "asc"},
#             "y": {"source_id": "sales", "field": "revenue", "aggregate": "sum"},
#         }],
#     })["cards"][0]
#
#     assert result["status"] == "success"
#     assert result["type"] == "bar"
#     assert result["data"]["points"] == [
#         {"x": "A", "y": 300.0},
#         {"x": "B", "y": 150.0},
#     ]
#     assert result["data"]["source_id"] == "sales"
#     assert result["data"]["limit"] == 100
#     assert result["data"]["provenance"] == []
#
#
# def test_scatter_retains_duplicate_raw_pairs_and_excludes_null_axes(sources, catalog):
#     sources.connection.execute("ALTER TABLE source ADD COLUMN cost REAL")
#     sources.connection.execute("DELETE FROM source")
#     sources.connection.executemany(
#         "INSERT INTO source (id, month, revenue, category, cost) VALUES (?, ?, ?, ?, ?)",
#         [
#             (1, "Jan", 10, "A", 5),
#             (2, "Feb", 10, "B", 5),
#             (3, "Mar", 20, "A", None),
#             (4, "Apr", None, "B", 8),
#             (5, "May", 30, "B", 12),
#         ],
#     )
#     catalog.schemas["sales"].objects[0].fields.append(
#         SchemaField(name="cost", inferred_type="number")
#     )
#
#     result = DashboardEngine(catalog, sources).create_dashboard({
#         "title": "Pairs", "cards": [{
#             "type": "scatter", "title": "Revenue and cost",
#             "x": {"source_id": "sales", "field": "revenue"},
#             "y": {"source_id": "sales", "field": "cost"},
#             "limit": 2,
#         }],
#     })["cards"][0]
#
#     assert result["status"] == "success"
#     assert result["data"]["points"] == [
#         {"x": 10.0, "y": 5.0},
#         {"x": 10.0, "y": 5.0},
#     ]
#     assert result["data"]["limit_reached"] is True
#     assert result["data"]["source_id"] == "sales"
#     assert "IS NOT NULL" in sources.queries[-1][1]
#     assert sources.queries[-1][2] == 2
#
#
# def test_table_returns_selected_raw_fields_in_stable_bounded_order(sources, catalog):
#     result = DashboardEngine(catalog, sources).create_dashboard({
#         "title": "Rows", "cards": [{
#             "type": "table", "title": "Raw sales",
#             "fields": [
#                 {"source_id": "sales", "field": "category"},
#                 {"source_id": "sales", "field": "revenue"},
#             ],
#             "limit": 2,
#         }],
#     })["cards"][0]
#
#     assert result["status"] == "success"
#     assert result["data"]["columns"] == ["category", "revenue"]
#     assert result["data"]["rows"] == [
#         {"category": "A", "revenue": 100.0},
#         {"category": "A", "revenue": 200.0},
#     ]
#     assert result["data"]["limit"] == 2
#     assert result["data"]["limit_reached"] is True
#     assert result["data"]["source_id"] == "sales"
#     assert sources.queries[-1][2] == 2
#
#
# def test_scatter_rejects_non_numeric_axis_and_cross_source_fields(sources, catalog):
#     cards = [
#         {"type": "scatter", "title": "Invalid axis",
#          "x": {"source_id": "sales", "field": "category"},
#          "y": {"source_id": "sales", "field": "revenue"}},
#         {"type": "scatter", "title": "Invalid source",
#          "x": {"source_id": "sales", "field": "revenue"},
#          "y": {"source_id": "other", "field": "id"}},
#     ]
#     results = DashboardEngine(catalog, sources).create_dashboard({
#         "title": "Invalid", "cards": cards,
#     })["cards"]
#
#     assert [card["status"] for card in results] == ["error", "error"]
#     assert [card["error"]["code"] for card in results] == [
#         "unsupported_type", "unsupported_join",
#     ]
#
#
# def test_bar_rejects_text_measure_and_table_rejects_cross_source_fields(sources, catalog):
#     results = DashboardEngine(catalog, sources).create_dashboard({
#         "title": "Invalid", "cards": [
#             {"type": "bar", "title": "Text measure",
#              "x": {"source_id": "sales", "field": "month"},
#              "y": {"source_id": "sales", "field": "category", "aggregate": "max"}},
#             {"type": "table", "title": "Two sources",
#              "fields": [
#                  {"source_id": "sales", "field": "category"},
#                  {"source_id": "other", "field": "id"},
#              ]},
#         ],
#     })["cards"]
#
#     assert [card["error"]["code"] for card in results] == [
#         "unsupported_type", "unsupported_join",
#     ]
#
#
# @pytest.mark.parametrize("kind,extra", [
#     ("scatter", {"x": {"source_id": "sales", "field": "id"},
#                  "y": {"source_id": "sales", "field": "revenue"}}),
#     ("table", {"fields": [{"source_id": "sales", "field": "month"}]}),
# ])
# def test_raw_chart_limits_are_bounded(kind, extra):
#     from pydantic import TypeAdapter
#     from app.charts.models import ChartDefinition
#
#     with pytest.raises(ValidationError):
#         TypeAdapter(ChartDefinition).validate_python({
#             "type": kind, "title": "Too many rows", "limit": 1001, **extra,
#         })
