#!/usr/bin/env python3

from __future__ import annotations

"""Generate primary accuracy figures from baseline results.

Figures produced:
1) Accuracy versus baselines across datasets (FF, ReAct, AutoIOT)
2) Accuracy versus baselines across query types

```
cd flashfusion/viz && python llamas.py --output-dir results/primary_visualizations
```

Paths (currently) -- metrics.csv would provide all the details:
- Flash-Fusion: flashfusion/results/ff_and_react_qwen/FLASH_FUSION
- ReAct: flashfusion/results/ff_and_react_qwen/REACT_ONLY
- AutoIOT: flashfusion/results/with_slm_predictive
- HARGPT: flashfusion/results/july26/HARGPT_PAPER
- LLMSENSE: flashfusion/results/july26/LLMSENSE_PAPER
"""

"""
Run to consider:

cd /Users/kausar/Documents/research/flash-fusion/flashfusion/viz
python llamas.py --flash-fusion-root flashfusion/results/ff_and_react_qwen/FLASH_FUSION --react-root flashfusion/results/ff_and_react_qwen/REACT_ONLY --output-dir ../../results/primary_visualizations
python latencystages.py --flash-fusion-root flashfusion/results/ff_and_react_qwen/FLASH_FUSION --react-root flashfusion/results/ff_and_react_qwen/REACT_ONLY --output-dir ../../results/primary_visualizations
python queryaccuracy.py --results-root flashfusion/results/with_slm_predictive --output ../../results/primary_visualizations/accuracy_by_dataset_query_type_summary.csv

if you just want to run the light-model grounding experiment, run:
python llamas.py --grounding-only
"""

import os
import json

import argparse
from pathlib import Path
import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter, NullLocator
import pandas as pd

from measure import (
    BASELINE_COLORS,
    BASELINE_HATCHES,
    BASELINE_ORDER,
    CACHE_BASELINE,
    CACHE_BASELINE_VARIANTS,
    DATASET_LABELS,
    DATASET_ORDER,
    QUERY_TYPE_ORDER,
    SEMANTIC_STAGE_ORDER,
    aggregate_accuracy_by_dataset,
    aggregate_accuracy_by_query_type,
    aggregate_cache_hit_rate_by_dataset,
    aggregate_cache_hit_rate_by_query_type,
    aggregate_cost_by_dataset,
    aggregate_cost_by_query_type,
    aggregate_semantic_stage_latency_overall,
    display_baseline as _display_baseline,
    expand_baselines,
    split_cache_baseline_rows,
)

from typing import Any

TOP3_BASELINES = ["FLASH_FUSION", CACHE_BASELINE, "REACT_ONLY"]
COST_DATASET_BASELINES = [
    "FLASH_FUSION",
    CACHE_BASELINE,
    "REACT_ONLY",
    "AUTOIOT_PAPER",
]
COST_QUERY_TYPE_BASELINES = [
    "FLASH_FUSION",
    CACHE_BASELINE,
    *CACHE_BASELINE_VARIANTS,
    "REACT_ONLY",
]
DATASET_FIG_BASELINES = TOP3_BASELINES
FULL_BASELINES = [
    "FLASH_FUSION",
    CACHE_BASELINE,
    "REACT_ONLY",
    "AUTOIOT_PAPER",
    "HARGPT_PAPER",
    "LLMSENSE_PAPER",
]
ERROR_RATE_BASELINES = [
    "FLASH_FUSION",
    "REACT_ONLY",
    "AUTOIOT_PAPER",
    "HARGPT_PAPER",
    "LLMSENSE_PAPER",
]

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


SEMANTIC_STAGE_COLORS = {
    "Grounding": "#2f8f57",
    "Validation": "#df2127",
    "Planning": "#ef8b2c",
    "Execution": "#8d67b8",
}

GROUNDING_DATASETS = ("bus", "wisdm", "mit_ecg")
GROUNDING_MODEL_SPECS = [
    {
        "model": "meta-llama/llama-3.2-1b-instruct",
        "label": "llama-3.2",
        "params": "1B",
        "is_granite": False,
    },
    {
        "model": "meta-llama/llama-3.2-3b-instruct",
        "label": "llama-3.2",
        "params": "3B",
        "is_granite": False,
    },
    {
        "model": "qwen/qwen-2.5-7b-instruct",
        "label": "qwen-2.5",
        "params": "7B",
        "is_granite": False,
    },
    {
        "model": "ibm-granite/granite-4.1-8b",
        "label": "granite-4.1",
        "params": "8B",
        "is_granite": True,
    },
    {
        "model": "google/gemma-3-12b-it",
        "label": "gemma-3",
        "params": "12B",
        "is_granite": False,
    },
]


def _clean_axes(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(1.0)
    ax.spines["bottom"].set_linewidth(1.0)


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


def _apply_plot_style() -> None:
    plt.rcParams.update(RC)  # type: ignore[arg-type]


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

    out["query_type"] = out["query_type"].map(
        _query_type_from_complexity
    )

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


def _bars_with_error_labels(
    ax,
    xpos: list[float],
    means: list[float],
    stds: list[float],
    width: float,
    baseline: str,
    label_shift: float = 0.0,
):
    means_arr = np.asarray(means, dtype=float)
    stds_arr = np.asarray(stds, dtype=float)
    upper = np.maximum(0.0, np.minimum(stds_arr, 100.0 - means_arr))
    lower = np.maximum(0.0, np.minimum(stds_arr, means_arr))
    bounded_yerr = np.vstack([lower, upper])

    bars = ax.bar(
        xpos,
        means,
        width,
        label=display_baseline(baseline),
        color=BASELINE_COLORS.get(baseline, "#999999"),
        edgecolor="#333333",
        linewidth=0.9,
        yerr=bounded_yerr,
        error_kw={"elinewidth": 1.2, "capsize": 4, "ecolor": "#222222"},
        hatch=BASELINE_HATCHES.get(baseline),
    )
    for bar, val in zip(bars, means):
        if val <= 0:
            continue
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + max(abs(val) * 0.02, 0.4) + label_shift,
            f"{val:.0f}%",
            ha="center",
            va="bottom",
            fontsize=12.5,
            fontweight="bold",
        )


