"""Generate deterministic references and stage traces for extra-hard IDs 17--20.

This module computes the intended pandas semantics directly, rather than using
the typed executor. It therefore establishes that the questions are answerable
from the supplied data even when a long typed plan is rejected or truncated.

Example:
    python -m flashfusion.eval.build_groundtruth.generate_extra_hard_ground_truth \
      --dataset wisdm \
      --output flashfusion/eval/ground_truth/ground_truth_wisdm.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from flashfusion.eval.queries import (
    DATASET_BUS,
    DATASET_MIT_ECG,
    DATASET_WISDM,
    get_queries,
)
from flashfusion.pipeline.loader import load_dataset_by_name

EXTRA_HARD_IDS = (17, 18, 19, 20)
DEFAULT_DATA_PATHS = {
    DATASET_WISDM: "data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt",
    DATASET_MIT_ECG: "data/AutoIOT_dataset/ECG.0/MIT_arrythmia_v1.txt",
    DATASET_BUS: "data/bus/bus_data_enriched_behavior.csv",
}
DEFAULT_OUTPUT_PATHS = {
    DATASET_WISDM: "flashfusion/eval/ground_truth/ground_truth_wisdm.json",
    DATASET_MIT_ECG: "flashfusion/eval/ground_truth/ground_truth_mit_ecg.json",
    DATASET_BUS: "flashfusion/eval/ground_truth/ground_truth_bus.json",
}


def _json_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if pd.isna(value):
        return None
    return value


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    return [
        {column: _json_value(row[column]) for column in columns}
        for _, row in frame.loc[:, columns].iterrows()
    ]


def _stage(name: str, value: Any) -> dict[str, Any]:
    return {"stage": name, "value": _json_value(value)}


def _entry(query_id: int, query_text: str, answer: str, trace: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "query_text": query_text,
        "reference_answer": answer,
        "expected_rejection": False,
        "ground_truth_method": "extra_hard_composition_v1",
        "stage_trace": trace,
    }


def _wisdm_entries(df: pd.DataFrame, query_texts: dict[int, str]) -> list[dict[str, Any]]:
    work = df.copy()
    work["activity_label"] = work["activity_label"].astype(str).str.strip()
    work["activity_lower"] = work["activity_label"].str.lower()
    work["magnitude"] = np.sqrt(work["x"] ** 2 + work["y"] ** 2 + work["z"] ** 2)
    dynamic = {"walking", "jogging", "upstairs", "downstairs"}
    resting = {"sitting", "standing"}

    dynamic_mean = work.loc[work["activity_lower"].isin(dynamic)].groupby("subject_id")["magnitude"].mean()
    resting_mean = work.loc[work["activity_lower"].isin(resting)].groupby("subject_id")["magnitude"].mean()
    q17 = pd.concat([dynamic_mean.rename("dynamic_mean"), resting_mean.rename("resting_mean")], axis=1).dropna()
    q17["difference"] = q17["dynamic_mean"] - q17["resting_mean"]
    q17 = q17.reset_index().sort_values(["difference", "subject_id"], ascending=[False, True], kind="stable")
    q17_top = q17.iloc[0]
    q17_trace = [
        _stage("stage_1_DeriveVectorMagnitude", {"column": "magnitude", "rows": len(work)}),
        _stage("stage_2_ParallelAggregate_partition_means", _records(q17, ["subject_id", "dynamic_mean", "resting_mean"])),
        _stage("stage_3_DeriveBinary_dynamic_minus_resting", _records(q17, ["subject_id", "difference"])),
        _stage("stage_4_RankRows_difference_desc", _records(q17.head(1), ["subject_id", "difference"])),
    ]

    jogging = work.loc[work["activity_lower"] == "jogging"]
    jogging_counts = jogging.groupby("subject_id").size().rename("jogging_sample_count")
    eligible = jogging_counts[jogging_counts >= 200].index
    # 200 samples equals 10 seconds at 20 Hz; 1.5x is the planned variance-noise threshold.
    jogging_var = jogging.groupby("subject_id")["x"].var().rename("jogging_x_variance")
    walking_var = work.loc[work["activity_lower"] == "walking"].groupby("subject_id")["x"].var().rename("walking_x_variance")
    q18 = pd.concat([jogging_counts, jogging_var, walking_var], axis=1).loc[eligible].dropna()
    q18["variance_ratio"] = q18["jogging_x_variance"] / q18["walking_x_variance"]
    q18 = q18[q18["variance_ratio"] > 1.5].copy()
    duration_work = work.sort_values(["subject_id", "timestamp"], kind="stable").copy()
    duration_work["dt_s"] = (
        duration_work.groupby("subject_id")["timestamp"].diff().clip(lower=0).fillna(0) / 1_000_000_000
    )
    jogging_duration = duration_work.loc[duration_work["activity_lower"] == "jogging"].groupby("subject_id")["dt_s"].sum()
    median_jogging_duration = float(jogging_duration.median())
    q18["jogging_duration_s"] = q18.index.map(jogging_duration).fillna(0.0)
    q18["duration_bin"] = np.where(q18["jogging_duration_s"] > median_jogging_duration, "above_median", "at_or_below_median")
    q18_counts = q18.groupby("duration_bin").size().reindex(["above_median", "at_or_below_median"], fill_value=0)
    q18_trace = [
        _stage("stage_1_GroupAggregate_jogging_sample_count", _json_value(jogging_counts.to_dict())),
        _stage("stage_2_ParallelAggregate_x_variances", _records(q18.reset_index(), ["subject_id", "jogging_x_variance", "walking_x_variance"])),
        _stage("stage_3_FilterCompare_variance_ratio_gt_1_5", _records(q18.reset_index(), ["subject_id", "variance_ratio"])),
        _stage("stage_4_DeriveDurationSeconds_jogging", _json_value(jogging_duration.to_dict())),
        _stage("stage_5_Median_jogging_duration_s", median_jogging_duration),
        _stage("stage_6_GroupAggregate_duration_bin_count", _json_value(q18_counts.to_dict())),
    ]

    group_counts = work.groupby(["subject_id", "activity_label"]).size().rename("sample_count")
    group_y_mean = work.groupby(["subject_id", "activity_label"])["y"].mean().rename("mean_y")
    q19_groups = pd.concat([group_counts, group_y_mean], axis=1).reset_index()
    q19_groups = q19_groups[q19_groups["sample_count"] >= 50]
    q19_top = (
        q19_groups.sort_values(["activity_label", "mean_y", "subject_id"], ascending=[True, False, True], kind="stable")
        .groupby("activity_label", as_index=False)
        .head(1)
    )
    subject_summary = work.groupby("subject_id").agg(overall_sample_count=("subject_id", "size"), mean_magnitude=("magnitude", "mean"))
    q19_selected = q19_top.join(subject_summary, on="subject_id")
    q19_corr = float(q19_selected["overall_sample_count"].corr(q19_selected["mean_magnitude"]))
    q19_trace = [
        _stage("stage_1_GroupAggregate_group_sample_count", _records(q19_groups, ["subject_id", "activity_label", "sample_count"])),
        _stage("stage_2_GroupAggregate_mean_y", _records(q19_groups, ["subject_id", "activity_label", "mean_y"])),
        _stage("stage_3_RankGroups_per_activity", _records(q19_selected, ["activity_label", "subject_id", "mean_y"])),
        _stage("stage_4_DeriveVectorMagnitude_and_subject_aggregates", _records(q19_selected, ["activity_label", "subject_id", "overall_sample_count", "mean_magnitude"])),
        _stage("stage_5_CorrelateColumns", q19_corr),
    ]

    chronological = work.sort_values("timestamp", kind="stable").reset_index(drop=True)
    partitions = np.array_split(np.arange(len(chronological)), 5)
    q20 = pd.DataFrame(
        [
            {
                "partition": index + 1,
                "mean_magnitude": float(chronological.iloc[rows]["magnitude"].mean()),
                "distinct_subject_ids": int(chronological.iloc[rows]["subject_id"].nunique()),
            }
            for index, rows in enumerate(partitions)
        ]
    ).sort_values(["mean_magnitude", "partition"], ascending=[False, True], kind="stable")
    q20_top, q20_bottom = q20.iloc[0], q20.iloc[-1]
    q20_ratio = float(q20_top["distinct_subject_ids"] / q20_bottom["distinct_subject_ids"])
    q20_trace = [
        _stage("stage_1_ChronologicalQuintilePartition", {"sort": "timestamp stable", "partition_sizes": [len(rows) for rows in partitions]}),
        _stage("stage_2_DeriveVectorMagnitude", {"column": "magnitude", "rows": len(chronological)}),
        _stage("stage_3_AggregatePartitions", _records(q20, ["partition", "mean_magnitude", "distinct_subject_ids"])),
        _stage("stage_4_Rank_and_ComparePartitions", {"top_partition": int(q20_top["partition"]), "bottom_partition": int(q20_bottom["partition"]), "ratio": q20_ratio}),
    ]

    return [
        _entry(17, query_texts[17], f"Top subject_id is {int(q17_top['subject_id'])}; dynamic-minus-resting mean magnitude is {float(q17_top['difference']):.2f}.", q17_trace),
        _entry(18, query_texts[18], f"Retained subject_id counts: above median Jogging duration = {int(q18_counts['above_median'])}; at or below median = {int(q18_counts['at_or_below_median'])}.", q18_trace),
        _entry(19, query_texts[19], f"Top subject_id per activity: {_records(q19_selected, ['activity_label', 'subject_id'])}. Pearson correlation is {q19_corr:.4f}.", q19_trace),
        _entry(20, query_texts[20], f"The distinct-subject_id count ratio of highest to lowest mean-magnitude chronological partition is {q20_ratio:.4f}.", q20_trace),
    ]


def _ecg_entries(df: pd.DataFrame, query_texts: dict[int, str]) -> list[dict[str, Any]]:
    work = df.copy()
    work["annotation"] = work["annotation"].astype(str).str.strip()
    work["annotated"] = work["annotation"].ne("")

    annotated = work.loc[work["annotated"]].copy()
    annotated["bin_10s"] = np.floor(annotated["time_s"] / 10).astype(int)
    q17_bins = annotated.groupby(["record_id", "bin_10s"])["MLII"].apply(lambda values: float(np.sqrt(np.mean(values**2)))).rename("rms_mlii").reset_index()
    q17_per_record = q17_bins.sort_values(["record_id", "rms_mlii", "bin_10s"], ascending=[True, False, True], kind="stable").groupby("record_id", as_index=False).head(1)
    q17_top = q17_per_record.sort_values(["rms_mlii", "record_id", "bin_10s"], ascending=[False, True, True], kind="stable").iloc[0]
    q17_trace = [
        _stage("stage_1_FilterNotEmpty_annotation", {"rows": len(annotated)}),
        _stage("stage_2_DeriveBin_10_seconds", {"column": "time_s", "bin_count": int(annotated["bin_10s"].nunique())}),
        _stage("stage_3_GroupAggregate_RMS", _records(q17_per_record, ["record_id", "bin_10s", "rms_mlii"])),
        _stage("stage_4_RankGroups_top_record", _records(pd.DataFrame([q17_top]), ["record_id", "bin_10s", "rms_mlii"])),
    ]

    ranges = work.groupby("record_id")["MLII"].agg(lambda values: float(values.max() - values.min())).rename("mlii_range")
    annotated_counts = work.loc[work["annotated"]].groupby("record_id").size().rename("annotated_beat_count")
    q18 = pd.concat([ranges, annotated_counts], axis=1).fillna(0).reset_index()
    median_count = float(q18["annotated_beat_count"].median())
    q18["beat_count_group"] = np.where(q18["annotated_beat_count"] > median_count, "above_median", "at_or_below_median")
    q18_means = q18.groupby("beat_count_group")["mlii_range"].mean().reindex(["above_median", "at_or_below_median"], fill_value=np.nan)
    q18_difference = float(q18_means["above_median"] - q18_means["at_or_below_median"])
    q18_higher = "above_median" if q18_difference >= 0 else "at_or_below_median"
    q18_trace = [
        _stage("stage_1_ParallelAggregate_MLII_range_and_annotated_count", _records(q18, ["record_id", "mlii_range", "annotated_beat_count"])),
        _stage("stage_2_AggregateColumn_median_annotated_count", median_count),
        _stage("stage_3_SplitByThreshold_annotated_count", _records(q18, ["record_id", "beat_count_group"])),
        _stage("stage_4_AggregatePartitions_mean_range", _json_value(q18_means.to_dict())),
        _stage("stage_5_ComparePartitions", {"higher": q18_higher, "difference": q18_difference}),
    ]

    q19_work = work.loc[work["record_id"] == 101].copy()
    q19_work["window_index"] = np.floor(q19_work["time_s"] / 10).astype(int)
    windows = q19_work.groupby("window_index").size().rename("rows")
    annotated_per_window = q19_work.loc[q19_work["annotated"]].groupby("window_index").size().reindex(windows.index, fill_value=0).rename("annotated_beat_count")
    q19 = annotated_per_window.reset_index()
    q19_corr = float(q19["window_index"].corr(q19["annotated_beat_count"]))
    q19_trace = [
        _stage("stage_1_FilterCompare_record_id_101", {"rows": len(q19_work)}),
        _stage("stage_2_DeriveBin_10_seconds", {"window_count": len(q19)}),
        _stage("stage_3_GroupAggregate_annotated_beat_count", _records(q19, ["window_index", "annotated_beat_count"])),
        _stage("stage_4_CorrelateColumns", q19_corr),
    ]

    q20 = work.groupby("record_id").agg(mlii_variance=("MLII", "var"), v1_variance=("V1", "var"), duration_s=("time_s", "max")).reset_index()
    top_mlii = q20.sort_values(["mlii_variance", "record_id"], ascending=[False, True], kind="stable").head(5)["record_id"]
    top_v1 = q20.sort_values(["v1_variance", "record_id"], ascending=[False, True], kind="stable").head(5)["record_id"]
    overlap = sorted(set(top_mlii).intersection(top_v1))
    overlap_duration = float(q20.loc[q20["record_id"].isin(overlap), "duration_s"].mean())
    overall_duration = float(q20["duration_s"].mean())
    q20_difference = abs(overlap_duration - overall_duration)
    q20_trace = [
        _stage("stage_1_GroupAggregate_variances", _records(q20, ["record_id", "mlii_variance", "v1_variance"])),
        _stage("stage_2_RankRows_top_5_per_metric", {"top_mlii": [int(value) for value in top_mlii], "top_v1": [int(value) for value in top_v1]}),
        _stage("stage_3_FilterIn_top_5_intersection", {"record_ids": [int(value) for value in overlap]}),
        _stage("stage_4_Aggregate_and_Compare_duration", {"overlap_mean_duration_s": overlap_duration, "overall_mean_duration_s": overall_duration, "absolute_difference_s": q20_difference}),
    ]

    return [
        _entry(17, query_texts[17], f"Top record_id is {int(q17_top['record_id'])}; its top 10-second bin is {int(q17_top['bin_10s'])} and RMS MLII is {float(q17_top['rms_mlii']):.4f}.", q17_trace),
        _entry(18, query_texts[18], f"The {q18_higher} annotated-beat-count group has the larger mean MLII range; above-minus-at-or-below difference is {q18_difference:.4f}.", q18_trace),
        _entry(19, query_texts[19], f"The Pearson correlation between 10-second window index and annotated-beat count for record_id 101 is {q19_corr:.3f}.", q19_trace),
        _entry(20, query_texts[20], f"Top-5 variance intersection record_id values are {overlap}; the absolute duration-mean difference is {q20_difference:.4f} seconds.", q20_trace),
    ]


def _bus_entries(df: pd.DataFrame, query_texts: dict[int, str]) -> list[dict[str, Any]]:
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce")
    work = work.dropna(subset=["timestamp"]).reset_index(drop=True)

    q17_work = work.copy()
    q17_work["minute"] = q17_work["timestamp"].dt.floor("1min")
    q17 = q17_work.groupby("minute").agg(mean_instability_score=("instability_score", "mean"), mean_accel_variance=("accel_variance", "mean")).reset_index()
    q17 = q17.sort_values(["mean_instability_score", "minute"], ascending=[False, True], kind="stable")
    q17_top_count = max(1, math.ceil(len(q17) * 0.10))
    q17_top = q17.head(q17_top_count)
    q17_corr = float(q17_top["mean_accel_variance"].corr(q17_top["mean_instability_score"]))
    q17_trace = [
        _stage("stage_1_DeriveBin_1_minute", {"bin_count": len(q17)}),
        _stage("stage_2_GroupAggregate_dual_means", _records(q17, ["minute", "mean_instability_score", "mean_accel_variance"])),
        _stage("stage_3_RankRows_and_Select_top_decile", _records(q17_top, ["minute", "mean_instability_score", "mean_accel_variance"])),
        _stage("stage_4_CorrelateColumns", q17_corr),
    ]

    work["peak_magnitude"] = np.sqrt(work["accel_stats_x_p99"] ** 2 + work["accel_stats_y_p99"] ** 2 + work["accel_stats_z_p99"] ** 2)
    latitude_median = float(work["latitude"].median())
    north = work[work["latitude"] > latitude_median]
    south = work[work["latitude"] <= latitude_median]
    q18 = pd.DataFrame(
        {
            "half": ["north", "south"],
            "mean_peak_magnitude": [float(north["peak_magnitude"].mean()), float(south["peak_magnitude"].mean())],
            "variance_gt_0_20_count": [int((north["accel_variance"] > 0.20).sum()), int((south["accel_variance"] > 0.20).sum())],
        }
    )
    magnitude_higher = q18.loc[q18["mean_peak_magnitude"].idxmax(), "half"]
    count_higher = q18.loc[q18["variance_gt_0_20_count"].idxmax(), "half"]
    q18_verdict = str(magnitude_higher) if magnitude_higher == count_higher else "disagreement"
    q18_trace = [
        _stage("stage_1_DeriveVectorMagnitude_peak", {"column": "peak_magnitude", "rows": len(work)}),
        _stage("stage_2_SplitByThreshold_latitude_median", {"median": latitude_median, "north_rows": len(north), "south_rows": len(south)}),
        _stage("stage_3_AggregatePartitions_dual_metrics", _records(q18, ["half", "mean_peak_magnitude", "variance_gt_0_20_count"])),
        _stage("stage_4_ComparePartitions", {"magnitude_higher": magnitude_higher, "count_higher": count_higher, "verdict": q18_verdict}),
    ]

    q19_work = work.copy()
    q19_work["bin_5min"] = q19_work["timestamp"].dt.floor("5min")
    q19_work["vertical_range"] = q19_work["accel_stats_z_p99"] - q19_work["accel_stats_z_p1"]
    q19_bins = q19_work.groupby("bin_5min").agg(mean_vertical_range=("vertical_range", "mean"), mean_extreme_event_magnitude=("extreme_event_magnitude", "mean")).reset_index()
    q19_top = q19_bins.sort_values(["mean_vertical_range", "bin_5min"], ascending=[False, True], kind="stable").head(3)
    q19_labels = q19_work.loc[q19_work["bin_5min"].isin(q19_top["bin_5min"])].groupby("behavior").size().rename("count").reset_index()
    q19_labels = q19_labels.sort_values(["count", "behavior"], ascending=[False, True], kind="stable")
    q19_top_label = str(q19_labels.iloc[0]["behavior"])
    q19_trace = [
        _stage("stage_1_DeriveBin_5_minutes_and_vertical_range", {"bin_count": len(q19_bins)}),
        _stage("stage_2_GroupAggregate_bin_metrics", _records(q19_bins, ["bin_5min", "mean_vertical_range", "mean_extreme_event_magnitude"])),
        _stage("stage_3_RankRows_Select_top_3_bins", _records(q19_top, ["bin_5min", "mean_vertical_range"])),
        _stage("stage_4_GroupAggregate_behavior_distribution", _records(q19_labels, ["behavior", "count"])),
    ]

    q20_work = work.copy()
    q20_work["minute"] = q20_work["timestamp"].dt.floor("1min")
    q20 = q20_work.groupby("minute").agg(mean_accel_mean=("accel_mean", "mean"), mean_accel_variance=("accel_variance", "mean"), mean_instability_score=("instability_score", "mean")).reset_index()
    q20["variance_quartile"] = pd.qcut(q20["mean_accel_variance"].rank(method="first"), q=4, labels=["Q1", "Q2", "Q3", "Q4"])
    roughest = float(q20.loc[q20["variance_quartile"] == "Q4", "mean_instability_score"].mean())
    smoothest = float(q20.loc[q20["variance_quartile"] == "Q1", "mean_instability_score"].mean())
    q20_ratio = roughest / smoothest if smoothest else float("nan")
    q20_trace = [
        _stage("stage_1_DeriveBin_1_minute", {"bin_count": len(q20)}),
        _stage("stage_2_GroupAggregate_minute_means", _records(q20, ["minute", "mean_accel_mean", "mean_accel_variance", "mean_instability_score"])),
        _stage("stage_3_QuartileSplit_mean_accel_variance", _records(q20, ["minute", "variance_quartile"])),
        _stage("stage_4_Aggregate_and_Compare_quartiles", {"roughest_mean_instability_score": roughest, "smoothest_mean_instability_score": smoothest, "ratio": q20_ratio}),
    ]

    return [
        _entry(17, query_texts[17], f"The top-decile 1-minute-bin Pearson correlation between mean accel_variance and mean instability_score is {q17_corr:.4f}.", q17_trace),
        _entry(18, query_texts[18], f"The two criteria yield {q18_verdict}. Mean peak-magnitude winner is {magnitude_higher}; accel_variance > 0.20 count winner is {count_higher}.", q18_trace),
        _entry(19, query_texts[19], f"The most frequent behavior label across the top three 5-minute range bins is {q19_top_label}.", q19_trace),
        _entry(20, query_texts[20], f"The roughest-to-smoothest quartile mean instability_score ratio is {q20_ratio:.2f}.", q20_trace),
    ]


def build_extra_hard_ground_truth(df: pd.DataFrame, dataset: str) -> list[dict[str, Any]]:
    query_texts = {int(query["id"]): str(query["text"]) for query in get_queries(dataset)}
    if not all(query_id in query_texts for query_id in EXTRA_HARD_IDS):
        raise ValueError(f"{dataset}: missing extra-hard query definitions")
    if dataset == DATASET_WISDM:
        return _wisdm_entries(df, query_texts)
    if dataset == DATASET_MIT_ECG:
        return _ecg_entries(df, query_texts)
    if dataset == DATASET_BUS:
        return _bus_entries(df, query_texts)
    raise ValueError(f"Unsupported dataset {dataset!r}")


def merge_extra_hard_entries(existing: list[dict[str, Any]], extra_hard: list[dict[str, Any]]) -> list[dict[str, Any]]:
    retained = [entry for entry in existing if int(entry.get("query_id", 0)) not in EXTRA_HARD_IDS]
    merged = retained + extra_hard
    return sorted(merged, key=lambda entry: int(entry["query_id"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, choices=[DATASET_WISDM, DATASET_MIT_ECG, DATASET_BUS])
    parser.add_argument("--data", default=None, help="Input dataset path; defaults to the benchmark source.")
    parser.add_argument("--output", default=None, help="Ground-truth JSON to create or merge into.")
    args = parser.parse_args()

    data_path = Path(args.data or DEFAULT_DATA_PATHS[args.dataset])
    output_path = Path(args.output or DEFAULT_OUTPUT_PATHS[args.dataset])
    df = load_dataset_by_name(str(data_path), args.dataset)
    extra_hard = build_extra_hard_ground_truth(df, args.dataset)
    existing = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else []
    if not isinstance(existing, list):
        raise ValueError(f"Expected a JSON list in {output_path}")
    merged = merge_extra_hard_entries(existing, extra_hard)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(extra_hard)} extra-hard entries; {len(merged)} total entries in {output_path}")


if __name__ == "__main__":
    main()