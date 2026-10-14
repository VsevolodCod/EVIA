import sqlite3
from pathlib import Path

from app.models import DataSource, SourceSchema


class SchemaCatalog:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS schemas (
                    source_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def upsert_source(self, source: DataSource) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO sources(source_id, payload)
                VALUES (?, ?)
                ON CONFLICT(source_id)
                DO UPDATE SET payload = excluded.payload
                """,
                (source.source_id, source.model_dump_json()),
            )

    def get_source(self, source_id: str) -> DataSource | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()

        if row is None:
            return None

        return DataSource.model_validate_json(row["payload"])

    def list_sources(self) -> list[DataSource]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM sources ORDER BY rowid"
            ).fetchall()

        return [
            DataSource.model_validate_json(row["payload"])
            for row in rows
        ]

    def save_schema(self, schema: SourceSchema) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO schemas(source_id, version, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id)
                DO UPDATE SET
                    version = excluded.version,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    schema.source_id,
                    schema.version,
                    schema.model_dump_json(),
                ),
            )

    def get_schema(self, source_id: str) -> SourceSchema | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM schemas WHERE source_id = ?",
                (source_id,),
            ).fetchone()

        if row is None:
            return None

        return SourceSchema.model_validate_json(row["payload"])
