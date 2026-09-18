"""The planner prefix must be byte-stable, self-contained, and cache-keyed.

Prefix caching is not an optimization the provider applies on request; it is a
property of the bytes we send. If a single character of the system message
varies across queries — a schema line, a timestamp, a re-ordered set — every
call is a cache miss and the ~10k-token vocabulary is billed at full price each
time. These tests fail loudly when that property is lost.
"""

from __future__ import annotations

import hashlib
import os
import re

from flashfusion.pipeline.operators import (
    ALL_OPERATOR_NAMES,
    FLASH_FUSION_PLANNER_PREFIX,
    OPERATOR_VOCABULARY_SPEC,
    OPERATOR_VOCABULARY_VERSION,
    PLAN_VERSION,
    PLANNER_PREFIX_SHA256,
    PLANNER_PREFIX_VERSION,
    build_planner_prefix,
    build_vocabulary_spec,
    planner_cache_key,
    planner_prefix_digest,
)
from flashfusion.prompts.templates import PLANNER_DYNAMIC_SUFFIX_TEMPLATE


def test_prefix_digest_matches_its_own_bytes() -> None:
    """The published digest must actually describe the published string."""
    assert (
        hashlib.sha256(FLASH_FUSION_PLANNER_PREFIX.encode("utf-8")).hexdigest()
        == PLANNER_PREFIX_SHA256
    )


def test_prefix_is_stable_across_processes() -> None:
    """A fresh interpreter, with a different hash seed, must produce the same
    bytes. Anything derived from set iteration order, dict identity, or the
    clock would diverge here — and would silently cost a cache miss per query.
    """
    import subprocess
    import sys

    env = {**os.environ, "PYTHONHASHSEED": "1"}
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from flashfusion.pipeline.operators import PLANNER_PREFIX_SHA256;"
            "print(PLANNER_PREFIX_SHA256)",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert out.stdout.strip() == PLANNER_PREFIX_SHA256


def test_prefix_carries_the_whole_vocabulary_and_its_versions() -> None:
    """The static half must be the *large* half — that is the point of caching."""
    assert OPERATOR_VOCABULARY_SPEC in FLASH_FUSION_PLANNER_PREFIX
    assert f"PLAN_VERSION: {PLAN_VERSION}" in FLASH_FUSION_PLANNER_PREFIX
    assert (
        f"OPERATOR_VOCABULARY_VERSION: {OPERATOR_VOCABULARY_VERSION}"
        in FLASH_FUSION_PLANNER_PREFIX
    )
    assert len(FLASH_FUSION_PLANNER_PREFIX) > 10_000


def test_prefix_contains_no_dynamic_placeholders() -> None:
    """Schema and question belong in the suffix; a placeholder here means the
    prefix is being formatted per query and can never be reused."""
    for placeholder in (
        "{column_metadata}",
        "{query}",
        "{operator_spec}",
        "{dataset}",
        "{schema_fingerprint}",
    ):
        assert placeholder not in FLASH_FUSION_PLANNER_PREFIX


def test_dynamic_suffix_holds_exactly_the_per_query_fields() -> None:
    for placeholder in ("{dataset}", "{schema_fingerprint}", "{column_metadata}", "{query}"):
        assert placeholder in PLANNER_DYNAMIC_SUFFIX_TEMPLATE
    # The suffix must not duplicate the vocabulary — that would defeat the split.
    assert OPERATOR_VOCABULARY_SPEC not in PLANNER_DYNAMIC_SUFFIX_TEMPLATE


def test_cache_key_partitions_by_model_and_environment() -> None:
    """A dev run must never be routed onto a production cache entry, and two
    models must never share one."""
    dev = planner_cache_key("qwen/qwen3-max", "dev")
    prod = planner_cache_key("qwen/qwen3-max", "prod")
    other = planner_cache_key("meta-llama/llama-3.3-70b-instruct", "dev")

    assert dev != prod
    assert dev != other
    assert PLANNER_PREFIX_VERSION in dev
    assert planner_cache_key("qwen/qwen3-max", "dev") == dev


