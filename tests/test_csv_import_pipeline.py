"""Acceptance cases for a lossless, versioned CSV import."""

from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


@pytest.fixture
def service(tmp_path):
    catalog = SchemaCatalog(tmp_path / "catalog.db")
    try:
        yield SourceService(tmp_path / "data", catalog)
    finally:
        catalog.close()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1251"])
def test_supported_encodings_keep_original_bytes_and_rows(service, encoding):
    original = 'Код;Сумма\n001;-120,50\n002;180.5\n'.encode(encoding)
    source = service.register_csv("sales.csv", original)

    assert service.preview(source.source_id) == [
        {"Код": "001", "Сумма": "-120,50"},
        {"Код": "002", "Сумма": "180.5"},
    ]
    assert service.raw_csv_path(source.source_id, source.snapshot_id).read_bytes() == original
    assert source.import_report.encoding == encoding
    assert source.import_report.rows_read == 2
    assert source.import_report.accepted_rows == 2
    assert source.import_report.rejected_rows == 0


def test_excel_sep_directive_is_counted_as_metadata(service):
    source = service.register_csv("excel.csv", b"sep=;\nid;amount\n001;12,50\n")
    assert source.import_report.delimiter == ";"
    assert source.import_report.rows_read == 1
    assert service.get_schema(source.source_id).objects[0].row_count == 1
    assert service.preview(source.source_id) == [{"id": "001", "amount": "12,50"}]


def test_typed_decimal_is_exact_while_raw_id_and_amount_stay_strings(service):
    source = service.register_csv("money.csv", b"id;amount\n001;120,50\n002;-20.25\n003;\n")
    assert service.preview(source.source_id)[0] == {"id": "001", "amount": "120,50"}
    assert source.import_report.typed_sql_types["id"] == "VARCHAR"
    assert source.import_report.typed_sql_types["amount"].startswith("DECIMAL")
    result = service.query(source.source_id, "SELECT SUM(amount) AS total FROM source_typed")
    assert result.rows == [["100.25"]]
    assert result.columns[0].data_type == "decimal"


def test_literal_backslash_zero_and_nul_are_not_silently_changed(service):
    source = service.register_csv("bytes.csv", b"a,b\n1,\\0\n2,\x00\n")
    assert source.import_report.encoding == "utf-8"
    assert source.import_report.accepted_rows == 2
    assert service.preview(source.source_id) == [{"a": "1", "b": "\\0"}, {"a": "2", "b": "\x00"}]


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_bomless_utf16_with_cyrillic_rows_is_detected(service, encoding):
    original = "Название;Категория\nЯблоко;Фрукты\nГруша;Фрукты\n".encode(encoding)
    source = service.register_csv("produce.csv", original)
    assert source.import_report.encoding == encoding
    assert service.preview(source.source_id)[0] == {"Название": "Яблоко", "Категория": "Фрукты"}


def test_header_spacing_is_preserved_and_case_duplicate_is_reported(service):
    source = service.register_csv("spaces.csv", b" a ,b\n1,2\n")
    assert service.preview(source.source_id) == [{" a ": "1", "b": "2"}]
    from app.csv_import import CSVImportError
    with pytest.raises(CSVImportError, match="duplicate column names"):
        service.register_csv("duplicate.csv", b"a,A\n1,2\n")


def test_long_text_and_unicode_digits_remain_importable_as_text(service):
    large = "x" * 131073
    source = service.register_csv("large-cell.csv", f"id,text,number\n1,{large},١٢٣\n".encode())
    assert source.import_report.typed_sql_types["number"] == "VARCHAR"
    assert service.preview(source.source_id)[0] == {"id": "1", "text": large, "number": "١٢٣"}


def test_week_dates_and_offset_timestamps_remain_text(service):
    source = service.register_csv("dates.csv", b"week,instant\n2023-W01-1,2024-01-01T10:00:00+05:00\n")
    assert source.import_report.typed_sql_types == {"week": "VARCHAR", "instant": "VARCHAR"}
    assert service.preview(source.source_id)[0]["instant"].endswith("+05:00")


def test_mixed_tail_and_ambiguous_date_are_explicit_in_full_file_report(service):
    content = b"id;amount;date\n" + b"001;1,50;01.02.2024\n" * 500 + b"501;broken;02.03.2024\n"
    source = service.register_csv("mixed.csv", content)
    fields = {field.name: field.inferred_type for field in service.get_schema(source.source_id).objects[0].fields}
    assert fields["amount"] == "string"
    assert fields["date"] == "string"
    assert any("amount" in warning and "mixed" in warning for warning in source.import_report.warnings)
    assert any("date" in warning and "ambiguous" in warning for warning in source.import_report.warnings)
    assert source.import_report.typed_sql_types["amount"] == "VARCHAR"


def test_bad_row_has_counted_rejection_and_no_published_source(service):
    from app.csv_import import CSVImportError

    with pytest.raises(CSVImportError) as caught:
        service.register_csv("bad.csv", b"id;value\n001;10\n002;20;extra\n")
    report = caught.value.report
    assert report.rows_read == 2
    assert report.accepted_rows == 1
    assert report.rejected_rows == 1
    assert report.rows_read == report.accepted_rows + report.rejected_rows
    assert service.catalog.list_sources() == []


