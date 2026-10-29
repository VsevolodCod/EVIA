"""Benchmark EVIA inside Railway with isolated synthetic data and the configured LLM.

Run on Railway only: python -m scripts.benchmark_railway_agent
The script does not read or write user sources and never prints API credentials.
"""

import argparse
import asyncio
import json
import math
import os
import statistics
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.agent import AgentRuntime
from app.config import get_settings
from app.llm.factory import create_llm_provider
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


CSV = b"period,revenue,segment\n2026-01-02,100,A\n2026-02-05,200,B\n2026-03-04,300,A\n"


def summarize(values: list[float]) -> dict[str, object]:
    """Return raw server durations and nearest-rank p95 (no interpolation)."""
    if not values:
        raise ValueError("At least one duration is required")
    ordered = sorted(values)
    return {
        "n": len(values),
        "raw_ms": [round(value) for value in values],
        "p50_ms": round(statistics.median(ordered)),
        "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1]),
        "max_ms": round(ordered[-1]),
    }


def verifies(case: str, answer) -> bool:
    if answer.status != "answered":
        return False
    if case == "schema":
        return all(name in answer.answer for name in ("period", "revenue", "segment"))
    if case == "overview":
        return all(fact in answer.answer for fact in ("3 строки", "3 поля", "2026-01-02", "2026-03-04"))
    for result in answer.results:
        if result.rows and result.rows[0]:
            try:
                if Decimal(str(result.rows[0][0])) == Decimal(600):
                    return True
            except (InvalidOperation, TypeError, ValueError):
                pass
    return False


async def benchmark(repeats: dict[str, int]) -> dict[str, object]:
    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="evia-benchmark-") as directory:
        catalog = SchemaCatalog(Path(directory) / "catalog.db")
        try:
            sources = SourceService(Path(directory) / "data", catalog)
            source = sources.register_csv("benchmark.csv", CSV)
            agent = AgentRuntime(
                create_llm_provider(settings), build_tool_registry(catalog, sources),
                max_steps=settings.agent_max_steps, sources=sources,
            )
            report = {
                "model": settings.llm_model,
                "source_id": source.source_id,
                "snapshot_id": source.snapshot_id,
                "schema_version": source.schema_version,
                "scope": "AgentTiming.elapsed_ms inside Railway; excludes browser/network rendering",
                "cases": {},
            }
            questions = {
                "schema": "Какие есть столбцы?",
                "overview": "Что передо мной?",
                "sql": "Какая сумма revenue?",
            }
            for case, question in questions.items():
                first = await agent.ask(question, [source.source_id])
                timings = []
                failures = []
                calls = []
                for index in range(repeats[case]):
                    answer = await agent.ask(question, [source.source_id])
                    timings.append(answer.timing.elapsed_ms)
                    calls.append(len(answer.timing.calls))
                    if not verifies(case, answer):
                        failures.append(index + 1)
                report["cases"][case] = {
                    "question": question,
                    "first_ms": round(first.timing.elapsed_ms),
                    "first_verified": verifies(case, first),
                    "first_model_calls": len(first.timing.calls),
                    "warm": summarize(timings),
                    "failed_runs": failures,
                    "model_calls": calls,
                }
            return report
        finally:
            catalog.close()


def main() -> int:
    if not os.getenv("RAILWAY_ENVIRONMENT"):
        raise SystemExit("Run this benchmark in Railway; local inference is disabled for this project")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-repeats", type=int, default=30)
    parser.add_argument("--overview-repeats", type=int, default=30)
    parser.add_argument("--sql-repeats", type=int, default=5)
    args = parser.parse_args()
    repeats = {
        "schema": args.schema_repeats,
        "overview": args.overview_repeats,
        "sql": args.sql_repeats,
    }
    if any(count < 1 for count in repeats.values()):
        parser.error("repeat counts must be positive")
    report = asyncio.run(benchmark(repeats))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any(
        not case["first_verified"] or case["failed_runs"]
        for case in report["cases"].values()
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
