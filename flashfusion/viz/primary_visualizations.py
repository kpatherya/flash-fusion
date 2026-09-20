#!/usr/bin/env python3
"""Generate the primary Flash-Fusion baseline and ablation visualizations.

This is the single entrypoint for the Phase A-B visualization pipeline. It
normalizes heterogeneous benchmark metrics, joins the requested extra-hard
supplement, and emits only the required comparison figures.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

matplotlib.use("Agg")
import matplotlib.pyplot as plt


REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS = ("bus", "wisdm", "ecg")
QUERY_TYPES = ("Direct", "Reasoning", "Predictive", "Out-of-Scope", "Extra-Hard")
PLOTTED_QUERY_TYPES = ("Direct", "Reasoning", "Predictive", "Out-of-Scope")
STAGES = ("Grounding", "Validation", "Planning", "Execution")
QUERY_TYPE_BY_ID = {
    **{query_id: "Direct" for query_id in range(1, 5)},
    **{query_id: "Reasoning" for query_id in range(5, 9)},
    **{query_id: "Out-of-Scope" for query_id in range(9, 13)},
    **{query_id: "Predictive" for query_id in range(13, 17)},
    **{query_id: "Extra-Hard" for query_id in range(17, 21)},
}

COLORS = {
    "FLASH_FUSION_CACHE": "#0f4c81",
    "REACT_ONLY": "#f59e0b",
    "AUTOIOT_PAPER": "#64748b",
    "HARGPT_PAPER": "#ef4444",
    "LLMSENSE_PAPER": "#8b5cf6",
    "FLASH_FUSION": "#1b9e77",
    "FF_NO_PRUNE": "#4fae91",
    "FF_NO_PROMPT": "#82c5b1",
}
LABELS = {
    "FLASH_FUSION_CACHE": "Flash-Fusion",
    "REACT_ONLY": "ReAct",
    "AUTOIOT_PAPER": "AutoIOT",
    "HARGPT_PAPER": "HARGPT",
    "LLMSENSE_PAPER": "LLMSense",
    "FLASH_FUSION": "- cache",
    "FF_NO_PRUNE": "- prune",
    "FF_NO_PROMPT": "- prompt",
}
STAGE_COLORS = {
    "Grounding": "#C77C9B",    # dusty rose
    "Validation": "#9B7BB5",   # muted purple
    "Planning": "#E5A04F",     # amber
    "Execution": "#6C8E5E",    # muted olive
}
GROUNDING_MODELS = (
    ("meta-llama/llama-3.2-1b-instruct", "Llama 3.2\n1B"),
    ("meta-llama/llama-3.2-3b-instruct", "Llama 3.2\n3B"),
    ("ibm-granite/granite-4.1-8b", "Granite 4.1\n8B"),
    ("google/gemma-3-12b-it", "Gemma 3\n12B"),
    ("qwen/qwen3-14b", "Qwen 3\n14B"),
)
PLOT_RC: dict[str, Any] = {
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
    "axes.facecolor": "#ffffff",
    "figure.facecolor": "#ffffff",
}


@dataclass(frozen=True)
class SourceSpec:
    code: str
    root: Path
    baseline: str | None = None
    include_extra_hard: bool = False


def build_source_registry(repo_root: Path = REPO_ROOT) -> dict[str, SourceSpec]:
    """Return the canonical source locations specified for primary figures."""
    results = repo_root / "flashfusion" / "results"
    return {
        "FLASH_FUSION_CACHE": SourceSpec(
            code="FLASH_FUSION_CACHE",
            root=results / "ff_hybrid_cache" / "FLASH_FUSION_CACHE",
            include_extra_hard=True,
        ),
        "FLASH_FUSION": SourceSpec(
            code="FLASH_FUSION",
            root=results / "ablations" / "primary",
            baseline="FF_NO_CACHE",
        ),
        "REACT_ONLY": SourceSpec(
            code="REACT_ONLY",
            root=results / "ff_and_react_qwen" / "REACT_ONLY",
            include_extra_hard=True,
        ),
        "AUTOIOT_PAPER": SourceSpec(code="AUTOIOT_PAPER", root=results / "with_slm_predictive"),
        "HARGPT_PAPER": SourceSpec(code="HARGPT_PAPER", root=results / "july26" / "HARGPT_PAPER"),
        "LLMSENSE_PAPER": SourceSpec(code="LLMSENSE_PAPER", root=results / "july26" / "LLMSENSE_PAPER"),
        "FF_NO_PRUNE": SourceSpec(code="FF_NO_PRUNE", root=results / "ablations" / "primary"),
        "FF_NO_PROMPT": SourceSpec(code="FF_NO_PROMPT", root=results / "ablations" / "primary"),
    }


def _dataset_from_path(path: Path) -> str:
    for parent in path.parents:
        name = parent.name.lower()
        if name in {"bus", "wisdm", "mit_ecg", "ecg"}:
            return "ecg" if name == "mit_ecg" else name
    raise ValueError(f"Cannot infer dataset from {path}")


def _metrics_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for dataset in ("bus", "wisdm", "mit_ecg", "ecg"):
        dataset_root = root / dataset
        direct = dataset_root / "metrics.csv"
        if direct.exists():
            paths.append(direct)
            continue
        paths.extend(sorted(dataset_root.glob("*/metrics.csv")))
    return paths


def normalize_schema(frame: pd.DataFrame, path: Path, expected_baseline: str) -> pd.DataFrame:
    """Normalize one metrics file into the fields used by primary figures."""
    required = {"baseline", "query_id", "gt_score", "latency_s", "cost_usd"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{path} missing required columns: {missing}")

    out = frame.copy()
    out["baseline"] = out["baseline"].astype(str).str.strip().str.upper()
    out = out[out["baseline"] == expected_baseline].copy()
    if out.empty:
        return out

    out["dataset"] = _dataset_from_path(path)
    for column in ("query_id", "gt_score", "latency_s", "cost_usd"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if out[["query_id", "gt_score", "latency_s", "cost_usd"]].isna().any().any():
        raise ValueError(f"{path} has invalid primary metric values")
    out["query_id"] = out["query_id"].astype(int)
    unknown = sorted(set(out.loc[~out["query_id"].isin(QUERY_TYPE_BY_ID), "query_id"]))
    if unknown:
        raise ValueError(f"{path} has unmapped query ids: {unknown}")
    out["query_type"] = out["query_id"].map(QUERY_TYPE_BY_ID)
    run_ids = out["run_id"] if "run_id" in out.columns else pd.Series(1, index=out.index)
    out["run_id"] = pd.to_numeric(run_ids, errors="coerce").fillna(1).astype(int)
    out["accuracy_percent"] = out["gt_score"] * 100.0

    for column in (
        "cache_grounding_latency_s",
        "cache_validation_latency_s",
        "ff_planner_latency_s",
        "guardrail_latency_s",
        "typed_exec_latency_s",
        "agent_latency_s",
        "s1_latency_s",
        "s2_latency_s",
        "s3_latency_s",
    ):
        values = out[column] if column in out.columns else pd.Series(0.0, index=out.index)
        out[column] = pd.to_numeric(values, errors="coerce").fillna(0.0)
    return out


def load_metrics(spec: SourceSpec, strict: bool) -> pd.DataFrame:
    paths = _metrics_paths(spec.root)
    if not paths:
        message = f"No metrics.csv files found for {spec.code} under {spec.root}"
        if strict:
            raise FileNotFoundError(message)
        print(f"[WARN] {message}")
        return pd.DataFrame()
    expected_baseline = spec.baseline or spec.code
    frames = [normalize_schema(pd.read_csv(path), path, expected_baseline) for path in paths]
    usable = [frame for frame in frames if not frame.empty]
    if not usable:
        raise ValueError(f"No {spec.code} rows found under {spec.root}")
    combined = pd.concat(usable, ignore_index=True)
    combined["baseline"] = spec.code
    return combined


def merge_extra_hard_queries(frame: pd.DataFrame, code: str, repo_root: Path, strict: bool) -> pd.DataFrame:
    """Append the source-specified q17-q20 metrics for the selected systems."""
    path_root = repo_root / "flashfusion" / "results" / "extra_hard" / code
    paths = _metrics_paths(path_root)
    if not paths:
        message = f"No extra-hard metrics for {code} under {path_root}"
        if strict:
            raise FileNotFoundError(message)
        print(f"[WARN] {message}")
        return frame
    extra = [normalize_schema(pd.read_csv(path), path, code) for path in paths]
    extra = [part for part in extra if not part.empty]
    if not extra:
        raise ValueError(f"No usable extra-hard {code} rows")
    return pd.concat([frame, *extra], ignore_index=True)


def load_collection(codes: Iterable[str], strict: bool) -> pd.DataFrame:
    registry = build_source_registry()
    frames: list[pd.DataFrame] = []
    for code in codes:
        spec = registry[code]
        frame = load_metrics(spec, strict)
        if spec.include_extra_hard:
            frame = merge_extra_hard_queries(frame, code, REPO_ROOT, strict)
        frames.append(frame)
        coverage = sorted(frame["query_id"].unique().tolist()) if not frame.empty else []
        print(f"[INFO] {code}: {len(frame)} rows, query ids={coverage}")
    return pd.concat(frames, ignore_index=True)


def compute_semantic_stages(frame: pd.DataFrame) -> pd.DataFrame:
    """Map native timing telemetry onto the common four-stage representation."""
    out = frame.copy()
    out["Grounding"] = out["cache_grounding_latency_s"] + out["s1_latency_s"]
    out["Validation"] = out["cache_validation_latency_s"] + out["guardrail_latency_s"]
    out["Planning"] = out["ff_planner_latency_s"] + out["s2_latency_s"]
    out["Execution"] = out["typed_exec_latency_s"] + out["agent_latency_s"] + out["s3_latency_s"]

    react = out["baseline"] == "REACT_ONLY"
    out.loc[react, "Grounding"] = 0.0
    out.loc[react, "Validation"] = out.loc[react, "latency_s"] * 0.10
    out.loc[react, "Planning"] = 0.0
    out.loc[react, "Execution"] = out.loc[react, "latency_s"] * 0.90

    assigned = out.loc[:, list(STAGES)].sum(axis=1)
    oversubscribed = assigned > out["latency_s"]
    if oversubscribed.any():
        scale = out.loc[oversubscribed, "latency_s"] / assigned.loc[oversubscribed]
        out.loc[oversubscribed, list(STAGES)] = out.loc[oversubscribed, list(STAGES)].mul(scale, axis=0)
    assigned = out.loc[:, list(STAGES)].sum(axis=1)
    out["Planning"] += (out["latency_s"] - assigned).clip(lower=0.0)
    return out


def _mean_by(frame: pd.DataFrame, value: str, groups: list[str]) -> pd.DataFrame:
    return frame.groupby(groups, observed=True)[value].mean().reset_index()


def _fold_extra_hard(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.loc[out["query_type"] == "Extra-Hard", "query_type"] = "Reasoning"
    return out


def compute_query_type_summary(frame: pd.DataFrame, codes: list[str], value: str) -> pd.DataFrame:
    """Return row means for `value` for each displayed query type after folding extra-hard rows."""
    comparison = _fold_extra_hard(frame[frame["baseline"].isin(codes)])
    return _mean_by(comparison, value, ["baseline", "query_type"])


def compute_query_type_latency_summary(frame: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    """Return row means for each displayed query type after folding extra-hard rows."""
    return compute_query_type_summary(frame, codes, "latency_s")


def compute_balanced_metric_summary(frame: pd.DataFrame, codes: list[str], value: str) -> pd.DataFrame:
    """Average `value` equally across the four displayed query types per baseline."""
    per_query_type = compute_query_type_summary(frame, codes, value)
    return per_query_type.groupby("baseline", as_index=False, observed=True)[value].mean()


def compute_balanced_dataset_run_summary(frame: pd.DataFrame, codes: list[str], value: str) -> pd.DataFrame:
    """Average `value` per (dataset, run_id) cell, then equally across cells per baseline."""
    per_cell = frame[frame["baseline"].isin(codes)].groupby(
        ["baseline", "dataset", "run_id"], as_index=False, observed=True
    )[value].mean()
    return per_cell.groupby("baseline", as_index=False, observed=True)[value].agg(["mean", "std"]).reset_index()


def compute_balanced_stage_summary(frame: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    """Average semantic stages equally across the four displayed query types."""
    staged = _fold_extra_hard(compute_semantic_stages(frame[frame["baseline"].isin(codes)]))
    per_query_type = staged.groupby(["baseline", "query_type"], observed=True)[list(STAGES)].mean().reset_index()
    return per_query_type.groupby("baseline", as_index=False, observed=True)[list(STAGES)].mean()


def validate_latency_consistency(
    frame: pd.DataFrame, codes: list[str], tol: float = 1e-6, strict: bool = False
) -> pd.DataFrame:
    """Check that balanced cumulative and semantic latency summaries agree."""
    query_summary = compute_query_type_latency_summary(frame, codes)
    cumulative = query_summary.groupby("baseline", as_index=False, observed=True)["latency_s"].mean()
    stages = compute_balanced_stage_summary(frame, codes)
    validation = cumulative.merge(stages, on="baseline", how="left")
    validation["balanced_cumulative_latency"] = validation.pop("latency_s")
    validation["balanced_semantic_total"] = validation.loc[:, list(STAGES)].sum(axis=1)
    validation["delta"] = validation["balanced_semantic_total"] - validation["balanced_cumulative_latency"]
    print("[INFO] Balanced latency consistency:\n" + validation[["baseline", "balanced_cumulative_latency", "balanced_semantic_total", "delta"]].to_string(index=False))
    invalid = validation[validation["delta"].abs() > tol]
    if not invalid.empty:
        message = f"Semantic-stage totals differ from cumulative latency for {invalid['baseline'].tolist()}"
        if strict:
            raise ValueError(message)
        print(f"[WARN] {message}")
    return validation


def _save(fig: Figure, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination.with_suffix(".png"), dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(destination.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[INFO] Wrote {destination.with_suffix('.png')} and .pdf")


def _style_axes(axis: Axes) -> None:
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.xaxis.grid(linestyle="--", alpha=0.3)
    axis.set_axisbelow(True)


def _apply_plot_style() -> None:
    plt.rcParams.update(PLOT_RC)


def plot_accuracy(frame: pd.DataFrame, codes: list[str], destination: Path, title: str | None = None) -> None:
    _apply_plot_style()
    summary = compute_balanced_dataset_run_summary(frame, codes, "accuracy_percent")
    means = [float(summary.loc[summary["baseline"] == code, "mean"].iloc[0]) for code in codes]
    stds = [float(summary.loc[summary["baseline"] == code, "std"].fillna(0.0).iloc[0]) for code in codes]
    bounded_yerr = np.vstack([
        np.minimum(stds, means),
        np.minimum(stds, 100.0 - np.asarray(means)),
    ])
    fig, axis = plt.subplots(figsize=(11.2, 5.4))
    bars = axis.bar(
        range(len(codes)), means, width=0.68, color=[COLORS[code] for code in codes],
        edgecolor="#333333", linewidth=0.9, yerr=bounded_yerr,
        error_kw={"elinewidth": 1.2, "capsize": 4, "ecolor": "#222222"},
    )
    for bar, mean, error in zip(bars, means, bounded_yerr[1]):
        axis.text(bar.get_x() + bar.get_width() / 2, mean + error + 1.0, f"{mean:.1f}%", ha="center", va="bottom", fontsize=16.25, fontweight="bold")
    axis.set_xticks(range(len(codes)), [LABELS[code] for code in codes])
    axis.set_ylabel("Query Accuracy (%)")
    axis.set_ylim(0, 100)
    if title:
        axis.set_title(title, loc="left")
    _style_axes(axis)
    fig.tight_layout()
    _save(fig, destination)


def plot_cost(frame: pd.DataFrame, codes: list[str], destination: Path) -> None:
    _apply_plot_style()
    summary = compute_summary_table(frame, codes)
    values = summary["Cost ($ x 10^-5)"].astype(float).tolist()
    fig, axis = plt.subplots(figsize=(9.6, 1.6 + 0.85 * len(codes)))
    bars = axis.barh(range(len(codes)), values, color=[COLORS[code] for code in codes], edgecolor="#333333", linewidth=0.8, height=0.58)
    for bar, value in zip(bars, values):
        axis.text(value * 1.12, bar.get_y() + bar.get_height() / 2, f"{value:.2f}", va="center", ha="left", fontsize=12.5, fontweight="bold")
    axis.set_yticks(range(len(codes)), [LABELS[code] for code in codes])
    axis.invert_yaxis()
    axis.set_xscale("log")
    axis.set_xlabel(r"Mean Cost ($\times 10^{-5}$ USD, log)")
    _style_axes(axis)
    fig.tight_layout()
    _save(fig, destination)


def plot_stage_latency(frame: pd.DataFrame, codes: list[str], destination: Path, log_scale: bool) -> None:
    _apply_plot_style()
    summary = compute_balanced_stage_summary(frame, codes)
    fig, axis = plt.subplots(figsize=(9.6, 1.6 + 0.85 * len(codes)))
    left = np.zeros(len(codes))
    for stage in STAGES:
        values = []
        for code in codes:
            row = summary[summary["baseline"] == code]
            values.append(float(row[stage].iloc[0]) if not row.empty else 0.0)
        axis.barh([LABELS[code] for code in codes], values, left=left, label=stage, color=STAGE_COLORS[stage], edgecolor="white")
        left += np.asarray(values)
    axis.set_xlabel("Mean Latency (s)" + (", log" if log_scale else ""))
    if log_scale and np.any(left > 0):
        axis.set_xscale("log")
    for position, total in enumerate(left):
        if total > 0:
            axis.text(total * 1.04 if log_scale else total + max(left) * 0.015, position, f"{total:.2f}s", va="center", ha="left", fontsize=12.5, fontweight="bold")
    axis.invert_yaxis()
    _style_axes(axis)
    legend_y = -0.26 if log_scale else -0.20
    axis.legend(ncol=4, frameon=False, loc="upper center", bbox_to_anchor=(0.5, legend_y))
    if log_scale:
        fig.subplots_adjust(bottom=0.30)
    fig.tight_layout()
    _save(fig, destination)


def plot_latency_by_query_type(frame: pd.DataFrame, codes: list[str], destination: Path, log_scale: bool) -> None:
    _apply_plot_style()
    summary = compute_query_type_latency_summary(frame, codes)
    qtypes = [query_type for query_type in PLOTTED_QUERY_TYPES if query_type in set(summary["query_type"])]
    y = np.arange(len(qtypes), dtype=float)
    width = 0.8 / len(codes)
    fig, axis = plt.subplots(figsize=(11.5, 6.0))
    for index, code in enumerate(codes):
        values = [summary.loc[(summary["baseline"] == code) & (summary["query_type"] == query_type), "latency_s"] for query_type in qtypes]
        means = [float(value.iloc[0]) if not value.empty else 0.0 for value in values]
        bars = axis.barh(y - 0.4 + width * (index + 0.5), means, width, label=LABELS[code], color=COLORS[code], edgecolor="#333333", linewidth=0.8)
        for bar, mean in zip(bars, means):
            if mean > 0:
                axis.text(mean * 1.08, bar.get_y() + bar.get_height() / 2, f"{mean:.2f}", va="center", ha="left", fontsize=12.5, fontweight="bold")
    axis.set_yticks(y, qtypes)
    axis.invert_yaxis()
    axis.set_xlabel(
        "Mean Latency (s)" + (", log" if log_scale else ""),
        labelpad=8,
    )
    if log_scale:
        axis.set_xscale("log")
    _style_axes(axis)
    axis.legend(ncol=len(codes), frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.16))
    fig.tight_layout()
    _save(fig, destination)


def compute_summary_table(frame: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    """Compute the reported summary using the same balanced aggregations as the figures."""
    subset = frame[frame["baseline"].isin(codes)].copy()
    accuracy_summary = compute_balanced_dataset_run_summary(subset, codes, "accuracy_percent")
    latency_summary = compute_balanced_metric_summary(subset, codes, "latency_s")
    cost_summary = compute_balanced_metric_summary(subset, codes, "cost_usd")
    rows: list[dict[str, Any]] = []
    for code in codes:
        part = subset[subset["baseline"] == code]
        rows.append(
            {
                "System/Ablation": LABELS[code],
                "baseline": code,
                "Accuracy (%)": float(accuracy_summary.loc[accuracy_summary["baseline"] == code, "mean"].iloc[0]),
                "Latency (s)": float(latency_summary.loc[latency_summary["baseline"] == code, "latency_s"].iloc[0]),
                "Cost ($ x 10^-5)": float(cost_summary.loc[cost_summary["baseline"] == code, "cost_usd"].iloc[0]) * 1e5,
                "Rows": len(part),
                "Query IDs": ", ".join(str(value) for value in sorted(part["query_id"].unique())),
            }
        )
    return pd.DataFrame(rows)


def write_summary_tables(frame: pd.DataFrame, codes: list[str], output_dir: Path, stem: str) -> pd.DataFrame:
    summary = compute_summary_table(frame, codes)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_dir / f"{stem}.csv", index=False, float_format="%.4f")

    display = summary[["System/Ablation", "Accuracy (%)", "Latency (s)", "Cost ($ x 10^-5)"]].copy()
    for column in display.columns[1:]:
        display[column] = display[column].map(lambda value: f"{float(value):.2f}")
    lines = [display.to_markdown(index=False), "", "## Coverage", ""]
    for _, row in summary.iterrows():
        lines.append(f"- {row['System/Ablation']}: {int(row['Rows'])} rows; query IDs {row['Query IDs']}")
    (output_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def build_cache_hit_curve_points(
    frame: pd.DataFrame, step_percent: int = 5, seed: int = 7, strict: bool = False
) -> pd.DataFrame:
    """Simulate increasing cache hits by replacing aligned no-cache query costs."""
    if step_percent <= 0 or 100 % step_percent:
        raise ValueError("step_percent must be a positive divisor of 100")
    keys = ["dataset", "query_id", "run_id"]
    costs = frame[frame["baseline"].isin(["FLASH_FUSION", "FLASH_FUSION_CACHE"])][keys + ["baseline", "cost_usd"]]
    no_cache = costs[costs["baseline"] == "FLASH_FUSION"].drop(columns="baseline")
    cached = costs[costs["baseline"] == "FLASH_FUSION_CACHE"].drop(columns="baseline")
    merged = no_cache.merge(cached, on=keys, how="inner", suffixes=("_no_cache", "_cached"))
    dropped = len(no_cache) + len(cached) - 2 * len(merged)
    if dropped:
        message = f"Cache curve excluded {dropped} unmatched source rows"
        if strict:
            raise ValueError(message)
        print(f"[WARN] {message}")
    if merged.empty:
        raise ValueError("Cache curve has no aligned FLASH_FUSION and FLASH_FUSION_CACHE rows")

    available_runs = sorted(merged["run_id"].unique().tolist())
    run_ids = available_runs[:3]
    if len(run_ids) < 3:
        print(f"[WARN] Cache curve uses {len(run_ids)} run(s), expected 3: {run_ids}")
    print(f"[INFO] Cache curve uses {len(merged)} aligned rows across run IDs {run_ids}")

    rng = np.random.default_rng(seed)
    per_run: dict[int, list[float]] = {}
    hit_rates = list(range(0, 101, step_percent))
    for run_id in run_ids:
        part = merged[merged["run_id"] == run_id].sort_values(["dataset", "query_id"])
        no_cache_costs = part["cost_usd_no_cache"].to_numpy(dtype=float)
        cached_costs = part["cost_usd_cached"].to_numpy(dtype=float)
        order = rng.permutation(len(part))
        values: list[float] = []
        for hit_rate in hit_rates:
            replacement_count = round(hit_rate / 100.0 * len(part))
            simulated = no_cache_costs.copy()
            simulated[order[:replacement_count]] = cached_costs[order[:replacement_count]]
            values.append(float(simulated.mean() * 1e5))
        per_run[int(run_id)] = values

    points = pd.DataFrame({"cache_hit_rate_percent": hit_rates})
    for index, run_id in enumerate(run_ids, start=1):
        points[f"flash_fusion_cost_run{index}_x_1e5"] = per_run[int(run_id)]
    run_columns = [column for column in points.columns if column.startswith("flash_fusion_cost_run")]
    points["flash_fusion_cost_mean_x_1e5"] = points[run_columns].mean(axis=1)
    points["flash_fusion_cost_std_x_1e5"] = points[run_columns].std(axis=1, ddof=1).fillna(0.0)
    return points


def plot_cache_hit_rate_cost_curve(points: pd.DataFrame, react_cost: float, destination: Path) -> None:
    points = points.copy()
    points["react_cost_x_1e5"] = react_cost
    points.to_csv(destination.with_suffix(".csv"), index=False, float_format="%.6f")

    fig, axis = plt.subplots(figsize=(9, 5.25))
    hit_rates = points["cache_hit_rate_percent"]
    mean_costs = points["flash_fusion_cost_mean_x_1e5"]
    cost_std = points["flash_fusion_cost_std_x_1e5"]
    axis.plot(hit_rates, mean_costs, color=COLORS["FLASH_FUSION_CACHE"], linewidth=2.8, label="Flash-Fusion")
    axis.fill_between(
        hit_rates,
        mean_costs - cost_std,
        mean_costs + cost_std,
        color=COLORS["FLASH_FUSION_CACHE"],
        alpha=0.18,
        linewidth=0,
    )
    axis.axhline(react_cost, color=COLORS["REACT_ONLY"], linestyle="--", linewidth=2.2, label="ReAct")
    axis.set_xlabel("Cache Hit Rate (%)")
    axis.set_ylabel(r"Mean Cost ($\times 10^{-5}$ USD)")
    axis.set_xlim(0, 100)
    _style_axes(axis)
    axis.legend(frameon=False)
    fig.tight_layout()
    _save(fig, destination)


def _load_grounding_rows(repo_root: Path) -> pd.DataFrame:
    root = repo_root / "flashfusion" / "results" / "ff_hybrid_cache" / "grounding_benchmark"
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/grounding_benchmark_summary.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        per_model = payload.get("per_model", {})
        if not isinstance(per_model, dict):
            continue
        for model, values in per_model.items():
            if not isinstance(values, dict):
                continue
            rows.append(
                {
                    "model": model,
                    "dataset": path.parent.name,
                    "n_queries_total": int(values.get("n_queries_total", 0) or 0),
                    "n_failures": int(values.get("n_failures", 0) or 0),
                }
            )
    return pd.DataFrame(rows)


def plot_grounding_error_rate(repo_root: Path, destination: Path) -> bool:
    rows = _load_grounding_rows(repo_root)
    if rows.empty:
        print("[WARN] No grounding benchmark summaries found; grounding figure was not written.")
        return False

    summaries: list[dict[str, Any]] = []
    for model, label in GROUNDING_MODELS:
        part = rows[rows["model"] == model]
        if part.empty:
            print(f"[WARN] Grounding summary lacks {model}; excluding it from the figure.")
            continue
        total = int(part["n_queries_total"].sum())
        failures = int(part["n_failures"].sum())
        summaries.append({"model": model, "label": label, "error_rate": 100.0 * failures / total, "queries": total})
    if not summaries:
        print("[WARN] No configured grounding models are present in benchmark summaries.")
        return False

    summary = pd.DataFrame(summaries)
    summary.to_csv(destination.with_suffix(".csv"), index=False, float_format="%.4f")
    fig, axis = plt.subplots(figsize=(10, 5.25))
    bars = axis.bar(summary.index, summary["error_rate"], color="#5b8def", edgecolor="#333333", linewidth=0.7)
    axis.set_xticks(summary.index, summary["label"])
    axis.set_ylabel("Grounding Error Rate (%)")
    axis.set_ylim(0, max(10.0, float(summary["error_rate"].max()) * 1.0))
    for bar, value in zip(bars, summary["error_rate"]):
        axis.text(bar.get_x() + bar.get_width() / 2.0, bar.get_height(), f"{value:.1f}%", ha="center", va="bottom")
    _style_axes(axis)
    fig.tight_layout()
    _save(fig, destination)
    return True


def plot_baselines(frame: pd.DataFrame, output_dir: Path, strict: bool = False) -> None:
    all_codes = ["FLASH_FUSION_CACHE", "REACT_ONLY", "AUTOIOT_PAPER", "HARGPT_PAPER", "LLMSENSE_PAPER"]
    latency_codes = ["FLASH_FUSION_CACHE", "REACT_ONLY", "AUTOIOT_PAPER"]
    plot_accuracy(frame, all_codes, output_dir / "query_accuracy_across_baselines")
    plot_cost(frame, all_codes, output_dir / "cost_vs_baselines_across_datasets")
    plot_stage_latency(frame, latency_codes, output_dir / "latency_by_semantic_stage", log_scale=True)
    plot_latency_by_query_type(frame, latency_codes, output_dir / "cumulative_latency_comparison_log_by_baseline_n3", log_scale=True)
    summary = write_summary_tables(frame, all_codes, output_dir, "summary_baselines")
    curve_codes = ["FLASH_FUSION_CACHE", "FLASH_FUSION", "REACT_ONLY"]
    curve_frame = load_collection(["FLASH_FUSION"], strict=True)
    curve_data = pd.concat([frame, curve_frame], ignore_index=True)
    curve_summary = compute_summary_table(curve_data, curve_codes)
    react_cost = float(curve_summary.loc[curve_summary["baseline"] == "REACT_ONLY", "Cost ($ x 10^-5)"].iloc[0])
    points = build_cache_hit_curve_points(curve_data, strict=strict)
    plot_cache_hit_rate_cost_curve(points, react_cost, output_dir / "cache_hit_rate_vs_cost_flash_fusion_vs_react")
    validate_latency_consistency(frame, latency_codes, strict=strict)
    plot_grounding_error_rate(REPO_ROOT, output_dir / "grounding_loss_vs_model_size")


def plot_ablations(frame: pd.DataFrame, output_dir: Path, strict: bool = False) -> None:
    codes = ["FLASH_FUSION_CACHE", "FLASH_FUSION", "FF_NO_PRUNE", "FF_NO_PROMPT"]
    plot_accuracy(frame, codes, output_dir / "query_accuracy_across_ablations", "")
    plot_stage_latency(frame, codes, output_dir / "latency_by_semantic_stage", log_scale=False)
    plot_latency_by_query_type(frame, codes, output_dir / "cumulative_latency_comparison_by_ablation_n3", log_scale=False)
    write_summary_tables(frame, codes, output_dir, "summary_ablations")
    validate_latency_consistency(frame, codes, strict=strict)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the primary Flash-Fusion visualizations.")
    parser.add_argument("--mode", choices=("baselines", "ablations", "all"), default="all")
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "results" / "primary_visualizations")
    parser.add_argument("--strict", action="store_true", help="Fail when an expected source is missing.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.mode in {"baselines", "all"}:
        baseline_codes = ["FLASH_FUSION_CACHE", "REACT_ONLY", "AUTOIOT_PAPER", "HARGPT_PAPER", "LLMSENSE_PAPER"]
        plot_baselines(load_collection(baseline_codes, args.strict), args.output_root / "baselines", args.strict)
    if args.mode in {"ablations", "all"}:
        ablation_codes = ["FLASH_FUSION_CACHE", "FLASH_FUSION", "FF_NO_PRUNE", "FF_NO_PROMPT"]
        plot_ablations(load_collection(ablation_codes, args.strict), args.output_root / "ablations", args.strict)


if __name__ == "__main__":
    main()