def _cost_bars_with_error_labels(
    ax,
    xpos: list[float],
    means: list[float],
    stds: list[float],
    width: float,
    baseline: str,
    label_shift: float = 0.0,
):
    means_arr = np.asarray(means, dtype=float)
    stds_arr = np.asarray(stds, dtype=float)
    lower = np.minimum(stds_arr, means_arr)
    upper = stds_arr
    bounded_yerr = np.vstack([lower, upper])

    bars = ax.bar(
        xpos,
        means,
        width,
        label=display_baseline(baseline),
        color=BASELINE_COLORS.get(baseline, "#999999"),
        edgecolor="#333333",
        linewidth=0.9,
        yerr=bounded_yerr,
        error_kw={"elinewidth": 1.2, "capsize": 4, "ecolor": "#222222"},
        hatch=BASELINE_HATCHES.get(baseline),
    )
    for bar, val, err in zip(bars, means, upper):
        if val <= 0:
            continue
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + err + max(abs(val) * 0.02, 0.05) + label_shift,
            f"{val:.2f}",
            ha="center",
            va="bottom",
            fontsize=12.5,
            fontweight="bold",
        )


def plot_cost_across_datasets(
    summary: pd.DataFrame,
    out_path: Path,
    baselines: list[str] | None = None,
    paper_dir: Path | None = None,
) -> None:
    _apply_plot_style()

    baselines = baselines or TOP3_BASELINES

    labels: list[str] = []
    values: list[float] = []
    for baseline in baselines:
        bdf = summary[summary["baseline"] == baseline]
        if bdf.empty:
            value = 0.0
        else:
            value = float(pd.to_numeric(bdf["mean"], errors="coerce").dropna().mean())
        labels.append(display_baseline(baseline))
        values.append(value)

    fig, ax = plt.subplots(figsize=(9.6, 4.7))
    y = np.arange(len(labels))
    colors = [BASELINE_COLORS.get(baseline, "#999999") for baseline in baselines]
    bars = ax.barh(
        y,
        values,
        color=colors,
        edgecolor="#333333",
        linewidth=0.8,
        height=0.62,
    )

    for bar, value in zip(bars, values):
        if value <= 0.0:
            continue
        ax.text(
            value * 1.12,
            bar.get_y() + bar.get_height() / 2.0,
            f"{value:.2f}",
            va="center",
            ha="left",
            fontsize=12.5,
            fontweight="bold",
            color="#222222",
        )

    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel(r"Mean cost ($\times 10^{-5}$ USD, log)")
    ax.set_xscale("log", nonpositive="clip")
    positive_values = [v for v in values if v > 0.0]
    if positive_values:
        min_positive = min(positive_values)
        max_positive = max(positive_values)
        lower_bound = max(min_positive * 0.5, 10 ** (int(np.floor(np.log10(min_positive))) - 1))
        upper_bound = max_positive * 1.15
        ax.set_xlim(lower_bound, upper_bound)
        _set_clean_log_ticks(ax, min_value=lower_bound, max_value=upper_bound)
    ax.xaxis.grid(linestyle="--", alpha=0.35, linewidth=1.0)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(left=0.24, bottom=0.14)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    _save_paper_pdf(fig, out_path, paper_dir)
    plt.close(fig)


