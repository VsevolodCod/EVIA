from app.data_sources.csv_adapter import CSVAdapter
from app.models import DataSource


def test_schema_inference_and_identifiers(tmp_path):
    source = DataSource(
        source_id="test123",
        name="sales",
        source_type="csv",
    )

    (tmp_path / "test123.csv").write_text(
        "user_id,revenue\n"
        "001,10\n"
        "002,20\n",
        encoding="utf-8",
    )

    adapter = CSVAdapter(tmp_path)
    schema = adapter.introspect_schema(source)

    fields = {
        field.name: field
        for field in schema.objects[0].fields
    }

    assert fields["user_id"].inferred_type == "string"
    assert fields["user_id"].is_identifier_candidate
    assert fields["revenue"].inferred_type == "integer"
    assert schema.objects[0].row_count == 2


def test_preview_respects_limit(tmp_path):
    source = DataSource(
        source_id="test123",
        name="sales",
        source_type="csv",
    )

    (tmp_path / "test123.csv").write_text(
        "id\n1\n2\n3\n",
        encoding="utf-8",
    )

    adapter = CSVAdapter(tmp_path)

    result = adapter.preview(
        source,
        object_name="sales",
        limit=2,
    )

    assert len(result) == 2
