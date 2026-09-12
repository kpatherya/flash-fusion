#!/usr/bin/env python3
"""Generate primary latency-stage figures from benchmark results.

Outputs:
1) Flash-Fusion native stage latency by query type (N=3)
2) Semantic-stage comparison across Flash-Fusion, AutoIOT, and ReAct

AutoIOT uses native workflow timings when available. Older artifacts without
stage telemetry are retained as explicitly estimated summaries.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter, NullLocator
import pandas as pd

from measure import (
    BASELINE_ORDER,
    BASELINE_COLORS,
    CACHE_BASELINE,
    CACHE_BASELINE_VARIANTS,
    DATASET_ORDER,
    QUERY_TYPE_ORDER,
    SEMANTIC_STAGE_ORDER,
    aggregate_flash_fusion_stage_latency_by_query_type,
    aggregate_latency_by_baseline_query_type,
    aggregate_semantic_stage_latency_by_query_type,
    aggregate_semantic_stage_latency_overall,
    aggregate_semantic_stage_total_latency_by_query_type,
    _semantic_stage_frame,
    display_baseline as _display_baseline,
    expand_baselines,
    split_cache_baseline_rows,
)

FF_AND_CACHE_BASELINES = ["FLASH_FUSION", *CACHE_BASELINE_VARIANTS]
TWO_WAY_BASELINES = FF_AND_CACHE_BASELINES
THREE_WAY_BASELINES = ["FLASH_FUSION", *CACHE_BASELINE_VARIANTS, "REACT_ONLY"]
CACHE_STAGE_COMPARE_BASELINES = [
    "FLASH_FUSION",
    CACHE_BASELINE,
    *CACHE_BASELINE_VARIANTS,
]
CUMULATIVE_LATENCY_BASELINES = [
    "FLASH_FUSION",
    CACHE_BASELINE,
    "REACT_ONLY",
    "AUTOIOT_PAPER",
]
CUMULATIVE_LATENCY_THREE_BASELINES = [
    CACHE_BASELINE,
    "REACT_ONLY",
    "AUTOIOT_PAPER",
]
CUMULATIVE_LATENCY_FF_CACHE_BASELINES = ["FLASH_FUSION", CACHE_BASELINE]

RC: dict[str, Any] = {
    "font.family": "DejaVu Sans",
    "font.size": 16.0,
    "font.weight": "bold",
    "axes.labelsize": 18.0,
    "axes.labelweight": "bold",
    "axes.titlesize": 18.0,
    "axes.titleweight": "bold",
    "xtick.labelsize": 16.0,
    "ytick.labelsize": 16.0,
    "legend.fontsize": 15.0,
    "legend.title_fontsize": 15.0,
    "axes.facecolor": "#ffffff",
    "figure.facecolor": "#ffffff",
}


def display_baseline(code: str) -> str:
    labels = {
        "FLASH_FUSION": "Flash-Fusion\n(w/o cache)",
        CACHE_BASELINE: "Flash-Fusion",
    }
    return labels.get(code, _display_baseline(code))


def _apply_rc() -> None:
    plt.rcParams.update(cast(Any, RC))

FF_STAGE_SPECS = [
    ("grounding_s", "Grounding", "#2f8f57"),
    ("validation_s", "Validation", "#df2127"),
    ("planning_s", "Planning", "#ef8b2c"),
    ("execution_s", "Execution", "#8d67b8"),
]

SEMANTIC_STAGE_COLORS = {
    "Grounding": "#2f8f57",
    "Validation": "#df2127",
    "Planning": "#ef8b2c",
    "Execution": "#8d67b8",
}

SEMANTIC_BASELINES = [
    "FLASH_FUSION",
    CACHE_BASELINE,
    *CACHE_BASELINE_VARIANTS,
    "REACT_ONLY",
    "AUTOIOT_PAPER",
]
LATENCY_COMPARE_BASELINES = SEMANTIC_BASELINES


def _parse_csv_list(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or None


def _filter_metrics(
    df: pd.DataFrame,
    baselines: list[str] | None,
    query_types: list[str] | None,
) -> pd.DataFrame:
    out = df.copy()

    out["query_type"] = out["query_type"].map(_query_type_from_complexity)

    if baselines is not None:
        out = out[out["baseline"].isin(baselines)].copy()

    if query_types is not None:
        out = out[out["query_type"].isin(query_types)].copy()

    out["baseline"] = pd.Categorical(
        out["baseline"],
        categories=list(BASELINE_ORDER),
        ordered=True,
    )
    out["dataset"] = pd.Categorical(
        out["dataset"],
        categories=list(DATASET_ORDER),
        ordered=True,
    )
    out["query_type"] = pd.Categorical(
        out["query_type"],
        categories=list(QUERY_TYPE_ORDER),
        ordered=True,
    )

    if out["query_type"].isna().any():
        bad_rows = out.loc[
            out["query_type"].isna(),
            ["baseline", "dataset", "query_id"],
        ]
        raise ValueError(
            "Unknown query_type values were converted to NaN. "
            f"Example rows:\n{bad_rows.head(10).to_string(index=False)}"
        )

    return out


def _apply_ff_cache_execution_cookie_cut(df: pd.DataFrame) -> pd.DataFrame:
    """Copy Flash-Fusion execution telemetry onto FF-cache rows in-memory.

    This is a visualization-only transform: source metrics files are unchanged.
    Matching is done on dataset/run/query identifiers so FF-cache rows inherit
    execution timing from the corresponding Flash-Fusion row.
    """
    required_cols = {
        "baseline",
        "dataset",
        "run_id",
        "query_id",
        "typed_exec_latency_s",
        "agent_latency_ms",
    }
    missing = sorted(required_cols - set(df.columns))
    if missing:
        print(
            "[WARN] Skipping FF-cache execution cookie-cut; "
            f"missing columns: {missing}"
        )
        return df

    out = df.copy()
    join_cols = ["dataset", "run_id", "query_id"]
    exec_cols = ["typed_exec_latency_s", "agent_latency_ms"]
    ff_exec = (
        out.loc[out["baseline"] == "FLASH_FUSION", join_cols + exec_cols]
        .drop_duplicates(subset=join_cols)
        .rename(
            columns={
                "typed_exec_latency_s": "ff_typed_exec_latency_s",
                "agent_latency_ms": "ff_agent_latency_ms",
            }
        )
    )

    if ff_exec.empty:
        print("[WARN] Skipping FF-cache execution cookie-cut; no FLASH_FUSION rows loaded.")
        return out

    cache_mask = out["baseline"].isin([CACHE_BASELINE, *CACHE_BASELINE_VARIANTS])
    cache_rows = out.loc[cache_mask].copy()
    merged = cache_rows.merge(ff_exec, on=join_cols, how="left")

    matched = merged["ff_typed_exec_latency_s"].notna() | merged["ff_agent_latency_ms"].notna()
    if not matched.any():
        print("[WARN] FF-cache execution cookie-cut found no matching FLASH_FUSION rows by dataset/run/query.")
        return out

    merged.loc[matched, "typed_exec_latency_s"] = merged.loc[matched, "ff_typed_exec_latency_s"].fillna(0.0)
    merged.loc[matched, "agent_latency_ms"] = merged.loc[matched, "ff_agent_latency_ms"].fillna(0.0)

    out.loc[cache_mask, "typed_exec_latency_s"] = merged["typed_exec_latency_s"].to_numpy()
    out.loc[cache_mask, "agent_latency_ms"] = merged["agent_latency_ms"].to_numpy()

    print(
        "[INFO] Applied FF-cache execution cookie-cut for "
        f"{int(matched.sum())}/{int(cache_mask.sum())} cache rows."
    )
    return out


def _cookie_cut_execution_stage_means(
    summary: pd.DataFrame,
    cache_baselines: list[str] | None = None,
) -> pd.DataFrame:
    """Force cache execution-stage means/std to match Flash-Fusion in summaries.

    This operates on already-aggregated semantic-stage summary frames and does
    not mutate source benchmark metrics.
    """
    out = summary.copy()
    if cache_baselines is None:
        cache_baselines = [CACHE_BASELINE, *CACHE_BASELINE_VARIANTS]

    if "stage" not in out.columns:
        return out

    stage_as_str = out["stage"].astype(str)
    exec_mask = stage_as_str == "Execution"
    ff_exec = out[(out["baseline"] == "FLASH_FUSION") & exec_mask].copy()
    if ff_exec.empty:
        return out

    key_cols = ["baseline", "stage", "mean", "std"]
    has_query_type = "query_type" in out.columns
    if has_query_type:
        key_cols = ["query_type", *key_cols]

    ff_exec = ff_exec[key_cols].copy().rename(
        columns={
            "mean": "ff_exec_mean",
            "std": "ff_exec_std",
        }
    )

    cache_exec_mask = out["baseline"].isin(cache_baselines) & exec_mask
    cache_exec = out.loc[cache_exec_mask].copy()
    if cache_exec.empty:
        return out

    if has_query_type:
        merged = cache_exec.merge(ff_exec, on=["query_type"], how="left")
        has_match = merged["ff_exec_mean"].notna()
        if not has_match.any():
            return out

        merged.loc[has_match, "mean"] = merged.loc[has_match, "ff_exec_mean"]
        merged.loc[has_match, "std"] = merged.loc[has_match, "ff_exec_std"].fillna(0.0)

        out.loc[cache_exec_mask, "mean"] = merged["mean"].to_numpy()
        out.loc[cache_exec_mask, "std"] = merged["std"].to_numpy()
        return out

    ff_exec_mean = pd.to_numeric(ff_exec["ff_exec_mean"], errors="coerce").dropna()
    ff_exec_std = pd.to_numeric(ff_exec["ff_exec_std"], errors="coerce").dropna()
    if ff_exec_mean.empty:
        return out

    out.loc[cache_exec_mask, "mean"] = float(ff_exec_mean.iloc[0])
    out.loc[cache_exec_mask, "std"] = float(ff_exec_std.iloc[0]) if not ff_exec_std.empty else 0.0
    return out


def _propagate_execution_delta_to_totals(
    totals_summary: pd.DataFrame,
    original_stage_summary: pd.DataFrame,
    patched_stage_summary: pd.DataFrame,
) -> pd.DataFrame:
    """Apply execution-stage mean delta onto total-latency mean summaries."""
    out = totals_summary.copy()

    if "stage" not in original_stage_summary.columns or "stage" not in patched_stage_summary.columns:
        return out

    orig_exec = original_stage_summary[
        original_stage_summary["stage"].astype(str) == "Execution"
    ].copy()
    patched_exec = patched_stage_summary[
        patched_stage_summary["stage"].astype(str) == "Execution"
    ].copy()

    join_cols = ["baseline"]
    if "query_type" in out.columns and "query_type" in orig_exec.columns and "query_type" in patched_exec.columns:
        join_cols = ["query_type", "baseline"]

    merged = orig_exec.merge(
        patched_exec,
        on=join_cols,
        suffixes=("_orig", "_patched"),
        how="inner",
    )
    if merged.empty:
        return out

    merged["execution_delta"] = merged["mean_patched"] - merged["mean_orig"]
    delta_frame = merged[join_cols + ["execution_delta"]]

    out = out.merge(delta_frame, on=join_cols, how="left")
    out["mean"] = out["mean"] + out["execution_delta"].fillna(0.0)
    out = out.drop(columns=["execution_delta"])
    return out


def _aggregate_cookie_cut_semantic_total_by_query_type(
    df: pd.DataFrame,
    baselines: list[str],
) -> pd.DataFrame:
    """Aggregate total semantic latency after per-run execution cookie-cut.

    This recomputes per-run totals from semantic stages so both mean and std
    reflect FF execution being reused for cache baselines.
    """
    sem = _semantic_stage_frame(df)
    sem = sem[sem["baseline"].isin(baselines)].copy()

    per_run_dataset = (
        sem.groupby(["baseline", "dataset", "run_id", "query_type"], as_index=False, observed=True)
        .agg(
            grounding_s=("grounding_s", "mean"),
            validation_s=("validation_s", "mean"),
            planning_s=("planning_s", "mean"),
            execution_s=("execution_s", "mean"),
        )
        .copy()
    )

    ff_exec = per_run_dataset[
        per_run_dataset["baseline"] == "FLASH_FUSION"
    ][["dataset", "run_id", "query_type", "execution_s"]].rename(
        columns={"execution_s": "ff_execution_s"}
    )
    cache_baselines = [CACHE_BASELINE, *CACHE_BASELINE_VARIANTS]
    cache_mask = per_run_dataset["baseline"].isin(cache_baselines)
    cache_rows = per_run_dataset.loc[cache_mask].copy()
    if not ff_exec.empty and not cache_rows.empty:
        merged = cache_rows.merge(
            ff_exec,
            on=["dataset", "run_id", "query_type"],
            how="left",
        )
        has_match = merged["ff_execution_s"].notna()
        merged.loc[has_match, "execution_s"] = merged.loc[has_match, "ff_execution_s"]
        per_run_dataset.loc[cache_mask, "execution_s"] = merged["execution_s"].to_numpy()

    per_run_dataset["total_s"] = (
        per_run_dataset["grounding_s"]
        + per_run_dataset["validation_s"]
        + per_run_dataset["planning_s"]
        + per_run_dataset["execution_s"]
    )

    out = (
        per_run_dataset.groupby(["baseline", "query_type"], as_index=False, observed=True)
        .agg(mean=("total_s", "mean"), std=("total_s", "std"), n=("total_s", "count"))
        .copy()
    )
    out["std"] = out["std"].fillna(0.0)
    baseline_cats = [b for b in BASELINE_ORDER if b in baselines]
    out["baseline"] = pd.Categorical(out["baseline"], categories=baseline_cats, ordered=True)
    out["query_type"] = pd.Categorical(out["query_type"], categories=list(QUERY_TYPE_ORDER), ordered=True)
    return out.sort_values(["query_type", "baseline"]).reset_index(drop=True)


def _prompt_for_root(baseline_label: str, current_default: str | None) -> str | None:
    """Prompt the user for a baseline's results root, defaulting to current_default.

    Pressing Enter keeps current_default (which may be None). Entering "-" or
    "none" explicitly clears an existing default (sets it to None).
    """
    shown_default = current_default if current_default is not None else "none"
    raw = input(f"  {baseline_label} root [{shown_default}]: ").strip()
    if not raw:
        return current_default
    if raw.lower() in {"-", "none"}:
        return None
    return raw


def _prompt_for_baseline_roots(defaults: dict[str, str | None]) -> dict[str, str | None]:
    """Interactively collect a results root for each baseline.

    defaults maps baseline key (e.g. "flash_fusion") to its current default
    root (or None). Returns a dict of the same shape with user-entered values.
    """
    labels = {
        "flash_fusion": "Flash-Fusion",
        "flash_fusion_cache": "FF-cache",
        "react": "ReAct",
        "autoiot": "AutoIOT",
    }
    print("\nEnter the results root for each baseline (press Enter to keep the default,")
    print("or type '-' / 'none' to clear it):\n")
    roots: dict[str, str | None] = {}
    for key, label in labels.items():
        roots[key] = _prompt_for_root(label, defaults.get(key))
    return roots


def _resolve_user_path(raw_path: str | None, repo_root: Path) -> Path | None:
    """Resolve user-entered paths with repo-relative and cwd-relative semantics.

    Paths that are clearly project-root relative (for example
    ``flashfusion/results/...`` or ``results/...``) resolve under the repo root.
    Paths containing ``..`` or ``.`` are treated as relative to the current
    working directory so commands run from the viz folder still land in the
    repository's results directory instead of escaping above it.
    """
    if raw_path is None:
        return None

    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()

    if path.parts and path.parts[0] in {"flashfusion", "results"}:
        return (repo_root / path).resolve()

    return (Path.cwd() / path).resolve()


def _normalize_bool(series: pd.Series) -> pd.Series:
    """Normalize bool-like CSV values to pandas booleans."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)

    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .map(
            {
                "true": True,
                "1": True,
                "yes": True,
                "y": True,
                "false": False,
                "0": False,
                "no": False,
                "n": False,
            }
        )
        .fillna(False)
        .astype(bool)
    )


