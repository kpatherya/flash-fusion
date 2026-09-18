"""``FF_NO_PROMPT`` — Flash-Fusion with aggressive planner prompt removal.

This arm strips operator-vocabulary guidance to signatures only (no hard
rules, no usage prose, no worked examples, no rejected-pattern walkthroughs),
and also removes planner-composition guidance paragraphs from the planning
contract. The result is an intentionally under-instructed planner prompt that
keeps only the minimum structural contract needed for typed-plan I/O.

The no-invention and output-grammar constraints are still retained in the
scope/output contract so invalid answers are rejected rather than rewarded.

Pruning and caching match this arm's reference, ``FF_NO_CACHE``. As with
``flash_fusion_no_prune``, this module binds a policy and delegates; the
cache-on single-reference variant is the ``FF_NO_PROMPT_CACHED`` diagnostic.
"""

from __future__ import annotations
from typing import Any

from flashfusion.baselines.flash_fusion_policy import (
    FlashFusionPolicy,
    resolve_policy,
    run_with_policy,
)
from flashfusion.pipeline.runner import LLMClient, RunResult

BASELINE_NAME = "FF_NO_PROMPT"
POLICY = resolve_policy(BASELINE_NAME)


def run_flash_fusion_no_prompt(
    query: str,
    df: Any,
    client: LLMClient,
    r: RunResult,
    *,
    policy: FlashFusionPolicy | None = None,
    **kwargs: Any,
) -> RunResult:
    """Run one query with planner composition guidance disabled.

    Args:
        policy: Override for the bound ``FF_NO_PROMPT`` policy — pass
            ``resolve_policy("FF_NO_PROMPT_CACHED")`` for the cache-on
            diagnostic. Must be a policy with ``planner_guidance=False``.
        **kwargs: Forwarded to the shared runner (``timeout_s``, ``dataset``,
            ``cache_path``, ``semantic_cache_path``).
    """
    active = policy or POLICY
    if active.planner_guidance:
        raise ValueError(
            f"{active.name} enables planner guidance; it cannot run as a "
            "no-prompt arm."
        )
    return run_with_policy(query, df, client, r, active, **kwargs)
