"""Mini-experiment: OpenRouter latency and cost vs chunk count (direct prompting).

This script benchmarks a direct single-call prompt (no multi-stage Flash-Fusion)
to isolate context-length effects on:
- TTFT: time to first streamed token (prefill-dominated)
- TTLT: time to last streamed token (prefill + bounded decode)
- Query cost (USD), split into input / output cost
- Context-window feasibility (measured, not just extrapolated)
- Answer error vs. ground truth (optional)

Design choices that keep the measurement clean:
- The prompt's output format is query-agnostic (``ANSWER=<number>``) and
  ``max_tokens`` is capped (default 128) so TTLT is not dominated by verbosity.
- ``--runs N`` repeats every chunk count N times, interleaved (runs outer loop,
  chunk counts inner loop; optionally shuffled) to avoid time-of-day bias.
- ``--provider`` pins the OpenRouter provider (no fallbacks) so price and
  throughput do not change between calls.
- Actual token usage reported by the provider is used to calibrate the
  actual/estimated token ratio, which drives the context-limit marker and the
  per-point overflow flag (``predicted_overflow``).
- Failures are classified (``overflow`` / ``rate_limit`` / ``provider_error``)
  and the raw error text is stored.

Outputs (in ``--output-dir``):
- latency_vs_chunks.csv          one row per (run, chunk count) trial
- latency_vs_chunks_summary.csv  mean/SD/median/IQR + success rate per chunk count
- latency_vs_chunks.png/.pdf     latency + cost (per-run scatter, mean +/- SD)
- latency_vs_chunks_extrapolation.png/.pdf   projected tokens/cost to 100% of data
- latency_vs_chunks_accuracy.png/.pdf        abs. error vs chunks (if truth available)

Three runs + variation (ECG; 100.csv has 650,000 rows -> 34,448 chunks of ~19 rows):

  for i in 1 2 3; do
    python -m flashfusion.viz.miniexp.latencychunks \
      --dataset ecg \
      --data-path data/AutoIOT_dataset/ECG.0/tmp_csv/100.csv \
      --model meta-llama/llama-3.3-70b-instruct \
      --chunks 50 100 150 200 250 260 270 280 290 300 \
      --chunk-token-target 200 --retries 1 \
      --output-dir flashfusion/viz/miniexp/results/latency_run$i
  done

  python -m flashfusion.viz.miniexp.latencychunks \
    --avg-inputs flashfusion/viz/miniexp/results/latency_run{1,2,3}/latency_vs_chunks.csv \
    --output-dir flashfusion/viz/miniexp/results \
    --total-rows 650000 --rows-per-chunk 19 \
    --plot

Equivalent single invocation: add ``--runs 3`` to one command (interleaved).

## DETAILS: with ~200 estimated tokens/chunk the measured actual/estimated ratio is
## ~2.02 (~430 real tokens/chunk), so the 128k window is exhausted between 250 and 300 chunks.

Regenerate the single-column paper figure from saved trials:

  python -m flashfusion.viz.miniexp.latencychunks \
    --csv-input flashfusion/viz/miniexp/results/latency_trials.csv \
    --output-dir flashfusion/viz/miniexp/results --layout single --xscale log --plot
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from langchain_core.messages import HumanMessage
from langchain_openrouter import ChatOpenRouter

from flashfusion.config import (
    DEFAULT_MODEL,
    MODEL_RATE_PER_1M_TOKENS,
    TOKEN_ESTIMATE_MULTIPLIER,  # noqa: F401  (kept for backwards-compatible imports)
)
from flashfusion.pipeline.loader import load_dataset_by_name

DEFAULT_BENCHMARK_MODEL = "meta-llama/llama-3.3-70b-instruct"
DEFAULT_CHUNK_COUNTS = [50, 100, 150, 200, 250, 260, 270, 280, 290, 300]
DEFAULT_QUERY = "What is the average MLII observed in this dataset?"
DEFAULT_CHUNK_TOKEN_TARGET = 200  # chars/4 ≈ estimated tokens; ~2x that in real tokens
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEFAULT_MAX_TOKENS = 128
DEFAULT_TRUTH_COLUMN = "MLII"
DEFAULT_RATES = {"input": 0.59, "output": 0.79}
DEFAULT_DATA_PATHS = {
    "bus": "data/bus/bus_data.csv",
    "ecg": "data/AutoIOT_dataset/ECG.0/tmp_csv/100.csv",
    "mit_ecg": "data/AutoIOT_dataset/ECG.0/tmp_csv/100.csv",
}

# Metrics summarised per chunk count (mean, std, median, q25, q75 over successful trials).
SUMMARY_METRICS = [
    "ttft_ms",
    "ttlt_ms",
    "cost_usd",
    "input_cost_usd",
    "output_cost_usd",
    "input_tokens",
    "output_tokens",
    "prefill_tok_per_s",
    "decode_ms_per_token",
    "abs_error",
]
# Per-chunk-count constants carried through to the summary.
STATIC_COLUMNS = [
    "effective_chunks",
    "chunk_token_target",
    "context_window_tokens",
    "max_tokens",
    "query",
    "model",
    "context_tokens_est",
    "data_tokens_est",
    "prompt_overhead_tokens_est",
    "context_pct_window",
    "predicted_overflow",
    "total_chunks_available",
    "rows_covered",
    "pct_rows_covered",
    "truth_value",
]

COLOR_TTFT = "#2f6ad9"
COLOR_TTLT = "#f28e2b"
COLOR_COST = "#10b981"
COLOR_FAIL = "#dc2626"


# --------------------------------------------------------------------------- #
# Basic helpers
# --------------------------------------------------------------------------- #
def estimate_tokens(text: str) -> int:
    """Approximate token count using character-based heuristic (chars / 4).

    Word-splitting severely undercounts numeric CSV data because comma-separated
    numbers don't split on whitespace.  The chars/4 rule is a standard LLM
    approximation; for numeric CSV the real count is ~2x this (see --actual-token-ratio).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def get_rates(model: str) -> dict[str, float]:
    """Return per-1M-token input/output rates for a model (config.py with fallback)."""
    return MODEL_RATE_PER_1M_TOKENS.get(model, DEFAULT_RATES)