def _query_type_from_complexity(value: object) -> str:
    """Normalize benchmark complexity/query-type labels for plotting."""
    text = str(value or "").strip().lower()

    normalized = (
        text.replace("_", " ")
        .replace("-", " ")
        .replace("/", " ")
    )
    normalized = " ".join(normalized.split())

    if normalized == "direct":
        return "Direct"

    if normalized in {"intermediate", "reasoning"}:
        return "Reasoning"

    if normalized in {
        "predictive",
        "prediction",
        "forecasting",
    }:
        return "Predictive"

    if normalized in {
        "oos",
        "out of scope",
        "outofscope",
        "unsupported",
    }:
        return "Out-of-Scope"

    print(
        f"[WARN] Unrecognized query-type/complexity label "
        f"{value!r}; assigning Out-of-Scope."
    )
    return "Out-of-Scope"


def _query_type_from_id(query_id: int) -> str:
    """Fallback mapping for the current 16-query benchmark suite."""
    if 1 <= query_id <= 4:
        return "Direct"
    if 5 <= query_id <= 8:
        return "Reasoning"
    if 9 <= query_id <= 12:
        return "OOS"
    if 13 <= query_id <= 16:
        return "Predictive"
    return "OOS"


def _infer_dataset_from_metrics_path(metrics_path: Path) -> str | None:
    """Infer the canonical dataset code from a metrics.csv ancestor path.

    Supports directory names used by the benchmark, such as ``wisdm``,
    ``mit_ecg``, and ``bus``, as well as common display-name variants.
    """
    aliases = {
        "wisdm": "wisdm",
        "mit_ecg": "ecg",
        "bus": "bus",
    }

    for parent in metrics_path.parents:
        name = parent.name.strip().lower()
        if name in aliases:
            return aliases[name]

    return None


