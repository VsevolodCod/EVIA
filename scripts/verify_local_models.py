"""Benchmark local Ollama candidates on the same synthetic CSV questions.

Run: python -m scripts.verify_local_models qwen2.5-coder:3b llama3.2:3b
"""

import argparse
import asyncio
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import httpx

from app.agent import AgentRuntime
from app.config import Settings
from app.llm.factory import create_llm_provider
from app.schema_catalog import SchemaCatalog
from app.source_service import SourceService
from app.tools import build_tool_registry


CSV = b"month,revenue\n2026-01,120\n2026-02,180\n"
QUESTIONS = [
    ("Сколько строк в таблице?", [[2]]),
    ("Сколько всего выручки?", [[300]]),
]


def _runner_rss_mb(modelfile: str) -> float | None:
    match = re.search(r"^FROM (\S+)", modelfile, flags=re.MULTILINE)
    if match is None:
        return None
    model_path = match.group(1)
    try:
        output = subprocess.check_output(["ps", "-axo", "rss=,command="], text=True)
        sizes = [int(line.split(maxsplit=1)[0]) for line in output.splitlines()
                 if "ollama/llama-server" in line and model_path in line and line.split(maxsplit=1)[0].isdigit()]
        return round(sum(sizes) / 1024, 1) if sizes else None
    except (OSError, subprocess.CalledProcessError):
        return None


async def verify(models: list[str], base_url: str) -> dict:
    report = {"host_memory_gb": None, "models": []}
    try:
        report["host_memory_gb"] = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
    except (AttributeError, ValueError, OSError):
        pass
    async with httpx.AsyncClient(base_url=base_url, timeout=120, trust_env=False) as client:
        tags = (await client.get("/api/tags")).json()["models"]
        for model in models:
            tag = next((item for item in tags if item["name"] == model), None)
            if tag is None:
                raise ValueError(f"Model is not downloaded locally: {model}")
            show_response = await client.post("/api/show", json={"model": model})
            show_response.raise_for_status()
            show = show_response.json()
            os.environ["LLM_PROVIDER"] = "ollama"
            os.environ["LLM_MODEL"] = model
            os.environ["OLLAMA_BASE_URL"] = base_url
            os.environ["THINKING"] = "0"
            os.environ["TIMEOUT"] = "120"
            os.environ["MAX_TOKENS_G"] = "256"
            record = {
                "model": model,
                "digest": tag["digest"],
                "size_bytes": tag["size"],
                "quantization": tag.get("details", {}).get("quantization_level"),
                "context_window": show.get("model_info", {}).get(
                    "qwen2.context_length", show.get("model_info", {}).get("llama.context_length")
                ),
                "inference_context": 4096,
                "license": next((line.strip() for line in (show.get("license") or "unknown").splitlines() if line.strip()), "unknown"),
                "questions": [],
            }
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                catalog = SchemaCatalog(root / "catalog.db")
                try:
                    sources = SourceService(root / "data", catalog)
                    source = sources.register_csv("sales.csv", CSV)
                    agent = AgentRuntime(create_llm_provider(Settings()), build_tool_registry(catalog, sources), sources=sources)
                    for question, expected in QUESTIONS:
                        try:
                            response = await agent.ask(question, [source.source_id])
                            actual = response.results[0].rows if response.results else None
                            passed = response.status == "answered" and _same_numeric_rows(actual, expected)
                            record["questions"].append({
                                "question": question,
                                "passed": passed,
                                "status": response.status,
                                "rows": actual,
                                "steps": response.steps,
                                "elapsed_ms": round(response.timing.elapsed_ms, 1),
                                "llm_ms": round(response.timing.llm_ms, 1),
                                "load_ms": [round(call.load_ms, 1) if call.load_ms is not None else None for call in response.timing.calls],
                                "sql": response.analysis.sql if response.analysis else None,
                            })
                        except Exception as exc:
                            record["questions"].append({"question": question, "passed": False, "error": type(exc).__name__})
                finally:
                    catalog.close()
            resident = (await client.get("/api/ps")).json().get("models", [])
            current = next((item for item in resident if item["name"] == model), {})
            record["loaded_size_bytes"] = current.get("size")
            record["reported_vram_bytes"] = current.get("size_vram")
            record["runner_rss_mb"] = _runner_rss_mb(show.get("modelfile", ""))
            report["models"].append(record)
    return report


def _same_numeric_rows(actual, expected) -> bool:
    if actual is None or len(actual) != len(expected):
        return False
    try:
        return all(
            len(left) == len(right) and all(Decimal(str(a)) == Decimal(str(b)) for a, b in zip(left, right))
            for left, right in zip(actual, expected)
        )
    except (InvalidOperation, TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", help="Already downloaded Ollama tags")
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(verify(args.models, args.url))
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if all(item["passed"] for model in report["models"] for item in model["questions"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