def compute_query_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute query cost in USD using model rates from config.py."""
    rates = get_rates(model)
    return (
        input_tokens * rates.get("input", 0.0)
        + output_tokens * rates.get("output", 0.0)
    ) / 1_000_000


def classify_error(message: str) -> str:
    """Classify a provider error message as overflow / rate_limit / provider_error."""
    low = (message or "").lower()
    if not low:
        return ""
    overflow_markers = (
        "context",
        "maximum",
        "too long",
        "too many tokens",
        "token limit",
        "exceed",
        "400",
    )
    if any(m in low for m in overflow_markers):
        return "overflow"
    if "429" in low or "rate limit" in low or "rate_limit" in low or "too many requests" in low:
        return "rate_limit"
    return "provider_error"


def parse_answer(text: str) -> float | None:
    """Extract the numeric answer from ``ANSWER=<number>`` (fallback: last number)."""
    if not text:
        return None
    num = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
    m = re.search(rf"ANSWER\s*=\s*({num})", text, flags=re.IGNORECASE)
    if m:
        return float(m.group(1))
    nums = re.findall(num, text)
    return float(nums[-1]) if nums else None


def resolve_data_path(dataset_name: str, data_path: str | None) -> Path:
    """Resolve the on-disk dataset file path from CLI inputs."""
    if data_path:
        candidate = Path(data_path)
        if candidate.is_dir():
            if dataset_name == "bus":
                candidate = candidate / "bus_data.csv"
            elif dataset_name in ("ecg", "mit_ecg"):
                candidate = candidate / "100.csv"
            else:
                raise ValueError(
                    f"Directory path is only auto-resolved for bus or ecg, got {dataset_name!r}."
                )
        if candidate.exists():
            return candidate
        # Try relative to repo root if absolute doesn't exist
        repo_root = Path(__file__).resolve().parents[3]
        candidate_rel = repo_root / data_path
        if candidate_rel.exists():
            return candidate_rel
        raise FileNotFoundError(f"Dataset path not found: {candidate}")

    rel_default = DEFAULT_DATA_PATHS.get(dataset_name)
    if not rel_default:
        raise ValueError(
            f"No default data path configured for dataset {dataset_name!r}; pass --data-path."
        )
    for p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[2]):
        candidate = p / rel_default
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Default dataset path not found: {rel_default}")


def build_token_chunks(df: pd.DataFrame, target_chunk_tokens: int) -> list[str]:
    """Build CSV chunks with approximately target_chunk_tokens per chunk."""
    if target_chunk_tokens <= 0:
        raise ValueError("target_chunk_tokens must be > 0")

    csv_text = df.to_csv(index=False)
    lines = csv_text.splitlines()
    if len(lines) <= 1:
        return []

    header = lines[0]
    row_lines = lines[1:]
    header_tokens = estimate_tokens(header)
    chunks: list[str] = []
    current_rows: list[str] = []
    current_tokens = header_tokens

    for row in row_lines:
        row_tokens = estimate_tokens(row)
        # If adding this row overshoots target and we already have content,
        # flush current chunk first.
        if current_rows and current_tokens + row_tokens > target_chunk_tokens:
            chunks.append(header + "\n" + "\n".join(current_rows))
            current_rows = []
            current_tokens = header_tokens

        current_rows.append(row)
        current_tokens += row_tokens

    if current_rows:
        chunks.append(header + "\n" + "\n".join(current_rows))

    return chunks


def build_prompt(query: str, chunk_texts: list[str]) -> str:
    """Build a deterministic, query-agnostic direct prompt for single-call measurement."""
    chunk_blocks = "\n\n".join(
        f"### CHUNK {i + 1}\n{chunk}" for i, chunk in enumerate(chunk_texts)
    )
    return (
        "You are a data analyst. Use ONLY the provided CSV chunks to answer the query.\n"
        "If the answer is not inferable from the data, respond with UNKNOWN.\n"
        "Do not show your work. Respond with the final answer only.\n\n"
        f"Query: {query}\n\n"
        "CSV data:\n"
        f"{chunk_blocks}\n\n"
        "Output format: ANSWER=<number>"
    )


# --------------------------------------------------------------------------- #
# Streaming measurement
# --------------------------------------------------------------------------- #
def _stream_chunk_to_text(chunk: Any) -> str:
    """Normalize streamed chunk content into plain text."""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def measure_streaming_latency(llm: ChatOpenRouter, prompt: str) -> dict[str, Any]:
    """Measure TTFT/TTLT, answer text and provider-reported usage/cost for one call."""
    start_s = time.perf_counter()
    first_token_s: float | None = None
    output_parts: list[str] = []
    out: dict[str, Any] = {
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "generation_id": "",
        "finish_reason": "",
        "upstream_cost_usd": None,
    }

    for chunk in llm.stream([HumanMessage(content=prompt)]):
        text = _stream_chunk_to_text(chunk)
        if text:
            if first_token_s is None:
                first_token_s = time.perf_counter()
            output_parts.append(text)
        um = getattr(chunk, "usage_metadata", None)
        if isinstance(um, dict):
            if "input_tokens" in um:
                out["input_tokens"] = int(um["input_tokens"])
            if "output_tokens" in um:
                out["output_tokens"] = int(um["output_tokens"])
        rm = getattr(chunk, "response_metadata", None)
        if isinstance(rm, dict):
            if "cost" in rm and rm["cost"] is not None:
                out["cost_usd"] = float(rm["cost"])
            cd = rm.get("cost_details")
            if isinstance(cd, dict) and cd.get("upstream_inference_cost") is not None:
                out["upstream_cost_usd"] = float(cd["upstream_inference_cost"])
            if rm.get("id"):
                out["generation_id"] = str(rm["id"])
            if rm.get("finish_reason"):
                out["finish_reason"] = str(rm["finish_reason"])

    end_s = time.perf_counter()
    out["ttft_ms"] = ((first_token_s if first_token_s is not None else end_s) - start_s) * 1000
    out["ttlt_ms"] = (end_s - start_s) * 1000
    out["answer"] = "".join(output_parts).strip()
    return out


def lookup_provider_name(generation_id: str, api_key: str | None) -> str:
    """Best-effort lookup of the serving provider via OpenRouter's generation endpoint."""
    if not generation_id or not api_key:
        return ""
    url = f"https://openrouter.ai/api/v1/generation?id={generation_id}"
    for delay in (1.0, 2.0):
        time.sleep(delay)  # the record is not available immediately
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8")).get("data", {})
            name = data.get("provider_name") or ""
            if name:
                return str(name)
        except Exception:  # noqa: BLE001
            continue
    return ""


# --------------------------------------------------------------------------- #
# Derived metrics, normalisation, summaries
# --------------------------------------------------------------------------- #
def add_derived_metrics(df: pd.DataFrame, cost_mismatch_tol: float = 0.10) -> pd.DataFrame:
    """Add prefill throughput, decode speed, and input/output cost split (idempotent)."""
    df = df.copy()
    ttft_s = pd.to_numeric(df["ttft_ms"], errors="coerce") / 1000
    ttlt_ms = pd.to_numeric(df["ttlt_ms"], errors="coerce")
    ttft_ms = pd.to_numeric(df["ttft_ms"], errors="coerce")
    in_tok = pd.to_numeric(df["input_tokens"], errors="coerce")
    out_tok = pd.to_numeric(df["output_tokens"], errors="coerce")

    df["prefill_tok_per_s"] = (in_tok / ttft_s).where(ttft_s > 0)
    df["decode_ms_per_token"] = ((ttlt_ms - ttft_ms) / out_tok).where(out_tok > 0)

    models = df["model"].fillna(DEFAULT_BENCHMARK_MODEL) if "model" in df.columns else pd.Series(
        [DEFAULT_BENCHMARK_MODEL] * len(df), index=df.index
    )
    in_rate = models.map(lambda m: get_rates(m).get("input", 0.0))
    out_rate = models.map(lambda m: get_rates(m).get("output", 0.0))
    df["input_cost_usd"] = in_tok * in_rate / 1_000_000
    df["output_cost_usd"] = out_tok * out_rate / 1_000_000
    df["computed_cost_usd"] = df["input_cost_usd"] + df["output_cost_usd"]

    cost = pd.to_numeric(df["cost_usd"], errors="coerce")
    df["cost_per_1k_input_usd"] = (cost / in_tok * 1000).where(in_tok > 0)
    rel = (cost - df["computed_cost_usd"]).abs() / df["computed_cost_usd"].where(
        df["computed_cost_usd"] > 0
    )
    df["cost_mismatch"] = (rel > cost_mismatch_tol).fillna(False)
    return df


