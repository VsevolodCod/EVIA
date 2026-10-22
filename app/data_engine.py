"""Persistent analytical representation for uploaded CSV sources.

The CSV file remains the immutable uploaded artifact.  This module materializes
the same rows in a local DuckDB file, keyed only by an opaque source id. SQL is
executed only through :mod:`app.safe_sql`; callers here never accept SQL text.
"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import duckdb

from app.csv_import import null_marker
from app.duckdb_access import DUCKDB_ACCESS_LOCK
from app.models import DataSource


class DuckDBDataEngine:
    """Store one materialized DuckDB table for every ready CSV source."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def table_name(self, source: DataSource) -> str:
        """Return a deterministic safe physical table name for a snapshot."""
        snapshot_key = f"{source.source_id}:{source.snapshot_id or 'legacy'}"
        snapshot_hash = sha256(snapshot_key.encode("utf-8")).hexdigest()[:24]
        return f"source_{snapshot_hash}"

    def typed_table_name(self, source: DataSource) -> str:
        return f"{self.table_name(source)}_typed"

    @contextmanager
    def _connect(self):
        with DUCKDB_ACCESS_LOCK:
            with duckdb.connect(str(self.database_path)) as connection:
                yield connection

    def _typed_projections(self, connection, raw_table: str, typed_sql_types: dict[str, str]) -> list[str]:
        raw_columns = [row[0] for row in connection.execute(f"DESCRIBE {raw_table}").fetchall()]
        if set(raw_columns) != set(typed_sql_types):
            raise ValueError("Typed columns do not match CSV header")
        projections = []
        for name in raw_columns:
            sql_type = typed_sql_types[name]
            if not re.fullmatch(r"VARCHAR|BIGINT|BOOLEAN|DATE|TIMESTAMP|DECIMAL\(38,\d{1,2}\)", sql_type):
                raise ValueError("Invalid typed CSV column")
            quoted = self._quote_identifier(name)
            if sql_type == "VARCHAR":
                expression = quoted
            elif sql_type.startswith("DECIMAL") or sql_type == "BIGINT":
                expression = f"CAST(NULLIF(REPLACE(TRIM({quoted}), ',', '.'), '') AS {sql_type})"
            else:
                expression = f"CAST(NULLIF(TRIM({quoted}), '') AS {sql_type})"
            projections.append(f"{expression} AS {quoted}")
        return projections

    def import_csv(
        self, source: DataSource, csv_path: Path, *, delimiter: str,
        typed_sql_types: dict[str, str] | None = None,
    ) -> None:
        """Atomically replace the materialized table after CSV validation.

        All values are loaded as VARCHAR.  This preserves identifiers such as
        ``001`` and makes the engine agree with the existing CSV preview.
        Analytical SQL can explicitly cast fields based on the stored schema.
        """
        table = self._quote_identifier(self.table_name(source))
        path = Path(csv_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Source file not found: {source.source_id}")
        if delimiter not in {",", ";", "\t", "|"}:
            raise ValueError("Unsupported CSV delimiter")

        # A snapshot is immutable: a retry after it was fully published must
        # not silently replace rows that may already be referenced by results.
        if self.has_table(source):
            return

        pending = self._quote_identifier(f"{self.table_name(source)}_pending_{uuid4().hex}")
        typed_pending = self._quote_identifier(f"{self.typed_table_name(source)}_pending_{uuid4().hex}")
        marker = null_marker(source.import_report.sha256) if source.import_report else f"__EVIA_NULL_{uuid4().hex}__"
        names_option = ", names = ?" if typed_sql_types is not None else ""
        parameters = [str(path), delimiter, marker]
        if typed_sql_types is not None:
            parameters.append(list(typed_sql_types))
        with self._connect() as connection:
            try:
                connection.execute("BEGIN TRANSACTION")
                connection.execute(
                    f"""
                    CREATE TABLE {pending} AS
                    SELECT * FROM read_csv(
                        ?,
                        delim = ?,
                        header = true,
                        all_varchar = true,
                        strict_mode = true,
                        nullstr = ?{names_option}
                    )
                    """,
                    parameters,
                )
                if typed_sql_types is not None:
                    projections = self._typed_projections(connection, pending, typed_sql_types)
                    connection.execute(f"CREATE TABLE {typed_pending} AS SELECT {', '.join(projections)} FROM {pending}")
                connection.execute(f"ALTER TABLE {pending} RENAME TO {table}")
                if typed_sql_types is not None:
                    connection.execute(
                        f"ALTER TABLE {typed_pending} RENAME TO {self._quote_identifier(self.typed_table_name(source))}"
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def repair_typed_table(self, source: DataSource, typed_sql_types: dict[str, str]) -> None:
        """Rebuild a missing typed table from the retained raw table without dropping raw data."""
        raw = self._quote_identifier(self.table_name(source))
        typed = self._quote_identifier(self.typed_table_name(source))
        pending = self._quote_identifier(f"{self.typed_table_name(source)}_pending_{uuid4().hex}")
        with self._connect() as connection:
            try:
                connection.execute("BEGIN TRANSACTION")
                projections = self._typed_projections(connection, raw, typed_sql_types)
                connection.execute(f"CREATE TABLE {pending} AS SELECT {', '.join(projections)} FROM {raw}")
                connection.execute(f"ALTER TABLE {pending} RENAME TO {typed}")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def discard(self, source: DataSource) -> None:
        with self._connect() as connection:
            connection.execute(
                f"DROP TABLE IF EXISTS {self._quote_identifier(self.typed_table_name(source))}"
            )
            connection.execute(
                f"DROP TABLE IF EXISTS {self._quote_identifier(self.table_name(source))}"
            )

    def has_table(self, source: DataSource) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_name = ?",
                [self.table_name(source)],
            ).fetchone()[0] == 1

    def has_typed_table(self, source: DataSource) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_name = ?",
                [self.typed_table_name(source)],
            ).fetchone()[0] == 1

    def row_count(self, source: DataSource) -> int:
        with self._connect() as connection:
            return int(connection.execute(
                f"SELECT COUNT(*) FROM {self._quote_identifier(self.table_name(source))}"
            ).fetchone()[0])

    def preview(self, source: DataSource, limit: int = 10) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return self._rows(source, limit)

    def _rows(self, source: DataSource, limit: int) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        table = self._quote_identifier(self.table_name(source))
        with self._connect() as connection:
            cursor = connection.execute(f"SELECT * FROM {table} LIMIT ?", [limit])
            names = [column[0] for column in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

    def profile(self, source: DataSource, sample_size: int = 500) -> dict[str, Any]:
        rows = self._rows(source, sample_size)
        columns: dict[str, dict[str, Any]] = {}
        for name in rows[0] if rows else self.columns(source):
            values = [row.get(name) for row in rows]
            nonempty = [value for value in values if value not in (None, "")]
            counts: dict[str, int] = {}
            for value in nonempty:
                text = str(value)
                counts[text] = counts.get(text, 0) + 1
            columns[name] = {
                "sample_non_null_count": len(nonempty),
                "sample_null_count": len(values) - len(nonempty),
                "distinct_sample_values": len(set(map(str, nonempty))),
                "top_values": [
                    {"value": value, "count": count}
                    for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
                ],
            }
        return {
            "sample_size": len(rows),
            "sample_limit": sample_size,
            "columns": columns,
            "note": "Column statistics use a bounded DuckDB sample.",
        }

    def columns(self, source: DataSource) -> list[str]:
        table = self._quote_identifier(self.table_name(source))
        with self._connect() as connection:
            return [row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()]