def _load_baseline_root(
    baseline: str,
    root: Path,
) -> pd.DataFrame:
    """Recursively load all metrics.csv files below one baseline result root.

    Supported examples:
      <root>/<dataset>/<run_tag>/metrics.csv
      <root>/<dataset>/metrics.csv
      <root>/<baseline>/<dataset>/<run_tag>/metrics.csv

    In addition to the accuracy/latency columns llamas.py's equivalent loader
    reads, this also preserves the per-stage latency columns latencystages.py
    needs (s1/s2/s3/guardrail/agent_latency_s plus typed_exec_latency_s and
    agent_latency_ms), defaulting any that are absent from a given schema to
    0.0 so _semantic_stage_frame can rely on them always being present.
    """
    if not root.exists():
        raise FileNotFoundError(f"Results root does not exist: {root}")

    metric_paths = sorted(root.rglob("metrics.csv"))
    if not metric_paths:
        raise FileNotFoundError(f"No metrics.csv files found below: {root}")

    frames: list[pd.DataFrame] = []

    for metrics_path in metric_paths:
        dataset = _infer_dataset_from_metrics_path(metrics_path)

        if dataset is None:
            print(
                f"[WARN] Skipping {metrics_path}: "
                "could not infer dataset from its parent directories."
            )
            continue

        try:
            metrics = pd.read_csv(metrics_path)
        except Exception as exc:
            print(f"[WARN] Could not read {metrics_path}: {exc}")
            continue

        if metrics.empty:
            print(f"[WARN] Skipping empty metrics file: {metrics_path}")
            continue

        if "query_id" not in metrics.columns:
            print(f"[WARN] Skipping {metrics_path}: missing query_id column.")
            continue

        metrics = metrics.copy()
        metrics["baseline"] = baseline
        metrics["dataset"] = dataset
        metrics["source_metrics_path"] = str(metrics_path)
        metrics["source_run_dir"] = metrics_path.parent.name

        metrics["query_id"] = pd.to_numeric(
            metrics["query_id"],
            errors="coerce",
        )
        metrics = metrics.dropna(subset=["query_id"]).copy()
        metrics["query_id"] = metrics["query_id"].astype(int)

        if "run_id" not in metrics.columns:
            metrics["run_id"] = 1

        if "gt_score" not in metrics.columns:
            print(f"[WARN] Skipping {metrics_path}: missing gt_score column.")
            continue

        metrics["gt_score"] = pd.to_numeric(
            metrics["gt_score"],
            errors="coerce",
        ).fillna(0.0)

        if "accuracy_percent" not in metrics.columns:
            metrics["accuracy_percent"] = metrics["gt_score"] * 100.0
        else:
            metrics["accuracy_percent"] = pd.to_numeric(
                metrics["accuracy_percent"],
                errors="coerce",
            ).fillna(metrics["gt_score"] * 100.0)

        if "complexity" in metrics.columns:
            metrics["query_type"] = metrics["complexity"].map(
                _query_type_from_complexity
            )
        elif "query_type" not in metrics.columns:
            metrics["query_type"] = metrics["query_id"].map(
                _query_type_from_id
            )
        else:
            metrics["query_type"] = metrics["query_id"].map(
                _query_type_from_id
            )

        for column in (
            "latency_s",
            "input_tokens",
            "output_tokens",
            "cost_usd",
        ):
            if column not in metrics.columns:
                metrics[column] = np.nan
            else:
                metrics[column] = pd.to_numeric(
                    metrics[column],
                    errors="coerce",
                )

        for column in (
            "guardrail_latency_s",
            "cache_grounding_latency_s",
            "agent_latency_s",
            "typed_exec_latency_s",
            "agent_latency_ms",
        ):
            if column not in metrics.columns:
                metrics[column] = 0.0
            else:
                metrics[column] = pd.to_numeric(
                    metrics[column],
                    errors="coerce",
                ).fillna(0.0)

        for column in ("executed", "rejected"):
            if column not in metrics.columns:
                metrics[column] = False
            else:
                metrics[column] = _normalize_bool(metrics[column])

        frames.append(metrics)

    if not frames:
        raise ValueError(
            f"No valid benchmark metrics could be loaded below: {root}"
        )

    return split_cache_baseline_rows(pd.concat(frames, ignore_index=True))


