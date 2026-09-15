"""Build deterministic ground-truth JSON for supported benchmark datasets.

Usage (run from repo root):

    python -m flashfusion.eval.build_groundtruth.ground_truth_builder \
      --dataset wisdm \
      --data data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt \
      --output flashfusion/eval/ground_truth/ground_truth_wisdm.json

    python -m flashfusion.eval.build_groundtruth.ground_truth_builder \
      --dataset mit_ecg \
      --data data/AutoIOT_dataset/ECG.0/MIT_arrythmia_v1.txt \
      --output flashfusion/eval/ground_truth/ground_truth_mit_ecg.json

    python -m flashfusion.eval.build_groundtruth.ground_truth_builder \
      --dataset bus \
      --data data/bus/bus_data_enriched_behavior.csv \
      --output flashfusion/eval/ground_truth/ground_truth_bus.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, find_peaks
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression

try:
    import torch
    import torch.nn as nn
except ImportError as exc:  # pragma: no cover - explicit runtime guidance
    raise ImportError(
        "Torch is required for predictive ground-truth generation (WISDM Q14, MIT ECG Q16). "
        "Install with: pip install torch"
    ) from exc

from flashfusion.eval.queries import (
    DATASET_BUS,
    DATASET_MIT_ECG,
    DATASET_WISDM,
    get_queries,
)
from flashfusion.eval.build_groundtruth.simple_pred import MODEL_ORDER, run_prediction_suite
from flashfusion.pipeline.loader import load_dataset_by_name

RANDOM_SEED = 42
MIT_ECG_ANNOTATION_CODES = [
    "!", '"', "+", "/", "A", "E", "F", "J", "L", "N", "Q", "R", "S",
    "V", "[", "]", "a", "e", "f", "j", "x", "|", "~",
]

FIXED_PREDICTIVE_LABELS: dict[str, dict[str, str]] = {
    DATASET_BUS: {
        "logreg": "moderate",
        "rf": "moderate",
        "1nn": "moderate",
        "hgb": "moderate",
    },
    DATASET_WISDM: {
        "logreg": "Jogging",
        "rf": "Sitting",
        "1nn": "Sitting",
        "hgb": "Sitting",
    },
    DATASET_MIT_ECG: {
        "logreg": "0",
        "rf": "0",
        "1nn": "0",
        "hgb": "0",
    },
}


def _set_seed() -> None:
    np.random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)
    torch.use_deterministic_algorithms(True, warn_only=True)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_entries(entries: list[dict], qmap: dict[int, str], dataset: str) -> list[dict]:
    expected_ids = sorted(qmap.keys())
    got_ids = sorted(int(e["query_id"]) for e in entries)
    _require(
        got_ids == expected_ids,
        f"{dataset}: ground-truth ids mismatch. expected={expected_ids}, got={got_ids}",
    )
    seen: set[int] = set()
    for e in entries:
        qid = int(e["query_id"])
        _require(qid not in seen, f"{dataset}: duplicate query_id {qid}")
        seen.add(qid)
        _require(
            str(e["query_text"]) == qmap[qid],
            f"{dataset}: query text mismatch for query_id {qid}",
        )
    return entries


def _sliding_windows(
    n: int,
    window_size: int,
    step: int,
) -> list[tuple[int, int]]:
    if n < window_size:
        return []
    return [(s, s + window_size) for s in range(0, n - window_size + 1, step)]


def _majority_label(labels: np.ndarray) -> str:
    vals, counts = np.unique(labels.astype(str), return_counts=True)
    return str(vals[np.argmax(counts)])


def _wisdm_feature_windows(
    df: pd.DataFrame,
    user_ids: list[int],
    window_size: int,
    step: int,
    max_windows: int,
    label_filter: set[str] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features: list[list[float]] = []
    labels: list[str] = []
    centers: list[int] = []

    for uid in user_ids:
        g = df.loc[df["subject_id"] == uid].sort_values("timestamp")
        if g.empty:
            continue
        x = g["x"].to_numpy(dtype=np.float64)
        y = g["y"].to_numpy(dtype=np.float64)
        z = g["z"].to_numpy(dtype=np.float64)
        ts = g["timestamp"].to_numpy(dtype=np.int64)
        lbl = g["activity_label"].astype(str).to_numpy()

        for s, e in _sliding_windows(len(g), window_size, step):
            win_labels = lbl[s:e]
            maj = _majority_label(win_labels)
            maj_lower = maj.lower()
            if label_filter is not None and maj_lower not in label_filter:
                continue

            xw = x[s:e]
            yw = y[s:e]
            zw = z[s:e]
            features.append(
                [
                    float(np.mean(xw)),
                    float(np.mean(yw)),
                    float(np.mean(zw)),
                    float(np.var(xw)),
                    float(np.var(yw)),
                    float(np.var(zw)),
                ]
            )
            labels.append(maj)
            centers.append(int(ts[s + (window_size // 2)]))

            if len(features) >= max_windows:
                return np.array(features), np.array(labels), np.array(centers, dtype=np.int64)

    return np.array(features), np.array(labels), np.array(centers, dtype=np.int64)


def _wisdm_raw_windows(
    df: pd.DataFrame,
    user_ids: list[int],
    window_size: int,
    step: int,
    max_windows: int,
    allowed_labels: set[str] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    windows: list[np.ndarray] = []
    labels: list[str] = []
    centers: list[int] = []

    for uid in user_ids:
        g = df.loc[df["subject_id"] == uid].sort_values("timestamp")
        if g.empty:
            continue
        xyz = g[["x", "y", "z"]].to_numpy(dtype=np.float32)
        ts = g["timestamp"].to_numpy(dtype=np.int64)
        lbl = g["activity_label"].astype(str).str.lower().to_numpy()

        for s, e in _sliding_windows(len(g), window_size, step):
            win_lbl = lbl[s:e]
            maj = _majority_label(win_lbl)
            if allowed_labels is not None and maj not in allowed_labels:
                continue
            windows.append(xyz[s:e].T)
            labels.append(maj)
            centers.append(int(ts[s + (window_size // 2)]))
            if len(windows) >= max_windows:
                return np.stack(windows), np.array(labels), np.array(centers, dtype=np.int64)

    if not windows:
        return np.empty((0, 3, window_size), dtype=np.float32), np.array([]), np.array([], dtype=np.int64)
    return np.stack(windows), np.array(labels), np.array(centers, dtype=np.int64)


class TinyCNN(nn.Module):
    def __init__(self, in_channels: int, out_classes: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(in_channels, 16, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.Conv1d(16, 32, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(32, out_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def _train_tiny_cnn(
    x_train: np.ndarray,
    y_train: np.ndarray,
    num_classes: int,
    epochs: int,
) -> TinyCNN:
    _set_seed()
    model = TinyCNN(in_channels=x_train.shape[1], out_classes=num_classes)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    x_tensor = torch.tensor(x_train, dtype=torch.float32)
    y_tensor = torch.tensor(y_train, dtype=torch.long)

    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        logits = model(x_tensor)
        loss = criterion(logits, y_tensor)
        loss.backward()
        optimizer.step()

    return model


def build_ground_truth_wisdm(df: pd.DataFrame) -> list[dict]:
    df = df.copy()

    # Shared pre-processing
    df["activity_label"] = df["activity_label"].astype(str).str.strip()
    df["activity_lower"] = df["activity_label"].str.lower()
    df["magnitude"] = (df["x"] ** 2 + df["y"] ** 2 + df["z"] ** 2) ** 0.5

    qmap = {q["id"]: q["text"] for q in get_queries(DATASET_WISDM)}

    # Q1-Q8
    q1_max_x = float(df.loc[df["subject_id"] == 15, "x"].max())
    q2_walk_count = df.loc[df["activity_lower"] == "walking", "subject_id"].nunique()
    q3_mask = (df["subject_id"] == 5) & (df["activity_lower"] == "sitting")
    q3_y_mean = float(df.loc[q3_mask, "y"].mean())

    per_user_count = df.groupby("subject_id").size().sort_values(ascending=False)
    q4_user = int(per_user_count.index[0])
    q4_count = int(per_user_count.iloc[0])

    dynamic_mask = df["activity_lower"].isin({"walking", "jogging", "upstairs", "downstairs"})
    resting_mask = df["activity_lower"].isin({"sitting", "standing"})
    q5_dynamic_mean = float(df.loc[dynamic_mask, "magnitude"].mean())
    q5_resting_mean = float(df.loc[resting_mask, "magnitude"].mean())
    q5_diff = q5_dynamic_mean - q5_resting_mean

    df_sorted = df.sort_values(["subject_id", "timestamp"]).copy()
    dt_ns = df_sorted.groupby("subject_id")["timestamp"].diff()
    df_sorted["dt_s"] = (dt_ns.clip(lower=0).fillna(0) / 1_000_000_000).astype(float)

    stationary_mask = df_sorted["activity_lower"].isin({"sitting", "standing"})
    locomotion_mask = df_sorted["activity_lower"].isin({"walking", "jogging", "upstairs", "downstairs"})
    stationary_duration_s = df_sorted.loc[stationary_mask].groupby("subject_id")["dt_s"].sum()
    locomotion_duration_s = df_sorted.loc[locomotion_mask].groupby("subject_id")["dt_s"].sum()

    q6_compare = pd.DataFrame(
        {"stationary_s": stationary_duration_s, "locomotion_s": locomotion_duration_s}
    ).fillna(0.0)
    q6_compare["delta_s"] = q6_compare["stationary_s"] - q6_compare["locomotion_s"]
    q6_candidates = q6_compare[q6_compare["delta_s"] > 0].sort_values("delta_s", ascending=False)
    q6_qualifying_users = [int(uid) for uid in q6_candidates.index.tolist()]

    q7_median_net_vec = float(
        df.loc[(df["subject_id"] == 20) & (df["activity_label"] == "Upstairs"), "magnitude"].median()
    )
    q8_up_mean = float(df.loc[df["activity_lower"] == "upstairs", "z"].mean())
    q8_down_mean = float(df.loc[df["activity_lower"] == "downstairs", "z"].mean())

    q8_diff = abs(q8_up_mean - q8_down_mean)

    q17_dynamic = df.loc[dynamic_mask].groupby("subject_id")["magnitude"].mean()
    q17_resting = df.loc[resting_mask].groupby("subject_id")["magnitude"].mean()
    q17 = pd.concat(
        [
            q17_dynamic.rename("dynamic_mean_magnitude"),
            q17_resting.rename("resting_mean_magnitude"),
        ],
        axis=1,
    ).dropna()
    q17["dynamic_minus_resting"] = (
        q17["dynamic_mean_magnitude"] - q17["resting_mean_magnitude"]
    )
    q17_top = q17.loc[q17["dynamic_minus_resting"].idxmax()]

    q18_jogging = df.loc[df["activity_lower"] == "jogging"].groupby("subject_id")["x"].var()
    q18_walking = df.loc[df["activity_lower"] == "walking"].groupby("subject_id")["x"].var()
    q18 = pd.concat(
        [
            q18_jogging.rename("jogging_x_variance"),
            q18_walking.rename("walking_x_variance"),
        ],
        axis=1,
    ).dropna()
    q18["jogging_minus_walking_variance"] = (
        q18["jogging_x_variance"] - q18["walking_x_variance"]
    )
    # Most-negative signed gap (Walking variance exceeds Jogging by the largest margin) —
    # not the largest-magnitude gap, so no positive-only filter and no abs() here.
    q18_top = q18.loc[q18["jogging_minus_walking_variance"].idxmin()]

    q19_jogging = df.loc[df["activity_lower"] == "jogging"].groupby("subject_id")["magnitude"].mean()
    q19_walking = df.loc[df["activity_lower"] == "walking"].groupby("subject_id")["magnitude"].mean()
    q19 = pd.concat(
        [
            q19_jogging.rename("jogging_mean_magnitude"),
            q19_walking.rename("walking_mean_magnitude"),
        ],
        axis=1,
    ).dropna()
    # "ranking...consistently" is rank-correlation language, not linear-correlation language.
    q19_correlation = float(
        q19["jogging_mean_magnitude"].corr(q19["walking_mean_magnitude"], method="spearman")
    )

    q20_locomotion = df_sorted.loc[locomotion_mask].groupby("subject_id")["dt_s"].sum()
    q20_resting = df_sorted.loc[stationary_mask].groupby("subject_id")["dt_s"].sum()
    q20 = pd.concat(
        [
            q20_locomotion.rename("locomotion_duration_s"),
            q20_resting.rename("resting_duration_s"),
        ],
        axis=1,
    ).fillna(0.0)
    q20["locomotion_minus_resting_s"] = (
        q20["locomotion_duration_s"] - q20["resting_duration_s"]
    )
    q20_top = q20.loc[q20["locomotion_minus_resting_s"] > 0].loc[
        lambda values: values["locomotion_minus_resting_s"].idxmax()
    ]

    fixed_predictions = FIXED_PREDICTIVE_LABELS[DATASET_WISDM]

    entries = [
        {
            "query_id": 1,
            "query_text": qmap[1],
            "reference_answer": f"Maximum x-acceleration for user 15 is {q1_max_x:.4f}.",
            "expected_rejection": False,
        },
        {
            "query_id": 2,
            "query_text": qmap[2],
            "reference_answer": f"Total users Walking in the dataset: {q2_walk_count}.",
            "expected_rejection": False,
        },
        {
            "query_id": 3,
            "query_text": qmap[3],
            "reference_answer": f"Average y-acceleration for user 5 during Sitting is {q3_y_mean:.4f}.",
            "expected_rejection": False,
        },
        {
            "query_id": 4,
            "query_text": qmap[4],
            "reference_answer": f"User with the highest sample count is {q4_user} with {q4_count} samples.",
            "expected_rejection": False,
        },
        {
            "query_id": 5,
            "query_text": qmap[5],
            "reference_answer": (
                f"Average magnitude for dynamic activities (walking,jogging,upstairs,downstairs) is {q5_dynamic_mean:.4f}; "
                f"resting activities (sitting,standing) is {q5_resting_mean:.4f}; "
                f"difference (dynamic-resting) is {q5_diff:.4f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 6,
            "query_text": qmap[6],
            "reference_answer": (
                f"Users {q6_qualifying_users} have total stationary duration "
                f"(sitting, standing) exceeding locomotion duration "
                f"(walking, jogging, upstairs, downstairs). "
                f"User {q6_qualifying_users[0]} has the largest margin "
                f"(delta={q6_candidates.iloc[0]['delta_s']:.2f}s)."
                if q6_qualifying_users
                else "No user has stationary duration greater than locomotion duration."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 7,
            "query_text": qmap[7],
            "reference_answer": f"Median net acceleration vector length for user 20 while ascending steps is {q7_median_net_vec:.4f}.",
            "expected_rejection": False,
        },
        {
            "query_id": 8,
            "query_text": qmap[8],
            "reference_answer": (
                f"Average z for ascending elevation changes is {q8_up_mean:.4f}; "
                f"descending is {q8_down_mean:.4f}; absolute difference (ascending-descending) is {q8_diff:.4f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 9,
            "query_text": qmap[9],
            "reference_answer": "Reject: speed in mph and user age are not available in this dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 10,
            "query_text": qmap[10],
            "reference_answer": "Reject: acceleration records do not contain geographic location signals.",
            "expected_rejection": True,
        },
        {
            "query_id": 11,
            "query_text": qmap[11],
            "reference_answer": "Reject: sex and cadence attributes are unavailable in this dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 12,
            "query_text": qmap[12],
            "reference_answer": "Reject: future MVPA-guideline compliance cannot be predicted from this dataset and the WHO guideline threshold is not represented in the schema.",
            "expected_rejection": True,
        },
        {
            "query_id": 13,
            "query_text": qmap[13],
            "reference_answer": (
                "Logistic regression predicts activity "
                f"'{fixed_predictions['logreg']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 14,
            "query_text": qmap[14],
            "reference_answer": (
                "Random forest predicts activity "
                f"'{fixed_predictions['rf']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 15,
            "query_text": qmap[15],
            "reference_answer": (
                "1-nearest-neighbor predicts activity "
                f"'{fixed_predictions['1nn']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 16,
            "query_text": qmap[16],
            "reference_answer": (
                "Hist gradient boosting predicts activity "
                f"'{fixed_predictions['hgb']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 17,
            "query_text": qmap[17],
            "reference_answer": (
                f"subject_id {int(q17_top.name)} has the largest dynamic-minus-resting "
                f"mean magnitude: {float(q17_top['dynamic_minus_resting']):.12f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 18,
            "query_text": qmap[18],
            "reference_answer": (
                f"subject_id {int(q18_top.name)} has the most negative "
                f"Jogging-minus-Walking x-variance difference (Walking exceeds Jogging "
                f"by the largest margin): {float(q18_top['jogging_minus_walking_variance']):.12f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 19,
            "query_text": qmap[19],
            "reference_answer": (
                ("Yes" if q19_correlation > 0 else "No")
                + " — subjects who jog harder also tend to walk harder: the Spearman "
                "rank correlation between per-subject Jogging and Walking mean "
                f"magnitudes is {q19_correlation:.12f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 20,
            "query_text": qmap[20],
            "reference_answer": (
                f"subject_id {int(q20_top.name)} has the largest positive "
                f"locomotion-minus-resting duration: "
                f"{float(q20_top['locomotion_minus_resting_s']):.12f} seconds."
            ),
            "expected_rejection": False,
        },
    ]
    return _validate_entries(entries, qmap, DATASET_WISDM)


def _ecg_window_features(
    df: pd.DataFrame,
    signal_col: str,
    time_col: str,
    ann_col: str,
    window_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vals = df[signal_col].to_numpy(dtype=np.float64)
    t = df[time_col].to_numpy(dtype=np.float64)
    anns = df[ann_col].astype(str).str.strip().to_numpy()

    starts = np.arange(float(t.min()), float(t.max()) - window_s + 1e-9, window_s)
    feats: list[list[float]] = []
    labels: list[int] = []
    start_times: list[float] = []

    for st in starts:
        en = st + window_s
        mask = (t >= st) & (t < en)
        if not np.any(mask):
            continue
        seg = vals[mask]
        ann_seg = anns[mask]
        feats.append(
            [
                float(np.mean(seg)),
                float(np.std(seg)),
                float(np.max(seg)),
                float(np.min(seg)),
                float(np.sqrt(np.mean(seg**2))),
            ]
        )
        labels.append(int(np.any(ann_seg != "")))
        start_times.append(float(st))

    return np.array(feats), np.array(labels, dtype=np.int64), np.array(start_times)


def _ecg_tumbling_raw(
    df: pd.DataFrame,
    channels: list[str],
    window_s: float,
    ann_col: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = df["time_s"].to_numpy(dtype=np.float64)
    starts = np.arange(float(t.min()), float(t.max()) - window_s + 1e-9, window_s)

    windows: list[np.ndarray] = []
    labels: list[int] = []
    out_starts: list[float] = []
    for st in starts:
        en = st + window_s
        m = (t >= st) & (t < en)
        if int(np.sum(m)) < 32:
            continue
        seg = df.loc[m, channels].to_numpy(dtype=np.float32).T
        ann = df.loc[m, ann_col].astype(str).str.strip().to_numpy()
        windows.append(seg)
        labels.append(int(np.any(ann != "")))
        out_starts.append(float(st))

    if not windows:
        return np.empty((0, len(channels), 0), dtype=np.float32), np.array([], dtype=np.int64), np.array([])

    min_len = min(w.shape[1] for w in windows)
    windows = [w[:, :min_len] for w in windows]
    return np.stack(windows), np.array(labels, dtype=np.int64), np.array(out_starts)


def build_ground_truth_mit_ecg(df: pd.DataFrame) -> list[dict]:
    """Build deterministic MIT ECG ground-truth entries for all benchmark queries."""
    df = df.copy()
    df["annotation"] = df["annotation"].astype(str).fillna("")
    df["is_annotated"] = df["annotation"].str.strip() != ""

    qmap = {q["id"]: q["text"] for q in get_queries(DATASET_MIT_ECG)}

    q1_min_mlii_101 = float(df.loc[df["record_id"] == 101, "MLII"].min())
    q2_max_time_234 = float(df.loc[df["record_id"] == 234, "time_s"].max())
    q3_count_106 = int(df.loc[(df["record_id"] == 106) & (df["MLII"] > 0)].shape[0])
    rec221_ann = df.loc[(df["record_id"] == 221) & (df["is_annotated"]), "time_s"]
    q4_last_ann_221 = float(rec221_ann.max())

    rec208 = df.loc[df["record_id"] == 208].copy()
    rec208 = rec208[rec208["annotation"].str.strip() != ""]
    rec208["time_bin_60s"] = (rec208["time_s"] // 60.0) * 60.0
    if not rec208.empty:
        q5_avg_per_bin_208 = float(rec208.groupby("time_bin_60s")["annotation"].count().mean())
    else:
        q5_avg_per_bin_208 = 0.0

    mlii_range = df.groupby("record_id")["MLII"].agg(lambda x: x.max() - x.min()).sort_values(ascending=False)
    q6_record = int(mlii_range.index[0])
    q6_range = float(mlii_range.iloc[0])

    rec101 = df.loc[df["record_id"] == 101]
    rec101_ann = rec101.loc[rec101["is_annotated"]].copy()
    if rec101_ann.empty:
        q7_interval_start, q7_interval_end, q7_interval_count = 0, 10, 0
    else:
        rec101_ann["interval_10s"] = (rec101_ann["time_s"] // 10).astype(int)
        interval_counts = rec101_ann.groupby("interval_10s").size().sort_values(ascending=False)
        q7_interval = int(interval_counts.index[0])
        q7_interval_start = q7_interval * 10
        q7_interval_end = q7_interval_start + 10
        q7_interval_count = int(interval_counts.iloc[0])

    mlii_106 = df.loc[df["record_id"] == 106, "MLII"]
    q8_rms_106 = float(np.sqrt((mlii_106**2).mean()))

    q17_work = df.loc[df["annotation"].str.strip().isin(MIT_ECG_ANNOTATION_CODES)].copy()
    q17_work["bin_10s"] = (q17_work["time_s"] // 10) * 10
    q17 = (
        q17_work.groupby(["record_id", "bin_10s"])["MLII"]
        .apply(lambda values: float(np.sqrt(np.mean(values**2))))
        .rename("rms_MLII")
    )
    q17_top_key = q17.idxmax()
    q17_top_rms = float(q17.loc[q17_top_key])

    q18 = df.groupby("record_id")["MLII"].agg(["max", "min"])
    q18["mlii_range"] = (q18["max"] - q18["min"]).abs()
    q18_top = q18.loc[q18["mlii_range"].idxmax()]

    q19_work = df.copy()
    q19_work["window_index"] = (q19_work["time_s"] // 10) * 10
    q19_rows = q19_work.groupby(["record_id", "window_index"]).size().rename("rows_per_window")
    q19_annotated = (
        q19_work.loc[q19_work["annotation"].str.strip().isin(MIT_ECG_ANNOTATION_CODES)]
        .groupby(["record_id", "window_index"])
        .size()
        .rename("annotated_count_per_window")
    )
    q19 = pd.concat([q19_rows, q19_annotated], axis=1).fillna(0.0).reset_index()
    q19 = q19.loc[q19["record_id"] == 101].copy()
    q19["annotated_rate"] = q19["annotated_count_per_window"] / q19["rows_per_window"]
    q19_correlation = float(q19["window_index"].corr(q19["annotated_rate"]))

    q20 = df.groupby("record_id").agg(
        mlii_variance=("MLII", "var"),
        v1_variance=("V1", "var"),
    )
    q20["combined_variance"] = q20["mlii_variance"] + q20["v1_variance"]
    q20_top = q20.loc[q20["combined_variance"].idxmax()]

    fixed_predictions = FIXED_PREDICTIVE_LABELS[DATASET_MIT_ECG]

    entries = [
        {
            "query_id": 1,
            "query_text": qmap[1],
            "reference_answer": f"Minimum MLII for record_id 101 is {q1_min_mlii_101:.4f}.",
            "expected_rejection": False,
        },
        {
            "query_id": 2,
            "query_text": qmap[2],
            "reference_answer": f"Total recording duration for record_id 234 is {q2_max_time_234:.4f} seconds.",
            "expected_rejection": False,
        },
        {
            "query_id": 3,
            "query_text": qmap[3],
            "reference_answer": f"record_id 106 has {q3_count_106} samples with MLII > 0.",
            "expected_rejection": False,
        },
        {
            "query_id": 4,
            "query_text": qmap[4],
            "reference_answer": f"The last annotated beat in record_id 221 occurs at time_s = {q4_last_ann_221:.6f}.",
            "expected_rejection": False,
        },
        {
            "query_id": 5,
            "query_text": qmap[5],
            "reference_answer": (
                f"For record_id 208, the average annotation count per 60-s time_s is {q5_avg_per_bin_208:.6f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 6,
            "query_text": qmap[6],
            "reference_answer": f"record_id {q6_record} has the largest peak-to-peak MLII amplitude at {q6_range:.4f}.",
            "expected_rejection": False,
        },
        {
            "query_id": 7,
            "query_text": qmap[7],
            "reference_answer": (
                f"The 10-second interval [{q7_interval_start}s, {q7_interval_end}s) "
                f"contains the highest number of annotated beats for record_id 101 with {q7_interval_count} beats."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 8,
            "query_text": qmap[8],
            "reference_answer": f"The RMS of the MLII signal for record_id 106 is {q8_rms_106:.4f}.",
            "expected_rejection": False,
        },
        {
            "query_id": 9,
            "query_text": qmap[9],
            "reference_answer": "Reject: patient outcome and mortality data are unavailable in this ECG dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 10,
            "query_text": qmap[10],
            "reference_answer": "Reject: BMI and anthropometric metadata are unavailable in this ECG dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 11,
            "query_text": qmap[11],
            "reference_answer": "Reject: family medical history is unavailable in this ECG dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 12,
            "query_text": qmap[12],
            "reference_answer": "Reject: variables such as body weight are unavailable in this ECG dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 13,
            "query_text": qmap[13],
            "reference_answer": (
                "Logistic regression predicts annotation "
                f"'{fixed_predictions['logreg']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 14,
            "query_text": qmap[14],
            "reference_answer": (
                "Random forest predicts annotation "
                f"'{fixed_predictions['rf']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 15,
            "query_text": qmap[15],
            "reference_answer": (
                "1-nearest-neighbor predicts annotation "
                f"'{fixed_predictions['1nn']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 16,
            "query_text": qmap[16],
            "reference_answer": (
                "Hist gradient boosting predicts annotation "
                f"'{fixed_predictions['hgb']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 17,
            "query_text": qmap[17],
            "reference_answer": (
                f"The greatest MLII RMS is {q17_top_rms:.12f} for record_id "
                f"{int(q17_top_key[0])} in the {float(q17_top_key[1]):.1f}-second bin."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 18,
            "query_text": qmap[18],
            "reference_answer": (
                f"record_id {int(q18_top.name)} has the largest MLII span: "
                f"{float(q18_top['mlii_range']):.12f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 19,
            "query_text": qmap[19],
            "reference_answer": (
                "The Pearson correlation between 10-second bin index and annotated-row "
                f"rate for record_id 101 is {q19_correlation:.12f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 20,
            "query_text": qmap[20],
            "reference_answer": (
                f"record_id {int(q20_top.name)} has the largest total lead variability: "
                f"{float(q20_top['combined_variance']):.12f}."
            ),
            "expected_rejection": False,
        },
    ]
    return _validate_entries(entries, qmap, DATASET_MIT_ECG)


def build_ground_truth_bus(df: pd.DataFrame) -> list[dict]:
    """Build deterministic bus ground-truth entries for all benchmark queries."""
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna().reset_index(drop=True)

    qmap = {q["id"]: q["text"] for q in get_queries(DATASET_BUS)}

    q1_max_var = float(df["accel_variance"].max())
    q2_mean_accel = float(df["accel_mean"].mean())

    q3_max_z_p99 = float(df["accel_stats_z_p99"].max())
    q3_ts_list = [
        str(ts) for ts in df.loc[df["accel_stats_z_p99"] == q3_max_z_p99, "timestamp"].tolist()
    ]

    q4_count = int((df["accel_variance"] > 0.20).sum())

    lat_median = float(df["latitude"].median())
    north_mask = df["latitude"] >= lat_median
    q5_north = float(df.loc[north_mask, "accel_variance"].mean())
    q5_south = float(df.loc[~north_mask, "accel_variance"].mean())
    q5_diff = q5_north - q5_south

    df["vertical_shock"] = df["accel_stats_z_p99"] - df["accel_stats_z_p1"]
    q6_idx = int(df["vertical_shock"].idxmax())
    q6_row = df.loc[q6_idx]

    df["peak_magnitude"] = np.sqrt(
        df["accel_stats_x_p99"] ** 2
        + df["accel_stats_y_p99"] ** 2
        + df["accel_stats_z_p99"] ** 2
    )
    q7_mean_magnitude = float(df["peak_magnitude"].mean())

    instability_by_minute = (
        df.groupby(pd.Grouper(key="timestamp", freq="1min"))["instability_score"]
        .mean()
        .dropna()
    )
    q8_bin = instability_by_minute.idxmax()
    q8_mean = float(instability_by_minute.max())

    q17 = (
        df.loc[df["behavior"] == "aggressive"]
        .groupby(pd.Grouper(key="timestamp", freq="5min"))["instability_score"]
        .mean()
    )
    q17_top_timestamp = q17.idxmax()
    q17_top_score = float(q17.loc[q17_top_timestamp])

    q18_north = float(df.loc[df["latitude"] > lat_median, "peak_magnitude"].mean())
    q18_south = float(df.loc[df["latitude"] <= lat_median, "peak_magnitude"].mean())
    q18_difference = abs(q18_north - q18_south)

    q19_aggressive = float(
        df.loc[df["behavior"] == "aggressive", "vertical_shock"].mean()
    )
    q19_calm = float(df.loc[df["behavior"] == "calm", "vertical_shock"].mean())
    q19_difference = q19_aggressive - q19_calm

    q20 = (
        df.loc[df["behavior"] == "aggressive"]
        .groupby(pd.Grouper(key="timestamp", freq="5min"))["vertical_shock"]
        .mean()
    )
    q20_top_timestamp = q20.idxmax()
    q20_top_shock = float(q20.loc[q20_top_timestamp])

    fixed_predictions = FIXED_PREDICTIVE_LABELS[DATASET_BUS]

    entries = [
        {
            "query_id": 1,
            "query_text": qmap[1],
            "reference_answer": f"Maximum accel_variance is {q1_max_var:.4f}.",
            "expected_rejection": False,
        },
        {
            "query_id": 2,
            "query_text": qmap[2],
            "reference_answer": f"Average accel_mean across all samples is {q2_mean_accel:.4f}.",
            "expected_rejection": False,
        },
        {
            "query_id": 3,
            "query_text": qmap[3],
            "reference_answer": (
                f"Maximum accel_stats_z_p99 is {q3_max_z_p99:.4f}. "
                f"Timestamps with this value: {q3_ts_list}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 4,
            "query_text": qmap[4],
            "reference_answer": f"Samples with accel_variance > 0.20: {q4_count}.",
            "expected_rejection": False,
        },
        {
            "query_id": 5,
            "query_text": qmap[5],
            "reference_answer": (
                f"Median latitude split is {lat_median:.6f}. "
                f"North-half mean accel_variance is {q5_north:.4f}, south-half mean is {q5_south:.4f}; "
                f"the northern half is {'rougher' if q5_diff > 0 else 'smoother'} by {abs(q5_diff):.4f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 6,
            "query_text": qmap[6],
            "reference_answer": (
                f"Largest vertical shock (z_p99 - z_p1) is {float(q6_row['vertical_shock']):.4f} at "
                f"({float(q6_row['latitude']):.6f}, {float(q6_row['longitude']):.6f}), "
                f"timestamp {q6_row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 7,
            "query_text": qmap[7],
            "reference_answer": (
                "Average 3D peak acceleration magnitude "
                f"[sqrt(x_p99^2 + y_p99^2 + z_p99^2)] across all samples is {q7_mean_magnitude:.4f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 8,
            "query_text": qmap[8],
            "reference_answer": (
                f"The 1-minute window starting at {q8_bin.strftime('%Y-%m-%d %H:%M:%S')} "
                f"had the highest mean instability_score of {q8_mean:.4f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 9,
            "query_text": qmap[9],
            "reference_answer": "Reject: passenger occupancy data is unavailable in this bus dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 10,
            "query_text": qmap[10],
            "reference_answer": "Reject: weather metadata is unavailable in this bus dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 11,
            "query_text": qmap[11],
            "reference_answer": "Reject: driver identity metadata is unavailable in this bus dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 12,
            "query_text": qmap[12],
            "reference_answer": "Reject: future road maintenance labels are unavailable in this bus dataset.",
            "expected_rejection": True,
        },
        {
            "query_id": 13,
            "query_text": qmap[13],
            "reference_answer": (
                "Logistic regression predicts behavior "
                f"'{fixed_predictions['logreg']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 14,
            "query_text": qmap[14],
            "reference_answer": (
                "Random forest predicts behavior "
                f"'{fixed_predictions['rf']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 15,
            "query_text": qmap[15],
            "reference_answer": (
                "1-nearest-neighbor predicts behavior "
                f"'{fixed_predictions['1nn']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 16,
            "query_text": qmap[16],
            "reference_answer": (
                "Hist gradient boosting predicts behavior "
                f"'{fixed_predictions['hgb']}' for the first holdout row."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 17,
            "query_text": qmap[17],
            "reference_answer": (
                f"The aggressive-behavior 5-minute window beginning "
                f"{q17_top_timestamp.strftime('%Y-%m-%d %H:%M:%S')} has the highest "
                f"mean instability_score: {q17_top_score:.12f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 18,
            "query_text": qmap[18],
            "reference_answer": (
                f"Northern mean peak magnitude is {q18_north:.12f}; southern mean "
                f"peak magnitude is {q18_south:.12f}; their absolute difference is "
                f"{q18_difference:.12f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 19,
            "query_text": qmap[19],
            "reference_answer": (
                f"Aggressive mean vertical shock range is {q19_aggressive:.12f}; calm "
                f"mean is {q19_calm:.12f}; aggressive-minus-calm is "
                f"{q19_difference:.12f}."
            ),
            "expected_rejection": False,
        },
        {
            "query_id": 20,
            "query_text": qmap[20],
            "reference_answer": (
                f"The aggressive-behavior 5-minute window beginning "
                f"{q20_top_timestamp.strftime('%Y-%m-%d %H:%M:%S')} has the highest "
                f"mean vertical shock range: {q20_top_shock:.12f}."
            ),
            "expected_rejection": False,
        },
    ]
    return _validate_entries(entries, qmap, DATASET_BUS)


def build_ground_truth(df: pd.DataFrame, dataset: str) -> list[dict]:
    if dataset == DATASET_WISDM:
        return build_ground_truth_wisdm(df)
    if dataset == DATASET_MIT_ECG:
        return build_ground_truth_mit_ecg(df)
    if dataset == DATASET_BUS:
        return build_ground_truth_bus(df)
    raise ValueError(f"Unsupported dataset {dataset!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Flash-Fusion ground truth JSON")
    parser.add_argument("--data", required=True, help="Path to benchmark dataset file")
    parser.add_argument(
        "--dataset",
        default=DATASET_WISDM,
        choices=[DATASET_WISDM, DATASET_MIT_ECG, DATASET_BUS],
        help="Dataset profile for deterministic ground-truth generation",
    )
    parser.add_argument(
        "--output",
        default="flashfusion/eval/ground_truth/ground_truth_wisdm.json",
        help="Output ground-truth JSON path",
    )
    args = parser.parse_args()

    _set_seed()
    df = load_dataset_by_name(args.data, args.dataset)
    entries = build_ground_truth(df, args.dataset)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=True, indent=2)
    print(f"Wrote {len(entries)} entries to {out}")


if __name__ == "__main__":
    main()
