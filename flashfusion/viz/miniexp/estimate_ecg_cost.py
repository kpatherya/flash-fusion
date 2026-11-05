"""Measure ECG prompt cost as a real OpenRouter context approaches its limit.

Unlike ``latencychunks.py``, this focused experiment sends only the cost
measurement requests. It records provider-reported input tokens and total
request cost when available, with a rate-based fallback only when OpenRouter
does not return cost metadata.

Example:

    MPLBACKEND=Agg python -m flashfusion.viz.miniexp.estimate_ecg_cost \
      --data-path data/AutoIOT_dataset/ECG.0/tmp_csv/100.csv \
      --model openai/gpt-5.4 --context-window-tokens 1100000 \
      --output-dir flashfusion/viz/miniexp/results/gpt54_1p1m
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from langchain_core.messages import HumanMessage
from langchain_openrouter import ChatOpenRouter

from flashfusion.viz.miniexp.latencychunks import (
    STYLES,
    _apply_style,
    _tight_layout,
    build_prompt,
    build_token_chunks,
    estimate_tokens,
    measure_streaming_latency,
)

DEFAULT_MODEL = "openai/gpt-5.4"
DEFAULT_CONTEXT_WINDOW = 1_100_000
DEFAULT_MAX_TOKENS = 128
DEFAULT_CHUNK_TOKEN_TARGET = 200
DEFAULT_QUERY = "What is the average MLII observed in this dataset?"
DEFAULT_INPUT_RATE = 2.50


def _rate_for_model(model: str, fallback: float) -> float:
    """Read configured USD/M input pricing, with an explicit CLI fallback."""
    from flashfusion.config import MODEL_RATE_PER_1M_TOKENS

    return float(MODEL_RATE_PER_1M_TOKENS.get(model, {}).get("input", fallback))


def _build_schedule(
    total_chunks: int,
    context_window_tokens: int,
    max_tokens: int,
    overhead_tokens: int,
    points: int,
    actual_token_ratio: float,
    chunk_token_target: int,
    calibrated_max_chunks: int | None = None,
) -> list[int]:
    """Choose chunk counts from a small prompt to just below the context limit."""
    available = context_window_tokens - max_tokens - overhead_tokens
    estimated_tokens_per_chunk = chunk_token_target * actual_token_ratio
    max_chunks = max(1, int(available / estimated_tokens_per_chunk))
    if calibrated_max_chunks is not None:
        max_chunks = min(max_chunks, calibrated_max_chunks)
    return sorted(
        {
            max(1, min(total_chunks, int(round(value))))
            for value in np.linspace(max_chunks / points, max_chunks, points)
        }
    )


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _plot(rows: list[dict[str, Any]], output_dir: Path, context_window_tokens: int) -> None:
    frame = pd.DataFrame(rows)
    successful = frame[frame["success"] & frame["cost_usd"].notna()].copy()
    if successful.empty:
        print("No successful cost rows; skipping plot.")
        return
    successful["cost_scaled"] = successful["cost_usd"] / 1e-3
    successful = successful.sort_values("rows_covered")
    x = successful["fraction_of_ecg_percent"].to_numpy(float)
    y = successful["cost_scaled"].to_numpy(float)
    limit_x = float(successful["context_fraction_percent"].iloc[-1])
    marker_x = max(limit_x * 1.08, x[-1] * 1.12)
    x_right = max(marker_x * 1.15, x[-1] * 1.12)

    st = STYLES["single"]
    _apply_style(st)
    fig, ax = plt.subplots(figsize=st["figsize"], layout="constrained")
    _tight_layout(fig, st)
    ax.plot(x, y, color="#10b981", marker="^", linewidth=2.2, markersize=6, label="Measured cost")
    ax.set_xlim(max(0.0, x[0] * 0.8), x_right)
    ax.axvline(marker_x, color="#64748b", linestyle="--", linewidth=1.0)
    ax.axvspan(marker_x, x_right, color="#dc2626", alpha=0.10)
    ax.text(
        marker_x * 1.01, 0.55, f"{context_window_tokens / 1_000_000:g}M token limit",
        rotation=90, ha="left", va="center", transform=ax.get_xaxis_transform(),
        color="#991b1b", fontweight="bold", style="italic",
    )
    ax.set_xlabel("Fraction of ECG Data (%)", fontweight="bold")
    ax.set_ylabel(r"Cost (\$ $\times$ 10$^{-3}$)", fontweight="bold")
    ax.grid(True, color="#cccccc", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    fig.savefig(output_dir / "ecg_cost.png", dpi=st["dpi"], bbox_inches="tight", pad_inches=0.02)
    fig.savefig(output_dir / "ecg_cost.pdf", bbox_inches="tight", pad_inches=0.02)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure real OpenRouter ECG prompt cost near a context limit.")
    parser.add_argument("--data-path", help="ECG CSV path")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--context-window-tokens", type=int, default=DEFAULT_CONTEXT_WINDOW)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--points", type=int, default=12)
    parser.add_argument("--chunk-token-target", type=int, default=DEFAULT_CHUNK_TOKEN_TARGET)
    parser.add_argument(
        "--actual-token-ratio", type=float, default=2.09,
        help="Fallback actual/nominal chunk-token ratio; calibrated from GPT-5.4 runs",
    )
    parser.add_argument(
        "--calibration-csv",
        help="Prior ecg_cost.csv used to fit measured token growth and cap the new schedule",
    )
    parser.add_argument(
        "--effective-context-window-tokens",
        type=int,
        default=None,
        help="Observed provider limit to use instead of the advertised model limit",
    )
    parser.add_argument("--csv-input", help="Plot an existing ecg_cost.csv without API calls")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--input-rate", type=float, default=None, help="Fallback USD per 1M input tokens")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--output-dir", default="flashfusion/viz/miniexp/results/gpt54_1p1m")
    args = parser.parse_args()
    if args.points < 2:
        parser.error("--points must be at least 2")
    if args.context_window_tokens <= args.max_tokens:
        parser.error("--context-window-tokens must exceed --max-tokens")
    output_dir = Path(args.output_dir)
    if args.csv_input:
        rows = list(csv.DictReader(Path(args.csv_input).open(encoding="utf-8")))
        for row in rows:
            row["success"] = str(row["success"]).lower() in {"true", "1"}
            for key in ("cost_usd", "input_tokens", "rows_covered", "fraction_of_ecg_percent", "context_fraction_percent"):
                if row.get(key) not in (None, ""):
                    row[key] = float(row[key])
        output_dir.mkdir(parents=True, exist_ok=True)
        _plot(rows, output_dir, args.context_window_tokens)
        print(f"Saved {output_dir / 'ecg_cost.png'}")
        print(f"Saved {output_dir / 'ecg_cost.pdf'}")
        return

    if not args.data_path:
        parser.error("--data-path is required unless --csv-input is used")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY environment variable required")

    data = pd.read_csv(args.data_path)
    chunks = build_token_chunks(data, args.chunk_token_target)
    if not chunks:
        raise ValueError("No CSV chunks were created from the dataset.")
    total_rows = len(data)
    overhead_tokens = estimate_tokens(build_prompt(args.query, []))
    calibrated_max_chunks = None
    if args.calibration_csv:
        calibration = pd.read_csv(args.calibration_csv)
        calibration = calibration[calibration["success"] & calibration["input_tokens"].notna()]
        if len(calibration) >= 2:
            slope, intercept = np.polyfit(calibration["chunk_count"], calibration["input_tokens"], 1)
            calibrated_max_chunks = int(calibration["chunk_count"].max())
            print(
                f"Calibration: {slope:.2f} input tokens/chunk + {intercept:.0f} overhead; "
                f"safe observed maximum={calibrated_max_chunks:,} chunks "
                f"({calibration['input_tokens'].max():,.0f} tokens)."
            )
    effective_context = args.effective_context_window_tokens or args.context_window_tokens
    schedule = _build_schedule(
        len(chunks), effective_context, args.max_tokens, overhead_tokens,
        args.points, args.actual_token_ratio, args.chunk_token_target, calibrated_max_chunks,
    )
    rate = args.input_rate if args.input_rate is not None else _rate_for_model(args.model, DEFAULT_INPUT_RATE)
    llm = ChatOpenRouter(
        model=args.model,
        api_key=api_key,
        temperature=0,
        max_tokens=args.max_tokens,
        max_retries=2,
    )
    cumulative_rows = np.cumsum([len(chunk.splitlines()) - 1 for chunk in chunks])
    total_estimated_tokens = overhead_tokens + estimate_tokens("\n\n".join(chunks))
    rows: list[dict[str, Any]] = []

    for point, chunk_count in enumerate(schedule, start=1):
        prompt = build_prompt(args.query, chunks[:chunk_count])
        context_fraction = (overhead_tokens + estimate_tokens("\n\n".join(chunks[:chunk_count]))) / total_estimated_tokens * 100
        row: dict[str, Any] = {
            "point": point,
            "chunk_count": chunk_count,
            "rows_covered": int(cumulative_rows[chunk_count - 1]),
            "fraction_of_ecg_percent": float(cumulative_rows[chunk_count - 1] / total_rows * 100),
            "context_fraction_percent": float(context_fraction),
            "context_window_tokens": args.context_window_tokens,
            "model": args.model,
            "success": False,
            "error": "",
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
            "input_cost_usd_est": None,
            "estimate_type": "provider_measurement",
        }
        for attempt in range(args.retries + 1):
            try:
                measurement = measure_streaming_latency(llm, prompt)
                input_tokens = measurement["input_tokens"]
                output_tokens = measurement["output_tokens"] or 0
                if input_tokens is None:
                    input_tokens = int(round(estimate_tokens(prompt) * args.actual_token_ratio))
                row.update(
                    success=True,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=measurement["cost_usd"],
                    input_cost_usd_est=input_tokens * rate / 1_000_000,
                )
                if row["cost_usd"] is None:
                    row["cost_usd"] = row["input_cost_usd_est"] + output_tokens * 0.0
                break
            except Exception as exc:  # noqa: BLE001 - preserve provider error per point
                row["error"] = str(exc)
                if attempt < args.retries:
                    continue
        rows.append(row)
        status = f"${row['cost_usd']:.4f}" if row["cost_usd"] is not None else f"FAILED: {row['error'][:100]}"
        print(f"{point}/{len(schedule)} chunks={chunk_count:,} input={row['input_tokens']} cost={status}")

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(output_dir / "ecg_cost.csv", rows)
    _plot(rows, output_dir, args.context_window_tokens)
    print(f"Saved {output_dir / 'ecg_cost.csv'}")
    print(f"Saved {output_dir / 'ecg_cost.png'}")
    print(f"Saved {output_dir / 'ecg_cost.pdf'}")


if __name__ == "__main__":
    main()