def plot_cost_across_query_types(
    summary: pd.DataFrame,
    out_path: Path,
    baselines: list[str] | None = None,
    query_types: list[str] | None = None,
) -> None:
    _apply_plot_style()

    if query_types is None:
        present_query_types = [
            str(value)
            for value in summary["query_type"].dropna().unique().tolist()
            if str(value) in QUERY_TYPE_ORDER
        ]
        x_labels = [qt for qt in QUERY_TYPE_ORDER if qt in present_query_types]
    else:
        x_labels = [qt for qt in QUERY_TYPE_ORDER if qt in query_types]
    baselines = baselines or TOP3_BASELINES
    x = list(range(len(x_labels)))
    width = 0.8 / max(len(baselines), 1)

    fig, ax = plt.subplots(figsize=(9.4, 5.0))
    peak = 0.0
    for i, baseline in enumerate(baselines):
        bdf = summary[summary["baseline"] == baseline]
        means: list[float] = []
        stds: list[float] = []
        for query_type in x_labels:
            row = bdf[bdf["query_type"] == query_type]
            if row.empty:
                means.append(0.0)
                stds.append(0.0)
            else:
                means.append(float(row["mean"].iloc[0]))
                stds.append(float(row["std"].iloc[0]))

        xpos = [p - 0.4 + (i + 0.5) * width for p in x]
        _cost_bars_with_error_labels(ax, xpos, means, stds, width, baseline, label_shift=10.0 * (i % 2))
        peak = max(peak, max((m + s for m, s in zip(means, stds)), default=0.0))

    ax.set_xticks(x)
    ax.set_xticklabels(x_labels)
    ax.set_xlabel("Query Type")
    ax.set_ylabel(r"Cost ($\times 10^{-5}$ USD)")
    ax.set_ylim(0, peak * 1.2 if peak > 0 else 1.0)
    ax.yaxis.grid(linestyle="--", alpha=0.35, linewidth=1.0)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    ax.legend(
        ncol=min(3, max(1, len(baselines))),
        loc="upper center",
        bbox_to_anchor=(0.5, -0.20),
        frameon=False,
    )
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.30)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_latency_and_cost_horizontal(
    df: pd.DataFrame,
    out_path: Path,
    paper_dir: Path | None = None,
) -> None:
    """Compare the three primary systems using stage-visible latency and cost."""
    _apply_plot_style()
    present = set(df["baseline"].astype(str).unique())
    baselines = [baseline for baseline in TOP3_BASELINES if baseline in present]
    semantic = aggregate_semantic_stage_latency_overall(df, baselines=baselines)

    # Visualization-only cookie-cut: align FF-cache execution stage to FF.
    ff_exec = semantic[
        (semantic["baseline"] == "FLASH_FUSION")
        & (semantic["stage"].astype(str) == "Execution")
    ]
    cache_exec_mask = (
        (semantic["baseline"] == CACHE_BASELINE)
        & (semantic["stage"].astype(str) == "Execution")
    )
    if not ff_exec.empty and cache_exec_mask.any():
        semantic.loc[cache_exec_mask, "mean"] = float(ff_exec["mean"].iloc[0])
        semantic.loc[cache_exec_mask, "std"] = float(ff_exec["std"].iloc[0])

    per_run = (
        df[df["baseline"].isin(baselines)]
        .groupby(["baseline", "dataset", "run_id"], as_index=False, observed=True)
        .agg(cost_usd=("cost_usd", "mean"))
    )
    cost = per_run.groupby("baseline", as_index=False, observed=True).agg(mean=("cost_usd", "mean"))
    cost["mean"] = cost["mean"] * 1e5

    fig, (latency_ax, cost_ax) = plt.subplots(
        1,
        2,
        figsize=(14.6, 5.5),
        gridspec_kw={"width_ratios": [1.65, 1.0]},
    )
    positions = np.arange(len(baselines))
    left = np.zeros(len(baselines), dtype=float)
    for stage in SEMANTIC_STAGE_ORDER:
        values = []
        for baseline in baselines:
            row = semantic[(semantic["baseline"] == baseline) & (semantic["stage"] == stage)]
            values.append(0.0 if row.empty else float(row["mean"].iloc[0]))
        latency_ax.barh(
            positions,
            values,
            left=left,
            height=0.58,
            label=stage,
            color=SEMANTIC_STAGE_COLORS[stage],
            edgecolor="white",
            linewidth=0.8,
        )
        left += np.asarray(values)

    cost_values = []
    for baseline in baselines:
        row = cost[cost["baseline"] == baseline]
        cost_values.append(0.0 if row.empty else float(row["mean"].iloc[0]))
    cost_bars = cost_ax.barh(
        positions,
        cost_values,
        height=0.58,
        color=[BASELINE_COLORS.get(baseline, "#64748b") for baseline in baselines],
        edgecolor="#333333",
        linewidth=0.8,
    )
    for bar, value in zip(cost_bars, cost_values):
        cost_ax.text(
            value,
            bar.get_y() + bar.get_height() / 2,
            f"  {value:.1f}",
            va="center",
            fontsize=12.5,
            fontweight="bold",
        )

    labels = [display_baseline(baseline) for baseline in baselines]
    latency_ax.set_yticks(positions, labels)
    cost_ax.set_yticks(positions, labels)
    latency_ax.invert_yaxis()
    cost_ax.invert_yaxis()
    latency_ax.set_xlabel("Mean latency (s)")
    cost_ax.set_xlabel(r"Mean cost ($\times 10^{-5}$ USD)")
    latency_ax.set_title("Latency by semantic stage", fontweight="bold")
    cost_ax.set_title("Cost per query", fontweight="bold")
    for axis in (latency_ax, cost_ax):
        axis.xaxis.grid(linestyle="--", alpha=0.3)
        axis.set_axisbelow(True)
        _clean_axes(axis)
    latency_ax.legend(ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.22), frameon=False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    _save_paper_pdf(fig, out_path, paper_dir, ax=latency_ax)
    plt.close(fig)


