from __future__ import annotations

"""
eval/benchmark.py — CLI entry point for the Flash-Fusion benchmark.

Usage:
    python -m flashfusion.eval.benchmark --help

    # Smoke test (3 queries × default 2 baselines)
    python -m flashfusion.eval.benchmark \\
        --data data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt \\
        --queries 1,4,10 \\
        --output flashfusion/eval_results/

    # Full benchmark
    python -m flashfusion.eval.benchmark \\
        --data data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt \\
        --baselines REACT_ONLY,FLASH_FUSION \\
        --output flashfusion/eval_results/

Environment:
    OPENROUTER_API_KEY — preferred; GROQ_API_KEY accepted during transition

See CLAUDE.md §eval/benchmark.py for the full run_benchmark() algorithm.
"""

"""
Tips:

How to produce the before/after (your run)
ReAct OOS (Q9–12), before vs after — the prompt change is now live, so "before" = git-stash/revert of the prefix or a prior run; "after" = current:
```

react before/after QUERIES:
python -m flashfusion.eval.benchmark --dataset bus \
    --data data/bus/bus_data_enriched_behavior.csv --baselines REACT_ONLY --queries 9,10,11,12 --runs 3 \
  --ground-truth flashfusion/eval/ground_truth/ground_truth_bus.json \
  --output flashfusion/results/react_oos_after/bus

python -m flashfusion.eval.benchmark --dataset wisdm \
  --data data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt --baselines REACT_ONLY --queries 9,10,11,12 --runs 3 \
  --ground-truth flashfusion/eval/ground_truth/ground_truth_wisdm.json \
  --output flashfusion/results/react_oos_after/wisdm
  
python -m flashfusion.eval.benchmark --dataset mit_ecg \
  --data data/AutoIOT_dataset/ECG.0/MIT_arrythmia_v1.txt --baselines REACT_ONLY --queries 9,10,11,12 --runs 3 \
  --ground-truth flashfusion/eval/ground_truth/ground_truth_mit_ecg.json \
  --output flashfusion/results/react_oos_after/mit_ecg  
```

PREDICTIVE QUERIES:

(i) Bus data
python -m flashfusion.eval.benchmark \
    --dataset bus \
    --data data/bus/bus_data_enriched_behavior.csv \
    --baselines FLASH_FUSION,REACT_ONLY,AUTOIOT_PAPER \
    --queries 13,14,15,16 \
  --runs 3 \
  --ground-truth flashfusion/eval/ground_truth/ground_truth_bus.json \
  --output flashfusion/results/predictive_n3/bus

(ii) WISDM data
python -m flashfusion.eval.benchmark \
    --dataset wisdm \
    --data data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt \
    --baselines FLASH_FUSION,REACT_ONLY,AUTOIOT_PAPER \
    --queries 13,14,15,16 \
  --runs 3 \
  --ground-truth flashfusion/eval/ground_truth/ground_truth_wisdm.json \
  --output flashfusion/results/predictive_n3/wisdm

(iii) MIT ECG data
python -m flashfusion.eval.benchmark \
    --dataset mit_ecg \
    --data data/AutoIOT_dataset/ECG.0/MIT_arrythmia_v1.txt \
    --baselines FLASH_FUSION,REACT_ONLY,AUTOIOT_PAPER \
    --queries 13,14,15,16 \
  --runs 3 \
  --ground-truth flashfusion/eval/ground_truth/ground_truth_mit_ecg.json \
  --output flashfusion/results/predictive_n3/mit_ecg

Flash-Fusion SLM, before vs after:
```
# before (70B everywhere)
python -m flashfusion.eval.benchmark --dataset bus --data data/bus/bus_data_enriched_behavior.csv \
  --baselines FLASH_FUSION --queries all \
  --ground-truth flashfusion/eval/ground_truth/ground_truth_bus.json \
  --output flashfusion/results/ff_70b/bus

# after (8B on S1/S2)
python -m flashfusion.eval.benchmark --dataset bus --data data/bus/bus_data_enriched_behavior.csv \
  --baselines FLASH_FUSION --queries all --stage12-model qwen/qwen-2.5-7b-instruct \
  --ground-truth flashfusion/eval/ground_truth/ground_truth_bus.json \
  --output flashfusion/results/ff_8b_s12/bus
```

"""

import argparse
import dataclasses
import json
import os
import random
import signal
import sys
import time

import pandas as pd
import numpy as np

from flashfusion.eval.ground_truth import load_ground_truth
from flashfusion.eval.ground_truth_llm_judge import (
    run_llm_ground_truth_judge,
    summarize_judgments,
    _rows_from_run_results,
)
from flashfusion.eval.metrics import aggregate_metrics
from flashfusion.eval.queries import (
    DATASET_WISDM,
    SUPPORTED_DATASETS,
    get_queries,
)
from flashfusion.eval import queries_v2, queries_v3
from flashfusion.eval.reporter import print_table, save_csv, save_markdown
from flashfusion.pipeline.loader import load_dataset_by_name
from flashfusion.pipeline.runner import (
    BaselineRunner,
    LLMClient,
    RunResult,
    _is_groq_model,
)
from flashfusion.baselines.flash_fusion_policy import (
    LEGACY_POLICY_ALIASES,
    POLICIES,
    PRIMARY_POLICY_SET,
    is_flash_fusion_policy,
    resolve_policy,
)
from flashfusion.config import DEFAULT_LIGHT_MODEL, DEFAULT_MODEL

ALL_BASELINES = [
    "LLM_ONLY",
    "WELLMAX_ONLY",
    "REACT_ONLY",
    "AUTOIOT_PAPER",
    "HARGPT_PAPER",
    "LLMSENSE_PAPER",
    # Flash-Fusion policy arms (see baselines/flash_fusion_policy.py).
    *PRIMARY_POLICY_SET,
]

#: Every accepted Flash-Fusion label, canonical and legacy.
FLASH_FUSION_BASELINES = frozenset(POLICIES) | frozenset(LEGACY_POLICY_ALIASES)

#: The four arms that support component-level claims.
PRIMARY_ABLATION_BASELINES = ",".join(PRIMARY_POLICY_SET)

DEFAULT_DATA_PATHS = {
    "wisdm": "data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt",
    "mit_ecg": "data/AutoIOT_dataset/ECG.0/MIT_arrythmia_v1.txt",
    "bus": "data/bus/bus_data_enriched_behavior.csv",
}

DEFAULT_GROUND_TRUTH_PATHS = {
    "wisdm": "flashfusion/eval/ground_truth/ground_truth_wisdm.json",
    "mit_ecg": "flashfusion/eval/ground_truth/ground_truth_mit_ecg.json",
    "bus": "flashfusion/eval/ground_truth/ground_truth_bus.json",
}

