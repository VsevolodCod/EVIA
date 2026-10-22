from app.models import DataSource


def test_imported_csv_is_available_for_analytics_and_survives_reopen(tmp_path):
    from app.data_engine import DuckDBDataEngine

    source = DataSource(
        source_id="sales-source",
        snapshot_id="snapshot-sales",
        name="Продажи за октябрь",
        source_type="csv",
        status="importing",
    )
    csv_path = tmp_path / "sales-source.csv"
    csv_path.write_text(
        "Код товара;Сумма, руб.\n001;10,50\n002;20,00\n",
        encoding="utf-8",
    )

    engine = DuckDBDataEngine(tmp_path / "analytics.duckdb")
    engine.import_csv(source, csv_path, delimiter=";")

    assert engine.preview(source, 2) == [
        {"Код товара": "001", "Сумма, руб.": "10,50"},
        {"Код товара": "002", "Сумма, руб.": "20,00"},
    ]
    reopened = DuckDBDataEngine(tmp_path / "analytics.duckdb")
    assert reopened.preview(source, 2) == [
        {"Код товара": "001", "Сумма, руб.": "10,50"},
        {"Код товара": "002", "Сумма, руб.": "20,00"},
    ]


def test_source_service_publishes_only_ready_duckdb_snapshot(tmp_path):
    from app.schema_catalog import SchemaCatalog
    from app.source_service import SourceService

    catalog_path = tmp_path / "catalog.db"
    catalog = SchemaCatalog(catalog_path)
    try:
        service = SourceService(tmp_path / "csv", catalog)
        source = service.register_csv(
            "sales.csv", b'id;revenue\n001;10\n002;20\n', name="Продажи"
        )
        assert source.status == "available"
        assert source.snapshot_id
        assert service.preview(source.source_id) == [
            {"id": "001", "revenue": "10"},
            {"id": "002", "revenue": "20"},
        ]
        assert service.query(
            source.source_id,
            f'SELECT COUNT(*) AS "count", SUM(TRY_CAST("revenue" AS BIGINT)) AS "total" '
            f'FROM "{service.data_engine.table_name(source)}"',
        ).rows == [[2, 30]]
    finally:
        catalog.close()

    reopened_catalog = SchemaCatalog(catalog_path)
    try:
        reopened = SourceService(tmp_path / "csv", reopened_catalog)
        assert reopened.query(
            source.source_id,
            f'SELECT COUNT(*) AS "count" FROM "{reopened.data_engine.table_name(source)}"',
        ).rows == [[2]]
    finally:
        reopened_catalog.close()


def test_existing_catalog_source_is_materialized_on_first_use(tmp_path):
    from app.schema_catalog import SchemaCatalog
    from app.source_service import SourceService

    catalog = SchemaCatalog(tmp_path / "catalog.db")
    try:
        service = SourceService(tmp_path / "csv", catalog)
        source = service.register_csv("sales.csv", b"id,value\n001,7\n")
    finally:
        catalog.close()

    (tmp_path / "csv" / "analytics.duckdb").unlink()
    repaired_catalog = SchemaCatalog(tmp_path / "catalog.db")
    try:
        repaired = SourceService(tmp_path / "csv", repaired_catalog)
        assert repaired.preview(source.source_id) == [{"id": "001", "value": "7"}]
        assert repaired_catalog.get_source(source.source_id).snapshot_id == source.snapshot_id
    finally:
        repaired_catalog.close()


def test_snapshots_with_one_source_id_are_immutable_and_isolated(tmp_path):
    import pytest

    from app.data_engine import DuckDBDataEngine

    engine = DuckDBDataEngine(tmp_path / "analytics.duckdb")
    first = DataSource(
        source_id="sales", snapshot_id="first", name="sales", source_type="csv"
    )
    second = first.model_copy(update={"snapshot_id": "second"})
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("value\n1\n", encoding="utf-8")
    engine.import_csv(first, csv_path, delimiter=",")
    csv_path.write_text("value\n2\n", encoding="utf-8")
    engine.import_csv(second, csv_path, delimiter=",")

    assert engine.table_name(first) != engine.table_name(second)
    assert engine.preview(first, 1) == [{"value": "1"}]
    assert engine.preview(second, 1) == [{"value": "2"}]

    csv_path.write_text("id,value\n1\n", encoding="utf-8")
    failed = first.model_copy(update={"snapshot_id": "failed"})
    with pytest.raises(Exception):
        engine.import_csv(failed, csv_path, delimiter=",")

    assert not engine.has_table(failed)
    assert engine.preview(first, 1) == [{"value": "1"}]