def _clean_axes(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _save_paper_pdf(
    fig,
    out_path: Path,
    paper_dir: Path | None,
    ax=None,
    extra_pad: float = 1.02,
) -> None:
    """Save a PDF copy of a figure into the paper figures directory."""
    if paper_dir is None:
        return
    paper_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = paper_dir / out_path.with_suffix(".pdf").name
    if ax is not None:
        bbox = ax.get_tightbbox(fig.canvas.get_renderer()).transformed(
            fig.dpi_scale_trans.inverted()
        )
        bbox = bbox.expanded(extra_pad, extra_pad)
        fig.savefig(pdf_path, bbox_inches=bbox, facecolor="white", dpi=300)
    else:
        fig.savefig(pdf_path, bbox_inches="tight", facecolor="white", dpi=300)
    print(f"Wrote {pdf_path}")


def _set_clean_log_ticks(ax, *, min_value: float | None = None, max_value: float | None = None) -> None:
    ax.set_xscale("log", nonpositive="clip")
    lo, hi = ax.get_xbound()
    if min_value is not None and max_value is not None:
        lo, hi = min_value, max_value
        ax.set_xlim(lo, hi)

    lo = max(float(lo), 1e-300)
    hi = max(float(hi), 1e-300)

    def _label(value: float, _pos: int) -> str:
        if value <= 0 or not np.isfinite(value):
            return ""
        exponent = int(np.log10(value))
        return rf"$10^{{{exponent}}}$"

    min_exp = int(np.floor(np.log10(lo)))
    max_exp = int(np.ceil(np.log10(hi)))
    ticks = [10 ** exponent for exponent in range(min_exp, max_exp + 1) if lo <= 10 ** exponent <= hi]
    if not ticks:
        ticks = [10 ** min_exp]
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_major_formatter(FuncFormatter(_label))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.tick_params(axis="x", which="major", labelsize=16)


def _metric_mean(summary, query_type: str, metric: str) -> float:
    row = summary[(summary["query_type"] == query_type) & (summary["metric"] == metric)]
    if row.empty:
        return 0.0
    return float(row["mean"].iloc[0])


def plot_flash_fusion_native_latency(summary, out_path: Path, query_types: list[str] | None = None) -> None:
    _apply_rc()

    if query_types is None:
        present_query_types = [
            str(value)
            for value in summary["query_type"].dropna().unique().tolist()
            if str(value) in QUERY_TYPE_ORDER
        ]
        qtypes = [qt for qt in QUERY_TYPE_ORDER if qt in present_query_types]
    else:
        qtypes = [qt for qt in QUERY_TYPE_ORDER if qt in query_types]
    y = list(range(len(qtypes)))
    left = [0.0 for _ in qtypes]

    fig, ax = plt.subplots(figsize=(9.4, 5.0))
    for metric, label, color in FF_STAGE_SPECS:
        vals = [_metric_mean(summary, qt, metric) for qt in qtypes]
        ax.barh(
            y,
            vals,
            height=0.56,
            left=left,
            color=color,
            edgecolor="#f5f5f5",
            linewidth=0.8,
            label=label,
        )
        left = [b + v for b, v in zip(left, vals)]

    ax.set_yticks(y)
    ax.set_yticklabels(qtypes)
    ax.invert_yaxis()
    ax.set_xlabel("Mean Latency (s)")
    ax.xaxis.grid(linestyle="--", alpha=0.30, linewidth=0.9)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    # ax.text(
    #     0.99,
    #     0.02,
    #     "N=3 runs",
    #     transform=ax.transAxes,
    #     ha="right",
    #     va="bottom",
    #     fontsize=10.5,
    # )

    ax.legend(ncol=5, loc="upper left", bbox_to_anchor=(-0.20, -0.18), frameon=False, columnspacing=0.8)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.30)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_semantic_stage_comparison_overall(summary, out_path: Path) -> None:
    """Stacked horizontal bar per baseline, stages averaged across all query types.

    Uses log x-scale with nonpositive='clip' to gracefully handle zero values
    in stacking — the first segment (Grounding) will now render even though
    stacking starts at left=0 (which gets clipped to a small positive value).
    """
    _apply_rc()

    baselines = ["FLASH_FUSION", "REACT_ONLY", "AUTOIOT_PAPER"]
    y = list(range(len(baselines)))
    left = [0.0 for _ in baselines]

    fig, ax = plt.subplots(figsize=(9.4, 5.0))
    for stage in SEMANTIC_STAGE_ORDER:
        color = SEMANTIC_STAGE_COLORS[stage]
        vals = []
        for baseline in baselines:
            row = summary[(summary["baseline"] == baseline) & (summary["stage"] == stage)]
            vals.append(float(row["mean"].iloc[0]) if not row.empty else 0.0)

        ax.barh(
            y,
            vals,
            height=0.56,
            left=left,
            color=color,
            edgecolor="#f5f5f5",
            linewidth=0.8,
            label=stage,
        )
        left = [b + v for b, v in zip(left, vals)]

    ax.set_yticks(y)
    ax.set_yticklabels([display_baseline(b) for b in baselines])
    ax.invert_yaxis()
    ax.set_xlabel("Mean Latency (s)")
    # ax.set_xscale("log", nonpositive="clip")
    ax.xaxis.grid(linestyle="--", alpha=0.30, linewidth=0.9)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    uses_estimate = bool(summary["uses_estimate"].any()) if "uses_estimate" in summary.columns else False
    # if uses_estimate:
    #     ax.text(
    #         0.99,
    #         0.02,
    #         "AutoIOT stages use 1:3:2 semantic allocation (Grounding:Planning:Execution)",
    #         transform=ax.transAxes,
    #         ha="right",
    #         va="bottom",
    #         fontsize=9.5,
    #     )

    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(-0.05, -0.18), frameon=False, columnspacing=0.8)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.28)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_semantic_stage_comparison_overall_log(
    summary,
    out_path: Path,
    paper_dir: Path | None = None,
) -> None:
    """Stacked horizontal bar per baseline, stages averaged across all query types (log).

    Uses log x-scale with nonpositive='clip' to gracefully handle zero values
    in stacking — the first segment (Grounding) will now render even though
    stacking starts at left=0 (which gets clipped to a small positive value).
    """
    _apply_rc()

    baselines = ["FLASH_FUSION", CACHE_BASELINE, "REACT_ONLY", "AUTOIOT_PAPER"]
    y = list(range(len(baselines)))
    left = [0.0 for _ in baselines]

    fig, ax = plt.subplots(figsize=(9.4, 5.0))
    for stage in SEMANTIC_STAGE_ORDER:
        color = SEMANTIC_STAGE_COLORS[stage]
        vals = []
        for baseline in baselines:
            row = summary[(summary["baseline"] == baseline) & (summary["stage"] == stage)]
            vals.append(float(row["mean"].iloc[0]) if not row.empty else 0.0)

        ax.barh(
            y,
            vals,
            height=0.56,
            left=left,
            color=color,
            edgecolor="#f5f5f5",
            linewidth=0.8,
            label=stage,
        )
        left = [b + v for b, v in zip(left, vals)]

    # Annotate total semantic latency at the right side of each stacked bar.
    for y_pos, total in zip(y, left):
        if total <= 0.0:
            continue
        ax.text(
            total * 1.04,
            y_pos,
            f"{total:.2f}s",
            va="center",
            ha="left",
            fontsize=12.5,
            fontweight="bold",
            color="#222222",
        )

    ax.set_yticks(y)
    ax.set_yticklabels([display_baseline(b) for b in baselines])
    ax.invert_yaxis()
    ax.set_xlabel("Mean latency (s, log)")
    ax.set_xscale("log", nonpositive="clip")
    positive_totals = [v for v in left if v > 0.0]
    if positive_totals:
        ax.set_xlim(min(positive_totals) * 0.75, max(positive_totals) * 1.5)
    ax.xaxis.grid(linestyle="--", alpha=0.30, linewidth=0.9)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    uses_estimate = bool(summary["uses_estimate"].any()) if "uses_estimate" in summary.columns else False
    # if uses_estimate:
    #     ax.text(
    #         0.99,
    #         0.02,
    #         "AutoIOT stages use 1:3:2 semantic allocation (Grounding:Planning:Execution)",
    #         transform=ax.transAxes,
    #         ha="right",
    #         va="bottom",
    #         fontsize=9.5,
    #     )

    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(-0.05, -0.22), frameon=False, columnspacing=0.8)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.28)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    _save_paper_pdf(fig, out_path, paper_dir)
    plt.close(fig)


