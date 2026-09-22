from __future__ import annotations

"""
benchmark_grounding.py

Benchmark cache-grounding stability in FLASH_FUSION_CACHE across light models.

PLAN (grounding_loss_vs_model_size expansion):
1. Densify the 3-7B range and drop the noisy qwen-2.5-7b-instruct point:
   swap qwen/qwen-2.5-7b-instruct -> qwen/qwen3-4b, qwen/qwen3-8b.
   Add google/gemma-3-4b-it, meta-llama/llama-3.1-8b-instruct, and
   microsoft/phi-4 to bring the model count to 10; all three ids were
   verified live against https://openrouter.ai/api/v1/models on 2026-09-22
   (mistralai/mistral-7b-instruct and its v0.3/:free variants 404 and were
   excluded). Every id's params_b falls within the existing MODEL_SIZE_META
   1-14B range.
2. Broaden scope from ids 1-8 (direct, intermediate) to the full ids 1-20
   (direct, intermediate, out_of_scope, predictive, extra_hard) so every
   query id is exercised across v1-v3 for bus, wisdm, and mit_ecg.
3. Re-run the CLI commands below for all three datasets, then regenerate
   MODEL_SIZE_META entries, flashfusion/config.py pricing for the new
   models, and the GROUNDING_MODELS tuple in flashfusion/viz/primary_visualizations.py.
4. Regenerate results/primary_visualizations/baselines/grounding_loss_vs_model_size.{csv,png,pdf}
   via `python -m flashfusion.viz.primary_visualizations`.

End-to-end run command example (single dataset, full ids 1-20 x v1-v3):

BUS:
python -m flashfusion.eval.benchmark_grounding \
    --dataset bus \
    --model ibm-granite/granite-4.2-8b \
    --models meta-llama/llama-3.2-1b-instruct,meta-llama/llama-3.2-3b-instruct,google/gemma-3-4b-it,qwen/qwen3-4b,qwen/qwen3-8b,meta-llama/llama-3.1-8b-instruct,ibm-granite/granite-4.2-8b,google/gemma-3-12b-it,microsoft/phi-4,qwen/qwen3-14b \
    --runs 3 \
    --query-versions v1,v2,v3 \
    --output-dir flashfusion/results/ff_hybrid_cache/grounding_benchmark/bus \
    --reuse-existing-granite-results \
    --existing-granite-root flashfusion/results/ff_hybrid_cache/FLASH_FUSION_CACHE \
    --save-traces \
    --emit-typed-plan-ground-truth-json flashfusion/results/ff_hybrid_cache/grounding_benchmark/typed_plan_ground_truth.json \
    --typed-plan-ground-truth-root flashfusion/results/ff_hybrid_cache/grounding_benchmark \
    --typed-plan-ground-truth-json flashfusion/results/ff_hybrid_cache/grounding_benchmark/typed_plan_ground_truth.json

WISDM:
python -m flashfusion.eval.benchmark_grounding \
    --dataset wisdm \
    --model ibm-granite/granite-4.2-8b \
    --models meta-llama/llama-3.2-1b-instruct,meta-llama/llama-3.2-3b-instruct,google/gemma-3-4b-it,qwen/qwen3-4b,qwen/qwen3-8b,meta-llama/llama-3.1-8b-instruct,ibm-granite/granite-4.2-8b,google/gemma-3-12b-it,microsoft/phi-4,qwen/qwen3-14b \
    --runs 3 \
    --query-versions v1,v2,v3 \
    --output-dir flashfusion/results/ff_hybrid_cache/grounding_benchmark/wisdm \
    --reuse-existing-granite-results \
    --existing-granite-root flashfusion/results/ff_hybrid_cache/FLASH_FUSION_CACHE \
    --save-traces \
    --emit-typed-plan-ground-truth-json flashfusion/results/ff_hybrid_cache/grounding_benchmark/typed_plan_ground_truth.json \
    --typed-plan-ground-truth-root flashfusion/results/ff_hybrid_cache/grounding_benchmark \
    --typed-plan-ground-truth-json flashfusion/results/ff_hybrid_cache/grounding_benchmark/typed_plan_ground_truth.json

ECG:
python -m flashfusion.eval.benchmark_grounding \
    --dataset mit_ecg \
    --model ibm-granite/granite-4.2-8b \
    --models meta-llama/llama-3.2-1b-instruct,meta-llama/llama-3.2-3b-instruct,google/gemma-3-4b-it,qwen/qwen3-4b,qwen/qwen3-8b,meta-llama/llama-3.1-8b-instruct,ibm-granite/granite-4.2-8b,google/gemma-3-12b-it,microsoft/phi-4,qwen/qwen3-14b \
    --runs 3 \
    --query-versions v1,v2,v3 \
    --output-dir flashfusion/results/ff_hybrid_cache/grounding_benchmark/mit_ecg \
    --reuse-existing-granite-results \
    --existing-granite-root flashfusion/results/ff_hybrid_cache/FLASH_FUSION_CACHE \
    --save-traces \
    --emit-typed-plan-ground-truth-json flashfusion/results/ff_hybrid_cache/grounding_benchmark/typed_plan_ground_truth.json \
    --typed-plan-ground-truth-root flashfusion/results/ff_hybrid_cache/grounding_benchmark \
    --typed-plan-ground-truth-json flashfusion/results/ff_hybrid_cache/grounding_benchmark/typed_plan_ground_truth.json


Primary metric:
    grounding_loss_pct = 100 * failures / total_in_scope

Where a failure is any run whose stages include:
    "cache_miss_or_validation_failure"
"""