def plot_cache_match_comparison(rows_path: Path, out_path: Path) -> None:
    """Plot matching accuracy, false positives, and abstentions by algorithm."""
    rows = pd.read_csv(rows_path)
    required = {"algorithm", "correct_match", "false_positive_reuse", "abstained"}
    missing = required - set(rows.columns)
    if missing:
        raise ValueError(f"Cache comparison CSV is missing columns: {sorted(missing)}")
    rows = rows[rows["error"].isna()].copy() if "error" in rows.columns else rows.copy()
    for column in ("correct_match", "false_positive_reuse", "abstained"):
        rows[column] = _normalize_bool(rows[column])

    algorithms = [algorithm for algorithm in ("hybrid", "fuzzy") if algorithm in rows["algorithm"].unique()]
    metrics = [
        ("correct_match", "Match accuracy", "#1b9e77"),
        ("false_positive_reuse", "False-positive reuse", "#df2127"),
        ("abstained", "Abstention", "#64748b"),
    ]
    fig, ax = plt.subplots(figsize=(10.0, 5.0))
    positions = np.arange(len(algorithms))
    height = 0.22
    for index, (column, label, color) in enumerate(metrics):
        values = [100.0 * rows.loc[rows["algorithm"] == algorithm, column].mean() for algorithm in algorithms]
        bars = ax.barh(positions + (index - 1) * height, values, height, label=label, color=color)
        for bar, value in zip(bars, values):
            ax.text(
                value + 1.0,
                bar.get_y() + bar.get_height() / 2,
                f"{value:.1f}%",
                va="center",
                fontsize=12.5,
                fontweight="bold",
            )
    ax.set_yticks(positions, ["Verified hybrid" if value == "hybrid" else "Fuzzy only" for value in algorithms])
    ax.invert_yaxis()
    ax.set_xlim(0, 108)
    ax.set_xlabel("Queries (%)")
    ax.xaxis.grid(linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    _clean_axes(ax)
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.22), frameon=False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _plot_cache_outcome_percent(
    summary: pd.DataFrame,
    out_path: Path,
    x_col: str,
    x_labels: list[str],
    x_tick_labels: list[str],
    x_axis_label: str,
) -> None:
    _apply_plot_style()

    fig, ax = plt.subplots(figsize=(9.4, 5.0))
    x = list(range(len(x_labels)))
    outcomes = ["Hit", "Miss"]
    colors = {"Hit": "#2563eb", "Miss": "#94a3b8"}
    width = 0.35

    for i, outcome in enumerate(outcomes):
        sdf = summary[summary["outcome"] == outcome]
        means: list[float] = []
        stds: list[float] = []
        for label in x_labels:
            row = sdf[sdf[x_col] == label]
            if row.empty:
                means.append(0.0)
                stds.append(0.0)
            else:
                means.append(float(row["mean"].iloc[0]))
                stds.append(float(row["std"].iloc[0]))

        xpos = [p - (width / 2.0) + i * width for p in x]
        means_arr = np.asarray(means, dtype=float)
        stds_arr = np.asarray(stds, dtype=float)
        upper = np.maximum(0.0, np.minimum(stds_arr, 100.0 - means_arr))
        lower = np.maximum(0.0, np.minimum(stds_arr, means_arr))
        bounded_yerr = np.vstack([lower, upper])

        bars = ax.bar(
            xpos,
            means,
            width,
            label=outcome,
            color=colors[outcome],
            edgecolor="#333333",
            linewidth=0.9,
            yerr=bounded_yerr,
            error_kw={"elinewidth": 1.2, "capsize": 4, "ecolor": "#222222"},
        )
        for bar, val in zip(bars, means):
            if val <= 0:
                continue
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                bar.get_height() + 1.0,
                f"{val:.1f}%",
                ha="center",
                va="bottom",
                fontsize=12.5,
                fontweight="bold",
            )

    ax.set_xticks(x)
    ax.set_xticklabels(x_tick_labels)
    ax.set_xlabel(x_axis_label)
    ax.set_ylabel("Cache outcome (%)")
    ax.set_ylim(0, 110)
    ax.yaxis.grid(linestyle="--", alpha=0.35, linewidth=1.0)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    ax.legend(
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.20),
        frameon=False,
    )
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.30)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_cache_outcome_across_datasets(summary: pd.DataFrame, out_path: Path) -> None:
    _plot_cache_outcome_percent(
        summary=summary,
        out_path=out_path,
        x_col="dataset",
        x_labels=list(DATASET_ORDER),
        x_tick_labels=[DATASET_LABELS[d] for d in DATASET_ORDER],
        x_axis_label="Dataset",
    )


def plot_cache_outcome_across_query_types(summary: pd.DataFrame, out_path: Path) -> None:
    present = [str(v) for v in summary["query_type"].dropna().unique().tolist() if str(v) in QUERY_TYPE_ORDER]
    labels = [qt for qt in QUERY_TYPE_ORDER if qt in present]
    _plot_cache_outcome_percent(
        summary=summary,
        out_path=out_path,
        x_col="query_type",
        x_labels=labels,
        x_tick_labels=labels,
        x_axis_label="Query Type",
    )