def test_legacy_catalog_source_receives_snapshot_before_materialization(tmp_path):
    from app.schema_catalog import SchemaCatalog
    from app.source_service import SourceService

    source = DataSource(
        source_id="legacy-sales",
        name="Legacy sales",
        source_type="csv",
        status="available",
    )
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    try:
        catalog.upsert_source(source)
        csv_dir = tmp_path / "csv"
        csv_dir.mkdir()
        (csv_dir / f"{source.source_id}.csv").write_text(
            "id,value\n001,7\n", encoding="utf-8"
        )
        service = SourceService(csv_dir, catalog)
        assert service.preview(source.source_id) == [{"id": "001", "value": "7"}]
        repaired = catalog.get_source(source.source_id)
        assert repaired is not None and repaired.snapshot_id
        assert service.data_engine.has_table(repaired)
    finally:
        catalog.close()


def test_profile_calculates_full_snapshot_statistics_and_typed_blocks(tmp_path):
    from app.contracts.v1 import Profile
    from app.data_engine import DuckDBDataEngine
    from app.models import ImportReport

    null_value = "__EVIA_NULL_profile-sha__"
    source = DataSource(
        source_id="profile-source",
        snapshot_id="profile-snapshot",
        name="Profile source",
        source_type="csv",
        import_report=ImportReport(
            sha256="profile-sha",
            typed_sql_types={
                "unique_id": "VARCHAR",
                "non_unique_id": "VARCHAR",
                "label": "VARCHAR",
                "amount": "DECIMAL(38,2)",
                "day": "DATE",
            },
        ),
    )
    csv_path = tmp_path / "profile.csv"
    csv_path.write_text(
        "unique_id;non_unique_id;label;amount;day\n"
        "id-1;repeat;alpha;10,50;2026-01-20\n"
        "id-2;repeat;;0,00;2026-01-01\n"
        f"id-3;tail;{null_value};5,25;2026-01-10\n"
        "id-4;tail;beta;4,00;2026-02-02\n"
        "id-5;tail;gamma;4,00;2026-01-15\n",
        encoding="utf-8",
    )
    engine = DuckDBDataEngine(tmp_path / "analytics.duckdb")
    engine.import_csv(source, csv_path, delimiter=";", typed_sql_types=source.import_report.typed_sql_types)

    profile = engine.profile(source, sample_size=2)

    Profile.model_validate(profile)
    assert profile["processed_rows"] == 5
    assert profile["coverage"] == "full"
    assert profile["snapshot_id"] == "profile-snapshot"
    assert profile["sample_size"] == 2
    assert profile["sample_limit"] == 2
    assert profile["columns"]["unique_id"]["distinct_count"] == 5
    assert profile["columns"]["unique_id"]["is_identifier_candidate"] is True
    assert profile["columns"]["non_unique_id"]["is_identifier_candidate"] is False
    assert profile["columns"]["label"] == {
        "sample_non_null_count": 1,
        "sample_null_count": 1,
        "distinct_sample_values": 1,
        "top_values": [{"value": "alpha", "count": 1}],
        "top_values_coverage": "sample",
        "non_null_count": 4,
        "null_count": 1,
        "empty_count": 1,
        "distinct_count": 4,
        "uniqueness_ratio": 1.0,
        "is_identifier_candidate": False,
        "numeric": None,
        "temporal": None,
    }
    assert profile["columns"]["non_unique_id"]["top_values"] == [{"value": "repeat", "count": 2}]
    assert profile["columns"]["amount"]["numeric"] == {
        "count": 5,
        "minimum": "0.00",
        "maximum": "10.50",
        "total": "23.75",
        "average": "4.75",
    }
    assert profile["columns"]["day"]["temporal"] == {
        "count": 5,
        "minimum": "2026-01-01",
        "maximum": "2026-02-02",
    }


def test_profile_for_legacy_raw_import_is_a_complete_text_only_payload(tmp_path):
    from app.contracts.v1 import Profile
    from app.data_engine import DuckDBDataEngine

    source = DataSource(
        source_id="legacy-profile-source",
        name="Legacy profile source",
        source_type="csv",
    )
    csv_path = tmp_path / "legacy-profile.csv"
    csv_path.write_text("id,text\n1,\n2,value\n", encoding="utf-8")
    engine = DuckDBDataEngine(tmp_path / "analytics.duckdb")
    engine.import_csv(source, csv_path, delimiter=",")

    profile = engine.profile(source, sample_size=10)

    Profile.model_validate(profile)
    assert profile["snapshot_id"] == "legacy"
    assert profile["sample_size"] == 2
    assert profile["sample_limit"] == 10
    assert profile["columns"]["id"]["numeric"] is None
    assert profile["columns"]["id"]["temporal"] is None
    assert profile["columns"]["text"]["non_null_count"] == 2
    assert profile["columns"]["text"]["null_count"] == 0
    assert profile["columns"]["text"]["empty_count"] == 1
