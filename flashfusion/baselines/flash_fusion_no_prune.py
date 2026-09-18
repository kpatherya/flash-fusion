"""``FF_NO_PRUNE`` — Flash-Fusion with the operator router disabled.

The planner is shown the complete operator vocabulary instead of the bucket
the deterministic router would have narrowed it to. Everything else is the
FF_NO_CACHE reference policy: same planner, same prompt (guidance included),
same Gate 1 / Gate 2 validation, same typed execution, same ReAct fallback,
same cache setting.

This module deliberately owns no orchestration logic. It binds a policy and
delegates to the shared runner, so "no pruning" cannot drift into also meaning
"no cache" or "no guidance" through copied code — the single planner
implementation in ``flash_fusion_no_cache`` serves every arm.

The cache is **off** here because it is off in this arm's reference,
``FF_NO_CACHE``. That is a deliberate experimental choice, not an artifact of
module layout: a cache hit never reaches the planner, so pruning is inert on
hits and a cache-on contrast would dilute the pruning effect by the hit rate
rather than isolate it. The single-reference, cache-on variant is registered
as the ``FF_NO_PRUNE_CACHED`` diagnostic and runs through this same entry
point via ``policy=``.
"""

from __future__ import annotations

from typing import Any

from flashfusion.baselines.flash_fusion_policy import (
    FlashFusionPolicy,
    resolve_policy,
    run_with_policy,
)
from flashfusion.pipeline.runner import LLMClient, RunResult

BASELINE_NAME = "FF_NO_PRUNE"
POLICY = resolve_policy(BASELINE_NAME)


def run_flash_fusion_no_prune(
    query: str,
    df: Any,
    client: LLMClient,
    r: RunResult,
    *,
    policy: FlashFusionPolicy | None = None,
    **kwargs: Any,
) -> RunResult:
    """Run one query with operator pruning disabled.

    Args:
        policy: Override for the bound ``FF_NO_PRUNE`` policy — pass
            ``resolve_policy("FF_NO_PRUNE_CACHED")`` for the cache-on
            diagnostic. Must be a policy with ``pruning=False``.
        **kwargs: Forwarded to the shared runner (``timeout_s``, ``dataset``,
            ``cache_path``, ``semantic_cache_path``).
    """
    active = policy or POLICY
    if active.pruning:
        raise ValueError(
            f"{active.name} enables pruning; it cannot run as a no-prune arm."
        )
    return run_with_policy(query, df, client, r, active, **kwargs)