def _normalize_trials(df: pd.DataFrame, actual_token_ratio: float = 1.9) -> pd.DataFrame:
    """Coerce a per-trial frame (including legacy CSVs) into the current schema."""
    df = df.copy()
    if "success" not in df.columns:
        df["success"] = df["ttft_ms"].notna()
    df["success"] = df["success"].map(lambda v: str(v).strip().lower() in ("true", "1", "1.0"))
    if "run_id" not in df.columns:
        df["run_id"] = "1"
    df["run_id"] = df["run_id"].astype(str)
    for col in ("error", "error_type", "answer", "provider", "generation_id", "finish_reason"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    if "model" not in df.columns:
        df["model"] = DEFAULT_BENCHMARK_MODEL
    for col in (
        "ttft_ms",
        "ttlt_ms",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "context_tokens_est",
        "chunk_count",
        "abs_error",
    ):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    ok = df["success"]
    miss_in = ok & df["input_tokens"].isna() & df["context_tokens_est"].notna()
    if miss_in.any():
        df.loc[miss_in, "input_tokens"] = (
            df.loc[miss_in, "context_tokens_est"] * actual_token_ratio
        ).round()
    miss_out = ok & df["output_tokens"].isna()
    if miss_out.any():
        df.loc[miss_out, "output_tokens"] = [
            float(estimate_tokens(a)) for a in df.loc[miss_out, "answer"]
        ]
    df = add_derived_metrics(df)
    miss_cost = ok & df["cost_usd"].isna()
    if miss_cost.any():
        df.loc[miss_cost, "cost_usd"] = df.loc[miss_cost, "computed_cost_usd"]
    # Failed rows with a message but no class (legacy CSVs).
    need_cls = (~df["success"]) & (df["error_type"] == "") & (df["error"] != "")
    if need_cls.any():
        df.loc[need_cls, "error_type"] = [classify_error(e) for e in df.loc[need_cls, "error"]]
    return df


def summarize_trials(trials: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per chunk count: n_runs, n_success, mean/std/median/IQR of each metric."""
    t = _normalize_trials(trials)
    rows: list[dict[str, Any]] = []
    for chunk_count, g in t.groupby("chunk_count", sort=True):
        ok = g[g["success"]]
        row: dict[str, Any] = {
            "chunk_count": int(chunk_count),
            "n_runs": int(g["run_id"].nunique()),
            "n_success": int(ok["run_id"].nunique()),
        }
        row["success_rate"] = row["n_success"] / row["n_runs"] if row["n_runs"] else 0.0
        row["success"] = row["n_success"] > 0
        fails = g[~g["success"]]
        row["error_type"] = (
            fails["error_type"].replace("", np.nan).dropna().mode().iloc[0]
            if not fails.empty and fails["error_type"].replace("", np.nan).notna().any()
            else ""
        )
        row["error"] = fails["error"].iloc[0] if not fails.empty else ""
        for col in STATIC_COLUMNS:
            row[col] = g[col].iloc[0] if col in g.columns else np.nan
        for m in SUMMARY_METRICS:
            vals = ok[m].dropna() if m in ok.columns else pd.Series(dtype=float)
            row[m] = vals.mean() if len(vals) else np.nan
            row[f"{m}_std"] = vals.std(ddof=1) if len(vals) > 1 else (0.0 if len(vals) == 1 else np.nan)
            row[f"{m}_median"] = vals.median() if len(vals) else np.nan
            row[f"{m}_q25"] = vals.quantile(0.25) if len(vals) else np.nan
            row[f"{m}_q75"] = vals.quantile(0.75) if len(vals) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def average_runs(
    csv_paths: list[str],
    actual_token_ratio: float = 1.9,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load per-run CSVs; return (combined trials, per-chunk summary)."""
    dfs: list[pd.DataFrame] = []
    for i, p in enumerate(csv_paths, 1):
        df = pd.read_csv(p)
        orig = df["run_id"].astype(str) if "run_id" in df.columns else pd.Series(["1"] * len(df))
        df["run_id"] = [f"{i}-{o}" for o in orig]
        df["source_csv"] = p
        dfs.append(df)
    combined = pd.concat(dfs, ignore_index=True)
    for field in ["chunk_token_target", "context_window_tokens", "query", "model", "max_tokens"]:
        if field not in combined.columns:
            continue
        unique_values = combined[field].dropna().unique().tolist()
        if len(unique_values) > 1:
            raise ValueError(
                f"Cannot average runs with different {field} values: {unique_values}. "
                "Regenerate or filter the inputs so all runs use the same settings."
            )
    trials = _normalize_trials(combined, actual_token_ratio=actual_token_ratio)
    if not trials["success"].any():
        raise ValueError("No successful rows found across provided CSVs.")
    return trials, summarize_trials(trials)


# --------------------------------------------------------------------------- #
# Experiment
# --------------------------------------------------------------------------- #
def run_experiment(
    dataset_name: str = "bus",
    data_path: str | None = None,
    chunk_counts: list[int] | None = None,
    model: str = DEFAULT_BENCHMARK_MODEL,
    output_dir: str = "flashfusion/viz/miniexp/results",
    query: str = DEFAULT_QUERY,
    chunk_token_target: int = DEFAULT_CHUNK_TOKEN_TARGET,
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS,
    retries: int = 0,
    dry_run: bool = False,
    actual_token_ratio: float = 1.9,
    runs: int = 1,
    max_tokens: int | None = DEFAULT_MAX_TOKENS,
    provider: list[str] | None = None,
    shuffle: bool = False,
    seed: int = 0,
    skip_predicted_overflow: bool = False,
    lookup_provider: bool = False,
    truth_column: str | None = DEFAULT_TRUTH_COLUMN,
) -> pd.DataFrame:
    """Run direct single-call OpenRouter measurements; returns one row per trial."""
    if chunk_counts is None:
        chunk_counts = DEFAULT_CHUNK_COUNTS
    chunk_counts = sorted({c for c in chunk_counts if c > 0})
    if not chunk_counts:
        raise ValueError("chunk_counts must contain at least one positive integer")
    if runs < 1:
        raise ValueError("runs must be >= 1")
    max_tokens = max_tokens if (max_tokens and max_tokens > 0) else None

    resolved_data_path = resolve_data_path(dataset_name, data_path)
    # Load directly from CSV when given a plain CSV file, bypassing typed loaders.
    if str(resolved_data_path).endswith(".csv") and dataset_name not in ("bus", "wisdm", "mit_ecg"):
        df = pd.read_csv(str(resolved_data_path))
    else:
        df = load_dataset_by_name(str(resolved_data_path), dataset_name)

    chunks = build_token_chunks(df, target_chunk_tokens=chunk_token_target)
    if not chunks:
        raise ValueError("Chunk builder produced no chunks; dataset may be empty.")
    chunk_rows = np.cumsum([len(c.splitlines()) - 1 for c in chunks])  # data rows per prefix

    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("GROQ_API_KEY")
    if not dry_run and not api_key:
        raise ValueError("OPENROUTER_API_KEY or GROQ_API_KEY environment variable required")

    llm = None
    if not dry_run:
        kwargs: dict[str, Any] = {"model": model, "api_key": api_key, "temperature": 0, "max_retries": 2}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if provider:
            kwargs["openrouter_provider"] = {"order": provider, "allow_fallbacks": False}
        llm = ChatOpenRouter(**kwargs)
    prompt_overhead_tokens = estimate_tokens(build_prompt(query=query, chunk_texts=[]))

    have_truth = bool(truth_column) and truth_column in df.columns
    if truth_column and not have_truth:
        print(f"Truth column {truth_column!r} not in dataset; skipping accuracy tracking.")

    print(f"Loaded dataset: {resolved_data_path}")
    print(f"Rows: {len(df):,} | built chunks: {len(chunks):,} at ~{chunk_token_target} tokens/chunk")
    print(
        f"Runs: {runs} | max_tokens: {max_tokens or 'unbounded'} | "
        f"provider: {provider or 'auto (fallbacks allowed)'}"
    )

    # Schedule: runs outer, chunk counts inner (interleaved); optionally shuffled.
    schedule = [(r, c) for r in range(1, runs + 1) for c in chunk_counts]
    if shuffle:
        random.Random(seed).shuffle(schedule)

    observed_ratios: list[float] = []
    results: list[dict[str, Any]] = []
    for run_id, requested_chunks in schedule:
        row: dict[str, Any] = {
            "run_id": run_id,
            "chunk_count": requested_chunks,
            "effective_chunks": requested_chunks,
            "total_chunks_available": len(chunks),
            "chunk_token_target": chunk_token_target,
            "context_window_tokens": context_window_tokens,
            "max_tokens": max_tokens or 0,
            "query": query,
            "model": model,
            "provider_pinned": ",".join(provider) if provider else "",
            "provider": "",
            "success": False,
            "error": "",
            "error_type": "",
            "ttft_ms": None,
            "ttlt_ms": None,
            "context_tokens_est": None,
            "data_tokens_est": None,
            "prompt_overhead_tokens_est": prompt_overhead_tokens,
            "context_pct_window": None,
            "crosses_context_window": None,
            "predicted_overflow": None,
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
            "token_ratio_obs": None,
            "generation_id": "",
            "finish_reason": "",
            "rows_covered": None,
            "pct_rows_covered": None,
            "truth_value": None,
            "parsed_answer": None,
            "abs_error": None,
            "answer": "",
        }
        tag = f"[run {run_id}/{runs}] Chunks={requested_chunks}"

        if requested_chunks > len(chunks):
            row["error"] = (
                f"Requested {requested_chunks} chunks but only {len(chunks)} available from dataset."
            )
            row["error_type"] = "skipped"
            results.append(row)
            print(f"{tag}: skipped ({row['error']})")
            continue

        selected_chunks = chunks[:requested_chunks]
        prompt = build_prompt(query=query, chunk_texts=selected_chunks)
        context_tokens_est = estimate_tokens(prompt)
        context_pct_window = (context_tokens_est / context_window_tokens) * 100
        ratio_now = float(np.median(observed_ratios)) if observed_ratios else actual_token_ratio
        predicted_actual = context_tokens_est * ratio_now + (max_tokens or 0)

        row["context_tokens_est"] = context_tokens_est
        row["data_tokens_est"] = max(0, context_tokens_est - prompt_overhead_tokens)
        row["context_pct_window"] = context_pct_window
        row["crosses_context_window"] = context_tokens_est >= context_window_tokens
        row["predicted_overflow"] = bool(predicted_actual > context_window_tokens)
        rows_covered = int(chunk_rows[requested_chunks - 1])
        row["rows_covered"] = rows_covered
        row["pct_rows_covered"] = rows_covered / len(df) * 100
        truth_value = float(df[truth_column].iloc[:rows_covered].mean()) if have_truth else None
        row["truth_value"] = truth_value

        if row["predicted_overflow"] and skip_predicted_overflow:
            row["error"] = (
                f"Predicted prompt ~{predicted_actual:,.0f} tokens exceeds window "
                f"{context_window_tokens:,}; call skipped."
            )
            row["error_type"] = "overflow_predicted"
            results.append(row)
            print(f"{tag}: skipped ({row['error']})")
            continue

        if dry_run:
            in_tok = int(round(context_tokens_est * actual_token_ratio))
            out_tok = 20
            row.update(
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=compute_query_cost(model, in_tok, out_tok),
                success=True,
                ttft_ms=np.nan,
                ttlt_ms=np.nan,
            )
            results.append(row)
            print(
                f"{tag}: dry-run | context~{context_tokens_est:,} "
                f"({context_pct_window:.1f}% of window), cost~${row['cost_usd']:.4f}, "
                f"predicted_overflow={row['predicted_overflow']}"
            )
            continue

        assert llm is not None
        last_error = ""
        for attempt in range(retries + 1):
            try:
                m = measure_streaming_latency(llm=llm, prompt=prompt)
                row["ttft_ms"] = m["ttft_ms"]
                row["ttlt_ms"] = m["ttlt_ms"]
                row["answer"] = m["answer"]
                row["generation_id"] = m["generation_id"]
                row["finish_reason"] = m["finish_reason"]
                row["input_tokens"] = (
                    m["input_tokens"]
                    if m["input_tokens"] is not None
                    else int(round(context_tokens_est * ratio_now))
                )
                row["output_tokens"] = (
                    m["output_tokens"] if m["output_tokens"] is not None else estimate_tokens(m["answer"])
                )
                row["cost_usd"] = (
                    m["cost_usd"]
                    if m["cost_usd"] is not None
                    else compute_query_cost(model, row["input_tokens"], row["output_tokens"])
                )
                if m["input_tokens"] is not None and context_tokens_est > 0:
                    row["token_ratio_obs"] = m["input_tokens"] / context_tokens_est
                    observed_ratios.append(row["token_ratio_obs"])
                if lookup_provider:
                    row["provider"] = lookup_provider_name(m["generation_id"], api_key)
                parsed = parse_answer(m["answer"])
                row["parsed_answer"] = parsed
                if parsed is not None and truth_value is not None:
                    row["abs_error"] = abs(parsed - truth_value)
                row["success"] = True
                last_error = ""
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if classify_error(last_error) == "overflow" and "400" in last_error:
                    break
                if attempt < retries:
                    print(f"{tag}: attempt {attempt + 1} failed, retrying... {last_error}")
                    time.sleep(2.0)

        row["error"] = last_error
        row["error_type"] = classify_error(last_error) if last_error else ""
        if last_error and row["error_type"] == "provider_error" and row["predicted_overflow"]:
            row["error_type"] = "overflow_suspected"  # generic provider error beyond predicted window
        results.append(row)
        if row["success"]:
            print(
                f"{tag}: TTFT={row['ttft_ms']:.0f}ms, TTLT={row['ttlt_ms']:.0f}ms, "
                f"in={row['input_tokens']:,}, out={row['output_tokens']:,}, "
                f"Cost=${row['cost_usd']:.4f}, ratio~{ratio_now:.2f}"
                + (f", abs_err={row['abs_error']:.3f}" if row["abs_error"] is not None else "")
            )
        else:
            print(f"{tag}: failed [{row['error_type']}] ({row['error']})")

    trials = pd.DataFrame(results)
    trials = _normalize_trials(trials, actual_token_ratio=actual_token_ratio)
    os.makedirs(output_dir, exist_ok=True)
    out_csv = Path(output_dir) / "latency_vs_chunks.csv"
    trials.to_csv(out_csv, index=False)
    summary = summarize_trials(trials)
    out_sum = Path(output_dir) / "latency_vs_chunks_summary.csv"
    summary.to_csv(out_sum, index=False)
    if observed_ratios:
        print(f"\nMeasured actual/estimated token ratio: median {np.median(observed_ratios):.3f}")
    print(f"Trials saved to {out_csv}")
    print(f"Summary saved to {out_sum}")
    return trials


# --------------------------------------------------------------------------- #
# Plotting
# --------------------------------------------------------------------------- #
STYLES: dict[str, dict[str, Any]] = {
    # IEEE single column (3.5 in): text is sized for 1:1 printing (8-9 pt labels).
    "single": dict(figsize=(3.5, 2.35), label=9, tick=8, legend=7, note=6.5, lw=1.4, ms=3.6,
                   axlw=0.8, scatter=7, dpi=300, compact=True),
    # IEEE double column / full-width figure (7.16 in).
    "double": dict(figsize=(7.16, 2.8), label=10, tick=9, legend=8, note=8, lw=1.8, ms=5.0,
                   axlw=1.0, scatter=14, dpi=300, compact=True),
    # Slides / screen.
    "large": dict(figsize=(18, 6.5), label=16, tick=14, legend=13, note=15, lw=2.4, ms=7.5,
                  axlw=1.8, scatter=22, dpi=180, compact=False),
}


def _apply_style(st: dict[str, Any]) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "figure.facecolor": "#ffffff",
            "axes.facecolor": "#ffffff",
            "axes.edgecolor": "#222222",
            "axes.linewidth": st["axlw"],
            "axes.titlesize": st["label"],
            "axes.titleweight": "bold",
            "axes.labelsize": st["label"],
            "axes.labelweight": "bold",
            "axes.labelpad": 1.5 if st["compact"] else 4.0,
            "xtick.labelsize": st["tick"],
            "ytick.labelsize": st["tick"],
            "xtick.major.pad": 1.5 if st["compact"] else 3.5,
            "ytick.major.pad": 1.5 if st["compact"] else 3.5,
            "xtick.major.size": 2.5 if st["compact"] else 4.0,
            "ytick.major.size": 2.5 if st["compact"] else 4.0,
            "xtick.major.width": st["axlw"],
            "ytick.major.width": st["axlw"],
            "legend.fontsize": st["legend"],
            "legend.title_fontsize": st["legend"],
            "grid.alpha": 0.55,
            "grid.color": "#cccccc",
            "grid.linewidth": 0.5 if st["compact"] else 1.0,
            "pdf.fonttype": 42,  # embed TrueType (IEEE PDF eXpress friendly)
            "ps.fonttype": 42,
        }
    )


