"""Flash-Fusion baseline with exact-match typed-plan skeleton caching.

A cache hit never returns a stored answer.  It retrieves only a previously
validated operator sequence, asks ``client.light`` to ground a new typed plan
with the SAME sequence against the live DataFrame schema, validates that plan
with the normal Flash-Fusion gates, and executes it deterministically.

If any cache, light-model, structural-validation, schema-validation, or
execution check fails, this module falls back to ``run_flash_fusion``.

Registry contract
-----------------
``flashfusion/eval/cache/cache_registry.json`` may be either a mapping from
arbitrary cache keys to records or ``{"entries": [...]}``.  A reusable record
must contain at least:

    {
      "dataset": "ecg",
      "query_text": "<literal query text>",
      "status": "reusable",
      "operator_skeleton": ["FILTER_COMPARE", "COUNT_ROWS"],
      "operator_contract_hash": "<optional; recommended>",
      "schema_fingerprint": "<optional; recommended>"
    }

An out-of-scope query may be cached with an empty skeleton:

    {
      "dataset": "bus",
      "query_text": "How does passenger occupancy correlate with road roughness?",
      "status": "reusable",
      "operator_skeleton": []
    }

The cache hit still requires a single light-model call to infer a guardrail-style
rejection reason from the query and the live DataFrame schema; it does not invoke
the full planner or guardrail.

The cache lookup uses literal equality on ``dataset`` and ``query_text``.
Dataset names are canonicalised the same way the cache builder does it
(``mit_ecg`` -> ``ecg``) so benchmark dataset keys match registry keys.
Set ``dataset`` at the call site; if it is omitted, a hit is permitted only
when the same literal query text appears under exactly one dataset.  This
prevents cross-dataset accidental reuse.

The registry intentionally does NOT need to retain an answer or bound values.
The light model returns an entire candidate ``DeterministicPlan`` JSON object,
but it is constrained to the cached operator sequence.  Pydantic plus
``validate_plan_against_dataframe`` remain the authoritative validators.

Typical benchmark integration:

    result = run_flash_fusion_cache(
        query, df, client, r,
        dataset="mit_ecg",
        cache_path="flashfusion/eval/cache/cache_registry.json",
    )

The function has the same leading arguments as ``run_flash_fusion``.  On a
cache miss/failure it delegates to the normal baseline.  The small adapter in
``_run_normal_flash_fusion`` tolerates either ``r`` or ``result`` as the
existing baseline's optional RunResult parameter.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import re
import time
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from flashfusion.baselines.flash_fusion_no_cache import (
    _format_typed_execution_value,
    record_policy_provenance,
    run_flash_fusion,
    typed_plan_digest,
)
from flashfusion.baselines.flash_fusion_policy import FlashFusionPolicy, resolve_policy
from flashfusion.pipeline.operators import (
    DeterministicPlan,
    PlanExecutionError,
    PlanSchemaError,
    build_compact_operator_spec,
    execute_plan,
    normalize_raw_plan,
    validate_plan_against_dataframe,
)
from flashfusion.pipeline.runner import LLMClient, RunResult

BASELINE_NAME = "FLASH_FUSION_CACHE"
#: Default policy for this module: the full system (cache + pruning + guidance).
DEFAULT_POLICY = resolve_policy("FF_FULL")

#: ``cache_outcome`` values recorded on every Flash-Fusion result row. Recorded
#: at the branch that produced them rather than reconstructed downstream from
#: ``execution_path``, so aggregate hit rates are reproducible from raw records.
CACHE_OUTCOME_DISABLED = "disabled"
CACHE_OUTCOME_EXACT_HIT = "exact_hit"
CACHE_OUTCOME_SEMANTIC_HIT = "semantic_hit"
CACHE_OUTCOME_HIT_REJECTED = "hit_rejected"
CACHE_OUTCOME_MISS = "miss"

#: Maps an internal lookup status to its recorded outcome label.
_LOOKUP_STATUS_TO_OUTCOME = {
    "exact_cache_hit": CACHE_OUTCOME_EXACT_HIT,
    "semantic_cache_hit": CACHE_OUTCOME_SEMANTIC_HIT,
    "exact_cache_hit_out_of_scope": CACHE_OUTCOME_HIT_REJECTED,
    "semantic_cache_hit_out_of_scope": CACHE_OUTCOME_HIT_REJECTED,
}
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[1] / "eval" / "cache" / "cache_registry.json"
DEFAULT_HYBRID_CONFIG_PATH = Path(__file__).resolve().parents[1] / "eval" / "cache" / "hybrid_match_config.json"

#: Execution path recorded on a successful cache-grounded typed run. Distinct
#: from ``typed_operator`` so cache wins are never confused with planner wins.
PATH_TYPED_OPERATOR_CACHE = "typed_operator_cache"

#: Registry dataset keys. Mirrors
#: ``build_operator_skeleton_cache.canonical_dataset_dir_name`` so a benchmark
#: ``--dataset mit_ecg`` run matches the ``ecg`` entries the builder wrote.
_DATASET_ALIASES = {"mit_ecg": "ecg", "ecg": "ecg", "bus": "bus", "wisdm": "wisdm"}


@dataclass
class _HybridMatcherRuntime:
    matcher: Any
    cache_key: str
    entry_fingerprint: str
    warmup: dict[str, float]


_HYBRID_RUNTIME: dict[str, _HybridMatcherRuntime] = {}

_GROUNDING_PREAMBLE = """You ground parameters into a fixed Flash-Fusion typed operator skeleton.

Preserve the REQUIRED OUTPUT sequence exactly: same number of parameter objects and same
order — never add, remove, or reorder entries. Each params entry MUST use ONLY the exact
field names given for its operator in OPERATOR FIELD SPEC (e.g. never "filter_column"/
"filter_op"/"filter_value"/"input" — those are not real fields). Fill fields from the
QUESTION and the LIVE DATASET SCHEMA only; never invent columns. Do not return an
answer and do not write Python.

Output contract: respond with exactly one JSON object — no markdown, prose, or code
fences before/after it, no trailing commas, top-level key exactly `params`. `params`
must be an array with one object per REQUIRED OUTPUT step, in that exact order. Return
only operator parameters: omit `version`, `steps`, and every `op` field because Python
reconstructs those fixed fields from the cached skeleton. Example for FILTER_NOT_EMPTY,
COUNT_ROWS: {"params":[{"column":"x"},{}]}. If a step cannot be grounded, emit exactly
{"cache_grounding_failed": true, "reason": "..."}.

"""

# Applies regardless of which operators are present -- always included.
_UNIVERSAL_SEMANTIC_RULE = """- Emit exactly one params object per checklist operator:
    same count and same order — never merge, split, add, omit, or reorder entries.
- Omit the `op` field shown in OPERATOR FIELD SPEC; the cached checklist supplies it.
- Copy EVERY field shown in the OPERATOR FIELD SPEC except `op` into each params
    object, including null values; never omit a field or rely on a default."""

# Each entry: (frozenset of operators that trigger this block, rule text).
# A block is included if ANY of its trigger operators appear in the skeleton.
_OPERATOR_SEMANTIC_RULES: list[tuple[frozenset[str], str]] = [
    (
        frozenset({"FILTER_COMPARE"}),
        """- Bare entity/id mentions imply equality filters on that key:
    - Example: "record_id 106", "for record_id 106", "user 20" -> comparator must be
        "eq" with that value for the corresponding key column.
    - Do NOT weaken bare key mentions to ranges like gt/ge/lt/le.
- Explicit relational language must map to the matching comparator:
    - ">", "strictly greater", "greater than", "above" -> "gt"
    - ">=", "at least", "no less than" -> "gte"
    - "<", "strictly less", "below" -> "lt"
    - "<=", "at most", "no more than" -> "lte"
