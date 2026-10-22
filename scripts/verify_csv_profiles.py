"""Create a metadata-only acceptance audit for imported CSV profiles.

Usage:
    python -m scripts.verify_csv_profiles /path/to/nine-csv-corpus \
        --output docs/issue-8-originals-profile-audit.json

The JSON output deliberately omits CSV rows, headers, column statistics, and
exception messages. It is safe to commit when file names and hashes are safe
to disclose.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from app.csv_import import CSVImportError
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


AUDIT_FORMAT = "evia-csv-profile-audit/v1"
DEFAULT_EXPECTED_FILES = 9


def _runtime_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)


def _entry(path: Path) -> dict[str, Any]:
    """Import and profile one CSV, retaining only safe acceptance metadata."""
    started_at = perf_counter()
    entry: dict[str, Any] = {
        "filename": path.name,
        "sha256": None,
        "source_id": None,
        "snapshot_id": None,
        "accepted_import_rows": None,
        "processed_rows": None,
        "coverage": None,
        "runtime_ms": None,
        "errors": [],
    }

    with TemporaryDirectory(prefix="evia-csv-profile-audit-") as directory:
        root = Path(directory)
        catalog = SchemaCatalog(root / "catalog.db")
        try:
            service = SourceService(root / "data", catalog)
            with path.open("rb") as stream:
                source = service.register_csv_stream(path.name, stream)
            report = source.import_report
            if report is None:
                entry["errors"].append("MISSING_IMPORT_REPORT")
                return entry

            entry.update(
                sha256=report.sha256,
                source_id=source.source_id,
                snapshot_id=source.snapshot_id,
                accepted_import_rows=report.accepted_rows,
            )
            profile = service.profile(source.source_id)
            entry.update(
                processed_rows=profile.get("processed_rows"),
                coverage=profile.get("coverage"),
            )

            if entry["processed_rows"] != entry["accepted_import_rows"]:
                entry["errors"].append("PROCESSED_ROWS_MISMATCH")
            if entry["coverage"] != "full":
                entry["errors"].append("INCOMPLETE_COVERAGE")
            if profile.get("snapshot_id") != source.snapshot_id:
                entry["errors"].append("SNAPSHOT_ID_MISMATCH")
        except CSVImportError as exc:
            entry["sha256"] = exc.report.sha256 or None
            entry["accepted_import_rows"] = exc.report.accepted_rows
            entry["errors"].append("IMPORT_REJECTED")
        except Exception:
            # Exception messages may contain input values or local paths.
            entry["errors"].append("UNEXPECTED_EXCEPTION")
        finally:
            catalog.close()
            entry["runtime_ms"] = _runtime_ms(started_at)

    return entry


def audit_directory(directory: Path, *, expected_files: int = DEFAULT_EXPECTED_FILES) -> dict[str, Any]:
    """Return the acceptance summary and enforce full profiles for every CSV."""
    started_at = perf_counter()
    files = sorted(path for path in directory.glob("*.csv") if path.is_file())
    entries = [_entry(path) for path in files]
    errors: list[str] = []
    if len(files) != expected_files:
        errors.append("FILE_COUNT_MISMATCH")
    if any(entry["errors"] for entry in entries):
        errors.append("PROFILE_ACCEPTANCE_FAILED")

    return {
        "format": AUDIT_FORMAT,
        "expected_file_count": expected_files,
        "found_file_count": len(files),
        "status": "accepted" if not errors else "rejected",
        "total_runtime_ms": _runtime_ms(started_at),
        "errors": errors,
        "files": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory containing the CSV corpus")
    parser.add_argument("--output", required=True, type=Path, help="Metadata-only JSON summary")
    parser.add_argument(
        "--expected-files",
        type=int,
        default=DEFAULT_EXPECTED_FILES,
        help=f"Required CSV count (default: {DEFAULT_EXPECTED_FILES})",
    )
    args = parser.parse_args()
    if args.expected_files < 1:
        parser.error("--expected-files must be positive")
    if not args.directory.is_dir():
        parser.error("directory must exist and be a directory")

    audit = audit_directory(args.directory, expected_files=args.expected_files)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{audit['status']}: {audit['found_file_count']}/{audit['expected_file_count']} CSV files; "
        f"{audit['total_runtime_ms']} ms; {args.output}",
        flush=True,
    )
    return 0 if audit["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