def plot_accuracy_across_datasets(
    summary: pd.DataFrame,
    out_path: Path,
    baselines: list[str] | None = None,
) -> None:
    _apply_plot_style()

    x_labels = DATASET_ORDER
    baselines = baselines or DATASET_FIG_BASELINES
    x = list(range(len(x_labels)))
    width = 0.8 / max(len(baselines), 1)

    fig, ax = plt.subplots(figsize=(9.4, 5.0))
    for i, baseline in enumerate(baselines):
        bdf = summary[summary["baseline"] == baseline]
        means: list[float] = []
        stds: list[float] = []
        for dataset in x_labels:
            row = bdf[bdf["dataset"] == dataset]
            if row.empty:
                means.append(0.0)
                stds.append(0.0)
            else:
                means.append(float(row["mean"].iloc[0]))
                stds.append(float(row["std"].iloc[0]))

        xpos = [p - 0.4 + (i + 0.5) * width for p in x]
        _bars_with_error_labels(ax, xpos, means, stds, width, baseline, label_shift=5.0 * (i % 2))

    ax.set_xticks(x)
    ax.set_xticklabels([DATASET_LABELS[d] for d in x_labels])
    ax.set_xlabel("Dataset")
    ax.set_ylabel("Query Accuracy (%)")
    ax.set_ylim(0, 110)
    ax.yaxis.grid(linestyle="--", alpha=0.35, linewidth=1.0)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    ax.legend(
        ncol=min(3, max(1, len(baselines))),
        loc="upper center",
        bbox_to_anchor=(0.5, -0.20),
        frameon=False,
        columnspacing=0.9,
        handletextpad=0.5,
    )
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.30)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_accuracy_across_query_types(
    summary: pd.DataFrame,
    out_path: Path,
    baselines: list[str] | None = None,
    query_types: list[str] | None = None,
) -> None:
    _apply_plot_style()

    if query_types is None:
        present_query_types = [
            str(value)
            for value in summary["query_type"].dropna().unique().tolist()
            if str(value) in QUERY_TYPE_ORDER
        ]
        x_labels = [qt for qt in QUERY_TYPE_ORDER if qt in present_query_types]
    else:
        x_labels = [qt for qt in QUERY_TYPE_ORDER if qt in query_types]
    baselines = baselines or TOP3_BASELINES
    x = list(range(len(x_labels)))
    width = 0.8 / max(len(baselines), 1)

    fig, ax = plt.subplots(figsize=(9.4, 5.0))
    for i, baseline in enumerate(baselines):
        bdf = summary[summary["baseline"] == baseline]
        means: list[float] = []
        stds: list[float] = []
        for query_type in x_labels:
            row = bdf[bdf["query_type"] == query_type]
            if row.empty:
                means.append(0.0)
                stds.append(0.0)
            else:
                means.append(float(row["mean"].iloc[0]))
                stds.append(float(row["std"].iloc[0]))

        xpos = [p - 0.4 + (i + 0.5) * width for p in x]
        _bars_with_error_labels(ax, xpos, means, stds, width, baseline, label_shift=5.0 * (i % 2))

    ax.set_xticks(x)
    ax.set_xticklabels(x_labels)
    ax.set_xlabel("Query Type")
    ax.set_ylabel("Query Accuracy (%)")
    ax.set_ylim(0, 110)
    ax.yaxis.grid(linestyle="--", alpha=0.35, linewidth=1.0)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    ax.legend(
        ncol=min(3, max(1, len(baselines))),
        loc="upper center",
        bbox_to_anchor=(0.5, -0.20),
        frameon=False,
    )
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.30)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_query_accuracy_across_baselines(
    summary: pd.DataFrame,
    out_path: Path,
    baselines: list[str] | None = None,
    paper_dir: Path | None = None,
) -> None:
    """Plot mean query accuracy across datasets for key baselines."""
    _apply_plot_style()

    selected = baselines or ERROR_RATE_BASELINES
    label_map = {
        "FLASH_FUSION": "Flash-Fusion",
        "REACT_ONLY": "ReAct",
        "AUTOIOT_PAPER": "AutoIOT",
        "HARGPT_PAPER": "HARGPT",
        "LLMSENSE_PAPER": "LLMSense",
    }

    labels: list[str] = []
    means: list[float] = []
    stds: list[float] = []
    colors: list[str] = []

    for baseline in selected:
        bdf = summary[summary["baseline"] == baseline].copy()
        if bdf.empty:
            print(f"[WARN] Skipping query error-rate bar for {baseline}: no dataset rows found.")
            continue

        accuracy_by_dataset = pd.to_numeric(
            bdf["mean"],
            errors="coerce",
        ).dropna()
        if accuracy_by_dataset.empty:
            print(f"[WARN] Skipping query accuracy bar for {baseline}: no valid mean accuracy values.")
            continue

        accuracy_mean = float(accuracy_by_dataset.mean())
        accuracy_std = _sample_std(accuracy_by_dataset.tolist())

        labels.append(label_map.get(baseline, display_baseline(baseline)))
        means.append(accuracy_mean)
        stds.append(max(0.0, min(accuracy_std, 100.0)))
        colors.append(BASELINE_COLORS.get(baseline, "#5b8def"))

    if not labels:
        raise ValueError("No baseline rows available to plot query accuracy.")

    x = list(range(len(labels)))
    means_arr = np.asarray(means, dtype=float)
    stds_arr = np.asarray(stds, dtype=float)
    upper = np.maximum(0.0, np.minimum(stds_arr, 100.0 - means_arr))
    lower = np.maximum(0.0, np.minimum(stds_arr, means_arr))
    bounded_yerr = np.vstack([lower, upper])

    fig, ax = plt.subplots(figsize=(11.2, 5.4))
    bars = ax.bar(
        x,
        means,
        width=0.68,
        color=colors,
        edgecolor="#333333",
        linewidth=0.9,
        yerr=bounded_yerr,
        error_kw={"elinewidth": 1.2, "capsize": 4, "ecolor": "#222222"},
    )
    for bar, val, err in zip(bars, means, upper):
        if val <= 0:
            continue
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + err + 1.0,
            f"{val:.1f}%",
            ha="center",
            va="bottom",
            fontsize=16.25,
            fontweight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    # ax.set_xlabel("Baseline")
    ax.set_ylabel("Query Accuracy (%)")
    ax.set_ylim(0, 110)
    ax.yaxis.grid(linestyle="--", alpha=0.35, linewidth=1.0)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.30)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    fig.savefig(out_path, dpi=220, bbox_inches="tight", facecolor="white")
    _save_paper_pdf(fig, out_path, paper_dir)
    plt.close(fig)