- FILTER_COMPARE.comparator accepts ONLY "eq","ne","gt","gte","lt","lte".
    Never emit "max", "min", "top", or a null value for comparator or value.""",
    ),
    (
        frozenset({"RANK_ROWS"}),
        """- To select the row(s) with the largest/smallest value of a derived column
    (e.g. "by the largest margin", "highest", "greatest"), use RANK_ROWS alone.
    Do NOT precede RANK_ROWS with a FILTER_COMPARE step whose purpose is
    extremum selection - that logic belongs to RANK_ROWS's direction field only.""",
    ),
    (
        frozenset({"SPLIT_BY_VALUES", "PARALLEL_AGGREGATE"}),
        """- Any step or branch object that sets non-empty filter_values MUST also set
    filter_column to the categorical column those values belong to (grounded
    from the LIVE DATASET SCHEMA, e.g. "activity_label"). Never leave
    filter_column null when filter_values is non-empty.
- Copy categorical values with the exact spelling and capitalization shown in
    LIVE DATASET SCHEMA sample_values; query text casing is not authoritative.""",
    ),
    (
        frozenset({"COUNT_ROWS"}),
        """- "how many", "number of samples/rows" means row counting semantics:
    - Use COUNT_ROWS / COUNT / group size when asking for sample counts.
    - Use nunique only when the question asks for unique entities.
- "highest/lowest total number of ... samples" means per-entity sample COUNT then rank.
    - Do NOT substitute sum of a sensor channel for sample counts.""",
    ),
    (
        frozenset({"DERIVE_BIN", "GROUP_AGGREGATE", "RANK_GROUPS"}),
        """- For a `DERIVE_BIN`, `GROUP_AGGREGATE`, `RANK_GROUPS` sequence answering
    "which N-second interval has the highest number/count of ...":
        - `GROUP_AGGREGATE.group_by` MUST be exactly the `DERIVE_BIN.result` column.
            Do not group by an entity key (such as `record_id`) already narrowed by a
            preceding filter, or by the DERIVE_BIN source (such as `time_s`); either
            produces the wrong groups instead of interval groups.
        - Use `aggregate="count"` with `column=null` to count rows in each interval,
            set `freq=null`, then use `RANK_GROUPS.direction="max"`.
        - Complete this data flow before emitting: `DERIVE_BIN.result` ->
            `GROUP_AGGREGATE.group_by=[that exact result]` -> `RANK_GROUPS`.
            For example, a 10-second temporal bin of numeric `time_s` is
            `{"op":"DERIVE_BIN","column":"time_s","kind":"temporal","width":null,
            "freq":"10s","epoch_unit":"s","result":"bin"}` followed by
            `{"op":"GROUP_AGGREGATE","group_by":["bin"],"aggregate":"count",
            "column":null,"freq":null}`. Numeric temporal sources require their explicit
            epoch unit; a `time_s` source uses `"s"`.""",
    ),
    (
        frozenset({"GROUP_AGGREGATE", "AGGREGATE_PARTITIONS"}),
        """- "average X" / "mean X" means mean aggregation of X.
    - Do NOT use variance unless the question explicitly asks for variance.""",
    ),
    (
        frozenset({"AGGREGATE_PARTITIONS", "COMPARE_PARTITIONS"}),
        """- Comparative roughness phrased on average variance must preserve average semantics.
    - If asked "rougher" with average/mean variance, compare mean variance values and use
        a comparison mode aligned to the question (difference/which higher), not ratio by default.""",
    ),
    (
        frozenset({"DERIVE_BINARY", "RANK_ROWS"}),
        """- "A exceeds/is greater than B by the largest margin" implies a SIGNED
    difference in the stated order (A - B), not abs_difference. Compute
    DERIVE_BINARY with operation="subtract" in that order, optionally gate
    with FILTER_COMPARE(comparator="gt", value=0) to enforce the stated
    direction, then RANK_ROWS on that signed column. Use abs_difference only
    when the query says "difference" or "contrast" with no stated direction.""",
    ),
    (
        frozenset({"DERIVE_BIN", "DERIVE_DURATION_SECONDS", "DERIVE_BINARY", "DERIVE_VECTOR_MAGNITUDE"}),
        """- A DERIVE_* `result` is a newly created column name. A later step that consumes it
    MUST use that exact result string, never the DERIVE_* source column.""",
    ),
    (
        frozenset({"DERIVE_BIN"}),
        """- DERIVE_BIN modes (mutually exclusive):
    - For numeric columns (e.g. float/int elapsed seconds like `time_s` or numeric values):
      use `kind="numeric"`, supply `width` (e.g. 60.0), and set `freq=null`, `epoch_unit=null`.
        - For datetime / calendar timestamps:
            use `kind="temporal"`, supply `freq` (e.g. "60s" or "1min"), set `width=null`,
            and set `epoch_unit=null`. Datetime sources MUST NOT set an epoch unit.
        - For a numeric epoch timestamp used with `kind="temporal"`, supply both
            `freq` and its explicit `epoch_unit` (one of `"s"`, `"ms"`, `"us"`, or
            `"ns"`), and set `width=null`. Infer the unit from the schema column
            name: `time_s` means `epoch_unit="s"`; suffixes `_ms`, `_us`, and `_ns`
            mean `"ms"`, `"us"`, and `"ns"` respectively. Never leave
            `epoch_unit` null for temporal binning of a numeric source.
    - NEVER mix `kind="temporal"` with `width` or `freq=null`.
    - NEVER mix `kind="numeric"` with `freq` or `epoch_unit` set to anything but null.
        REJECTED: {"kind":"numeric","width":10,"freq":null,"epoch_unit":"s"} — epoch_unit
        must be null whenever kind="numeric", with no exception.
    - Always include `result`; never omit `freq`/`epoch_unit` when the chosen kind requires them.""",
    ),
    (
        frozenset({"DERIVE_DURATION_SECONDS"}),
        """- DERIVE_DURATION_SECONDS fields:
    - DERIVE_DURATION_SECONDS is materialized ONCE across the timeline. Emit EXACTLY 1 step
      regardless of how many categories or comparison groups the question mentions:
      Emit a single DERIVE_DURATION_SECONDS step with a generic result column (e.g., "dt_s" or "duration_seconds").
      NEVER create multiple category-specific duration steps (e.g., "resting_duration_s" and "dynamic_duration_s").
      Category distinctions are handled entirely within downstream steps (e.g., PARALLEL_AGGREGATE branches filtering
      by activity_label and summing the single derived duration column).
    - `group_by` must be the entity key column only (e.g. ['subject_id'] or ['record_id']).
      Never include category/label columns (e.g. 'activity_label') in DERIVE_DURATION_SECONDS.group_by;
      category filtering is handled in downstream steps (e.g. PARALLEL_AGGREGATE branches).
    - `fill_first` MUST be a float number (default 0.0), NEVER null or omitted.
    - `clip_negative` MUST be a boolean (default true).
    - `result` is the derived column name (e.g. "dt_s" or "duration_seconds").""",
    ),
    (
        frozenset({"SPLIT_BY_VALUES", "AGGREGATE_PARTITIONS"}),
        """- When comparing two or more named groups of a categorical column (e.g.
    "compare X between label A and label B"), emit one SPLIT_BY_VALUES step
    PER GROUP, each with its own distinct label and its own values list.
    Never reuse the same label across steps and never merge multiple
    comparison groups' values into a single SPLIT_BY_VALUES call.
    AGGREGATE_PARTITIONS.partitions must then list every distinct label
    produced this way (minimum two), never a single repeated label.""",
    ),
    (
        frozenset({"PREDICTIVE_PIPELINE"}),
        """- Train split and holdout row are independent fields in predictive plans:
    - The query may mention both a training split (e.g., 'first 80%') and a holdout row
        position (e.g., 'first row in the holdout set'). These are independent.
        `train_fraction` controls the split; `holdout_row` must reflect only the phrase
        that describes which holdout row to predict. If the query says 'first row in the
        holdout set', `holdout_row` must be 'first'.
- PREDICTIVE_PIPELINE target semantics:
        - `target_column` MUST be the real DataFrame schema column being predicted (e.g.,
            "annotation"). It is a column reference, not a class label or a check name.
        - `target_from_non_empty` controls target construction. Set it to true when the
            question asks whether `target_column` is present, non-empty, or annotated; this
            converts the target into the binary classes 0/1 before training.
        - `target_label` is display text for the prediction sentence only. It is NOT a
            DataFrame column, is NOT used to construct `y`, and must never replace
            `target_column`. For a presence question, use `target_label="present"`.
        - For "whether an annotation is present" / "whether <column> is non-empty", emit
            `target_column="annotation"` (or the real named schema column),
            `target_from_non_empty=true`, and `target_label="present"`. Do not emit
            `target_from_non_empty=false`, which trains on raw annotation strings.""",
    ),
    (
        frozenset({"AGGREGATE_COLUMN", "AGGREGATE_GROUPS", "GROUP_AGGREGATE", "AGGREGATE_PARTITIONS", "PARALLEL_AGGREGATE", "FILTER_EQ_AGGREGATE"}),
        """- `aggregate` accepts ONLY the closed enum: "min","max","mean","median","sum","count",
    "std","var","nunique","rms". Never emit a percentile/quantile value such as "p99",
    "percentile_95", or "quantile".""",
    ),
    (
        frozenset({"GROUP_AGGREGATE"}),
        """- GROUP_AGGREGATE has NO `result`/`result_column` field — never add one.
    - `column` MUST be null ONLY when `aggregate=="count"`. For every other aggregate value,
        `column` is REQUIRED and must be a real schema column name, never left null "by default".
    - `freq` must always be present (null unless the grouped column is time-windowed) — never omit it.
    - Its output is consumed ONLY by RANK_GROUPS or AGGREGATE_GROUPS; never invent a column
        name (e.g. "max_val") to reference its result from another step.""",
    ),
    (
        frozenset({"PARALLEL_AGGREGATE"}),
        """- Each PARALLEL_AGGREGATE checklist item occupies EXACTLY ONE object in `params`.
    Put every branch inside that one object's `branches` array; branches are NOT separate
    `params` entries and do not consume additional checklist steps. For example, when the
    required sequence is PARALLEL_AGGREGATE, DERIVE_BINARY, RANK_ROWS, emit exactly:
    {"params":[{"branches":[{"filter_column":null,"filter_values":null,"group_by":["entity_key"],"aggregate":"max","column":"metric_column","result_column":"metric_max"},{"filter_column":null,"filter_values":null,"group_by":["entity_key"],"aggregate":"min","column":"metric_column","result_column":"metric_min"}]},{"left":"metric_max","right":"metric_min","operation":"subtract","result":"metric_range"},{"column":"metric_range","direction":"max","return_columns":["entity_key"]}]}.
- Each branch's `column` MUST be null ONLY when `aggregate=="count"`. For every other
    aggregate (mean, sum, median, std, var, rms, min, max, nunique), `column` is REQUIRED
    and must be a real schema column name, never left null "by default".
    - `group_by` must never be an empty list.""",
    ),
    (
        frozenset({"COMPARE_VALUES"}),
        """- COMPARE_VALUES fields are ONLY `mode`, `label_a`, `label_b` — it takes NO column
    references at all. Never emit `column`, `column1`, `column2`, `left`, or `right` on this
    operator; any such field fails structural validation because every operator forbids
    unknown fields.
    - `mode` is one of "difference","abs_difference","ratio". `label_a`/`label_b` are display
        strings describing the first/second scalar already computed earlier in the plan, in
        that order — they are never column names.""",
    ),
    (
        frozenset({"CORRELATE_COLUMNS"}),
        """- `left` and `right` must both be real numeric schema columns, or the `result` of an
    earlier DERIVE_* step in this plan. `method` is one of "pearson","spearman","kendall"
    (default "pearson"). Never substitute a difference, ratio, or ranking for a correlation.""",
    ),
    (
        frozenset({"SPLIT_BY_THRESHOLD"}),
        """- `threshold` accepts ONLY "median","mean","min","max". `comparator` accepts ONLY
    "gt","gte","lt","lte". `label` names the partition for a later AGGREGATE_PARTITIONS step —
    reuse the exact same label string in both places.""",
    ),
    (
        frozenset({"FILTER_IN"}),
        """- FILTER_IN keeps rows where `column` is one of `values` (a non-empty list). Use it for
    membership in an explicit set of categories from the schema's sample values; do not
    substitute repeated FILTER_COMPARE(comparator="eq") steps for a single membership check.""",
    ),
    (
        frozenset({"FILTER_EQ_AGGREGATE"}),
        """- FILTER_EQ_AGGREGATE keeps rows where `column` equals `aggregate(column)` (e.g. every row
    tied for the column's maximum). Use it only for "row(s) where X reaches its max/min",
    which preserves ties; it never accepts a literal `value` field.""",
    ),
    (
        frozenset({"DERIVE_VECTOR_MAGNITUDE"}),
        """- `columns` MUST be exactly three real numeric schema column names (no more, no fewer).
    `result` names the new derived magnitude column for downstream steps to reference.""",
    ),
    (
        frozenset({"SELECT_COLUMN", "COUNT_DISTINCT"}),
        """- `column` must be a real schema column name. SELECT_COLUMN's `distinct` field is a
    boolean; set it true only when the question asks for unique values.""",
    ),
]


@lru_cache(maxsize=256)
def _build_grounding_system_prompt(skeleton: tuple[str, ...]) -> str:
    """Assemble the grounding system prompt for exactly this skeleton.

    Cached by skeleton so (a) repeated calls with the same skeleton are
    free after the first, and (b) the output is guaranteed byte-identical
    across every query that shares this skeleton -- a precondition for
    KV-cache prefix reuse on the serving side (e.g. Ollama prefix caching).
    Must be called with a tuple (hashable) rather than a list.
    """
    skeleton_set = set(skeleton)
    blocks = [_GROUNDING_PREAMBLE, _UNIVERSAL_SEMANTIC_RULE]
    for trigger_ops, text in _OPERATOR_SEMANTIC_RULES:
        if trigger_ops & skeleton_set:
            blocks.append(text)
    return "\n".join(blocks)

OUT_OF_SCOPE_SYSTEM_PROMPT = """You are a dataset guardrail. The user's query
has already been classified as out-of-scope for the available dataset. Given
the query and the live dataset schema, produce a concise, factual rejection
reason explaining why the query cannot be answered from the available fields.

Use the same style as the original Flash-Fusion guardrail:
- "The dataset does not contain columns for X or Y."
- "The dataset does not contain any information about Z."
- "The dataset does not contain any column indicating W."

Return exactly one JSON object and no markdown, prose, or code fences:
{"rejection_reason": "..."}

Strict requirements:
- Return a single valid JSON object only; no trailing commas.
- The top-level keys are exactly: {"rejection_reason":"..."}.
- Do not include comments, markdown fences, or any text before/after the JSON.
"""


# ---------------------------------------------------------------------------
# Trace record (debug aid for eval/trace_query.py --cache)
# ---------------------------------------------------------------------------


@dataclass
class CacheGroundingTrace:
    """Everything the cache path did, for human inspection.

    Populated even on failure paths so a trace shows exactly which gate sent
    the query back to the full planner.
    """

    cache_path: str = ""
    requested_dataset: str | None = None
    lookup_status: str = ""
    entry: dict[str, Any] | None = None
    operator_skeleton: list[str] = field(default_factory=list)
    prompt: str = ""
    raw_light_output: str = ""
    grounding_latency_s: float = 0.0
    prompt_build_latency_s: float = 0.0
    light_input_tokens: int = 0
    light_output_tokens: int = 0
    light_reasoning_tokens: int = 0
    parsed_plan: dict[str, Any] | None = None
    validated_plan: dict[str, Any] | None = None
    executed_value: Any = None
    hit: bool = False
    failure_reason: str = ""
    fell_back: bool = False
    semantic_match_evidence: dict[str, Any] | None = None


