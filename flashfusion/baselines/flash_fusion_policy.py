"""Policy matrix for Flash-Fusion and its component ablations.

Flash-Fusion has three removable components:

1. **cache** — the operator-skeleton cache (exact + semantic) that lets a light
   model reground a previously validated operator sequence instead of invoking
   the full planner.
2. **pruning** — the deterministic operator router, which narrows the operator
   vocabulary shown to the planner.
3. **planner guidance** — the multi-step composition/sequencing guidance in the
   planner system prefix.

A *policy* is one (cache, pruning, guidance) setting plus the reference policy
it is meant to be contrasted against. Every primary ablation differs from its
reference in exactly one component; nothing else about the run changes.

Why ``FF_NO_PRUNE`` and ``FF_NO_PROMPT`` have the cache off
----------------------------------------------------------
A cache hit never reaches the planner: it grounds a cached operator skeleton
with the light model. Pruning and planner guidance are therefore *inert* on
every cache hit, so a cache-on no-pruning arm is byte-identical to the full
system except on the cache-miss subset, and its measured effect is diluted by
the hit rate rather than isolated by it.

So the primary set uses two references:

* the **cache** contrast is ``FF_FULL`` vs ``FF_NO_CACHE``;
* the **pruning** and **prompting** contrasts are ``FF_NO_CACHE`` vs
  ``FF_NO_PRUNE`` / ``FF_NO_PROMPT``.

Each contrast still isolates exactly one component. The cache-on variants are
registered too (``FF_NO_PRUNE_CACHED``, ``FF_NO_PROMPT_CACHED``) for anyone who
wants the single-reference version; they are diagnostics, not the primary set.

Legacy names
------------
``FLASH_FUSION``, ``FLASH_FUSION_CACHE``, ``FF_NO_PRUNING`` and
``FF_NO_PLANNING`` all keep working and keep their historical semantics. See
``LEGACY_POLICY_ALIASES`` and ``docs/flash_fusion_ablation_policy_matrix.md``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

#: ``route_mode`` values understood by the planner entry point.
ROUTE_MODE_ROUTER = "router"
ROUTE_MODE_FULL = "full"

#: ``planner_guidance`` values understood by the planner entry point.
PLANNER_GUIDANCE_FULL = "full"
PLANNER_GUIDANCE_NONE = "none"

#: A policy's place in the experiment.
ROLE_FULL = "full_system"
ROLE_PRIMARY = "primary_ablation"
ROLE_DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True)
class FlashFusionPolicy:
    """One point in the (cache, pruning, planner-guidance) matrix."""

    name: str
    cache: bool
    pruning: bool
    planner_guidance: bool
    role: str
    #: Policy this arm should be differenced against. Empty for the full system.
    reference: str = ""
    #: Which single component this arm removes relative to ``reference``.
    treatment: str = ""
    description: str = ""

    @property
    def route_mode(self) -> str:
        """``route_mode`` argument for the planner entry point."""
        return ROUTE_MODE_ROUTER if self.pruning else ROUTE_MODE_FULL

    @property
    def planner_guidance_mode(self) -> str:
        """``planner_guidance`` argument for the planner entry point."""
        return PLANNER_GUIDANCE_FULL if self.planner_guidance else PLANNER_GUIDANCE_NONE

    @property
    def digest(self) -> str:
        """Short stable digest of the *settings*, independent of the label.

        Two arms that share a digest ran the same policy under different names
        — which is exactly what makes the legacy aliases safe to mix with the
        new labels in one analysis.
        """
        payload = (
            f"cache={int(self.cache)}"
            f"|pruning={int(self.pruning)}"
            f"|guidance={int(self.planner_guidance)}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def as_log_record(self) -> dict[str, Any]:
        """Flat, JSON-safe policy description for the per-query result row."""
        return {
            "policy_name": self.name,
            "policy_cache_enabled": self.cache,
            "policy_pruning_enabled": self.pruning,
            "policy_planner_guidance_enabled": self.planner_guidance,
            "policy_role": self.role,
            "policy_reference": self.reference,
            "policy_treatment": self.treatment,
            "policy_digest": self.digest,
            "route_mode": self.route_mode,
            "planner_guidance_mode": self.planner_guidance_mode,
        }


def _policy(**kwargs: Any) -> FlashFusionPolicy:
    return FlashFusionPolicy(**kwargs)


#: Canonical policies, keyed by their experimental label.
POLICIES: dict[str, FlashFusionPolicy] = {
    "FF_FULL": _policy(
        name="FF_FULL",
        cache=True,
        pruning=True,
        planner_guidance=True,
        role=ROLE_FULL,
        reference="",
        treatment="",
        description="Full Flash-Fusion: cache + operator pruning + planner guidance.",
    ),
    "FF_NO_CACHE": _policy(
        name="FF_NO_CACHE",
        cache=False,
        pruning=True,
        planner_guidance=True,
        role=ROLE_PRIMARY,
        reference="FF_FULL",
        treatment="cache",
        description="Cache disabled; pruning and planner guidance unchanged.",
    ),
    "FF_NO_PRUNE": _policy(
        name="FF_NO_PRUNE",
        cache=False,
        pruning=False,
        planner_guidance=True,
        role=ROLE_PRIMARY,
        reference="FF_NO_CACHE",
        treatment="pruning",
        description=(
            "Operator pruning disabled (full vocabulary); cache and planner "
            "guidance match the FF_NO_CACHE reference."
        ),
    ),
    "FF_NO_PROMPT": _policy(
        name="FF_NO_PROMPT",
        cache=False,
        pruning=True,
        planner_guidance=False,
        role=ROLE_PRIMARY,
        reference="FF_NO_CACHE",
        treatment="planner_guidance",
        description=(
            "Planner composition guidance disabled; cache and pruning match "
            "the FF_NO_CACHE reference."
        ),
    ),
    # --- Diagnostics: not part of the primary reported comparisons ----------
    "FF_NO_PRUNE_CACHED": _policy(
        name="FF_NO_PRUNE_CACHED",
        cache=True,
        pruning=False,
        planner_guidance=True,
        role=ROLE_DIAGNOSTIC,
        reference="FF_FULL",
        treatment="pruning",
        description=(
            "Single-reference pruning ablation. Differs from FF_FULL in one "
            "dimension, but pruning is inert on cache hits so the effect is "
            "diluted by the hit rate."
        ),
    ),
    "FF_NO_PROMPT_CACHED": _policy(
        name="FF_NO_PROMPT_CACHED",
        cache=True,
        pruning=True,
        planner_guidance=False,
        role=ROLE_DIAGNOSTIC,
        reference="FF_FULL",
        treatment="planner_guidance",
        description=(
            "Single-reference prompting ablation. Differs from FF_FULL in one "
            "dimension, but guidance is inert on cache hits so the effect is "
            "diluted by the hit rate."
        ),
    ),
    "FF_NO_PRUNE_NO_PROMPT": _policy(
        name="FF_NO_PRUNE_NO_PROMPT",
        cache=False,
        pruning=False,
        planner_guidance=False,
        role=ROLE_DIAGNOSTIC,
        reference="FF_NO_CACHE",
        treatment="pruning+planner_guidance",
        description=(
            "Cumulative diagnostic: both planner-side components removed. "
            "Supports the adjacent FF_NO_PRUNE -> FF_NO_PRUNE_NO_PROMPT "
            "contrast; not a component-level claim on its own."
        ),
    ),
}

#: Historical baseline names -> the policy they have always denoted.
#:
#: These are *exact* semantic aliases, not approximations: each legacy name
#: already ran the settings of the policy it maps to, so saved runs under the
#: old label can be pooled with new runs under the new label.
LEGACY_POLICY_ALIASES: dict[str, str] = {
    "FLASH_FUSION_CACHE": "FF_FULL",
    "FLASH_FUSION": "FF_NO_CACHE",
    "FF_NO_PRUNING": "FF_NO_PRUNE",
    "FF_NO_PLANNING": "FF_NO_PRUNE_NO_PROMPT",
}

#: Labels the benchmark should report as component-level ablations.
PRIMARY_POLICY_SET: tuple[str, ...] = (
    "FF_FULL",
    "FF_NO_CACHE",
    "FF_NO_PRUNE",
    "FF_NO_PROMPT",
)


def resolve_policy(name: str) -> FlashFusionPolicy:
    """Return the policy for a canonical or legacy baseline label.

    Raises:
        KeyError: if *name* is not a Flash-Fusion policy label.
    """
    key = str(name or "").strip().upper()
    key = LEGACY_POLICY_ALIASES.get(key, key)
    try:
        return POLICIES[key]
    except KeyError:
        raise KeyError(
            f"{name!r} is not a Flash-Fusion policy. Known labels: "
            + ", ".join(sorted(set(POLICIES) | set(LEGACY_POLICY_ALIASES)))
        ) from None


def is_flash_fusion_policy(name: str) -> bool:
    """Whether *name* denotes any Flash-Fusion policy (canonical or legacy)."""
    key = str(name or "").strip().upper()
    return key in POLICIES or key in LEGACY_POLICY_ALIASES


def policy_label_for(name: str) -> str:
    """Canonical policy label for a possibly-legacy baseline name."""
    return resolve_policy(name).name


def run_with_policy(
    query: str,
    df: Any,
    client: Any,
    r: Any,
    policy: FlashFusionPolicy,
    **kwargs: Any,
) -> Any:
    """Execute one query under *policy*.

    Routes to the cache-first entry point or straight to the planner depending
    on ``policy.cache``; the pruning and planner-guidance settings are passed
    through identically on both paths, so the only thing the cache flag changes
    is whether a cache lookup precedes the planner.

    ``kwargs`` are forwarded verbatim (``timeout_s``, ``dataset``,
    ``cache_path``, ``semantic_cache_path``, ...); cache-only keys are dropped
    on the no-cache path so callers can pass one uniform kwargs dict.
    """
    # Imported lazily: the baseline modules import this one for their policy
    # constants, so a module-level import here would be circular.
    from flashfusion.baselines.flash_fusion_no_cache import run_flash_fusion

    planner_kwargs = dict(
        route_mode=policy.route_mode,
        planner_guidance=policy.planner_guidance_mode,
        policy=policy,
    )

    if not policy.cache:
        cache_only = ("dataset", "cache_path", "semantic_cache_path")
        passthrough = {k: v for k, v in kwargs.items() if k not in cache_only}
        return run_flash_fusion(query, df, client, r, **passthrough, **planner_kwargs)

    from flashfusion.baselines.flash_fusion_cache import (
        DEFAULT_CACHE_PATH,
        run_flash_fusion_cache,
    )

    cache_kwargs = dict(kwargs)
    cache_kwargs.setdefault("cache_path", DEFAULT_CACHE_PATH)
    if cache_kwargs.get("cache_path") is None:
        cache_kwargs["cache_path"] = DEFAULT_CACHE_PATH
    return run_flash_fusion_cache(query, df, client, r, **cache_kwargs, **planner_kwargs)
