from __future__ import annotations

import httpx
import pytest
from openrouter.errors.badrequestresponse_error import (
    BadRequestResponseError,
    BadRequestResponseErrorData as BadRequestResponsePayload,
)
from openrouter.components.badrequestresponseerrordata import (
    BadRequestResponseErrorData as ProviderErrorPayload,
)
from openrouter.errors.responsevalidationerror import ResponseValidationError

from flashfusion.pipeline import runner


class _RateLimitedThenSuccessfulRunnable:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, payload, config):
        self.calls += 1
        if self.calls == 1:
            response = httpx.Response(
                429,
                request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            )
            raise ResponseValidationError("response validation failed", response, ValueError("429"), "{}")
        return "recovered"


class _ProviderErrorThenSuccessfulRunnable:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, payload, config):
        self.calls += 1
        if self.calls == 1:
            response = httpx.Response(
                400,
                request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            )
            raise BadRequestResponseError(
                BadRequestResponsePayload(
                    error=ProviderErrorPayload(
                        code=400,
                        message="Provider returned error",
                    )
                ),
                response,
            )
        return "recovered"


def test_retryable_openrouter_429_logs_only_successful_attempt_latency(monkeypatch) -> None:
    client = object.__new__(runner.LLMClient)
    client.model_name = "qwen/qwen-2.5-7b-instruct"
    client.call_log = []
    client.last_invocation_latency_s = 0.0
    client.last_retry_overhead_s = 0.0
    runnable = _RateLimitedThenSuccessfulRunnable()
    clock = iter((0.0, 0.2, 0.7, 1.0))
    sleeps: list[float] = []

    monkeypatch.setattr(runner.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(runner.time, "sleep", sleeps.append)

    assert client._invoke(runnable, {}, stage="cache_grounding") == "recovered"
    assert runnable.calls == 2
    assert sleeps == [0.5]
    assert client.last_invocation_latency_s == pytest.approx(0.3)
    assert client.last_retry_overhead_s == pytest.approx(0.7)
    assert len(client.call_log) == 1
    assert client.call_log[0].latency_s == pytest.approx(0.3)


def test_retryable_openrouter_provider_error_retries(monkeypatch) -> None:
    client = object.__new__(runner.LLMClient)
    client.model_name = "qwen/qwen-2.5-7b-instruct"
    client.call_log = []
    client.last_invocation_latency_s = 0.0
    client.last_retry_overhead_s = 0.0
    runnable = _ProviderErrorThenSuccessfulRunnable()
    sleeps: list[float] = []

    monkeypatch.setattr(runner.time, "sleep", sleeps.append)

    assert client._invoke(runnable, {}, stage="S_summarize") == "recovered"
    assert runnable.calls == 2
    assert sleeps == [0.5]