SEMANTIC_CACHE_REGISTRY_PATHS = {
    "wisdm": "flashfusion/eval/cache/semantic_registry_wisdm_v1.json",
    "mit_ecg": "flashfusion/eval/cache/semantic_registry_mit_ecg_v1.json",
    "bus": "flashfusion/eval/cache/semantic_registry_bus_v1.json",
}

_CACHE_QUERY_VERSIONS = {1: "v1", 2: "v2", 3: "v3"}
_QUERY_MAX_ATTEMPTS = 3
_QUERY_RETRY_BACKOFF_BASE_S = 2.0


def _cache_queries_for_run(dataset: str, run_id: int) -> tuple[str, list[dict]]:
    """Return the cache baseline's query bank for a repeated benchmark run."""
    version = _CACHE_QUERY_VERSIONS.get(run_id, "v1")
    if version == "v2":
        return version, queries_v2.get_queries(dataset)
    if version == "v3":
        return version, queries_v3.get_queries(dataset)
    return version, get_queries(dataset)


def _cache_query_order_for_run(
    *,
    query_ids: list[int],
    run_id: int,
    randomize: bool,
    base_seed: int,
) -> tuple[list[int], int | None]:
    ordered = list(query_ids)
    if not randomize:
        return ordered, None
    seed = int(base_seed) + int(run_id) - 1
    rng = random.Random(seed)
    rng.shuffle(ordered)
    return ordered, seed


def _rewording_baselines(baselines: list[str], mode: str) -> set[str]:
    """Return the baselines that get the per-run reworded query bank.

    The v1/v2/v3 reworded banks and the shuffled order exist to exercise
    *semantic* cache matching, so historically only ``FLASH_FUSION_CACHE``
    received them. That is fine when the cache baseline is measured on its own,
    but it destroys paired comparison the moment a cache arm and a no-cache arm
    appear in the same experiment: the two arms would be answering differently
    worded questions in different orders.

    Modes:
        ``paired`` — nobody gets rewording; every arm sees the same bank in the
            same order. Required for the FF_FULL vs FF_NO_CACHE contrast.
        ``cache-only`` — legacy behaviour; cache policies get the reworded bank.
        ``auto`` — ``cache-only`` when the run contains no non-cache
            Flash-Fusion arm to pair against, otherwise ``paired``.
    """
    policy_arms = [b for b in baselines if is_flash_fusion_policy(b)]
    cache_arms = {b for b in policy_arms if resolve_policy(b).cache}

    if mode == "paired":
        return set()
    if mode == "cache-only":
        return cache_arms
    if mode != "auto":
        raise ValueError(f"unknown query-rewording mode {mode!r}")

    non_cache_arms = [b for b in policy_arms if not resolve_policy(b).cache]
    return set() if (cache_arms and non_cache_arms) else cache_arms


def _per_baseline_overrides(
    *,
    baselines: list[str],
    rewording_mode: str,
    cache_query_defs: list[dict],
    cache_order_ids: list[int],
) -> tuple[dict[str, list[dict]], dict[str, list[int]]]:
    """Build the per-baseline query-bank and query-order override maps."""
    targets = _rewording_baselines(baselines, rewording_mode)
    defs_by_baseline = {b: cache_query_defs for b in targets}
    ids_by_baseline = {b: cache_order_ids for b in targets}
    return defs_by_baseline, ids_by_baseline


def _run_schedule(
    *,
    baselines: list[str],
    query_ids: list[int],
    query_ids_by_baseline: dict[str, list[int]] | None,
    interleave: bool,
) -> list[tuple[str, int]]:
    """Return the (baseline, query_id) execution order for one replicate.

    Blocked order (``interleave=False``) runs every query of one arm before
    starting the next, which confounds arm with wall-clock position: provider
    load, rate-limit backoff and cache warmth all drift over a run and that
    drift lands entirely on whichever arm occupied that stretch of time.

    Interleaved order runs all arms on one query before moving to the next, so
    that drift is shared across arms at each query instead of being absorbed
    by one of them. Arm order is rotated per query so no arm is always first,
    which would otherwise let it consistently absorb cold-start cost.
    """
    per_baseline = {
        baseline: list((query_ids_by_baseline or {}).get(baseline, query_ids))
        for baseline in baselines
    }
    if not interleave:
        return [(b, qid) for b in baselines for qid in per_baseline[b]]

    schedule: list[tuple[str, int]] = []
    for position in range(max((len(v) for v in per_baseline.values()), default=0)):
        rotated = baselines[position % len(baselines):] + baselines[: position % len(baselines)]
        for baseline in rotated:
            ids = per_baseline[baseline]
            if position < len(ids):
                schedule.append((baseline, ids[position]))
    return schedule


def _query_defs_for_reporting(
    query_defs: list[dict], query_defs_by_baseline: dict[str, list[dict]] | None
) -> list[dict]:
    """Include reworded query text in the shared query-text-to-ID lookup."""
    by_text = {str(query["text"]): query for query in query_defs}
    for definitions in (query_defs_by_baseline or {}).values():
        for query in definitions:
            by_text.setdefault(str(query["text"]), query)
    return list(by_text.values())

class QueryTimeoutError(TimeoutError):
    """Raised when a single query run exceeds the configured latency budget."""


def _is_retryable_query_error(exc: Exception) -> bool:
    """Return whether a failed benchmark query may safely be retried."""
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    return type(exc).__name__ == "TooManyRequestsResponseError"


def _query_retry_delay_seconds(exc: Exception, attempt: int) -> float:
    """Return a bounded provider-requested or exponential retry delay."""
    headers = getattr(exc, "headers", None)
    retry_after = headers.get("retry-after") if headers is not None else None
    try:
        if retry_after is not None:
            return min(max(float(retry_after), 0.0), 30.0)
    except (TypeError, ValueError):
        pass
    return min(_QUERY_RETRY_BACKOFF_BASE_S * (2**attempt), 30.0)


def _is_forbidden_chat_data_path(path: str) -> bool:
    """Return True when path points to legacy chat/data content."""
    normalized = os.path.normpath(path).replace("\\", "/")
    if normalized == "chat/data" or normalized.startswith("chat/data/"):
        return True
    return "/chat/data/" in normalized


def _is_under_data_root(path: str) -> bool:
    """Return True when path resolves under a data/ segment."""
    normalized = os.path.normpath(path).replace("\\", "/")
    return normalized.startswith("data/") or "/data/" in normalized


