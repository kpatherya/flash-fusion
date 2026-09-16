#!/usr/bin/env python3
"""Shared loaders and aggregations for primary July26 visualizations.

This module centralizes reading and summarizing baseline metrics so plotting
scripts do not duplicate path handling or grouping logic.
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path
from typing import Iterable

import pandas as pd

QUERY_TYPE_BY_ID = {
    1: "Direct",
    2: "Direct",
    3: "Direct",
    4: "Direct",
    5: "Reasoning",
    6: "Reasoning",
    7: "Reasoning",
    8: "Reasoning",
    9: "Out-of-Scope",
    10: "Out-of-Scope",
    11: "Out-of-Scope",
    12: "Out-of-Scope",
    13: "Predictive",
    14: "Predictive",
    15: "Predictive",
    16: "Predictive",
    17: "Extra-Hard",
    18: "Extra-Hard",
    19: "Extra-Hard",
    20: "Extra-Hard",
}

QUERY_TYPE_ORDER = ["Direct", "Reasoning", "Predictive", "Out-of-Scope", "Extra-Hard"]
DATASET_ORDER = ["bus", "wisdm", "ecg"]
SEMANTIC_STAGE_ORDER = ["Grounding", "Validation", "Planning", "Execution"]
CACHE_BASELINE = "FLASH_FUSION_CACHE"
CACHE_HIT_BASELINE = "FLASH_FUSION_CACHE_HIT"
CACHE_MISS_BASELINE = "FLASH_FUSION_CACHE_MISS"
CACHE_BASELINE_VARIANTS = [CACHE_HIT_BASELINE, CACHE_MISS_BASELINE]
BASELINE_ORDER = [
    "FLASH_FUSION",
    "FF_NO_PRUNING",
    "FF_NO_PLANNING",
    CACHE_BASELINE,
    *CACHE_BASELINE_VARIANTS,
    "AUTOIOT_PAPER",
    "REACT_ONLY",
    "HARGPT_PAPER",
    "LLMSENSE_PAPER",
]

BASELINE_LABELS = {
    "FLASH_FUSION": "Flash-Fusion",
    "FF_NO_PRUNING": "FF no pruning",
    "FF_NO_PLANNING": "FF no planning",
    CACHE_BASELINE: "Flash-Fusion",
    CACHE_HIT_BASELINE: "FF-cache hit",
    CACHE_MISS_BASELINE: "FF-cache miss",
    "AUTOIOT_PAPER": "AutoIOT",
    "REACT_ONLY": "ReAct",
    "HARGPT_PAPER": "HARGPT",
    "LLMSENSE_PAPER": "LLMSense",
}

BASELINE_COLORS = {
    "FLASH_FUSION": "#1b9e77",
    "FF_NO_PRUNING": "#2f855a",
    "FF_NO_PLANNING": "#14532d",
    CACHE_BASELINE: "#0f4c81",
    CACHE_HIT_BASELINE: "#2563eb",
    CACHE_MISS_BASELINE: "#94a3b8",
    "AUTOIOT_PAPER": "#64748b",
    "REACT_ONLY": "#f59e0b",
    "HARGPT_PAPER": "#ef4444",
    "LLMSENSE_PAPER": "#8b5cf6",
}

# was "//"
BASELINE_HATCHES = {
    "REACT_ONLY": "",
}

DATASET_LABELS = {
    "bus": "Bus",
    "wisdm": "WISDM",
    "ecg": "ECG",
}


def normalize_baseline(value: object) -> str:
    return str(value).strip().upper()


def display_baseline(code: str) -> str:
    return BASELINE_LABELS.get(code, code)


def expand_baselines(baselines: Iterable[str]) -> list[str]:
    """Normalize and de-duplicate explicitly requested chart baselines."""
    expanded: list[str] = []
    for baseline in baselines:
        normalized = normalize_baseline(baseline)
        if normalized not in expanded:
            expanded.append(normalized)
    return expanded


def split_cache_baseline_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Retain averaged FF-cache rows and add hit/miss outcome-specific copies."""
    out = df.copy()
    if "baseline" not in out.columns:
        return out
    out["baseline"] = out["baseline"].map(normalize_baseline)
    cache_rows = out["baseline"] == CACHE_BASELINE
    if not cache_rows.any():
        return out

    variants = out.loc[cache_rows].copy()
    if "cache_outcome" in variants.columns:
        hits = variants["cache_outcome"].astype(str).str.strip().str.lower().isin({"hit", "hit_rejected"})
    else:
        plan_source = variants.get("plan_source", pd.Series("", index=variants.index)).fillna("").astype(str)
        execution_path = variants.get("execution_path", pd.Series("", index=variants.index)).fillna("").astype(str)
        hits = (
            execution_path.eq("typed_operator_cache")
            | plan_source.str.startswith("exact_query_cache_")
            | plan_source.str.startswith("semantic_cache_")
        )
    variants.loc[hits, "baseline"] = CACHE_HIT_BASELINE
    variants.loc[~hits, "baseline"] = CACHE_MISS_BASELINE
    return pd.concat([out, variants], ignore_index=True)


def _canonical_dataset_name(raw: str) -> str:
    raw_norm = raw.strip().lower()
    if raw_norm == "mit_ecg":
        return "ecg"
    return raw_norm


def metrics_path(results_root: Path, baseline: str, dataset: str, run_dir: str = "july26_full") -> Path:
    dataset_dir = "mit_ecg" if dataset == "ecg" else dataset
    return results_root / baseline / dataset_dir / run_dir / "metrics.csv"