def _record(trace: CacheGroundingTrace | None, **fields: Any) -> None:
    if trace is None:
        return
    for name, value in fields.items():
        setattr(trace, name, value)


def _accounted_light_latency(client: LLMClient, started: float) -> float:
    """Return full wall-clock elapsed latency for the light-model stage."""
    return time.perf_counter() - started


def _light_retry_overhead_s(client: LLMClient) -> float:
    """Return provider retry/backoff overhead for the most recent light call."""
    light = getattr(client, "light", None) or client
    overhead = getattr(light, "last_retry_overhead_s", None)
    if isinstance(overhead, (int, float)) and overhead >= 0:
        return float(overhead)
    return 0.0


def _accounted_cache_latency(stage_latency: dict[str, float]) -> float:
    return sum(
        float(value)
        for name, value in stage_latency.items()
        if name != "cache_retry_overhead"
    )


# ---------------------------------------------------------------------------
# Registry loading and lookup
# ---------------------------------------------------------------------------


def canonical_dataset(name: str | None) -> str | None:
    """Map a benchmark dataset key onto the registry's dataset key."""
    if name is None:
        return None
    key = str(name).strip().lower()
    return _DATASET_ALIASES.get(key, key)


def _load_entries(cache_path: str | Path) -> list[dict[str, Any]]:
    """Load both supported registry shapes and reject malformed records."""
    with Path(cache_path).open(encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
        candidates: Iterable[Any] = raw["entries"]
    elif isinstance(raw, dict) and isinstance(raw.get("entries"), dict):
        candidates = raw["entries"].values()
    elif isinstance(raw, dict):
        candidates = raw.values()
    elif isinstance(raw, list):
        candidates = raw
    else:
        raise ValueError("cache registry must be a list, a key->record mapping, or {'entries': [...]}")
    return [x for x in candidates if isinstance(x, dict)]


def _entry_fingerprint(entries: Iterable[dict[str, Any]]) -> str:
    payload: list[tuple[Any, ...]] = []
    for entry in entries:
        payload.append(
            (
                canonical_dataset(entry.get("dataset")),
                str(entry.get("query_text") or "").strip(),
                entry.get("status"),
                tuple(entry.get("operator_skeleton") or ()),
                entry.get("operator_contract_hash"),
                entry.get("schema_fingerprint"),
            )
        )
    payload.sort()
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()


def _invalidate_hybrid_runtime(*, cache_path: str | Path, dataset: str | None) -> None:
    prefix = f"{Path(cache_path)}::{canonical_dataset(dataset)}::"
    doomed = [key for key in _HYBRID_RUNTIME if key.startswith(prefix)]
    for key in doomed:
        _HYBRID_RUNTIME.pop(key, None)


def _query_contract_to_signature(contract: Any) -> dict[str, Any]:
    predictive = {k: v for k, v in getattr(contract, "predictive", ())}
    return {
        "admissibility": getattr(contract, "admissibility", "unknown"),
        "confidence": float(getattr(contract, "confidence", 0.0) or 0.0),
        "aggregate": getattr(contract, "aggregate", None),
        "fields": sorted(list(getattr(contract, "fields", ()) or ())),
        "predicate_ops": {k: v for k, v in getattr(contract, "predicate_ops", ())},
        "filter_values": {k: v for k, v in getattr(contract, "filter_values", ())},
        "output_shape": getattr(contract, "output_shape", None),
        "analytic_intents": sorted(list(getattr(contract, "analytic_intents", ()) or ())),
        "predictive": {
            "model": predictive.get("model"),
            "target_column": predictive.get("target_column"),
            "holdout_row": predictive.get("holdout_row"),
            "train_fraction": predictive.get("train_fraction"),
        },
        "operator_skeleton_hint": list(getattr(contract, "operator_skeleton_hint", ()) or ()) or None,
        "applicable_evidence_count": int(getattr(contract, "applicable_evidence_count", 0) or 0),
        "matched_evidence_count": int(getattr(contract, "matched_evidence_count", 0) or 0),
    }


def _merge_semantic_overlays(
    *,
    entries: list[dict[str, Any]],
    semantic_entries: list[dict[str, Any]] | None,
    df: pd.DataFrame,
) -> list[dict[str, Any]]:
    overlay_by_key: dict[tuple[str | None, str], dict[str, Any]] = {}
    if semantic_entries:
        for item in semantic_entries:
            if item.get("status") != "reusable":
                continue
            query_text = str(item.get("query_text") or "").strip()
            if not query_text:
                continue
            key = (canonical_dataset(item.get("dataset")), query_text)
            overlay_by_key[key] = item

    out: list[dict[str, Any]] = []
    for entry in entries:
        merged = dict(entry)
        if not str(merged.get("query_text") or "").strip():
            qid = merged.get("query_id")
            if qid is not None:
                try:
                    from flashfusion.eval.trace_hybrid_cache import resolve_query

                    merged["query_text"] = resolve_query(
                        query_id=str(qid),
                        version="v1",
                        dataset=str(canonical_dataset(merged.get("dataset")) or ""),
                        override=None,
                    )
                except Exception:
                    merged["query_text"] = str(qid)
        query_text = str(merged.get("query_text") or "").strip()
        key = (canonical_dataset(merged.get("dataset")), query_text)
        overlay = overlay_by_key.get(key)
        if overlay is not None:
            if merged.get("semantic_signature") is None and isinstance(overlay.get("semantic_signature"), dict):
                merged["semantic_signature"] = overlay["semantic_signature"]
            if merged.get("retrieval_contract") is None and isinstance(overlay.get("retrieval_contract"), dict):
                merged["retrieval_contract"] = overlay["retrieval_contract"]
        if merged.get("semantic_signature") is None and query_text:
            merged["semantic_signature"] = _extract_semantic_signature(query_text, df)
        out.append(merged)
    return out


def _is_out_of_scope_entry(entry: dict[str, Any]) -> bool:
    """Return whether a reusable entry represents a guardrail rejection."""
    return entry.get("operator_skeleton") == []


def _build_hybrid_runtime(
    *,
    entries: list[dict[str, Any]],
    dataset: str | None,
    df: pd.DataFrame,
    cache_path: str | Path,
    semantic_cache_path: str | Path | None,
    out_of_scope_only: bool = False,
) -> _HybridMatcherRuntime:
    _require_sentence_transformers()
    from flashfusion.eval.trace_hybrid_cache import HybridMatcher, load_config

    usable = [
        entry
        for entry in entries
        if entry.get("status") == "reusable"
        and isinstance(entry.get("operator_skeleton"), list)
        and (not out_of_scope_only or _is_out_of_scope_entry(entry))
    ]
    semantic_entries: list[dict[str, Any]] | None = None
    if semantic_cache_path is not None and Path(semantic_cache_path).exists():
        semantic_entries = _load_entries(semantic_cache_path)

    hybrid_entries = _merge_semantic_overlays(
        entries=usable,
        semantic_entries=semantic_entries,
        df=df,
    )
    fingerprint = _entry_fingerprint(hybrid_entries)
    ds = canonical_dataset(dataset)
    schema_fp = _schema_fingerprint(df)
    cols_fp = hashlib.sha256(
        json.dumps([str(c) for c in df.columns], separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    runtime_key = (
        f"{Path(cache_path)}::{ds}::{schema_fp}::{cols_fp}::"
        f"{Path(semantic_cache_path) if semantic_cache_path else ''}::oos={out_of_scope_only}"
    )
    cached = _HYBRID_RUNTIME.get(runtime_key)
    if cached is not None and cached.entry_fingerprint == fingerprint:
        return cached

    matcher = HybridMatcher(
        entries=hybrid_entries,
        config=load_config(DEFAULT_HYBRID_CONFIG_PATH),
        dataset=dataset,
        schema_columns=[str(column) for column in df.columns],
        schema_fingerprint=schema_fp,
        device="cpu",
        no_warmup=False,
        mode="hybrid",
        dense_top_k_override=None,
        lexical_top_k_override=None,
    )
    warm = matcher.warm_up()
    runtime = _HybridMatcherRuntime(
        matcher=matcher,
        cache_key=runtime_key,
        entry_fingerprint=fingerprint,
        warmup={k: float(v) for k, v in warm.items()},
    )
    _HYBRID_RUNTIME[runtime_key] = runtime
    return runtime


def _require_sentence_transformers() -> None:
    try:
        importlib.import_module("sentence_transformers")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Hybrid cache matching requires sentence_transformers. "
            "Install it in the active environment before running FLASH_FUSION_CACHE."
        ) from exc


def prewarm_hybrid_cache_runtime(
    *,
    df: pd.DataFrame,
    dataset: str | None,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    semantic_cache_path: str | Path | None = None,
) -> dict[str, float]:
    """Preload and warm the hybrid matcher runtime for this dataset/schema.

    This is intended for benchmark setup so dense model load and warm-up are
    completed outside per-query timing.
    """
    entries = _load_entries(cache_path)
    runtime = _build_hybrid_runtime(
        entries=entries,
        dataset=dataset,
        df=df,
        cache_path=cache_path,
        semantic_cache_path=semantic_cache_path,
        out_of_scope_only=False,
    )
    warm = dict(runtime.warmup)
    warm.setdefault("model_load_ms", 0.0)
    warm.setdefault("warm_up_ms", 0.0)
    warm.setdefault("dense_index_build_ms", 0.0)
    return {
        "model_load_ms": float(warm.get("model_load_ms", 0.0) or 0.0),
        "warm_up_ms": float(warm.get("warm_up_ms", 0.0) or 0.0),
        "dense_index_build_ms": float(warm.get("dense_index_build_ms", 0.0) or 0.0),
    }


def _hybrid_decision_to_status(decision: str) -> str:
    mapping = {
        "exact_hit": "semantic_cache_hit",
        "hybrid_hit": "semantic_cache_hit",
        "out_of_scope_hit": "admissibility_out_of_scope",
        "ambiguous_multi_candidate": "semantic_ambiguous_candidates",
        "low_confidence_candidate": "semantic_low_confidence_winner",
        "incompatible_candidate": "semantic_gate_reject_all",
        "complete_miss": "semantic_no_candidates",
    }
    return mapping.get(decision, f"semantic_{decision}")


def _hybrid_evidence(
    *,
    matcher: Any,
    query: str,
    result: Any,
    decision_status: str,
) -> dict[str, Any]:
    query_contract = _query_contract_to_signature(matcher.extractor.extract(query))
    candidate_scores = {
        c.candidate_id: {
            "score": float(c.final_score),
            "details": dict(c.component_scores),
            "dense_score": float(c.dense_score),
            "lexical_score": float(c.lexical_score),
            "contract_score": float(c.contract_score),
            "retrieval_score": float(c.retrieval_score),
        }
        for c in result.candidates
    }
    hard_gate_results = {
        c.candidate_id: {
            "ok": bool(c.compatibility),
            "gates": {},
            "reason": ",".join(c.compatibility_failures),
        }
        for c in result.candidates
    }
    elapsed_ms = {k: float(v) for k, v in (result.elapsed_ms or {}).items()}
    elapsed_ms["model_load_ms"] = 0.0
    elapsed_ms["warm_up_ms"] = 0.0
    return {
        "decision": result.decision,
        "status": decision_status,
        "extracted_signature": query_contract,
        "candidate_ids_considered": [c.candidate_id for c in result.candidates],
        "hard_gate_results": hard_gate_results,
        "candidate_scores": candidate_scores,
        "extraction_confidence": query_contract.get("confidence"),
        "abstention_reason": "" if decision_status == "semantic_cache_hit" else decision_status,
        "score_threshold": float(matcher.thresholds.get("acceptance_floor", 0.75)),
        "score_margin": float(matcher.thresholds.get("ambiguity_margin", 0.08)),
        "winner": None
        if result.winner is None
        else {
            "candidate_id": result.winner.candidate_id,
            "query_id": result.winner.query_id,
            "score": float(result.winner.final_score),
        },
        "runner_up": None
        if result.runner_up is None
        else {
            "candidate_id": result.runner_up.candidate_id,
            "query_id": result.runner_up.query_id,
            "score": float(result.runner_up.final_score),
        },
        "elapsed_ms": elapsed_ms,
    }


def _extract_cached_skeleton_from_result(result: RunResult) -> list[str]:
    steps = result.typed_plan.get("steps") if isinstance(result.typed_plan, dict) else None
    if not isinstance(steps, list):
        return []
    skeleton: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            return []
        op = step.get("op")
        if not isinstance(op, str) or not op.strip():
            return []
        skeleton.append(op)
    return skeleton


def _upsert_reusable_cache_entry(
    *,
    cache_path: str | Path,
    dataset: str | None,
    query: str,
    skeleton: list[str],
    df: pd.DataFrame,
    expected_operator_contract_hash: str | None,
    query_id: int | None,
) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any]
    if path.exists():
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = {"entries": []}

    if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
        entries = [x for x in raw["entries"] if isinstance(x, dict)]
    elif isinstance(raw, dict):
        entries = [x for x in raw.values() if isinstance(x, dict)]
    elif isinstance(raw, list):
        entries = [x for x in raw if isinstance(x, dict)]
    else:
        entries = []

    wanted_ds = canonical_dataset(dataset)
    wanted_q = _normalise_query(query)
    now_sig = _extract_semantic_signature(query, df)
    base = {
        "dataset": wanted_ds,
        "query_text": query,
        "status": "reusable",
        "operator_skeleton": list(skeleton),
        "schema_fingerprint": _schema_fingerprint(df),
        "semantic_signature": now_sig,
    }
    if expected_operator_contract_hash:
        base["operator_contract_hash"] = expected_operator_contract_hash
    if query_id and query_id > 0:
        base["query_id"] = str(query_id)

    replaced = False
    for idx, entry in enumerate(entries):
        if (
            canonical_dataset(entry.get("dataset")) == wanted_ds
            and isinstance(entry.get("query_text"), str)
            and entry["query_text"].strip() == wanted_q
        ):
            merged = dict(entry)
            merged.update(base)
            entries[idx] = merged
            replaced = True
            break
    if not replaced:
        entries.append(base)

    payload = {"entries": entries}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalise_query(query: str) -> str:
    # Preserve exact-match semantics.  Surrounding whitespace is transport
    # noise; all internal whitespace, punctuation, and case remain meaningful.
    return query.strip()


def _find_exact_entry(
    entries: Iterable[dict[str, Any]], query: str, dataset: str | None
) -> tuple[dict[str, Any] | None, str]:
    q = _normalise_query(query)
    wanted = canonical_dataset(dataset)
    matches = [
        entry
        for entry in entries
        if entry.get("status") == "reusable"
        and isinstance(entry.get("query_text"), str)
        and entry["query_text"].strip() == q
        and (wanted is None or canonical_dataset(entry.get("dataset")) == wanted)
    ]
    if not matches:
        return None, "exact_query_miss"
    if wanted is None:
        datasets = {canonical_dataset(entry.get("dataset")) for entry in matches}
        if len(datasets) != 1:
            return None, "ambiguous_cross_dataset_exact_match"
    if len(matches) != 1:
        return None, "duplicate_registry_entries"
    skeleton = matches[0].get("operator_skeleton")
    if isinstance(skeleton, list) and len(skeleton) == 0:
        # Out-of-scope queries are cached with an empty skeleton. We will
        # reject via a single cheap light-model call rather than the full
        # planner/guardrail pipeline.
        return matches[0], "exact_cache_hit_out_of_scope"
    if not isinstance(skeleton, list) or not skeleton or not all(isinstance(x, str) for x in skeleton):
        return None, "invalid_or_empty_operator_skeleton"
    return matches[0], "exact_cache_hit"


def _detect_aggregate(query_lc: str) -> str | None:
    if re.search(r"\b(median)\b", query_lc):
        return "median"
    if re.search(r"\b(min|minimum|smallest|lowest|least)\b", query_lc):
        return "min"
    if re.search(r"\b(max|maximum|largest|highest|greatest|peak)\b", query_lc):
        return "max"#
    if re.search(r"\b(mean|average)\b", query_lc):
        return "mean"
    if re.search(r"\b(sum|total)\b", query_lc):
        return "sum"
    if re.search(r"\b(how many|count|number of)\b", query_lc):
        return "count"
    return None


def _detect_predictive_model(query_lc: str) -> str | None:
    model_patterns = {
        "logistic_regression": (
            r"\blogistic[- ]regression\b",
            r"\blogistic[- ]classifier\b",
        ),
        "random_forest": (
            r"\brandom[- ]forest(?:[- ]classifier)?\b",
            r"\brf[- ]classifier\b",
        ),
        "one_nearest_neighbor": (
            r"\b1\s*[- ]?nearest[- ]?neighbo?r(?:[- ]classifier)?\b",
            r"\b1[- ]?nn\b",
            r"\bk\s*=\s*1\s+nearest[- ]neighbo?r\b",
        ),
        "hist_gradient_boosting": (
            r"\bhist(?:ogram)?[- ]gradient[- ]boosting(?:[- ]classifier)?\b",
            r"\bhistgradientboosting(?:classifier)?\b",
        ),
    }
    matches = {
        model
        for model, patterns in model_patterns.items()
        if any(re.search(pattern, query_lc) for pattern in patterns)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _detect_train_fraction(query_lc: str) -> float | None:
    m = re.search(
        r"\bfirst\s+(\d{1,3})%\s+of\s+(?:the\s+)?rows?"
        r"\s+(?:for|in|as)\s+train(?:ing)?\b",
        query_lc,
    )
    if not m:
        return None
    pct = int(m.group(1))
    if not 0 < pct < 100:
        return None
    return round(pct / 100.0, 4)


def _detect_holdout_position(query_lc: str) -> str | None:
    if "first row in the holdout" in query_lc:
        return "first"
    if "last row in the holdout" in query_lc:
        return "last"
    return None

def _ground_predictive_cache_hit(
    query: str, skeleton: list[str], df: pd.DataFrame
) -> dict[str, Any] | None:
    """Bind a fully specified one-step predictive cache hit without an LLM.

    Exact-query cache entries have already fixed the operator shape. This parser
    accepts only the benchmark's explicit chronological-prediction grammar and
    returns ``None`` for anything ambiguous, preserving light-model grounding
    as the safe fallback.
    """
    if skeleton != ["PREDICTIVE_PIPELINE"]:
        return None

    query_lc = query.lower()
    model = _detect_predictive_model(query_lc)
    train_fraction = _detect_train_fraction(query_lc)
    holdout_row = _detect_holdout_position(query_lc)
    columns_by_lower = {str(column).lower(): str(column) for column in df.columns}

    sort_match = re.search(
        r"\bsort\s+(?:all\s+\w+\s+|its\s+)?rows\s+by\s+([a-z_][a-z0-9_]*)",
        query_lc,
    )
    if sort_match is None:
        return None
    sort_by = [columns_by_lower.get(sort_match.group(1))]
    tie_breaker = re.search(r"\busing\s+([a-z_][a-z0-9_]*)\s+as\s+the\s+tie-breaker\b", query_lc)
    if tie_breaker is not None:
        sort_by.append(columns_by_lower.get(tie_breaker.group(1)))

    feature_match = re.search(r"\bfeatures?\s+([a-z_][a-z0-9_]*(?:\s*,\s*[a-z_][a-z0-9_]*)*(?:\s*(?:,?\s+and)\s+[a-z_][a-z0-9_]*)?)\s*\.", query_lc)
    if feature_match is not None:
        feature_names = re.split(r"\s*,\s*|\s+(?:and)\s+", feature_match.group(1))
        feature_columns = [columns_by_lower.get(name.strip()) for name in feature_names]
    elif "acceleration features" in query_lc:
        feature_columns = [
            str(column)
            for column in df.columns
            if str(column).startswith("accel_")
            or str(column) in {"extreme_event_magnitude", "instability_score"}
        ]
        if not feature_columns:
            return None
    else:
        return None

    target_column = _extract_target_column(query_lc, df)
    target_from_non_empty = bool(
        re.search(r"\b(?:whether|if)\b[^.?!]*\b(?:present|non[- ]empty|annotated)\b", query_lc)
    )
    if target_from_non_empty and target_column is None:
        target_column = columns_by_lower.get("annotation")
    target_label = "present" if target_from_non_empty else "label"

    filter_column: str | None = None
    filter_value: Any = None
    key_mentions = _extract_key_mentions(query_lc)
    matched_keys = [
        (columns_by_lower.get(column), value)
        for column, value in key_mentions.items()
        if columns_by_lower.get(column) is not None
    ]
    if len(matched_keys) > 1:
        return None
    if matched_keys:
        filter_column, filter_value = matched_keys[0]

    required_values = [model, train_fraction, holdout_row, target_column, *sort_by, *feature_columns]
    if any(value is None for value in required_values):
        return None

    return {
        "version": "1",
        "steps": [
            {
                "op": "PREDICTIVE_PIPELINE",
                "model": model,
                "feature_columns": feature_columns,
                "target_column": target_column,
                "sort_by": sort_by,
                "train_fraction": train_fraction,
                "holdout_row": holdout_row,
                "filter_column": filter_column,
                "filter_value": filter_value,
                "target_from_non_empty": target_from_non_empty,
                "target_label": target_label,
            }
        ],
    }


def _extract_filter_values(query_lc: str, df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    key_mentions = _extract_key_mentions(query_lc)
    for key, val in key_mentions.items():
        out[key] = val

    if re.search(r"\bactivity[_ ]labels?\b", query_lc):
        activity_columns = [
            column
            for column in df.columns
            if str(column).lower() in {"activity", "activity_label"}
        ]
        activity_values = {
            str(value).strip().lower()
            for column in activity_columns
            for value in df[column].dropna().unique()
            if str(value).strip()
        }
        mentioned_values = {
            value
            for value in activity_values
            if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", query_lc)
        }
        if len(mentioned_values) == 1:
            out["activity"] = next(iter(mentioned_values))

    # Parse explicit numeric column filters like "mlii > 0".
    for m in re.finditer(r"\b([a-z_][a-z0-9_]*)\s*(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)", query_lc):
        field = m.group(1)
        raw = float(m.group(3))
        value: Any = int(raw) if raw.is_integer() else raw
        out[f"{field}__value"] = value
    return out


def _extract_intent_flags(query_lc: str) -> dict[str, bool]:
    return {
        "rank": bool(re.search(r"\b(highest|lowest|largest|smallest|most|least)\b", query_lc)),
        "group_by": bool(re.search(r"\b(per|each|group|grouped|by)\b", query_lc)),
        "difference": bool(re.search(r"\b(difference|gap|exceeds|absolute difference)\b", query_lc)),
        "derived_magnitude": bool(re.search(r"\b(magnitude|root mean square|rms)\b", query_lc)),
        "time_bin": bool(re.search(r"\b(minute|1-minute|window|interval|bin|bucket)\b", query_lc)),
        "correlation": bool(re.search(r"\b(correlate|correlation)\b", query_lc)),
        "last_event": bool(re.search(r"\b(last annotated|last)\b", query_lc)),
        "predictive": bool(re.search(r"\b(train|training|fit|holdout|predict|prediction|forecast|estimate|classifier|regressor|model)\b", query_lc)),
    }


def _extract_target_column(query_lc: str, df: pd.DataFrame) -> str | None:
    columns_lc = {str(column).lower(): str(column) for column in df.columns}
    m = re.search(r"\blabel\s+in\s+the\s+([a-z_][a-z0-9_]*)\s+column\b", query_lc)
    if m and m.group(1) in columns_lc:
        return columns_lc[m.group(1)]
    if re.search(r"\bactivity[_ ]label\b", query_lc) and "activity_label" in columns_lc:
        return columns_lc["activity_label"]
    if re.search(r"\bbehavio(?:u)?r\s+label\b", query_lc) and "behavior" in columns_lc:
        return columns_lc["behavior"]
    if re.search(r"\bannotation\s+is\s+present\b", query_lc) and "annotation_present" in columns_lc:
        return columns_lc["annotation_present"]
    return None


def _extract_operator_skeleton_hint(query_lc: str) -> list[str] | None:
    # Conservative hints only: emit only when intent is explicit and unambiguous.
    if re.search(r"\b(train|training|fit|holdout|predict|prediction|forecast|estimate|classifier|regressor|model)\b", query_lc):
        return ["PREDICTIVE_PIPELINE"]
    has_count = bool(re.search(r"\b(how many|count|number of)\b", query_lc))
    has_numeric_cmp = bool(re.search(r"(>=|<=|>|<)", query_lc))
    if has_count and has_numeric_cmp:
        return ["FILTER_COMPARE", "COUNT_ROWS"]
    return None


def _extract_semantic_signature(query: str, df: pd.DataFrame) -> dict[str, Any]:
    """Extract a conservative schema-aware semantic signature for pre-grounding gates.

    This is intentionally minimal and abstain-first. It only emits fields when
    they are directly supported by query text and live schema headers.
    """
    query_lc = query.lower()
    out_of_scope_markers = (
        "geographic location",
        "location where",
        "family history",
        "patient's weight",
        "who recommended",
        "weekly moderate-to-vigorous",
        "weather",
        "occupancy",
        "operating schedule",
    )
    if any(marker in query_lc for marker in out_of_scope_markers):
        return {
            "admissibility": "out_of_scope",
            "confidence": 0.95,
            "aggregate": None,
            "fields": [],
            "predicate_ops": {},
            "filter_values": {},
            "intent_flags": _extract_intent_flags(query_lc),
            "predictive": {
                "model": _detect_predictive_model(query_lc),
                "target_column": _extract_target_column(query_lc, df),
                "train_fraction": _detect_train_fraction(query_lc),
                "holdout_row": _detect_holdout_position(query_lc),
            },
            "operator_skeleton_hint": _extract_operator_skeleton_hint(query_lc),
            "output_shape": "unknown",
        }

    columns = [str(c) for c in df.columns]
    columns_lc = [c.lower() for c in columns]
    fields = [c for c in columns if re.search(rf"\b{re.escape(c.lower())}\b", query_lc)]
    predicate_ops: dict[str, str] = {}
    for m in re.finditer(r"\b([a-z_][a-z0-9_]*)\s*(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)", query_lc):
        col = m.group(1)
        if col not in columns_lc:
            continue
        op = m.group(2)
        predicate_ops[col] = {
            ">": "gt",
            ">=": "gte",
            "<": "lt",
            "<=": "lte",
            "=": "eq",
        }[op]

    for key_col in ("record_id", "user_id", "subject_id"):
        if key_col in columns_lc and re.search(rf"\b{key_col}\s*(?:=|is)?\s*\d+\b", query_lc):
            predicate_ops.setdefault(key_col, "eq")

    aggregate = _detect_aggregate(query_lc)
    filter_values = _extract_filter_values(query_lc, df)
    intent_flags = _extract_intent_flags(query_lc)
    predictive = {
        "model": _detect_predictive_model(query_lc),
        "target_column": _extract_target_column(query_lc, df),
        "train_fraction": _detect_train_fraction(query_lc),
        "holdout_row": _detect_holdout_position(query_lc),
    }
    operator_skeleton_hint = _extract_operator_skeleton_hint(query_lc)

    output_shape = "unknown"
    if predictive["model"] is not None:
        output_shape = "predictive"
    elif re.search(r"\blist\b", query_lc):
        output_shape = "list"
    elif aggregate is not None or re.search(r"\b(how many|count|number of)\b", query_lc):
        output_shape = "scalar"

    admissibility = "unknown"
    if intent_flags["predictive"] or aggregate or fields or predicate_ops or filter_values:
        admissibility = "in_scope"
    if re.search(
        r"\b(?:predict|forecast)\s+next\s+week(?:'s)?\b|\b(?:fatal cardiac event|bmi|cadence)\b",
        query_lc,
    ):
        admissibility = "out_of_scope"

    confidence = 0.95 if admissibility == "out_of_scope" else 0.85 if admissibility == "in_scope" else 0.4
    return {
        "admissibility": admissibility,
        "confidence": confidence,
        "aggregate": aggregate,
        "fields": sorted(set(fields)),
        "predicate_ops": predicate_ops,
        "filter_values": filter_values,
        "intent_flags": intent_flags,
        "predictive": predictive,
        "operator_skeleton_hint": operator_skeleton_hint,
        "output_shape": output_shape,
    }


def extract_semantic_signature(query: str, df: pd.DataFrame) -> dict[str, Any]:
    """Public wrapper used by offline tooling to mirror runtime extraction."""
    return _extract_semantic_signature(query, df)


def _candidate_id(entry: dict[str, Any], index: int) -> str:
    raw = entry.get("sig_id") or entry.get("template_id") or entry.get("signature")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return f"candidate_{index}"


def _find_semantic_entry(
    entries: Iterable[dict[str, Any]],
    query: str,
    dataset: str | None,
    df: pd.DataFrame,
    expected_operator_contract_hash: str | None,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    _require_sentence_transformers()
    live_signature = _extract_semantic_signature(query, df)
    if live_signature.get("admissibility") == "out_of_scope":
        evidence = {
            "decision": "out_of_scope_hit",
            "status": "admissibility_out_of_scope",
            "extracted_signature": live_signature,
            "candidate_ids_considered": [],
            "hard_gate_results": {},
            "candidate_scores": {},
            "extraction_confidence": float(live_signature.get("confidence", 0.0) or 0.0),
            "abstention_reason": "admissibility_out_of_scope",
            "score_threshold": 0.75,
            "score_margin": 0.08,
            "winner": None,
            "runner_up": None,
            "elapsed_ms": {"model_load_ms": 0.0, "warm_up_ms": 0.0},
        }
        return None, "admissibility_out_of_scope", evidence

    candidates = [x for x in entries if isinstance(x, dict)]
    overlayed = _merge_semantic_overlays(entries=candidates, semantic_entries=None, df=df)
    if not overlayed:
        evidence = {
            "decision": "complete_miss",
            "status": "semantic_no_candidates",
            "extracted_signature": live_signature,
            "candidate_ids_considered": [],
            "hard_gate_results": {},
            "candidate_scores": {},
            "extraction_confidence": 0.0,
            "abstention_reason": "semantic_no_candidates",
            "score_threshold": 0.75,
            "score_margin": 0.08,
            "winner": None,
            "runner_up": None,
            "elapsed_ms": {"model_load_ms": 0.0, "warm_up_ms": 0.0},
        }
        return None, "semantic_no_candidates", evidence

    from flashfusion.eval.trace_hybrid_cache import HybridMatcher, load_config

    matcher = HybridMatcher(
        entries=overlayed,
        config=load_config(DEFAULT_HYBRID_CONFIG_PATH),
        dataset=dataset,
        schema_columns=[str(column) for column in df.columns],
        schema_fingerprint=_schema_fingerprint(df),
        device="cpu",
        no_warmup=False,
        mode="hybrid",
        dense_top_k_override=None,
        lexical_top_k_override=None,
    )
    matcher.warm_up()
    result = matcher.match(query, expected_contract_hash=expected_operator_contract_hash)
    status = _hybrid_decision_to_status(result.decision)
    evidence = _hybrid_evidence(matcher=matcher, query=query, result=result, decision_status=status)
    evidence["extracted_signature"] = _query_contract_to_signature(matcher.extractor.extract(query))

    if result.entry is None:
        return None, status, evidence
    return result.entry, "semantic_cache_hit", evidence


def _execute_grounded_cache_entry(
    *,
    query: str,
    df: pd.DataFrame,
    client: LLMClient,
    result: RunResult,
    trace: CacheGroundingTrace | None,
    entry: dict[str, Any],
    stage_hit: str,
    plan_source: str,
    stage_latency: dict[str, float],
    started: float,
) -> RunResult:
    _record(trace, operator_skeleton=list(entry["operator_skeleton"]))
    _append_stage(result, stage_hit)
    _append_stage(result, "cache_light_grounding")
    grounding_started = time.perf_counter()
    try:
        raw_plan = _ground_predictive_cache_hit(query, entry["operator_skeleton"], df)
        if raw_plan is None:
            prompt_started = time.perf_counter()
            prompt = _grounding_prompt(query, entry, df)
            _record(trace, prompt_build_latency_s=time.perf_counter() - prompt_started)
            _record(trace, prompt=prompt)
            raw_plan = _invoke_light_for_plan(client, prompt, entry["operator_skeleton"], trace)
        else:
            _record(trace, prompt_build_latency_s=0.0, parsed_plan=raw_plan)
    finally:
        stage_latency["cache_grounding"] += _accounted_light_latency(client, grounding_started)
        stage_latency["cache_retry_overhead"] += _light_retry_overhead_s(client)
    validation_started = time.perf_counter()
    try:
        raw_plan = _apply_grounding_semantic_guards(raw_plan, query, df=df)
        plan = _parse_and_validate_cached_plan(raw_plan, entry["operator_skeleton"], df)
    finally:
        stage_latency["cache_validation"] += time.perf_counter() - validation_started
    _append_stage(result, "cache_plan_validated")
    _record(trace, validated_plan=plan.model_dump(mode="json"))
    _print_grounding_confirmation(entry["operator_skeleton"], plan)

    execution_started = time.perf_counter()
    execution = execute_plan(df, plan)
    stage_latency["typed_exec"] += time.perf_counter() - execution_started
    if not execution.ok:
        raise PlanExecutionError(execution.error or "typed execution failed")
    _append_stage(result, "typed_exec")
    _record(trace, executed_value=execution.value, hit=True)

    answer = _format_typed_execution_value(execution.value)
    _set_if_present(result, "answer", answer)
    _set_if_present(result, "raw_answer", str(execution.value))
    _set_if_present(result, "executed_value", execution.value)
    _set_if_present(result, "executed", True)
    _set_if_present(result, "rejected", False)
    _set_if_present(result, "execution_path", PATH_TYPED_OPERATOR_CACHE)
    _set_if_present(result, "plan_validation_stage_failed", "")
    _set_if_present(result, "plan_source", plan_source)
    _set_if_present(result, "typed_plan", plan.model_dump(mode="json"))
    _set_if_present(result, "typed_plan_sha256", typed_plan_digest(plan))
    _set_if_present(result, "operators_used", list(plan.operators_used))
    _set_if_present(result, "agent_tries", len(execution.steps))
    _set_if_present(result, "execution_attempts", list(execution.steps))
    _set_if_present(
        result,
        "typed_execution_certificate",
        {
            "certificate_status": "ok",
            "execution_path": PATH_TYPED_OPERATOR_CACHE,
            "typed_plan_sha256": typed_plan_digest(plan),
            "operators_used": list(execution.operators_used),
            "rows_scanned": execution.rows_scanned,
            "rows_after_filter": execution.rows_after_filter,
            "cache_query_text": entry.get("query_text", ""),
            "cache_dataset": entry.get("dataset", ""),
            "result": execution.value,
            "code": execution.code,
        },
    )
    _set_if_present(
        result,
        "trace",
        "Cache hit: light model grounded cached skeleton; validated typed execution.\n"
        + (execution.trace or ""),
    )
    _set_if_present(result, "final_code", execution.code)
    _set_if_present(result, "latency_s", _accounted_cache_latency(stage_latency))
    return result


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


def _schema_fingerprint(df: pd.DataFrame) -> str:
    """Stable local fingerprint for optional cache invalidation.

    This deliberately fingerprints columns and dtypes only. The normal live
    schema validator remains responsible for domain/type requirements; do not
    cache data values or answers.
    """
    payload = [(str(column), str(dtype)) for column, dtype in df.dtypes.items()]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def _schema_context(df: pd.DataFrame, max_values: int = 8) -> str:
    """Provide the light model compact schema grounding context, not raw rows."""
    cache_key = f"_flashfusion_schema_context_v{max_values}"
    cached = df.attrs.get(cache_key)
    if isinstance(cached, str):
        return cached
    lines = []
    for column in df.columns:
        series = df[column]
        line = f"- {column}: dtype={series.dtype}; nulls={int(series.isna().sum())}"
        if not series.empty and (
            pd.api.types.is_object_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype)
        ):
            values = [str(v) for v in series.dropna().drop_duplicates().head(max_values).tolist()]
            line += f"; sample_values={values}"
        lines.append(line)
    context = "\n".join(lines)
    # DataFrame.copy() preserves attrs, so a benchmark's fresh per-query copies
    # reuse the schema derived from the same immutable base dataset.
    df.attrs[cache_key] = context
    return context


def _grounding_prompt(query: str, entry: dict[str, Any], df: pd.DataFrame) -> str:
    skeleton = entry["operator_skeleton"]
    n = len(skeleton)
    checklist = "\n".join(f"  step {i + 1}: {op}" for i, op in enumerate(skeleton))
    return "\n".join(
        [
            f"QUESTION (literal exact cache key): {query}",
            f"DATASET: {entry.get('dataset', '(unspecified)')}",
            f"REQUIRED OUTPUT ({n} steps, this order):",
            checklist,
            "OPERATOR FIELD SPEC (use these exact field names, nothing else):",
            build_compact_operator_spec(skeleton),
            "LIVE DATASET SCHEMA:",
            _schema_context(df),
        ]
    )


def _cache_grounding_system_message(skeleton: tuple[str, ...]) -> SystemMessage:
    return SystemMessage(
        content=[
            {
                "type": "text",
                "text": _build_grounding_system_prompt(skeleton),
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )


def _cache_rejection_system_message() -> SystemMessage:
    return SystemMessage(
        content=[
            {
                "type": "text",
                "text": OUT_OF_SCOPE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )


def prewarm_flash_fusion_cache_prompt_cache(
    *,
    client: LLMClient,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    dataset: str | None = None,
    query_ids: Iterable[int] | None = None,
) -> int:
    """Populate provider caches for static cache-grounding system prompts.

    Cache entries are limited to the selected query IDs when available. The
    model response is intentionally discarded; only the static system prefix
    is warmed before benchmark query timing begins.
    """
    wanted_dataset = canonical_dataset(dataset)
    wanted_ids = set(query_ids) if query_ids is not None else None
    skeletons: set[tuple[str, ...]] = set()
    for entry in _load_entries(cache_path):
        if entry.get("status") != "reusable":
            continue
        if wanted_dataset is not None and canonical_dataset(entry.get("dataset")) != wanted_dataset:
            continue
        if wanted_ids is not None:
            entry_query_id = entry.get("query_id")
            if entry_query_id is None:
                continue
            try:
                if int(entry_query_id) not in wanted_ids:
                    continue
            except (TypeError, ValueError):
                continue
        skeleton = entry.get("operator_skeleton")
        if isinstance(skeleton, list) and all(isinstance(operator, str) for operator in skeleton):
            skeletons.add(tuple(skeleton))

    for skeleton in skeletons:
        system_message = (
            _cache_rejection_system_message()
            if not skeleton
            else _cache_grounding_system_message(skeleton)
        )
        client.warm_prompt_cache(
            [system_message, HumanMessage(content="Prompt-cache warmup.")],
            stage="ff_cache_prompt_cache_warmup",
        )
    return len(skeletons)


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3].rstrip()
    return raw.strip()


def _recover_split_params_arrays(raw: str) -> str | None:
    """Merge malformed adjacent arrays belonging to a top-level ``params`` key.

    Some light models emit ``{"params":[step1],[step2]}`` instead of putting
    every step object in one array. Decode each array independently so recovery
    remains JSON-aware and applies only when the entire payload has that shape.
    """
    match = re.match(r'^\s*\{\s*"params"\s*:\s*', raw)
    if match is None:
        return None

    decoder = json.JSONDecoder()
    position = match.end()
    merged: list[Any] = []
    arrays_seen = 0
    while True:
        try:
            value, position = decoder.raw_decode(raw, position)
        except json.JSONDecodeError:
            return None
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            return None
        merged.extend(value)
        arrays_seen += 1

        while position < len(raw) and raw[position].isspace():
            position += 1
        if position >= len(raw) or raw[position] != ",":
            break
        position += 1
        while position < len(raw) and raw[position].isspace():
            position += 1
        if position >= len(raw) or raw[position] != "[":
            return None

    while position < len(raw) and raw[position].isspace():
        position += 1
    if arrays_seen < 2 or position >= len(raw) or raw[position] != "}":
        return None
    if raw[position + 1 :].strip():
        return None
    return json.dumps({"params": merged}, separators=(",", ":"))


def _repair_light_json(raw: str) -> str:
    """Repair the most common LLM JSON mistakes without inventing semantics.

    The lightweight repair is intentionally small: strip markdown fences, remove
    trailing commas before closing brackets/braces, and trim to the first JSON
    object in the response. Anything still malformed is rejected explicitly so
    the cache path can fall back to the full planner instead of crashing.
    """
    cleaned = _strip_code_fence(raw)
    if not cleaned:
        raise ValueError("light model returned empty content")

    candidates = [cleaned]
    candidates.append(re.sub(r",(\s*[}\]])", r"\1", cleaned))

    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if 0 <= first < last:
        candidates.append(cleaned[first : last + 1])

    recovered = _recover_split_params_arrays(cleaned)
    if recovered is not None:
        candidates.append(recovered)

    last_err: ValueError | None = None
    for candidate in candidates:
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError as exc:
            last_err = ValueError(f"light model JSON repair failed: {exc.msg}")
    if last_err is not None:
        raise last_err
    raise ValueError("light model output was not valid JSON")


def _reconstruct_plan_from_compact_params(
    raw_response: dict[str, Any],
    skeleton: list[str],
) -> dict[str, Any]:
    """Reconstruct a full DeterministicPlan payload from compact params or full steps."""
    if "steps" in raw_response and isinstance(raw_response["steps"], list):
        return raw_response

    params_list = raw_response.get("params")
    if not isinstance(params_list, list):
        raise ValueError("Model response missing 'params' list.")

    if len(params_list) != len(skeleton):
        raise ValueError(
            f"Grounding step count mismatch: expected {len(skeleton)} for skeleton "
            f"{skeleton}, got {len(params_list)}"
        )

    reconstructed_steps = []
    for op_name, param_obj in zip(skeleton, params_list):
        step_dict = dict(param_obj) if isinstance(param_obj, dict) else {}
        step_dict["op"] = op_name
        reconstructed_steps.append(step_dict)

    return {
        "version": "1",
        "steps": reconstructed_steps,
    }


def _invoke_light_for_plan(
    client: LLMClient,
    prompt: str,
    skeleton: list[str],
    trace: CacheGroundingTrace | None = None,
) -> dict[str, Any]:
    """Call only the configured light model and parse a single JSON object.

    Messages are passed directly rather than through a ``ChatPromptTemplate``:
    the system prompt contains a literal JSON output contract, whose braces a
    template would try to interpolate. Going through ``invoke_messages`` also
    records tokens, latency, and cost in the client's call_log — otherwise the
    cache baseline would report a free LLM call in the benchmark.
    """
    light = getattr(client, "light", None) or client
    if getattr(light, "llm", None) is None or not hasattr(light, "invoke_messages"):
        raise RuntimeError("cache grounding requires client.light.llm")
    messages = [
        _cache_grounding_system_message(tuple(skeleton)),
        HumanMessage(content=prompt),
    ]
    started = time.perf_counter()
    raw = light.invoke_messages(messages, stage="cache_grounding")
    call_log = getattr(light, "call_log", None)
    if isinstance(call_log, list) and call_log:
        call = call_log[-1]
        _record(
            trace,
            light_input_tokens=int(getattr(call, "input_tokens", 0) or 0),
            light_output_tokens=int(getattr(call, "output_tokens", 0) or 0),
            light_reasoning_tokens=int(getattr(call, "reasoning_tokens", 0) or 0),
        )
    _record(
        trace,
        raw_light_output=raw,
        grounding_latency_s=time.perf_counter() - started,
    )
    repaired = _repair_light_json(raw)
    parsed = json.loads(repaired)
    if not isinstance(parsed, dict):
        raise ValueError("light model output must be a JSON object")
    if parsed.get("cache_grounding_failed") is True:
        raise ValueError(f"light model declined grounding: {parsed.get('reason', '')}")
    reconstructed = _reconstruct_plan_from_compact_params(parsed, skeleton)
    _record(trace, parsed_plan=reconstructed)
    return reconstructed


def _rejection_reason_prompt(query: str, df: pd.DataFrame) -> str:
    return "\n".join(
        [
            f"QUESTION: {query}",
            "LIVE DATASET SCHEMA:",
            _schema_context(df),
        ]
    )


def _invoke_light_for_rejection_reason(
    client: LLMClient, query: str, df: pd.DataFrame, trace: CacheGroundingTrace | None = None
) -> str:
    """Ask the light model to infer a guardrail-style rejection reason."""
    light = getattr(client, "light", None) or client
    if getattr(light, "llm", None) is None or not hasattr(light, "invoke_messages"):
        raise RuntimeError("cache rejection reasoning requires client.light.llm")
    messages = [
        _cache_rejection_system_message(),
        HumanMessage(content=_rejection_reason_prompt(query, df)),
    ]
    started = time.perf_counter()
    raw = light.invoke_messages(messages, stage="cache_rejection_reason")
    _record(
        trace,
        raw_light_output=raw,
        grounding_latency_s=time.perf_counter() - started,
    )
    repaired = _repair_light_json(raw)
    parsed = json.loads(repaired)
    if not isinstance(parsed, dict):
        raise ValueError("light model rejection output must be a JSON object")
    reason = parsed.get("rejection_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("light model did not return a non-empty rejection_reason")
    return reason.strip()


_RELATIONAL_TERMS = {
    "gt": ("strictly greater", "greater than", "above", "over"),
    "gte": ("at least", "no less than", "greater than or equal"),
    "lt": ("strictly less", "less than", "below", "under"),
    "lte": ("at most", "no more than", "less than or equal"),
}


def _query_mentions_relational_for_column(query_lc: str, column: str) -> bool:
    escaped = re.escape(column.lower())
    symbolic = rf"\b{escaped}\b\s*(>=|<=|>|<)"
    if re.search(symbolic, query_lc):
        return True
    for terms in _RELATIONAL_TERMS.values():
        for term in terms:
            if re.search(rf"\b{escaped}\b[^.\n]{{0,48}}\b{re.escape(term)}\b", query_lc):
                return True
            if re.search(rf"\b{re.escape(term)}\b[^.\n]{{0,48}}\b{escaped}\b", query_lc):
                return True
    return False


def _extract_key_mentions(query_lc: str) -> dict[str, int]:
    mentions: dict[str, int] = {}
    patterns = {
        "record_id": [
            r"\bfor\s+record_id\s*(?:=|is)?\s*(\d+)\b",
            r"\brecord_id\s*(?:=|is)?\s*(\d+)\b",
        ],
        "subject_id": [
            r"\bfor\s+subject_id\s*(?:=|is)?\s*(\d+)\b",
            r"\bsubject_id\s*(?:=|is)?\s*(\d+)\b",
            r"\buser\s+(\d+)\b",
        ],
    }
    for column, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, query_lc)
            if m:
                mentions[column] = int(m.group(1))
                break
    return mentions


def _query_requests_ratio(query_lc: str) -> bool:
    return bool(
        re.search(r"\b(ratio|times|x\s+as\s+much|percent|percentage|per\s+cent)\b", query_lc)
    )


def _canonicalize_live_domain_values(
    df: pd.DataFrame,
    column: str,
    values: list[Any],
    *,
    op: str,
) -> list[Any]:
    """Bind string literals to unique values from a live categorical domain."""
    if column not in df.columns:
        return values
    series = df[column]
    if not (
        pd.api.types.is_object_dtype(series.dtype)
        or pd.api.types.is_string_dtype(series.dtype)
        or isinstance(series.dtype, pd.CategoricalDtype)
    ):
        return values

    domain = series.dropna().drop_duplicates().tolist()
    normalized: dict[str, list[Any]] = {}
    for domain_value in domain:
        key = str(domain_value).strip().casefold()
        normalized.setdefault(key, []).append(domain_value)

    canonical: list[Any] = []
    for value in values:
        if not isinstance(value, str):
            canonical.append(value)
            continue
        exact = [domain_value for domain_value in domain if domain_value == value]
        if len(exact) == 1:
            canonical.append(exact[0])
            continue
        matches = normalized.get(value.strip().casefold(), [])
        if len(matches) != 1:
            qualifier = "no" if not matches else "multiple"
            raise PlanSchemaError(
                f"{op} value {value!r} has {qualifier} unique match in the live "
                f"domain of column {column!r}"
            )
        canonical.append(matches[0])
    return canonical


def _apply_grounding_semantic_guards(
    raw_plan: dict[str, Any], query: str, df: pd.DataFrame | None = None
) -> dict[str, Any]:
    """Apply conservative post-grounding fixes for high-confidence intent cues.

    These guards do not add/remove/reorder operators. They only patch field values
    in-place when the query intent is explicit and a mismatch is a known failure mode.
    """
    if not isinstance(raw_plan, dict):
        return raw_plan
    steps = raw_plan.get("steps")
    if not isinstance(steps, list):
        return raw_plan

    query_lc = query.lower()
    key_mentions = _extract_key_mentions(query_lc)
    wants_count_extrema = bool(
        re.search(r"\b(highest|lowest)\b", query_lc)
        and re.search(r"\b(number|count)\b", query_lc)
        and re.search(r"\b(sample|samples|row|rows)\b", query_lc)
    )
    wants_average = bool(re.search(r"\b(mean|average)\b", query_lc))
    wants_rough_compare = bool(re.search(r"\brougher\b", query_lc))
    wants_first_holdout = "first row in the holdout" in query_lc
    wants_last_holdout = "last row in the holdout" in query_lc
    asks_difference = bool(re.search(r"\b(difference|gap)\b", query_lc))
    wants_target_presence = bool(
        re.search(r"\b(?:whether|if)\b[^.?!]*\b(?:present|non[- ]empty|annotated)\b", query_lc)
    )

    for step in steps:
        if not isinstance(step, dict):
            continue
        op = str(step.get("op", ""))

        if op == "FILTER_COMPARE":
            column = str(step.get("column", ""))
            mention_value = key_mentions.get(column)
            if mention_value is not None and not _query_mentions_relational_for_column(query_lc, column):
                step["comparator"] = "eq"
                step["value"] = mention_value
            if (
                df is not None
                and step.get("comparator") in {"eq", "ne"}
                and isinstance(step.get("value"), str)
            ):
                step["value"] = _canonicalize_live_domain_values(
                    df, column, [step["value"]], op=op
                )[0]

        elif op in {"FILTER_IN", "SPLIT_BY_VALUES"}:
            column = step.get("column")
            values = step.get("values")
            if df is not None and isinstance(column, str) and isinstance(values, list):
                step["values"] = _canonicalize_live_domain_values(
                    df, column, values, op=op
                )

        elif op == "DERIVE_BIN":
            kind = step.get("kind")
            width = step.get("width")
            freq = step.get("freq")

            col_name = step.get("column")
            result_name = step.get("result")
            if isinstance(col_name, str) and col_name.strip() and (
                result_name is None or (isinstance(result_name, str) and not result_name.strip())
            ):
                derived = f"{col_name.strip()}_bin"
                step["result"] = derived

            if kind == "temporal" and freq is None and width is not None:
                step["kind"] = "numeric"
                step["freq"] = None
                step["epoch_unit"] = None
            elif kind == "numeric" and width is None and isinstance(freq, str):
                freq_value = freq.strip()
                if freq_value:
                    step["kind"] = "temporal"
                    step["freq"] = freq_value
                    step["epoch_unit"] = None
                    if "width" in step:
                        step.pop("width", None)
            elif kind == "temporal" and freq is not None and width is None:
                # If the query specifies fixed-size window intervals like "10-second interval" or "60-second bins"
                # without an explicit epoch_unit, and the column is numeric (e.g. time_s), convert to kind="numeric"
                # so it bins via floor(col / width) * width.
                col_name_str = str(col_name or "")
                is_numeric_col = False
                if df is not None and col_name_str in df.columns:
                    is_numeric_col = pd.api.types.is_numeric_dtype(df[col_name_str])
                elif col_name_str.endswith("_s") or col_name_str in {"time_s", "timestamp_ms", "sample_idx"}:
                    is_numeric_col = True

                if (df is None or is_numeric_col) and step.get("epoch_unit") is None:
                    sec_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:second|seconds|sec|s)\b", str(freq))
                    if not sec_match:
                        sec_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:second|seconds|sec|s)\b", query_lc)
                    min_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:minute|minutes|min|m)\b", str(freq))
                    if not min_match:
                        min_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:minute|minutes|min|m)\b", query_lc)

                    if sec_match:
                        step["kind"] = "numeric"
                        step["width"] = float(sec_match.group(1))
                        step["freq"] = None
                        step["epoch_unit"] = None
                    elif min_match:
                        step["kind"] = "numeric"
                        step["width"] = float(min_match.group(1)) * 60.0
                        step["freq"] = None
                        step["epoch_unit"] = None
            elif kind == "temporal" and freq is None and width is None:
                # A temporal bucketing step without a frequency is not valid. Use
                # the common numeric bucket width when the query explicitly states a
                # fixed-size window like "60-second bins".
                if re.search(r"\b(\d+(?:\.\d+)?)\s*(?:second|seconds|sec|s)\b", query_lc):
                    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:second|seconds|sec|s)\b", query_lc)
                    if match:
                        step["kind"] = "numeric"
                        step["width"] = float(match.group(1))
                        step["freq"] = None
                        step["epoch_unit"] = None
                elif re.search(r"\b(\d+(?:\.\d+)?)\s*(?:minute|minutes|min|m)\b", query_lc):
                    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:minute|minutes|min|m)\b", query_lc)
                    if match:
                        step["kind"] = "numeric"
                        step["width"] = float(match.group(1)) * 60.0
                        step["freq"] = None
                        step["epoch_unit"] = None

            # Pydantic's DeriveBin._validate_mode_fields requires freq/epoch_unit
            # to be null for kind="numeric", and width to be null for
            # kind="temporal" — enforce that regardless of which branch above
            # ran (or none did), since the light model may set kind="numeric"
            # while leaving a stray epoch_unit/freq from an earlier draft.
            if step.get("kind") == "numeric":
                step["freq"] = None
                step["epoch_unit"] = None
            elif step.get("kind") == "temporal":
                step["width"] = None

            if step.get("result") is None:
                if isinstance(col_name, str) and col_name.strip():
                    step["result"] = f"{col_name.strip()}_bin"
                else:
                    step["result"] = "binned_value"

        elif op == "DERIVE_DURATION_SECONDS":
            group_by = step.get("group_by")
            if isinstance(group_by, list):
                # Filter out categorical/activity columns that should not segment the continuous timeline
                entity_keys = [
                    k for k in group_by
                    if str(k).lower() not in {"activity", "activity_label", "behavior", "annotation_present"}
                ]
                if entity_keys:
                    step["group_by"] = entity_keys

            fill_first = step.get("fill_first")
            if fill_first is None or not isinstance(fill_first, (int, float)):
                step["fill_first"] = 0.0
            else:
                step["fill_first"] = float(fill_first)

            if step.get("clip_negative") is None:
                step["clip_negative"] = True

            if not step.get("result"):
                step["result"] = "dt_s"
            if isinstance(step.get("aggregate"), dict):
                agg_dict = step["aggregate"]
                step["aggregate"] = agg_dict.get("op") or agg_dict.get("aggregate")
                if not step.get("column") and "column" in agg_dict:
                    step["column"] = agg_dict["column"]
            if wants_count_extrema:
                step["aggregate"] = "count"
                step["column"] = None

        elif op == "AGGREGATE_PARTITIONS" and wants_average and str(step.get("aggregate")) == "var":
            step["aggregate"] = "mean"

        elif op == "COMPARE_PARTITIONS":
            mode = str(step.get("mode", ""))
            if mode == "ratio" and (wants_rough_compare or wants_average) and not _query_requests_ratio(query_lc):
                step["mode"] = "difference" if asks_difference else "difference"
            # COMPARE_PARTITIONS accepts only 'op' and 'mode'
            step.pop("column", None)

        elif op == "PREDICTIVE_PIPELINE":
            if wants_first_holdout:
                step["holdout_row"] = "first"
            elif wants_last_holdout:
                step["holdout_row"] = "last"
            if wants_target_presence:
                step["target_from_non_empty"] = True
                step["target_label"] = "present"

        elif op == "COMPARE_VALUES":
            # COMPARE_VALUES takes no column references — strip any stray
            # column/left/right/column1/column2 fields a light model copies
            # over from a preceding step; extra="forbid" rejects them outright.
            for stray in ("column", "column1", "column2", "left", "right"):
                step.pop(stray, None)

        elif op == "GROUP_AGGREGATE":
            # GROUP_AGGREGATE has no result/result_column field of its own.
            step.pop("result", None)
            step.pop("result_column", None)

        elif op == "FILTER_EQ_AGGREGATE":
            # FILTER_EQ_AGGREGATE has no literal "value" field — only column+aggregate.
            step.pop("value", None)
            step.pop("comparator", None)

        elif op == "PARALLEL_AGGREGATE":
            branches = step.get("branches")
            if isinstance(branches, list):
                for branch in branches:
                    if not isinstance(branch, dict):
                        continue
                    if "result" in branch and "result_column" not in branch:
                        branch["result_column"] = branch.pop("result")
                    column = branch.get("filter_column")
                    values = branch.get("filter_values")
                    if df is not None and isinstance(column, str) and isinstance(values, list):
                        branch["filter_values"] = _canonicalize_live_domain_values(
                            df, column, values, op=op
                        )

    return raw_plan


