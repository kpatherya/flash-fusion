"""Staging harness for typed-operator-compatible WISDM queries 17--20.

Run before promoting the query texts and references into the benchmark::

    python -m flashfusion.eval.build_groundtruth.trace.extra_hard_wisdm_ff_compatible
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from flashfusion.eval.queries import DATASET_WISDM
from flashfusion.pipeline.loader import load_dataset_by_name
from flashfusion.pipeline.operators import (
    execute_plan,
    structural_validate,
    validate_plan_against_dataframe,
)

DEFAULT_DATA_PATH = "data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt"
DYNAMIC_ACTIVITIES = ["Walking", "Jogging", "Upstairs", "Downstairs"]
RESTING_ACTIVITIES = ["Sitting", "Standing"]

NEW_QUERY_TEXT: dict[int, str] = {
    17: (
        "For every subject_id, compute mean acceleration magnitude separately for "
        "dynamic activities (Walking, Jogging, Upstairs, Downstairs) and resting "
        "activities (Sitting, Standing). Return the subject_id with the largest "
        "dynamic-minus-resting mean magnitude."
    ),
    18: (
        "For every subject_id, compute x-acceleration variance separately while "
        "Jogging and while Walking. Among subject_id values whose Jogging variance "
        "exceeds their Walking variance, return the subject_id with the largest "
        "Jogging-minus-Walking variance difference."
    ),
    19: (
        "For every subject_id, compute mean acceleration magnitude while Jogging "
        "and while Walking. Return the Pearson correlation between the two per-subject "
        "mean-magnitude columns."
    ),
    20: (
        "For every subject_id, derive elapsed seconds from timestamp, then compute "
        "total locomotion duration (Walking, Jogging, Upstairs, Downstairs) and "
        "total resting duration (Sitting, Standing). Among subjects with more "
        "locomotion than resting time, return the subject_id with the largest "
        "locomotion-minus-resting duration."
    ),
}

FLASH_FUSION_RAW_PLANS: dict[int, dict[str, Any]] = {
    17: {
        "version": "1",
        "steps": [
            {
                "op": "DERIVE_VECTOR_MAGNITUDE",
                "columns": ["x", "y", "z"],
                "result": "magnitude",
            },
            {
                "op": "PARALLEL_AGGREGATE",
                "branches": [
                    {
                        "filter_column": "activity_label",
                        "filter_values": DYNAMIC_ACTIVITIES,
                        "group_by": ["subject_id"],
                        "aggregate": "mean",
                        "column": "magnitude",
                        "result_column": "dynamic_mean_magnitude",
                    },
                    {
                        "filter_column": "activity_label",
                        "filter_values": RESTING_ACTIVITIES,
                        "group_by": ["subject_id"],
                        "aggregate": "mean",
                        "column": "magnitude",
                        "result_column": "resting_mean_magnitude",
                    },
                ],
            },
            {
                "op": "DERIVE_BINARY",
                "left": "dynamic_mean_magnitude",
                "right": "resting_mean_magnitude",
                "operation": "subtract",
                "result": "dynamic_minus_resting",
            },
            {
                "op": "RANK_ROWS",
                "column": "dynamic_minus_resting",
                "direction": "max",
                "return_columns": ["subject_id", "dynamic_minus_resting"],
            },
        ],
    },
    18: {
        "version": "1",
        "steps": [
            {
                "op": "PARALLEL_AGGREGATE",
                "branches": [
                    {
                        "filter_column": "activity_label",
                        "filter_values": ["Jogging"],
                        "group_by": ["subject_id"],
                        "aggregate": "var",
                        "column": "x",
                        "result_column": "jogging_x_variance",
                    },
                    {
                        "filter_column": "activity_label",
                        "filter_values": ["Walking"],
                        "group_by": ["subject_id"],
                        "aggregate": "var",
                        "column": "x",
                        "result_column": "walking_x_variance",
                    },
                ],
            },
            {
                "op": "DERIVE_BINARY",
                "left": "jogging_x_variance",
                "right": "walking_x_variance",
                "operation": "subtract",
                "result": "jogging_minus_walking_variance",
            },
            {
                "op": "FILTER_COMPARE",
                "column": "jogging_minus_walking_variance",
                "comparator": "gt",
                "value": 0,
            },
            {
                "op": "RANK_ROWS",
                "column": "jogging_minus_walking_variance",
                "direction": "max",
                "return_columns": ["subject_id", "jogging_minus_walking_variance"],
            },
        ],
    },
    19: {
        "version": "1",
        "steps": [
            {
                "op": "DERIVE_VECTOR_MAGNITUDE",
                "columns": ["x", "y", "z"],
                "result": "magnitude",
            },
            {
                "op": "PARALLEL_AGGREGATE",
                "branches": [
                    {
                        "filter_column": "activity_label",
                        "filter_values": ["Jogging"],
                        "group_by": ["subject_id"],
                        "aggregate": "mean",
                        "column": "magnitude",
                        "result_column": "jogging_mean_magnitude",
                    },
                    {
                        "filter_column": "activity_label",
                        "filter_values": ["Walking"],
                        "group_by": ["subject_id"],
                        "aggregate": "mean",
                        "column": "magnitude",
                        "result_column": "walking_mean_magnitude",
                    },
                ],
            },
            {
                "op": "CORRELATE_COLUMNS",
                "left": "jogging_mean_magnitude",
                "right": "walking_mean_magnitude",
                "method": "pearson",
            },
        ],
    },
    20: {
        "version": "1",
        "steps": [
            {
                "op": "DERIVE_DURATION_SECONDS",
                "timestamp_column": "timestamp",
                "group_by": ["subject_id"],
                "result": "dt_s",
                "clip_negative": True,
                "fill_first": 0.0,
            },
            {
                "op": "PARALLEL_AGGREGATE",
                "branches": [
                    {
                        "filter_column": "activity_label",
                        "filter_values": DYNAMIC_ACTIVITIES,
                        "group_by": ["subject_id"],
                        "aggregate": "sum",
                        "column": "dt_s",
                        "result_column": "locomotion_duration_s",
                    },
                    {
                        "filter_column": "activity_label",
                        "filter_values": RESTING_ACTIVITIES,
                        "group_by": ["subject_id"],
                        "aggregate": "sum",
                        "column": "dt_s",
                        "result_column": "resting_duration_s",
                    },
                ],
            },
            {
                "op": "DERIVE_BINARY",
                "left": "locomotion_duration_s",
                "right": "resting_duration_s",
                "operation": "subtract",
                "result": "locomotion_minus_resting_s",
            },
            {
                "op": "FILTER_COMPARE",
                "column": "locomotion_minus_resting_s",
                "comparator": "gt",
                "value": 0,
            },
            {
                "op": "RANK_ROWS",
                "column": "locomotion_minus_resting_s",
                "direction": "max",
                "return_columns": ["subject_id", "locomotion_minus_resting_s"],
            },
        ],
    },
}


def _top_record(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    return frame.loc[frame[column].idxmax()].to_dict()


def build_q17_trace(df: pd.DataFrame) -> dict[str, Any]:
    work = df.copy()
    work["magnitude"] = np.sqrt(work["x"] ** 2 + work["y"] ** 2 + work["z"] ** 2)
    dynamic = work.loc[work["activity_label"].isin(DYNAMIC_ACTIVITIES)].groupby("subject_id")["magnitude"].mean()
    resting = work.loc[work["activity_label"].isin(RESTING_ACTIVITIES)].groupby("subject_id")["magnitude"].mean()
    result = pd.concat([dynamic.rename("dynamic_mean_magnitude"), resting.rename("resting_mean_magnitude")], axis=1).dropna().reset_index()
    result["dynamic_minus_resting"] = result["dynamic_mean_magnitude"] - result["resting_mean_magnitude"]
    top = _top_record(result, "dynamic_minus_resting")
    return {"subject_id": int(top["subject_id"]), "dynamic_minus_resting": float(top["dynamic_minus_resting"])}


def build_q18_trace(df: pd.DataFrame) -> dict[str, Any]:
    jogging = df.loc[df["activity_label"] == "Jogging"].groupby("subject_id")["x"].var()
    walking = df.loc[df["activity_label"] == "Walking"].groupby("subject_id")["x"].var()
    result = pd.concat([jogging.rename("jogging_x_variance"), walking.rename("walking_x_variance")], axis=1).dropna().reset_index()
    result["jogging_minus_walking_variance"] = result["jogging_x_variance"] - result["walking_x_variance"]
    top = _top_record(result.loc[result["jogging_minus_walking_variance"] > 0], "jogging_minus_walking_variance")
    return {"subject_id": int(top["subject_id"]), "jogging_minus_walking_variance": float(top["jogging_minus_walking_variance"])}


def build_q19_trace(df: pd.DataFrame) -> float:
    work = df.copy()
    work["magnitude"] = np.sqrt(work["x"] ** 2 + work["y"] ** 2 + work["z"] ** 2)
    jogging = work.loc[work["activity_label"] == "Jogging"].groupby("subject_id")["magnitude"].mean()
    walking = work.loc[work["activity_label"] == "Walking"].groupby("subject_id")["magnitude"].mean()
    result = pd.concat([jogging.rename("jogging_mean_magnitude"), walking.rename("walking_mean_magnitude")], axis=1).dropna()
    return round(float(result["jogging_mean_magnitude"].corr(result["walking_mean_magnitude"])), 12)


def build_q20_trace(df: pd.DataFrame) -> dict[str, Any]:
    work = df.sort_values(["subject_id", "timestamp"]).copy()
    work["dt_s"] = work.groupby("subject_id")["timestamp"].diff().clip(lower=0).fillna(0) / 1_000_000_000
    locomotion = work.loc[work["activity_label"].isin(DYNAMIC_ACTIVITIES)].groupby("subject_id")["dt_s"].sum()
    resting = work.loc[work["activity_label"].isin(RESTING_ACTIVITIES)].groupby("subject_id")["dt_s"].sum()
    result = pd.concat([locomotion.rename("locomotion_duration_s"), resting.rename("resting_duration_s")], axis=1).fillna(0.0).reset_index()
    result["locomotion_minus_resting_s"] = result["locomotion_duration_s"] - result["resting_duration_s"]
    top = _top_record(result.loc[result["locomotion_minus_resting_s"] > 0], "locomotion_minus_resting_s")
    return {"subject_id": int(top["subject_id"]), "locomotion_minus_resting_s": float(top["locomotion_minus_resting_s"])}


PANDAS_BUILDERS: dict[int, Callable[[pd.DataFrame], Any]] = {
    17: build_q17_trace,
    18: build_q18_trace,
    19: build_q19_trace,
    20: build_q20_trace,
}


def compare_answers(df: pd.DataFrame, query_id: int) -> dict[str, Any]:
    """Run both validation gates and compare typed execution to pandas ground truth."""
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
    df = load_dataset_by_name(str(Path(args.data)), DATASET_WISDM)
    for query_id in args.query_id or sorted(FLASH_FUSION_RAW_PLANS):
        print(json.dumps(compare_answers(df, query_id), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()