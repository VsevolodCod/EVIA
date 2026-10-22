"""Audit original CSVs locally without copying their contents into the repository.

Usage: python -m scripts.verify_csv_imports /path/to/csv-directory --report /tmp/evia-csv-audit.json
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.csv_import import CSVImportError
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService


def audit_file(path: Path) -> dict:
    with TemporaryDirectory(prefix="evia-csv-audit-") as directory:
        root = Path(directory)
        catalog = SchemaCatalog(root / "catalog.db")
        service = SourceService(root / "data", catalog)
        try:
            with path.open("rb") as stream:
                source = service.register_csv_stream(path.name, stream)
            report = source.import_report
            assert report is not None
            raw = service.raw_csv_path(source.source_id)
            with raw.open("rb") as stream:
                digest = sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            assert digest.hexdigest() == report.sha256
            assert service.data_engine.row_count(source) == report.accepted_rows
            return {
                "file": path.name,
                "status": "accepted",
                "report": report.model_dump(mode="json"),
                "materialized_rows": service.data_engine.row_count(source),
            }
        except CSVImportError as exc:
            return {"file": path.name, "status": "rejected", "message": str(exc),
                    "report": exc.report.model_dump(mode="json")}
        except Exception as exc:
            return {"file": path.name, "status": "error", "message": f"{type(exc).__name__}: {exc}"}
        finally:
            catalog.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--summary", type=Path, help="Optional metadata-only report safe to commit")
    args = parser.parse_args()
    files = sorted(args.directory.glob("*.csv"))
    if not files:
        parser.error("No CSV files found")
    results = []
    for path in files:
        print(f"Auditing {path.name}...", flush=True)
        result = audit_file(path)
        results.append(result)
        report = result.get("report", {})
        print(f"  {result['status']}: {report.get('accepted_rows', 0)} accepted, "
              f"{report.get('rejected_rows', 0)} rejected", flush=True)
    args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.summary:
        summary = [{
            "file": item["file"],
            "status": item["status"],
            **{key: item.get("report", {}).get(key) for key in (
                "sha256", "size_bytes", "encoding", "delimiter", "rows_read",
                "accepted_rows", "rejected_rows", "errors",
            )},
        } for item in results]
        args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Local report: {args.report}", flush=True)
    return 0 if all(result["status"] == "accepted" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