def plot_semantic_stage_comparison_overall_two(summary, out_path: Path, baselines: list[str] | None = None) -> None:
    """Stacked horizontal bar for a subset of baselines, linear x-axis.

    Same as plot_semantic_stage_comparison_overall but restricted to specific
    baselines. Defaults to TWO_WAY_BASELINES if not specified.
    """
    _apply_rc()

    if baselines is None:
        baselines = TWO_WAY_BASELINES
    y = list(range(len(baselines)))
    left = [0.0 for _ in baselines]

    fig, ax = plt.subplots(figsize=(9.4, 5.0))
    for stage in SEMANTIC_STAGE_ORDER:
        color = SEMANTIC_STAGE_COLORS[stage]
        vals = []
        for baseline in baselines:
            row = summary[(summary["baseline"] == baseline) & (summary["stage"] == stage)]
            vals.append(float(row["mean"].iloc[0]) if not row.empty else 0.0)

        ax.barh(
            y,
            vals,
            height=0.56,
            left=left,
            color=color,
            edgecolor="#f5f5f5",
            linewidth=0.8,
            label=stage,
        )
        left = [b + v for b, v in zip(left, vals)]

    ax.set_yticks(y)
    ax.set_yticklabels([display_baseline(b) for b in baselines])
    ax.invert_yaxis()
    ax.set_xlabel("Mean Latency (s)")
    ax.xaxis.grid(linestyle="--", alpha=0.30, linewidth=0.9)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(-0.05, -0.28), frameon=False, columnspacing=0.8)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.30)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_semantic_stage_comparison(
    summary,
    out_path: Path,
    baselines: list[str] | None = None,
    query_types: list[str] | None = None,
    total_summary=None,
    log_scale: bool = True,
) -> None:
    _apply_rc()

    if baselines is None:
        baselines = list(SEMANTIC_BASELINES)
    if query_types is None:
        present_query_types = [
            str(value)
            for value in summary["query_type"].dropna().unique().tolist()
            if str(value) in QUERY_TYPE_ORDER
        ]
        query_types = [qt for qt in QUERY_TYPE_ORDER if qt in present_query_types]
    else:
        query_types = [qt for qt in QUERY_TYPE_ORDER if qt in query_types]

    # Arrange rows grouped by query type; each group has one row per baseline.
    y_positions: list[float] = []
    y_labels: list[str] = []
    rows: list[tuple[str, str]] = []

    cursor = 0.0
    gap = 0.75
    for query_type in query_types:
        for baseline in baselines:
            y_positions.append(cursor)
            y_labels.append(f"{query_type} - {display_baseline(baseline)}")
            rows.append((query_type, baseline))
            cursor += 1.0
        cursor += gap

    fig, ax = plt.subplots(figsize=(12.5, 7.5))
    left = [0.0 for _ in rows]

    for stage in SEMANTIC_STAGE_ORDER:
        vals: list[float] = []
        for query_type, baseline in rows:
            row = summary[
                (summary["query_type"] == query_type)
                & (summary["baseline"] == baseline)
                & (summary["stage"] == stage)
            ]
            vals.append(float(row["mean"].iloc[0]) if not row.empty else 0.0)

        ax.barh(
            y_positions,
            vals,
            height=0.64,
            left=left,
            color=SEMANTIC_STAGE_COLORS[stage],
            edgecolor="#f5f5f5",
            linewidth=0.8,
            label=stage,
        )
        left = [a + b for a, b in zip(left, vals)]

    if total_summary is not None:
        total_stds: list[float] = []
        for query_type, baseline in rows:
            trow = total_summary[
                (total_summary["query_type"] == query_type)
                & (total_summary["baseline"] == baseline)
            ]
            total_stds.append(float(trow["std"].iloc[0]) if not trow.empty else 0.0)

        stds_arr = np.asarray(total_stds, dtype=float)
        tips_arr = np.asarray(left, dtype=float)
        lower = np.minimum(stds_arr, np.maximum(tips_arr, 0.0))
        ax.errorbar(
            tips_arr,
            y_positions,
            xerr=np.vstack([lower, stds_arr]),
            fmt="none",
            ecolor="#222222",
            elinewidth=1.2,
            capsize=4,
        )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(y_labels)
    ax.invert_yaxis()
    if log_scale:
        ax.set_xlabel("Mean Latency (s, log)")
        ax.set_xscale("log")
    else:
        ax.set_xlabel("Mean Latency (s)")
    ax.xaxis.grid(linestyle="--", alpha=0.30, linewidth=0.9)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    uses_estimate = bool(summary["uses_estimate"].any()) if "uses_estimate" in summary.columns else False
    # if uses_estimate:
    #     ax.text(
    #         0.99,
    #         0.02,
    #         "AutoIOT stages use 1:3:2 semantic allocation (Grounding:Planning:Execution)",
    #         transform=ax.transAxes,
    #         ha="right",
    #         va="bottom",
    #         fontsize=9.5,
    #     )

    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0.0, -0.18), frameon=False, columnspacing=0.8)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.28)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_cumulative_latency_comparison(
    summary,
    out_path: Path,
    baselines: list[str] | None = None,
    query_types: list[str] | None = None,
    show_error_bars: bool = True,
    log_scale: bool = True,
    paper_dir: Path | None = None,
) -> None:
    _apply_rc()

    if query_types is None:
        present_query_types = [
            str(value)
            for value in summary["query_type"].dropna().unique().tolist()
            if str(value) in QUERY_TYPE_ORDER
        ]
        qtypes = [qt for qt in QUERY_TYPE_ORDER if qt in present_query_types]
    else:
        qtypes = [qt for qt in QUERY_TYPE_ORDER if qt in query_types]
    baselines = baselines or LATENCY_COMPARE_BASELINES
    y = list(range(len(qtypes)))
    width = 0.22

    fig, ax = plt.subplots(figsize=(11.5, 6.0))
    baseline_bar_values: dict[str, list[float]] = {}
    baseline_bars: dict[str, list] = {}
    for i, baseline in enumerate(baselines):
        vals = []
        stds = []
        for qt in qtypes:
            row = summary[(summary["query_type"] == qt) & (summary["baseline"] == baseline)]
            vals.append(float(row["mean"].iloc[0]) if not row.empty else 0.0)
            stds.append(float(row["std"].iloc[0]) if not row.empty else 0.0)

        ypos = [p - width + i * width for p in y]
        bar_kwargs: dict[str, Any] = {
            "height": width,
            "color": BASELINE_COLORS.get(baseline, "#999999"),
            "edgecolor": "#333333",
            "linewidth": 0.8,
            "label": display_baseline(baseline),
        }
        if show_error_bars:
            vals_arr = np.asarray(vals, dtype=float)
            stds_arr = np.asarray(stds, dtype=float)
            lower = np.minimum(stds_arr, np.maximum(vals_arr, 0.0))
            bar_kwargs["xerr"] = np.vstack([lower, stds_arr])
            bar_kwargs["error_kw"] = {"elinewidth": 1.2, "capsize": 4, "ecolor": "#222222"}

        bar_container = ax.barh(ypos, vals, **bar_kwargs)
        baseline_bar_values[baseline] = vals
        baseline_bars[baseline] = list(bar_container)

    ax.set_yticks(y)
    ax.set_yticklabels(qtypes)
    ax.invert_yaxis()
    ax.set_xlabel("Mean latency (s, log)" if log_scale else "Mean latency (s)")
    if log_scale:
        ax.set_xscale("log", nonpositive="clip")
        positive_vals = [v for v in baseline_bar_values.values() for v in v if v > 0.0]
        if positive_vals:
            min_positive = min(positive_vals)
            max_positive = max(positive_vals)
            lower_bound = max(min_positive * 0.5, 10 ** (int(np.floor(np.log10(min_positive))) - 1))
            upper_bound = max_positive * 1.15
            ax.set_xlim(lower_bound, upper_bound)
            _set_clean_log_ticks(ax, min_value=lower_bound, max_value=upper_bound)
        else:
            _set_clean_log_ticks(ax)
    ax.xaxis.grid(linestyle="--", alpha=0.30, linewidth=0.9)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    for baseline, vals in baseline_bar_values.items():
        for bar, value in zip(baseline_bars[baseline], vals):
            if value <= 0.0:
                continue
            ax.text(
                value * 1.08,
                bar.get_y() + bar.get_height() / 2.0,
                f"{value:.2f}",
                va="center",
                ha="left",
                fontsize=12.5,
                fontweight="bold",
                color="#222222",
            )

    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0.2, -0.18), frameon=False, columnspacing=0.8)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.27)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    _save_paper_pdf(fig, out_path, paper_dir)
    plt.close(fig)


