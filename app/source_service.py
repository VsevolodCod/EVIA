import csv
import io
import uuid
from pathlib import Path
from typing import Any

from app.data_sources.csv_adapter import CSVAdapter
from app.data_sources.csv_format import PARSER_VERSION, csv_reader, read_header
from app.models import DataSource, SourceSchema
from app.schema_catalog import SchemaCatalog


class SourceService:
    def __init__(
        self,
        data_dir: Path,
        catalog: SchemaCatalog,
    ) -> None:

        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.catalog = catalog
        self.csv_adapter = CSVAdapter(self.data_dir)

    def register_csv(
        self,
        filename: str,
        content: bytes,
        name: str | None = None,
    ) -> DataSource:

        if not filename.lower().endswith(".csv"):
            raise ValueError("Only CSV files are supported")

        if not content:
            raise ValueError("Uploaded CSV is empty")

        try:
            text = content.decode("utf-8-sig")
            reader = csv_reader(io.StringIO(text, newline=''))
            read_header(reader)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError("CSV must be valid UTF-8") from exc

        source_id = uuid.uuid4().hex
        source_name = (
            name or Path(filename).stem or "uploaded_csv"
        ).strip()[:120]

        source = DataSource(
            source_id=source_id,
            name=source_name,
            source_type="csv",
            status="available",
        )

        target = (self.data_dir / f"{source_id}.csv").resolve()

        if target.parent != self.data_dir:
            raise ValueError("Invalid target path")

        target.write_bytes(content)

        try:
            schema = self.csv_adapter.introspect_schema(source)
            source.schema_version = schema.version

            self.catalog.upsert_source(source)
            self.catalog.save_schema(schema)

        except (csv.Error, UnicodeDecodeError) as exc:
            target.unlink(missing_ok=True)
            raise ValueError('CSV contains invalid encoding or quoting') from exc
        except Exception:
            target.unlink(missing_ok=True)
            raise

        return source

    def get_schema(self, source_id: str) -> SourceSchema:
        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        schema = self.catalog.get_schema(source_id)

        if schema is None or schema.parser_version < PARSER_VERSION:
            if schema is not None:
                source.schema_version = max(source.schema_version, schema.version) + 1
            schema = self.csv_adapter.introspect_schema(source)
            self.catalog.save_schema(schema)
            self.catalog.upsert_source(source)

        return schema

    def preview(
        self,
        source_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:

        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        return self.csv_adapter.preview(source, source.name, limit)

    def profile(self, source_id: str) -> dict[str, Any]:
        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        return self.csv_adapter.profile(source, source.name)
