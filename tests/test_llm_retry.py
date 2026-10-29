from unittest.mock import AsyncMock, call

import httpx
import pytest

from app.retry_agent import (
    LLMRetryExhausted,
    LLMRetryPolicy,
    call_with_retry,
)


class FakeResponse:
    """Минимальный ответ модели для тестирования ретраев."""

    def __init__(
        self,
        content: str = "",
        tool_calls: list | None = None,
        finish_reason: str | None = "stop",
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.finish_reason = finish_reason


def make_http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com/chat")
    response = httpx.Response(status_code, request=request)

    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


@pytest.fixture
def policy() -> LLMRetryPolicy:
    return LLMRetryPolicy(
        max_attempts=3,
        base_delay_seconds=0.5,
        backoff_multiplier=2.0,
        max_delay_seconds=2.0,
    )


@pytest.fixture
def sleep_mock(monkeypatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr("app.retry_agent.asyncio.sleep", mock)
    return mock


@pytest.mark.asyncio
async def test_success_on_first_attempt(policy, sleep_mock):
    operation = AsyncMock(return_value=FakeResponse(content="Ответ"))

    result = await call_with_retry(
        operation,
        policy,
        is_retryable_result=lambda response: not response.content.strip(),
    )

    assert result.content == "Ответ"
    operation.assert_awaited_once()
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_retries_after_http_502(policy, sleep_mock):
    operation = AsyncMock(
        side_effect=[
            make_http_error(502),
            FakeResponse(content="Ответ"),
        ]
    )

    result = await call_with_retry(
        operation,
        policy,
        is_retryable_result=lambda response: not response.content.strip(),
    )

    assert result.content == "Ответ"
    assert operation.await_count == 2
    sleep_mock.assert_has_awaits([call(0.5)])


@pytest.mark.asyncio
async def test_retries_after_empty_response(policy, sleep_mock):
    operation = AsyncMock(
        side_effect=[
            FakeResponse(content="   "),
            FakeResponse(content="Ответ"),
        ]
    )

    result = await call_with_retry(
        operation,
        policy,
        is_retryable_result=lambda response: not response.content.strip(),
    )

    assert result.content == "Ответ"
    assert operation.await_count == 2
    sleep_mock.assert_has_awaits([call(0.5)])


@pytest.mark.asyncio
async def test_raises_after_max_attempts_for_http_error(policy, sleep_mock):
    error = make_http_error(502)
    operation = AsyncMock(side_effect=error)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await call_with_retry(
            operation,
            policy,
            is_retryable_result=lambda response: False,
        )

    assert exc_info.value is error
    assert operation.await_count == 3
    sleep_mock.assert_has_awaits([call(0.5), call(1.0)])


@pytest.mark.asyncio
async def test_raises_after_max_attempts_for_empty_responses(
    policy,
    sleep_mock,
):
    operation = AsyncMock(
        return_value=FakeResponse(content=" ")
    )

    with pytest.raises(LLMRetryExhausted):
        await call_with_retry(
            operation,
            policy,
            is_retryable_result=lambda response: not response.content.strip(),
        )

    assert operation.await_count == 3
    sleep_mock.assert_has_awaits([call(0.5), call(1.0)])


@pytest.mark.asyncio
async def test_does_not_retry_non_retryable_http_error(
    policy,
    sleep_mock,
):
    operation = AsyncMock(side_effect=make_http_error(400))

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await call_with_retry(
            operation,
            policy,
            is_retryable_result=lambda response: False,
        )

    assert exc_info.value.response.status_code == 400
    operation.assert_awaited_once()
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_does_not_retry_unexpected_exception(policy, sleep_mock):
    operation = AsyncMock(side_effect=ValueError("Invalid response"))

    with pytest.raises(ValueError, match="Invalid response"):
        await call_with_retry(
            operation,
            policy,
            is_retryable_result=lambda response: False,
        )

    operation.assert_awaited_once()
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_retries_transport_error(policy, sleep_mock):
    operation = AsyncMock(
        side_effect=[
            httpx.ConnectError("Connection failed"),
            FakeResponse(content="Ответ"),
        ]
    )

    result = await call_with_retry(
        operation,
        policy,
        is_retryable_result=lambda response: not response.content.strip(),
    )

    assert result.content == "Ответ"
    assert operation.await_count == 2
    sleep_mock.assert_has_awaits([call(0.5)])


def test_exponential_backoff():
    policy = LLMRetryPolicy(
        max_attempts=6,
        base_delay_seconds=0.5,
        backoff_multiplier=2.0,
        max_delay_seconds=3.0,
    )

    assert [
        policy.delay(attempt)
        for attempt in range(1, 7)
    ] == [0.5, 1.0, 2.0, 3.0, 3.0, 3.0]


def test_zero_delay_is_supported():
    policy = LLMRetryPolicy(
        max_attempts=3,
        base_delay_seconds=0.0,
        backoff_multiplier=2.0,
        max_delay_seconds=0.0,
    )

    assert policy.delay(1) == 0.0
    assert policy.delay(2) == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"base_delay_seconds": -1.0},
        {"backoff_multiplier": 0.5},
        {"max_delay_seconds": -1.0},
        {"base_delay_seconds": float("inf")},
        {"backoff_multiplier": float("nan")},
    ],
)
def test_invalid_policy_raises_value_error(kwargs):
    with pytest.raises(ValueError):
        LLMRetryPolicy(**kwargs)