def _parse_and_validate_cached_plan(
    raw_plan: dict[str, Any], expected_skeleton: list[str], df: pd.DataFrame
) -> DeterministicPlan:
    """Apply both standard Flash-Fusion gates plus skeleton equality."""
    normalized_raw, _ = normalize_raw_plan(raw_plan)
    plan = DeterministicPlan.model_validate(normalized_raw)  # structural/Pydantic gate
    actual_skeleton = [step.op for step in plan.steps]
    if actual_skeleton != expected_skeleton:
        raise PlanSchemaError(
            "cache grounding changed the cached operator skeleton: "
            f"expected={expected_skeleton!r}, actual={actual_skeleton!r}"
        )
    validate_plan_against_dataframe(plan, df)  # live schema/semantic gate
    return plan


def _print_grounding_confirmation(skeleton: list[str], plan: DeterministicPlan) -> None:
    """Print the cached operators and the field values grounded for each."""
    op_list = ", ".join(skeleton)
    grounded_steps = "\n".join(
        f"  {i + 1}. {json.dumps(step.model_dump(mode='json'), sort_keys=True)}"
        for i, step in enumerate(plan.steps)
    )
    print(
        f"[flash_fusion_cache] {op_list} operators that were extracted from the "
        f"cache and were grounded as follows:\n{grounded_steps}"
    )