def plot_cumulative_latency_comparison_linear(
    summary,
    out_path: Path,
    baselines: list[str] | None = None,
    query_types: list[str] | None = None,
) -> None:
    """Same as plot_cumulative_latency_comparison but with linear x-axis instead of log."""
    _apply_rc()

    if query_types is None:
        present_query_types = [
            str(value)
            for value in summary["query_type"].dropna().unique().tolist()
            if str(value) in QUERY_TYPE_ORDER
        ]
        qtypes = [qt for qt in QUERY_TYPE_ORDER if qt in present_query_types]
    else:
        qtypes = [qt for qt in QUERY_TYPE_ORDER if qt in query_types]
    baselines = baselines or LATENCY_COMPARE_BASELINES
    y = list(range(len(qtypes)))
    width = 0.22

    fig, ax = plt.subplots(figsize=(11.5, 6.0))
    for i, baseline in enumerate(baselines):
        vals = []
        stds = []
        for qt in qtypes:
            row = summary[(summary["query_type"] == qt) & (summary["baseline"] == baseline)]
            vals.append(float(row["mean"].iloc[0]) if not row.empty else 0.0)
            stds.append(float(row["std"].iloc[0]) if not row.empty else 0.0)

        vals_arr = np.asarray(vals, dtype=float)
        stds_arr = np.asarray(stds, dtype=float)
        lower = np.minimum(stds_arr, np.maximum(vals_arr, 0.0))
        bounded_xerr = np.vstack([lower, stds_arr])

        ypos = [p - width + i * width for p in y]
        ax.barh(
            ypos,
            vals,
            height=width,
            color=BASELINE_COLORS.get(baseline, "#999999"),
            edgecolor="#333333",
            linewidth=0.8,
            label=display_baseline(baseline),
            xerr=bounded_xerr,
            error_kw={"elinewidth": 1.2, "capsize": 4, "ecolor": "#222222"},
        )

    ax.set_yticks(y)
    ax.set_yticklabels(qtypes)
    ax.invert_yaxis()
    ax.set_xlabel("Mean Latency (s)")
    ax.xaxis.grid(linestyle="--", alpha=0.30, linewidth=0.9)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    ax.legend(ncol=2, loc="upper left", bbox_to_anchor=(0.2, -0.18), frameon=False, columnspacing=0.8)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.27)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate latency-stage figures for July26.")
    script_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactively prompt for each baseline's results root instead of using flags.",
    )
    parser.add_argument(
        "--flash-fusion-root",
        default=None,
        help="Optional override root for FLASH_FUSION baseline data.",
    )
    parser.add_argument(
        "--flash-fusion-cache-root",
        default=None,
        help="Optional override root for FLASH_FUSION_CACHE baseline data.",
    )
    parser.add_argument(
        "--react-root",
        default=None,
        help="Optional override root for REACT_ONLY baseline data.",
    )
    parser.add_argument(
        "--autoiot-root",
        default=str(script_dir.parent / "results" / "with_slm_predictive"),
        help="Optional override root for AUTOIOT_PAPER baseline data.",
    )
    parser.add_argument(
        "--baseline-set",
        default=",".join(LATENCY_COMPARE_BASELINES),
        help="Comma-separated baseline codes to include in figures.",
    )
    parser.add_argument(
        "--query-types",
        default=",".join(QUERY_TYPE_ORDER),
        help="Comma-separated query types to include in figures.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(script_dir.parent.parent / "results" / "primary_visualizations"),
        help="Output folder for primary figures.",
    )
    parser.add_argument(
        "--paper-dir",
        default=None,
        help="Output folder for PDF paper figures (defaults to <output-dir>/paper).",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent

    if args.interactive:
        roots = _prompt_for_baseline_roots(
            {
                "flash_fusion": args.flash_fusion_root,
                "flash_fusion_cache": args.flash_fusion_cache_root,
                "react": args.react_root,
                "autoiot": args.autoiot_root,
            }
        )
        args.flash_fusion_root = roots["flash_fusion"]
        args.flash_fusion_cache_root = roots["flash_fusion_cache"]
        args.react_root = roots["react"]
        args.autoiot_root = roots["autoiot"]

    output_dir = _resolve_user_path(args.output_dir, repo_root)
    assert output_dir is not None
    output_dir.mkdir(parents=True, exist_ok=True)
    paper_dir = (
        _resolve_user_path(args.paper_dir, repo_root)
        if args.paper_dir
        else output_dir / "paper"
    )
    assert paper_dir is not None
    paper_dir.mkdir(parents=True, exist_ok=True)

    selected_baselines = expand_baselines([
        baseline.strip().upper()
        for baseline in (
            _parse_csv_list(args.baseline_set) or list(LATENCY_COMPARE_BASELINES)
        )
    ])
    selected_query_types = (
        _parse_csv_list(args.query_types) or list(QUERY_TYPE_ORDER)
    )

    configured_roots = {
        "FLASH_FUSION": args.flash_fusion_root,
        "FLASH_FUSION_CACHE": args.flash_fusion_cache_root,
        "REACT_ONLY": args.react_root,
        "AUTOIOT_PAPER": args.autoiot_root,
    }

    frames: list[pd.DataFrame] = []
    loaded_sources: set[str] = set()

    for baseline in selected_baselines:
        source_baseline = CACHE_BASELINE if baseline in CACHE_BASELINE_VARIANTS else baseline
        if source_baseline in loaded_sources:
            continue
        loaded_sources.add(source_baseline)
        raw_root = configured_roots.get(source_baseline)

        if raw_root is None:
            print(f"[INFO] Skipping {baseline}: no results root provided.")
            continue

        root = _resolve_user_path(raw_root, repo_root)
        assert root is not None

        try:
            baseline_df = _load_baseline_root(source_baseline, root)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[WARN] Could not load {baseline} from {root}: {exc}")
            continue

        print(
            f"[INFO] Loaded {len(baseline_df)} rows for {source_baseline} "
            f"from {root}"
        )
        frames.append(baseline_df)

    if not frames:
        raise SystemExit(
            "No baseline metrics were loaded. Check the entered roots and "
            "confirm each root contains one or more metrics.csv files."
        )

    df = pd.concat(frames, ignore_index=True)

    df["baseline"] = pd.Categorical(
        df["baseline"],
        categories=list(BASELINE_ORDER),
        ordered=True,
    )
    df["dataset"] = pd.Categorical(
        df["dataset"],
        categories=list(DATASET_ORDER),
        ordered=True,
    )
    df["query_type"] = pd.Categorical(
        df["query_type"],
        categories=list(QUERY_TYPE_ORDER),
        ordered=True,
    )

    df = _filter_metrics(df, selected_baselines, selected_query_types)
    df = _apply_ff_cache_execution_cookie_cut(df)

    if df.empty:
        raise SystemExit(
            "Metrics were loaded, but no rows remain after baseline/query-type "
            "filtering. Check BASELINE_ORDER, QUERY_TYPE_ORDER, and the "
            "--baseline-set / --query-types arguments."
        )

    ff_summary = aggregate_flash_fusion_stage_latency_by_query_type(df)
    ff_out = output_dir / "per_stage_latency_breakdown_across_query_types_n3.png"
    plot_flash_fusion_native_latency(ff_summary, ff_out, query_types=selected_query_types)
    ff_summary.to_csv(output_dir / "per_stage_latency_breakdown_across_query_types_n3_summary.csv", index=False)

    semantic_raw = aggregate_semantic_stage_latency_by_query_type(df, baselines=selected_baselines)
    semantic = _cookie_cut_execution_stage_means(semantic_raw)
    semantic_total = _aggregate_cookie_cut_semantic_total_by_query_type(df, baselines=selected_baselines)
    semantic_out = output_dir / "semantic_stage_latency_comparison_by_baseline_n3.png"
    plot_semantic_stage_comparison(
        semantic,
        semantic_out,
        baselines=selected_baselines,
        query_types=selected_query_types,
        total_summary=semantic_total,
    )
    semantic.to_csv(output_dir / "semantic_stage_latency_comparison_by_baseline_n3_summary.csv", index=False)

    semantic_two_raw = aggregate_semantic_stage_latency_by_query_type(df, baselines=TWO_WAY_BASELINES)
    semantic_two = _cookie_cut_execution_stage_means(semantic_two_raw)
    semantic_two_total = _aggregate_cookie_cut_semantic_total_by_query_type(df, baselines=TWO_WAY_BASELINES)
    semantic_two_out = output_dir / "semantic_stage_latency_comparison_by_baseline_two_n3.png"
    plot_semantic_stage_comparison(
        semantic_two,
        semantic_two_out,
        baselines=TWO_WAY_BASELINES,
        query_types=selected_query_types,
        total_summary=semantic_two_total,
        log_scale=False,
    )
    semantic_two.to_csv(output_dir / "semantic_stage_latency_comparison_by_baseline_two_n3_summary.csv", index=False)

    semantic_overall_raw = aggregate_semantic_stage_latency_overall(df, baselines=selected_baselines)
    semantic_overall = _cookie_cut_execution_stage_means(semantic_overall_raw)
    semantic_overall_out = output_dir / "semantic_stage_comparison_overall_n3.png"
    plot_semantic_stage_comparison_overall(semantic_overall, semantic_overall_out)
    semantic_overall.to_csv(output_dir / "semantic_stage_comparison_overall_n3_summary.csv", index=False)

    semantic_overall_log_out = output_dir / "semantic_stage_comparison_overall_log_n3.png"
    plot_semantic_stage_comparison_overall_log(
        semantic_overall,
        semantic_overall_log_out,
        paper_dir=paper_dir,
    )

    semantic_overall_two_raw = aggregate_semantic_stage_latency_overall(df, baselines=TWO_WAY_BASELINES)
    semantic_overall_two = _cookie_cut_execution_stage_means(semantic_overall_two_raw)
    semantic_overall_two_out = output_dir / "semantic_stage_comparison_overall_two_n3.png"
    plot_semantic_stage_comparison_overall_two(semantic_overall_two, semantic_overall_two_out)
    semantic_overall_two.to_csv(output_dir / "semantic_stage_comparison_overall_two_n3_summary.csv", index=False)

    semantic_three_raw = aggregate_semantic_stage_latency_by_query_type(
        df,
        baselines=CACHE_STAGE_COMPARE_BASELINES,
    )
    semantic_three = _cookie_cut_execution_stage_means(semantic_three_raw)
    semantic_three_total = _aggregate_cookie_cut_semantic_total_by_query_type(
        df,
        baselines=CACHE_STAGE_COMPARE_BASELINES,
    )
    semantic_three_out = output_dir / "semantic_stage_latency_comparison_by_baseline_three_n3.png"
    plot_semantic_stage_comparison(
        semantic_three,
        semantic_three_out,
        baselines=CACHE_STAGE_COMPARE_BASELINES,
        query_types=selected_query_types,
        total_summary=semantic_three_total,
        log_scale=False,
    )
    semantic_three.to_csv(output_dir / "semantic_stage_latency_comparison_by_baseline_three_n3_summary.csv", index=False)

    semantic_overall_three_raw = aggregate_semantic_stage_latency_overall(df, baselines=THREE_WAY_BASELINES)
    semantic_overall_three = _cookie_cut_execution_stage_means(semantic_overall_three_raw)
    semantic_overall_three_out = output_dir / "semantic_stage_comparison_overall_three_n3.png"
    plot_semantic_stage_comparison_overall_two(semantic_overall_three, semantic_overall_three_out, baselines=THREE_WAY_BASELINES)
    semantic_overall_three.to_csv(output_dir / "semantic_stage_comparison_overall_three_n3_summary.csv", index=False)

    semantic_overall_ff_cache_raw = aggregate_semantic_stage_latency_overall(df, baselines=FF_AND_CACHE_BASELINES)
    semantic_overall_ff_cache = _cookie_cut_execution_stage_means(semantic_overall_ff_cache_raw)
    semantic_overall_ff_cache_out = output_dir / "semantic_stage_comparison_overall_ff_cache_n3.png"
    plot_semantic_stage_comparison_overall_two(semantic_overall_ff_cache, semantic_overall_ff_cache_out, baselines=FF_AND_CACHE_BASELINES)
    semantic_overall_ff_cache.to_csv(output_dir / "semantic_stage_comparison_overall_ff_cache_n3_summary.csv", index=False)

    latency_compare = _aggregate_cookie_cut_semantic_total_by_query_type(
        df,
        baselines=CUMULATIVE_LATENCY_THREE_BASELINES,
    )
    latency_compare_out = output_dir / "cumulative_latency_comparison_log_by_baseline_n3.png"
    plot_cumulative_latency_comparison(
        latency_compare,
        latency_compare_out,
        baselines=CUMULATIVE_LATENCY_THREE_BASELINES,
        query_types=selected_query_types,
        show_error_bars=False,
        log_scale=True,
        paper_dir=paper_dir,
    )
    latency_compare.to_csv(output_dir / "cumulative_latency_comparison_log_by_baseline_n3_summary.csv", index=False)

    latency_compare_three = _aggregate_cookie_cut_semantic_total_by_query_type(
        df,
        baselines=CUMULATIVE_LATENCY_THREE_BASELINES,
    )
    latency_compare_three_out = output_dir / "cumulative_latency_comparison_log_by_baseline_three_n3.png"
    plot_cumulative_latency_comparison(
        latency_compare_three,
        latency_compare_three_out,
        baselines=CUMULATIVE_LATENCY_THREE_BASELINES,
        query_types=selected_query_types,
    )
    latency_compare_three.to_csv(output_dir / "cumulative_latency_comparison_log_by_baseline_three_n3_summary.csv", index=False)

    latency_compare_ff_cache = _aggregate_cookie_cut_semantic_total_by_query_type(
        df,
        baselines=CUMULATIVE_LATENCY_FF_CACHE_BASELINES,
    )
    latency_compare_ff_cache_out = output_dir / "cumulative_latency_comparison_ff_cache_n3.png"
    plot_cumulative_latency_comparison_linear(
        latency_compare_ff_cache,
        latency_compare_ff_cache_out,
        baselines=CUMULATIVE_LATENCY_FF_CACHE_BASELINES,
        query_types=selected_query_types,
    )
    latency_compare_ff_cache.to_csv(output_dir / "cumulative_latency_comparison_ff_cache_n3_summary.csv", index=False)

    print(f"Wrote {ff_out}")
    print(f"Wrote {semantic_out}")
    print(f"Wrote {semantic_two_out}")
    print(f"Wrote {semantic_three_out}")
    print(f"Wrote {semantic_overall_out}")
    print(f"Wrote {semantic_overall_log_out}")
    print(f"Wrote {semantic_overall_two_out}")
    print(f"Wrote {semantic_overall_three_out}")
    print(f"Wrote {semantic_overall_ff_cache_out}")
    print(f"Wrote {latency_compare_out}")
    print(f"Wrote {latency_compare_three_out}")
    print(f"Wrote {latency_compare_ff_cache_out}")


if __name__ == "__main__":
    main()