def _json_serialize(obj):
    """Custom JSON serializer for pandas/numpy types."""
    # Pandas types
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, np.datetime64):
        return pd.Timestamp(obj).isoformat()
    
    # Numpy scalar types - use generic base classes
    if isinstance(obj, (np.integer, np.floating, np.bool_, np.complexfloating)):
        return obj.item()
    
    # Numpy arrays
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    
    # Pandas NA/NaT/None
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    
    # Generic numpy scalar fallback
    if hasattr(obj, 'item') and callable(obj.item):
        try:
            return obj.item()
        except (TypeError, ValueError):
            pass
    
    # Last resort: try str() for any remaining numpy/pandas types
    if type(obj).__module__.startswith(('numpy', 'pandas')):
        return str(obj)
    
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _baseline_summary(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """Compute baseline-level averages from a per-query metrics dataframe."""
    metric_cols = [
        c
        for c in ["gt_score", "latency_s", "cost_usd", "input_tokens", "output_tokens"]
        if c in metrics_df.columns
    ]
    if metrics_df.empty:
        return pd.DataFrame(columns=["baseline", *metric_cols])
    return (
        metrics_df.groupby("baseline", as_index=False)[metric_cols]
        .mean()
        .sort_values("baseline")
        .reset_index(drop=True)
    )


def _print_flash_fusion_router_summary(metrics_df: pd.DataFrame) -> None:
    """Print planner telemetry for the current benchmark slice."""
    ff = metrics_df[metrics_df["baseline"] == "FLASH_FUSION"]
    if ff.empty:
        return

    planner_used = ff["ff_planner_used"].astype(bool)
    print("\n=== Flash-Fusion Router Summary ===")
    subset = ff[planner_used]
    if subset.empty:
        print("Planner: no calls")
        return
    print(
        f"Planner: median={subset['ff_planner_latency_s'].median():.3f}s "
        f"p95={subset['ff_planner_latency_s'].quantile(0.95):.3f}s "
        f"avg_tokens={subset['ff_planner_input_tokens'].mean():.1f}in/"
        f"{subset['ff_planner_output_tokens'].mean():.1f}out "
        f"avg_cost=${subset['ff_planner_cost_usd'].mean():.6f}"
    )


def _write_cache_grounding_issues(output_dir: str, raw_results_path: str) -> None:
    """Write a human-readable report of FLASH_FUSION_CACHE grounding failures.

    A record is emitted whenever a FLASH_FUSION_CACHE run includes the
    ``cache_miss_or_validation_failure`` stage.  The report is saved as
    ``cache_grounding_issues.md`` in the parent dataset result directory so
    the exact cache-grounding failure is preserved alongside the benchmark
    artifacts.
    """
    if not os.path.exists(raw_results_path):
        return

    issues: list[dict] = []
    with open(raw_results_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("baseline") != "FLASH_FUSION_CACHE":
                continue
            if "cache_miss_or_validation_failure" not in rec.get("stages_run", []):
                continue
            issues.append(rec)

    if not issues:
        return

    issues.sort(key=lambda r: (r.get("run_id", 1), r.get("query_id", 0)))

    lines: list[str] = ["# Cache Grounding Issues\n\n"]
    lines.append(
        f"Reported {len(issues)} FLASH_FUSION_CACHE grounding failure(s) where the "
        "cached skeleton could not be reused directly.\n\n"
    )

    for rec in issues:
        qid = rec.get("query_id", "?")
        run_id = rec.get("run_id")
        header = f"## Query {qid}"
        if run_id is not None:
            header += f" (run {run_id})"
        lines.append(header + "\n\n")
        lines.append(f"**Query text:** {rec.get('query', '')}\n\n")
        lines.append(
            f"**Failure reason:** `{rec.get('deterministic_fallback_reason', '(none)')}`\n\n"
        )
        lines.append(
            f"**Execution path after fallback:** `{rec.get('execution_path', '')}`\n\n"
        )
        lines.append(
            f"**Plan source after fallback:** `{rec.get('plan_source', '')}`\n\n"
        )
        if rec.get("plan_validation_stage_failed"):
            lines.append(
                f"**Plan validation stage failed:** "
                f"`{rec['plan_validation_stage_failed']}`\n\n"
            )

        typed_plan = rec.get("typed_plan") or {}
        if typed_plan:
            lines.append("**Typed plan executed after fallback:**\n")
            lines.append("```json\n")
            lines.append(json.dumps(typed_plan, indent=2, ensure_ascii=False))
            lines.append("\n```\n\n")

        raw_plan = rec.get("raw_plan") or {}
        if raw_plan:
            lines.append("**Raw planner output (before normalization):**\n")
            lines.append("```json\n")
            lines.append(json.dumps(raw_plan, indent=2, ensure_ascii=False))
            lines.append("\n```\n\n")

        final_code = rec.get("final_code", "")
        if final_code:
            lines.append("**Final executed code:**\n")
            lines.append("```python\n")
            lines.append(final_code)
            lines.append("\n```\n\n")

        stages_run = rec.get("stages_run", [])
        if stages_run:
            lines.append("**Stages run:** " + " → ".join(stages_run) + "\n\n")

        lines.append("---\n\n")

    out_path = os.path.join(output_dir, "cache_grounding_issues.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    print(f"\nCache grounding issues written to {out_path}", flush=True)


def _prewarm_provider_prompt_caches(
    *,
    baselines: list[str],
    query_defs: list[dict],
    query_ids: list[int],
    df: pd.DataFrame,
    model_name: str,
    api_key: str,
    stage12_model: str | None,
    light_api_key: str | None,
    dataset: str,
    cache_path: str | None,
) -> None:
    """Populate static provider prompt caches outside benchmark query timing.

    Each policy is warmed for the exact (route_mode, planner_guidance) prefix
    it will send. Warming only the router-narrowed, guidance-on prefix — as an
    earlier version did — left the no-pruning arm sending an unwarmed
    full-vocabulary prefix, so a cold provider cache was charged to "pruning".
    """
    policy_baselines = [b for b in baselines if is_flash_fusion_policy(b)]
    if not policy_baselines:
        return

    setup_client = LLMClient(
        model_name=model_name,
        api_key=api_key,
        light_model_name=stage12_model,
        light_api_key=light_api_key,
    )
    warmed: list[str] = []
    cache_policies = [b for b in policy_baselines if resolve_policy(b).cache]
    try:
        from flashfusion.baselines.flash_fusion_no_cache import (
            prewarm_flash_fusion_prompt_cache,
        )

        selected_queries = [
            query["text"] for query in query_defs if int(query["id"]) in set(query_ids)
        ]
        # Deduplicate by prefix variant: two arms sharing (route_mode,
        # guidance) share byte-identical prefixes and must not be warmed twice.
        variants: dict[tuple[str, str], list[str]] = {}
        for baseline in policy_baselines:
            policy = resolve_policy(baseline)
            key = (policy.route_mode, policy.planner_guidance_mode)
            variants.setdefault(key, []).append(baseline)

        for (route_mode, guidance), arms in sorted(variants.items()):
            count = prewarm_flash_fusion_prompt_cache(
                df,
                setup_client,
                selected_queries,
                planner_guidance=guidance,
                route_mode=route_mode,
            )
            warmed.append(
                f"planner_prefixes[route={route_mode},guidance={guidance}]"
                f"={count}({'+'.join(sorted(arms))})"
            )
        if cache_policies:
            from flashfusion.baselines.flash_fusion_cache import (
                DEFAULT_CACHE_PATH,
                prewarm_flash_fusion_cache_prompt_cache,
            )

            count = prewarm_flash_fusion_cache_prompt_cache(
                client=setup_client.light,
                cache_path=cache_path or DEFAULT_CACHE_PATH,
                dataset=dataset,
                query_ids=query_ids,
            )
            warmed.append(f"cache_prefixes={count}")
    except Exception as exc:  # Prompt caching is an optional provider optimization.
        print(
            f"[PROMPT_CACHE_WARMUP] skipped after {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return

    print(
        "[PROMPT_CACHE_WARMUP] "
        + " ".join(warmed)
        + f" latency_s={setup_client.total_latency():.3f}"
        + f" tokens={setup_client.total_input_tokens()}in/{setup_client.total_output_tokens()}out"
        + f" cached_tokens={setup_client.total_cached_tokens()}"
        + f" cache_write_tokens={setup_client.total_cache_write_tokens()}"
        + f" cost=${setup_client.total_cost_usd():.6f}",
        flush=True,
    )


def _run_single_benchmark_iteration(
    *,
    baselines: list[str],
    query_ids: list[int],
    df_base: pd.DataFrame,
    output_dir: str,
    model_name: str,
    api_key: str,
    ground_truth_by_id,
    data_path: str,
    max_query_latency: float,
    llm_judge_max_answer_chars: int,
    llm_judge_max_code_chars: int,
    dataset: str,
    query_defs: list[dict],
    query_ids_by_baseline: dict[str, list[int]] | None = None,
    query_defs_by_baseline: dict[str, list[dict]] | None = None,
    stage12_model: str | None = None,
    light_api_key: str | None = None,
    cache_path: str | None = None,
    semantic_cache_path: str | None = None,
    prewarm_cache_runtime: bool = True,
    interleave_policies: bool = False,
) -> tuple[list[RunResult], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Execute one full baseline x query benchmark run and persist artifacts."""
    report_query_defs = _query_defs_for_reporting(query_defs, query_defs_by_baseline)
    os.makedirs(output_dir, exist_ok=True)
    raw_results_path = os.path.join(output_dir, "raw_results.jsonl")
    if os.path.exists(raw_results_path):
        os.remove(raw_results_path)

    # Hybrid-matcher warmup is a one-time embedding-model load and index build.
    # It must happen before any timed query and outside the per-query loop, so
    # that an interleaved schedule does not charge it to whichever arm happens
    # to run first.
    if prewarm_cache_runtime and any(
        is_flash_fusion_policy(b) and resolve_policy(b).cache for b in baselines
    ):
        from flashfusion.baselines.flash_fusion_cache import (
            DEFAULT_CACHE_PATH,
            prewarm_hybrid_cache_runtime,
        )

        warm = prewarm_hybrid_cache_runtime(
            df=df_base,
            dataset=dataset,
            cache_path=cache_path or DEFAULT_CACHE_PATH,
            semantic_cache_path=semantic_cache_path,
        )
        print(
            "[cache runtime] prewarm complete: "
            f"model_load_ms={warm.get('model_load_ms', 0.0):.2f} "
            f"warm_up_ms={warm.get('warm_up_ms', 0.0):.2f} "
            f"dense_index_build_ms={warm.get('dense_index_build_ms', 0.0):.2f}",
            flush=True,
        )

    results: list[RunResult] = []
    for baseline, qid in _run_schedule(
        baselines=baselines,
        query_ids=query_ids,
        query_ids_by_baseline=query_ids_by_baseline,
        interleave=interleave_policies,
    ):
        baseline_queries = (query_defs_by_baseline or {}).get(baseline, query_defs)
        baseline_query_lookup = {int(query["id"]): query for query in baseline_queries}

        query_def = baseline_query_lookup.get(int(qid))
        if query_def is None:
            raise ValueError(f"Query id {qid} was not found in baseline query definitions.")
        query_text = query_def["text"]
        print(
            f"\n[{baseline}] Q{qid}: {query_text[:60]}...",
            flush=True,
        )
        # print(f"  [DEBUG] Starting runner.run() at {time.strftime('%H:%M:%S')}", flush=True)

        # DEBUG: Check df_base before passing to runner
        # import sys
        # print(f"[BENCHMARK DEBUG] df_base len={len(df_base)}, cols={list(df_base.columns)}", file=sys.stderr, flush=True)
        # if len(df_base) > 0:
        #     print(f"[BENCHMARK DEBUG] df_base.head(3):\n{df_base.head(3)}", file=sys.stderr, flush=True)

        t0 = time.time()
        client: LLMClient | None = None

        def _timeout_handler(signum, frame):
            raise QueryTimeoutError()

        prev_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, max_query_latency)
        try:
            for attempt in range(_QUERY_MAX_ATTEMPTS):
                client = LLMClient(
                    model_name=model_name,
                    api_key=api_key,
                    light_model_name=stage12_model,
                    light_api_key=light_api_key,
                )
                runner = BaselineRunner(
                    mode=baseline,
                    df=df_base.copy(),
                    client=client,
                    dataset=dataset,
                    cache_path=cache_path,
                    semantic_cache_path=(
                        semantic_cache_path
                        if is_flash_fusion_policy(baseline)
                        and resolve_policy(baseline).cache
                        else None
                    ),
                )
                try:
                    result = runner.run(query_text)
                    break
                except Exception as exc:
                    if not _is_retryable_query_error(exc) or attempt + 1 == _QUERY_MAX_ATTEMPTS:
                        raise
                    retry_delay = _query_retry_delay_seconds(exc, attempt)
                    print(
                        f"  [WARN] {type(exc).__name__} on query attempt "
                        f"{attempt + 1}/{_QUERY_MAX_ATTEMPTS}; retrying in "
                        f"{retry_delay:.1f}s...",
                        flush=True,
                    )
                    time.sleep(retry_delay)
        except QueryTimeoutError:
            elapsed = time.time() - t0
            result = RunResult(
                baseline=baseline,
                model=model_name,
                query=query_text,
                answer=(
                    f"[TIMEOUT] Query exceeded {max_query_latency:.1f}s "
                    "latency budget; skipped to next query."
                ),
                rejected=False,
                executed=False,
            )
            result.latency_s = elapsed
            result.rejection_reason = (
                f"Timed out after {elapsed:.2f}s (budget {max_query_latency:.2f}s)"
            )
            result.stages_run = ["timeout"]
            if client is not None:
                result.input_tokens = client.total_input_tokens()
                result.output_tokens = client.total_output_tokens()
                result.cost_usd = client.total_cost_usd()
        except Exception as e:
            import traceback
            tb_lines = traceback.format_exc().splitlines()
            traceback_tail = "\n".join(tb_lines[-10:]) if len(tb_lines) > 10 else traceback.format_exc()
            error_msg = f"[ERROR] {type(e).__name__}: {e}"
            result = RunResult(
                baseline=baseline,
                model=model_name,
                query=query_text,
                answer=error_msg,
                rejected=False,
                executed=False,
            )
            result.alignment_explanation = f"Exception during {baseline} execution:\n{traceback_tail}"
            if client is not None:
                result.input_tokens = client.total_input_tokens()
                result.output_tokens = client.total_output_tokens()
                result.cost_usd = client.total_cost_usd()
            print(f"  [ERROR] {baseline} failed: {e}", file=sys.stderr, flush=True)
            print(f"  Traceback (last 10 lines):\n{traceback_tail}", file=sys.stderr, flush=True)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, prev_handler)
        # Query wording changes across v1/v2/v3, but the numeric ID is the
        # stable benchmark identity used to join results, judgments, and GT.
        result.query_id = int(qid)
        results.append(result)

        j = result.judge_verdict.get("verdict", "N/A") if result.judge_verdict else "N/A"
        print(
            f"  -> executed={result.executed} rejected={result.rejected} "
            f"alignment={j} latency={result.latency_s:.1f}s "
            f"tokens={result.input_tokens}in/{result.output_tokens}out "
            f"cost=${result.cost_usd:.4f}",
            flush=True,
        )

        with open(raw_results_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dataclasses.asdict(result), default=_json_serialize) + "\n")

    judge_out_dir = os.path.join(output_dir, "ground_truth_llm_judge")
    rows_for_judge: list[dict] = []
    skipped_judge_count = 0
    for result, row in zip(results, _rows_from_run_results(results)):
        # Out-of-scope guardrail rejections are scored deterministically in metrics.
        if result.rejected and not result.executed:
            skipped_judge_count += 1
            continue
        rows_for_judge.append(row)

    if not rows_for_judge:
        # print(
        #     "  [DEBUG] Skipping LLM judge because no rows are eligible "
        #     f"(skipped {skipped_judge_count} guardrail-rejected rows).",
        #     flush=True,
        # )
        judgments_df = pd.DataFrame()
        sanity_df = pd.DataFrame()
    else:
        # print(
        #     f"  [DEBUG] Ground truth LLM initiates at {time.strftime('%H:%M:%S')} "
        #     f"({len(rows_for_judge)} eligible rows; skipped {skipped_judge_count} guardrail-rejected rows)",
        #     flush=True,
        # )
        judgments_df, _, sanity_df = run_llm_ground_truth_judge(
            rows=rows_for_judge,
            ground_truth_by_id=ground_truth_by_id,
            output_dir=judge_out_dir,
            model_name=model_name,
            api_key=api_key,
            data_path=data_path,
            dataset=dataset,
            max_answer_chars=llm_judge_max_answer_chars,
            max_code_chars=llm_judge_max_code_chars,
        )
        print(f"Ground-truth LLM responses written to {judge_out_dir}")

    metrics_df = aggregate_metrics(
        results,
        llm_judgments_df=judgments_df,
        ground_truth_by_id=ground_truth_by_id,
        query_defs=report_query_defs,
    )

    save_csv(metrics_df, os.path.join(output_dir, "metrics.csv"))
    save_markdown(
        results,
        os.path.join(output_dir, "report.md"),
        metrics_df=metrics_df,
        query_defs=report_query_defs,
    )
    print("\n=== Summary ===")
    print_table(metrics_df)
    _print_flash_fusion_router_summary(metrics_df)
    print(f"\nResults written to {output_dir}")
    return results, judgments_df, metrics_df, sanity_df


def run_benchmark(args: argparse.Namespace) -> list[RunResult]:
    """
    Execute the benchmark for all requested baseline × query combinations.

    Args:
        args: Parsed argparse.Namespace with attributes:
              data, baselines, queries, model, output

    Returns:
        List of RunResult objects (one per baseline × query combination).

    Implementation (see CLAUDE.md §eval/benchmark.py for full algorithm):

        1. Validate OPENROUTER_API_KEY (or fallback GROQ_API_KEY) in environment.
        2. Resolve baselines list from args.baselines ("all" or comma-separated).
        3. Resolve query_ids list from args.queries ("all" or comma-separated ints).
        4. df_base = load_wisdm(args.data)
        5. os.makedirs(args.output, exist_ok=True)
        6. raw_results_path = os.path.join(args.output, "raw_results.jsonl")
        7. results = []

        For each baseline in baselines:
          For each query_id in query_ids:
            query_def = WISDM_QUERIES[query_id - 1]
            query_text = query_def["text"]
            print progress header

            client = LLMClient(model_name=args.model, api_key=api_key)
            runner = BaselineRunner(
                mode=baseline,
                df=df_base.copy(),    # fresh copy per run
                client=client,
            )
            result = runner.run(query_text)
            results.append(result)

            # Print one-line progress summary
            j = result.judge_verdict.get("verdict", "N/A")
            print(f"  → executed={result.executed} rejected={result.rejected} "
                  f"judge={j} latency={result.latency_s:.1f}s cost=${result.cost_usd:.4f}")

            # Append to JSONL
            with open(raw_results_path, "a") as f:
                f.write(json.dumps(dataclasses.asdict(result)) + "\n")

        8. metrics_df = aggregate_metrics(results)
        9. save_csv(metrics_df, os.path.join(args.output, "metrics.csv"))
        10. save_markdown(results, os.path.join(args.output, "report.md"))
        11. print("\n=== Summary ===")
        12. print_table(metrics_df)
        13. print(f"\nResults written to {args.output}")
        14. return results
    """
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")
    primary_is_groq = _is_groq_model(args.model)
    light_is_groq = bool(args.stage12_model) and _is_groq_model(args.stage12_model)
    api_key = groq_key if primary_is_groq else openrouter_key
    light_api_key = groq_key if light_is_groq else openrouter_key
    if not api_key:
        sys.exit(
            "Error: set GROQ_API_KEY for the primary Groq model."
            if primary_is_groq
            else "Error: set OPENROUTER_API_KEY for the primary OpenRouter model."
        )
    if light_is_groq and not light_api_key:
        sys.exit("Error: set GROQ_API_KEY for --stage12-model.")

    # Infer data path from dataset if not provided
    if args.data is None:
        args.data = DEFAULT_DATA_PATHS.get(args.dataset)
        if args.data is None:
            sys.exit(
                f"Error: --data not provided and no default path configured for dataset '{args.dataset}'. "
                f"Please specify --data explicitly."
            )

    if _is_forbidden_chat_data_path(args.data):
        sys.exit(
            "Error: dataset path under chat/data is not allowed. "
            "Use data/AutoIOT_dataset/IMU/ for WISDM, "
            "data/AutoIOT_dataset/ECG.0/ for ECG, and data/bus/ for bus."
        )
    if not _is_under_data_root(args.data):
        sys.exit(
            "Error: dataset path must be under data/. "
            "Use data/AutoIOT_dataset/IMU/, data/AutoIOT_dataset/ECG.0/, or data/bus/."
        )

    # Infer ground truth path from dataset if using default
    if args.ground_truth == "flashfusion/eval/ground_truth/ground_truth_wisdm.json":
        args.ground_truth = DEFAULT_GROUND_TRUTH_PATHS.get(
            args.dataset, args.ground_truth
        )

    try:
        ground_truth_by_id = load_ground_truth(args.ground_truth)
    except FileNotFoundError as e:
        sys.exit(str(e))
    except Exception as e:
        sys.exit(f"Invalid ground truth file: {e}")

    if args.ground_truth_measurement != "llm":
        sys.exit(
            "Error: --ground-truth-measurement must be 'llm'. Semantic scoring "
            "is no longer supported."
        )

    if args.baselines == "all":
        baselines = list(ALL_BASELINES)
    else:
        baselines = [b.strip().upper() for b in args.baselines.split(",") if b.strip()]
    for b in baselines:
        if b not in ALL_BASELINES:
            sys.exit(f"Error: unknown baseline {b!r}. Options: {ALL_BASELINES}")
    if args.semantic_cache_path is None and "FLASH_FUSION_CACHE" in baselines:
        args.semantic_cache_path = SEMANTIC_CACHE_REGISTRY_PATHS[args.dataset]

    query_defs = get_queries(args.dataset)

    if args.queries == "all":
        query_ids = [q["id"] for q in query_defs]
    else:
        query_ids = [int(x.strip()) for x in args.queries.split(",") if x.strip()]
    valid_ids = {q["id"] for q in query_defs}
    for qid in query_ids:
        if qid not in valid_ids:
            sys.exit(f"Error: unknown query id {qid}. Valid: {sorted(valid_ids)}")

    if args.runs < 1:
        sys.exit("Error: --runs must be >= 1")

    print(f"[DEBUG] Loading dataset from {args.data!r} with dataset={args.dataset!r} …", flush=True)
    _t_load = time.time()
    df_base = load_dataset_by_name(args.data, args.dataset)
    print(f"[DEBUG] Dataset loaded in {time.time()-_t_load:.2f}s  shape={df_base.shape}  len={len(df_base)}", flush=True)
    print(f"[DEBUG] df_base columns: {list(df_base.columns)}", flush=True)
    if len(df_base) > 0:
        print(f"[DEBUG] df_base.head(3):\n{df_base.head(3)}", flush=True)
    else:
        print(f"[DEBUG] WARNING: df_base is EMPTY after loading!", flush=True)
    os.makedirs(args.output, exist_ok=True)
    if args.runs == 1:
        if args.prompt_cache_warmup:
            _prewarm_provider_prompt_caches(
                baselines=baselines,
                query_defs=query_defs,
                query_ids=query_ids,
                df=df_base,
                model_name=args.model,
                api_key=api_key,
                stage12_model=args.stage12_model,
                light_api_key=light_api_key,
                dataset=args.dataset,
                cache_path=getattr(args, "cache_path", None),
            )
        cache_order_ids, cache_order_seed = _cache_query_order_for_run(
            query_ids=query_ids,
            run_id=1,
            randomize=bool(args.cache_random_order),
            base_seed=int(args.cache_order_base_seed),
        )
        single_defs_by_baseline, single_ids_by_baseline = _per_baseline_overrides(
            baselines=baselines,
            rewording_mode=args.query_rewording,
            cache_query_defs=query_defs,
            cache_order_ids=cache_order_ids,
        )
        if single_ids_by_baseline:
            order_manifest = {
                "randomized": bool(args.cache_random_order),
                "seed": cache_order_seed,
                "query_order": cache_order_ids,
                "applies_to": sorted(single_ids_by_baseline),
            }
            with open(os.path.join(args.output, "flash_fusion_cache_query_order.json"), "w", encoding="utf-8") as fh:
                json.dump(order_manifest, fh, indent=2)

        results, _, _, _ = _run_single_benchmark_iteration(
            baselines=baselines,
            query_ids=query_ids,
            query_ids_by_baseline=single_ids_by_baseline,
            df_base=df_base,
            output_dir=args.output,
            model_name=args.model,
            api_key=api_key,
            ground_truth_by_id=ground_truth_by_id,
            data_path=args.data,
            dataset=args.dataset,
            query_defs=query_defs,
            max_query_latency=args.max_query_latency,
            llm_judge_max_answer_chars=args.llm_judge_max_answer_chars,
            llm_judge_max_code_chars=args.llm_judge_max_code_chars,
            stage12_model=args.stage12_model,
            light_api_key=light_api_key,
            cache_path=getattr(args, "cache_path", None),
            semantic_cache_path=getattr(args, "semantic_cache_path", None),
            prewarm_cache_runtime=bool(args.cache_prewarm_hybrid),
            interleave_policies=bool(args.interleave_policies),
        )
        _write_cache_grounding_issues(
            args.output, os.path.join(args.output, "raw_results.jsonl")
        )
        return results

    all_results: list[RunResult] = []
    all_metrics: list[pd.DataFrame] = []
    all_judgments: list[pd.DataFrame] = []
    baseline_per_run: list[pd.DataFrame] = []
    first_sanity_df: pd.DataFrame | None = None

    for run_id in range(1, args.runs + 1):
        run_output_dir = os.path.join(args.output, f"run_{run_id}")
        print(f"\n##### Run {run_id}/{args.runs} -> {run_output_dir} #####", flush=True)
        if args.prompt_cache_warmup:
            _prewarm_provider_prompt_caches(
                baselines=baselines,
                query_defs=query_defs,
                query_ids=query_ids,
                df=df_base,
                model_name=args.model,
                api_key=api_key,
                stage12_model=args.stage12_model,
                light_api_key=light_api_key,
                dataset=args.dataset,
                cache_path=getattr(args, "cache_path", None),
            )
        cache_query_version, cache_query_defs = _cache_queries_for_run(args.dataset, run_id)
        cache_order_ids, cache_order_seed = _cache_query_order_for_run(
            query_ids=query_ids,
            run_id=run_id,
            randomize=bool(args.cache_random_order),
            base_seed=int(args.cache_order_base_seed),
        )
        query_defs_by_baseline, query_ids_by_baseline = _per_baseline_overrides(
            baselines=baselines,
            rewording_mode=args.query_rewording,
            cache_query_defs=cache_query_defs,
            cache_order_ids=cache_order_ids,
        )
        if query_ids_by_baseline:
            print(
                f"[FLASH_FUSION_CACHE] Query version for run {run_id}: "
                f"{cache_query_version}; semantic registry: {args.semantic_cache_path}; "
                f"random_seed={cache_order_seed}; query_order={cache_order_ids}",
                flush=True,
            )
            os.makedirs(run_output_dir, exist_ok=True)
            order_manifest = {
                "run_id": run_id,
                "randomized": bool(args.cache_random_order),
                "seed": cache_order_seed,
                "query_order": cache_order_ids,
                "query_version": cache_query_version,
            }
            with open(
                os.path.join(run_output_dir, "flash_fusion_cache_query_order.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                json.dump(order_manifest, fh, indent=2)
        run_results, run_judgments, run_metrics, run_sanity = _run_single_benchmark_iteration(
            baselines=baselines,
            query_ids=query_ids,
            query_ids_by_baseline=query_ids_by_baseline,
            df_base=df_base,
            output_dir=run_output_dir,
            model_name=args.model,
            api_key=api_key,
            ground_truth_by_id=ground_truth_by_id,
            data_path=args.data,
            dataset=args.dataset,
            query_defs=query_defs,
            query_defs_by_baseline=query_defs_by_baseline,
            max_query_latency=args.max_query_latency,
            llm_judge_max_answer_chars=args.llm_judge_max_answer_chars,
            llm_judge_max_code_chars=args.llm_judge_max_code_chars,
            stage12_model=args.stage12_model,
            light_api_key=light_api_key,
            cache_path=getattr(args, "cache_path", None),
            semantic_cache_path=getattr(args, "semantic_cache_path", None),
            prewarm_cache_runtime=bool(args.cache_prewarm_hybrid),
            interleave_policies=bool(args.interleave_policies),
        )

        all_results.extend(run_results)
        if first_sanity_df is None:
            first_sanity_df = run_sanity

        run_metrics = run_metrics.copy()
        run_metrics.insert(0, "run_id", run_id)
        all_metrics.append(run_metrics)

        run_judgments = run_judgments.copy()
        run_judgments.insert(0, "run_id", run_id)
        all_judgments.append(run_judgments)

        run_summary = _baseline_summary(run_metrics)
        run_summary.insert(0, "run_id", run_id)
        baseline_per_run.append(run_summary)

    combined_metrics_df = pd.concat(all_metrics, ignore_index=True)
    save_csv(combined_metrics_df, os.path.join(args.output, "metrics.csv"))

    top_raw_results_path = os.path.join(args.output, "raw_results.jsonl")
    with open(top_raw_results_path, "w", encoding="utf-8") as f:
        for run_id in range(1, args.runs + 1):
            run_dir = os.path.join(args.output, f"run_{run_id}")
            run_raw_path = os.path.join(run_dir, "raw_results.jsonl")
            if not os.path.exists(run_raw_path):
                continue
            with open(run_raw_path, "r", encoding="utf-8") as rf:
                for line in rf:
                    line = line.strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    payload["run_id"] = run_id
                    f.write(json.dumps(payload, default=_json_serialize) + "\n")

    judge_out_dir = os.path.join(args.output, "ground_truth_llm_judge")
    os.makedirs(judge_out_dir, exist_ok=True)
    combined_judgments_df = pd.concat(all_judgments, ignore_index=True)
    combined_judgments_df.to_csv(
        os.path.join(judge_out_dir, "llm_judgments.csv"), index=False
    )
    with open(os.path.join(judge_out_dir, "llm_judgments.jsonl"), "w", encoding="utf-8") as fh:
        for row in combined_judgments_df.to_dict(orient="records"):
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
    summarize_judgments(combined_judgments_df).to_csv(
        os.path.join(judge_out_dir, "llm_judgments_summary.csv"),
        index=False,
    )
    if first_sanity_df is None:
        first_sanity_df = pd.DataFrame()
    first_sanity_df.to_csv(os.path.join(judge_out_dir, "ground_truth_sanity.csv"), index=False)

    baseline_per_run_df = pd.concat(baseline_per_run, ignore_index=True)
    save_csv(baseline_per_run_df, os.path.join(args.output, "baseline_summary_per_run.csv"))

    metric_cols = [
        c
        for c in ["gt_score", "latency_s", "cost_usd", "input_tokens", "output_tokens"]
        if c in baseline_per_run_df.columns
    ]
    baseline_avg_df = (
        baseline_per_run_df.groupby("baseline", as_index=False)[metric_cols]
        .mean()
        .sort_values("baseline")
        .reset_index(drop=True)
    )
    baseline_avg_df["runs"] = args.runs
    save_csv(baseline_avg_df, os.path.join(args.output, "metrics_baseline_avg.csv"))

    save_markdown(
        all_results,
        os.path.join(args.output, "report.md"),
        metrics_df=combined_metrics_df,
        query_defs=query_defs,
    )
    save_markdown([], os.path.join(args.output, "report_avg.md"), metrics_df=baseline_avg_df)

    _write_cache_grounding_issues(args.output, top_raw_results_path)

    print("\n=== Combined Summary (all per-query rows across runs) ===")
    print_table(combined_metrics_df)
    print("\n=== Baseline Average Summary (across runs) ===")
    print_table(baseline_avg_df)
    print(f"\nResults written to {args.output}")
    return all_results


def _build_parser() -> argparse.ArgumentParser:
    """
    Build and return the argparse parser for the benchmark CLI.

    Arguments:
        --data       (required) Path to WISDM_ar_v1.1_raw.txt
        --baselines  (default "REACT_ONLY,FLASH_FUSION") "all" or comma-separated baseline names
        --queries    (default "all") "all" or comma-separated 1-indexed query IDs
        --model      (default config.DEFAULT_MODEL) provider model identifier
        --output     (default "flashfusion/eval_results/") Output directory path
    """
    parser = argparse.ArgumentParser(
        description=(
            "Flash-Fusion Benchmark — evaluate default Agent-Only vs Flash-Fusion "
            "(or any selected baselines) across query sets "
            "measuring accuracy, latency, and token cost."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m flashfusion.eval.benchmark --data data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt "
            "--baselines REACT_ONLY,FLASH_FUSION --queries 1,5,9,12\n"
            "  python -m flashfusion.eval.benchmark --data ... --baselines all"
        ),
    )
    parser.add_argument(
        "--data",
        default=None,
        help=(
            "Path to dataset file (relative to repo root or absolute). "
            "If omitted, uses default path for --dataset."
        ),
    )
    parser.add_argument(
        "--dataset",
        default=DATASET_WISDM,
        choices=list(SUPPORTED_DATASETS),
        help="Dataset profile for loading and query-bank selection",
    )
    parser.add_argument(
        "--baselines",
        default=PRIMARY_ABLATION_BASELINES,
        help=(
            'Comma-separated baseline names or "all". '
            "Default is the primary component-ablation set. "
            f"Options: {', '.join(ALL_BASELINES)}. "
            "Diagnostics: "
            + ", ".join(n for n in POLICIES if n not in PRIMARY_POLICY_SET)
            + ". Legacy aliases: "
            + ", ".join(f"{k}->{v}" for k, v in LEGACY_POLICY_ALIASES.items())
        ),
    )
    parser.add_argument(
        "--interleave-policies",
        action="store_true",
        help=(
            "Run every baseline on one query before advancing to the next, "
            "rotating arm order per query. Shares provider-load drift across "
            "arms instead of letting one arm absorb it. Requires all arms in "
            "one invocation."
        ),
    )
    parser.add_argument(
        "--query-rewording",
        choices=("auto", "paired", "cache-only"),
        default="auto",
        help=(
            "Who receives the per-run reworded query bank (v1/v2/v3) and the "
            "shuffled order. 'paired' gives nobody rewording so every arm sees "
            "identical queries in identical order; 'cache-only' is the legacy "
            "behaviour; 'auto' (default) uses 'paired' whenever a cache arm "
            "and a no-cache arm are both present, else 'cache-only'."
        ),
    )
    parser.add_argument(
        "--queries",
        default="all",
        help='Comma-separated 1-indexed query IDs or "all". E.g. "1,5,9,12"',
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model identifier (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--stage12-model",
        default=DEFAULT_LIGHT_MODEL,
        help=(
            "Optional lighter model for Flash-Fusion Stages 1 and 2 and for "
            "FLASH_FUSION_CACHE light-model grounding (default: OpenRouter "
            f"{DEFAULT_LIGHT_MODEL}). All other stages use --model. "
            "When omitted, every stage uses --model."
        ),
    )
    parser.add_argument(
        "--cache-path",
        default=None,
        help=(
            "Operator-skeleton cache registry for FLASH_FUSION_CACHE "
            "(default: flashfusion/eval/cache/cache_registry.json)"
        ),
    )
    parser.add_argument(
        "--semantic-cache-path",
        default=None,
        help=(
            "Semantic template registry for FLASH_FUSION_CACHE. Defaults to the "
            "checked-in v1 registry for --dataset."
        ),
    )
    parser.add_argument(
        "--output",
        default="flashfusion/eval_results/",
        help="Output directory for metrics.csv, report.md, raw_results.jsonl",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of repeated benchmark runs to execute (default: 1)",
    )
    parser.add_argument(
        "--cache-random-order",
        dest="cache_random_order",
        action="store_true",
        default=True,
        help=(
            "Randomize FLASH_FUSION_CACHE query order per run with reproducible seeds "
            "(default: enabled)."
        ),
    )
    parser.add_argument(
        "--no-cache-random-order",
        dest="cache_random_order",
        action="store_false",
        help="Disable randomized FLASH_FUSION_CACHE query order and preserve explicit query order.",
    )
    parser.add_argument(
        "--cache-order-base-seed",
        type=int,
        default=20260821,
        help=(
            "Base seed for FLASH_FUSION_CACHE query-order randomization; "
            "effective seed per run is base_seed + run_id - 1."
        ),
    )
    parser.add_argument(
        "--cache-prewarm-hybrid",
        dest="cache_prewarm_hybrid",
        action="store_true",
        default=True,
        help=(
            "Prewarm FLASH_FUSION_CACHE hybrid runtime before timed queries so model load/warm-up "
            "are not charged to per-query latency (default: enabled)."
        ),
    )
    parser.add_argument(
        "--no-cache-prewarm-hybrid",
        dest="cache_prewarm_hybrid",
        action="store_false",
        help="Disable FLASH_FUSION_CACHE benchmark prewarm of the hybrid matcher runtime.",
    )
    parser.add_argument(
        "--prompt-cache-warmup",
        dest="prompt_cache_warmup",
        action="store_true",
        default=True,
        help=(
            "Populate provider prompt caches for static Flash-Fusion and cache-grounding "
            "system prompts before each benchmark run (default: enabled)."
        ),
    )
    parser.add_argument(
        "--no-prompt-cache-warmup",
        dest="prompt_cache_warmup",
        action="store_false",
        help="Disable provider prompt-cache setup requests before benchmark runs.",
    )
    parser.add_argument(
        "--ground-truth",
        default="flashfusion/eval/ground_truth/ground_truth_wisdm.json",
        help="Path to ground truth JSON file (required to score answers)",
    )
    parser.add_argument(
        "--max-query-latency",
        type=float,
        default=600.0,
        help="Per-query latency budget in seconds; timed-out queries are skipped",
    )
    parser.add_argument(
        "--ground-truth-measurement",
        default="llm",
        choices=["llm"],
        help=(
            "Ground-truth scoring mode. gt_score is LLM-verdict-based only."
        ),
    )
    parser.add_argument(
        "--llm-judge-max-answer-chars",
        type=int,
        default=1800,
        help="Max answer chars passed to LLM judge",
    )
    parser.add_argument(
        "--llm-judge-max-code-chars",
        type=int,
        default=1400,
        help="Max generated-code chars passed to LLM judge",
    )
    return parser


def main() -> None:
    """Parse arguments and run the benchmark."""
    parser = _build_parser()
    args = parser.parse_args()
    run_benchmark(args)


if __name__ == "__main__":
    main()
