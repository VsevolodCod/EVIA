import json


def test_profile_audit_records_only_metadata_and_full_csv_coverage(tmp_path):
    from scripts.verify_csv_profiles import audit_directory

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    corpus.joinpath("orders.csv").write_bytes(
        b"id,amount\n001,10\n002,patient-secret\n"
    )

    audit = audit_directory(corpus, expected_files=1)

    assert audit["status"] == "accepted"
    assert audit["found_file_count"] == 1
    assert audit["total_runtime_ms"] >= 0
    entry = audit["files"][0]
    assert entry["filename"] == "orders.csv"
    assert len(entry["sha256"]) == 64
    assert entry["source_id"]
    assert entry["snapshot_id"]
    assert entry["accepted_import_rows"] == 2
    assert entry["processed_rows"] == entry["accepted_import_rows"]
    assert entry["coverage"] == "full"
    assert entry["errors"] == []

    serialized = json.dumps(audit, ensure_ascii=False)
    assert "patient-secret" not in serialized
    assert '"columns"' not in serialized
