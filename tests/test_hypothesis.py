from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.hypothesis.base import (
    build_filter_expression,
    build_where,
    extract_rows,
    quote_identifier,
    sql_literal,
)
from app.hypothesis.engine import HypothesisEngine
from app.hypothesis.implementations.compare import CompareImplementation
from app.hypothesis.implementations.relationship import (
    RelationshipImplementation,
)
from app.hypothesis.models import (
    CompareCheck,
    DataFilter,
    HypothesisRequest,
    MetricExpression,
    MetricSpec,
    RelationshipCheck,
)


class FakeSources:
    """Источник данных с заранее заданными результатами запросов."""

    def __init__(self, *results):
        self.results = list(results)
        self.queries: list[dict] = []

    def query(self, source_id, sql, *, row_limit=None):
        self.queries.append(
            {
                "source_id": source_id,
                "sql": sql,
                "row_limit": row_limit,
            }
        )

        if not self.results:
            raise AssertionError("Unexpected query")

        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result

        return SimpleNamespace(rows=result)


def compare_payload(**overrides):
    payload = {
        "id": "sales-comparison",
        "method": "compare",
        "metric": {
            "source_id": "sales",
            "aggregation": "sum",
            "field": "amount",
        },
        "left": {
            "label": "До",
            "filters": [
                {
                    "field": "period",
                    "operator": "eq",
                    "value": "before",
                }
            ],
        },
        "right": {
            "label": "После",
            "filters": [
                {
                    "field": "period",
                    "operator": "eq",
                    "value": "after",
                }
            ],
        },
        "expected": "increase",
    }
    payload.update(overrides)
    return payload


def relationship_payload(**overrides):
    payload = {
        "id": "sales-relationship",
        "method": "relationship",
        "source_id": "sales",
        "x_metric": {
            "aggregation": "sum",
            "field": "marketing_cost",
        },
        "y_metric": {
            "aggregation": "sum",
            "field": "revenue",
        },
        "group_by": [{"field": "month"}],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Models and validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operator", "value"),
    [
        ("eq", "x"),
        ("ne", 1),
        ("gt", 1),
        ("gte", 1),
        ("lt", 1),
        ("lte", 1),
        ("in", [1, 2]),
        ("not_in", ["a", "b"]),
        ("between", [1, 10]),
        ("is_null", None),
        ("not_null", None),
    ],
)
def test_data_filter_accepts_valid_operators(operator, value):
    item = DataFilter(
        field="column",
        operator=operator,
        value=value,
    )
    assert item.operator == operator


@pytest.mark.parametrize(
    ("operator", "value"),
    [
        ("eq", None),
        ("gt", None),
        ("in", []),
        ("in", "x"),
        ("not_in", []),
        ("between", [1]),
        ("between", [1, 2, 3]),
        ("between", 1),
        ("eq", [1, 2]),
        ("is_null", "x"),
        ("not_null", 0),
    ],
)
def test_data_filter_rejects_invalid_values(operator, value):
    with pytest.raises(ValidationError):
        DataFilter(
            field="column",
            operator=operator,
            value=value,
        )


def test_data_filter_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        DataFilter(
            field="amount",
            operator="eq",
            value=1,
            unexpected=True,
        )


@pytest.mark.parametrize(
    "aggregation",
    ["sum", "count_distinct", "avg", "min", "max"],
)
def test_metric_spec_requires_field_for_non_count_aggregations(
    aggregation,
):
    with pytest.raises(ValidationError):
        MetricSpec(
            source_id="sales",
            aggregation=aggregation,
        )


def test_metric_spec_count_does_not_require_field():
    metric = MetricSpec(
        source_id="sales",
        aggregation="count",
    )
    assert metric.field is None


def test_metric_expression_count_does_not_require_field():
    metric = MetricExpression(aggregation="count")
    assert metric.field is None


def test_metric_expression_requires_field_for_sum():
    with pytest.raises(ValidationError):
        MetricExpression(aggregation="sum")


def test_relationship_requires_one_to_three_groupings():
    with pytest.raises(ValidationError):
        RelationshipCheck.model_validate(
            relationship_payload(group_by=[])
        )

    with pytest.raises(ValidationError):
        RelationshipCheck.model_validate(
            relationship_payload(
                group_by=[
                    {"field": "a"},
                    {"field": "b"},
                    {"field": "c"},
                    {"field": "d"},
                ]
            )
        )