def _tight_layout(fig: Any, st: dict[str, Any]) -> None:
    """Minimise whitespace: constrained layout with small pads (inches)."""
    engine = fig.get_layout_engine()
    if engine is not None:
        if st["compact"]:
            engine.set(w_pad=0.02, h_pad=0.02, wspace=0.05, hspace=0.02)
        else:
            engine.set(w_pad=0.1, h_pad=0.1, wspace=0.06)


def _save(fig: Any, out_png: Path, out_pdf: Path | None, st: dict[str, Any]) -> None:
    pad = 0.02 if st["compact"] else 0.1
    fig.savefig(out_png, dpi=st["dpi"], bbox_inches="tight", pad_inches=pad)
    if out_pdf is not None:
        fig.savefig(out_pdf, bbox_inches="tight", pad_inches=pad)


def _fig_legend(fig: Any, axes: Any, st: dict[str, Any], ncol: int | None = None) -> None:
    """One de-duplicated legend above the panels (saves per-panel whitespace)."""
    handles, labels, seen = [], [], set()
    for ax in axes:
        for h, l in zip(*ax.get_legend_handles_labels()):
            if l and not l.startswith("_") and l not in seen:
                seen.add(l)
                handles.append(h)
                labels.append(l)
    if not handles:
        return
    fig.legend(
        handles, labels, loc="outside upper center", ncol=ncol or len(handles), frameon=False,
        handlelength=1.3 if st["compact"] else 2.0, handletextpad=0.3,
        columnspacing=0.9 if st["compact"] else 1.8, borderaxespad=0.0,
    )