def load_metrics_for_baseline_dataset(
    results_root: Path,
    baseline: str,
    dataset: str,
    run_dir: str = "july26_full",
) -> pd.DataFrame:
    path = metrics_path(results_root, baseline, dataset, run_dir=run_dir)
    if not path.exists():
        raise FileNotFoundError(f"Missing metrics file: {path}")

    df = pd.read_csv(path)
    required = {
        "run_id",
        "baseline",
        "query_id",
        "gt_score",
        "latency_s",
        "cost_usd",
        "input_tokens",
        "output_tokens",
        "guardrail_latency_s",
        "agent_latency_s",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{path} missing required columns: {missing}")

    out = df.copy()
    out["baseline"] = out["baseline"].map(normalize_baseline)
    out = split_cache_baseline_rows(out)
    out["dataset"] = _canonical_dataset_name(dataset)
    out["query_id"] = pd.to_numeric(out["query_id"], errors="coerce").astype("Int64")
    out["run_id"] = pd.to_numeric(out["run_id"], errors="coerce").astype("Int64")
    out["gt_score"] = pd.to_numeric(out["gt_score"], errors="coerce")
    out["accuracy_percent"] = out["gt_score"] * 100.0

    numeric_cols = [
        "latency_s",
        "cost_usd",
        "input_tokens",
        "output_tokens",
        "guardrail_latency_s",
        "agent_latency_s",
    ]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    if out[["run_id", "query_id", "accuracy_percent"] + numeric_cols].isna().any().any():
        raise ValueError(f"{path} contains invalid numeric values")

    unknown = sorted(
        [int(v) for v in out.loc[~out["query_id"].isin(QUERY_TYPE_BY_ID), "query_id"].unique().tolist()]
    )
    if unknown:
        warnings.warn(
            f"{path}: query_id values not in QUERY_TYPE_BY_ID (will be labelled 'Unknown'): {unknown}",
            stacklevel=2,
        )
        for uid in unknown:
            QUERY_TYPE_BY_ID[uid] = "Unknown"

    out["query_type"] = out["query_id"].map(QUERY_TYPE_BY_ID)
    return out


def load_metrics_for_baseline_dataset_safe(
    results_root: Path,
    baseline: str,
    dataset: str,
    run_dir: str = "july26_full",
) -> pd.DataFrame | None:
    """Load metrics for baseline/dataset, returning None if file doesn't exist."""
    try:
        return load_metrics_for_baseline_dataset(results_root, baseline, dataset, run_dir=run_dir)
    except FileNotFoundError:
        return None


def load_metrics_from_dataset_root(
    results_root: Path,
    baseline: str,
    dataset: str,
) -> pd.DataFrame | None:
    """Load direct or one-level nested dataset metrics for one baseline."""
    dataset_dir = "mit_ecg" if dataset == "ecg" else dataset
    dataset_root = results_root / dataset_dir
    direct_path = dataset_root / "metrics.csv"
    nested_paths = sorted(dataset_root.glob("*/metrics.csv"))
    paths = [direct_path] if direct_path.exists() else nested_paths
    if not paths:
        return None

    if len(paths) > 1:
        raise ValueError(
            f"Multiple metrics files found under {dataset_root}: {paths}. "
            "Specify a single run directory."
        )
    path = paths[0]

    df = pd.read_csv(path)
    df["baseline"] = df["baseline"].map(normalize_baseline)
    df = df[df["baseline"] == normalize_baseline(baseline)].copy()
    df = split_cache_baseline_rows(df)
    if df.empty:
        return None

    required = {"query_id", "gt_score", "latency_s", "cost_usd", "input_tokens", "output_tokens"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{path} missing required columns: {missing}")

    df["dataset"] = _canonical_dataset_name(dataset)
    df["query_id"] = pd.to_numeric(df["query_id"], errors="coerce").astype("Int64")
    df["run_id"] = pd.to_numeric(df["run_id"], errors="coerce").astype("Int64")
    df["gt_score"] = pd.to_numeric(df["gt_score"], errors="coerce")
    df["accuracy_percent"] = df["gt_score"] * 100.0
    numeric_cols = [
        "latency_s", "cost_usd", "input_tokens", "output_tokens",
        "guardrail_latency_s", "agent_latency_s",
    ]
    for col in numeric_cols:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["s1_latency_s", "s2_latency_s", "s3_latency_s"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if df[["run_id", "query_id", "accuracy_percent"] + numeric_cols].isna().any().any():
        raise ValueError(f"{path} contains invalid numeric values")
    df["query_type"] = df["query_id"].map(QUERY_TYPE_BY_ID)
    return df


def load_ffpaper_metrics(
    ffpaper_run_root: Path,
    baseline: str,
    dataset: str,
) -> pd.DataFrame | None:
    """Load metrics from performance_ffpaper data layout.

    Expects: ffpaper_run_root/<dataset>/benchmark/metrics.csv
    Fills in missing stage-latency columns (guardrail/agent) with 0.0
    so the resulting DataFrame is compatible with the current schema.
    Legacy s1/s2/s3 columns are kept optional for old metrics.csv files.
    """
    dataset_dir = "mit_ecg" if dataset == "ecg" else dataset
    path = ffpaper_run_root / dataset_dir / "benchmark" / "metrics.csv"
    if not path.exists():
        return None

    df = pd.read_csv(path)
    # Filter to the requested baseline
    df["baseline"] = df["baseline"].map(normalize_baseline)
    df = df[df["baseline"] == normalize_baseline(baseline)].copy()
    if df.empty:
        return None

    # Ensure required columns exist; fill missing stage-latency columns with 0.
    # s1/s2/s3 are legacy AutoIOT stage keys kept optional for old metrics.csv files.
    stage_cols = ["guardrail_latency_s", "agent_latency_s"]
    for col in stage_cols:
        if col not in df.columns:
            df[col] = 0.0
    for col in ["s1_latency_s", "s2_latency_s", "s3_latency_s"]:
        if col not in df.columns:
            df[col] = 0.0

    df["dataset"] = _canonical_dataset_name(dataset)
    df["query_id"] = pd.to_numeric(df["query_id"], errors="coerce").astype("Int64")
    df["run_id"] = pd.to_numeric(df["run_id"], errors="coerce").astype("Int64")
    df["gt_score"] = pd.to_numeric(df["gt_score"], errors="coerce")
    df["accuracy_percent"] = df["gt_score"] * 100.0

    numeric_cols = ["latency_s", "cost_usd", "input_tokens", "output_tokens"] + stage_cols
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    unknown = sorted(
        [int(v) for v in df.loc[~df["query_id"].isin(QUERY_TYPE_BY_ID), "query_id"].unique().tolist()]
    )
    if unknown:
        warnings.warn(
            f"{path}: query_id values not in QUERY_TYPE_BY_ID (will be labelled 'Unknown'): {unknown}",
            stacklevel=2,
        )
        for uid in unknown:
            QUERY_TYPE_BY_ID[uid] = "Unknown"

    df["query_type"] = df["query_id"].map(QUERY_TYPE_BY_ID)
    return df


def load_ffpaper_per_baseline_metrics(
    ffpaper_run_root: Path,
    baseline: str,
    dataset: str,
) -> pd.DataFrame | None:
    """Load metrics from performance_ffpaper per_baseline layout.

    Expects: ffpaper_run_root/<dataset>/per_baseline/<baseline>/metrics.csv
    """
    dataset_dir = "mit_ecg" if dataset == "ecg" else dataset
    path = ffpaper_run_root / dataset_dir / "per_baseline" / baseline / "metrics.csv"
    if not path.exists():
        return None

    df = pd.read_csv(path)
    df["baseline"] = df["baseline"].map(normalize_baseline)
    df = df[df["baseline"] == normalize_baseline(baseline)].copy()
    if df.empty:
        return None

    stage_cols = ["guardrail_latency_s", "agent_latency_s"]
    for col in stage_cols:
        if col not in df.columns:
            df[col] = 0.0
    for col in ["s1_latency_s", "s2_latency_s", "s3_latency_s"]:
        if col not in df.columns:
            df[col] = 0.0

    df["dataset"] = _canonical_dataset_name(dataset)
    df["query_id"] = pd.to_numeric(df["query_id"], errors="coerce").astype("Int64")
    df["run_id"] = pd.to_numeric(df["run_id"], errors="coerce").astype("Int64")
    df["gt_score"] = pd.to_numeric(df["gt_score"], errors="coerce")
    df["accuracy_percent"] = df["gt_score"] * 100.0

    numeric_cols = ["latency_s", "cost_usd", "input_tokens", "output_tokens"] + stage_cols
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    unknown = sorted(
        [int(v) for v in df.loc[~df["query_id"].isin(QUERY_TYPE_BY_ID), "query_id"].unique().tolist()]
    )
    if unknown:
        warnings.warn(
            f"{path}: query_id values not in QUERY_TYPE_BY_ID (will be labelled 'Unknown'): {unknown}",
            stacklevel=2,
        )
        for uid in unknown:
            QUERY_TYPE_BY_ID[uid] = "Unknown"

    df["query_type"] = df["query_id"].map(QUERY_TYPE_BY_ID)
    return df


def load_ffpaper_flash_fusion(
    ffpaper_run_root: Path,
    ecg_ff_root: Path,
) -> pd.DataFrame:
    """Load Flash-Fusion data from performance_ffpaper sources for all three datasets.

    Source layout per dataset:
      bus  : ffpaper_run_root/bus/per_baseline/FLASH_FUSION/metrics.csv
      wisdm: ffpaper_run_root/wisdm/benchmark/metrics.csv  (filter to FLASH_FUSION)
      ecg  : ecg_ff_root/benchmark/metrics.csv             (filter to FLASH_FUSION)
    """
    parts: list[pd.DataFrame] = []

    bus = load_ffpaper_per_baseline_metrics(ffpaper_run_root, "FLASH_FUSION", "bus")
    if bus is not None:
        parts.append(bus)

    wisdm = load_ffpaper_metrics(ffpaper_run_root, "FLASH_FUSION", "wisdm")
    if wisdm is not None:
        parts.append(wisdm)

    ecg = load_ffpaper_metrics(ecg_ff_root, "FLASH_FUSION", "ecg")
    if ecg is None:
        # ecg_ff_root uses benchmark/metrics.csv directly (no dataset subdirectory)
        ecg_path = ecg_ff_root / "benchmark" / "metrics.csv"
        if ecg_path.exists():
            tmp = pd.read_csv(ecg_path)
            tmp["baseline"] = tmp["baseline"].map(normalize_baseline)
            tmp = tmp[tmp["baseline"] == "FLASH_FUSION"].copy()
            if not tmp.empty:
                stage_cols = ["guardrail_latency_s", "agent_latency_s"]
                for col in stage_cols:
                    if col not in tmp.columns:
                        tmp[col] = 0.0
                for col in ["s1_latency_s", "s2_latency_s", "s3_latency_s"]:
                    if col not in tmp.columns:
                        tmp[col] = 0.0
                tmp["dataset"] = "ecg"
                tmp["query_id"] = pd.to_numeric(tmp["query_id"], errors="coerce").astype("Int64")
                tmp["run_id"] = pd.to_numeric(tmp["run_id"], errors="coerce").astype("Int64")
                tmp["gt_score"] = pd.to_numeric(tmp["gt_score"], errors="coerce")
                tmp["accuracy_percent"] = tmp["gt_score"] * 100.0
                numeric_cols = ["latency_s", "cost_usd", "input_tokens", "output_tokens"] + stage_cols
                for col in numeric_cols:
                    tmp[col] = pd.to_numeric(tmp[col], errors="coerce").fillna(0.0)
                tmp["query_type"] = tmp["query_id"].map(QUERY_TYPE_BY_ID)
                parts.append(tmp)
    else:
        parts.append(ecg)

    if not parts:
        raise ValueError("Could not load Flash-Fusion data from any ffpaper source")
    return pd.concat(parts, ignore_index=True)


def _replace_baseline_rows(
    base_df: pd.DataFrame,
    replacement_df: pd.DataFrame,
    baseline_code: str,
) -> pd.DataFrame:
    """Replace all rows for a baseline in base_df with rows from replacement_df."""
    if replacement_df.empty or not (replacement_df["baseline"] == baseline_code).any():
        return base_df
    base_rows = base_df[base_df["baseline"] != baseline_code].copy()
    repl_rows = replacement_df[replacement_df["baseline"] == baseline_code].copy()
    return pd.concat([base_rows, repl_rows], ignore_index=True)


def load_all_metrics(
    results_root: Path,
    baselines: Iterable[str] = BASELINE_ORDER,
    datasets: Iterable[str] = DATASET_ORDER,
    run_dir: str = "july26_full",
    fallback_roots: dict[str, Path] | None = None,
    ffpaper_run_root: Path | None = None,
) -> pd.DataFrame:
    """Load metrics from results_root with optional fallbacks.

    Resolution order per (baseline, dataset):
      1. Primary results_root / run_dir layout
      2. fallback_roots[baseline] if provided (same july26_full layout)
      3. ffpaper_run_root (performance_ffpaper layout: <dataset>/benchmark/metrics.csv)
    """
    parts: list[pd.DataFrame] = []
    fallback_roots = fallback_roots or {}

    requested_baselines = expand_baselines(baselines)
    source_baselines = []
    for baseline in requested_baselines:
        source = CACHE_BASELINE if baseline in CACHE_BASELINE_VARIANTS else baseline
        if source not in source_baselines:
            source_baselines.append(source)

    for baseline in source_baselines:
        for dataset in datasets:
            df = load_metrics_for_baseline_dataset_safe(results_root, baseline, dataset, run_dir=run_dir)

            if df is None:
                df = load_metrics_from_dataset_root(results_root, baseline, dataset)

            if df is None and baseline in fallback_roots:
                df = load_metrics_for_baseline_dataset_safe(fallback_roots[baseline], baseline, dataset, run_dir="july26_full")

            if df is None and ffpaper_run_root is not None:
                df = load_ffpaper_metrics(ffpaper_run_root, baseline, dataset)

            if df is not None:
                parts.append(df)

    if not parts:
        raise ValueError(f"No metrics found in {results_root} or fallback roots")

    out = pd.concat(parts, ignore_index=True)
    out = split_cache_baseline_rows(out)
    out = out[out["baseline"].isin(requested_baselines)].copy()
    out["baseline"] = pd.Categorical(out["baseline"], categories=list(BASELINE_ORDER), ordered=True)
    out["dataset"] = pd.Categorical(out["dataset"], categories=list(DATASET_ORDER), ordered=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    return out


def load_metrics_from_dir(
    run_dir: Path,
    label: str,
    baselines: Iterable[str] = BASELINE_ORDER,
    query_type_filter: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Load a flat ``metrics.csv`` from *run_dir* (benchmark output layout).

    Expects ``run_dir/metrics.csv`` or ``run_dir/run_*/metrics.csv`` (multi-run).
    Attaches a ``label`` column (e.g. "before" / "after") for before/after comparisons.
    query_type_filter: if provided, keep only rows whose query_type is in this list.
    """
    import glob

    # Prefer a direct metrics.csv; fall back to run_*/metrics.csv for multi-run dirs.
    direct = run_dir / "metrics.csv"
    paths = [direct] if direct.exists() else sorted(run_dir.glob("run_*/metrics.csv"))
    if not paths:
        raise FileNotFoundError(f"No metrics.csv found under {run_dir}")

    parts: list[pd.DataFrame] = []
    for path in paths:
        df = pd.read_csv(path)
        df["baseline"] = df["baseline"].map(normalize_baseline)
        df = df[df["baseline"].isin(list(baselines))].copy()
        if df.empty:
            continue
        df["dataset"] = df["dataset"].map(_canonical_dataset_name) if "dataset" in df.columns else "unknown"
        df["query_id"] = pd.to_numeric(df["query_id"], errors="coerce").astype("Int64")
        df["gt_score"] = pd.to_numeric(df["gt_score"], errors="coerce")
        df["accuracy_percent"] = df["gt_score"] * 100.0
        for col in ["latency_s", "cost_usd", "guardrail_latency_s", "agent_latency_s",
                    "input_tokens", "output_tokens"]:
            if col not in df.columns:
                df[col] = 0.0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        for col in ["s1_latency_s", "s2_latency_s", "s3_latency_s"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        unknown = sorted(
            [int(v) for v in df.loc[~df["query_id"].isin(QUERY_TYPE_BY_ID), "query_id"].unique().tolist()]
        )
        if unknown:
            warnings.warn(
                f"{path}: unmapped query_id values labelled 'Unknown': {unknown}",
                stacklevel=2,
            )
            for uid in unknown:
                QUERY_TYPE_BY_ID[uid] = "Unknown"
        df["query_type"] = df["query_id"].map(QUERY_TYPE_BY_ID)
        parts.append(df)

    if not parts:
        raise ValueError(f"No usable rows found under {run_dir}")

    out = pd.concat(parts, ignore_index=True)
    if query_type_filter is not None:
        out = out[out["query_type"].isin(list(query_type_filter))].copy()
    out["label"] = label
    out["baseline"] = pd.Categorical(out["baseline"], categories=list(BASELINE_ORDER), ordered=True)
    out["dataset"] = pd.Categorical(out["dataset"], categories=list(DATASET_ORDER), ordered=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    return out


def aggregate_accuracy_before_after(
    before_df: pd.DataFrame,
    after_df: pd.DataFrame,
    group_col: str = "query_type",
    baselines: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Aggregate mean accuracy grouped by baseline + group_col for before/after DataFrames.

    Returns a long-form DataFrame with columns:
      label, baseline, <group_col>, mean, std, n
    Ready to pass directly to ``plot_before_after``.
    """
    baselines = list(baselines) if baselines is not None else list(BASELINE_ORDER)
    parts = []
    for label, df in (("before", before_df), ("after", after_df)):
        df = df[df["baseline"].isin(baselines)].copy()
        agg = (
            df.groupby(["baseline", group_col], as_index=False, observed=True)
            .agg(
                mean=("accuracy_percent", "mean"),
                std=("accuracy_percent", "std"),
                n=("accuracy_percent", "count"),
            )
        )
        agg["std"] = agg["std"].fillna(0.0)
        agg["label"] = label
        parts.append(agg)
    out = pd.concat(parts, ignore_index=True)
    out["baseline"] = pd.Categorical(out["baseline"], categories=baselines, ordered=True)
    return out


def aggregate_accuracy_by_dataset(df: pd.DataFrame) -> pd.DataFrame:
    per_run = (
        df.groupby(["baseline", "dataset", "run_id"], as_index=False, observed=True)
        .agg(accuracy_percent=("accuracy_percent", "mean"))
        .copy()
    )
    out = (
        per_run.groupby(["baseline", "dataset"], as_index=False, observed=True)
        .agg(
            mean=("accuracy_percent", "mean"),
            std=("accuracy_percent", "std"),
            n_runs=("run_id", "nunique"),
        )
        .copy()
    )
    out["std"] = out["std"].fillna(0.0)
    out["baseline"] = pd.Categorical(out["baseline"], categories=list(BASELINE_ORDER), ordered=True)
    out["dataset"] = pd.Categorical(out["dataset"], categories=list(DATASET_ORDER), ordered=True)
    return out.sort_values(["dataset", "baseline"]).reset_index(drop=True)


def aggregate_cost_by_dataset(df: pd.DataFrame, scale: float = 1e5) -> pd.DataFrame:
    per_run = (
        df.groupby(["baseline", "dataset", "run_id"], as_index=False, observed=True)
        .agg(cost_usd=("cost_usd", "mean"))
        .copy()
    )
    out = (
        per_run.groupby(["baseline", "dataset"], as_index=False, observed=True)
        .agg(
            mean=("cost_usd", "mean"),
            std=("cost_usd", "std"),
            n_runs=("run_id", "nunique"),
        )
        .copy()
    )
    out["std"] = out["std"].fillna(0.0)
    out["mean"] = out["mean"] * scale
    out["std"] = out["std"] * scale
    out["baseline"] = pd.Categorical(out["baseline"], categories=list(BASELINE_ORDER), ordered=True)
    out["dataset"] = pd.Categorical(out["dataset"], categories=list(DATASET_ORDER), ordered=True)
    return out.sort_values(["dataset", "baseline"]).reset_index(drop=True)


def aggregate_cost_by_query_type(df: pd.DataFrame, scale: float = 1e5) -> pd.DataFrame:
    per_run_dataset = (
        df.groupby(["baseline", "dataset", "run_id", "query_type"], as_index=False, observed=True)
        .agg(cost_usd=("cost_usd", "mean"))
        .copy()
    )
    out = (
        per_run_dataset.groupby(["baseline", "query_type"], as_index=False, observed=True)
        .agg(
            mean=("cost_usd", "mean"),
            std=("cost_usd", "std"),
            n=("cost_usd", "count"),
        )
        .copy()
    )
    out["std"] = out["std"].fillna(0.0)
    out["mean"] = out["mean"] * scale
    out["std"] = out["std"] * scale
    out["baseline"] = pd.Categorical(out["baseline"], categories=list(BASELINE_ORDER), ordered=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    return out.sort_values(["query_type", "baseline"]).reset_index(drop=True)


def aggregate_cache_hit_rate_by_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate FF-cache hit/miss percentages by dataset.

    Percentages are computed per (dataset, run_id) from cache-hit/cache-miss
    variant rows, then averaged across runs.
    """
    cache_rows = df[df["baseline"].isin(CACHE_BASELINE_VARIANTS)].copy()
    if cache_rows.empty:
        return pd.DataFrame(columns=["dataset", "outcome", "mean", "std", "n_runs"])

    per_run = (
        cache_rows.groupby(["dataset", "run_id", "baseline"], as_index=False, observed=True)
        .size()
        .pivot_table(
            index=["dataset", "run_id"],
            columns="baseline",
            values="size",
            fill_value=0,
            observed=True,
        )
        .reset_index()
    )

    per_run[CACHE_HIT_BASELINE] = per_run.get(CACHE_HIT_BASELINE, 0)
    per_run[CACHE_MISS_BASELINE] = per_run.get(CACHE_MISS_BASELINE, 0)
    denom = per_run[CACHE_HIT_BASELINE] + per_run[CACHE_MISS_BASELINE]
    nonzero = denom > 0
    per_run = per_run.loc[nonzero].copy()
    if per_run.empty:
        return pd.DataFrame(columns=["dataset", "outcome", "mean", "std", "n_runs"])

    per_run["hit_percent"] = (per_run[CACHE_HIT_BASELINE] / denom.loc[nonzero]) * 100.0
    per_run["miss_percent"] = 100.0 - per_run["hit_percent"]

    hit = (
        per_run.groupby("dataset", as_index=False, observed=True)
        .agg(mean=("hit_percent", "mean"), std=("hit_percent", "std"), n_runs=("run_id", "nunique"))
        .copy()
    )
    hit["outcome"] = "Hit"

    miss = (
        per_run.groupby("dataset", as_index=False, observed=True)
        .agg(mean=("miss_percent", "mean"), std=("miss_percent", "std"), n_runs=("run_id", "nunique"))
        .copy()
    )
    miss["outcome"] = "Miss"

    out = pd.concat([hit, miss], ignore_index=True)
    out["std"] = out["std"].fillna(0.0)
    out["dataset"] = pd.Categorical(out["dataset"], categories=list(DATASET_ORDER), ordered=True)
    out["outcome"] = pd.Categorical(out["outcome"], categories=["Hit", "Miss"], ordered=True)
    return out.sort_values(["dataset", "outcome"]).reset_index(drop=True)


def aggregate_cache_hit_rate_by_query_type(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate FF-cache hit/miss percentages by query type.

    Percentages are computed per (dataset, run_id, query_type) from cache
    variant rows, then averaged across dataset-runs.
    """
    cache_rows = df[df["baseline"].isin(CACHE_BASELINE_VARIANTS)].copy()
    if cache_rows.empty:
        return pd.DataFrame(columns=["query_type", "outcome", "mean", "std", "n"])

    per_run = (
        cache_rows.groupby(["dataset", "run_id", "query_type", "baseline"], as_index=False, observed=True)
        .size()
        .pivot_table(
            index=["dataset", "run_id", "query_type"],
            columns="baseline",
            values="size",
            fill_value=0,
            observed=True,
        )
        .reset_index()
    )

    per_run[CACHE_HIT_BASELINE] = per_run.get(CACHE_HIT_BASELINE, 0)
    per_run[CACHE_MISS_BASELINE] = per_run.get(CACHE_MISS_BASELINE, 0)
    denom = per_run[CACHE_HIT_BASELINE] + per_run[CACHE_MISS_BASELINE]
    nonzero = denom > 0
    per_run = per_run.loc[nonzero].copy()
    if per_run.empty:
        return pd.DataFrame(columns=["query_type", "outcome", "mean", "std", "n"])

    per_run["hit_percent"] = (per_run[CACHE_HIT_BASELINE] / denom.loc[nonzero]) * 100.0
    per_run["miss_percent"] = 100.0 - per_run["hit_percent"]

    hit = (
        per_run.groupby("query_type", as_index=False, observed=True)
        .agg(mean=("hit_percent", "mean"), std=("hit_percent", "std"), n=("hit_percent", "count"))
        .copy()
    )
    hit["outcome"] = "Hit"

    miss = (
        per_run.groupby("query_type", as_index=False, observed=True)
        .agg(mean=("miss_percent", "mean"), std=("miss_percent", "std"), n=("miss_percent", "count"))
        .copy()
    )
    miss["outcome"] = "Miss"

    out = pd.concat([hit, miss], ignore_index=True)
    out["std"] = out["std"].fillna(0.0)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    out["outcome"] = pd.Categorical(out["outcome"], categories=["Hit", "Miss"], ordered=True)
    return out.sort_values(["query_type", "outcome"]).reset_index(drop=True)


def aggregate_accuracy_by_query_type(df: pd.DataFrame) -> pd.DataFrame:
    per_run_dataset = (
        df.groupby(["baseline", "dataset", "run_id", "query_type"], as_index=False, observed=True)
        .agg(accuracy_percent=("accuracy_percent", "mean"))
        .copy()
    )
    out = (
        per_run_dataset.groupby(["baseline", "query_type"], as_index=False, observed=True)
        .agg(
            mean=("accuracy_percent", "mean"),
            std=("accuracy_percent", "std"),
            n=("accuracy_percent", "count"),
        )
        .copy()
    )
    out["std"] = out["std"].fillna(0.0)
    out["baseline"] = pd.Categorical(out["baseline"], categories=list(BASELINE_ORDER), ordered=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    return out.sort_values(["query_type", "baseline"]).reset_index(drop=True)


def aggregate_accuracy_by_dataset_query_type(
    df: pd.DataFrame,
    baselines: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Aggregate accuracy by baseline, dataset, and query type.

    Accuracy is averaged per query type within each run first, then summarized
    across runs. This prevents repeated query rows from dominating the result
    and keeps the summary consistent with the other accuracy aggregations.
    """
    baseline_order = list(baselines) if baselines is not None else list(BASELINE_ORDER)
    subset = df[df["baseline"].isin(baseline_order)].copy()
    per_run = (
        subset.groupby(
            ["baseline", "dataset", "run_id", "query_type"],
            as_index=False,
            observed=True,
        )
        .agg(accuracy_percent=("accuracy_percent", "mean"))
        .copy()
    )
    out = (
        per_run.groupby(["baseline", "dataset", "query_type"], as_index=False, observed=True)
        .agg(
            mean=("accuracy_percent", "mean"),
            std=("accuracy_percent", "std"),
            n_runs=("run_id", "nunique"),
        )
        .copy()
    )
    out["std"] = out["std"].fillna(0.0)
    out["baseline"] = pd.Categorical(out["baseline"], categories=baseline_order, ordered=True)
    out["dataset"] = pd.Categorical(out["dataset"], categories=list(DATASET_ORDER), ordered=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    return out.sort_values(["dataset", "query_type", "baseline"]).reset_index(drop=True)


def aggregate_flash_fusion_stage_latency_by_query_type(df: pd.DataFrame) -> pd.DataFrame:
    sem = _semantic_stage_frame(df)
    ff = sem[sem["baseline"] == "FLASH_FUSION"].copy()
    stage_cols = [
        "grounding_s",
        "validation_s",
        "planning_s",
        "execution_s",
    ]

    per_run = (
        ff.groupby(["dataset", "run_id", "query_type"], as_index=False, observed=True)[stage_cols]
        .mean(numeric_only=True)
        .copy()
    )
    per_run["total_latency_s"] = per_run[stage_cols].sum(axis=1)

    agg_parts = []
    for col in stage_cols + ["total_latency_s"]:
        part = (
            per_run.groupby("query_type", as_index=False, observed=True)
            .agg(mean=(col, "mean"), std=(col, "std"), n_runs=(col, "count"))
            .copy()
        )
        part["metric"] = col
        part["std"] = part["std"].fillna(0.0)
        agg_parts.append(part)

    out = pd.concat(agg_parts, ignore_index=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    return out.sort_values(["query_type", "metric"]).reset_index(drop=True)


def _semantic_stage_frame(df: pd.DataFrame) -> pd.DataFrame:
    base_cols = [
        "baseline",
        "dataset",
        "run_id",
        "query_type",
        "latency_s",
        "guardrail_latency_s",
        "agent_latency_s",
    ]
    sem = df[base_cols].copy()
    for col in (
        "s1_latency_s",
        "s2_latency_s",
        "s3_latency_s",
        "cache_grounding_latency_s",
        "typed_exec_latency_s",
        "agent_latency_ms",
    ):
        if col in df.columns:
            sem[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        else:
            sem[col] = 0.0

    sem["grounding_s"] = 0.0
    sem["validation_s"] = 0.0
    sem["planning_s"] = 0.0
    sem["execution_s"] = 0.0
    sem["is_estimated"] = False

    # Flash-Fusion's typed-operator path collapses S1/S2/S3 to 0 and puts all
    # grounding/validation/planning work inside guardrail_latency_s, so the
    # semantic split has to be estimated from that single column instead.
    # This applies to both FLASH_FUSION and FLASH_FUSION_CACHE since they use
    # the same underlying architecture. Cache grounding is native telemetry;
    # any remaining query-scoped overhead is spread uniformly so the semantic
    # stages reconcile with latency_s, except that cache hits have no planning
    # stage and must not receive a planning allocation.
    ff_mask = sem["baseline"].isin([
        "FLASH_FUSION",
        CACHE_BASELINE,
        *CACHE_BASELINE_VARIANTS,
    ])
    ff_guardrail = sem.loc[ff_mask, "guardrail_latency_s"]
    ff_cache_grounding = sem.loc[ff_mask, "cache_grounding_latency_s"]
    sem.loc[ff_mask, "grounding_s"] = ff_guardrail * 0.10 + ff_cache_grounding
    sem.loc[ff_mask, "validation_s"] = ff_guardrail * 0.10
    sem.loc[ff_mask, "planning_s"] = ff_guardrail * 0.80

    ff_typed_exec = sem.loc[ff_mask, "typed_exec_latency_s"]
    ff_agent_ms_as_s = sem.loc[ff_mask, "agent_latency_ms"] / 1000.0
    sem.loc[ff_mask, "execution_s"] = ff_typed_exec.where(ff_typed_exec != 0.0, ff_agent_ms_as_s)

    ff_semantic_total = sem.loc[ff_mask, [
        "grounding_s",
        "validation_s",
        "planning_s",
        "execution_s",
    ]].sum(axis=1)
    ff_residual_per_stage = (
        sem.loc[ff_mask, "latency_s"] - ff_semantic_total
    ) / 4.0
    for stage in ("grounding_s", "validation_s", "planning_s", "execution_s"):
        sem.loc[ff_mask, stage] += ff_residual_per_stage

    # Cache hits reuse a validated cached skeleton and do not invoke the
    # planner. Do not turn the residual display allocation into planning time.
    cache_hit_mask = sem["baseline"] == CACHE_HIT_BASELINE
    sem.loc[cache_hit_mask, "planning_s"] = 0.0

    # ReAct has no grounding/planning phase; treat 10% of its end-to-end
    # latency as validation and the rest as execution.
    react_mask = sem["baseline"] == "REACT_ONLY"
    sem.loc[react_mask, "validation_s"] = sem.loc[react_mask, "latency_s"] * 0.10
    sem.loc[react_mask, "execution_s"] = sem.loc[react_mask, "latency_s"] * 0.90

    auto_mask = sem["baseline"] == "AUTOIOT_PAPER"
    auto_stage_cols = [
        "s1_latency_s",
        "s2_latency_s",
        "s3_latency_s",
        "guardrail_latency_s",
        "agent_latency_s",
    ]
    auto_has_native_timing = (
        auto_mask
        & sem[auto_stage_cols].sum(axis=1).gt(0.0)
        & sem[auto_stage_cols].notna().all(axis=1)
    )
    sem.loc[auto_has_native_timing, "grounding_s"] = sem.loc[auto_has_native_timing, "s1_latency_s"]
    sem.loc[auto_has_native_timing, "validation_s"] = sem.loc[auto_has_native_timing, "guardrail_latency_s"]
    sem.loc[auto_has_native_timing, "planning_s"] = sem.loc[auto_has_native_timing, "s2_latency_s"]
    sem.loc[auto_has_native_timing, "execution_s"] = (
        sem.loc[auto_has_native_timing, "s3_latency_s"]
        + sem.loc[auto_has_native_timing, "agent_latency_s"]
    )

    # Historic artifacts predate native AutoIOT telemetry. Keep their chart
    # data usable, but identify the allocation so it cannot be confused with
    # timings from instrumented benchmark runs.
    auto_legacy_timing = auto_mask & ~auto_has_native_timing
    auto_latency = sem.loc[auto_legacy_timing, "latency_s"]
    sem.loc[auto_legacy_timing, "grounding_s"] = auto_latency * (1.0 / 6.0)
    sem.loc[auto_legacy_timing, "planning_s"] = auto_latency * (3.0 / 6.0)
    sem.loc[auto_legacy_timing, "execution_s"] = auto_latency * (2.0 / 6.0)
    sem.loc[auto_legacy_timing, "is_estimated"] = True

    return sem[["baseline", "dataset", "run_id", "query_type", "grounding_s", "validation_s", "planning_s", "execution_s", "is_estimated"]]


def aggregate_semantic_stage_latency_by_query_type(
    df: pd.DataFrame,
    baselines: Iterable[str] = ("FLASH_FUSION", "AUTOIOT_PAPER", "REACT_ONLY"),
) -> pd.DataFrame:
    sem = _semantic_stage_frame(df)
    sem = sem[sem["baseline"].isin(list(baselines))].copy()

    per_run_dataset = (
        sem.groupby(["baseline", "dataset", "run_id", "query_type"], as_index=False, observed=True)
        .agg(
            grounding_s=("grounding_s", "mean"),
            validation_s=("validation_s", "mean"),
            planning_s=("planning_s", "mean"),
            execution_s=("execution_s", "mean"),
            uses_estimate=("is_estimated", "max"),
        )
        .copy()
    )

    stage_cols = [
        ("grounding_s", "Grounding"),
        ("validation_s", "Validation"),
        ("planning_s", "Planning"),
        ("execution_s", "Execution"),
    ]

    parts: list[pd.DataFrame] = []
    for col, stage in stage_cols:
        part = (
            per_run_dataset.groupby(["baseline", "query_type"], as_index=False, observed=True)
            .agg(
                mean=(col, "mean"),
                std=(col, "std"),
                n=(col, "count"),
                uses_estimate=("uses_estimate", "max"),
            )
            .copy()
        )
        part["stage"] = stage
        part["std"] = part["std"].fillna(0.0)
        parts.append(part)

    out = pd.concat(parts, ignore_index=True)
    baseline_cats = [b for b in BASELINE_ORDER if b in list(baselines)]
    out["baseline"] = pd.Categorical(out["baseline"], categories=baseline_cats, ordered=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    out["stage"] = pd.Categorical(out["stage"], categories=list(SEMANTIC_STAGE_ORDER), ordered=True)
    return out.sort_values(["query_type", "baseline", "stage"]).reset_index(drop=True)


def aggregate_semantic_stage_total_latency_by_query_type(
    df: pd.DataFrame,
    baselines: Iterable[str] = ("FLASH_FUSION", "AUTOIOT_PAPER", "REACT_ONLY"),
) -> pd.DataFrame:
    """Mean/std of TOTAL semantic-stage latency (all 4 stages summed) per (baseline, query_type).

    Used to draw a single whisker at the tip of each fully-stacked bar in
    plot_semantic_stage_comparison, since per-stage stds cannot be summed
    directly without ignoring covariance between stages.
    """
    sem = _semantic_stage_frame(df)
    sem = sem[sem["baseline"].isin(list(baselines))].copy()
    sem["total_s"] = sem["grounding_s"] + sem["validation_s"] + sem["planning_s"] + sem["execution_s"]

    per_run_dataset = (
        sem.groupby(["baseline", "dataset", "run_id", "query_type"], as_index=False, observed=True)
        .agg(total_s=("total_s", "mean"))
        .copy()
    )

    out = (
        per_run_dataset.groupby(["baseline", "query_type"], as_index=False, observed=True)
        .agg(mean=("total_s", "mean"), std=("total_s", "std"), n=("total_s", "count"))
        .copy()
    )
    out["std"] = out["std"].fillna(0.0)
    baseline_cats = [b for b in BASELINE_ORDER if b in list(baselines)]
    out["baseline"] = pd.Categorical(out["baseline"], categories=baseline_cats, ordered=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    return out.sort_values(["query_type", "baseline"]).reset_index(drop=True)


def aggregate_semantic_stage_latency_overall(
    df: pd.DataFrame,
    baselines: Iterable[str] = ("FLASH_FUSION", "AUTOIOT_PAPER", "REACT_ONLY"),
) -> pd.DataFrame:
    """Average semantic-stage latencies across all query types.

    Groups by (baseline, dataset, run_id) — dropping query_type — so the
    result is a single mean per baseline per stage, averaged uniformly over
    all queries across all datasets and runs.
    """
    sem = _semantic_stage_frame(df)
    sem = sem[sem["baseline"].isin(list(baselines))].copy()

    per_run_dataset = (
        sem.groupby(["baseline", "dataset", "run_id"], as_index=False, observed=True)
        .agg(
            grounding_s=("grounding_s", "mean"),
            validation_s=("validation_s", "mean"),
            planning_s=("planning_s", "mean"),
            execution_s=("execution_s", "mean"),
            uses_estimate=("is_estimated", "max"),
        )
        .copy()
    )

    stage_cols = [
        ("grounding_s", "Grounding"),
        ("validation_s", "Validation"),
        ("planning_s", "Planning"),
        ("execution_s", "Execution"),
    ]

    parts: list[pd.DataFrame] = []
    for col, stage in stage_cols:
        part = (
            per_run_dataset.groupby(["baseline"], as_index=False, observed=True)
            .agg(
                mean=(col, "mean"),
                std=(col, "std"),
                n=(col, "count"),
                uses_estimate=("uses_estimate", "max"),
            )
            .copy()
        )
        part["stage"] = stage
        part["std"] = part["std"].fillna(0.0)
        parts.append(part)

    out = pd.concat(parts, ignore_index=True)
    baseline_cats = [b for b in BASELINE_ORDER if b in list(baselines)]
    out["baseline"] = pd.Categorical(out["baseline"], categories=baseline_cats, ordered=True)
    out["stage"] = pd.Categorical(out["stage"], categories=list(SEMANTIC_STAGE_ORDER), ordered=True)
    return out.sort_values(["baseline", "stage"]).reset_index(drop=True)


def aggregate_latency_by_baseline_query_type(
    df: pd.DataFrame,
    baselines: Iterable[str] = ("FLASH_FUSION", "AUTOIOT_PAPER", "REACT_ONLY"),
) -> pd.DataFrame:
    subset = df[df["baseline"].isin(list(baselines))].copy()

    per_run_dataset = (
        subset.groupby(["baseline", "dataset", "run_id", "query_type"], as_index=False, observed=True)
        .agg(latency_s=("latency_s", "mean"))
        .copy()
    )

    out = (
        per_run_dataset.groupby(["baseline", "query_type"], as_index=False, observed=True)
        .agg(
            mean=("latency_s", "mean"),
            std=("latency_s", "std"),
            n=("latency_s", "count"),
        )
        .copy()
    )
    out["std"] = out["std"].fillna(0.0)
    baseline_cats = [b for b in BASELINE_ORDER if b in list(baselines)]
    out["baseline"] = pd.Categorical(out["baseline"], categories=baseline_cats, ordered=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    return out.sort_values(["query_type", "baseline"]).reset_index(drop=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect July26 baseline metrics summaries.")
    script_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "--results-root",
        default=str(script_dir.parent / "results" / "july26"),
        help="Root folder containing baseline result folders for July26.",
    )
    parser.add_argument(
        "--run-dir",
        default="july26_full",
        help="Per-dataset run folder name under each baseline/dataset.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    results_root = Path(args.results_root).resolve()

    df = load_all_metrics(results_root, run_dir=args.run_dir)
    ds = aggregate_accuracy_by_dataset(df)
    qt = aggregate_accuracy_by_query_type(df)

    print("Loaded rows:", len(df))
    print("\nAccuracy across datasets (mean/std):")
    print(ds[["baseline", "dataset", "mean", "std", "n_runs"]].to_string(index=False))
    print("\nAccuracy across query types (mean/std):")
    print(qt[["baseline", "query_type", "mean", "std", "n"]].to_string(index=False))


if __name__ == "__main__":
    main()
