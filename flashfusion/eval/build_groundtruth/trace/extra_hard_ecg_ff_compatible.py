"""Staging harness for typed-operator-compatible MIT-ECG queries 17--20.

Every candidate has one terminal typed-executor value. Run the module before
promoting its texts or references into the benchmark::

python -m flashfusion.eval.build_groundtruth.trace.extra_hard_ecg_ff_compatible
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from flashfusion.eval.queries import DATASET_MIT_ECG
from flashfusion.pipeline.loader import load_dataset_by_name
from flashfusion.pipeline.operators import (
    execute_plan,
    structural_validate,
    validate_plan_against_dataframe,
)

DEFAULT_DATA_PATH = "data/AutoIOT_dataset/ECG.0/MIT_arrythmia_v1.txt"
ANNOTATION_CODES = [
    "!", '"', "+", "/", "A", "E", "F", "J", "L", "N", "Q", "R", "S",
    "V", "[", "]", "a", "e", "f", "j", "x", "|", "~",
]


# ---------------------------------------------------------------------------
# Redesigned query text
# ---------------------------------------------------------------------------

NEW_QUERY_TEXT: dict[int, str] = {
    17: (
        "Among rows whose annotation is one of the known MIT-ECG annotation codes, "
        "divide time_s into 10-second bins. For each (record_id, bin) pair, compute "
        "MLII RMS. Return the (record_id, bin) pair with the greatest RMS."
    ),
    18: (
        "For every record_id, independently compute maximum and minimum MLII. "
        "Define MLII span as maximum minus minimum. Return the record_id with "
        "the largest MLII span."
    ),
    19: (
        "For record_id 101, divide time_s into 10-second bins. For each bin, "
        "compute annotated-row rate as rows with an annotation in the known "
        "annotation-code list divided by all rows in the bin. Return the Pearson "
        "correlation between bin index and annotated-row rate."
    ),
    20: (
        "For every record_id, independently compute MLII variance and V1 variance. "
        "Define total lead variability as their sum. Return the record_id with "
        "the largest total lead variability."
    ),
}


# ---------------------------------------------------------------------------
# FLASH_FUSION_RAW_PLANS -- literal, legal plans in the FF vocabulary
# ---------------------------------------------------------------------------

FLASH_FUSION_RAW_PLANS: dict[int, dict[str, Any]] = {
    17: {
        "version": "1",
        "steps": [
            {"op": "FILTER_IN", "column": "annotation", "values": ANNOTATION_CODES},
            {
                "op": "DERIVE_BIN", "column": "time_s", "kind": "numeric",
                "width": 10, "result": "bin_10s",
            },
            {
                "op": "GROUP_AGGREGATE", "group_by": ["record_id", "bin_10s"],
                "aggregate": "rms", "column": "MLII",
            },
            {"op": "RANK_GROUPS", "direction": "max"},
        ],
    },
    18: {
        "version": "1",
        "steps": [
            {
                "op": "PARALLEL_AGGREGATE",
                "branches": [
                    {
                        "filter_column": None,
                        "filter_values": None,
                        "group_by": ["record_id"],
                        "aggregate": "max",
                        "column": "MLII",
                        "result_column": "max_mlii",
                    },
                    {
                        "filter_column": None,
                        "filter_values": None,
                        "group_by": ["record_id"],
                        "aggregate": "min",
                        "column": "MLII",
                        "result_column": "min_mlii",
                    },
                ],
            },
            {
                "op": "DERIVE_BINARY",
                "left": "max_mlii",
                "right": "min_mlii",
                "operation": "abs_difference",
                "result": "mlii_range",
            },
            {
                "op": "RANK_ROWS", "column": "mlii_range", "direction": "max",
                "return_columns": ["record_id", "mlii_range"],
            },
        ],
    },
    19: {
        "version": "1",
        "steps": [
            {"op": "FILTER_COMPARE", "column": "record_id", "comparator": "eq", "value": 101},
            {
                "op": "DERIVE_BIN",
                "column": "time_s",
                "kind": "numeric",
                "width": 10,
                "result": "window_index",
            },
            {
                "op": "PARALLEL_AGGREGATE",
                "branches": [
                    {
                        "filter_column": None,
                        "filter_values": None,
                        "group_by": ["window_index"],
                        "aggregate": "count",
                        "column": None,
                        "result_column": "rows_per_window",
                    },
                    {
                        "filter_column": "annotation",
                        "filter_values": ANNOTATION_CODES,
                        "group_by": ["window_index"],
                        "aggregate": "count",
                        "column": None,
                        "result_column": "annotated_count_per_window",
                    },
                ],
            },
            {
                "op": "DERIVE_BINARY",
                "left": "annotated_count_per_window",
                "right": "rows_per_window",
                "operation": "divide",
                "result": "annotated_rate",
            },
            {"op": "CORRELATE_COLUMNS", "left": "window_index", "right": "annotated_rate", "method": "pearson"},
        ],
    },
    20: {
        "version": "1",
        "steps": [
            {
                "op": "PARALLEL_AGGREGATE",
                "branches": [
                    {
                        "filter_column": None,
                        "filter_values": None,
                        "group_by": ["record_id"],
                        "aggregate": "var",
                        "column": "MLII",
                        "result_column": "mlii_variance",
                    },
                    {
                        "filter_column": None,
                        "filter_values": None,
                        "group_by": ["record_id"],
                        "aggregate": "var",
                        "column": "V1",
                        "result_column": "v1_variance",
                    },
                ],
            },
            {
                "op": "DERIVE_BINARY",
                "left": "mlii_variance",
                "right": "v1_variance",
                "operation": "add",
                "result": "combined_variance",
            },
            {
                "op": "RANK_ROWS", "column": "combined_variance", "direction": "max",
                "return_columns": ["record_id", "combined_variance"],
            },
        ],
    },
}

OPERATOR_SKELETONS: dict[int, list[str]] = {
    query_id: [step["op"] for step in plan["steps"]]
    for query_id, plan in FLASH_FUSION_RAW_PLANS.items()
}


# ---------------------------------------------------------------------------
# Annotation-code verification
# ---------------------------------------------------------------------------


def discover_annotation_codes(df: pd.DataFrame) -> list[str]:
    """Return the sorted list of distinct non-empty annotation codes.

    Hard Rule R5 requires filter values to exist in the schema's sample
    values before they are emitted. Run this once against the loaded MIT-ECG
    dataframe and compare it with the literal ``ANNOTATION_CODES`` before a
    planning run. The literal list is part of the reproducible plan contract.
    """
    codes = df["annotation"].astype(str).str.strip()
    return sorted(codes[codes.ne("")].unique().tolist())


# ---------------------------------------------------------------------------
# Pandas ground truth, mirroring each raw plan step for step
# ---------------------------------------------------------------------------


def build_q17_trace(df: pd.DataFrame) -> dict[str, Any]:
    work = df.copy()
    work["annotation"] = work["annotation"].astype(str).str.strip()
    work["bin_10s"] = (work["time_s"] // 10) * 10
    annotated = work.loc[work["annotation"].isin(ANNOTATION_CODES)]
    bin_rms = (
        annotated.groupby(["record_id", "bin_10s"])["MLII"]
        .apply(lambda values: float(np.sqrt(np.mean(values ** 2))))
        .rename("bin_rms")
        .reset_index()
    )
    top = bin_rms.loc[bin_rms["bin_rms"].idxmax()].to_dict()
    return {
        "record_id": int(top["record_id"]),
        "bin_10s": float(top["bin_10s"]),
        "rms_MLII": float(top["bin_rms"]),
    }


def build_q18_trace(df: pd.DataFrame) -> dict[str, Any]:
    grouped = df.groupby("record_id")["MLII"].agg(["max", "min"]).reset_index()
    grouped["mlii_range"] = (grouped["max"] - grouped["min"]).abs()
    top = grouped.loc[grouped["mlii_range"].idxmax()].to_dict()
    return {
        "record_id": int(top["record_id"]),
        "mlii_range": float(top["mlii_range"]),
    }


def build_q19_trace(df: pd.DataFrame, record_id: int = 101) -> float:
    work = df.copy()
    work["window_index"] = (work["time_s"] // 10) * 10
    work["annotation"] = work["annotation"].astype(str).str.strip()

    rows_per_window = (
        work.groupby(["record_id", "window_index"]).size().rename("rows_per_window").reset_index()
    )
    annotated_per_window = (
        work.loc[work["annotation"].isin(ANNOTATION_CODES)]
        .groupby(["record_id", "window_index"])
        .size()
        .rename("annotated_count_per_window")
        .reset_index()
    )
    merged = rows_per_window.merge(
        annotated_per_window, on=["record_id", "window_index"], how="left"
    ).fillna({"annotated_count_per_window": 0})

    scoped = merged.loc[(merged["record_id"] == record_id) & (merged["rows_per_window"] > 0)]
    scoped = scoped.copy()
    scoped["annotated_rate"] = scoped["annotated_count_per_window"] / scoped["rows_per_window"]

    correlation = float(scoped["window_index"].corr(scoped["annotated_rate"]))
    return round(correlation, 12)


def build_q20_trace(df: pd.DataFrame) -> dict[str, Any]:
    q20 = df.groupby("record_id").agg(
        mlii_variance=("MLII", "var"),
        v1_variance=("V1", "var"),
        duration_s=("time_s", "max"),
    ).reset_index()
    q20["combined_variance"] = q20["mlii_variance"] + q20["v1_variance"]
    top = q20.loc[q20["combined_variance"].idxmax()].to_dict()
    return {
        "record_id": int(top["record_id"]),
        "combined_variance": float(top["combined_variance"]),
    }


PANDAS_BUILDERS: dict[int, Callable[[pd.DataFrame], Any]] = {
    17: build_q17_trace, 18: build_q18_trace, 19: build_q19_trace, 20: build_q20_trace,
}


def compare_answers(df: pd.DataFrame, query_id: int) -> dict[str, Any]:
    """Run both gates and compare the typed terminal value with pandas ground truth."""
    plan = structural_validate(FLASH_FUSION_RAW_PLANS[query_id])
    validate_plan_against_dataframe(plan, df)
    execution = execute_plan(df, plan)
    if not execution.ok:
        raise RuntimeError(execution.error)
    ground_truth = PANDAS_BUILDERS[query_id](df)
    flash_fusion = round(float(execution.value), 12) if query_id == 19 else execution.value
    return {
        "query_id": query_id,
        "ground_truth": ground_truth,
        "flash_fusion": flash_fusion,
        "matches": ground_truth == flash_fusion,
        "operators": plan.operators_used,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=DEFAULT_DATA_PATH)
    parser.add_argument("--query-id", type=int, choices=sorted(FLASH_FUSION_RAW_PLANS), action="append")
    args = parser.parse_args()
    df = load_dataset_by_name(str(Path(args.data)), DATASET_MIT_ECG)
    discovered = discover_annotation_codes(df)
    if discovered != ANNOTATION_CODES:
        raise ValueError(f"Pinned annotation codes differ from dataset values: {discovered!r}")
    for query_id in args.query_id or sorted(FLASH_FUSION_RAW_PLANS):
        print(json.dumps(compare_answers(df, query_id), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
