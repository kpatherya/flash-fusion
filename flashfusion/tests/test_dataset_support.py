from __future__ import annotations

from pathlib import Path

from flashfusion.eval.queries import (
    DATASET_BUS,
    DATASET_MIT_ECG,
    DATASET_WISDM,
    get_queries,
)
from flashfusion.eval import queries_v2, queries_v3
from flashfusion.pipeline.loader import load_bus_data, load_dataset_by_name, load_mit_arrythmia


def test_mit_query_bank_has_expected_split() -> None:
    queries = get_queries(DATASET_MIT_ECG)
    assert len(queries) == 20

    complexity_counts: dict[str, int] = {}
    for q in queries:
        complexity = str(q["complexity"])
        complexity_counts[complexity] = complexity_counts.get(complexity, 0) + 1

    assert complexity_counts.get("direct", 0) == 4
    assert complexity_counts.get("intermediate", 0) == 4
    assert complexity_counts.get("out_of_scope", 0) == 4
    assert complexity_counts.get("predictive", 0) == 4


def test_load_mit_arrythmia_parses_rows(tmp_path: Path) -> None:
    p = tmp_path / "mit.txt"
    p.write_text(
        "0,0.0,-0.345,-0.16,101,;\n"
        "1,0.0027777777777777,-0.345,-0.16,101,N;\n"
        "bad,line;\n"
        "2,0.0055555555555555,-0.100,0.010,101,NaN;\n",
        encoding="utf-8",
    )

    df = load_mit_arrythmia(str(p))
    assert list(df.columns) == ["sample_idx", "time_s", "MLII", "V1", "record_id", "annotation"]
    assert len(df) == 3
    assert int(df.iloc[0]["sample_idx"]) == 0
    assert int(df.iloc[1]["record_id"]) == 101
    assert str(df.iloc[1]["annotation"]) == "N"
    # NaN annotation string is normalized to empty.
    assert str(df.iloc[2]["annotation"]) == ""


def test_load_dataset_by_name_dispatches_mit(tmp_path: Path) -> None:
    p = tmp_path / "mit.txt"
    p.write_text("0,0.0,-0.3,-0.1,101,;\n", encoding="utf-8")

    df = load_dataset_by_name(str(p), DATASET_MIT_ECG)
    assert len(df) == 1
    assert list(df.columns) == ["sample_idx", "time_s", "MLII", "V1", "record_id", "annotation"]

    # WISDM path still available; this call should simply return a list for the known dataset id.
    assert len(get_queries(DATASET_WISDM)) == 20


def test_bus_query_bank_has_expected_split() -> None:
    queries = get_queries(DATASET_BUS)
    assert len(queries) == 20

    complexity_counts: dict[str, int] = {}
    for q in queries:
        complexity = str(q["complexity"])
        complexity_counts[complexity] = complexity_counts.get(complexity, 0) + 1

    assert complexity_counts.get("direct", 0) == 4
    assert complexity_counts.get("intermediate", 0) == 4
    assert complexity_counts.get("out_of_scope", 0) == 4
    assert complexity_counts.get("predictive", 0) == 4
    assert complexity_counts.get("extra_hard", 0) == 4


def test_extra_hard_query_versions_preserve_metadata_and_reword_text() -> None:
    for dataset in (DATASET_WISDM, DATASET_MIT_ECG, DATASET_BUS):
        base_by_id = {q["id"]: q for q in get_queries(dataset)}
        v2_by_id = {q["id"]: q for q in queries_v2.get_queries(dataset)}
        v3_by_id = {q["id"]: q for q in queries_v3.get_queries(dataset)}

        for query_id in range(17, 21):
            base = base_by_id[query_id]
            v2 = v2_by_id[query_id]
            v3 = v3_by_id[query_id]
            assert base["complexity"] == v2["complexity"] == v3["complexity"] == "extra_hard"
            assert base["operation"] == v2["operation"] == v3["operation"]
            assert base["text"] != v2["text"]
            assert base["text"] != v3["text"]


def test_load_bus_data_parses_rows(tmp_path: Path) -> None:
    p = tmp_path / "bus.csv"
    p.write_text(
        "timestamp,latitude,longitude,accel_mean,accel_variance,accel_stats_x_p1,accel_stats_x_p10,accel_stats_x_p90,accel_stats_x_p99,accel_stats_y_p1,accel_stats_y_p10,accel_stats_y_p90,accel_stats_y_p99,accel_stats_z_p1,accel_stats_z_p10,accel_stats_z_p90,accel_stats_z_p99,extreme_event_magnitude,instability_score,behavior\n"
        "2025-06-06 16:36:34,33.77697,-84.38988,9.344,0.127,-1.686,-0.46,1.073,1.992,0.766,2.452,3.065,3.218,8.274,8.581,9.194,11.032,0.5,0.2,moderate\n"
        "bad_ts,33.77697,-84.38988,9.344,0.127,-1.686,-0.46,1.073,1.992,0.766,2.452,3.065,3.218,8.274,8.581,9.194,11.032,0.5,0.2,moderate\n"
        "2025-06-06 16:36:31,33.77697,-84.38988,9.344,not_a_number,-1.686,-0.46,1.073,1.992,0.766,2.452,3.065,3.218,8.274,8.581,9.194,11.032,0.5,0.2,moderate\n",
        encoding="utf-8",
    )

    df = load_bus_data(str(p))
    assert len(df) == 1
    assert "timestamp" in df.columns
    assert float(df.iloc[0]["accel_variance"]) == 0.127
    assert df.iloc[0]["behavior"] == "moderate"


def _assert_predictive_metadata(queries: list) -> None:
    """Verify that every predictive query is fully specified for baseline execution."""
    predictive = [q for q in queries if q.get("complexity") == "predictive"]
    for q in predictive:
        qid = q["id"]
        assert "[]" not in q["text"], f"query {qid} still has '[]' placeholder in text"
        assert q.get("operation", "<>") != "<>", f"query {qid} has placeholder operation"
        assert q.get("stress", "").strip() != "", f"query {qid} has empty stress field"


def test_wisdm_predictive_metadata() -> None:
    _assert_predictive_metadata(get_queries(DATASET_WISDM))


def test_mit_ecg_predictive_metadata() -> None:
    _assert_predictive_metadata(get_queries(DATASET_MIT_ECG))


def test_bus_predictive_metadata() -> None:
    _assert_predictive_metadata(get_queries(DATASET_BUS))


def test_load_dataset_by_name_dispatches_bus(tmp_path: Path) -> None:
    p = tmp_path / "bus.csv"
    p.write_text(
        "timestamp,latitude,longitude,accel_mean,accel_variance,accel_stats_x_p1,accel_stats_x_p10,accel_stats_x_p90,accel_stats_x_p99,accel_stats_y_p1,accel_stats_y_p10,accel_stats_y_p90,accel_stats_y_p99,accel_stats_z_p1,accel_stats_z_p10,accel_stats_z_p90,accel_stats_z_p99,extreme_event_magnitude,instability_score,behavior\n"
        "2025-06-06 16:36:34,33.77697,-84.38988,9.344,0.127,-1.686,-0.46,1.073,1.992,0.766,2.452,3.065,3.218,8.274,8.581,9.194,11.032,0.5,0.2,moderate\n",
        encoding="utf-8",
    )

    df = load_dataset_by_name(str(p), DATASET_BUS)
    assert len(df) == 1
    assert "accel_mean" in df.columns
    assert df.iloc[0]["behavior"] == "moderate"
