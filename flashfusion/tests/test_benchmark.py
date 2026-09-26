from __future__ import annotations

import random

from flashfusion.eval import benchmark


class TooManyRequestsResponseError(Exception):
    pass


class _RateLimitedError(Exception):
    def __init__(self, retry_after: str) -> None:
        self.headers = {"retry-after": retry_after}


def test_query_retry_recognizes_openrouter_rate_limit_exception() -> None:
    assert benchmark._is_retryable_query_error(TooManyRequestsResponseError())


def test_query_retry_prefers_bounded_provider_delay() -> None:
    error = _RateLimitedError("45")

    assert benchmark._query_retry_delay_seconds(error, attempt=0) == 30.0


def test_grounding_retry_recognizes_openrouter_rate_limit_exception() -> None:
    from flashfusion.eval import benchmark_grounding

    assert benchmark_grounding._is_rate_limited_error(TooManyRequestsResponseError())


def test_grounding_retry_prefers_bounded_provider_delay() -> None:
    from flashfusion.eval import benchmark_grounding

    assert benchmark_grounding._rate_limit_retry_delay_s(_RateLimitedError("45"), attempt=0) == 30.0


def test_grounding_reuse_requires_every_selected_query_for_each_run() -> None:
    from flashfusion.eval import benchmark_grounding

    rows = [
        {"run_index": run_index, "query_version": "v1", "query_id": query_id}
        for run_index in (1, 2)
        for query_id in (1, 2)
    ]

    missing = benchmark_grounding._missing_reused_grounding_rows(
        rows,
        dataset="bus",
        runs=2,
        query_versions=["v1"],
        query_ids={1, 2, 3},
    )

    assert missing == [(1, "v1", 3), (2, "v1", 3)]


def test_grounding_query_order_is_seeded_and_preserves_coverage() -> None:
    from flashfusion.eval import benchmark_grounding

    query_defs = {query_id: {} for query_id in range(1, 9)}

    first = benchmark_grounding._shuffled_query_ids(query_defs, random.Random(7))
    second = benchmark_grounding._shuffled_query_ids(query_defs, random.Random(7))

    assert first == second
    assert sorted(first) == list(query_defs)