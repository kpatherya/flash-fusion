"""
eval/metrics.py — Accuracy, latency, and cost metrics for benchmark results.

Functions:
    compute_accuracy(result) → dict
  compute_latency(result) → dict
  compute_cost(result) → dict
  aggregate_metrics(results) → pd.DataFrame

Accuracy scoring rules (see CLAUDE.md §eval/metrics.py):
    Use raw LLM judge score (llm_score) in [0,1] when available.
    Missing or invalid judgments default to 0.0.
"""

from __future__ import annotations

import pandas as pd

from flashfusion.config import (
    ACCURACY_FAIL_SCORE,
    ACCURACY_PASS_SCORE,
)
from flashfusion.pipeline.runner import RunResult


def _normalize_verdict(verdict: str | None) -> str:
    if verdict is None:
        return ""
    return str(verdict).strip().upper()


def _score_from_llm_verdict(verdict: str | None) -> float:
    normalized = _normalize_verdict(verdict)
    if normalized == "PASS":
        return ACCURACY_PASS_SCORE
    return ACCURACY_FAIL_SCORE


def compute_accuracy(result: RunResult) -> dict:
    """
    Compute binary accuracy from the run-level judge verdict.

    PASS maps to 1.0; FAIL/missing/unknown map to 0.0.

    Args:
        result: RunResult from BaselineRunner.run().

    Returns:
        dict with keys:
            score      (float)        — 0.0 or 1.0
            executed   (bool)         — whether pandas agent ran code
            judge_pass (bool)         — True when verdict is PASS
            rejected   (bool)         — whether query was rejected by guardrail/S2
    """
    verdict = _normalize_verdict(
        result.judge_verdict.get("verdict") if result.judge_verdict else None
    )
    score = _score_from_llm_verdict(verdict)

    return {
        "score": score,
        "executed": result.executed,
        "judge_pass": verdict == "PASS",
        "rejected": result.rejected,
    }


def compute_latency(result: RunResult) -> dict:
    """
    Extract latency metrics from a RunResult.

    Args:
        result: RunResult from BaselineRunner.run().

    Returns:
        dict with keys:
            total_s (float) — end-to-end wall-clock latency in seconds
    """
    return {"total_s": result.latency_s}


def _canonical_stage_latencies_s(result: RunResult) -> dict[str, float]:
    """Return canonical stage latencies in seconds with stable defaults."""
    src = result.stage_latency_s if isinstance(result.stage_latency_s, dict) else {}
    guardrail_plan = float(
        src.get(
            "guardrail+plan",
            float(src.get("guardrail", 0.0) or 0.0)
            + float(src.get("plan", 0.0) or 0.0),
        )
        or 0.0
    )
    return {
        "guardrail": guardrail_plan,
        "cache_lookup": float(src.get("cache_lookup", 0.0) or 0.0),
        "cache_grounding": float(src.get("cache_grounding", 0.0) or 0.0),
        "cache_validation": float(src.get("cache_validation", 0.0) or 0.0),
        "cache_rejection": float(src.get("cache_rejection", 0.0) or 0.0),
        "cache_retry_overhead": float(src.get("cache_retry_overhead", 0.0) or 0.0),
        "typed_exec": float(src.get("typed_exec", 0.0) or 0.0),
        "agent": float(src.get("agent", 0.0) or 0.0),
    }


