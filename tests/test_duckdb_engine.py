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

    table = engine.table_name(source)
    assert engine.preview(source, 2) == [
        {"Код товара": "001", "Сумма, руб.": "10,50"},
        {"Код товара": "002", "Сумма, руб.": "20,00"},
    ]
    assert engine.query(source, f'''SELECT COUNT(*) AS "count", SUM(TRY_CAST(REPLACE("Сумма, руб.", ',', '.') AS DOUBLE)) AS "total" FROM "{table}"''') == [
        {"count": 2, "total": 30.5},
    ]

    reopened = DuckDBDataEngine(tmp_path / "analytics.duckdb")
    assert reopened.query(source, f'SELECT COUNT(*) AS "count" FROM "{table}"') == [{"count": 2}]


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
        ) == [{"count": 2, "total": 30}]
    finally:
        catalog.close()

    reopened_catalog = SchemaCatalog(catalog_path)
    try:
        reopened = SourceService(tmp_path / "csv", reopened_catalog)
        assert reopened.query(
            source.source_id,
            f'SELECT COUNT(*) AS "count" FROM "{reopened.data_engine.table_name(source)}"',
        ) == [{"count": 2}]
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
    assert engine.query(first, f'SELECT "value" FROM "{engine.table_name(first)}"') == [{"value": "1"}]
    assert engine.query(second, f'SELECT "value" FROM "{engine.table_name(second)}"') == [{"value": "2"}]

    csv_path.write_text("id,value\n1\n", encoding="utf-8")
    failed = first.model_copy(update={"snapshot_id": "failed"})
    with pytest.raises(Exception):
        engine.import_csv(failed, csv_path, delimiter=",")

    assert not engine.has_table(failed)
    assert engine.query(first, f'SELECT "value" FROM "{engine.table_name(first)}"') == [{"value": "1"}]


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