def test_header_only_csv_is_available_with_an_explicit_empty_warning(service):
    source = service.register_csv("empty.csv", b"id;amount\n")
    assert source.import_report.accepted_rows == 0
    assert any("no_data_rows" in warning for warning in source.import_report.warnings)
    assert service.preview(source.source_id) == []


def test_reimport_creates_new_snapshot_and_keeps_previous_original(service):
    first = service.register_csv("sales.csv", b"id;amount\n001;10\n")
    second = service.register_csv("sales.csv", b"id;amount\n001;20\n", source_id=first.source_id)
    assert second.source_id == first.source_id
    assert second.snapshot_id != first.snapshot_id
    assert second.schema_version == first.schema_version + 1
    assert service.raw_csv_path(first.source_id, first.snapshot_id).read_bytes() == b"id;amount\n001;10\n"
    assert service.raw_csv_path(second.source_id, second.snapshot_id).read_bytes() == b"id;amount\n001;20\n"
    assert service.preview(second.source_id) == [{"id": "001", "amount": "20"}]
    assert [version.snapshot_id for version in service.list_csv_versions(first.source_id)] == [first.snapshot_id, second.snapshot_id]


def test_invalid_reimport_leaves_previous_snapshot_and_catalog_untouched(service):
    from app.csv_import import CSVImportError

    first = service.register_csv("sales.csv", b"id;amount\n001;10\n")
    with pytest.raises(CSVImportError):
        service.register_csv("sales.csv", b"id;amount\n001;20;extra\n", source_id=first.source_id)
    current = service.catalog.get_source(first.source_id)
    assert current.snapshot_id == first.snapshot_id
    assert len(service.list_csv_versions(first.source_id)) == 1
    assert service.preview(first.source_id) == [{"id": "001", "amount": "10"}]


def test_stale_reimport_cannot_replace_a_newer_version(service):
    from app.schema_catalog import CatalogConflictError

    first = service.register_csv("sales.csv", b"id;amount\n001;10\n")
    second = service.register_csv("sales.csv", b"id;amount\n001;20\n", source_id=first.source_id)
    with pytest.raises(CatalogConflictError):
        service.catalog.save_source_and_schema(
            first, service.get_schema(first.source_id), expected_snapshot_id=first.snapshot_id,
        )
    assert service.catalog.get_source(first.source_id).snapshot_id == second.snapshot_id
    assert len(service.list_csv_versions(first.source_id)) == 2


def test_concurrent_reimports_do_not_lose_a_successful_snapshot(service, monkeypatch):
    from app.csv_import import CSVImportError

    first = service.register_csv("sales.csv", b"id;amount\n001;10\n")
    monkeypatch.setattr(service.data_engine, "import_csv", lambda *args, **kwargs: None)
    monkeypatch.setattr(service.data_engine, "row_count", lambda *args: 1)
    monkeypatch.setattr(service.data_engine, "discard", lambda *args: None)
    save = service.catalog.save_source_and_schema
    ready = Barrier(2)

    def racing_save(*args, **kwargs):
        ready.wait(timeout=5)
        return save(*args, **kwargs)

    monkeypatch.setattr(service.catalog, "save_source_and_schema", racing_save)

    def reimport(amount):
        try:
            return service.register_csv("sales.csv", f"id;amount\n001;{amount}\n".encode(), source_id=first.source_id)
        except CSVImportError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reimport, (20, 30)))
    successes = [item for item in results if not isinstance(item, CSVImportError)]
    conflicts = [item for item in results if isinstance(item, CSVImportError)]
    assert len(successes) == 1
    assert len(conflicts) == 1 and conflicts[0].status_code == 409
    assert [version.snapshot_id for version in service.list_csv_versions(first.source_id)] == [
        first.snapshot_id, successes[0].snapshot_id,
    ]


def test_upload_size_limit_is_reported_and_cleans_partial_copy(service, monkeypatch):
    from app import csv_import

    monkeypatch.setattr(csv_import, "MAX_CSV_BYTES", 15)
    with pytest.raises(csv_import.CSVImportError) as caught:
        service.register_csv("sales.csv", b"id;amount\n001;120\n")
    assert caught.value.status_code == 413
    assert caught.value.report.size_bytes == 18
    assert service.catalog.list_sources() == []
    assert list(service.data_dir.glob("*.csv")) == []


def test_streaming_upload_does_not_request_the_whole_file_at_once(service):
    class BoundedStream(BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024
            return super().read(size)

    stream = BoundedStream(b"id,value\n001,10\n")
    source = service.register_csv_stream("sales.csv", stream)
    assert source.import_report.size_bytes == len(b"id,value\n001,10\n")
    assert service.preview(source.source_id) == [{"id": "001", "value": "10"}]


def test_missing_typed_table_is_rebuilt_from_raw_even_without_normalized_copy(service):
    source = service.register_csv("sales.csv", b"id;amount\n001;10,50\n")
    with service.data_engine._connect() as connection:
        connection.execute(f'DROP TABLE "{service.data_engine.typed_table_name(source)}"')
    (service.data_dir / source.csv_versions[-1].normalized_filename).unlink()
    result = service.query(source.source_id, "SELECT SUM(amount) AS total FROM source_typed")
    assert result.rows == [["10.50"]]
