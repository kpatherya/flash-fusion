"""Deprecated module path — use ``flashfusion.baselines.flash_fusion_no_cache``.

The Flash-Fusion planner implementation moved to ``flash_fusion_no_cache`` so
that the module name states its policy (cache disabled) instead of implying it
is the full system. This shim keeps ``from flashfusion.baselines.flash_fusion
import run_flash_fusion`` working for saved scripts and external callers.

Note for test authors: ``unittest.mock.patch`` targets must name the *real*
module, e.g. ``flashfusion.baselines.flash_fusion_no_cache.execute_plan``.
Patching ``flashfusion.baselines.flash_fusion.<name>`` rebinds only this
shim's re-exported alias and will not affect the running implementation.
"""

from __future__ import annotations

import warnings

from flashfusion.baselines.flash_fusion_no_cache import *  # noqa: F401,F403
from flashfusion.baselines.flash_fusion_no_cache import (  # noqa: F401
    DEFAULT_POLICY,
    FF_DEBUG,
    FF_FALLBACK_GROUNDING,
    FF_PROGRESS,
    FF_REACT_FALLBACK,
    PATH_GUARDRAIL_REJECT,
    PATH_REACT_FALLBACK,
    PATH_SCOPE_REJECT,
    PATH_TYPED_OPERATOR,
    PATH_TYPED_PLAN_UNAVAILABLE,
    PLANNER_GUIDANCE_FULL,
    PLANNER_GUIDANCE_NONE,
    ROUTE_MODE_FULL,
    ROUTE_MODE_ROUTER,
    _format_typed_execution_value,
    _FlashFusionTimeoutError,
    _run_with_timeout,
    build_react_query,
    prewarm_flash_fusion_prompt_cache,
    record_policy_provenance,
    request_guardrail_and_plan,
    run_flash_fusion,
    schema_fingerprint,
    typed_plan_digest,
    warm_flash_fusion_prefix,
)

warnings.warn(
    "flashfusion.baselines.flash_fusion is deprecated; import from "
    "flashfusion.baselines.flash_fusion_no_cache instead.",
    DeprecationWarning,
    stacklevel=2,
)
