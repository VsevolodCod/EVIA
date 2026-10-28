from __future__ import annotations

from typing import Any

from app.hypothesis.implementations import hypothesis_implementations
from app.hypothesis.models import (
    CheckResult,
    HypothesisRequest,
    HypothesisResult,
)


class HypothesisEngine:
    def __init__(self, sources: Any) -> None:
        self.implementations = {
            implementation.method: implementation(sources)
            for implementation in hypothesis_implementations
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = HypothesisRequest.model_validate(payload)
        results: list[CheckResult] = []

        for check in request.checks:
            implementation = self.implementations.get(check.method)

            if implementation is None:
                results.append(
                    CheckResult(
                        id=check.id,
                        method=check.method,
                        status="error",
                        error=(
                            f"Unsupported check method: {check.method}"
                        ),
                    )
                )
                continue

            try:
                data = implementation.execute(check)

                results.append(
                    CheckResult(
                        id=check.id,
                        method=check.method,
                        status="completed",
                        data=data,
                    )
                )
            except Exception as exc:
                # Ошибка одной проверки не прерывает остальные.
                results.append(
                    CheckResult(
                        id=check.id,
                        method=check.method,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

        return HypothesisResult(
            statement=request.statement,
            results=results,
        ).model_dump(mode="json")
