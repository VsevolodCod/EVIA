import csv
import json

from app.dataset_audit import audit_csv, audit_directory, write_public_method_report


def write_csv(path, rows, *, encoding="utf-8-sig", delimiter=";"):
    with path.open("w", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerows(rows)


def test_audit_directory_is_repeatable_and_does_not_store_source_values(tmp_path):
    datasets = tmp_path / "datasets"
    datasets.mkdir()
    write_csv(
        datasets / "orders.csv",
        [
            ["order_id", "created_at", "amount", "return_amount", "session_id"],
            ["0001", "2026-10-01", "10,50", "", "session-a"],
            ["0002", "2026-10-02", "-5,00", "-5,00", "session-b"],
        ],
    )
    write_csv(
        datasets / "events.csv",
        [["событие", "attempt_id", "chain_id", "event_time"], ["evt-1", "a-1", "c-1", "12:30:00"]],
        encoding="cp1251",
    )

    first = audit_directory(datasets, expected_files=2)
    second = audit_directory(datasets, expected_files=2)

    assert first == second
    assert first["file_count"] == 2
    orders = next(item for item in first["files"] if item["name"] == "orders.csv")
    assert orders["encoding"] == "utf-8-sig"
    assert orders["delimiter"] == ";"
    assert orders["row_count"] == 2
    assert orders["schema"] == [
        {"name": "order_id", "inferred_type": "string", "null_count": 0},
        {"name": "created_at", "inferred_type": "date", "null_count": 0},
        {"name": "amount", "inferred_type": "decimal_comma", "null_count": 0},
        {"name": "return_amount", "inferred_type": "decimal_comma", "null_count": 1},
        {"name": "session_id", "inferred_type": "string", "null_count": 0},
    ]
    assert {"identifier", "date", "decimal", "return", "session"} <= set(
        orders["semantic_candidates"],
    )
    events = next(item for item in first["files"] if item["name"] == "events.csv")
    assert events["encoding"] == "cp1251"

    serialized = json.dumps(first, ensure_ascii=False)
    assert "0001" not in serialized
    assert "session-a" not in serialized
    assert "10,50" not in serialized


def test_audit_rejects_an_unexpected_number_of_files_and_public_report_has_no_dataset_details(tmp_path):
    datasets = tmp_path / "datasets"
    datasets.mkdir()
    write_csv(datasets / "only.csv", [["id"], ["secret-value"]])

    try:
        audit_directory(datasets, expected_files=9)
    except ValueError as error:
        assert "Expected 9 CSV files, found 1" in str(error)
    else:
        raise AssertionError("expected file-count validation")

    report = write_public_method_report()
    assert "hash" in report
    assert "raw rows" in report
    assert "secret-value" not in report
    assert "only.csv" not in report


def test_audit_finds_a_composite_grain_when_no_single_identifier_is_unique(tmp_path):
    dataset = tmp_path / "pharmacy.csv"
    write_csv(
        dataset,
        [
            ["Дата", "ID_Аптеки", "ID_Лекарства", "Количество"],
            ["2026-10-01", "1", "10", "3"],
            ["2026-10-01", "1", "11", "2"],
            ["2026-10-01", "2", "10", "4"],
            ["2026-10-01", "2", "11", "5"],
            ["2026-10-02", "1", "10", "6"],
            ["2026-10-02", "1", "11", "7"],
            ["2026-10-02", "2", "10", "8"],
            ["2026-10-02", "2", "11", "9"],
        ],
    )

    result = audit_csv(dataset)

    assert result["candidate_grain_keys"] == []
    assert result["candidate_composite_grain_keys"] == [["Дата", "ID_Аптеки", "ID_Лекарства"]]