@pytest.mark.parametrize("alpha", [0, 1, -0.1, 1.1])
def test_relationship_rejects_invalid_alpha(alpha):
    with pytest.raises(ValidationError):
        RelationshipCheck.model_validate(
            relationship_payload(alpha=alpha)
        )


def test_request_requires_at_least_one_check():
    with pytest.raises(ValidationError):
        HypothesisRequest.model_validate(
            {"statement": "Check sales", "checks": []}
        )



def test_request_parses_discriminated_check_types():
    request = HypothesisRequest.model_validate(
        {
            "statement": "Compare sales",
            "checks": [compare_payload()],
        }
    )

    assert isinstance(request.checks[0], CompareCheck)

    relationship = RelationshipCheck.model_validate(
        relationship_payload()
    )
    assert isinstance(relationship, RelationshipCheck)


# ---------------------------------------------------------------------------
# SQL helpers and safety
# ---------------------------------------------------------------------------


def test_quote_identifier_escapes_double_quotes():
    assert quote_identifier('total"amount') == '"total""amount"'


@pytest.mark.parametrize("identifier", ["", "bad\x00name"])
def test_quote_identifier_rejects_invalid_identifier(identifier):
    with pytest.raises(ValueError):
        quote_identifier(identifier)


def test_sql_literal_escapes_single_quotes():
    assert sql_literal("O'Reilly") == "'O''Reilly'"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "TRUE"),
        (False, "FALSE"),
        (10, "10"),
        (2.5, "2.5"),
    ],
)
def test_sql_literal_supports_scalar_values(value, expected):
    assert sql_literal(value) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_sql_literal_rejects_non_finite_numbers(value):
    with pytest.raises(ValueError):
        sql_literal(value)


def test_sql_literal_rejects_unsupported_types():
    with pytest.raises(ValueError):
        sql_literal({"unexpected": "object"})


def test_build_filter_expression_between():
    item = DataFilter(
        field="amount",
        operator="between",
        value=[10, 20],
    )
    assert build_filter_expression(item) == '"amount" BETWEEN 10 AND 20'


def test_build_filter_expression_in():
    item = DataFilter(
        field="status",
        operator="in",
        value=["new", "paid"],
    )
    assert (
        build_filter_expression(item)
        == '"status" IN (\'new\', \'paid\')'
    )


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("is_null", '"status" IS NULL'),
        ("not_null", '"status" IS NOT NULL'),
    ],
)
def test_build_filter_expression_null_operators(operator, expected):
    item = DataFilter(
        field="status",
        operator=operator,
        value=None,
    )
    assert build_filter_expression(item) == expected


def test_build_where_joins_conditions_with_and():
    filters = [
        DataFilter(field="status", operator="eq", value="paid"),
        DataFilter(field="amount", operator="gte", value=100),
    ]

    assert build_where(filters) == (
        """ WHERE ("status" = 'paid') AND ("amount" >= 100)"""
    )


def test_build_where_without_filters_is_empty():
    assert build_where([]) == ""


def test_extract_rows_accepts_dict_rows():
    result = SimpleNamespace(rows=[{"amount": 10}])
    assert extract_rows(result) == [{"amount": 10}]


def test_extract_rows_accepts_pydantic_like_rows():
    row = Mock()
    row.model_dump.return_value = {"amount": 10}

    assert extract_rows(SimpleNamespace(rows=[row])) == [
        {"amount": 10}
    ]


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(),
        SimpleNamespace(rows=None),
        SimpleNamespace(rows=[("amount", 10)]),
    ],
)
def test_extract_rows_rejects_unsupported_result_shapes(result):
    with pytest.raises(ValueError):
        extract_rows(result)


# ---------------------------------------------------------------------------
# Compare implementation
# ---------------------------------------------------------------------------