def _nice_x_ticks(lo: float, hi: float, log_x: bool, use_pct: bool, measured: list[float], compact: bool) -> list[float]:
    """Few, readable x ticks inside [lo, hi]."""
    if log_x:
        narrow = hi / max(lo, 1e-12) < 15
        cands = (
            ([0.1, 0.15, 0.2, 0.3, 0.5, 0.7, 1, 1.5, 2, 3, 5, 7, 10] if narrow else [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100])
            if use_pct
            else [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
        )
        ticks = [c for c in cands if lo <= c <= hi]
        if compact and len(ticks) > 5:
            ticks = ticks[:: math.ceil(len(ticks) / 5)]
        return [float(t) for t in ticks]
    ticks = sorted(measured)
    max_n = 5 if compact else 12
    if len(ticks) > max_n:
        idx = np.unique(np.linspace(0, len(ticks) - 1, max_n).round().astype(int))
        ticks = [ticks[i] for i in idx]
    return ticks


def _fmt_tick(v: float) -> str:
    return f"{v:g}" if v < 1000 else f"{v / 1000:g}k"


def _resolve_total_chunks(
    summary: pd.DataFrame,
    total_chunks: int | None,
    total_rows: int | None,
    rows_per_chunk: int | None,
) -> int | None:
    if total_chunks:
        return int(total_chunks)
    if "total_chunks_available" in summary.columns and summary["total_chunks_available"].notna().any():
        return int(summary["total_chunks_available"].dropna().max())
    if total_rows and rows_per_chunk:
        return int(math.ceil(total_rows / rows_per_chunk))
    return None


def fit_input_tokens(summary: pd.DataFrame) -> tuple[float, float] | None:
    """Linear fit input_tokens = slope * chunks + intercept over successful chunk counts."""
    ok = summary[summary["n_success"] > 0].dropna(subset=["input_tokens"])
    if ok["chunk_count"].nunique() < 2:
        return None
    slope, intercept = np.polyfit(ok["chunk_count"].astype(float), ok["input_tokens"].astype(float), 1)
    if slope <= 0:
        return None
    return float(slope), float(intercept)


def _plot_main(
    trials_df: pd.DataFrame,
    output_dir: str = "flashfusion/viz/miniexp/results",
    chunk_token_target: int = DEFAULT_CHUNK_TOKEN_TARGET,
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS,
    ttft_only: bool = False,
    actual_token_ratio: float = 1.9,
    max_chunks: int | None = None,
    total_rows: int | None = None,
    rows_per_chunk: int | None = None,
    total_chunks: int | None = None,
    filename_prefix: str = "latency_vs_chunks",
    dataset_label: str = "Dataset",
    layout: str = "single",
    xscale: str = "log",
    yscale: str = "linear",
    show_variance: bool = True,
    extras: bool = True,
) -> None:
    """Plot latency and cost (per-run scatter, mean +/- SD) plus extrapolation/accuracy figures.

    layout: "single" (IEEE column, 3.5 in), "double" (7.16 in) or "large" (slides).
    xscale / yscale: "log" or "linear"; log x exposes the tail near the context limit.
    """
    trials = _normalize_trials(trials_df, actual_token_ratio=actual_token_ratio)
    if max_chunks is not None:
        trials = trials[trials["chunk_count"] <= max_chunks]
    summary = summarize_trials(trials)
    ok_summary = summary[summary["n_success"] > 0].sort_values("chunk_count")
    if ok_summary.empty:
        print("No successful rows to plot.")
        return
    ok_trials = trials[trials["success"]]
    multi_run = int(summary["n_runs"].max()) > 1
    max_tokens = (
        float(trials["max_tokens"].dropna().max())
        if "max_tokens" in trials.columns and trials["max_tokens"].notna().any()
        else 0.0
    )

    total_chunks_n = _resolve_total_chunks(summary, total_chunks, total_rows, rows_per_chunk)
    if total_chunks_n:
        def xmap(c: Any) -> Any:
            return np.asarray(c, dtype=float) * 100.0 / total_chunks_n
    elif total_rows and rows_per_chunk:
        def xmap(c: Any) -> Any:
            return np.asarray(c, dtype=float) * rows_per_chunk / total_rows * 100.0
    else:
        xmap = None  # type: ignore[assignment]
    use_pct_axis = xmap is not None
    if not use_pct_axis:
        def xmap(c: Any) -> Any:  # type: ignore[no-redef]
            return np.asarray(c, dtype=float)

    st = STYLES[layout]
    compact = bool(st["compact"])
    log_x = xscale == "log"
    log_y = yscale == "log"
    x_label = f"Fraction of {dataset_label} Data (%)" if use_pct_axis else "Number of Chunks"
    _apply_style(st)
    fig, ax_lat = plt.subplots(1, 1, figsize=st["figsize"], layout="constrained")
    ax_cost = ax_lat.twinx()  # single plot: TTFT on left axis, cost on right axis
    _tight_layout(fig, st)

    xs = xmap(ok_summary["chunk_count"])

    top_vals: dict[str, float] = {}

    def _band(ax: Any, mean_col: str, scale: float, color: str, marker: str, label: str, band_alpha: float) -> None:
        mean = ok_summary[mean_col] / scale
        std = ok_summary[f"{mean_col}_std"].fillna(0) / scale
        ax.plot(xs, mean, marker=marker, color=color, linewidth=st["lw"], markersize=st["ms"], alpha=0.95, label=label)
        top_vals.setdefault(mean_col, float((mean + (std if (multi_run and show_variance) else 0)).max()))
        if multi_run and show_variance:
            lower = (mean - std).clip(lower=mean.min() * 0.2 if log_y else 0)
            ax.fill_between(
                xs, lower, mean + std, color=color, alpha=band_alpha, linewidth=0,
                label=None if compact else f"{label} ±1 SD",
            )

    # Left: latency
    _band(ax_lat, "ttft_ms", 1000.0, COLOR_TTFT, "o", "TTFT", 0.18)
    ax_lat.set_ylabel("Time to First Token (s)")

    # Right: cost
    _band(ax_cost, "cost_usd", 1e-5, COLOR_COST, "^", "Cost", 0.18)
    ax_cost.set_ylabel(r"Cost (\$ $\times$ 10$^{-5}$)")
    if multi_run and not compact:
        for _, r in ok_summary.iterrows():
            ax_cost.annotate(
                f"{int(r['n_success'])}/{int(r['n_runs'])}",
                (float(xmap(r["chunk_count"])), float(r["cost_usd"])),
                textcoords="offset points", xytext=(0, 6), ha="center", fontsize=st["note"] * 0.7, color="#475569",
            )

    for ax in (ax_lat, ax_cost):
        ax.set_xscale("log" if log_x else "linear")
        if log_y:
            ax.set_yscale("log")
    if not log_y:
        # Cost spans several orders of magnitude, so show it on a true log scale.
        from matplotlib.ticker import MaxNLocator

        def _ticks(top: float) -> np.ndarray:
            t = MaxNLocator(4 if compact else 6, steps=[1, 2, 2.5, 5, 10]).tick_values(0, top)
            return t[(t >= 0) & (t <= t[t >= top].min() if (t >= top).any() else t.max())]

        lat_ticks = _ticks(top_vals["ttft_ms"] * 1.03)
        lat_top = float(lat_ticks.max())
        cost_ticks = np.array([1, 10, 100, 1000, 10000], dtype=float)
        ax_lat.set_ylim(0, lat_top * 1.05)
        ax_cost.set_yscale("log")
        ax_cost.set_ylim(cost_ticks[0], cost_ticks[-1])
        lat_all = np.arange(0, lat_top * 1.05 + 1e-9, float(lat_ticks[1] - lat_ticks[0]))
        ax_lat.set_yticks(lat_all)
        ax_cost.set_yticks(cost_ticks)
        ax_cost.set_yticklabels([r"$10^0$", r"$10^1$", r"$10^2$", r"$10^3$", r"$10^4$"])
    ax_lat.grid(True, which="major", axis="both" if log_x else "y")
    ax_lat.set_axisbelow(True)

    # Context-limit marker from a regression on measured input tokens.
    threshold_chunks: float | None = None
    fit = fit_input_tokens(summary)
    if fit is not None:
        slope, intercept = fit
        threshold_chunks = (context_window_tokens - max_tokens - intercept) / slope
    else:
        first, last = ok_summary.iloc[0], ok_summary.iloc[-1]
        if len(ok_summary) >= 2 and last["chunk_count"] > first["chunk_count"]:
            s_est = (last["context_tokens_est"] - first["context_tokens_est"]) / (
                last["chunk_count"] - first["chunk_count"]
            )
            if s_est > 0:
                overhead_est = float(ok_summary["prompt_overhead_tokens_est"].iloc[0])
                threshold_chunks = (context_window_tokens / actual_token_ratio - overhead_est) / s_est
    threshold_x = (
        float(xmap(threshold_chunks)) if threshold_chunks is not None and threshold_chunks > 0 else None
    )

    # Failed points: X markers on the x-axis.
    failed = summary[summary["n_success"] == 0]
    fail_x = [float(xmap(c)) for c in failed["chunk_count"]]

    data_min = float(xs.min())
    data_max = float(max([float(xs.max())] + fail_x))
    data_span = max(data_max - data_min, 1e-9)
    if log_x:
        x_left = data_min / 1.2
        x_right = data_max * 1.12
        show_limit = threshold_x is not None and threshold_x <= data_max * 5
        if show_limit:
            x_right = max(x_right, threshold_x * 1.25)
    else:
        x_left = data_min - data_span * 0.03
        x_right = data_max + data_span * 0.04
        show_limit = threshold_x is not None and threshold_x <= data_max + 2.0 * data_span
        if show_limit:
            x_right = max(x_right, threshold_x + data_span * 0.1)

    measured_x = [float(v) for v in xmap(sorted(summary["chunk_count"].astype(int).unique().tolist()))]
    ticks = _nice_x_ticks(x_left, x_right, log_x, use_pct_axis, measured_x, compact)
    limit_label = f"{context_window_tokens // 1000}k limit" if compact else f"Context limit: {context_window_tokens // 1000}k tokens"

    for ax in (ax_lat,):
        ax.set_xlim(x_left, x_right)
        ax.set_xticks(ticks)
        ax.set_xticklabels([_fmt_tick(t) if use_pct_axis or log_x else f"{int(t)}" for t in ticks])
        ax.xaxis.set_minor_locator(plt.NullLocator())
        if fail_x:
            ax.plot(
                fail_x, [0.03] * len(fail_x), linestyle="none", marker="X", markersize=st["ms"] + 1.5,
                color=COLOR_FAIL, transform=ax.get_xaxis_transform(), clip_on=False, zorder=5,
                label="Failed",
            )
        if show_limit:
            ax.axvline(threshold_x, linestyle="--", color="#64748b", linewidth=st["lw"] * 0.7)
            ax.axvspan(threshold_x, x_right, color=COLOR_FAIL, alpha=0.07, linewidth=0)
            ax.text(
                threshold_x * 1.04 if log_x else threshold_x + data_span * 0.01, 0.55, limit_label,
                rotation=90, ha="left", va="center", fontsize=st["note"], color="#475569",
                style="italic", fontweight="bold", transform=ax.get_xaxis_transform(),
            )

    fig.supxlabel(x_label, fontsize=st["label"], fontweight="bold")
    _fig_legend(fig, (ax_lat, ax_cost), st)

    if threshold_x is not None:
        unit = "% of dataset" if use_pct_axis else "chunks"
        print(f"Context-window threshold ~{threshold_x:.2f} {unit} (~{threshold_chunks:.0f} chunks)")

    os.makedirs(output_dir, exist_ok=True)
    out_png = Path(output_dir) / f"{filename_prefix}.png"
    out_pdf = Path(output_dir) / f"{filename_prefix}.pdf"
    _save(fig, out_png, out_pdf, st)
    print(f"Plot saved to {out_png}")
    print(f"Plot saved to {out_pdf}")
    plt.close(fig)

    if extras and total_chunks_n:
        plot_extrapolation(
            summary, total_chunks_n, context_window_tokens, max_tokens, output_dir,
            f"{filename_prefix}_extrapolation", dataset_label, layout=layout,
        )
    elif extras:
        print("Skipping extrapolation figure (pass --total-chunks, or --total-rows with --rows-per-chunk).")
    if extras:
        plot_accuracy(trials, summary, xmap, x_label, output_dir, f"{filename_prefix}_accuracy", layout=layout, log_x=log_x)


def plot_results(trials_df: pd.DataFrame, **kwargs: Any) -> None:
    """Write two main figures: <prefix>.png (clean lines) and <prefix>_variance.png (mean +/- SD bands)."""
    prefix = kwargs.pop("filename_prefix", "latency_vs_chunks")
    _plot_main(trials_df, filename_prefix=prefix, show_variance=False, extras=True, **kwargs)
    _plot_main(trials_df, filename_prefix=f"{prefix}_variance", show_variance=True, extras=False, **kwargs)


def plot_extrapolation(
    summary: pd.DataFrame,
    total_chunks: int,
    context_window_tokens: int,
    max_tokens: float,
    output_dir: str,
    filename_prefix: str,
    dataset_label: str = "Dataset",
    layout: str = "single",
) -> None:
    """Project input tokens and per-query cost to 100% of the dataset (log-log)."""
    fit = fit_input_tokens(summary)
    ok = summary[summary["n_success"] > 0]
    if fit is None or ok.empty:
        print("Not enough successful points for extrapolation figure.")
        return
    slope, intercept = fit
    model = str(ok["model"].iloc[0]) if "model" in ok.columns else DEFAULT_BENCHMARK_MODEL
    rates = get_rates(model)
    mean_out_tokens = float(ok["output_tokens"].mean()) if ok["output_tokens"].notna().any() else 0.0

    c_min = max(1.0, float(ok["chunk_count"].min()))
    cs = np.logspace(math.log10(c_min), math.log10(total_chunks), 300)
    tokens = slope * cs + intercept
    cfg_rate = rates.get("input", 0.0) / 1e6
    # Effective $/prompt-token implied by the provider-reported cost (may differ from config rates).
    valid = ok.dropna(subset=["cost_usd", "input_tokens"])
    eff_rate = float(valid["cost_usd"].sum() / valid["input_tokens"].sum()) if len(valid) else cfg_rate
    cost = tokens * eff_rate
    cost_cfg = tokens * cfg_rate + mean_out_tokens * rates.get("output", 0.0) / 1e6
    budget = context_window_tokens - max_tokens
    feasible = tokens <= budget
    pct = cs * 100.0 / total_chunks

    full_tokens = slope * total_chunks + intercept
    full_cost = full_tokens * eff_rate
    full_cost_cfg = full_tokens * cfg_rate + mean_out_tokens * rates.get("output", 0.0) / 1e6
    limit_chunks = (budget - intercept) / slope
    limit_pct = limit_chunks * 100.0 / total_chunks

    st = STYLES[layout]
    compact = bool(st["compact"])
    _apply_style(st)
    fig, (ax_t, ax_c) = plt.subplots(1, 2, figsize=st["figsize"], layout="constrained")
    _tight_layout(fig, st)
    okx = ok["chunk_count"].astype(float) * 100.0 / total_chunks

    for ax, ys, meas, ylabel, color in (
        (ax_t, tokens, ok["input_tokens"], "Prompt tokens" if compact else "Prompt Tokens per Query", COLOR_TTFT),
        (ax_c, cost, ok["cost_usd"], "Cost (USD)" if compact else "Projected Query Cost (USD)", COLOR_COST),
    ):
        ax.plot(pct[feasible], ys[feasible], color=color, linewidth=st["lw"], label="Fits")
        ax.plot(pct[~feasible], ys[~feasible], color=COLOR_FAIL, linewidth=st["lw"], linestyle="--", label="Exceeds window")
        ax.scatter(okx, meas, s=st["scatter"] * 3, color=color, edgecolor="black", linewidth=0.5, zorder=4, label="Measured")
        if ys is cost:
            ax.plot(
                pct, cost_cfg, color="#94a3b8", linewidth=st["lw"] * 0.8, linestyle=":",
                label=f"Config rate (\\${rates.get('input', 0.0):.2f}/M)",
            )
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_ylabel(ylabel)
        ax.grid(True, which="major", axis="both")
        ax.set_axisbelow(True)
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:g}"))
        ax.axvline(limit_pct, linestyle="--", color="#64748b", linewidth=st["lw"] * 0.7)
        ax.text(
            limit_pct * 1.12, 0.97, f"{context_window_tokens // 1000}k window" if compact else f"{context_window_tokens // 1000}k window ≈ {limit_pct:.2f}% of data",
            rotation=90, ha="left", va="top", fontsize=st["note"], color="#475569",
            style="italic", fontweight="bold", transform=ax.get_xaxis_transform(),
        )

    ax_t.axhline(context_window_tokens, linestyle=":", color=COLOR_FAIL, linewidth=st["lw"] * 0.8)
    ax_t.annotate(
        f"100%: {full_tokens / 1e6:.1f}M tok\n({full_tokens / context_window_tokens:.0f}× window)" if compact
        else f"100% of data: ~{full_tokens / 1e6:.1f}M tokens\n({full_tokens / context_window_tokens:.0f}x the window)",
        (100.0, full_tokens), xycoords="data", textcoords="axes fraction", xytext=(0.97, 0.05), ha="right",
        va="bottom", fontsize=st["note"], fontweight="bold",
    )
    ax_c.annotate(
        f"100%: \\${full_cost:,.2f}/query" if compact
        else f"100% of data: ~\\${full_cost:,.2f}/query (reported \\${eff_rate * 1e6:.2f}/M)\n(hypothetical, cannot be sent)",
        (100.0, full_cost), xycoords="data", textcoords="axes fraction", xytext=(0.97, 0.05), ha="right",
        va="bottom", fontsize=st["note"], fontweight="bold",
    )
    fig.supxlabel(f"Fraction of {dataset_label} Data (%)", fontsize=st["label"], fontweight="bold")
    _fig_legend(fig, (ax_t, ax_c), st, ncol=3 if compact else None)

    out_png = Path(output_dir) / f"{filename_prefix}.png"
    out_pdf = Path(output_dir) / f"{filename_prefix}.pdf"
    _save(fig, out_png, out_pdf, st)
    print(f"Extrapolation plot saved to {out_png}")
    print(
        f"Full dataset ~{full_tokens:,.0f} tokens ({full_tokens / context_window_tokens:.0f}x window), "
        f"~${full_cost:,.2f}/query at reported rate (~${full_cost_cfg:,.2f} at config rate); window reached at ~{limit_chunks:.0f} chunks ({limit_pct:.2f}%)."
    )
    plt.close(fig)


