import csv
import io
import uuid
from pathlib import Path
from typing import Any

from app.data_sources.csv_adapter import CSVAdapter
from app.data_sources.csv_format import (
    PARSER_VERSION,
    SAMPLE_CHARS,
    csv_reader,
    detect_delimiter,
    read_header,
)
from app.data_engine import DuckDBDataEngine
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
        self.data_engine = DuckDBDataEngine(self.data_dir / "analytics.duckdb")

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
            snapshot_id=uuid.uuid4().hex,
            name=source_name,
            source_type="csv",
            status="importing",
        )

        target = (self.data_dir / f"{source_id}.csv").resolve()

        if target.parent != self.data_dir:
            raise ValueError("Invalid target path")

        target.write_bytes(content)

        try:
            # Validate the complete file before publishing it to DuckDB.  A
            # malformed tail therefore cannot leave a table that looks ready.
            schema = self.csv_adapter.introspect_schema(source)
            self.data_engine.import_csv(
                source,
                target,
                delimiter=detect_delimiter(text),
            )
            source.schema_version = schema.version
            source.status = "available"

            self.catalog.upsert_source(source)
            self.catalog.save_schema(schema)

        except (csv.Error, UnicodeDecodeError) as exc:
            self.data_engine.discard(source)
            target.unlink(missing_ok=True)
            raise ValueError('CSV contains invalid encoding or quoting') from exc
        except ValueError:
            self.data_engine.discard(source)
            target.unlink(missing_ok=True)
            raise
        except Exception:
            self.data_engine.discard(source)
            target.unlink(missing_ok=True)
            raise

        return source

    def get_schema(self, source_id: str) -> SourceSchema:
        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        source = self._ensure_materialized(source)

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

        source = self._ensure_materialized(source)
        return self.data_engine.preview(source, limit)

    def profile(self, source_id: str) -> dict[str, Any]:
        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        source = self._ensure_materialized(source)
        return self.data_engine.profile(source, self.csv_adapter.sample_size)

    def query(self, source_id: str, sql: str) -> list[dict[str, Any]]:
        """Execute internal analytical SQL for a ready CSV snapshot.

        This is deliberately not exposed as an API/tool before #9 adds the
        read-only guard, table allowlist and resource limits.
        """
        source = self.catalog.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        source = self._ensure_materialized(source)
        if source.status != "available":
            raise ValueError("Source is not ready for analytics")
        return self.data_engine.query(source, sql)

    def _ensure_materialized(self, source: DataSource) -> DataSource:
        """Repair pre-DuckDB catalog entries from their retained CSV artifact."""
        if self.data_engine.has_table(source):
            return source
        if source.status != "available":
            raise ValueError("Source is not ready for analytics")

        path = self.csv_adapter._path(source)
        if not path.is_file():
            raise FileNotFoundError(f"Source file not found: {source.source_id}")
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            text = csv_file.read(SAMPLE_CHARS)
        assigned_snapshot = source.snapshot_id is None
        if assigned_snapshot:
            # The physical table is keyed by snapshot_id, so legacy records
            # must receive it before their first materialization.
            source.snapshot_id = uuid.uuid4().hex
        self.data_engine.import_csv(
            source,
            path,
            delimiter=detect_delimiter(text),
        )
        if assigned_snapshot:
            self.catalog.upsert_source(source)
        return source