def test_compare_builds_sum_sql_and_uses_both_groups():
    sources = FakeSources(
        [{"metric_value": 100}],
        [{"metric_value": 150}],
    )
    implementation = CompareImplementation(sources)
    check = CompareCheck.model_validate(compare_payload())

    result = implementation.execute(check)

    assert len(sources.queries) == 2
    assert all(query["source_id"] == "sales" for query in sources.queries)
    assert all(query["row_limit"] == 1 for query in sources.queries)

    assert 'SUM(TRY_CAST("amount" AS DOUBLE)) AS metric_value' in (
        sources.queries[0]["sql"]
    )
    assert '"period" = \'before\'' in sources.queries[0]["sql"]
    assert '"period" = \'after\'' in sources.queries[1]["sql"]

    assert result["left"]["value"] == 100
    assert result["right"]["value"] == 150
    assert result["delta"] == 50
    assert result["change_percent"] == 50
    assert result["direction"] == "increase"
    assert result["assessment"] == "supports"


@pytest.mark.parametrize(
    ("left", "right", "expected_direction", "expected_delta"),
    [
        (100, 80, "decrease", -20),
        (100, 100, "no_change", 0),
    ],
)
def test_compare_detects_direction(
    left,
    right,
    expected_direction,
    expected_delta,
):
    sources = FakeSources(
        [{"metric_value": left}],
        [{"metric_value": right}],
    )
    result = CompareImplementation(sources).execute(
        CompareCheck.model_validate(compare_payload(expected="any"))
    )

    assert result["direction"] == expected_direction
    assert result["delta"] == expected_delta
    assert result["assessment"] == "observed"


def test_compare_contradicts_expected_direction():
    sources = FakeSources(
        [{"metric_value": 100}],
        [{"metric_value": 80}],
    )
    result = CompareImplementation(sources).execute(
        CompareCheck.model_validate(compare_payload(expected="increase"))
    )

    assert result["direction"] == "decrease"
    assert result["assessment"] == "contradicts"


def test_compare_zero_baseline_has_no_percentage_change():
    sources = FakeSources(
        [{"metric_value": 0}],
        [{"metric_value": 10}],
    )
    result = CompareImplementation(sources).execute(
        CompareCheck.model_validate(compare_payload())
    )

    assert result["delta"] == 10
    assert result["change_percent"] is None


def test_compare_null_metric_is_inconclusive():
    sources = FakeSources(
        [{"metric_value": None}],
        [{"metric_value": 10}],
    )
    result = CompareImplementation(sources).execute(
        CompareCheck.model_validate(compare_payload())
    )

    assert result["assessment"] == "inconclusive"
    assert result["delta"] is None
    assert result["change_percent"] is None
    assert "reason" in result


def test_compare_empty_rows_produce_inconclusive_result():
    sources = FakeSources([], [{"metric_value": 10}])
    result = CompareImplementation(sources).execute(
        CompareCheck.model_validate(compare_payload())
    )

    assert result["assessment"] == "inconclusive"
    assert result["left"]["value"] is None


@pytest.mark.parametrize(
    ("aggregation", "expected_sql"),
    [
        ("count", "COUNT(*)"),
        ("count_distinct", 'COUNT(DISTINCT "amount")'),
        ("sum", 'SUM(TRY_CAST("amount" AS DOUBLE))'),
        ("avg", 'AVG(TRY_CAST("amount" AS DOUBLE))'),
        ("min", 'MIN(TRY_CAST("amount" AS DOUBLE))'),
        ("max", 'MAX(TRY_CAST("amount" AS DOUBLE))'),
    ],
)
def test_compare_aggregate_sql(aggregation, expected_sql):
    payload = compare_payload(
        metric={
            "source_id": "sales",
            "aggregation": aggregation,
            **({} if aggregation == "count" else {"field": "amount"}),
        }
    )
    check = CompareCheck.model_validate(payload)

    assert CompareImplementation._aggregate_sql(check) == expected_sql


def test_compare_rejects_boolean_metric_result():
    sources = FakeSources(
        [{"metric_value": True}],
        [{"metric_value": 10}],
    )

    with pytest.raises(ValueError, match="Boolean"):
        CompareImplementation(sources).execute(
            CompareCheck.model_validate(compare_payload())
        )


# ---------------------------------------------------------------------------
# Relationship implementation
# ---------------------------------------------------------------------------


def correlation_rows():
    return [
        {"group_0": "2026-01", "x_value": 1, "y_value": 2},
        {"group_0": "2026-02", "x_value": 2, "y_value": 4},
        {"group_0": "2026-03", "x_value": 3, "y_value": 6},
        {"group_0": "2026-04", "x_value": 4, "y_value": 8},
    ]