import argparse
import csv
import json
import math
import os
import signal
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flashfusion.config import DEFAULT_MODEL
from flashfusion.eval.benchmark import DEFAULT_DATA_PATHS
from flashfusion.eval import queries as queries_v1
from flashfusion.eval import queries_v2, queries_v3
from flashfusion.pipeline.loader import load_dataset_by_name
from flashfusion.pipeline.runner import BaselineRunner, LLMClient, RunResult, _is_groq_model


DEFAULT_STAGE12_MODELS = [
    "meta-llama/llama-3.2-1b-instruct",
    "meta-llama/llama-3.2-3b-instruct",
    "google/gemma-3-4b-it",
    "qwen/qwen3-4b",
    "qwen/qwen3-8b",
    "meta-llama/llama-3.1-8b-instruct",
    "ibm-granite/granite-4.2-8b",
    "google/gemma-3-12b-it",
    "microsoft/phi-4",
    "qwen/qwen3-14b",
]

MODEL_SIZE_META = {
    "meta-llama/llama-3.2-1b-instruct": {"label": "1b", "params_b": 1.0},
    "meta-llama/llama-3.2-3b-instruct": {"label": "3b", "params_b": 3.0},
    "google/gemma-3-4b-it": {"label": "4b", "params_b": 4.0},
    "qwen/qwen3-4b": {"label": "4b", "params_b": 4.0},
    "qwen/qwen3-8b": {"label": "8b", "params_b": 8.0},
    "meta-llama/llama-3.1-8b-instruct": {"label": "8b", "params_b": 8.0},
    "ibm-granite/granite-4.2-8b": {"label": "8b", "params_b": 8.0},
    "google/gemma-3-12b-it": {"label": "12b", "params_b": 12.0},
    "microsoft/phi-4": {"label": "14b", "params_b": 14.0},
    "qwen/qwen3-14b": {"label": "14b", "params_b": 14.0},
}

SUPPORTED_QUERY_VERSIONS = ("v1", "v2", "v3")
# Covers query ids 1-20 (direct, intermediate, out_of_scope, predictive, extra_hard).
INSCOPE_COMPLEXITIES = {"direct", "intermediate", "out_of_scope", "predictive", "extra_hard"}
FALLBACK_STAGE = "cache_miss_or_validation_failure"
ALL_DATASETS = ("bus", "wisdm", "mit_ecg")
GROUNDING_ATTEMPT_TIMEOUT_S = 15.0
GROUNDING_RATE_LIMIT_MAX_ATTEMPTS = 3
GROUNDING_RATE_LIMIT_BACKOFF_BASE_S = 2.0


class GroundingAttemptTimeoutError(TimeoutError):
    """Raised when one benchmark grounding attempt exceeds its time budget."""


def _parse_csv_arg(value: str | None, default: list[str]) -> list[str]:
    if value is None or not value.strip():
        return list(default)
    return [x.strip() for x in value.split(",") if x.strip()]


def _get_queries(dataset: str, version: str) -> list[dict[str, Any]]:
    if version == "v1":
        return queries_v1.get_queries(dataset)
    if version == "v2":
        return queries_v2.get_queries(dataset)
    if version == "v3":
        return queries_v3.get_queries(dataset)
    raise ValueError(f"Unsupported query version: {version!r}")


def _inscope_query_defs(dataset: str, version: str) -> dict[int, dict[str, Any]]:
    defs = _get_queries(dataset, version)
    return {
        int(q["id"]): q
        for q in defs
        if str(q.get("complexity", "")).strip().lower() in INSCOPE_COMPLEXITIES
    }


def _is_forbidden_chat_data_path(path: str) -> bool:
    normalized = os.path.normpath(path).replace("\\", "/")
    return normalized == "chat/data" or normalized.startswith("chat/data/") or "/chat/data/" in normalized


def _is_under_data_root(path: str) -> bool:
    normalized = os.path.normpath(path).replace("\\", "/")
    return normalized.startswith("data/") or "/data/" in normalized


