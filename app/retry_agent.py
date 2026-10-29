import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LLMRetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        values = (
            self.base_delay_seconds,
            self.backoff_multiplier,
            self.max_delay_seconds,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Retry settings must be finite")

        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be >= 0")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be >= 1")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be >= 0")

    def delay(self, attempt: int) -> float:
        """Рассчитывает задержку перед следующим повтором."""
        delay = self.base_delay_seconds * (
            self.backoff_multiplier ** (attempt - 1)
        )
        return min(delay, self.max_delay_seconds)


def is_retryable_error(exc: Exception) -> bool:
    """Определяет, имеет ли смысл повторять запрос к LLM."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_HTTP_STATUSES

    return isinstance(exc, httpx.TransportError)


class LLMRetryExhausted(Exception):
    """Все попытки получения пригодного ответа исчерпаны."""


async def call_with_retry(
    operation: Callable[[], Awaitable[T]],
    policy: LLMRetryPolicy,
    *,
    is_retryable_result: Callable[[T], bool],
) -> T:
    """
    Повторяет операцию при временных ошибках или непригодных ответах.

    is_retryable_result возвращает True, если ответ нужно получить заново.
    """
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = await operation()

        except Exception as exc:
            if not is_retryable_error(exc):
                raise

            if attempt == policy.max_attempts:
                logger.error(
                    "LLM request failed after %s attempts: %s",
                    attempt,
                    type(exc).__name__,
                )
                raise

            delay = policy.delay(attempt)

            logger.warning(
                "Temporary LLM error: attempt %s/%s, "
                "retry in %.2f seconds (%s)",
                attempt,
                policy.max_attempts,
                delay,
                type(exc).__name__,
            )

        else:
            if not is_retryable_result(result):
                return result

            if attempt == policy.max_attempts:
                logger.error(
                    "LLM returned unusable output after %s attempts",
                    attempt,
                )
                raise LLMRetryExhausted(
                    "LLM returned unusable output"
                )

            delay = policy.delay(attempt)

            logger.warning(
                "Unusable LLM output: attempt %s/%s, "
                "retry in %.2f seconds",
                attempt,
                policy.max_attempts,
                delay,
            )

        await asyncio.sleep(delay)

    raise AssertionError("Unreachable")
