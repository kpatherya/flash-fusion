"""Seed extra-hard operator skeletons into the Flash-Fusion cache registries.

The normal exact-cache registry builder, ``flashfusion.pipeline.build_operator_skeleton_cache``,
harvests skeletons from completed Flash-Fusion benchmark artifacts. Query IDs 17-20
are intentionally seedable here before those benchmarks exist so
``FLASH_FUSION_CACHE`` can rely on the same fixed operator checklists during the
extra-hard comparison run.

Typical use:
  python -m flashfusion.eval.seed_extra_hard_cache_registry
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

from flashfusion.eval.benchmark import DEFAULT_DATA_PATHS
from flashfusion.eval.build_semantic_registry import build_semantic_registry
from flashfusion.eval.queries import DATASET_BUS, DATASET_MIT_ECG, DATASET_WISDM, get_queries
from flashfusion.pipeline.loader import load_dataset_by_name
from flashfusion.pipeline.operators import PLANNER_PREFIX_SHA256, TypedOperator


REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "flashfusion" / "eval" / "cache"
EXACT_CACHE_PATH = CACHE_DIR / "cache_registry.json"
SEMANTIC_OUTPUTS = {
    DATASET_BUS: CACHE_DIR / "semantic_registry_bus_v1.json",
    DATASET_WISDM: CACHE_DIR / "semantic_registry_wisdm_v1.json",
    DATASET_MIT_ECG: CACHE_DIR / "semantic_registry_mit_ecg_v1.json",
}

EXTRA_HARD_SKELETONS: dict[str, dict[int, list[str] | None]] = {
    DATASET_BUS: {
        17: ["FILTER_COMPARE", "DERIVE_BIN", "GROUP_AGGREGATE", "RANK_GROUPS"],
        18: [
            "DERIVE_VECTOR_MAGNITUDE",
            "SPLIT_BY_THRESHOLD",
            "SPLIT_BY_THRESHOLD",
            "AGGREGATE_PARTITIONS",
            "COMPARE_PARTITIONS",
        ],
        19: ["DERIVE_BIN", "DERIVE_BINARY", "PARALLEL_AGGREGATE", "AGGREGATE_COLUMN", "AGGREGATE_COLUMN", "COMPARE_VALUES"],
        20: ["DERIVE_BINARY", "FILTER_COMPARE", "DERIVE_BIN", "GROUP_AGGREGATE", "RANK_GROUPS"],
    },
    DATASET_WISDM: {
        17: ["DERIVE_VECTOR_MAGNITUDE", "PARALLEL_AGGREGATE", "DERIVE_BINARY", "RANK_ROWS"],
        # No stable typed skeleton: this query exposes premature router pruning.
        # Omit it from the cache so a cache miss delegates to the full FF planner.
        18: None,
        19: ["FILTER_NOT_EMPTY", "DERIVE_VECTOR_MAGNITUDE", "PARALLEL_AGGREGATE", "RANK_ROWS"],
        20: ["DERIVE_DURATION_SECONDS", "PARALLEL_AGGREGATE", "DERIVE_BINARY", "FILTER_COMPARE", "RANK_ROWS"],
    },
    DATASET_MIT_ECG: {
        17: ["FILTER_NOT_EMPTY", "DERIVE_BIN", "GROUP_AGGREGATE", "RANK_GROUPS"],
        18: ["PARALLEL_AGGREGATE", "DERIVE_BINARY", "RANK_ROWS"],
        19: ["FILTER_COMPARE", "DERIVE_BIN", "PARALLEL_AGGREGATE", "DERIVE_BINARY", "CORRELATE_COLUMNS"],
        20: ["PARALLEL_AGGREGATE", "DERIVE_BINARY", "RANK_ROWS"],
    },
}


def _canonical_dataset(dataset: str) -> str:
    return "ecg" if dataset == DATASET_MIT_ECG else dataset


def _operator_slots_by_name() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for model in get_args(get_args(TypedOperator)[0]):
        op_name = get_args(model.model_fields["op"].annotation)[0]
        out[op_name] = sorted(field for field in model.model_fields if field != "op")
    return out


def _load_exact_entries(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError(f"Expected {path} to contain a list or {{'entries': [...]}}")
    return [entry for entry in entries if isinstance(entry, dict)]


def _query_texts(dataset: str) -> dict[int, str]:
    return {int(query["id"]): str(query["text"]) for query in get_queries(dataset)}


def _seed_entry(dataset: str, query_id: int, skeleton: list[str], slots_by_name: dict[str, list[str]]) -> dict[str, Any]:
    canonical_dataset = _canonical_dataset(dataset)
    query_text = _query_texts(dataset)[query_id]
    return {
        "dataset": canonical_dataset,
        "example_run_ids": ["query_def_seed"],
        "field_level_skeleton": [
            {"op": op_name, "slots": slots_by_name[op_name]} for op_name in skeleton
        ],
        "n_runs_agreeing": 0,
        "n_runs_observed": 0,
        "operator_contract_hash": PLANNER_PREFIX_SHA256,
        "operator_skeleton": skeleton,
        "plan_source_modes": ["query_def_seed"],
        "query_id": str(query_id),
        "query_text": query_text,
        "query_text_source": "query_def_seed",
        "reasons": [],
        "status": "reusable",
    }


def seed_exact_registry(path: Path = EXACT_CACHE_PATH) -> int:
    entries = _load_exact_entries(path)
    target_keys = {
        (_canonical_dataset(dataset), str(query_id))
        for dataset, by_id in EXTRA_HARD_SKELETONS.items()
        for query_id in by_id
    }
    retained = [
        entry
        for entry in entries
        if (str(entry.get("dataset")), str(entry.get("query_id"))) not in target_keys
    ]
    slots_by_name = _operator_slots_by_name()
    for dataset, by_id in EXTRA_HARD_SKELETONS.items():
        for query_id, skeleton in by_id.items():
            if skeleton is None:
                continue
            for operator_name in skeleton:
                if not isinstance(operator_name, str) or not operator_name.strip() or operator_name not in slots_by_name:
                    raise ValueError(
                        "Invalid operator skeleton: "
                        f"dataset={dataset!r}, query_id={query_id}, operator={operator_name!r}"
                    )
    seeded = [
        _seed_entry(dataset, query_id, skeleton, slots_by_name)
        for dataset, by_id in EXTRA_HARD_SKELETONS.items()
        for query_id, skeleton in sorted(by_id.items())
        if skeleton is not None
    ]
    retained.extend(seeded)
    path.write_text(json.dumps({"entries": retained}, indent=2) + "\n", encoding="utf-8")
    return len(seeded)


def rebuild_semantic_registries() -> None:
    for dataset, output_path in SEMANTIC_OUTPUTS.items():
        data_path = DEFAULT_DATA_PATHS[dataset]
        max_rows = 1 if dataset == DATASET_MIT_ECG else None
        df = load_dataset_by_name(data_path, dataset, max_rows=max_rows)
        payload = build_semantic_registry(
            dataset=dataset,
            query_version="v1",
            data_path=data_path,
            cache_path=EXACT_CACHE_PATH,
            df=df,
        )
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {output_path} with {payload['count']} entries")


def main() -> None:
    seeded_count = seed_exact_registry()
    print(f"Seeded {seeded_count} exact extra-hard entries into {EXACT_CACHE_PATH}")
    rebuild_semantic_registries()


if __name__ == "__main__":
    main()