def _validate_data_path(path: str) -> None:
    if _is_forbidden_chat_data_path(path):
        raise ValueError(f"Invalid data path (forbidden chat/data): {path}")
    if not _is_under_data_root(path):
        raise ValueError(f"Invalid data path (must be under data/): {path}")


def _resolve_api_keys(primary_model: str, light_model: str) -> tuple[str, str]:
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")

    primary_is_groq = _is_groq_model(primary_model)
    light_is_groq = _is_groq_model(light_model)

    primary_key = groq_key if primary_is_groq else openrouter_key
    light_key = groq_key if light_is_groq else openrouter_key

    if not primary_key:
        env_name = "GROQ_API_KEY" if primary_is_groq else "OPENROUTER_API_KEY"
        raise SystemExit(f"Missing required API key for primary model: set {env_name}")
    if not light_key:
        env_name = "GROQ_API_KEY" if light_is_groq else "OPENROUTER_API_KEY"
        raise SystemExit(f"Missing required API key for light model: set {env_name}")
    return primary_key, light_key


def _is_rate_limited_error(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 429 or type(exc).__name__ == "TooManyRequestsResponseError"


def _rate_limit_retry_delay_s(exc: Exception, attempt: int) -> float:
    headers = getattr(exc, "headers", None)
    retry_after = headers.get("retry-after") if headers is not None else None
    try:
        if retry_after is not None:
            return min(max(float(retry_after), 0.0), 30.0)
    except (TypeError, ValueError):
        pass
    return min(GROUNDING_RATE_LIMIT_BACKOFF_BASE_S * (2**attempt), 30.0)


def _record_from_result(
    *,
    result: RunResult,
    dataset: str,
    query_version: str,
    run_index: int,
    stage12_model: str,
    planner_model: str,
    query_id: int,
    complexity: str,
    source: str,
    cache_grounding_failure: dict[str, Any] | None = None,
    typed_plan_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stages = list(result.stages_run or [])
    stage_latency = dict(result.stage_latency_s or {})
    fallback_reason = str(result.deterministic_fallback_reason or "").strip()
    failed = FALLBACK_STAGE in stages
    typed_plan_payload = typed_plan_payload if isinstance(typed_plan_payload, dict) else dict(result.typed_plan or {})
    typed_plan_signature = ""
    if typed_plan_payload:
        typed_plan_signature = json.dumps(typed_plan_payload, sort_keys=True, ensure_ascii=True)
    failure_stage_excerpt = ""
    if failed:
        failure_stage_excerpt = fallback_reason or "cache_miss_or_validation_failure"
    return {
        "dataset": dataset,
        "query_id": int(query_id),
        "query_version": query_version,
        "complexity": complexity,
        "run_index": int(run_index),
        "stage12_model": stage12_model,
        "planner_model": planner_model,
        "execution_path": str(result.execution_path or ""),
        "plan_source": str(result.plan_source or ""),
        "stages_run": stages,
        "failure_for_grounding_loss": bool(failed),
        "deterministic_fallback_reason": fallback_reason,
        "cache_grounding_latency_s": float(stage_latency.get("cache_grounding", 0.0) or 0.0),
        "cache_lookup_latency_s": float(stage_latency.get("cache_lookup", 0.0) or 0.0),
        "cache_validation_latency_s": float(stage_latency.get("cache_validation", 0.0) or 0.0),
        "typed_exec_latency_s": float(stage_latency.get("typed_exec", 0.0) or 0.0),
        "total_latency_s": float(result.latency_s or 0.0),
        "run_source": source,
        "cache_grounding_failure": cache_grounding_failure or dict(result.cache_grounding_failure or {}),
        "typed_plan_signature": typed_plan_signature,
        "failure_stage_excerpt": failure_stage_excerpt,
    }


def _failed_grounding_attempt_result(
    *,
    query: str,
    planner_model: str,
    elapsed_s: float,
    reason: str,
    exception_type: str,
) -> RunResult:
    result = RunResult(
        baseline="FLASH_FUSION_CACHE",
        model=planner_model,
        query=query,
        answer=f"[FAILED_GROUNDING_ATTEMPT] {reason}",
        rejected=False,
        executed=False,
    )
    result.execution_path = "grounding_attempt_failed"
    result.plan_source = "benchmark_failed_grounding_attempt"
    result.deterministic_fallback_reason = f"cache: {reason}"
    result.stages_run = [FALLBACK_STAGE, "grounding_attempt_failed"]
    result.latency_s = elapsed_s
    result.cache_grounding_failure = {
        "failure_reason": reason,
        "exception_type": exception_type,
        "elapsed_s": elapsed_s,
    }
    return result


def _safe_jsonl_load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _safe_json_load(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected JSON list in {path}")
    return payload


def _parse_typed_plan_signature(signature: str) -> dict[str, Any] | None:
    sig = str(signature or "").strip()
    if not sig:
        return None
    try:
        parsed = json.loads(sig)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _build_typed_plan_ground_truth_from_root(root: Path) -> dict[str, Any]:
    # dataset -> query_id -> version -> signature evidence
    accumulator: dict[str, dict[int, dict[str, dict[str, dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict))
    )

    for dataset in ALL_DATASETS:
        traces_path = root / dataset / "grounding_benchmark_traces.json"
        if not traces_path.exists():
            continue
        rows = _safe_json_load(traces_path)
        for row in rows:
            if not isinstance(row, dict):
                continue
            qid = row.get("query_id")
            qv = str(row.get("query_version", "")).strip().lower()
            sig = str(row.get("typed_plan_signature", "")).strip()
            if not isinstance(qid, int) or qv not in SUPPORTED_QUERY_VERSIONS or not sig:
                continue

            bucket = accumulator[dataset][qid][qv]
            info = bucket.get(sig)
            if info is None:
                info = {
                    "count": 0,
                    "failure_count": 0,
                }
                bucket[sig] = info
            info["count"] += 1
            if bool(row.get("failure_for_grounding_loss")):
                info["failure_count"] += 1

    datasets_payload: dict[str, Any] = {}
    flat_index: dict[str, str] = {}

    for dataset in ALL_DATASETS:
        query_map = accumulator.get(dataset, {})
        queries_payload: dict[str, Any] = {}
        for query_id in sorted(query_map):
            versions = query_map[query_id]
            by_version: dict[str, Any] = {}
            all_sig_counts: Counter[str] = Counter()

            for version in SUPPORTED_QUERY_VERSIONS:
                sig_bucket = versions.get(version, {})
                if not sig_bucket:
                    continue
                # choose most frequent signature for this (dataset,query_id,version)
                chosen_sig, chosen_info = max(
                    sig_bucket.items(),
                    key=lambda kv: (int(kv[1].get("count", 0)), -int(kv[1].get("failure_count", 0))),
                )
                chosen_plan = _parse_typed_plan_signature(chosen_sig)
                by_version[version] = {
                    "typed_plan_signature": chosen_sig,
                    "typed_plan": chosen_plan,
                    "support_count": int(chosen_info.get("count", 0)),
                    "failure_support_count": int(chosen_info.get("failure_count", 0)),
                    "candidate_signature_count": len(sig_bucket),
                }
                all_sig_counts[chosen_sig] += int(chosen_info.get("count", 0))
                flat_index[f"{dataset}|{query_id}|{version}"] = chosen_sig

            canonical_sig = ""
            canonical_plan = None
            if all_sig_counts:
                canonical_sig = all_sig_counts.most_common(1)[0][0]
                canonical_plan = _parse_typed_plan_signature(canonical_sig)

            queries_payload[str(query_id)] = {
                "by_version": by_version,
                "canonical_typed_plan_signature": canonical_sig,
                "canonical_typed_plan": canonical_plan,
            }

        datasets_payload[dataset] = {
            "queries": queries_payload,
        }

    return {
        "name": "ff_cache_typed_plan_ground_truth",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root),
        "datasets": datasets_payload,
        "flat_index": flat_index,
    }


def _load_typed_plan_ground_truth(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Ground-truth file must be a JSON object: {path}")
    return payload


def _lookup_ground_truth_signature(
    gt: dict[str, Any],
    *,
    dataset: str,
    query_id: int,
    query_version: str,
) -> tuple[str, str]:
    datasets = gt.get("datasets") if isinstance(gt, dict) else None
    if not isinstance(datasets, dict):
        return "", ""
    ds = datasets.get(dataset)
    if not isinstance(ds, dict):
        return "", ""
    queries = ds.get("queries")
    if not isinstance(queries, dict):
        return "", ""
    q = queries.get(str(query_id))
    if not isinstance(q, dict):
        return "", ""

    by_version = q.get("by_version")
    if isinstance(by_version, dict):
        ver = by_version.get(query_version)
        if isinstance(ver, dict):
            sig = str(ver.get("typed_plan_signature", "")).strip()
            if sig:
                return sig, "dataset_query_version"

    sig = str(q.get("canonical_typed_plan_signature", "")).strip()
    if sig:
        return sig, "dataset_query_canonical"
    return "", ""


def _attach_ground_truth_to_rows(rows: list[dict[str, Any]], gt: dict[str, Any]) -> list[dict[str, Any]]:
    patched: list[dict[str, Any]] = []
    for row in rows:
        entry = dict(row)
        dataset = str(entry.get("dataset", ""))
        query_version = str(entry.get("query_version", "")).strip().lower()
        query_id_raw = entry.get("query_id")
        query_id = int(query_id_raw) if isinstance(query_id_raw, int) else None
        gt_sig = ""
        gt_source = ""
        if query_id is not None and dataset and query_version:
            gt_sig, gt_source = _lookup_ground_truth_signature(
                gt,
                dataset=dataset,
                query_id=query_id,
                query_version=query_version,
            )

        current_sig = str(entry.get("typed_plan_signature", "")).strip()
        imputed = False
        if not current_sig and gt_sig:
            entry["typed_plan_signature"] = gt_sig
            current_sig = gt_sig
            imputed = True

        entry["ground_truth_typed_plan_signature"] = gt_sig
        entry["ground_truth_signature_source"] = gt_source
        entry["typed_plan_signature_imputed"] = imputed
        if gt_sig:
            entry["typed_plan_signature_matches_ground_truth"] = current_sig == gt_sig
        else:
            entry["typed_plan_signature_matches_ground_truth"] = None
        patched.append(entry)
    return patched


def _load_existing_granite_rows(
    *,
    dataset: str,
    granite_model: str,
    planner_model: str,
    existing_root: Path,
    runs: int,
) -> list[dict[str, Any]]:
    base = existing_root / dataset
    if not base.exists():
        return []

    loaded: list[dict[str, Any]] = []
    for run_index in range(1, runs + 1):
        run_dir = base / f"run_{run_index}"
        order_path = run_dir / "flash_fusion_cache_query_order.json"
        raw_path = run_dir / "raw_results.jsonl"
        if not order_path.exists() or not raw_path.exists():
            continue

        order_payload = json.loads(order_path.read_text(encoding="utf-8"))
        query_version = str(order_payload.get("query_version", "")).strip().lower()
        if query_version not in SUPPORTED_QUERY_VERSIONS:
            continue

        inscope = _inscope_query_defs(dataset, query_version)
        for payload in _safe_jsonl_load(raw_path):
            qid = payload.get("query_id")
            if not isinstance(qid, int):
                continue
            query_def = inscope.get(int(qid))
            if query_def is None:
                continue

            rr = RunResult(
                baseline=str(payload.get("baseline", "FLASH_FUSION_CACHE")),
                model=str(payload.get("model", planner_model)),
                query=str(payload.get("query", "")),
            )
            rr.stages_run = list(payload.get("stages_run") or [])
            rr.plan_source = str(payload.get("plan_source", ""))
            rr.execution_path = str(payload.get("execution_path", ""))
            rr.deterministic_fallback_reason = str(payload.get("deterministic_fallback_reason", ""))
            rr.stage_latency_s = dict(payload.get("stage_latency_s") or {})
            rr.latency_s = float(payload.get("latency_s") or 0.0)

            row = _record_from_result(
                result=rr,
                dataset=dataset,
                query_version=query_version,
                run_index=run_index,
                stage12_model=granite_model,
                planner_model=planner_model,
                query_id=int(qid),
                complexity=str(query_def.get("complexity", "")),
                source="reused_existing_granite",
                cache_grounding_failure=dict(payload.get("cache_grounding_failure") or {}),
                typed_plan_payload=dict(payload.get("typed_plan") or {}),
            )
            loaded.append(row)
    return loaded


def _run_live_model(
    *,
    dataset: str,
    df,
    planner_model: str,
    stage12_model: str,
    runs: int,
    query_versions: list[str],
    cache_path: str | None,
    semantic_cache_path: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for run_index in range(1, runs + 1):
        query_version = query_versions[(run_index - 1) % len(query_versions)]
        inscope = _inscope_query_defs(dataset, query_version)
        print(
            f"[benchmark_grounding] model={stage12_model} run={run_index}/{runs} "
            f"query_version={query_version} n_in_scope={len(inscope)}",
            flush=True,
        )

        primary_key, light_key = _resolve_api_keys(planner_model, stage12_model)
        client = LLMClient(
            model_name=planner_model,
            api_key=primary_key,
            light_model_name=stage12_model,
            light_api_key=light_key,
        )
        runner = BaselineRunner(
            mode="FLASH_FUSION_CACHE",
            df=df,
            client=client,
            dataset=dataset,
            cache_path=cache_path,
            semantic_cache_path=semantic_cache_path,
            copy_dataframe=False,
        )

        for query_id in sorted(inscope):
            query_def = inscope[query_id]
            query_text = str(query_def["text"])
            print(
                f"[benchmark_grounding] model={stage12_model} run={run_index}/{runs} "
                f"query_id={query_id} starting",
                flush=True,
            )
            query_started = time.perf_counter()
            result: RunResult | None = None
            for attempt in range(GROUNDING_RATE_LIMIT_MAX_ATTEMPTS):
                input_tokens_before = client.total_input_tokens()
                output_tokens_before = client.total_output_tokens()
                cost_usd_before = client.total_cost_usd()

                def _timeout_handler(signum, frame):
                    raise GroundingAttemptTimeoutError(
                        f"grounding attempt exceeded {GROUNDING_ATTEMPT_TIMEOUT_S:.0f}s"
                    )

                previous_handler = signal.getsignal(signal.SIGALRM)
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.setitimer(signal.ITIMER_REAL, GROUNDING_ATTEMPT_TIMEOUT_S)
                try:
                    result = runner.run(query_text)
                    break
                except GroundingAttemptTimeoutError as exc:
                    result = _failed_grounding_attempt_result(
                        query=query_text,
                        planner_model=planner_model,
                        elapsed_s=time.perf_counter() - query_started,
                        reason=str(exc),
                        exception_type=type(exc).__name__,
                    )
                    result.stages_run.append("grounding_attempt_timeout")
                    break
                except Exception as exc:  # Model output and provider failures must not abort the benchmark.
                    if _is_rate_limited_error(exc) and attempt + 1 < GROUNDING_RATE_LIMIT_MAX_ATTEMPTS:
                        retry_delay_s = _rate_limit_retry_delay_s(exc, attempt)
                        print(
                            f"[benchmark_grounding] query_id={query_id} rate limited; "
                            f"retrying attempt {attempt + 2}/{GROUNDING_RATE_LIMIT_MAX_ATTEMPTS} "
                            f"in {retry_delay_s:.1f}s",
                            flush=True,
                        )
                        time.sleep(retry_delay_s)
                        client = LLMClient(
                            model_name=planner_model,
                            api_key=primary_key,
                            light_model_name=stage12_model,
                            light_api_key=light_key,
                        )
                        runner = BaselineRunner(
                            mode="FLASH_FUSION_CACHE",
                            df=df,
                            client=client,
                            dataset=dataset,
                            cache_path=cache_path,
                            semantic_cache_path=semantic_cache_path,
                            copy_dataframe=False,
                        )
                        continue
                    result = _failed_grounding_attempt_result(
                        query=query_text,
                        planner_model=planner_model,
                        elapsed_s=time.perf_counter() - query_started,
                        reason=f"{type(exc).__name__}: {exc}",
                        exception_type=type(exc).__name__,
                    )
                    break
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, previous_handler)

            if result is None:
                raise RuntimeError("grounding attempt completed without a result")
            if result.execution_path == "grounding_attempt_failed":
                result.input_tokens = client.total_input_tokens() - input_tokens_before
                result.output_tokens = client.total_output_tokens() - output_tokens_before
                result.cost_usd = client.total_cost_usd() - cost_usd_before
            print(
                f"[benchmark_grounding] model={stage12_model} run={run_index}/{runs} "
                f"query_id={query_id} complete elapsed_s={time.perf_counter() - query_started:.2f}",
                flush=True,
            )
            result.query_id = int(query_id)

            row = _record_from_result(
                result=result,
                dataset=dataset,
                query_version=query_version,
                run_index=run_index,
                stage12_model=stage12_model,
                planner_model=planner_model,
                query_id=query_id,
                complexity=str(query_def.get("complexity", "")),
                source="live",
            )
            rows.append(row)
    return rows


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sample_std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mu = _mean(values)
    var = sum((x - mu) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(var)


def _summarize(
    rows: list[dict[str, Any]],
    model_order: list[str],
    runs: int,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["stage12_model"])].append(row)

    per_model: dict[str, Any] = {}
    for model in model_order:
        model_rows = grouped.get(model, [])
        by_run: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in model_rows:
            by_run[int(row["run_index"])].append(row)

        per_run_loss_pct: list[float] = []
        per_run_counts: dict[str, dict[str, int]] = {}
        for run_index in range(1, runs + 1):
            run_rows = by_run.get(run_index, [])
            total = len(run_rows)
            fails = sum(1 for r in run_rows if bool(r["failure_for_grounding_loss"]))
            loss = (100.0 * fails / total) if total else 0.0
            per_run_loss_pct.append(loss)
            per_run_counts[str(run_index)] = {
                "n_queries": total,
                "n_failures": fails,
            }

        total = len(model_rows)
        fails = sum(1 for r in model_rows if bool(r["failure_for_grounding_loss"]))
        mean_loss = _mean(per_run_loss_pct)
        std_loss = _sample_std(per_run_loss_pct)
        ci95 = 1.96 * std_loss / math.sqrt(len(per_run_loss_pct)) if per_run_loss_pct else 0.0

        failure_reasons = Counter(
            (r["deterministic_fallback_reason"] or "(none)")
            for r in model_rows
            if bool(r["failure_for_grounding_loss"])
        )
        plan_sources = Counter((r["plan_source"] or "(none)") for r in model_rows)

        size_meta = MODEL_SIZE_META.get(model, {"label": "unknown", "params_b": None})

        per_model[model] = {
            "size_label": size_meta["label"],
            "params_b": size_meta["params_b"],
            "n_queries_total": total,
            "n_failures": fails,
            "grounding_loss_mean_pct": mean_loss,
            "grounding_loss_std_pct": std_loss,
            "grounding_loss_ci95_pct": ci95,
            "per_run_loss_pct": per_run_loss_pct,
            "per_run_counts": per_run_counts,
            "failure_reason_breakdown": dict(failure_reasons),
            "cache_plan_source_breakdown": dict(plan_sources),
        }

    return {
        "benchmark": {
            "name": "ff_cache_grounding_loss_vs_model_size",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "fallback_stage": FALLBACK_STAGE,
            "runs": runs,
        },
        "model_order": model_order,
        "x_axis_size_labels": [MODEL_SIZE_META.get(m, {}).get("label", "unknown") for m in model_order],
        "model_label_map": {MODEL_SIZE_META.get(m, {}).get("label", "unknown"): m for m in model_order},
        "per_model": per_model,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _write_summary_csv(path: Path, summary: dict[str, Any], model_order: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "model",
                "size_label",
                "params_b",
                "n_queries_total",
                "n_failures",
                "grounding_loss_mean_pct",
                "grounding_loss_std_pct",
                "grounding_loss_ci95_pct",
            ],
        )
        writer.writeheader()
        for model in model_order:
            row = summary["per_model"].get(model, {})
            writer.writerow(
                {
                    "model": model,
                    "size_label": row.get("size_label"),
                    "params_b": row.get("params_b"),
                    "n_queries_total": row.get("n_queries_total", 0),
                    "n_failures": row.get("n_failures", 0),
                    "grounding_loss_mean_pct": row.get("grounding_loss_mean_pct", 0.0),
                    "grounding_loss_std_pct": row.get("grounding_loss_std_pct", 0.0),
                    "grounding_loss_ci95_pct": row.get("grounding_loss_ci95_pct", 0.0),
                }
            )


def _write_plot_csv(path: Path, summary: dict[str, Any], model_order: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "model",
                "size_label",
                "params_b",
                "grounding_loss_mean_pct",
                "grounding_loss_std_pct",
                "grounding_loss_ci95_pct",
            ],
        )
        writer.writeheader()
        for model in model_order:
            row = summary["per_model"].get(model, {})
            writer.writerow(
                {
                    "model": model,
                    "size_label": row.get("size_label"),
                    "params_b": row.get("params_b"),
                    "grounding_loss_mean_pct": row.get("grounding_loss_mean_pct", 0.0),
                    "grounding_loss_std_pct": row.get("grounding_loss_std_pct", 0.0),
                    "grounding_loss_ci95_pct": row.get("grounding_loss_ci95_pct", 0.0),
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark FLASH_FUSION_CACHE grounding loss across light models.")
    parser.add_argument("--dataset", required=True, choices=queries_v1.SUPPORTED_DATASETS)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Primary planner model (held constant).")
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_STAGE12_MODELS),
        help="Comma-separated stage12/light models to evaluate.",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--query-versions", default="v1,v2,v3")
    parser.add_argument("--cache-path", default=None)
    parser.add_argument("--semantic-cache-path", default=None)
    parser.add_argument("--data", default=None, help="Override dataset path.")
    parser.add_argument(
        "--output-dir",
        default="flashfusion/results/ff_hybrid_cache/grounding_benchmark",
    )
    parser.add_argument("--save-traces", action="store_true")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--error-bar", choices=("std", "ci95"), default="std")
    parser.add_argument(
        "--reuse-existing-granite-results",
        dest="reuse_existing_granite_results",
        action="store_true",
        default=True,
        help="Reuse granite rows from --existing-granite-root when available (default: on).",
    )
    parser.add_argument(
        "--no-reuse-existing-granite-results",
        dest="reuse_existing_granite_results",
        action="store_false",
        help="Disable importing existing granite rows and run granite live.",
    )
    parser.add_argument(
        "--existing-granite-root",
        default="flashfusion/results/ff_hybrid_cache/FLASH_FUSION_CACHE",
    )
    parser.add_argument(
        "--granite-model-id",
        default="ibm-granite/granite-4.2-8b",
        help="Model id to tag reused granite rows with.",
    )
    parser.add_argument(
        "--emit-typed-plan-ground-truth-json",
        default=None,
        help=(
            "Optional output path for consolidated typed-plan ground truth JSON "
            "built from <root>/<dataset>/grounding_benchmark_traces.json files."
        ),
    )
    parser.add_argument(
        "--typed-plan-ground-truth-root",
        default="flashfusion/results/ff_hybrid_cache/grounding_benchmark",
        help="Root folder containing bus/wisdm/mit_ecg subfolders with grounding_benchmark_traces.json.",
    )
    parser.add_argument(
        "--typed-plan-ground-truth-json",
        default=None,
        help="Optional typed-plan ground-truth JSON used to enrich/impute signatures in output rows.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.runs <= 0:
        raise SystemExit("--runs must be > 0")

    query_versions = _parse_csv_arg(args.query_versions, ["v1", "v2", "v3"])
    for v in query_versions:
        if v not in SUPPORTED_QUERY_VERSIONS:
            raise SystemExit(f"Unsupported query version in --query-versions: {v!r}")

    stage12_models = _parse_csv_arg(args.models, DEFAULT_STAGE12_MODELS)
    if not stage12_models:
        raise SystemExit("No models supplied in --models")

    model_order = sorted(
        stage12_models,
        key=lambda m: float(MODEL_SIZE_META.get(m, {}).get("params_b") or 1e9),
    )

    data_path = args.data or DEFAULT_DATA_PATHS[args.dataset]
    _validate_data_path(str(data_path))

    print(f"[benchmark_grounding] loading dataset={args.dataset} path={data_path}", flush=True)
    df = load_dataset_by_name(data_path, args.dataset, max_rows=args.max_rows)
    print(f"[benchmark_grounding] loaded rows={len(df)} cols={len(df.columns)}", flush=True)

    all_rows: list[dict[str, Any]] = []
    granite_model = args.granite_model_id
    reused_granite = False

    if args.reuse_existing_granite_results and granite_model in model_order:
        existing_rows = _load_existing_granite_rows(
            dataset=args.dataset,
            granite_model=granite_model,
            planner_model=args.model,
            existing_root=Path(args.existing_granite_root),
            runs=args.runs,
        )
        if existing_rows:
            print(
                "[benchmark_grounding] reusing existing granite artifacts "
                f"from {args.existing_granite_root} ({len(existing_rows)} rows)",
                flush=True,
            )
            all_rows.extend(existing_rows)
            reused_granite = True
        else:
            print(
                "[benchmark_grounding] no reusable granite rows found; granite will run live",
                flush=True,
            )

    for stage12_model in model_order:
        if reused_granite and stage12_model == granite_model:
            continue
        rows = _run_live_model(
            dataset=args.dataset,
            df=df,
            planner_model=args.model,
            stage12_model=stage12_model,
            runs=args.runs,
            query_versions=query_versions,
            cache_path=args.cache_path,
            semantic_cache_path=args.semantic_cache_path,
        )
        all_rows.extend(rows)

    built_gt: dict[str, Any] | None = None
    if args.emit_typed_plan_ground_truth_json:
        gt_root = Path(args.typed_plan_ground_truth_root)
        built_gt = _build_typed_plan_ground_truth_from_root(gt_root)
        gt_out = Path(args.emit_typed_plan_ground_truth_json)
        gt_out.parent.mkdir(parents=True, exist_ok=True)
        gt_out.write_text(json.dumps(built_gt, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"[benchmark_grounding] wrote typed-plan ground truth: {gt_out}", flush=True)

    gt_payload: dict[str, Any] | None = None
    if args.typed_plan_ground_truth_json:
        gt_payload = _load_typed_plan_ground_truth(Path(args.typed_plan_ground_truth_json))
    elif built_gt is not None:
        gt_payload = built_gt

    if gt_payload is not None:
        all_rows = _attach_ground_truth_to_rows(all_rows, gt_payload)
        print("[benchmark_grounding] attached typed-plan ground truth to row outputs", flush=True)

    summary = _summarize(all_rows, model_order=model_order, runs=args.runs)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_jsonl = output_dir / "grounding_benchmark_raw.jsonl"
    summary_json = output_dir / "grounding_benchmark_summary.json"
    summary_csv = output_dir / "grounding_benchmark_summary.csv"

    _write_jsonl(raw_jsonl, all_rows)
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    _write_summary_csv(summary_csv, summary, model_order)

    viz_dir = Path("results/primary_visualizations")
    plot_csv = viz_dir / "grounding_loss_vs_model_size.csv"
    _write_plot_csv(plot_csv, summary, model_order)

    if args.save_traces:
        traces_path = output_dir / "grounding_benchmark_traces.json"
        traces_path.write_text(json.dumps(all_rows, indent=2, ensure_ascii=True), encoding="utf-8")

    print("[benchmark_grounding] complete", flush=True)
    print(f"  raw:     {raw_jsonl}", flush=True)
    print(f"  summary: {summary_json}", flush=True)
    print(f"  csv:     {summary_csv}", flush=True)
    print(f"  plot_csv:{plot_csv}", flush=True)
    print("  plot_png:generate via flashfusion/viz/llamas.py", flush=True)


if __name__ == "__main__":
    main()
