"""Staging harness for typed-operator-compatible bus queries 17--20.

Run before promoting the query texts and references into the benchmark::

    python -m flashfusion.eval.build_groundtruth.trace.extra_hard_bus_ff_compatible
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from flashfusion.eval.queries import DATASET_BUS
from flashfusion.pipeline.loader import load_dataset_by_name
from flashfusion.pipeline.operators import (
    execute_plan,
    structural_validate,
    validate_plan_against_dataframe,
)

DEFAULT_DATA_PATH = "data/bus/bus_data_enriched_behavior.csv"

NEW_QUERY_TEXT: dict[int, str] = {
    17: (
        "Filter the route to rows labeled aggressive, group them into 5-minute "
        "timestamp windows, and return the window with the highest mean "
        "instability_score."
    ),
    18: (
        "Derive peak acceleration magnitude from accel_stats_x_p99, "
        "accel_stats_y_p99, and accel_stats_z_p99. Split the route at the median "
        "latitude and report the absolute difference between the northern and "
        "southern halves' mean peak magnitudes."
    ),
    19: (
        "Derive the vertical shock range as accel_stats_z_p99 minus "
        "accel_stats_z_p1. Compute its mean separately for aggressive and calm "
        "behavior labels, then report the aggressive-minus-calm difference."
    ),
    20: (
        "Derive the vertical shock range as accel_stats_z_p99 minus "
        "accel_stats_z_p1. Filter to aggressive behavior, group rows into "
        "5-minute timestamp windows, and return the window with the highest mean "
        "vertical shock range."
    ),
}

FLASH_FUSION_RAW_PLANS: dict[int, dict[str, Any]] = {
    17: {
        "version": "1",
        "steps": [
            {"op": "FILTER_IN", "column": "behavior", "values": ["aggressive"]},
            {
                "op": "GROUP_AGGREGATE",
                "group_by": ["timestamp"],
                "freq": "5min",
                "aggregate": "mean",
                "column": "instability_score",
            },
            {"op": "RANK_GROUPS", "direction": "max"},
        ],
    },
    18: {
        "version": "1",
        "steps": [
            {
                "op": "DERIVE_VECTOR_MAGNITUDE",
                "columns": [
                    "accel_stats_x_p99",
                    "accel_stats_y_p99",
                    "accel_stats_z_p99",
                ],
                "result": "peak_acceleration_magnitude",
            },
            {
                "op": "SPLIT_BY_THRESHOLD",
                "column": "latitude",
                "comparator": "gt",
                "threshold": "median",
                "label": "north",
            },
            {
                "op": "SPLIT_BY_THRESHOLD",
                "column": "latitude",
                "comparator": "lte",
                "threshold": "median",
                "label": "south",
            },
            {
                "op": "AGGREGATE_PARTITIONS",
                "partitions": ["north", "south"],
                "aggregate": "mean",
                "column": "peak_acceleration_magnitude",
            },
            {"op": "COMPARE_PARTITIONS", "mode": "abs_difference"},
        ],
    },
    19: {
        "version": "1",
        "steps": [
            {
                "op": "DERIVE_BINARY",
                "left": "accel_stats_z_p99",
                "right": "accel_stats_z_p1",
                "operation": "subtract",
                "result": "vertical_shock_range",
            },
            {
                "op": "SPLIT_BY_VALUES",
                "column": "behavior",
                "values": ["aggressive"],
                "label": "aggressive",
            },
            {
                "op": "SPLIT_BY_VALUES",
                "column": "behavior",
                "values": ["calm"],
                "label": "calm",
            },
            {
                "op": "AGGREGATE_PARTITIONS",
                "partitions": ["aggressive", "calm"],
                "aggregate": "mean",
                "column": "vertical_shock_range",
            },
            {"op": "COMPARE_PARTITIONS", "mode": "difference"},
        ],
    },
    20: {
        "version": "1",
        "steps": [
            {
                "op": "DERIVE_BINARY",
                "left": "accel_stats_z_p99",
                "right": "accel_stats_z_p1",
                "operation": "subtract",
                "result": "vertical_shock_range",
            },
            {"op": "FILTER_IN", "column": "behavior", "values": ["aggressive"]},
            {
                "op": "GROUP_AGGREGATE",
                "group_by": ["timestamp"],
                "freq": "5min",
                "aggregate": "mean",
                "column": "vertical_shock_range",
            },
            {"op": "RANK_GROUPS", "direction": "max"},
        ],
    },
}


def build_q17_trace(df: pd.DataFrame) -> dict[str, Any]:
    grouped = (
        df.loc[df["behavior"] == "aggressive"]
        .groupby(pd.Grouper(key="timestamp", freq="5min"))["instability_score"]
        .mean()
    )
    top_timestamp = grouped.idxmax()
    return {
        "timestamp": top_timestamp.isoformat(),
        "mean_instability_score": float(grouped.loc[top_timestamp]),
    }


def build_q18_trace(df: pd.DataFrame) -> dict[str, float]:
    work = df.copy()
    work["peak_acceleration_magnitude"] = (
        work["accel_stats_x_p99"].pow(2)
        + work["accel_stats_y_p99"].pow(2)
        + work["accel_stats_z_p99"].pow(2)
    ).pow(0.5)
    median_latitude = work["latitude"].median()
    north = work.loc[work["latitude"] > median_latitude, "peak_acceleration_magnitude"].mean()
    south = work.loc[work["latitude"] <= median_latitude, "peak_acceleration_magnitude"].mean()
    return {
        "higher": "north" if north >= south else "south",
        "lower": "south" if north >= south else "north",
        "metric": "mean peak_acceleration_magnitude",
        "north": float(north),
        "south": float(south),
        "abs_difference": float(abs(north - south)),
    }


def build_q19_trace(df: pd.DataFrame) -> dict[str, float]:
    work = df.copy()
    work["vertical_shock_range"] = work["accel_stats_z_p99"] - work["accel_stats_z_p1"]
    aggressive = work.loc[work["behavior"] == "aggressive", "vertical_shock_range"].mean()
    calm = work.loc[work["behavior"] == "calm", "vertical_shock_range"].mean()
    return {
        "higher": "aggressive" if aggressive >= calm else "calm",
        "lower": "calm" if aggressive >= calm else "aggressive",
        "metric": "mean vertical_shock_range",
        "aggressive": float(aggressive),
        "calm": float(calm),
        "difference": float(aggressive - calm),
    }


def build_q20_trace(df: pd.DataFrame) -> dict[str, Any]:
    work = df.copy()
    work["vertical_shock_range"] = work["accel_stats_z_p99"] - work["accel_stats_z_p1"]
    grouped = (
        work.loc[work["behavior"] == "aggressive"]
        .groupby(pd.Grouper(key="timestamp", freq="5min"))["vertical_shock_range"]
        .mean()
    )
    top_timestamp = grouped.idxmax()
    return {
        "timestamp": top_timestamp.isoformat(),
        "mean_vertical_shock_range": float(grouped.loc[top_timestamp]),
    }


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
    return {
        "query_id": query_id,
        "ground_truth": ground_truth,
        "flash_fusion": execution.value,
        "matches": ground_truth == execution.value,
        "operators": plan.operators_used,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=DEFAULT_DATA_PATH)
    parser.add_argument(
        "--query-id",
        type=int,
        choices=sorted(FLASH_FUSION_RAW_PLANS),
        action="append",
    )
    args = parser.parse_args()
    df = load_dataset_by_name(str(Path(args.data)), DATASET_BUS)
    for query_id in args.query_id or sorted(FLASH_FUSION_RAW_PLANS):
        print(json.dumps(compare_answers(df, query_id), indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    main()