def test_full_vocabulary_slice_is_byte_identical_to_the_spec() -> None:
    """Asking for every operator must return the hand-written spec untouched —
    otherwise the narrowing machinery would silently rewrite the contract that
    every existing benchmark result was produced under."""
    assert build_vocabulary_spec(ALL_OPERATOR_NAMES) == OPERATOR_VOCABULARY_SPEC
    assert build_planner_prefix(build_vocabulary_spec(ALL_OPERATOR_NAMES)) == (
        FLASH_FUSION_PLANNER_PREFIX
    )


def test_narrowed_slice_drops_only_the_excluded_operators() -> None:
    """A narrowed prefix must be strictly smaller, must still define every
    operator it kept, and must not mention any it dropped."""
    kept = ("FILTER_COMPARE", "AGGREGATE_COLUMN", "COUNT_ROWS", "SELECT_COLUMN")
    spec = build_vocabulary_spec(kept)

    assert len(spec) < len(OPERATOR_VOCABULARY_SPEC)
    for name in kept:
        assert f'"op":"{name}"' in spec
    for name in ("PREDICTIVE_PIPELINE", "CORRELATE_COLUMNS", "GROUP_AGGREGATE"):
        assert name not in spec


def test_narrowed_slice_is_byte_stable_and_distinctly_keyed() -> None:
    """Each vocabulary slice is its own cache entry, so each must hash stably
    and must not collide with the full-vocabulary entry."""
    kept = ("FILTER_COMPARE", "AGGREGATE_COLUMN", "COUNT_ROWS", "SELECT_COLUMN")
    first = build_planner_prefix(build_vocabulary_spec(kept))
    second = build_planner_prefix(build_vocabulary_spec(reversed(kept)))

    assert first == second
    assert planner_prefix_digest(first) != PLANNER_PREFIX_SHA256


def test_no_planning_prefix_excludes_planning_guidance() -> None:
    """No-planning variant keeps contract/output but drops planning guidance."""
    prefix = build_planner_prefix(include_planning_guidance=False)
    assert "PLANNING\n  Resolve every concept" in prefix
    assert "emit a single-step PREDICTIVE_PIPELINE plan" not in prefix
    assert "fixed-size intervals against a CONSTANT" not in prefix
    assert "SCOPE CHECK" in prefix
    assert "NO INVENTION" in prefix
    assert "Respond with a single JSON object and nothing else:" in prefix


def test_no_planning_prefix_is_stable_and_distinct() -> None:
    first = build_planner_prefix(include_planning_guidance=False)
    second = build_planner_prefix(include_planning_guidance=False)

    assert first == second
    assert planner_prefix_digest(first) != PLANNER_PREFIX_SHA256


def test_no_prompt_runtime_prefix_strips_vocabulary_guidance() -> None:
    """FF_NO_PROMPT keeps signatures and contracts, never planner hints.

    The no-prompt arm should keep only operator signatures plus the scope/output
    contracts. Every letter-number hint in the canonical vocabulary is derived
    here, so a newly added R*, W*, or X* hint cannot silently enter this arm.
    """
    from types import SimpleNamespace

    from flashfusion.baselines.flash_fusion_no_cache import (
        _planner_prefix_message,
    )
    from flashfusion.baselines.flash_fusion_no_prompt import POLICY

    hint_markers = set(re.findall(r"(?m)^([A-Z]+\d+)\.", OPERATOR_VOCABULARY_SPEC))
    assert hint_markers

    _, prefix = _planner_prefix_message(
        SimpleNamespace(session_key="smoke_no_prompt"),
        planner_guidance=POLICY.planner_guidance_mode,
    )

    assert not POLICY.planner_guidance
    assert '"op":"FILTER_COMPARE"' in prefix
    assert '"op":"PARALLEL_AGGREGATE"' in prefix
    for hint in hint_markers:
        assert f"{hint}." not in prefix
    for instructional_label in (
        "HARD RULES",
        "WORKED EXAMPLES",
        "INVALID PATTERN",
        "REJECTED PATTERNS",
        "USE FOR:",
        "USE WHEN:",
        "DO NOT USE",
        "CRITICAL:",
        "Example (",
        "REJECTED:",
        "CORRECT:",
    ):
        assert instructional_label not in prefix
    assert "Respond with a single JSON object and nothing else:" in prefix
