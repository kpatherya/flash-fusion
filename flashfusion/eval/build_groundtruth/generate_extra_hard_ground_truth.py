"""Compatibility CLI for extra-hard ground-truth entries.

Canonical ground-truth computation for every benchmark query lives in
``ground_truth_builder.py``. This module preserves the previous extra-hard API
while delegating to that single implementation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from flashfusion.eval.build_groundtruth.ground_truth_builder import build_ground_truth
from flashfusion.eval.queries import DATASET_BUS, DATASET_MIT_ECG, DATASET_WISDM
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


def build_extra_hard_ground_truth(df: pd.DataFrame, dataset: str) -> list[dict[str, Any]]:
    """Return the canonical entries for query IDs 17--20."""
    return [
        entry
        for entry in build_ground_truth(df, dataset)
        if int(entry["query_id"]) in EXTRA_HARD_IDS
    ]


def merge_extra_hard_entries(
    existing: list[dict[str, Any]], extra_hard: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Preserve the legacy merge helper for callers that manage IDs 1--16."""
    retained = [
        entry for entry in existing if int(entry.get("query_id", 0)) not in EXTRA_HARD_IDS
    ]
    return sorted(retained + extra_hard, key=lambda entry: int(entry["query_id"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        required=True,
        choices=[DATASET_WISDM, DATASET_MIT_ECG, DATASET_BUS],
    )
    parser.add_argument("--data", default=None, help="Input dataset path.")
    parser.add_argument("--output", default=None, help="Output ground-truth JSON path.")
    args = parser.parse_args()

    data_path = Path(args.data or DEFAULT_DATA_PATHS[args.dataset])
    output_path = Path(args.output or DEFAULT_OUTPUT_PATHS[args.dataset])
    df = load_dataset_by_name(str(data_path), args.dataset)
    entries = build_ground_truth(df, args.dataset)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(entries, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(entries)} canonical entries to {output_path}")


if __name__ == "__main__":
    main()