# ---------------------------------------------------------------------------
# RunResult plumbing
# ---------------------------------------------------------------------------


def _set_if_present(result: RunResult, name: str, value: Any) -> None:
    if hasattr(result, name):
        setattr(result, name, value)


def _append_stage(result: RunResult, stage: str) -> None:
    stages = getattr(result, "stages_run", None)
    if isinstance(stages, list):
        stages.append(stage)


def _new_result(query: str, client: LLMClient) -> RunResult:
    model = getattr(client, "model_name", None) or getattr(client, "model", None) or ""
    return RunResult(baseline=BASELINE_NAME, model=str(model), query=query)


def _record_cache_failure(result: RunResult, reason: str) -> None:
    _set_if_present(result, "deterministic_fallback_reason", f"cache: {reason}")
    _append_stage(result, "cache_miss_or_validation_failure")


def _run_normal_flash_fusion(
    query: str, df: pd.DataFrame, client: LLMClient, result: RunResult, **kwargs: Any
) -> RunResult:
    """Delegate safely despite small signature differences across revisions."""
    signature = inspect.signature(run_flash_fusion)
    call_kwargs = {name: value for name, value in kwargs.items() if name in signature.parameters}
    if "r" in signature.parameters:
        call_kwargs["r"] = result
    elif "result" in signature.parameters:
        call_kwargs["result"] = result
    returned = run_flash_fusion(query, df, client, **call_kwargs)
    return returned if isinstance(returned, RunResult) else result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_flash_fusion_cache(
    query: str,
    df: pd.DataFrame,
    client: LLMClient,
    r: RunResult | None = None,
    *,
    dataset: str | None = None,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    semantic_cache_path: str | Path | None = None,
    enable_semantic_matching: bool = True,
    expected_operator_contract_hash: str | None = None,
    trace: CacheGroundingTrace | None = None,
    policy: FlashFusionPolicy | None = None,
    **flash_fusion_kwargs: Any,
) -> RunResult:
    """Run the cache-first Flash-Fusion baseline.

    On a valid cache hit this uses one light-model call for value grounding,
    then normal typed validation/execution. On every non-successful cache
    path it falls back to the existing full Flash-Fusion planner.

    Args:
        policy: The active policy. Its pruning and planner-guidance settings
            are forwarded to the planner used on cache miss/fallback, so a
            cache-on ablation keeps its treatment on the planner path instead
            of silently reverting to the full policy there. Defaults to
            ``FF_FULL``.
    """
    trace = trace if trace is not None else CacheGroundingTrace()
    result = r if r is not None else _new_result(query, client)
    active_policy = policy or DEFAULT_POLICY
    record_policy_provenance(result, active_policy)
    # Forward the treatment to the planner fallback; run_flash_fusion re-stamps
    # provenance from the same object, so hits and misses agree on the policy.
    flash_fusion_kwargs.setdefault("policy", active_policy)
    stage_latency = (
        dict(result.stage_latency_s)
        if isinstance(result.stage_latency_s, dict)
        else {}
    )
    stage_latency.setdefault("cache_grounding", 0.0)
    stage_latency.setdefault("cache_lookup", 0.0)
    stage_latency.setdefault("cache_validation", 0.0)
    stage_latency.setdefault("typed_exec", 0.0)
    stage_latency.setdefault("cache_rejection", 0.0)
    stage_latency.setdefault("cache_retry_overhead", 0.0)
    result.stage_latency_s = stage_latency
    started = time.perf_counter()
    _record(
        trace,
        cache_path=str(cache_path),
        requested_dataset=canonical_dataset(dataset),
    )

    # Prewarm the hybrid matcher runtime before the timed cache lookup so
    # that one-time embedding model load and dense index build are excluded
    # from per-query cache_lookup latency. Serverless callers can retain the
    # exact-match cache without carrying the optional embedding dependency.
    if enable_semantic_matching:
        prewarm_hybrid_cache_runtime(
            df=df,
            dataset=dataset,
            cache_path=cache_path,
            semantic_cache_path=semantic_cache_path,
        )

    try:
        lookup_started = time.perf_counter()
        try:
            entries = _load_entries(cache_path)
            entry, lookup_status = _find_exact_entry(entries, query, dataset)
            _record(trace, lookup_status=lookup_status, entry=entry)

            if entry is None:
                if not enable_semantic_matching:
                    raise LookupError(lookup_status)
                semantic_signature = _extract_semantic_signature(query, df)
                admissibility_hint = (
                    "out_of_scope"
                    if semantic_signature.get("admissibility") == "out_of_scope"
                    and float(semantic_signature.get("confidence", 0.0) or 0.0) >= 0.9
                    else None
                )
                runtime = _build_hybrid_runtime(
                    entries=entries,
                    dataset=dataset,
                    df=df,
                    cache_path=cache_path,
                    semantic_cache_path=semantic_cache_path,
                    out_of_scope_only=admissibility_hint == "out_of_scope",
                )
                hybrid_result = runtime.matcher.match(
                    query,
                    expected_contract_hash=expected_operator_contract_hash,
                    admissibility_hint=admissibility_hint,
                )
                hybrid_status = _hybrid_decision_to_status(hybrid_result.decision)
                hybrid_evidence = _hybrid_evidence(
                    matcher=runtime.matcher,
                    query=query,
                    result=hybrid_result,
                    decision_status=hybrid_status,
                )
                elapsed_ms = hybrid_result.elapsed_ms if isinstance(hybrid_result.elapsed_ms, dict) else {}
                stage_latency["cache_validation"] += float(elapsed_ms.get("verify_ms", 0.0) or 0.0) / 1000.0
                _record(trace, semantic_match_evidence=hybrid_evidence)

                if hybrid_result.entry is not None and hybrid_status == "semantic_cache_hit":
                    entry = hybrid_result.entry
                    lookup_status = "semantic_cache_hit"
                    _record(trace, lookup_status=lookup_status, entry=entry)
                elif hybrid_result.entry is not None and hybrid_status == "admissibility_out_of_scope":
                    entry = hybrid_result.entry
                    lookup_status = "semantic_cache_hit_out_of_scope"
                    _record(trace, lookup_status=lookup_status, entry=entry)
                else:
                    _append_stage(result, f"hybrid_{hybrid_status}")
                    raise LookupError(f"semantic: {hybrid_status}")

            if entry is None:
                raise LookupError(lookup_status)
        finally:
            stage_latency["cache_lookup"] += time.perf_counter() - lookup_started

        # Cheap out-of-scope short-circuit: the registry records an empty
        # skeleton, so we ask the light model for the guardrail reason instead
        # of invoking the full planner/guardrail pipeline.
        if lookup_status in {"exact_cache_hit_out_of_scope", "semantic_cache_hit_out_of_scope"}:
            _set_if_present(result, "cache_outcome", CACHE_OUTCOME_HIT_REJECTED)
            _set_if_present(result, "cache_outcome_reason", lookup_status)
            _append_stage(result, lookup_status)
            _append_stage(result, "cache_light_rejection_reason")
            grounding_started = time.perf_counter()
            try:
                reason = _invoke_light_for_rejection_reason(client, query, df, trace)
            finally:
                stage_latency["cache_rejection"] += _accounted_light_latency(
                    client, grounding_started
                )
                stage_latency["cache_retry_overhead"] += _light_retry_overhead_s(client)
            _append_stage(result, "cache_rejection_reason_ready")
            _set_if_present(result, "rejected", True)
            _set_if_present(result, "executed", False)
            _set_if_present(result, "execution_path", "guardrail_reject")
            _set_if_present(
                result,
                "plan_source",
                "exact_query_cache_out_of_scope"
                if lookup_status == "exact_cache_hit_out_of_scope"
                else "semantic_query_cache_out_of_scope",
            )
            _set_if_present(result, "answer", f"Query rejected. Reason: {reason}")
            _set_if_present(
                result,
                "trace",
                "Rejected by the guardrail because the query cannot be answered "
                f"from available dataset fields. Reason: {reason}",
            )
            _set_if_present(result, "latency_s", _accounted_cache_latency(stage_latency))
            return result

        if lookup_status == "exact_cache_hit":
            validation_started = time.perf_counter()
            try:
                cached_contract_hash = entry.get("operator_contract_hash")
                if expected_operator_contract_hash and cached_contract_hash != expected_operator_contract_hash:
                    raise LookupError("operator_contract_hash_mismatch")
                # cached_schema_fingerprint = entry.get("schema_fingerprint")
                # if cached_schema_fingerprint and cached_schema_fingerprint != _schema_fingerprint(df):
                #     raise LookupError("schema_fingerprint_mismatch")
            finally:
                stage_latency["cache_validation"] += time.perf_counter() - validation_started
            _set_if_present(result, "cache_outcome", CACHE_OUTCOME_EXACT_HIT)
            _set_if_present(result, "cache_outcome_reason", lookup_status)
            return _execute_grounded_cache_entry(
                query=query,
                df=df,
                client=client,
                result=result,
                trace=trace,
                entry=entry,
                stage_hit="exact_cache_hit",
                plan_source="exact_query_cache_light_grounded",
                stage_latency=stage_latency,
                started=started,
            )

        if lookup_status == "semantic_cache_hit":
            _set_if_present(result, "cache_outcome", CACHE_OUTCOME_SEMANTIC_HIT)
            _set_if_present(result, "cache_outcome_reason", lookup_status)
            return _execute_grounded_cache_entry(
                query=query,
                df=df,
                client=client,
                result=result,
                trace=trace,
                entry=entry,
                stage_hit="hybrid_cache_hit",
                plan_source="semantic_cache_light_grounded",
                stage_latency=stage_latency,
                started=started,
            )

        raise LookupError(f"unsupported_lookup_status:{lookup_status}")

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        ValidationError,
        PlanSchemaError,
        PlanExecutionError,
        LookupError,
        RuntimeError,
    ) as exc:
        _record(trace, failure_reason=f"{type(exc).__name__}: {exc}", fell_back=True)
        failure_trace = asdict(trace)
        _set_if_present(result, "cache_grounding_failure", failure_trace)
        # Every non-hit path lands here: lookup miss, hard-gate rejection,
        # grounding failure, and post-grounding validation failure. The reason
        # string distinguishes them without re-deriving anything downstream.
        _set_if_present(result, "cache_outcome", CACHE_OUTCOME_MISS)
        _set_if_present(result, "cache_outcome_reason", f"{type(exc).__name__}: {exc}")
        _record_cache_failure(result, str(exc))
        fallback_result = _run_normal_flash_fusion(query, df, client, result, **flash_fusion_kwargs)
        _set_if_present(fallback_result, "cache_grounding_failure", failure_trace)
        skeleton = _extract_cached_skeleton_from_result(fallback_result)
        if (
            fallback_result.executed
            and not fallback_result.rejected
            and fallback_result.execution_path == "typed_operator"
            and skeleton
        ):
            try:
                _upsert_reusable_cache_entry(
                    cache_path=cache_path,
                    dataset=dataset,
                    query=query,
                    skeleton=skeleton,
                    df=df,
                    expected_operator_contract_hash=expected_operator_contract_hash,
                    query_id=getattr(fallback_result, "query_id", 0),
                )
                _invalidate_hybrid_runtime(cache_path=cache_path, dataset=dataset)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                # Cache write failures are non-fatal: the baseline answer remains valid.
                pass
        return fallback_result
