import csv
import io
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import ValidationError

from app.data_sources.csv_adapter import CSVAdapter
from app.data_sources.csv_format import (
    PARSER_VERSION,
    SAMPLE_CHARS,
    detect_delimiter,
)
from app.data_engine import DuckDBDataEngine
from app.csv_import import CSVImportError, ImportReport, copy_original, scan_csv
from app.data_sources.postgresql_adapter import PostgreSQLAdapter
from app.contracts.v1 import Profile, Provenance, QueryResult
from app.models import CSVVersion, DataSource, SourceSchema, utc_now
from app.profile_cache import ProfileCache
from app.safe_sql import SafeQueryExecutor
from app.schema_catalog import CatalogConflictError, SchemaCatalog


class SourceService:
    def __init__(
        self,
        data_dir: Path,
        catalog: SchemaCatalog,
        *,
        postgres_adapter: PostgreSQLAdapter | None = None,
    ) -> None:

        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.catalog = catalog
        self.csv_adapter = CSVAdapter(self.data_dir)
        self.data_engine = DuckDBDataEngine(self.data_dir / "analytics.duckdb")
        self.sql_executor = SafeQueryExecutor(self.data_engine.database_path)
        self.postgres_adapter = postgres_adapter
        self._profile_cache = ProfileCache()

    def register_postgresql_sources(self) -> list[DataSource]:
        """Discover configured live PostgreSQL tables and cache non-secret metadata."""
        if self.postgres_adapter is None:
            return []
        sources = self.postgres_adapter.discover()
        for source in sources:
            self.catalog.upsert_source(source)
            self.catalog.save_schema(self.postgres_adapter.introspect_schema(source))
        return sources

    def list_sources(self) -> list[DataSource]:
        """Return catalog sources that are usable under the current configuration."""
        sources = self.catalog.list_sources()
        if self.postgres_adapter is None:
            return [source for source in sources if source.source_type != "postgresql"]

        allowed_tables = self.postgres_adapter.settings.allowed_tables
        return [
            source
            for source in sources
            if source.source_type != "postgresql"
            or (source.schema_name, source.table_name) in allowed_tables
        ]

    def register_csv(
        self,
        filename: str,
        content: bytes,
        name: str | None = None,
        source_id: str | None = None,
    ) -> DataSource:
        return self.register_csv_stream(filename, io.BytesIO(content), name=name, source_id=source_id)

    def register_csv_stream(
        self,
        filename: str,
        stream: BinaryIO,
        name: str | None = None,
        source_id: str | None = None,
    ) -> DataSource:

        if not filename.lower().endswith(".csv"):
            raise ValueError("Only CSV files are supported")

        previous = self.catalog.get_source(source_id) if source_id else None
        if source_id and (previous is None or previous.source_type != "csv"):
            raise ValueError("CSV source for reimport was not found")
        source_id = source_id or uuid.uuid4().hex
        snapshot_id = uuid.uuid4().hex
        source_name = (
            name or (previous.name if previous else None) or Path(filename).stem or "uploaded_csv"
        ).strip()[:120]

        if previous:
            source = previous.model_copy(deep=True)
            source.snapshot_id = snapshot_id
            source.schema_version += 1
            source.name = source_name
            source.status = "importing"
            if not source.csv_versions and previous.snapshot_id:
                source.csv_versions.append(CSVVersion(
                    snapshot_id=previous.snapshot_id,
                    raw_filename=f"{source_id}.csv",
                    normalized_filename=f"{source_id}.csv",
                    report=previous.import_report or ImportReport(),
                ))
        else:
            source = DataSource(
                source_id=source_id,
                snapshot_id=snapshot_id,
                name=source_name,
                source_type="csv",
                status="importing",
            )
        raw_filename = f"{source_id}.csv" if previous is None else f"{source_id}.{snapshot_id}.csv"
        normalized_filename = f"{source_id}.{snapshot_id}.normalized.csv"
        target = self.data_dir / raw_filename
        normalized = self.data_dir / normalized_filename

        report: ImportReport | None = None
        try:
            report = scan_csv(target, normalized, copy_original(stream, target))
            source.import_report = report
            source.csv_versions.append(CSVVersion(
                snapshot_id=snapshot_id,
                raw_filename=raw_filename,
                normalized_filename=normalized_filename,
                report=report,
            ))
            schema = self.csv_adapter.introspect_schema(source)
            self.data_engine.import_csv(
                source,
                normalized,
                delimiter=",",
                typed_sql_types=report.typed_sql_types,
            )
            if self.data_engine.row_count(source) != report.accepted_rows:
                raise CSVImportError("Imported row count does not match validated CSV", report)
            source.schema_version = schema.version
            source.status = "available"

            self.catalog.save_source_and_schema(
                source, schema, expected_snapshot_id=previous.snapshot_id if previous else None,
            )

        except Exception as exc:
            self.data_engine.discard(source)
            target.unlink(missing_ok=True)
            normalized.unlink(missing_ok=True)
            if isinstance(exc, CatalogConflictError):
                raise CSVImportError("CSV source changed during import; retry with the latest version",
                                     report or ImportReport(), status_code=409) from exc
            raise

        return source

    def list_csv_versions(self, source_id: str) -> list[CSVVersion]:
        source = self.catalog.get_source(source_id)
        if source is None or source.source_type != "csv":
            raise KeyError(f"Unknown CSV source: {source_id}")
        return source.csv_versions

    def raw_csv_path(self, source_id: str, snapshot_id: str | None = None) -> Path:
        source = self.catalog.get_source(source_id)
        if source is None or source.source_type != "csv":
            raise KeyError(f"Unknown CSV source: {source_id}")
        if snapshot_id is None:
            snapshot_id = source.snapshot_id
        version = next((item for item in source.csv_versions if item.snapshot_id == snapshot_id), None)
        if version is None and (source.csv_versions or snapshot_id != source.snapshot_id):
            raise KeyError(f"Unknown CSV snapshot: {snapshot_id}")
        filename = version.raw_filename if version else f"{source_id}.csv"
        path = (self.data_dir / filename).resolve()
        if path.parent != self.data_dir:
            raise ValueError("Invalid source path")
        return path

    def get_schema(self, source_id: str) -> SourceSchema:
        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        if source.source_type == "postgresql":
            if self.postgres_adapter is None:
                raise ValueError("PostgreSQL source is not configured")
            schema = self.postgres_adapter.introspect_schema(source)
            self.catalog.save_schema(schema)
            return schema

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

        if source.source_type == "postgresql":
            if self.postgres_adapter is None:
                raise ValueError("PostgreSQL source is not configured")
            return self.postgres_adapter.preview(source, limit=limit)

        source = self._ensure_materialized(source)
        return self.data_engine.preview(source, limit)

    def profile(self, source_id: str) -> dict[str, Any]:
        source = self.catalog.get_source(source_id)

        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        if source.source_type == "postgresql":
            if self.postgres_adapter is None:
                raise ValueError("PostgreSQL source is not configured")
            profile = self.postgres_adapter.profile(source)
            try:
                return Profile.model_validate(profile).model_dump(mode="json")
            except ValidationError:
                return Profile.model_validate(
                    self._sampled_postgresql_profile(profile)
                ).model_dump(mode="json")

        source = self._ensure_materialized(source)
        sample_size = self.csv_adapter.sample_size
        # CSV snapshots are immutable. Reimports, schema changes and sampling
        # changes get different keys. Live PostgreSQL deliberately bypasses this.
        key = (source.source_id, source.snapshot_id, source.schema_version, PARSER_VERSION, sample_size)

        def compute():
            profile = Profile.model_validate(
                self.data_engine.profile(source, sample_size)
            ).model_dump(mode="json")
            if profile.get("snapshot_id") != source.snapshot_id:
                raise ValueError("Profile does not match the requested CSV snapshot")
            return profile

        return self._profile_cache.get_or_compute(key, compute)

    @staticmethod
    def _sampled_postgresql_profile(profile: dict[str, Any]) -> dict[str, Any]:
        """Make the legacy bounded PostgreSQL sample explicit without mutating its source."""
        sample_size = profile.get("sample_size", 0)
        if not isinstance(sample_size, int) or sample_size < 0:
            sample_size = 0
        sample_limit = profile.get("sample_limit", sample_size or 1)
        if not isinstance(sample_limit, int) or sample_limit < 1:
            sample_limit = max(sample_size, 1)

        columns: dict[str, dict[str, Any]] = {}
        raw_columns = profile.get("columns", {})
        if isinstance(raw_columns, dict):
            for name, raw_column in raw_columns.items():
                column = raw_column if isinstance(raw_column, dict) else {}
                non_null_count = SourceService._nonnegative_int(
                    column.get("sample_non_null_count"), default=0
                )
                null_count = SourceService._nonnegative_int(
                    column.get("sample_null_count"), default=0
                )
                distinct_count = SourceService._nonnegative_int(
                    column.get("distinct_sample_values"), default=0
                )
                top_values = column.get("top_values", [])
                columns[str(name)] = {
                    "sample_non_null_count": non_null_count,
                    "sample_null_count": null_count,
                    "distinct_sample_values": distinct_count,
                    "top_values": top_values if isinstance(top_values, list) else [],
                }

        note = profile.get("note")
        return {
            "sample_size": sample_size,
            "sample_limit": sample_limit,
            "coverage": "sample",
            "columns": columns,
            "note": note if isinstance(note, str) else "Column statistics use a bounded sample.",
        }

    @staticmethod
    def _nonnegative_int(value: Any, *, default: int) -> int:
        return value if isinstance(value, int) and value >= 0 else default

    def query(
        self,
        source_id: str,
        sql: str,
        *,
        row_limit: int | None = None,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        """Run one guarded analytical query against one ready snapshot."""
        source = self.catalog.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        if source.source_type == "postgresql":
            if self.postgres_adapter is None:
                raise ValueError("PostgreSQL source is not configured")
            return self.postgres_adapter.query(source, sql, row_limit=row_limit)
        source = self._ensure_materialized(source)
        if source.status != "available":
            raise ValueError("Source is not ready for analytics")
        return self.sql_executor.execute(
            sql,
            allowed_tables={
                "source": self.data_engine.table_name(source),
                **({"source_typed": self.data_engine.typed_table_name(source)} if source.import_report else {}),
                self.data_engine.table_name(source): self.data_engine.table_name(source),
                **({self.data_engine.typed_table_name(source): self.data_engine.typed_table_name(source)} if source.import_report else {}),
            },
            provenance=Provenance(
                source_id=source.source_id,
                snapshot_id=source.snapshot_id or "legacy",
                schema_version=source.schema_version,
                tool_name="query_data",
                executed_at=utc_now(),
            ),
            row_limit=row_limit,
            timeout_seconds=timeout_seconds,
        )

    def _ensure_materialized(self, source: DataSource) -> DataSource:
        """Repair pre-DuckDB catalog entries from their retained CSV artifact."""
        raw_ready = self.data_engine.has_table(source)
        typed_ready = not source.import_report or self.data_engine.has_typed_table(source)
        if raw_ready and typed_ready:
            return source
        if source.status != "available":
            raise ValueError("Source is not ready for analytics")
        if raw_ready and source.import_report:
            self.data_engine.repair_typed_table(source, source.import_report.typed_sql_types)
            return source

        path = self.csv_adapter._path(source)
        if not path.is_file():
            raise FileNotFoundError(f"Source file not found: {source.source_id}")
        if source.csv_versions:
            normalized = self.data_dir / source.csv_versions[-1].normalized_filename
            import_path = normalized
            delimiter = ","
        else:
            with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
                text = csv_file.read(SAMPLE_CHARS)
            import_path = path
            delimiter = detect_delimiter(text)
        assigned_snapshot = source.snapshot_id is None
        if assigned_snapshot:
            # The physical table is keyed by snapshot_id, so legacy records
            # must receive it before their first materialization.
            source.snapshot_id = uuid.uuid4().hex
        self.data_engine.import_csv(
            source,
            import_path,
            delimiter=delimiter,
            typed_sql_types=source.import_report.typed_sql_types if source.import_report else None,
        )
        if assigned_snapshot:
            self.catalog.upsert_source(source)
        return source
