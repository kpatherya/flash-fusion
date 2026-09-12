"""Visualize baseline metrics by query type.

Creates grouped bar charts and tables for:
- LLM verdict accuracy (%)
- Latency (seconds)
- Input tokens
- Output tokens
- Cost (USD)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from flashfusion.eval.queries import DATASET_WISDM, SUPPORTED_DATASETS, get_queries


QUERY_TYPE_ORDER = ["Predictive", "Direct", "Reasoning", "Out-of-Scope", "Extra-Hard"]
QUERY_TYPE_LABELS = {
    "predictive": "Predictive",
    "direct": "Direct",
    "intermediate": "Reasoning",
    "out_of_scope": "Out-of-Scope",
    "extra_hard": "Extra-Hard",
}

BASELINE_ORDER = ["FLASH_FUSION", "REACT_ONLY"]
BASELINE_LABELS = {
    "FLASH_FUSION": "Flash-Fusion",
    "WELLMAX_ONLY": "WellMax + Agent",
    "REACT_ONLY": "ReAct-Only",
}
BASELINE_COLORS = {
    "FLASH_FUSION": "#2c8c4a",
    "WELLMAX_ONLY": "#2f6ad9",
    "REACT_ONLY": "#f28e2b",
}

ERROR_BAR_METRICS = {"accuracy_percent", "latency_s", "cost_usd"}


def _ordered_baselines_from(values: pd.Series) -> list[str]:
    present = {str(v) for v in values.dropna().unique().tolist()}
    ordered = [b for b in BASELINE_ORDER if b in present]
    extras = sorted([b for b in present if b not in BASELINE_ORDER])
    return ordered + extras


METRICS = [
    {
        "key": "accuracy_percent",
        "ylabel": "LLM Verdict Accuracy (%)",
        "title": "LLM Verdict Accuracy by Query Type",
        "filename": "accuracy_by_query_type.png",
        "table_base": "accuracy_by_query_type",
        "format_kind": "percent",
        "ylim": (0.0, 110.0),  # Extend y-axis to 110 for accuracy
    },
    {
        "key": "latency_s",
        "ylabel": "Latency (s)",
        "title": "Latency by Query Type",
        "filename": "latency_by_query_type.png",
        "table_base": "latency_by_query_type",
        "format_kind": "float2",
        "ylim": None,
    },
    {
        "key": "input_tokens",
        "ylabel": "Input Tokens",
        "title": "Input Tokens by Query Type",
        "filename": "input_tokens_by_query_type.png",
        "table_base": "input_tokens_by_query_type",
        "format_kind": "int",
        "ylim": None,
    },
    {
        "key": "output_tokens",
        "ylabel": "Output Tokens",
        "title": "Output Tokens by Query Type",
        "filename": "output_tokens_by_query_type.png",
        "table_base": "output_tokens_by_query_type",
        "format_kind": "int",
        "ylim": None,
    },
    {
        "key": "cost_usd",
        "ylabel": "Cost (USD)",
        "title": "Cost by Query Type",
        "filename": "cost_by_query_type.png",
        "table_base": "cost_by_query_type",
        "format_kind": "usd",
        "ylim": None,
    },
]


def _import_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except Exception as e:  # pragma: no cover - import guard for runtime env
        raise SystemExit(
            "matplotlib is required for visualization. "
            "Install it with: pip install matplotlib"
        ) from e
    return plt


def _configure_plot_style(plt) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "figure.facecolor": "#ffffff",
            "axes.facecolor": "#ffffff",
            "axes.edgecolor": "#222222",
            "axes.linewidth": 1.8,
            "axes.titlesize": 22,
            "axes.titleweight": "bold",
            "axes.labelsize": 17,
            "axes.labelweight": "bold",
            "xtick.labelsize": 15,
            "ytick.labelsize": 15,
            "legend.fontsize": 18,
            "legend.title_fontsize": 18,
            "grid.alpha": 0.55,
            "grid.color": "#ffffff",
            "grid.linewidth": 1.0,
        }
    )


def _load_metrics(path: str, baseline_name: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Metrics file not found: {path}")
    df = pd.read_csv(p)
    if "baseline" not in df.columns:
        df["baseline"] = baseline_name
    else:
        df["baseline"] = baseline_name
    return df


def _load_metrics_any(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Metrics file not found: {path}")
    return pd.read_csv(p)


def _resolve_input_df(args: argparse.Namespace) -> pd.DataFrame:
    metrics_path = Path(args.metrics)
    if args.metrics and metrics_path.exists():
        df = _load_metrics_any(args.metrics)
        if "baseline" not in df.columns:
            raise ValueError("--metrics file must include a 'baseline' column")
        return df

    legacy_candidates = [args.wellmax, args.agent, args.flashfusion]
    if all(Path(x).exists() for x in legacy_candidates):
        df_w = _load_metrics(args.wellmax, "WELLMAX_ONLY")
        df_a = _load_metrics(args.agent, "REACT_ONLY")
        df_f = _load_metrics(args.flashfusion, "FLASH_FUSION")
        return pd.concat([df_w, df_a, df_f], ignore_index=True)

    raise FileNotFoundError(
        "Could not find input metrics. Pass --metrics or provide all of "
        "--wellmax/--agent/--flashfusion."
    )


def _prepare_query_types(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    if "query_id" not in df.columns:
        raise ValueError("Input metrics must include 'query_id' column")

    query_defs = get_queries(dataset)
    complexity_by_id = {int(q["id"]): str(q["complexity"]) for q in query_defs}
    df = df.copy()
    df["query_id"] = pd.to_numeric(df["query_id"], errors="coerce")
    if df["query_id"].isna().any():
        raise ValueError("query_id contains non-numeric values")
    df["query_id"] = df["query_id"].astype(int)
    df["query_type"] = df["query_id"].map(complexity_by_id).map(QUERY_TYPE_LABELS)

    unknown = sorted(df[df["query_type"].isna()]["query_id"].unique().tolist())
    if unknown:
        raise ValueError(f"Unknown query_id values not found in {dataset} query bank: {unknown}")

    return df


def _prepare_metrics(df: pd.DataFrame, accuracy_col: str) -> pd.DataFrame:
    if "input_tokens" not in df.columns:
        df["input_tokens"] = 0
    if "output_tokens" not in df.columns:
        df["output_tokens"] = 0

    needed = ["baseline", "query_id", accuracy_col, "latency_s", "cost_usd", "input_tokens", "output_tokens"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required metric columns: {missing}")

    return df


def _aggregate_by_query_type(df: pd.DataFrame, accuracy_col: str) -> tuple[pd.DataFrame, bool]:
    use_variation = "run_id" in df.columns and df["run_id"].nunique() > 1

    if use_variation:
        per_run = (
            df.groupby(["run_id", "baseline", "query_type"], as_index=False)
            .agg(
                accuracy_raw=(accuracy_col, "mean"),
                latency_s=("latency_s", "mean"),
                input_tokens=("input_tokens", "mean"),
                output_tokens=("output_tokens", "mean"),
                cost_usd=("cost_usd", "mean"),
            )
        )
        summary = (
            per_run.groupby(["baseline", "query_type"], as_index=False)
            .agg(
                runs_n=("run_id", "nunique"),
                accuracy_raw=("accuracy_raw", "mean"),
                accuracy_raw_std=("accuracy_raw", "std"),
                latency_s=("latency_s", "mean"),
                latency_s_std=("latency_s", "std"),
                input_tokens=("input_tokens", "mean"),
                input_tokens_std=("input_tokens", "std"),
                output_tokens=("output_tokens", "mean"),
                output_tokens_std=("output_tokens", "std"),
                cost_usd=("cost_usd", "mean"),
                cost_usd_std=("cost_usd", "std"),
            )
        )
        for std_col in [
            "accuracy_raw_std",
            "latency_s_std",
            "input_tokens_std",
            "output_tokens_std",
            "cost_usd_std",
        ]:
            summary[std_col] = summary[std_col].fillna(0.0)
    else:
        summary = (
            df.groupby(["baseline", "query_type"], as_index=False)
            .agg(
                accuracy_raw=(accuracy_col, "mean"),
                latency_s=("latency_s", "mean"),
                input_tokens=("input_tokens", "mean"),
                output_tokens=("output_tokens", "mean"),
                cost_usd=("cost_usd", "mean"),
            )
        )

    summary["accuracy_percent"] = summary["accuracy_raw"] * 100.0
    if use_variation:
        summary["accuracy_percent_std"] = summary["accuracy_raw_std"] * 100.0

    ordered_baselines = _ordered_baselines_from(summary["baseline"])
    full_index = pd.MultiIndex.from_product(
        [ordered_baselines, QUERY_TYPE_ORDER], names=["baseline", "query_type"]
    )
    summary = summary.set_index(["baseline", "query_type"]).reindex(full_index).reset_index()
    return summary, use_variation


def _aggregate_overall_accuracy(
    df: pd.DataFrame, accuracy_col: str, use_variation: bool
) -> pd.DataFrame:
    if use_variation:
        per_run = (
            df.groupby(["run_id", "baseline"], as_index=False)
            .agg(accuracy_raw=(accuracy_col, "mean"))
        )
        overall = (
            per_run.groupby("baseline", as_index=False)
            .agg(
                accuracy_raw=("accuracy_raw", "mean"),
                accuracy_raw_std=("accuracy_raw", "std"),
            )
        )
        overall["accuracy_raw_std"] = overall["accuracy_raw_std"].fillna(0.0)
    else:
        overall = (
            df.groupby("baseline", as_index=False)
            .agg(accuracy_raw=(accuracy_col, "mean"))
        )
    overall["accuracy_percent"] = overall["accuracy_raw"] * 100.0
    if "accuracy_raw_std" in overall.columns:
        overall["accuracy_percent_std"] = overall["accuracy_raw_std"] * 100.0
    return overall


def _format_for_table(v: float, kind: str) -> str:
    if pd.isna(v):
        return "N/A"
    if kind == "percent":
        return f"{v:.1f}%"
    if kind == "float2":
        return f"{v:.2f}"
    if kind == "int":
        return f"{v:.0f}"
    if kind == "usd":
        return f"{v:.6f}"
    return f"{v:.4f}"


def _format_for_table_with_variation(mean_v: float, std_v: float, kind: str) -> str:
    if pd.isna(mean_v):
        return "N/A"
    if pd.isna(std_v):
        std_v = 0.0
    if kind == "percent":
        return f"{mean_v:.1f}% +/- {std_v:.1f}%"
    if kind == "float2":
        return f"{mean_v:.2f} +/- {std_v:.2f}"
    if kind == "int":
        return f"{mean_v:.0f} +/- {std_v:.0f}"
    if kind == "usd":
        return f"{mean_v:.6f} +/- {std_v:.6f}"
    return f"{mean_v:.4f} +/- {std_v:.4f}"


def _metric_table(summary: pd.DataFrame, metric_key: str) -> pd.DataFrame:
    table = summary.pivot(index="baseline", columns="query_type", values=metric_key)
    table = table.reindex(index=_ordered_baselines_from(pd.Series(table.index)))
    table = table.reindex(columns=QUERY_TYPE_ORDER)
    table.index = [BASELINE_LABELS.get(b, str(b)) for b in table.index]
    table.index.name = "Baseline"
    return table


def _save_metric_table_markdown(
    df: pd.DataFrame,
    out_path: Path,
    heading: str,
    format_kind: str,
    std_df: pd.DataFrame | None = None,
) -> None:
    lines = [f"# {heading}", ""]
    header = "| Baseline | " + " | ".join(QUERY_TYPE_ORDER) + " |"
    sep = "|---|" + "|".join(["---:" for _ in QUERY_TYPE_ORDER]) + "|"
    lines.extend([header, sep])

    for baseline_name, row in df.iterrows():
        if std_df is not None:
            vals = [
                _format_for_table_with_variation(
                    float(row[c]) if pd.notna(row[c]) else float("nan"),
                    float(std_df.loc[baseline_name, c])
                    if pd.notna(std_df.loc[baseline_name, c])
                    else 0.0,
                    format_kind,
                )
                for c in QUERY_TYPE_ORDER
            ]
        else:
            vals = [
                _format_for_table(float(row[c]) if pd.notna(row[c]) else float("nan"), format_kind)
                for c in QUERY_TYPE_ORDER
            ]
        lines.append("| " + str(baseline_name) + " | " + " | ".join(vals) + " |")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_value_label(v: float, kind: str) -> str:
    if kind == "percent":
        return f"{v:.1f}%"
    if kind == "float2":
        return f"{v:.2f}"
    if kind == "int":
        return f"{v:.0f}"
    if kind == "usd":
        return f"${v:.6f}"
    return f"{v:.3f}"


def _plot_grouped_metric(
    summary: pd.DataFrame,
    metric_key: str,
    metric_std_key: str | None,
    overall_df: pd.DataFrame | None,
    output_png: Path,
    title: str,
    ylabel: str,
    format_kind: str,
    ylim: tuple[float, float] | None,
    show_error_bars: bool,
    include_overall: bool,
) -> None:
    plt = _import_matplotlib()
    _configure_plot_style(plt)
    fig, ax = plt.subplots(figsize=(12.5, 7.2))

    query_labels = list(QUERY_TYPE_ORDER)
    if include_overall:
        query_labels.append("All")

    x = np.arange(len(query_labels))
    width = 0.24

    baselines = _ordered_baselines_from(summary["baseline"])
    for idx, baseline in enumerate(baselines):
        base_df = summary[summary["baseline"] == baseline].set_index("query_type")
        vals = [base_df[metric_key].get(qt, np.nan) for qt in QUERY_TYPE_ORDER]
        errs = None
        if show_error_bars and metric_std_key and metric_std_key in base_df.columns:
            errs = [base_df[metric_std_key].get(qt, np.nan) for qt in QUERY_TYPE_ORDER]
            errs = np.nan_to_num(np.array(errs, dtype=float), nan=0.0)
        if include_overall and overall_df is not None:
            overall_row = overall_df[overall_df["baseline"] == baseline]
            overall_val = (
                float(overall_row[metric_key].iloc[0])
                if not overall_row.empty
                else np.nan
            )
            vals.append(overall_val)
            if show_error_bars and metric_std_key and metric_std_key in overall_df.columns:
                overall_std = (
                    float(overall_row[metric_std_key].iloc[0])
                    if not overall_row.empty
                    else 0.0
                )
                if errs is None:
                    errs = np.zeros(len(QUERY_TYPE_ORDER), dtype=float)
                errs = np.append(errs, float(overall_std))
            elif errs is not None:
                errs = np.append(errs, 0.0)
        centers = x + (idx - (len(baselines) - 1) / 2) * width
        bars = ax.bar(
            centers,
            vals,
            width=width,
            yerr=errs,
            capsize=4 if errs is not None else 0,
            error_kw={"ecolor": "#111111", "elinewidth": 1.2, "capthick": 1.2},
            label=BASELINE_LABELS.get(baseline, baseline),
            color=BASELINE_COLORS.get(baseline, "#999999"),
            edgecolor="#1f1f1f",
            linewidth=0.8,
        )
        for i, (bar, v) in enumerate(zip(bars, vals)):
            if pd.isna(v):
                continue
            err_v = float(errs[i]) if errs is not None else 0.0
            top_v = float(v) + max(0.0, err_v)
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                top_v + (0.8 if format_kind == "percent" else max(0.01 * top_v, 0.02)),
                _format_value_label(float(v), format_kind),
                ha="center",
                va="bottom",
                fontsize=12,
                fontweight="bold",
            )

    ax.set_title(title, pad=20)  # Increased padding to prevent overlap
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Query Type", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(query_labels)
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.legend(
        title="Baseline",
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        borderaxespad=0,
        frameon=True,
        fontsize=14,
        title_fontsize=14,
    )

    fig.subplots_adjust(left=0.09, right=0.85, bottom=0.12, top=0.88)  # Right margin for legend
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _build_per_query_table(df: pd.DataFrame, accuracy_col: str) -> pd.DataFrame:
    cols = [
        "query_id",
        "query_type",
        "baseline",
        accuracy_col,
        "latency_s",
        "cost_usd",
        "input_tokens",
        "output_tokens",
    ]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out = out.rename(columns={accuracy_col: "accuracy_raw"})
    out["accuracy_percent"] = out["accuracy_raw"] * 100.0
    out = out.sort_values(["query_id", "baseline"]).reset_index(drop=True)
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Visualize baseline comparison by query type. "
            "Simple usage: python -m flashfusion.eval.visualize_comparison "
            "--metrics flashfusion/eval_results/runs/latest/benchmark/metrics.csv. "
            "If run_id with >1 runs is present, tables show mean +/- sd and "
            "accuracy/latency/cost charts include error bars."
        )
    )
    parser.add_argument(
        "--metrics",
        default="flashfusion/eval_results/runs/latest/benchmark/metrics.csv",
        help=(
            "Path to combined metrics.csv containing all baselines "
            "(default view focuses on Flash-Fusion and Agent-Only)"
        ),
    )
    parser.add_argument(
        "--wellmax",
        default="flashfusion/eval_results/wellmax_all/metrics.csv",
        help="Path to wellmax metrics.csv",
    )
    parser.add_argument(
        "--agent",
        default="flashfusion/eval_results/agent_all/metrics.csv",
        help="Path to agent metrics.csv",
    )
    parser.add_argument(
        "--flashfusion",
        default="flashfusion/eval_results/ff_accuracy_all/metrics.csv",
        help="Path to flashfusion metrics.csv",
    )
    parser.add_argument(
        "--accuracy-column",
        default="gt_score",
        help="Accuracy column to compare (default: gt_score, binary LLM-verdict based)",
    )
    parser.add_argument(
        "--output",
        default="flashfusion/eval_results/runs/latest/visuals",
        help="Output directory for charts and tables",
    )
    parser.add_argument(
        "--title",
        default="Baseline Comparison by Query Type",
        help="Chart title",
    )
    parser.add_argument(
        "--dataset",
        default=DATASET_WISDM,
        choices=list(SUPPORTED_DATASETS),
        help="Dataset profile used to resolve query complexity by query_id",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_df = _resolve_input_df(args)
    all_df = _prepare_metrics(all_df, accuracy_col=args.accuracy_column)
    all_df = _prepare_query_types(all_df, dataset=args.dataset)
    summary, use_variation = _aggregate_by_query_type(all_df, accuracy_col=args.accuracy_column)
    overall_accuracy = _aggregate_overall_accuracy(
        all_df,
        accuracy_col=args.accuracy_column,
        use_variation=use_variation,
    )

    summary_csv = out_dir / "query_type_summary.csv"
    per_query_csv = out_dir / "per_query_metrics.csv"

    summary.to_csv(summary_csv, index=False)

    if use_variation:
        run_count = int(all_df["run_id"].nunique()) if "run_id" in all_df.columns else 0
        print(f"Detected multi-run metrics with run_id (n={run_count}); using mean +/- sd views.")

    per_query = _build_per_query_table(all_df, accuracy_col=args.accuracy_column)
    per_query.to_csv(per_query_csv, index=False)
    output_paths: list[Path] = [summary_csv, per_query_csv]

    for spec in METRICS:
        metric_key = str(spec["key"])
        metric_std_key = f"{metric_key}_std" if use_variation else None
        show_error_bars = bool(use_variation and metric_key in ERROR_BAR_METRICS and metric_std_key in summary.columns)
        include_overall = metric_key == "accuracy_percent"

        chart_path = out_dir / spec["filename"]
        _plot_grouped_metric(
            summary=summary,
            metric_key=metric_key,
            metric_std_key=metric_std_key,
            overall_df=overall_accuracy if include_overall else None,
            output_png=chart_path,
            title=f"{args.title} - {spec['title']}",
            ylabel=str(spec["ylabel"]),
            format_kind=str(spec["format_kind"]),
            ylim=spec["ylim"],
            show_error_bars=show_error_bars,
            include_overall=include_overall,
        )
        output_paths.append(chart_path)

        table = _metric_table(summary, metric_key)
        std_table: pd.DataFrame | None = None
        if use_variation and metric_std_key in summary.columns:
            std_table = _metric_table(summary, metric_std_key)

        csv_path = out_dir / f"{spec['table_base']}.csv"
        md_path = out_dir / f"{spec['table_base']}.md"
        if std_table is None:
            table.to_csv(csv_path)
        else:
            out_table = pd.DataFrame(index=table.index)
            for qtype in QUERY_TYPE_ORDER:
                out_table[f"{qtype}_mean"] = table[qtype]
                out_table[f"{qtype}_std"] = std_table[qtype]
            out_table.to_csv(csv_path)

        _save_metric_table_markdown(
            table,
            md_path,
            heading=str(spec["title"]),
            format_kind=str(spec["format_kind"]),
            std_df=std_table,
        )
        output_paths.extend([csv_path, md_path])

    print(f"Wrote: {summary_csv}")
    print(f"Wrote: {per_query_csv}")
    for p in output_paths:
        if p not in {summary_csv, per_query_csv}:
            print(f"Wrote: {p}")


if __name__ == "__main__":
    main()
