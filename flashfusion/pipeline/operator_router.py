"""
pipeline/operator_router.py — deterministic, zero-LM operator routing.

The planner used to be preceded by a light-LM "fast path" that guessed a whole
plan in one cheap call. It produced semantic false positives: a structurally
valid, cached-looking plan that answered a *different* question. This module
replaces it with a pure-Python router that never decides *what* the plan is —
it only decides which parts of the operator vocabulary the planner could
possibly need, so the (unchanged) full planner sees a smaller prompt.

Design principle: ELIMINATION, NOT SELECTION
--------------------------------------------
Every bucket starts as a candidate. A bucket leaves the candidate set only when
a *named* rule fires an explicit ``exclude`` verdict for it. Weak or absent
evidence is not evidence of exclusion. ``require`` always beats ``exclude``.

The failure modes are asymmetric and the thresholds are biased accordingly:
excluding a bucket the gold plan needed makes the correct plan impossible;
including a bucket that goes unused only costs prompt tokens.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

_FALLBACK_OPERATOR_NAMES: tuple[str, ...] = (
    "FILTER_COMPARE",
    "FILTER_IN",
    "FILTER_NOT_EMPTY",
    "FILTER_EQ_AGGREGATE",
    "AGGREGATE_COLUMN",
    "COUNT_ROWS",
    "COUNT_DISTINCT",
    "SELECT_COLUMN",
    "DERIVE_BINARY",
    "DERIVE_VECTOR_MAGNITUDE",
    "DERIVE_BIN",
    "DERIVE_DURATION_SECONDS",
    "GROUP_AGGREGATE",
    "AGGREGATE_GROUPS",
    "RANK_GROUPS",
    "RANK_ROWS",
    "SPLIT_BY_THRESHOLD",
    "SPLIT_BY_VALUES",
    "AGGREGATE_PARTITIONS",
    "COMPARE_PARTITIONS",
    "COMPARE_VALUES",
    "CORRELATE_COLUMNS",
    "PARALLEL_AGGREGATE",
    "PREDICTIVE_PIPELINE",
)

try:
    from flashfusion.pipeline.operators import ALL_OPERATOR_NAMES
except ModuleNotFoundError as exc:
    if exc.name != "numpy":
        raise
    ALL_OPERATOR_NAMES = _FALLBACK_OPERATOR_NAMES

__all__ = [
    "BUCKETS",
    "BUCKET_FULL",
    "OperatorRoute",
    "RuleResult",
    "route_operator_bucket",
]

# ---------------------------------------------------------------------------
# Canonical buckets
# ---------------------------------------------------------------------------

BUCKET_DIRECT = frozenset(
    {
        "SELECT_COLUMN",
        "FILTER_COMPARE",
        "FILTER_IN",
        "FILTER_NOT_EMPTY",
        "FILTER_EQ_AGGREGATE",
        "AGGREGATE_COLUMN",
        "COUNT_ROWS",
        "COUNT_DISTINCT",
    }
)
BUCKET_GROUP_RANK = BUCKET_DIRECT | frozenset(
    {"GROUP_AGGREGATE", "AGGREGATE_GROUPS", "RANK_GROUPS", "RANK_ROWS"}
)
BUCKET_PARTITION_COMPARE = BUCKET_DIRECT | frozenset(
    {
        "SPLIT_BY_THRESHOLD",
        "SPLIT_BY_VALUES",
        "AGGREGATE_PARTITIONS",
        "COMPARE_PARTITIONS",
        "COMPARE_VALUES",
    }
)
BUCKET_DERIVE = BUCKET_DIRECT | frozenset(
    {
        "DERIVE_BINARY",
        "DERIVE_VECTOR_MAGNITUDE",
        "DERIVE_BIN",
        "DERIVE_DURATION_SECONDS",
    }
)
BUCKET_CORRELATION = BUCKET_DIRECT | frozenset({"CORRELATE_COLUMNS"})
BUCKET_PARALLEL = BUCKET_GROUP_RANK | frozenset({"PARALLEL_AGGREGATE"})
BUCKET_PREDICTIVE = frozenset({"PREDICTIVE_PIPELINE"})
BUCKET_FULL = frozenset(ALL_OPERATOR_NAMES)

DIRECT = "direct"
GROUP_RANK = "group_rank"
PARTITION_COMPARE = "partition_compare"
DERIVE = "derive"
CORRELATION = "correlation"
PARALLEL = "parallel"
PREDICTIVE = "predictive"
FULL = "full"

#: Fixed iteration order — the rendered vocabulary must not depend on set order.
BUCKETS: tuple[tuple[str, frozenset[str]], ...] = (
    (DIRECT, BUCKET_DIRECT),
    (GROUP_RANK, BUCKET_GROUP_RANK),
    (PARTITION_COMPARE, BUCKET_PARTITION_COMPARE),
    (DERIVE, BUCKET_DERIVE),
    (CORRELATION, BUCKET_CORRELATION),
    (PARALLEL, BUCKET_PARALLEL),
    (PREDICTIVE, BUCKET_PREDICTIVE),
)

#: Queries longer than this are treated as ambiguous and routed to the full
#: vocabulary rather than narrowed on cues that may belong to different clauses.
AMBIGUITY_TOKEN_LIMIT = 100


# ---------------------------------------------------------------------------
# Lexical cues
# ---------------------------------------------------------------------------
# A cue ending in "*" matches any word starting with it ("correlat*" covers
# correlate/correlated/correlation); otherwise the whole word must match.

GROUPING_CUES = ("by", "per", "each", "every", "across", "group*", "respective*")
RANKING_CUES = (
    "most", "least", "top", "bottom", "highest", "lowest", "largest", "smallest",
    "greatest", "biggest", "longest", "shortest", "best", "worst", "first", "last",
    "latest", "earliest", "max*", "min*", "peak*", "rank*", "exceed*", "extreme*",
    "which", "whose", "who",
)
COMPARISON_CUES = (
    "compare*", "comparison", "versus", "vs", "difference*", "differ*", "than",
    "between", "split*", "half", "halves", "gap", "delta", "margin",
)
THRESHOLD_CUES = (
    "above", "below", "greater", "less", "over", "under", "exceed*", "threshold",
    "median", "at least", "at most", "more than", "fewer than",
)
DERIVE_CUES = (
    "magnitude", "bin*", "bucket*", "ratio", "duration", "elapsed", "how long",
    "time spent", "difference*", "differ*", "interval*", "window*", "rate",
    "range", "spread", "second*", "minute*", "hour*", "derived", "combined",
    "normalized", "product",
)
CORRELATION_CUES = (
    "correlat*", "relationship", "related", "associat*", "vary with",
    "varies with", "depend*", "influence*", "affect*", "impact*",
)
MULTI_BRANCH_CUES = (
    "for each of", "separately", "broken down by", "respectively", "each of",
    "both",
)
PREDICTIVE_CUES = (
    "predict*", "forecast*", "classif*", "train*", "holdout", "regression",
    "model", "estimate*",
)
ENTITY_CUES = (
    "user*", "subject*", "record*", "device*", "patient*", "participant*",
    "entity", "entities", "person", "people", "location*", "segment*", "id",
)
AGGREGATION_CUES = (
    "average", "mean", "median", "sum", "total", "count*", "how many", "how much",
    "number of", "std", "standard deviation", "variance", "var", "rms",
    "root mean square", "list", "show", "value*", "percentile", "distinct",
    "unique", "maximum", "minimum", "calculate", "compute",
)
NEGATION_CUES = ("not", "never", "excluding", "without", "except", "other than")
INTENT_CUES = (
    "what", "which", "who", "whose", "when", "where", "how many", "how much",
    "how long", "how does", "list", "calculate", "compare", "identify",
    "is there", "are there",
)

_KNOWN_ANALYTICAL_CUES = (
    GROUPING_CUES
    + RANKING_CUES
    + COMPARISON_CUES
    + THRESHOLD_CUES
    + DERIVE_CUES
    + CORRELATION_CUES
    + PREDICTIVE_CUES
    + AGGREGATION_CUES
)

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleResult:
    bucket: str
    verdict: Literal["require", "exclude", "no_opinion"]
    rule_name: str


@dataclass(frozen=True)
class OperatorRoute:
    candidate_ops: frozenset[str]
    excluded_buckets: tuple[str, ...]
    matched_rules: tuple[str, ...]
    used_full_fallback: bool

    @property
    def route_key(self) -> str:
        """Stable identity of this vocabulary slice, for prompt-cache keying."""
        if self.used_full_fallback:
            return FULL
        return "+".join(sorted(self.candidate_ops))


@dataclass(frozen=True)
class _Query:
    text: str
    token_count: int
    entity_cues: tuple[str, ...]


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _normalize(query: str) -> str:
    return " " + _TOKEN_RE.sub(" ", query.lower()).strip() + " "


def _matches(text: str, cue: str) -> bool:
    if cue.endswith("*"):
        return f" {cue[:-1]}" in text
    return f" {cue} " in text


def _any(text: str, cues: Sequence[str]) -> bool:
    return any(_matches(text, cue) for cue in cues)


def _entity_cues(schema_columns: Sequence[str] | None) -> tuple[str, ...]:
    """Entity-key vocabulary: the built-in words plus any ``*_id`` schema column."""
    extra: list[str] = []
    for column in schema_columns or ():
        name = column.lower()
        if name.endswith("_id") or name == "id":
            extra.append(name.replace("_", " "))
            extra.append(name.rsplit("_id", 1)[0] + "*" if name != "id" else "id")
    return ENTITY_CUES + tuple(sorted(set(extra)))


# ---------------------------------------------------------------------------
# Elimination rules
# ---------------------------------------------------------------------------


def _rule_predictive(q: _Query) -> tuple[RuleResult, ...]:
    """Predictive language is rare and unambiguous, so this bucket is opt-in."""
    if _any(q.text, PREDICTIVE_CUES):
        return (RuleResult(PREDICTIVE, "require", "require_predictive_cue"),)
    return (RuleResult(PREDICTIVE, "exclude", "default_predictive"),)


def _rule_group_rank(q: _Query) -> tuple[RuleResult, ...]:
    if _any(q.text, GROUPING_CUES) or _any(q.text, RANKING_CUES):
        return ()
    return (RuleResult(GROUP_RANK, "exclude", "no_grouping_or_ranking_cue"),)


def _rule_partition_compare(q: _Query) -> tuple[RuleResult, ...]:
    if _any(q.text, COMPARISON_CUES) or _any(q.text, THRESHOLD_CUES):
        return ()
    return (RuleResult(PARTITION_COMPARE, "exclude", "no_comparison_or_threshold_cue"),)


def _rule_derive(q: _Query) -> tuple[RuleResult, ...]:
    if _any(q.text, DERIVE_CUES):
        return ()
    return (RuleResult(DERIVE, "exclude", "no_derived_feature_cue"),)


def _rule_correlation(q: _Query) -> tuple[RuleResult, ...]:
    if _any(q.text, CORRELATION_CUES):
        return ()
    return (RuleResult(CORRELATION, "exclude", "no_correlation_cue"),)


def _rule_parallel(q: _Query) -> tuple[RuleResult, ...]:
    """Parallel branches need either an explicit multi-branch cue or grouping."""
    if _any(q.text, MULTI_BRANCH_CUES):
        return ()
    if _any(q.text, GROUPING_CUES) or _any(q.text, RANKING_CUES):
        return ()
    return (RuleResult(PARALLEL, "exclude", "no_multi_branch_or_grouping_cue"),)


def _rule_entity_selection(q: _Query) -> tuple[RuleResult, ...]:
    """"Which <entity> ..." is the per-entity shape (spec rule R2): keep both the
    grouping and the parallel-branch operators available regardless of other cues.
    """
    interrogative = _any(q.text, ("which", "whose", "who"))
    if interrogative and _any(q.text, q.entity_cues):
        return (
            RuleResult(GROUP_RANK, "require", "entity_selection"),
            RuleResult(PARALLEL, "require", "entity_selection"),
        )
    return ()


RULES = (
    _rule_predictive,
    _rule_group_rank,
    _rule_partition_compare,
    _rule_derive,
    _rule_correlation,
    _rule_parallel,
    _rule_entity_selection,
)


# ---------------------------------------------------------------------------
# Ambiguity override
# ---------------------------------------------------------------------------


def _ambiguity_rule(q: _Query) -> str:
    """Name of the detector that forces the full vocabulary, or ""."""
    if q.token_count > AMBIGUITY_TOKEN_LIMIT:
        return "ambiguous_query_length"
    if not _any(q.text, _KNOWN_ANALYTICAL_CUES):
        return "ambiguous_unknown_verb"
    if _any(q.text, NEGATION_CUES) and _any(q.text, AGGREGATION_CUES):
        return "ambiguous_negated_aggregation"
    if _any(q.text, ("and", "or")) and sum(
        _matches(q.text, cue) for cue in INTENT_CUES
    ) >= 2:
        return "ambiguous_multi_intent"
    return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def route_operator_bucket(
    query: str, schema_columns: Sequence[str] | None = None
) -> OperatorRoute:
    """Deterministic, no-LM operator router.

    Returns an OperatorRoute with:
      - candidate_ops: frozenset[str]      # union of surviving buckets
      - excluded_buckets: tuple[str, ...]  # bucket names removed
      - matched_rules: tuple[str, ...]     # rule_name for every require/exclude
      - used_full_fallback: bool

    Pure function: no I/O, no LLM client, no network calls.
    """
    q = _Query(
        text=_normalize(query),
        token_count=len(_normalize(query).split()),
        entity_cues=_entity_cues(schema_columns),
    )

    ambiguity = _ambiguity_rule(q)
    if ambiguity:
        return OperatorRoute(
            candidate_ops=BUCKET_FULL,
            excluded_buckets=(),
            matched_rules=(ambiguity,),
            used_full_fallback=True,
        )

    results = [result for rule in RULES for result in rule(q)]
    required = {r.bucket for r in results if r.verdict == "require"}
    excluded = {
        r.bucket for r in results if r.verdict == "exclude" and r.bucket not in required
    }
    excluded.discard(DIRECT)  # the baseline bucket is never excludable

    matched: list[str] = []
    for result in results:
        if result.verdict != "no_opinion" and result.rule_name not in matched:
            matched.append(result.rule_name)

    surviving = [
        (name, ops) for name, ops in BUCKETS if name == DIRECT or name not in excluded
    ]
    if not surviving:  # pragma: no cover — DIRECT always survives
        return OperatorRoute(BUCKET_FULL, tuple(sorted(excluded)), tuple(matched), True)

    candidate_ops: frozenset[str] = frozenset().union(*(ops for _, ops in surviving))
    if candidate_ops >= BUCKET_FULL:
        return OperatorRoute(BUCKET_FULL, (), tuple(matched), True)

    return OperatorRoute(
        candidate_ops=candidate_ops,
        excluded_buckets=tuple(sorted(excluded)),
        matched_rules=tuple(matched),
        used_full_fallback=False,
    )
