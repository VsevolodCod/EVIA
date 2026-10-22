"""Verify the public v1 gold-question corpus without a running LLM.

Run: python -m scripts.verify_eval_corpus --output /tmp/evia-evals.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from app.evaluation import verify_corpus


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "evals" / "v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--data-dir", type=Path,
                        help="Temporary EVIA data directory; default is an isolated temp directory.")
    args = parser.parse_args()

    if args.data_dir is None:
        with tempfile.TemporaryDirectory(prefix="evia-evals-") as folder:
            report = verify_corpus(args.corpus, data_dir=Path(folder))
    else:
        report = verify_corpus(args.corpus, data_dir=args.data_dir)
    payload = report.as_dict()
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