def test_relationship_builds_grouped_aggregation_sql():
    check = RelationshipCheck.model_validate(
        relationship_payload(
            group_by=[{"field": "month", "granularity": "month"}],
            filters=[
                {
                    "field": "region",
                    "operator": "eq",
                    "value": "north",
                }
            ],
        )
    )

    implementation = RelationshipImplementation(FakeSources())
    sql = implementation._build_sql(check)

    assert 'DATE_TRUNC(\'month\', TRY_CAST("month" AS TIMESTAMP))' in sql
    assert 'SUM(TRY_CAST("marketing_cost" AS DOUBLE)) AS x_value' in sql
    assert 'SUM(TRY_CAST("revenue" AS DOUBLE)) AS y_value' in sql
    assert '"region" = \'north\'' in sql
    assert "GROUP BY DATE_TRUNC" in sql
    assert "ORDER BY DATE_TRUNC" in sql
    assert "LIMIT 10001" in sql


@pytest.mark.parametrize(
    ("aggregation", "expected_sql"),
    [
        ("count", "COUNT(*)"),
        ("count_distinct", 'COUNT(DISTINCT "amount")'),
        ("sum", 'SUM(TRY_CAST("amount" AS DOUBLE))'),
        ("avg", 'AVG(TRY_CAST("amount" AS DOUBLE))'),
        ("min", 'MIN(TRY_CAST("amount" AS DOUBLE))'),
        ("max", 'MAX(TRY_CAST("amount" AS DOUBLE))'),
    ],
)
def test_relationship_aggregate_sql(aggregation, expected_sql):
    metric = MetricExpression(
        aggregation=aggregation,
        **({} if aggregation == "count" else {"field": "amount"}),
    )

    assert (
        RelationshipImplementation._aggregate_sql(metric)
        == expected_sql
    )


@pytest.mark.parametrize(
    ("granularity", "expected"),
    [
        (None, '"created_at"'),
        (
            "day",
            'DATE_TRUNC(\'day\', TRY_CAST("created_at" AS TIMESTAMP))',
        ),
        (
            "week",
            'DATE_TRUNC(\'week\', TRY_CAST("created_at" AS TIMESTAMP))',
        ),
        (
            "month",
            'DATE_TRUNC(\'month\', TRY_CAST("created_at" AS TIMESTAMP))',
        ),
        (
            "quarter",
            'DATE_TRUNC(\'quarter\', TRY_CAST("created_at" AS TIMESTAMP))',
        ),
        (
            "year",
            'DATE_TRUNC(\'year\', TRY_CAST("created_at" AS TIMESTAMP))',
        ),
    ],
)
def test_relationship_group_expression(granularity, expected):
    from app.hypothesis.models import GroupBySpec

    group = GroupBySpec(field="created_at", granularity=granularity)
    assert RelationshipImplementation._group_expression(group) == expected


def test_relationship_reports_pearson_correlation_and_interval():
    sources = FakeSources(correlation_rows())
    implementation = RelationshipImplementation(sources)
    check = RelationshipCheck.model_validate(relationship_payload())

    result = implementation.execute(check)

    assert result["sample_size"] == 4
    assert result["correlation"] == pytest.approx(1.0)
    assert result["p_value"] == pytest.approx(0.0, abs=1e-10)
    assert result["statistically_significant"] is True
    assert result["strength"] == "strong"
    assert result["confidence_interval"] is not None
    assert result["confidence_interval"]["level"] == 0.95
    assert len(result["preview"]) == 4
    assert result["preview"][0]["group"] == {"month": "2026-01"}
    assert sources.queries[0]["row_limit"] == 10_001


def test_relationship_excludes_null_and_non_finite_values():
    rows = correlation_rows() + [
        {"group_0": "2026-05", "x_value": None, "y_value": 10},
        {"group_0": "2026-06", "x_value": float("inf"), "y_value": 12},
    ]
    result = RelationshipImplementation(FakeSources(rows)).execute(
        RelationshipCheck.model_validate(relationship_payload())
    )

    assert result["sample_size"] == 4
    assert result["excluded_groups"] == 2
    assert any("2 groups were excluded" in warning for warning in result["warnings"])