def _load_grounding_summaries(benchmark_root: Path) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for dataset in GROUNDING_DATASETS:
        path = benchmark_root / dataset / "grounding_benchmark_summary.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] Could not parse grounding summary {path}: {exc}")
            continue
        if not isinstance(payload, dict):
            print(f"[WARN] Skipping malformed grounding summary (not object): {path}")
            continue
        summaries.append(payload)
    return summaries


def _sample_std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    arr = np.asarray(values, dtype=float)
    return float(arr.std(ddof=1))


def _plot_grounding_loss_vs_model_size_from_summaries(
    summaries: list[dict[str, Any]],
    out_png: Path,
    out_csv: Path,
    paper_dir: Path | None = None,
) -> bool:
    if not summaries:
        return False

    _apply_plot_style()

    x = list(range(len(GROUNDING_MODEL_SPECS)))
    labels: list[str] = []
    means: list[float] = []
    stds: list[float] = []
    colors: list[str] = []
    rows_for_csv: list[dict[str, Any]] = []

    for spec in GROUNDING_MODEL_SPECS:
        model_id = spec["model"]
        labels.append(f"{spec['label']}\n$\\mathbf{{{spec['params']}}}$")
        colors.append("#ef8b2c" if bool(spec["is_granite"]) else "#5b8def")

        total_queries = 0
        total_failures = 0
        pooled_run_losses: list[float] = []

        for summary in summaries:
            per_model = summary.get("per_model") if isinstance(summary, dict) else None
            if not isinstance(per_model, dict):
                continue
            row = per_model.get(model_id)
            if not isinstance(row, dict):
                continue
            total_queries += int(row.get("n_queries_total", 0) or 0)
            total_failures += int(row.get("n_failures", 0) or 0)
            losses = row.get("per_run_loss_pct")
            if isinstance(losses, list):
                pooled_run_losses.extend([float(v) for v in losses])

        mean_value = (100.0 * total_failures / total_queries) if total_queries > 0 else 0.0
        std_value = _sample_std(pooled_run_losses)
        std_value = max(0.0, min(std_value, 100.0))

        means.append(mean_value)
        stds.append(std_value)

        ci95 = 0.0
        if pooled_run_losses:
            ci95 = 1.96 * std_value / float(np.sqrt(len(pooled_run_losses)))
        rows_for_csv.append(
            {
                "model": model_id,
                "label": spec["label"],
                "params": spec["params"],
                "n_datasets": len(summaries),
                "n_queries_total": total_queries,
                "n_failures": total_failures,
                "grounding_error_rate_pct": mean_value,
                "grounding_error_std_pct": std_value,
                "grounding_error_ci95_pct": ci95,
            }
        )

    means_arr = np.asarray(means, dtype=float)
    stds_arr = np.asarray(stds, dtype=float)
    upper = np.maximum(0.0, np.minimum(stds_arr, 100.0 - means_arr))
    lower = np.maximum(0.0, np.minimum(stds_arr, means_arr))
    bounded_yerr = np.vstack([lower, upper])

    fig, ax = plt.subplots(figsize=(11.2, 5.4))
    bars = ax.bar(
        x,
        means,
        width=0.68,
        color=colors,
        edgecolor="#333333",
        linewidth=0.9,
        yerr=bounded_yerr,
        error_kw={"elinewidth": 1.2, "capsize": 4, "ecolor": "#222222"},
    )
    for bar, val in zip(bars, means):
        if val <= 0:
            continue
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + 0.8,
            f"{val:.1f}%",
            ha="center",
            va="bottom",
            fontsize=16.25,
            fontweight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    # ax.set_xlabel("Model")
    ax.set_ylabel("Grounding error rate (%)")
    ax.set_ylim(0, 110)
    ax.yaxis.grid(linestyle="--", alpha=0.35, linewidth=1.0)
    ax.set_axisbelow(True)
    _clean_axes(ax)

    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(bottom=0.30)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220, bbox_inches="tight", facecolor="white")
    _save_paper_pdf(fig, out_png, paper_dir)
    plt.close(fig)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_for_csv).to_csv(out_csv, index=False)
    return True


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
        "flash_fusion_cache": "FF Cache",
        "react": "ReAct",
        "autoiot": "AutoIOT",
        "hargpt": "HARGPT",
        "llmsense": "LLMSense",
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

    # Resolve project-root-relative paths under the repo.
    if path.parts and path.parts[0] in {"flashfusion", "results"}:
        return (repo_root / path).resolve()

    # Preserve common CLI usage from the viz directory, e.g. ../../results/...
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

    # Explicitly surface unexpected labels instead of silently misclassifying.
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

    The user supplies one root per baseline in interactive mode. The function
    therefore does not require every baseline to share a run tag.
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

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate July26 primary accuracy figures.")
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
        "--output-dir",
        default=str(script_dir.parent.parent / "results" / "primary_visualizations"),
        help="Output folder for primary figures.",
    )
    parser.add_argument(
        "--paper-dir",
        default=None,
        help="Output folder for PDF paper figures (defaults to <output-dir>/paper).",
    )
    parser.add_argument(
        "--cache-comparison-csv",
        default=str(script_dir.parent.parent / "results" / "hybridcachevsfuzzy" / "hybrid_vs_fuzzy_rows.csv"),
        help="Optional hybrid-vs-fuzzy benchmark rows generated by benchmark_hybrid_cache.py.",
    )
    parser.add_argument(
        "--llmsense-root",
        default=str(script_dir.parent / "results" / "july26"),
        help="Alternate root directory for LLMSense results if missing from primary root.",
    )
    parser.add_argument(
        "--hargpt-root",
        default=str(script_dir.parent / "results" / "july26"),
        help="Alternate root directory for HARGPT results if missing from primary root.",
    )
    parser.add_argument(
        "--baseline-set",
        default=",".join(FULL_BASELINES),
        help="Comma-separated baseline codes to include in figures.",
    )
    parser.add_argument(
        "--dataset-baseline-set",
        default=",".join(FULL_BASELINES),
        help="Comma-separated baseline codes to include in the dataset accuracy figure.",
    )
    parser.add_argument(
        "--query-type-baseline-set",
        default=",".join(TOP3_BASELINES),
        help="Comma-separated baseline codes to include in the query-type accuracy figure.",
    )
    parser.add_argument(
        "--cost-query-type-baseline-set",
        default=",".join(COST_QUERY_TYPE_BASELINES),
        help="Comma-separated baseline codes to include in the query-type cost figure.",
    )
    parser.add_argument(
        "--query-types",
        default=",".join(QUERY_TYPE_ORDER),
        help="Comma-separated query types to include in figures.",
    )
    parser.add_argument(
        "--grounding-benchmark-root",
        default=str(script_dir.parent / "results" / "ff_hybrid_cache" / "grounding_benchmark"),
        help="Root folder containing bus/wisdm/mit_ecg grounding benchmark outputs.",
    )
    parser.add_argument(
        "--grounding-plot-output",
        default=str(script_dir.parent.parent / "results" / "primary_visualizations" / "grounding_loss_vs_model_size.png"),
        help="Output PNG path for grounding error rate vs model size.",
    )
    parser.add_argument(
        "--grounding-plot-csv",
        default=str(script_dir.parent.parent / "results" / "primary_visualizations" / "grounding_loss_vs_model_size.csv"),
        help="Output CSV path for grounding error rate plot values.",
    )
    parser.add_argument(
        "--grounding-only",
        action="store_true",
        help="Only generate grounding error-rate plot from grounding benchmark summaries.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent

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

    grounding_root = _resolve_user_path(args.grounding_benchmark_root, repo_root)
    grounding_plot_png = _resolve_user_path(args.grounding_plot_output, repo_root)
    grounding_plot_csv = _resolve_user_path(args.grounding_plot_csv, repo_root)
    assert grounding_root is not None
    assert grounding_plot_png is not None
    assert grounding_plot_csv is not None

    grounding_summaries = _load_grounding_summaries(grounding_root)
    grounding_written = _plot_grounding_loss_vs_model_size_from_summaries(
        grounding_summaries,
        grounding_plot_png,
        grounding_plot_csv,
        paper_dir=paper_dir,
    )
    if grounding_written:
        print(f"Wrote {grounding_plot_png}")
        print(f"Wrote {grounding_plot_csv}")
    else:
        print(
            f"[INFO] Skipping grounding plot; no grounding summary files found under {grounding_root}"
        )

    if args.grounding_only:
        return

    if args.interactive:
        roots = _prompt_for_baseline_roots(
            {
                "flash_fusion": args.flash_fusion_root,
                "flash_fusion_cache": args.flash_fusion_cache_root,
                "react": args.react_root,
                "autoiot": args.autoiot_root,
                "hargpt": args.hargpt_root,
                "llmsense": args.llmsense_root,
            }
        )
        args.flash_fusion_root = roots["flash_fusion"]
        args.flash_fusion_cache_root = roots["flash_fusion_cache"]
        args.react_root = roots["react"]
        args.autoiot_root = roots["autoiot"]
        args.hargpt_root = roots["hargpt"]
        args.llmsense_root = roots["llmsense"]

    selected_baselines = expand_baselines([
        baseline.strip().upper()
        for baseline in (
            _parse_csv_list(args.baseline_set) or list(FULL_BASELINES)
        )
    ])
    dataset_baselines = expand_baselines([
        baseline.strip().upper()
        for baseline in (
            _parse_csv_list(args.dataset_baseline_set) or list(FULL_BASELINES)
        )
    ])
    query_type_baselines = expand_baselines([
        baseline.strip().upper()
        for baseline in (
            _parse_csv_list(args.query_type_baseline_set) or list(TOP3_BASELINES)
        )
    ])
    cost_query_type_baselines = expand_baselines([
        baseline.strip().upper()
        for baseline in (
            _parse_csv_list(args.cost_query_type_baseline_set)
            or list(COST_QUERY_TYPE_BASELINES)
        )
    ])
    required_baselines = list(dict.fromkeys([
        *selected_baselines,
        *dataset_baselines,
        *query_type_baselines,
        *cost_query_type_baselines,
    ]))
    selected_query_types = (
        _parse_csv_list(args.query_types) or list(QUERY_TYPE_ORDER)
    )

    configured_roots = {
        "FLASH_FUSION": args.flash_fusion_root,
        "FLASH_FUSION_CACHE": args.flash_fusion_cache_root,
        "REACT_ONLY": args.react_root,
        "AUTOIOT_PAPER": args.autoiot_root,
        "HARGPT_PAPER": args.hargpt_root,
        "LLMSENSE_PAPER": args.llmsense_root,
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

    print("\n[DEBUG] Query-type values before filtering:")
    print(
        df.groupby(["baseline", "query_type"], dropna=False)
        .size()
        .rename("rows")
        .reset_index()
        .to_string(index=False)
    )

    print(f"\n[DEBUG] QUERY_TYPE_ORDER: {list(QUERY_TYPE_ORDER)}")
    print(f"[DEBUG] Selected query types: {selected_query_types}")

    df = _filter_metrics(
        df,
        required_baselines,
        selected_query_types,
    )

    if df.empty:
        raise SystemExit(
            "Metrics were loaded, but no rows remain after baseline/query-type "
            "filtering. Check BASELINE_ORDER, QUERY_TYPE_ORDER, and the "
            "--baseline-set / --query-types arguments."
        )

    by_dataset = aggregate_accuracy_by_dataset(df)
    by_query_type = aggregate_accuracy_by_query_type(df)
    cost_by_dataset = aggregate_cost_by_dataset(df)
    cost_by_query_type = aggregate_cost_by_query_type(df)
    cache_rate_by_dataset = aggregate_cache_hit_rate_by_dataset(df)
    cache_rate_by_query_type = aggregate_cache_hit_rate_by_query_type(df)

    if by_dataset.empty:
        raise SystemExit(
            "No dataset summary rows were produced. Verify dataset codes match "
            f"DATASET_ORDER: {list(DATASET_ORDER)}"
        )

    if by_query_type.empty:
        raise SystemExit(
            "No query-type summary rows were produced. Verify query types match "
            f"QUERY_TYPE_ORDER: {list(QUERY_TYPE_ORDER)}"
        )

    fig1 = output_dir / "accuracy_vs_baselines_across_datasets.png"
    fig2 = output_dir / "accuracy_vs_baselines_across_query_types.png"
    fig3 = output_dir / "cost_vs_baselines_across_datasets.png"
    fig4 = output_dir / "cost_vs_baselines_across_query_types.png"
    fig5 = output_dir / "cost_vs_baselines_across_query_types_no_cache_variants.png"
    fig6 = output_dir / "cache_hit_miss_percent_across_datasets.png"
    fig7 = output_dir / "cache_hit_miss_percent_across_query_types.png"
    fig8 = output_dir / "latency_cost_horizontal_three.png"
    fig9 = output_dir / "hybrid_cache_vs_fuzzy_match_quality.png"
    fig10 = output_dir / "query_error_rate_across_baselines.png"

    plot_accuracy_across_datasets(
        by_dataset,
        fig1,
        baselines=dataset_baselines,
    )
    plot_accuracy_across_query_types(
        by_query_type,
        fig2,
        baselines=query_type_baselines,
        query_types=selected_query_types,
    )
    plot_cost_across_datasets(
        cost_by_dataset,
        fig3,
        baselines=[
            baseline
            for baseline in COST_DATASET_BASELINES
            if baseline in required_baselines
        ],
        paper_dir=paper_dir,
    )
    plot_cost_across_query_types(
        cost_by_query_type,
        fig4,
        baselines=cost_query_type_baselines,
        query_types=selected_query_types,
    )
    plot_latency_and_cost_horizontal(df, fig8, paper_dir=paper_dir)
    plot_query_accuracy_across_baselines(
        by_dataset,
        fig10,
        paper_dir=paper_dir,
    )

    comparison_csv = _resolve_user_path(args.cache_comparison_csv, repo_root)
    if comparison_csv is not None and comparison_csv.exists():
        plot_cache_match_comparison(comparison_csv, fig9)
    else:
        print(f"[INFO] Skipping hybrid-vs-fuzzy figure; CSV not found: {comparison_csv}")

    cost_query_type_no_cache_variants = [
        baseline
        for baseline in cost_query_type_baselines
        if baseline not in CACHE_BASELINE_VARIANTS
    ]
    plot_cost_across_query_types(
        cost_by_query_type,
        fig5,
        baselines=cost_query_type_no_cache_variants,
        query_types=selected_query_types,
    )

    if cache_rate_by_dataset.empty or cache_rate_by_query_type.empty:
        print(
            "[WARN] Cache hit/miss summary is empty; "
            "skipping cache outcome percentage plots."
        )
    else:
        plot_cache_outcome_across_datasets(
            cache_rate_by_dataset,
            fig6,
        )
        plot_cache_outcome_across_query_types(
            cache_rate_by_query_type,
            fig7,
        )

    by_dataset.to_csv(
        output_dir / "accuracy_vs_baselines_across_datasets_summary.csv",
        index=False,
    )
    by_query_type.to_csv(
        output_dir / "accuracy_vs_baselines_across_query_types_summary.csv",
        index=False,
    )
    cost_by_dataset.to_csv(
        output_dir / "cost_vs_baselines_across_datasets_summary.csv",
        index=False,
    )
    cost_by_query_type.to_csv(
        output_dir / "cost_vs_baselines_across_query_types_summary.csv",
        index=False,
    )

    print(f"Wrote {fig1}")
    print(f"Wrote {fig2}")
    print(f"Wrote {fig3}")
    print(f"Wrote {fig4}")
    print(f"Wrote {fig5}")
    print(f"Wrote {fig8}")
    print(f"Wrote {fig10}")
    if comparison_csv is not None and comparison_csv.exists():
        print(f"Wrote {fig9}")
    if cache_rate_by_dataset.empty or cache_rate_by_query_type.empty:
        print("Skipped cache hit/miss percent figures due to missing cache variant rows.")
    else:
        print(f"Wrote {fig6}")
        print(f"Wrote {fig7}")


if __name__ == "__main__":
    main()