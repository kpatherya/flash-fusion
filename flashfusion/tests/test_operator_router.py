"""tests/test_operator_router.py — deterministic operator router coverage.

The router is a pure function: no LLM client, no network, no I/O. These tests
verify (1) every canonical bucket is reachable, (2) the predictive bucket is
opt-in only, (3) the ambiguity override reaches the full vocabulary, and (4)
an operator-recall regression gate over labeled gold plans harvested from
historical full-vocabulary benchmark runs — 100% recall is the primary
correctness requirement, more important than bucket size.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from unittest.mock import patch

from flashfusion.pipeline.operator_router import (
    BUCKET_CORRELATION,
    BUCKET_DERIVE,
    BUCKET_DIRECT,
    BUCKET_FULL,
    BUCKET_GROUP_RANK,
    BUCKET_PARALLEL,
    BUCKET_PARTITION_COMPARE,
    BUCKET_PREDICTIVE,
    route_operator_bucket,
)

# (dataset, query_id) -> operators the full-vocabulary planner actually used to
# answer correctly (score >= 0.999), harvested from flashfusion/results/**/metrics.csv.
GOLD_OPERATORS: dict[tuple[str, int], list[str]] = {
    ("wisdm", 1): ["AGGREGATE_COLUMN", "FILTER_IN", "FILTER_NOT_EMPTY"],
    ("wisdm", 2): ["COUNT_DISTINCT", "COUNT_ROWS", "FILTER_IN"],
    ("wisdm", 3): ["AGGREGATE_COLUMN", "FILTER_IN"],
    ("wisdm", 4): [
        "AGGREGATE_COLUMN", "AGGREGATE_GROUPS", "GROUP_AGGREGATE",
        "RANK_GROUPS", "SELECT_COLUMN",
    ],
    ("wisdm", 5): [
        "AGGREGATE_PARTITIONS", "COMPARE_PARTITIONS",
        "DERIVE_VECTOR_MAGNITUDE", "SPLIT_BY_VALUES",
    ],
    ("wisdm", 6): [
        "DERIVE_BINARY", "DERIVE_DURATION_SECONDS", "FILTER_COMPARE",
        "FILTER_NOT_EMPTY", "PARALLEL_AGGREGATE", "RANK_ROWS",
    ],
    ("wisdm", 7): [
        "AGGREGATE_COLUMN", "DERIVE_VECTOR_MAGNITUDE", "FILTER_COMPARE",
        "FILTER_EQ_AGGREGATE", "FILTER_IN",
    ],
    ("wisdm", 8): [
        "AGGREGATE_COLUMN", "AGGREGATE_PARTITIONS", "COMPARE_PARTITIONS",
        "DERIVE_VECTOR_MAGNITUDE", "FILTER_IN", "FILTER_NOT_EMPTY",
        "SPLIT_BY_VALUES",
    ],
    ("wisdm", 13): ["PREDICTIVE_PIPELINE"],
    ("wisdm", 14): ["PREDICTIVE_PIPELINE"],
    ("wisdm", 15): ["PREDICTIVE_PIPELINE"],
    ("wisdm", 16): ["PREDICTIVE_PIPELINE"],
    ("mit_ecg", 1): ["AGGREGATE_COLUMN", "FILTER_COMPARE", "FILTER_IN"],
    ("mit_ecg", 2): ["AGGREGATE_COLUMN", "FILTER_COMPARE", "FILTER_IN"],
    ("mit_ecg", 3): ["COUNT_ROWS", "FILTER_COMPARE", "FILTER_IN"],
    ("mit_ecg", 4): [
        "FILTER_EQ_AGGREGATE", "FILTER_IN", "FILTER_NOT_EMPTY",
        "RANK_ROWS", "SELECT_COLUMN", "AGGREGATE_COLUMN",
    ],
    ("mit_ecg", 5): [
        "AGGREGATE_GROUPS", "DERIVE_BIN", "FILTER_COMPARE",
        "FILTER_NOT_EMPTY", "GROUP_AGGREGATE",
    ],
    ("mit_ecg", 6): [
        "AGGREGATE_GROUPS", "DERIVE_BINARY", "GROUP_AGGREGATE",
        "PARALLEL_AGGREGATE", "RANK_GROUPS", "RANK_ROWS",
    ],
    ("mit_ecg", 7): [
        "DERIVE_BIN", "FILTER_COMPARE", "FILTER_IN",
        "FILTER_NOT_EMPTY", "GROUP_AGGREGATE", "RANK_GROUPS",
    ],
    ("mit_ecg", 8): ["AGGREGATE_COLUMN", "FILTER_COMPARE", "FILTER_IN"],
    ("mit_ecg", 13): ["FILTER_COMPARE", "PREDICTIVE_PIPELINE"],
    ("mit_ecg", 14): ["FILTER_COMPARE", "PREDICTIVE_PIPELINE"],
    ("mit_ecg", 15): ["FILTER_COMPARE", "PREDICTIVE_PIPELINE"],
    ("mit_ecg", 16): ["FILTER_COMPARE", "PREDICTIVE_PIPELINE"],
    ("bus", 1): ["AGGREGATE_COLUMN"],
    ("bus", 2): ["AGGREGATE_COLUMN"],
    ("bus", 3): ["AGGREGATE_COLUMN", "FILTER_EQ_AGGREGATE", "SELECT_COLUMN"],
    ("bus", 4): ["COUNT_ROWS", "FILTER_COMPARE"],
    ("bus", 5): ["AGGREGATE_PARTITIONS", "COMPARE_PARTITIONS", "SPLIT_BY_THRESHOLD"],
    ("bus", 6): ["DERIVE_BINARY", "PARALLEL_AGGREGATE", "RANK_ROWS"],
    ("bus", 7): ["AGGREGATE_COLUMN", "DERIVE_VECTOR_MAGNITUDE"],
    ("bus", 8): ["DERIVE_BIN", "GROUP_AGGREGATE", "RANK_GROUPS", "SELECT_COLUMN"],
    ("bus", 13): ["PREDICTIVE_PIPELINE"],
    ("bus", 14): ["PREDICTIVE_PIPELINE"],
    ("bus", 15): ["PREDICTIVE_PIPELINE"],
    ("bus", 16): ["PREDICTIVE_PIPELINE"],
}


def test_router_is_pure_no_llm_or_network_call() -> None:
    """The router must never touch a provider client or the network."""
    with patch("socket.socket") as sock, patch("urllib.request.urlopen") as urlopen:
        route = route_operator_bucket(
            "Which subject has the highest average magnitude per activity?"
        )
    sock.assert_not_called()
    urlopen.assert_not_called()
    assert route.candidate_ops  # sanity: still returned a route


def test_router_import_falls_back_when_numpy_is_unavailable(monkeypatch) -> None:
    module_name = "flashfusion.pipeline.operator_router"
    real_import = builtins.__import__
    original_module = sys.modules.get(module_name)

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "flashfusion.pipeline.operators":
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules.pop(module_name, None)
    try:
        fallback_module = importlib.import_module(module_name)
        assert fallback_module.BUCKET_FULL == BUCKET_FULL
        assert fallback_module.route_operator_bucket("What is the average x value?")
    finally:
        sys.modules.pop(module_name, None)
        if original_module is not None:
            sys.modules[module_name] = original_module


def test_every_canonical_bucket_is_reachable() -> None:
    """At least one representative query must select each non-direct bucket
    without falling back to the full vocabulary."""
    representative_queries = {
        BUCKET_GROUP_RANK: "What is the average magnitude per activity?",
        BUCKET_PARTITION_COMPARE: "Compare average magnitude above vs below the median.",
        BUCKET_DERIVE: "What is the average duration in seconds per session?",
        BUCKET_CORRELATION: "Is there a correlation between x and y?",
        BUCKET_PARALLEL: "For each of the activities, what is the peak magnitude?",
        BUCKET_PREDICTIVE: "Predict the activity label for the next observation.",
    }
    for bucket, query in representative_queries.items():
        route = route_operator_bucket(query)
        assert not route.used_full_fallback, query
        assert bucket <= route.candidate_ops, (bucket, route.candidate_ops)

    direct_route = route_operator_bucket("What is the average x value?")
    assert BUCKET_DIRECT <= direct_route.candidate_ops


def test_predictive_bucket_excluded_for_generic_observational_query() -> None:
    route = route_operator_bucket("Which activity occurred most frequently?")
    assert not route.used_full_fallback
    assert "PREDICTIVE_PIPELINE" not in route.candidate_ops
    assert "default_predictive" in route.matched_rules


def test_predictive_bucket_required_for_explicit_predictive_query() -> None:
    route = route_operator_bucket("Predict the next activity for this subject.")
    assert "PREDICTIVE_PIPELINE" in route.candidate_ops
    assert "require_predictive_cue" in route.matched_rules


def test_ambiguity_override_routes_to_full_bucket() -> None:
    route = route_operator_bucket("Xyzzy plugh the frobnicate widget?")
    assert route.used_full_fallback is True
    assert route.candidate_ops == BUCKET_FULL
    assert route.excluded_buckets == ()


def test_ambiguity_override_on_negated_aggregation() -> None:
    route = route_operator_bucket("What is the average excluding outliers?")
    assert route.used_full_fallback is True
    assert "ambiguous_negated_aggregation" in route.matched_rules


def test_ambiguity_override_on_query_length() -> None:
    long_query = "What is the average magnitude " + "and also the total count " * 20
    route = route_operator_bucket(long_query)
    assert route.used_full_fallback is True
    assert "ambiguous_query_length" in route.matched_rules


def test_direct_bucket_is_never_excluded() -> None:
    for query in (
        "Predict the next activity.",
        "Is there a correlation between x and y?",
        "What is the average x value?",
    ):
        route = route_operator_bucket(query)
        assert BUCKET_DIRECT <= route.candidate_ops


def test_operator_recall_regression_against_gold_fixture() -> None:
    """Every operator the full-vocabulary planner actually needed to answer a
    query correctly must still survive routing — 100% recall, no exceptions."""
    from flashfusion.eval.queries import get_queries

    misses: list[str] = []
    for dataset in ("wisdm", "mit_ecg", "bus"):
        queries_by_id = {q["id"]: q for q in get_queries(dataset)}
        for (ds, query_id), gold_ops in GOLD_OPERATORS.items():
            if ds != dataset:
                continue
            query_def = queries_by_id[query_id]
            route = route_operator_bucket(query_def["text"])
            missing = set(gold_ops) - route.candidate_ops
            if missing:
                misses.append(f"{dataset}#{query_id}: missing {sorted(missing)}")

    assert not misses, "operator recall regression:\n" + "\n".join(misses)
