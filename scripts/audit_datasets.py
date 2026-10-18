"""Create a local dataset-audit manifest without copying CSV contents into git."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.dataset_audit import audit_directory, write_public_method_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit local CSV datasets without exporting their rows")
    parser.add_argument("--input", type=Path, required=True, help="Directory containing the source CSV files")
    parser.add_argument("--output", type=Path, required=True, help="Local path for the JSON manifest")
    parser.add_argument("--public-report", type=Path, help="Optional path for the method-only Markdown report")
    parser.add_argument("--expected-files", type=int, default=9, help="Required CSV file count (default: 9)")
    args = parser.parse_args()
    manifest = audit_directory(args.input, expected_files=args.expected_files)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.public_report:
        args.public_report.parent.mkdir(parents=True, exist_ok=True)
        args.public_report.write_text(write_public_method_report(), encoding="utf-8")
    print(f"Audited {manifest['file_count']} CSV files; manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