def plot_accuracy(
    trials: pd.DataFrame,
    summary: pd.DataFrame,
    xmap: Any,
    x_label: str,
    output_dir: str,
    filename_prefix: str,
    layout: str = "single",
    log_x: bool = True,
) -> None:
    """Plot absolute answer error vs context size (only if ground truth was tracked)."""
    ok = trials[trials["success"] & trials["abs_error"].notna()]
    if ok.empty:
        return
    s = summary[summary["abs_error_median"].notna()].sort_values("chunk_count")
    st = STYLES[layout]
    compact = bool(st["compact"])
    _apply_style(st)
    fig, ax = plt.subplots(figsize=(st["figsize"][0], st["figsize"][1]) if compact else (9, 6.5), layout="constrained")
    _tight_layout(fig, st)
    ax.scatter(xmap(ok["chunk_count"]), ok["abs_error"], s=st["scatter"], color="#7c3aed", alpha=0.4, linewidths=0, label="Per run")
    ax.plot(xmap(s["chunk_count"]), s["abs_error"], marker="o", color="#7c3aed", linewidth=st["lw"], markersize=st["ms"], label="Mean")
    if log_x:
        ax.set_xscale("log")
        lo, hi = ax.get_xlim()
        ticks = _nice_x_ticks(lo, hi, True, True, [], compact)
        ax.set_xticks(ticks)
        ax.set_xticklabels([_fmt_tick(t) for t in ticks])
        ax.xaxis.set_minor_locator(plt.NullLocator())
    ax.set_xlabel(x_label)
    ax.set_ylabel("|Error|" if compact else "|Answer - Ground Truth|")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    parsed = trials[trials["success"]]["parsed_answer"].notna().mean() if "parsed_answer" in trials.columns else float("nan")
    if not compact:
        ax.set_title("Answer error vs. context size", fontsize=16)
    if not math.isnan(parsed):
        ax.text(0.98, 0.95, f"Answers parsed: {parsed * 100:.0f}%", transform=ax.transAxes, ha="right", va="top", fontsize=st["note"])
    ax.legend(loc="upper left", frameon=False)
    out_png = Path(output_dir) / f"{filename_prefix}.png"
    out_pdf = Path(output_dir) / f"{filename_prefix}.pdf"
    _save(fig, out_png, out_pdf, st)
    print(f"Accuracy plot saved to {out_png}")
    plt.close(fig)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    """CLI entry point for the latency/cost vs. chunks experiment."""
    parser = argparse.ArgumentParser(
        description="Latency and cost vs. Chunks (direct OpenRouter streaming benchmark)"
    )
    parser.add_argument("--dataset", default="bus", help="Dataset name (default: bus)")
    parser.add_argument(
        "--data-path",
        default="/Users/kausar/Documents/backups/flash-fusion/data/bus",
        help=(
            "Path to dataset file or folder. For bus, passing the folder is supported "
            "and bus_data.csv is auto-selected."
        ),
    )
    parser.add_argument(
        "--chunks", nargs="+", type=int, default=DEFAULT_CHUNK_COUNTS,
        help=f"Chunk counts to test (default: {DEFAULT_CHUNK_COUNTS})",
    )
    parser.add_argument("--model", default=DEFAULT_BENCHMARK_MODEL, help=f"LLM model (default: {DEFAULT_BENCHMARK_MODEL})")
    parser.add_argument("--output-dir", default="flashfusion/viz/miniexp/results", help="Output directory")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Natural language query")
    parser.add_argument(
        "--chunk-token-target", type=int, default=DEFAULT_CHUNK_TOKEN_TARGET,
        help=f"Approx (estimated) tokens per chunk (default: {DEFAULT_CHUNK_TOKEN_TARGET})",
    )
    parser.add_argument(
        "--context-window-tokens", type=int, default=DEFAULT_CONTEXT_WINDOW_TOKENS,
        help=f"Model context window token budget (default: {DEFAULT_CONTEXT_WINDOW_TOKENS})",
    )
    parser.add_argument("--retries", type=int, default=0, help="Retries per trial on API errors (default: 0)")
    parser.add_argument("--runs", type=int, default=1, help="Repeats of every chunk count, interleaved (default: 1)")
    parser.add_argument(
        "--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
        help=f"Cap on generated tokens so TTLT excludes verbosity; 0 = unbounded (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--provider", nargs="+", default=None,
        help="Pin OpenRouter provider(s) in order, with fallbacks disabled (e.g. --provider Together)",
    )
    parser.add_argument("--shuffle", action="store_true", help="Randomise the (run, chunk) call order")
    parser.add_argument("--seed", type=int, default=0, help="Seed for --shuffle (default: 0)")
    parser.add_argument(
        "--skip-predicted-overflow", action="store_true",
        help="Do not call the API when calibrated tokens + max_tokens exceed the window",
    )
    parser.add_argument(
        "--lookup-provider", action="store_true",
        help="Best-effort lookup of the serving provider per call (adds ~1-3s per trial, not timed)",
    )
    parser.add_argument(
        "--truth-column", default=DEFAULT_TRUTH_COLUMN,
        help=f"Column whose mean is the ground truth for answer error ('' to disable; default: {DEFAULT_TRUTH_COLUMN})",
    )
    parser.add_argument("--csv-input", help="Path to an existing latency_vs_chunks.csv to plot (skips experiment)")
    parser.add_argument(
        "--avg-inputs", nargs="+",
        help="Paths to 2+ per-run CSVs; combines trials, summarises (mean/SD/median/IQR) and plots",
    )
    parser.add_argument("--max-chunks", type=int, default=None, help="Cap the plot x-axis at this many chunks")
    parser.add_argument("--dry-run", action="store_true", help="Compute chunk/context stats without API calls")
    parser.add_argument("--plot", action="store_true", help="Generate plots")
    parser.add_argument(
        "--ttft-only", action=argparse.BooleanOptionalAction, default=False,
        help="Plot only TTFT (omit TTLT line). Default: show both TTFT and TTLT.",
    )
    parser.add_argument(
        "--actual-token-ratio", type=float, default=1.9,
        help="Fallback actual/estimated token ratio when provider usage is absent (default: 1.9; ~2.02 measured)",
    )
    parser.add_argument("--total-rows", type=int, default=None, help="Total rows in the dataset (e.g. 650000 for ECG 100.csv)")
    parser.add_argument("--rows-per-chunk", type=int, default=None, help="Rows per chunk (ECG 100.csv @200 tokens: ~19)")
    parser.add_argument(
        "--total-chunks", type=int, default=None,
        help="Total chunks in the full dataset (auto-read from trial CSVs when available)",
    )
    parser.add_argument("--dataset-label", default="ECG", help="Label used on plot axes (default: ECG)")
    parser.add_argument(
        "--layout", choices=sorted(STYLES), default="single",
        help="Figure sizing: single = IEEE column (3.5in), double = 7.16in, large = slides (default: single)",
    )
    parser.add_argument("--xscale", choices=["log", "linear"], default="log", help="X-axis scale (default: log)")
    parser.add_argument("--yscale", choices=["log", "linear"], default="linear", help="Y-axis scale for latency/cost (default: linear)")

    args = parser.parse_args()
    plot_kwargs: dict[str, Any] = {
        "output_dir": args.output_dir,
        "chunk_token_target": args.chunk_token_target,
        "context_window_tokens": args.context_window_tokens,
        "ttft_only": args.ttft_only,
        "actual_token_ratio": args.actual_token_ratio,
        "max_chunks": args.max_chunks,
        "total_rows": args.total_rows,
        "rows_per_chunk": args.rows_per_chunk,
        "total_chunks": args.total_chunks,
        "dataset_label": args.dataset_label,
        "layout": args.layout,
        "xscale": args.xscale,
        "yscale": args.yscale,
    }

    if args.avg_inputs:
        print(f"Combining {len(args.avg_inputs)} run file(s): {args.avg_inputs}")
        trials, summary = average_runs(args.avg_inputs, actual_token_ratio=args.actual_token_ratio)
        os.makedirs(args.output_dir, exist_ok=True)
        out_trials = Path(args.output_dir) / "latency_trials.csv"
        out_csv = Path(args.output_dir) / "latency_vs_chunks_avg.csv"
        trials.to_csv(out_trials, index=False)
        summary.to_csv(out_csv, index=False)
        print(f"Combined trials saved to {out_trials}")
        print(f"Averaged results saved to {out_csv}")
        if args.plot:
            plot_results(trials, **plot_kwargs)
        return

    if args.csv_input:
        trials = pd.read_csv(args.csv_input)
        if args.plot:
            plot_results(trials, **plot_kwargs)
        else:
            print(f"Loaded {len(trials)} rows from {args.csv_input}")
            print("Pass --plot to generate plots.")
        return

    trials = run_experiment(
        dataset_name=args.dataset,
        data_path=args.data_path,
        chunk_counts=args.chunks,
        model=args.model,
        output_dir=args.output_dir,
        query=args.query,
        chunk_token_target=args.chunk_token_target,
        context_window_tokens=args.context_window_tokens,
        retries=args.retries,
        dry_run=args.dry_run,
        actual_token_ratio=args.actual_token_ratio,
        runs=args.runs,
        max_tokens=args.max_tokens,
        provider=args.provider,
        shuffle=args.shuffle,
        seed=args.seed,
        skip_predicted_overflow=args.skip_predicted_overflow,
        lookup_provider=args.lookup_provider,
        truth_column=args.truth_column or None,
    )

    if args.plot:
        plot_results(trials, **plot_kwargs)


if __name__ == "__main__":
    main()
