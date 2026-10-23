"""Compare at least two downloaded Ollama models on the public EVIA corpus.

Example:
  python -m scripts.benchmark_local_models qwen2.5-coder:7b qwen2.5-coder:3b \
    --output /tmp/evia-model-benchmark.json --markdown /tmp/evia-model-benchmark.md
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from typing import Sequence

from app.agent import AgentRuntime
from app.config import Settings
from app.evaluation import load_corpus
from app.llm.factory import create_llm_provider
from app.model_benchmark import BenchmarkReport, BenchmarkRunner, OllamaMetadataClient
from app.source_service import SourceService
from app.tools import build_tool_registry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "evals" / "v1"


def _host_memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        return None


def _agent_factory(model: str, sources: SourceService, args: argparse.Namespace) -> AgentRuntime:
    settings = Settings()
    settings.llm_provider = "ollama"
    settings.llm_model = model
    settings.ollama_base_url = args.url.rstrip("/")
    settings.thinking = args.thinking
    settings.timeout = args.timeout
    settings.max_tokens_generate = args.max_tokens
    return AgentRuntime(
        create_llm_provider(settings),
        build_tool_registry(sources.catalog, sources),
        max_steps=settings.agent_max_steps,
        sources=sources,
    )


def _format_rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def render_markdown(report: BenchmarkReport) -> str:
    lines = [
        "# Сравнение локальных моделей EVIA",
        "",
        f"Corpus: `evals/v{report.corpus_version}`, schema report: {report.schema_version}.",
        "",
        "| Модель | EX | JSON | Valid SQL | Ошибки | Timeouts | p50 | p95 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in report.models:
        summary = model.summary
        lines.append(
            f"| `{model.model}` | {_format_rate(summary.exact_match_rate)} | "
            f"{_format_rate(summary.json_validity_rate)} | {_format_rate(summary.valid_sql_rate)} | "
            f"{summary.errors} | {summary.timeouts} | {summary.p50_latency_ms or '—'} ms | "
            f"{summary.p95_latency_ms or '—'} ms |"
        )
    lines += ["", "## Неуспешные cases", ""]
    failures = [
        (model.model, outcome)
        for model in report.models
        for outcome in model.outcomes
        if not outcome.exact_match or outcome.error_code
    ]
    if not failures:
        lines.append("Нет.")
    else:
        lines += ["| Модель | Case | Режим | Статус | Ошибка |", "| --- | --- | --- | --- | --- |"]
        lines += [
            f"| `{model}` | `{outcome.case_id}` | {outcome.mode} | {outcome.status} | "
            f"{outcome.error_code or 'несовпадение результата'} |"
            for model, outcome in failures
        ]
    lines += [
        "",
        "## Ограничения",
        "",
        "Это локальное измерение на конкретном железе, версии Ollama и версиях весов. "
        "Оно не является универсальным рейтингом моделей. Выбор кандидата требует нулевых "
        "провалов безопасных cases и анализа каждой ошибки; скорость сама по себе не основание для выбора.",
        "",
    ]
    return "\n".join(lines)


def write_reports(report: BenchmarkReport, *, output: Path, markdown: Path | None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown is not None:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(render_markdown(report), encoding="utf-8")


def _has_fatal_result(report: BenchmarkReport) -> bool:
    return any(
        outcome.status == "error" or (outcome.expected_kind != "computed" and not outcome.exact_match)
        for model in report.models
        for outcome in model.outcomes
    )


async def _run(args: argparse.Namespace) -> BenchmarkReport:
    corpus = load_corpus(args.corpus)
    metadata = OllamaMetadataClient(args.url)
    with tempfile.TemporaryDirectory(prefix="evia-model-benchmark-") as work_dir:
        runner = BenchmarkRunner(
            corpus,
            Path(work_dir),
            lambda model, sources: _agent_factory(model, sources, args),
            metadata,
        )
        report = await runner.run(args.models, warm_repeats=args.warm_repeats, cold=not args.skip_cold)
    return replace(report, run_metadata={
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "host_memory_bytes": _host_memory_bytes(),
        "ollama_url": args.url.rstrip("/"),
        "thinking": args.thinking,
        "timeout_seconds": args.timeout,
        "max_tokens": args.max_tokens,
        "warm_repeats": args.warm_repeats,
        "cold_enabled": not args.skip_cold,
    })


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", help="Downloaded Ollama tags; pass at least two.")
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--warm-repeats", type=int, default=1)
    parser.add_argument("--skip-cold", action="store_true")
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("TIMEOUT", "120")))
    parser.add_argument("--max-tokens", type=int, default=int(os.getenv("MAX_TOKENS_G", "512")))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)
    if len(args.models) < 2:
        parser.error("pass at least two model tags for a comparison")
    if args.warm_repeats < 0:
        parser.error("--warm-repeats must be non-negative")
    try:
        report = asyncio.run(_run(args))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"benchmark failed: {exc}\n")
    write_reports(report, output=args.output, markdown=args.markdown)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 1 if _has_fatal_result(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
