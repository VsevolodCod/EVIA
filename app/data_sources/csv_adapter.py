import csv
from itertools import islice
from pathlib import Path
from typing import Any

from app.data_sources.base import DataSourceAdapter
from app.data_sources.csv_format import PARSER_VERSION, csv_reader, read_header, checked_rows
from app.models import (
    DataSource,
    SchemaField,
    SchemaObject,
    SourceSchema,
)


def infer_type(values: list[str]) -> str:
    values = [
        value.strip()
        for value in values
        if value is not None and value.strip()
    ]

    if not values:
        return "unknown"

    if all(v.lower() in {"true", "false", "yes", "no"} for v in values):
        return "boolean"

    # Ведущие нули часто означают, что это идентификатор.
    # Не преобразуем такие значения в числа.
    if all(v.isdigit() for v in values):
        if any(len(v) > 1 and v.startswith("0") for v in values):
            return "string"
        return "integer"

    try:
        for value in values:
            float(value.replace(',', '.'))
        return "number"
    except ValueError:
        return "string"


class CSVAdapter(DataSourceAdapter):
    """
    Контракт для взаимодействия с CSV
    """
    def __init__(
        self,
        storage_dir: Path,
        sample_size: int = 500,
    ) -> None:

        self.storage_dir = storage_dir.resolve()
        self.sample_size = sample_size

    def _path(self, source: DataSource) -> Path:
        filename = source.csv_versions[-1].raw_filename if source.csv_versions else f"{source.source_id}.csv"
        path = (self.storage_dir / filename).resolve()

        if path.parent != self.storage_dir:
            raise ValueError("Invalid source path")

        return path

    def test_connection(self, source: DataSource) -> tuple[bool, str]:
        if self._path(source).is_file():
            return True, "CSV file is available"

        return False, "CSV file not found"

    def _read_sample(
        self,
        source: DataSource,
    ) -> tuple[list[str], list[dict[str, str]]]:

        path = self._path(source)

        if not path.is_file():
            raise FileNotFoundError(
                f"Source file not found: {source.source_id}"
            )

        encoding = source.import_report.encoding if source.import_report else "utf-8-sig"
        with path.open("r", encoding=encoding, newline="") as file:
            reader = csv_reader(file)
            headers = read_header(reader)
            rows = list(islice(checked_rows(reader, headers), self.sample_size))

        return headers, rows

    def _count_rows(self, source: DataSource) -> int:
        if source.import_report is not None:
            return source.import_report.accepted_rows
        with self._path(source).open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv_reader(file)
            header = read_header(reader)
            return sum(1 for _ in checked_rows(reader, header))

    def introspect_schema(self, source: DataSource) -> SourceSchema:
        headers, rows = self._read_sample(source)
        fields = []

        for header in headers:
            values = [row.get(header, "") or "" for row in rows]
            nonempty = [v for v in values if v.strip()]

            unique_ratio = (
                len(set(nonempty)) / len(nonempty)
                if nonempty
                else 0.0
            )

            report = source.import_report
            fields.append(
                SchemaField(
                    name=header,
                    inferred_type=report.column_types.get(header, infer_type(values)) if report else infer_type(values),
                    nullable=(
                        report.column_nullable.get(header) if report else
                        (any(not v.strip() for v in values) if values else None)
                    ),
                    is_identifier_candidate=(
                        len(nonempty) >= 2 and unique_ratio >= 0.95
                    ),
                )
            )

        return SourceSchema(
            source_id=source.source_id,
            parser_version=PARSER_VERSION,
            version=source.schema_version,
            objects=[
                SchemaObject(
                    object_id=f"{source.source_id}:table",
                    name=source.name,
                    object_type="csv_table",
                    fields=fields,
                    row_count=self._count_rows(source),
                )
            ],
        )

    def preview(
        self,
        source: DataSource,
        object_name: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        if object_name not in {
            source.name,
            f"{source.source_id}:table",
            "table",
        }:
            raise ValueError(f"Unknown object: {object_name}")

        headers, rows = self._read_sample(source)
        return [
            {header: row.get(header) for header in headers}
            for row in rows[:limit]
        ]

    def profile(
        self,
        source: DataSource,
        object_name: str,
    ) -> dict[str, Any]:
        if object_name not in {
            source.name,
            f"{source.source_id}:table",
            "table",
        }:
            raise ValueError(f"Unknown object: {object_name}")

        headers, rows = self._read_sample(source)
        columns = {}

        for header in headers:
            values = [row.get(header, "") or "" for row in rows]
            nonempty = [v for v in values if v.strip()]

            counts: dict[str, int] = {}
            for value in nonempty:
                counts[value] = counts.get(value, 0) + 1

            top_values = sorted(
                counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:5]

            columns[header] = {
                "sample_non_null_count": len(nonempty),
                "sample_null_count": len(values) - len(nonempty),
                "distinct_sample_values": len(set(nonempty)),
                "top_values": [
                    {"value": value, "count": count}
                    for value, count in top_values
                ],
            }

        return {
            "sample_size": len(rows),
            "sample_limit": self.sample_size,
            "columns": columns,
            "note": (
                "Column statistics use a bounded sample. "
                "The reported row count from schema introspection is exact."
            ),
        }