def compute_cost(result: RunResult) -> dict:
    """
    Extract cost metrics from a RunResult.

    Args:
        result: RunResult from BaselineRunner.run().

    Returns:
        dict with keys:
            total_usd     (float) — total estimated cost in USD
            input_tokens  (int)   — total estimated input tokens
            output_tokens (int)   — total estimated output tokens
    """
    return {
        "total_usd": result.cost_usd,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


#: Recorded cache_outcome values -> the coarse label used in reports/figures.
_RECORDED_CACHE_OUTCOMES = {
    "exact_hit": "hit",
    "semantic_hit": "hit",
    "hit_rejected": "hit_rejected",
    "miss": "miss",
    "disabled": "not_applicable",
}


def _cache_outcome_label(result: RunResult) -> str:
    """Classify a run into a branch-accurate cache outcome.

    Prefers the outcome the cache path recorded on the row itself. The
    execution_path/plan_source reconstruction below is retained only to read
    runs saved before ``cache_outcome`` existed; new runs never reach it.
    """
    recorded = str(getattr(result, "cache_outcome", "") or "")
    if recorded:
        return _RECORDED_CACHE_OUTCOMES.get(recorded, recorded)

    # --- legacy fallback for pre-cache_outcome result files ----------------
    if result.baseline != "FLASH_FUSION_CACHE":
        return "not_applicable"

    execution_path = str(getattr(result, "execution_path", "") or "")
    plan_source = str(getattr(result, "plan_source", "") or "")

    if execution_path == "typed_operator_cache":
        return "hit"

    if execution_path == "guardrail_reject" and plan_source.startswith(
        (
            "exact_query_cache_out_of_scope",
            "semantic_query_cache_out_of_scope",
            "semantic_cache_out_of_scope",
        )
    ):
        return "hit_rejected"

    return "miss"


def aggregate_metrics(
    results: list[RunResult],
    llm_judgments_df: pd.DataFrame | None = None,
    ground_truth_by_id=None,
    query_defs: list[dict] | None = None,
) -> pd.DataFrame:
    """
    Build a tidy DataFrame of per-(baseline, query) metrics.

    Each row corresponds to one RunResult. The DataFrame is sorted by
    (baseline, query_id) for consistent reporting.

    Args:
        results: List of RunResult objects from run_benchmark().

    Returns:
        pd.DataFrame with columns:
            baseline        (str)
            query_id        (int)   — stable ID shared across query versions
            gt_score        (float) — raw llm_score when present, else 0.0
            gt_method       (str)   — scoring method: llm_judge_score[(_missing)]
            latency_s       (float) — from compute_latency()
            cost_usd        (float) — from compute_cost()
            input_tokens    (int)
            output_tokens   (int)
            executed        (bool)
            rejected        (bool)
            judge_verdict   (str)   — "PASS", "FAIL", "N/A", or "UNKNOWN"
            stages_run      (str)   — comma-joined list of stage names

    Implementation:
        from flashfusion.eval.queries import WISDM_QUERIES
        Build a legacy lookup: query_text → query_id from WISDM_QUERIES.
        For each result:
            Prefer result.query_id.
            If absent, use the legacy text lookup or fail if unmatched.
            lat = compute_latency(result)
            cost = compute_cost(result)
            Append row dict to list.
        return pd.DataFrame(rows).sort_values(["baseline", "query_id"]).reset_index(drop=True)
    """
    from flashfusion.eval.queries import WISDM_QUERIES

    if query_defs is None:
        query_defs = WISDM_QUERIES
    query_lookup = {q["text"]: q["id"] for q in query_defs}
    judgment_by_key: dict[tuple[str, int], tuple[float, str]] = {}

    if llm_judgments_df is not None and not llm_judgments_df.empty:
        required = {"baseline", "query_id", "llm_verdict", "llm_score"}
        missing = [c for c in required if c not in llm_judgments_df.columns]
        if missing:
            raise ValueError(
                f"llm_judgments_df missing required columns: {sorted(missing)}"
            )

        for row in llm_judgments_df.to_dict(orient="records"):
            baseline = str(row.get("baseline", "")).strip()
            try:
                qid = int(row.get("query_id", 0))
            except (TypeError, ValueError):
                continue
            key = (baseline, qid)
            if key not in judgment_by_key:
                verdict = _normalize_verdict(row.get("llm_verdict"))
                try:
                    raw_score = float(row.get("llm_score", 0.0))
                except (TypeError, ValueError):
                    raw_score = 0.0
                raw_score = max(0.0, min(1.0, raw_score))
                judgment_by_key[key] = (raw_score, verdict)

    rows: list[dict] = []
    for r in results:
        lat = compute_latency(r)
        cost = compute_cost(r)
        stage_s = _canonical_stage_latencies_s(r)
        explicit_query_id = int(getattr(r, "query_id", 0) or 0)
        if explicit_query_id > 0:
            query_id = explicit_query_id
        else:
            query_id = query_lookup.get(r.query, 0)
            if query_id == 0:
                raise ValueError(
                    "Unable to resolve query identity for metrics: RunResult has "
                    f"query_id=0 and query text is unknown: {r.query!r}"
                )

        score_and_verdict = judgment_by_key.get((r.baseline, query_id))
        if score_and_verdict is None:
            expected_rejection = None
            if ground_truth_by_id is not None:
                gt_entry = ground_truth_by_id.get(query_id)
                if gt_entry is not None:
                    expected_rejection = bool(gt_entry.expected_rejection)

            if r.rejected and not r.executed and expected_rejection is not None:
                if expected_rejection:
                    gt_score = 1.0
                    gt_method = "guardrail_skip_expected_rejection"
                else:
                    gt_score = 0.0
                    gt_method = "guardrail_skip_unexpected_rejection"
            else:
                gt_score = 0.0
                gt_method = "llm_judge_score_missing"
            llm_verdict = ""
        else:
            gt_score, llm_verdict = score_and_verdict
            gt_method = "llm_judge_score"

        rows.append(
            {
                "baseline": r.baseline,
                "cache_outcome": _cache_outcome_label(r),
                "cache_outcome_reason": getattr(r, "cache_outcome_reason", ""),
                # Policy provenance travels with every row so a component-level
                # claim can be checked against the settings that produced it,
                # and so legacy and current labels for the same policy pool.
                "policy_name": getattr(r, "policy_name", ""),
                "policy_cache_enabled": getattr(r, "policy_cache_enabled", False),
                "policy_pruning_enabled": getattr(r, "policy_pruning_enabled", False),
                "policy_planner_guidance_enabled": getattr(
                    r, "policy_planner_guidance_enabled", False
                ),
                "policy_role": getattr(r, "policy_role", ""),
                "policy_reference": getattr(r, "policy_reference", ""),
                "policy_treatment": getattr(r, "policy_treatment", ""),
                "policy_digest": getattr(r, "policy_digest", ""),
                "route_mode": getattr(r, "route_mode", ""),
                "planner_guidance_mode": getattr(r, "planner_guidance_mode", ""),
                "planner_candidate_op_count": getattr(r, "planner_candidate_op_count", 0),
                "planner_full_vocabulary": getattr(r, "planner_full_vocabulary", False),
                "planner_prefix_chars": getattr(r, "planner_prefix_chars", 0),
                "planner_prefix_sha256": getattr(r, "planner_prefix_sha256", ""),
                "model": r.model,
                "query_id": query_id,
                "gt_score": gt_score,
                "gt_method": gt_method,
                "latency_s": lat["total_s"],
                "cost_usd": cost["total_usd"],
                "input_tokens": cost["input_tokens"],
                "output_tokens": cost["output_tokens"],
                "executed": r.executed,
                "rejected": r.rejected,
                "judge_verdict": (
                    r.judge_verdict.get("verdict", "N/A")
                    if r.judge_verdict
                    else "N/A"
                ),
                "stages_run": ",".join(r.stages_run),
                # Typed-vs-ReAct comparison signals. Coverage rate is
                # mean(execution_path == "typed_operator"); report latency and
                # accuracy separately for that subset rather than claiming an
                # aggregate win while ReAct still absorbs the harder tail.
                "execution_path": r.execution_path,
                "plan_validation_stage_failed": r.plan_validation_stage_failed,
                "plan_source": r.plan_source,
                "operators_used": ",".join(r.operators_used),
                "ff_planner_used": r.ff_planner_used,
                "ff_planner_latency_s": r.ff_planner_latency_s,
                "ff_planner_input_tokens": r.ff_planner_input_tokens,
                "ff_planner_output_tokens": r.ff_planner_output_tokens,
                "ff_planner_cost_usd": r.ff_planner_cost_usd,
                "guardrail_latency_s": stage_s["guardrail"],
                "cache_lookup_latency_s": stage_s["cache_lookup"],
                "cache_grounding_latency_s": stage_s["cache_grounding"],
                "cache_validation_latency_s": stage_s["cache_validation"],
                "cache_rejection_latency_s": stage_s["cache_rejection"],
                "cache_retry_overhead_s": stage_s["cache_retry_overhead"],
                "typed_exec_latency_s": stage_s["typed_exec"],
                "agent_latency_s": stage_s["agent"],
                "guardrail_latency_ms": stage_s["guardrail"] * 1000.0,
                "cache_lookup_latency_ms": stage_s["cache_lookup"] * 1000.0,
                "cache_grounding_latency_ms": stage_s["cache_grounding"] * 1000.0,
                "cache_validation_latency_ms": stage_s["cache_validation"] * 1000.0,
                "cache_rejection_latency_ms": stage_s["cache_rejection"] * 1000.0,
                "cache_retry_overhead_ms": stage_s["cache_retry_overhead"] * 1000.0,
                "typed_exec_latency_ms": stage_s["typed_exec"] * 1000.0,
                "agent_latency_ms": stage_s["agent"] * 1000.0,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["baseline", "query_id"]).reset_index(drop=True)
    return df
