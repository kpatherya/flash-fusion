"""Build deterministic typed-plan ground truth for the grounding benchmark.

The trace-derived seed covers direct and intermediate queries (1--8). This
module extends it with canonical typed plans for predictive and extra-hard
queries (13--20). Out-of-scope queries (9--12) intentionally have no plan.
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flashfusion.eval.build_groundtruth.trace.extra_hard_bus_ff_compatible import (
    FLASH_FUSION_RAW_PLANS as BUS_EXTRA_HARD_PLANS,
)
from flashfusion.eval.build_groundtruth.trace.extra_hard_ecg_ff_compatible import (
    FLASH_FUSION_RAW_PLANS as ECG_EXTRA_HARD_PLANS,
)
from flashfusion.eval.build_groundtruth.trace.extra_hard_wisdm_ff_compatible import (
    FLASH_FUSION_RAW_PLANS as WISDM_EXTRA_HARD_PLANS,
)
from flashfusion.pipeline.operators import structural_validate

DATASETS = ("bus", "wisdm", "mit_ecg")
QUERY_VERSIONS = ("v1", "v2", "v3")
SEED_QUERY_IDS = tuple(range(1, 9))
SKELETON_QUERY_IDS = (*SEED_QUERY_IDS, *range(13, 21))
PREDICTIVE_MODELS = {
    13: "logistic_regression",
    14: "random_forest",
    15: "one_nearest_neighbor",
    16: "hist_gradient_boosting",
}
BUS_FEATURE_COLUMNS = [
    "accel_mean",
    "accel_variance",
    "accel_stats_x_p1",
    "accel_stats_x_p10",
    "accel_stats_x_p90",
    "accel_stats_x_p99",
    "accel_stats_y_p1",
    "accel_stats_y_p10",
    "accel_stats_y_p90",
    "accel_stats_y_p99",
    "accel_stats_z_p1",
    "accel_stats_z_p10",
    "accel_stats_z_p90",
    "accel_stats_z_p99",
    "extreme_event_magnitude",
    "instability_score",
]


def _predictive_plan(dataset: str, query_id: int) -> dict[str, Any]:
    model = PREDICTIVE_MODELS[query_id]
    if dataset == "wisdm":
        return {
            "version": "1",
            "steps": [
                {
                    "op": "PREDICTIVE_PIPELINE",
                    "model": model,
                    "feature_columns": ["x", "y", "z"],
                    "target_column": "activity_label",
                    "sort_by": ["timestamp", "subject_id"],
                    "train_fraction": 0.8,
                    "holdout_row": "first",
                    "target_from_non_empty": False,
                    "target_label": "activity_label",
                }
            ],
        }
    if dataset == "mit_ecg":
        return {
            "version": "1",
            "steps": [
                {
                    "op": "FILTER_COMPARE",
                    "column": "record_id",
                    "comparator": "eq",
                    "value": 101,
                },
                {
                    "op": "PREDICTIVE_PIPELINE",
                    "model": model,
                    "feature_columns": ["MLII", "V1"],
                    "target_column": "annotation",
                    "sort_by": ["time_s"],
                    "train_fraction": 0.8,
                    "holdout_row": "first",
                    "target_from_non_empty": True,
                    "target_label": "annotation_present",
                },
            ],
        }
    if dataset == "bus":
        return {
            "version": "1",
            "steps": [
                {
                    "op": "PREDICTIVE_PIPELINE",
                    "model": model,
                    "feature_columns": BUS_FEATURE_COLUMNS,
                    "target_column": "behavior",
                    "sort_by": ["timestamp"],
                    "train_fraction": 0.8,
                    "holdout_row": "first",
                    "target_from_non_empty": False,
                    "target_label": "behavior",
                }
            ],
        }
    raise ValueError(f"Unsupported dataset: {dataset!r}")


def _canonical_plan(dataset: str, query_id: int) -> dict[str, Any]:
    if query_id in PREDICTIVE_MODELS:
        raw_plan = _predictive_plan(dataset, query_id)
    elif dataset == "bus":
        raw_plan = BUS_EXTRA_HARD_PLANS[query_id]
    elif dataset == "wisdm":
        raw_plan = WISDM_EXTRA_HARD_PLANS[query_id]
        if query_id == 19:
            raw_plan = copy.deepcopy(raw_plan)
            raw_plan["steps"][-1]["method"] = "spearman"
    elif dataset == "mit_ecg":
        raw_plan = ECG_EXTRA_HARD_PLANS[query_id]
    else:
        raise ValueError(f"Unsupported dataset: {dataset!r}")

    return structural_validate(raw_plan).model_dump(mode="json")


def _plan_entry(plan: dict[str, Any]) -> dict[str, Any]:
    signature = json.dumps(plan, sort_keys=True, ensure_ascii=True)
    return {
        "typed_plan_signature": signature,
        "typed_plan": plan,
        "support_count": 1,
        "failure_support_count": 0,
        "candidate_signature_count": 1,
    }


def build_ground_truth(seed: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(seed)
    datasets = output.setdefault("datasets", {})

    for dataset in DATASETS:
        query_map = datasets.setdefault(dataset, {}).setdefault("queries", {})
        missing_seed = [str(query_id) for query_id in SEED_QUERY_IDS if str(query_id) not in query_map]
        if missing_seed:
            raise ValueError(
                f"Seed ground truth is missing {dataset} query IDs: {', '.join(missing_seed)}"
            )
        for query_id in range(13, 21):
            plan = _canonical_plan(dataset, query_id)
            entry = _plan_entry(plan)
            query_map[str(query_id)] = {
                "by_version": {
                    query_version: copy.deepcopy(entry) for query_version in QUERY_VERSIONS
                },
                "canonical_typed_plan_signature": entry["typed_plan_signature"],
                "canonical_typed_plan": plan,
            }

    flat_index: dict[str, str] = {}
    for dataset in DATASETS:
        query_map = datasets[dataset]["queries"]
        for query_id in SKELETON_QUERY_IDS:
            versions = query_map[str(query_id)]["by_version"]
            for query_version in QUERY_VERSIONS:
                flat_index[f"{dataset}|{query_id}|{query_version}"] = versions[query_version][
                    "typed_plan_signature"
                ]

    output["name"] = "ff_cache_typed_plan_ground_truth"
    output["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    output["source_root"] = "deterministic seed plans plus canonical typed-plan fixtures"
    output["included_query_ids"] = list(SKELETON_QUERY_IDS)
    output["excluded_query_ids"] = [9, 10, 11, 12]
    output["flat_index"] = flat_index
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        default="flashfusion/results/grounding/typed_plan_ground_truth.json",
        help="Existing trace-derived ground truth for query IDs 1--8.",
    )
    parser.add_argument(
        "--output",
        default="flashfusion/results/grounding/typed_plan_ground_truth_full.json",
        help="Path for the expanded typed-plan ground-truth artifact.",
    )
    args = parser.parse_args()

    seed_path = Path(args.seed)
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    output = build_ground_truth(seed)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {output_path} ({len(DATASETS) * len(SKELETON_QUERY_IDS) * len(QUERY_VERSIONS)} plans)")


if __name__ == "__main__":
    main()