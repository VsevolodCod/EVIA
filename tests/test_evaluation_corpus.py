from pathlib import Path
import json
import subprocess
import sys

from app.evaluation import load_corpus, verify_corpus


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evals" / "v1"


def test_v1_has_twenty_unique_cases_and_fixture_hashes():
    corpus = load_corpus(CORPUS)

    assert corpus.version == 1
    assert len(corpus.cases) == 20
    assert len({case.case_id for case in corpus.cases}) == 20
    assert sum(case.expected_kind == "computed" for case in corpus.cases) == 17
    assert sum(case.expected_kind != "computed" for case in corpus.cases) == 3
    assert all(case.fixture_sha256 for case in corpus.cases)
    assert corpus.verify_fixture_hashes() == []


def test_gold_cases_execute_through_source_service(tmp_path):
    report = verify_corpus(CORPUS, data_dir=tmp_path / "data")

    assert report.failed == []
    assert report.passed_computed == 17
    assert report.passed_safe == 3


def test_cli_writes_machine_readable_report(tmp_path):
    output = tmp_path / "report.json"
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.verify_eval_corpus", "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "corpus_version": 1,
        "failed": [],
        "passed_computed": 17,
        "passed_safe": 3,
    }