def test_relationship_warns_when_fewer_than_three_valid_groups():
    rows = correlation_rows()[:2]
    result = RelationshipImplementation(FakeSources(rows)).execute(
        RelationshipCheck.model_validate(relationship_payload())
    )

    assert result["sample_size"] == 2
    assert result["correlation"] is None
    assert result["p_value"] is None
    assert result["statistically_significant"] is None
    assert result["confidence_interval"] is None
    assert any("At least 3 valid groups" in w for w in result["warnings"])


def test_relationship_warns_when_metric_has_no_variation():
    rows = [
        {"group_0": str(i), "x_value": 5, "y_value": i}
        for i in range(1, 5)
    ]
    result = RelationshipImplementation(FakeSources(rows)).execute(
        RelationshipCheck.model_validate(relationship_payload())
    )

    assert result["correlation"] is None
    assert result["strength"] == "undefined"
    assert any("no variation" in warning for warning in result["warnings"])


def test_relationship_rejects_more_than_max_groups():
    rows = [
        {"group_0": str(i), "x_value": i, "y_value": i * 2}
        for i in range(RelationshipImplementation.MAX_GROUPS + 1)
    ]
    implementation = RelationshipImplementation(FakeSources(rows))
    check = RelationshipCheck.model_validate(relationship_payload())

    with pytest.raises(ValueError, match="more than 10000 groups"):
        implementation.execute(check)


def test_relationship_limits_preview_size():
    rows = [
        {"group_0": str(i), "x_value": i, "y_value": i * 2}
        for i in range(1, 26)
    ]
    result = RelationshipImplementation(FakeSources(rows)).execute(
        RelationshipCheck.model_validate(relationship_payload())
    )

    assert result["sample_size"] == 25
    assert len(result["preview"]) == RelationshipImplementation.PREVIEW_GROUPS
    assert result["preview_limit"] == 20


def test_relationship_includes_causation_and_time_series_limitations():
    result = RelationshipImplementation(FakeSources(correlation_rows())).execute(
        RelationshipCheck.model_validate(relationship_payload())
    )

    assert any("does not establish causation" in item for item in result["limitations"])
    assert any("autocorrelated" in item for item in result["limitations"])


# ---------------------------------------------------------------------------
# Hypothesis engine
# ---------------------------------------------------------------------------


def test_engine_returns_completed_check_result():
    sources = FakeSources(
        [{"metric_value": 10}],
        [{"metric_value": 15}],
    )
    engine = HypothesisEngine(sources)

    result = engine.run(
        {
            "statement": "Sales increased",
            "checks": [compare_payload()],
        }
    )

    assert result["statement"] == "Sales increased"
    assert result["results"][0]["id"] == "sales-comparison"
    assert result["results"][0]["method"] == "compare"
    assert result["results"][0]["status"] == "completed"
    assert result["results"][0]["data"]["delta"] == 5
    assert result["results"][0]["error"] is None


def test_engine_isolates_errors_between_checks(monkeypatch):
    engine = HypothesisEngine(FakeSources())

    def fail(_check):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(
        engine.implementations["compare"],
        "execute",
        fail,
    )

    result = engine.run(
        {
            "statement": "Run two checks",
            "checks": [
                compare_payload(),
                compare_payload(id="second-comparison"),
            ],
        }
    )

    assert len(result["results"]) == 2
    assert result["results"][0]["status"] == "error"
    assert result["results"][0]["error"] == (
        "RuntimeError: simulated failure"
    )
    assert result["results"][1]["status"] == "error"
    assert result["results"][1]["error"] == (
        "RuntimeError: simulated failure"
    )


def test_engine_rejects_invalid_request_before_execution():
    engine = HypothesisEngine(FakeSources())

    with pytest.raises(ValidationError):
        engine.run(
            {
                "statement": "",
                "checks": [compare_payload()],
            }
        )


def test_engine_continues_after_one_check_fails(monkeypatch):
    engine = HypothesisEngine(FakeSources())
    calls = 0

    def execute(check):
        nonlocal calls
        calls += 1

        if calls == 1:
            raise RuntimeError("simulated failure")

        return {"delta": 5}

    monkeypatch.setattr(
        engine.implementations["compare"],
        "execute",
        execute,
    )

    result = engine.run(
        {
            "statement": "Run two checks",
            "checks": [
                compare_payload(),
                compare_payload(id="second-comparison"),
            ],
        }
    )

    assert result["results"][0]["status"] == "error"
    assert result["results"][1]["status"] == "completed"
    assert result["results"][1]["data"] == {"delta": 5}
