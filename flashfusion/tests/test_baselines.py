"""
tests/test_baselines.py — Flow-shape tests for baseline pipelines.

Run with: pytest flashfusion/tests/test_baselines.py -v
"""

from __future__ import annotations

import dataclasses
import os
import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from flashfusion.pipeline.runner import BaselineRunner, RunResult


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "subject_id": [1600, 1601],
            "activity_label": ["A", "B"],
            "timestamp": [1000, 2000],
            "x": [0.1, 0.2],
            "y": [0.1, 0.2],
            "z": [0.1, 0.2],
            "magnitude": [0.173, 0.346],
            "activity_name": ["Walking", "Jogging"],
        }
    )


def _client() -> MagicMock:
    c = MagicMock()
    c.model_name = "llama-3.3-70b-versatile"
    c.llm = MagicMock()
    return c


def _result(mode: str, query: str) -> RunResult:
    return RunResult(baseline=mode, model="llama-3.3-70b-versatile", query=query)


def _guardrail_return(verdict) -> tuple:
    """Mimic ``request_guardrail_and_plan``: (parsed, suffix, error, prefix)."""
    from flashfusion.pipeline.operators import ParsedGuardrail

    return (
        ParsedGuardrail(parsed=verdict, raw={}, normalization_actions=[]),
        "",
        "",
        "prefix",
    )


def test_runner_does_not_precompute_derived_features() -> None:
    """BaselineRunner must hand the pipeline the raw schema unmodified; any
    derived feature (e.g. magnitude) is now materialized only after Stage 2
    grounding explicitly requires it, not speculatively for every query."""
    raw_df = _df().drop(columns=["magnitude", "activity_name"])
    runner = BaselineRunner(mode="FLASH_FUSION", df=raw_df, client=_client())

    with patch("flashfusion.baselines.flash_fusion.run_flash_fusion"):
        runner.run("Compare acceleration magnitude.")

    assert list(runner.df.columns) == list(raw_df.columns)


def test_runner_can_reuse_caller_dataframe() -> None:
    raw_df = _df()
    runner = BaselineRunner(
        mode="FLASH_FUSION",
        df=raw_df,
        client=_client(),
        copy_dataframe=False,
    )

    assert runner.df is raw_df


def test_runner_reports_usage_delta_when_client_is_reused() -> None:
    client = _client()
    client.total_input_tokens.side_effect = [100, 130]
    client.total_output_tokens.side_effect = [50, 70]
    client.total_cost_usd.side_effect = [0.10, 0.15]
    client.total_cached_tokens.side_effect = [10, 14]
    client.total_cache_write_tokens.side_effect = [2, 5]
    client.total_cache_discount_usd.side_effect = [0.01, 0.03]
    runner = BaselineRunner(mode="FLASH_FUSION", df=_df(), client=client)

    with patch("flashfusion.baselines.flash_fusion.run_flash_fusion"):
        result = runner.run("Count records.")

    assert result.input_tokens == 30
    assert result.output_tokens == 20
    assert result.cost_usd == pytest.approx(0.05)
    assert result.cached_tokens == 4
    assert result.cache_write_tokens == 3
    assert result.cache_discount_usd == pytest.approx(0.02)


def test_flash_fusion_runner_warms_planner_components_without_llm_call() -> None:
    from flashfusion.baselines import flash_fusion

    client = _client()
    client.session_key = "test-planner-session"
    runner = BaselineRunner(mode="FLASH_FUSION", df=_df(), client=client)

    assert runner.mode == "FLASH_FUSION"
    assert any(key[0] == client.session_key for key in flash_fusion._PLANNER_PREFIX_CACHE)
    assert any(key[0] == client.session_key for key in flash_fusion._PLANNER_SUFFIX_PREFIX_CACHE)
    client.invoke_messages.assert_not_called()


def test_flash_fusion_timeout_helper_raises_for_slow_call() -> None:
    """The Flash-Fusion timeout helper must raise when a call exceeds the budget."""
    from flashfusion.baselines.flash_fusion import _FlashFusionTimeoutError, _run_with_timeout

    def slow_callable() -> None:
        time.sleep(0.05)

    with pytest.raises(_FlashFusionTimeoutError):
        _run_with_timeout(slow_callable, timeout_s=0.01)


def test_flash_fusion_timeout_applies_to_typed_execution() -> None:
    """Flash-Fusion enforces the configured timeout around plan execution."""
    from flashfusion.baselines.flash_fusion import run_flash_fusion
    from flashfusion.pipeline.operators import GuardrailAndPlan

    query = "What is the average x observed in this dataset?"
    r = _result("FLASH_FUSION", query)
    plan = _plan({"op": "AGGREGATE_COLUMN", "column": "x", "aggregate": "mean"})

    with patch(
        "flashfusion.baselines.flash_fusion.request_guardrail_and_plan",
        return_value=_guardrail_return(GuardrailAndPlan(in_scope=True, plan=plan)),
    ), patch(
        "flashfusion.baselines.flash_fusion.ExecutionLayer"
    ) as execution_layer_cls, patch(
        "flashfusion.baselines.flash_fusion._run_with_timeout"
    ) as timeout_mock:
        execution_layer_cls.return_value.synthesize.return_value = "The average is 0.15"
        timeout_mock.return_value = MagicMock(
            ok=True, value=0.15, trace="trace", code="code", steps=[], latency_ms=1.0
        )

        out = run_flash_fusion(query, _df(), _client(), r)

    assert timeout_mock.called
    assert out.executed is True
    assert out.execution_path == "typed_operator"


def _plan(*steps: dict) -> "DeterministicPlan":
    from flashfusion.pipeline.operators import structural_validate

    return structural_validate({"version": "1", "steps": list(steps)})


def test_filter_not_empty_excludes_null_and_blank_strings() -> None:
    from flashfusion.pipeline.operators import execute_plan

    df = pd.DataFrame({"annotation": ["N", "", "  ", None, "V"]})
    execution = execute_plan(
        df, _plan({"op": "FILTER_NOT_EMPTY", "column": "annotation"}),
    )

    assert execution.ok
    assert execution.rows_after_filter == 2
    assert "notna()" in execution.code
    assert ".str.strip().ne('')" in execution.code


def test_structural_gate_rejects_unknown_operator() -> None:
    """Gate 1: an operator outside the closed vocabulary never reaches the data."""
    from flashfusion.pipeline.operators import StructuralValidationError, structural_validate

    with pytest.raises(StructuralValidationError):
        structural_validate(
            {"version": "1", "steps": [{"op": "USER_ACTIVITY_DURATION_MARGIN"}]}
        )


def test_structural_gate_rejects_extra_operator_fields() -> None:
    """Gate 1: operators forbid unknown kwargs, so no untyped payload slips in."""
    from flashfusion.pipeline.operators import StructuralValidationError, structural_validate

    with pytest.raises(StructuralValidationError):
        structural_validate(
            {
                "version": "1",
                "steps": [
                    {
                        "op": "AGGREGATE_COLUMN",
                        "column": "x",
                        "aggregate": "mean",
                        "python": "os.system('rm -rf /')",
                    }
                ],
            }
        )


def test_schema_gate_rejects_unknown_column() -> None:
    """Gate 2: a structurally valid plan can still reference a column that
    does not exist in this DataFrame."""
    from flashfusion.pipeline.operators import (
        PlanSchemaError,
        validate_plan_against_dataframe,
    )

    plan = _plan({"op": "AGGREGATE_COLUMN", "column": "heart_rate", "aggregate": "mean"})
    with pytest.raises(PlanSchemaError, match="heart_rate"):
        validate_plan_against_dataframe(plan, _df())


def test_schema_gate_rejects_numeric_aggregate_on_text_column() -> None:
    from flashfusion.pipeline.operators import (
        PlanSchemaError,
        validate_plan_against_dataframe,
    )

    plan = _plan(
        {"op": "AGGREGATE_COLUMN", "column": "activity_label", "aggregate": "mean"}
    )
    with pytest.raises(PlanSchemaError, match="numeric"):
        validate_plan_against_dataframe(plan, _df())


def test_typed_plan_executes_filter_then_aggregate() -> None:
    from flashfusion.pipeline.operators import execute_plan, validate_plan_against_dataframe

    plan = _plan(
        {"op": "FILTER_COMPARE", "column": "subject_id", "comparator": "eq", "value": 1600},
        {"op": "AGGREGATE_COLUMN", "column": "x", "aggregate": "max"},
    )
    validate_plan_against_dataframe(plan, _df())
    execution = execute_plan(_df(), plan)

    assert execution.ok is True
    assert execution.value == 0.1
    assert execution.operators_used == ["FILTER_COMPARE", "AGGREGATE_COLUMN"]
    assert execution.rows_after_filter == 1


def test_typed_plan_predictive_uses_filtered_working_frame() -> None:
    from flashfusion.pipeline.operators import execute_plan

    df = pd.DataFrame(
        {
            "record_id": [101, 101, 101, 101, 202, 202],
            "time_s": [0, 1, 2, 3, 4, 5],
            "MLII": [0.1, 0.2, 0.3, 0.4, 9.0, 9.5],
            "V1": [0.1, 0.1, 0.2, 0.2, 9.0, 9.0],
            "annotation": ["N", "", "N", "", "", ""],
        }
    )
    plan = _plan(
        {"op": "FILTER_COMPARE", "column": "record_id", "comparator": "eq", "value": 101},
        {
            "op": "PREDICTIVE_PIPELINE",
            "model": "logistic_regression",
            "feature_columns": ["MLII", "V1"],
            "target_column": "annotation",
            "sort_by": ["time_s"],
            "train_fraction": 0.5,
            "holdout_row": "first",
            "filter_column": None,
            "filter_value": None,
            "target_from_non_empty": True,
            "target_label": "present",
        },
    )

    execution = execute_plan(df, plan)

    assert execution.ok is True
    assert "split=2/4" in execution.code


def test_aggregate_groups_render_does_not_reference_undefined_grouped() -> None:
    from flashfusion.pipeline.operators import execute_plan

    plan = _plan(
        {
            "op": "GROUP_AGGREGATE",
            "group_by": ["subject_id"],
            "column": "x",
            "aggregate": "mean",
        },
        {"op": "AGGREGATE_GROUPS", "aggregate": "mean"},
    )

    execution = execute_plan(_df(), plan)

    assert execution.ok is True
    assert "grouped." not in execution.code
    assert "result = result.mean()" in execution.code


def test_abs_difference_render_is_explicit_and_valid() -> None:
    from flashfusion.pipeline.operators import execute_plan

    df = pd.DataFrame({"a": [1.0, -2.0], "b": [-3.0, 4.0]})
    plan = _plan(
        {
            "op": "DERIVE_BINARY",
            "left": "a",
            "right": "b",
            "operation": "abs_difference",
            "result": "delta",
        }
    )

    execution = execute_plan(df, plan)

    assert execution.ok is True
    assert "(df['a'] - df['b']).abs()" in execution.code
    assert "(abs)" not in execution.code


def test_typed_plan_returns_all_values_at_a_tied_column_maximum() -> None:
    from flashfusion.pipeline.operators import execute_plan, validate_plan_against_dataframe

    df = pd.DataFrame(
        {
            "timestamp": ["2026-01-01T00:00:00", "2026-01-01T00:01:00", "2026-01-01T00:02:00"],
            "accel_stats_z_p99": [1.0, 2.0, 2.0],
        }
    )
    plan = _plan(
        {"op": "FILTER_EQ_AGGREGATE", "column": "accel_stats_z_p99", "aggregate": "max"},
        {"op": "SELECT_COLUMN", "column": "timestamp"},
    )

    validate_plan_against_dataframe(plan, df)
    execution = execute_plan(df, plan)

    assert execution.ok is True
    assert execution.value == ["2026-01-01T00:01:00", "2026-01-01T00:02:00"]
    assert execution.operators_used == ["FILTER_EQ_AGGREGATE", "SELECT_COLUMN"]


def test_typed_plan_groupby_then_rank_returns_group_and_metric() -> None:
    from flashfusion.pipeline.operators import execute_plan

    plan = _plan(
        {
            "op": "GROUP_AGGREGATE",
            "group_by": ["subject_id"],
            "column": "timestamp",
            "aggregate": "sum",
        },
        {"op": "RANK_GROUPS", "direction": "max"},
    )
    execution = execute_plan(_df(), plan)

    assert execution.ok is True
    assert execution.value == {"subject_id": 1601, "sum_timestamp": 2000}


def test_typed_plan_temporal_minute_rank_returns_window_and_mean() -> None:
    from flashfusion.pipeline.operators import execute_plan, validate_plan_against_dataframe

    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2025-06-06 16:00:10",
                    "2025-06-06 16:01:00",
                    "2025-06-06 16:01:20",
                    "2025-06-06 16:01:40",
                    "2025-06-06 16:02:05",
                ]
            ),
            "instability_score": [4.8, 6.0, 5.8, 5.807, 5.1],
        }
    )

    plan = _plan(
        {
            "op": "DERIVE_BIN",
            "column": "timestamp",
            "kind": "temporal",
            "freq": "1min",
            "result": "minute_window",
        },
        {
            "op": "GROUP_AGGREGATE",
            "group_by": ["minute_window"],
            "aggregate": "mean",
            "column": "instability_score",
        },
        {"op": "RANK_GROUPS", "direction": "max"},
    )

    validate_plan_against_dataframe(plan, df)
    execution = execute_plan(df, plan)

    assert execution.ok is True
    assert isinstance(execution.value, dict)
    assert execution.value["minute_window"] == "2025-06-06T16:01:00"
    assert execution.value["mean_instability_score"] == pytest.approx(5.869)
    assert not isinstance(execution.value, list)


def test_typed_plan_derive_bin_numeric_mode_stays_backward_compatible() -> None:
    from flashfusion.pipeline.operators import execute_plan, validate_plan_against_dataframe

    df = pd.DataFrame({"x": [1, 2, 11, 12]})
    plan = _plan(
        {
            "op": "DERIVE_BIN",
            "column": "x",
            "kind": "numeric",
            "width": 10,
            "result": "x_bin",
        },
        {"op": "SELECT_COLUMN", "column": "x_bin", "distinct": True},
    )

    validate_plan_against_dataframe(plan, df)
    execution = execute_plan(df, plan)

    assert execution.ok is True
    assert execution.value == [0, 10]


def test_typed_plan_temporal_bin_requires_epoch_unit_for_numeric_timestamp() -> None:
    from flashfusion.pipeline.operators import PlanSchemaError, validate_plan_against_dataframe

    df = pd.DataFrame(
        {
            "ts_ns": [
                1749225660000000000,
                1749225670000000000,
            ],
            "instability_score": [5.0, 6.0],
        }
    )
    plan = _plan(
        {
            "op": "DERIVE_BIN",
            "column": "ts_ns",
            "kind": "temporal",
            "freq": "1min",
            "result": "minute_window",
        }
    )

    with pytest.raises(PlanSchemaError, match="epoch_unit"):
        validate_plan_against_dataframe(plan, df)


def test_typed_plan_temporal_bin_numeric_timestamp_with_epoch_unit_executes() -> None:
    from flashfusion.pipeline.operators import execute_plan, validate_plan_against_dataframe

    df = pd.DataFrame(
        {
            "ts_ns": [
                1749225660000000000,
                1749225670000000000,
            ],
            "instability_score": [5.0, 6.0],
        }
    )
    plan = _plan(
        {
            "op": "DERIVE_BIN",
            "column": "ts_ns",
            "kind": "temporal",
            "freq": "1min",
            "epoch_unit": "ns",
            "result": "minute_window",
        },
        {"op": "SELECT_COLUMN", "column": "minute_window", "distinct": True},
    )

    validate_plan_against_dataframe(plan, df)
    execution = execute_plan(df, plan)

    assert execution.ok is True
    assert execution.value == ["2025-06-06T16:01:00"]


def test_typed_plan_rank_groups_all_null_values_fails_deterministically() -> None:
    from flashfusion.pipeline.operators import execute_plan

    df = pd.DataFrame(
        {
            "minute_window": pd.to_datetime(["2025-06-06 16:00:00", "2025-06-06 16:01:00"]),
            "instability_score": [float("nan"), float("nan")],
        }
    )
    plan = _plan(
        {
            "op": "GROUP_AGGREGATE",
            "group_by": ["minute_window"],
            "aggregate": "mean",
            "column": "instability_score",
        },
        {"op": "RANK_GROUPS", "direction": "max"},
    )

    execution = execute_plan(df, plan)
    assert execution.ok is False
    assert "non-null grouped values" in (execution.error or "")


def test_typed_plan_rank_groups_tie_uses_first_group() -> None:
    from flashfusion.pipeline.operators import execute_plan, validate_plan_against_dataframe

    df = pd.DataFrame(
        {
            "minute_window": pd.to_datetime(["2025-06-06 16:01:00", "2025-06-06 16:02:00"]),
            "instability_score": [5.0, 5.0],
        }
    )
    plan = _plan(
        {
            "op": "GROUP_AGGREGATE",
            "group_by": ["minute_window"],
            "aggregate": "mean",
            "column": "instability_score",
        },
        {"op": "RANK_GROUPS", "direction": "max"},
    )

    validate_plan_against_dataframe(plan, df)
    execution = execute_plan(df, plan)

    assert execution.ok is True
    assert execution.value["minute_window"] == "2025-06-06T16:01:00"
    assert execution.value["mean_instability_score"] == 5.0


def test_schema_gate_rejects_steps_after_rank_groups() -> None:
    from flashfusion.pipeline.operators import PlanSchemaError, validate_plan_against_dataframe

    plan = _plan(
        {
            "op": "GROUP_AGGREGATE",
            "group_by": ["subject_id"],
            "column": "timestamp",
            "aggregate": "sum",
        },
        {"op": "RANK_GROUPS", "direction": "max"},
        {"op": "SELECT_COLUMN", "column": "subject_id"},
    )

    with pytest.raises(PlanSchemaError, match="RANK_GROUPS must be the final step"):
        validate_plan_against_dataframe(plan, _df())


def test_typed_plan_rank_on_empty_frame_reports_error_not_crash() -> None:
    """An empty filter must surface as a coverage gap, not a pandas traceback."""
    from flashfusion.pipeline.operators import execute_plan

    plan = _plan(
        {
            "op": "FILTER_COMPARE",
            "column": "activity_label",
            "comparator": "eq",
            "value": "Missing",
        },
        {
            "op": "RANK_ROWS",
            "column": "x",
            "direction": "max",
            "return_columns": ["timestamp"],
        },
    )
    execution = execute_plan(_df(), plan)

    assert execution.ok is False
    assert "no rows" in (execution.error or "")


def test_parallel_aggregate_preserves_common_prefix_filter() -> None:
    from flashfusion.pipeline.operators import execute_plan

    df = pd.DataFrame(
        {
            "record_id": [101, 101, 102, 102],
            "label": ["annotated", "plain", "annotated", "plain"],
        }
    )
    plan = _plan(
        {"op": "FILTER_COMPARE", "column": "record_id", "comparator": "eq", "value": 101},
        {
            "op": "PARALLEL_AGGREGATE",
            "branches": [
                {
                    "filter_column": "label",
                    "filter_values": ["annotated"],
                    "group_by": ["record_id"],
                    "aggregate": "count",
                    "column": None,
                    "result_column": "annotated_count",
                },
                {
                    "filter_column": None,
                    "filter_values": None,
                    "group_by": ["record_id"],
                    "aggregate": "count",
                    "column": None,
                    "result_column": "total_count",
                },
            ],
        },
        {
            "op": "RANK_ROWS",
            "column": "total_count",
            "direction": "max",
            "return_columns": ["record_id", "annotated_count", "total_count"],
        },
    )

    execution = execute_plan(df, plan)

    assert execution.ok is True
    assert execution.value == {"record_id": 101, "annotated_count": 1, "total_count": 2}
    assert ".groupby(['record_id']).size()" in execution.code


def test_parallel_aggregate_does_not_zero_fill_missing_means() -> None:
    from flashfusion.pipeline.operators import execute_plan

    df = pd.DataFrame(
        {
            "subject_id": [1, 1, 2, 2, 3],
            "activity": ["dynamic", "resting", "dynamic", "resting", "dynamic"],
            "magnitude": [12.0, 10.0, 15.0, 10.0, 100.0],
        }
    )
    plan = _plan(
        {
            "op": "PARALLEL_AGGREGATE",
            "branches": [
                {
                    "filter_column": "activity",
                    "filter_values": ["dynamic"],
                    "group_by": ["subject_id"],
                    "aggregate": "mean",
                    "column": "magnitude",
                    "result_column": "dynamic_mean",
                },
                {
                    "filter_column": "activity",
                    "filter_values": ["resting"],
                    "group_by": ["subject_id"],
                    "aggregate": "mean",
                    "column": "magnitude",
                    "result_column": "resting_mean",
                },
            ],
        },
        {
            "op": "DERIVE_BINARY",
            "left": "dynamic_mean",
            "right": "resting_mean",
            "operation": "subtract",
            "result": "delta",
        },
        {
            "op": "RANK_ROWS",
            "column": "delta",
            "direction": "max",
            "return_columns": ["subject_id", "delta"],
        },
    )

    execution = execute_plan(df, plan)

    assert execution.ok is True
    assert execution.value == {"subject_id": 2, "delta": 5.0}


def test_build_react_query_includes_grounding_and_ambiguous_concepts() -> None:
    from flashfusion.baselines.flash_fusion import build_react_query

    out = build_react_query(
        "Which user is roughest?",
        "MAPPINGS:\n  roughness → accel_variance\nUNMAPPABLE: NONE",
        ["roughness"],
    )
    assert "Which user is roughest?" in out
    assert "accel_variance" in out
    assert "roughness" in out


def test_agent_runs_agent_without_guardrail() -> None:
    from flashfusion.baselines.react_only import run_react_only

    query = "What is the average x-axis acceleration?"
    r = _result("REACT_ONLY", query)

    with patch("flashfusion.baselines.react_only.ExecutionLayer") as execution_layer_cls:
        executor = execution_layer_cls.return_value
        executor.execute_single.return_value = ("answer", "trace", MagicMock(final_code="code", tries=1))

        out = run_react_only(query, _df(), _client(), r)

    executor.guardrail.assert_not_called()
    executor.execute_single.assert_called_once_with(query)
    assert out.executed is True
    assert out.rejected is False
    assert out.answer_source == "model_final_answer"
    assert out.execution_path == "react_agent"
    assert out.stages_run == ["react_agent"]


def test_react_only_marks_scope_check_abstention_as_rejected() -> None:
    from flashfusion.baselines.react_only import run_react_only

    query = "Can you predict next week's pothole repairs?"
    r = _result("REACT_ONLY", query)

    abstention = "REJECT: Future pothole repair labels are not present in the dataset."

    with patch("flashfusion.baselines.react_only.ExecutionLayer") as execution_layer_cls:
        executor = execution_layer_cls.return_value
        executor.execute_single.return_value = (
            abstention,
            "trace",
            MagicMock(final_code="code", tries=1, attempts=[]),
        )

        out = run_react_only(query, _df(), _client(), r)

    assert out.rejected is True
    assert out.executed is False
    assert out.rejection_reason == abstention
    assert out.answer_source == "structured_rejection"
    assert out.execution_path == "react_reject"
    assert out.stages_run == ["react_agent"]


def test_react_only_non_abstention_answer_remains_executed() -> None:
    from flashfusion.baselines.react_only import run_react_only

    query = "What is the average x-axis acceleration?"
    r = _result("REACT_ONLY", query)

    with patch("flashfusion.baselines.react_only.ExecutionLayer") as execution_layer_cls:
        executor = execution_layer_cls.return_value
        executor.execute_single.return_value = (
            "The average x-axis acceleration is 0.52.",
            "trace",
            MagicMock(final_code="code", tries=1, attempts=[]),
        )

        out = run_react_only(query, _df(), _client(), r)

    assert out.rejected is False
    assert out.executed is True
    assert out.answer_source == "model_final_answer"
    assert out.execution_path == "react_agent"
    assert out.stages_run == ["react_agent"]


def test_react_only_propagates_structured_executor_outcome() -> None:
    from flashfusion.baselines.react_only import run_react_only
    from flashfusion.pipeline.executor import ExecutionDetails, ReActResult

    query = "Predict holdout label"
    r = _result("REACT_ONLY", query)

    structured = ReActResult(
        raw_answer="The predicted behavior label for the first holdout row is: moderate.",
        trace="trace",
        rejected=False,
        rejection_reason=None,
        answer_source="executed_observation",
        executed_value="moderate",
        details=ExecutionDetails(
            final_code="result = 'moderate'",
            tries=1,
            attempts=[],
            rejected=False,
            rejection_reason=None,
            answer_source="executed_observation",
            executed_value="moderate",
        ),
    )

    with patch("flashfusion.baselines.react_only.ExecutionLayer") as execution_layer_cls:
        executor = execution_layer_cls.return_value
        executor.execute_single.return_value = structured

        out = run_react_only(query, _df(), _client(), r)

    assert out.rejected is False
    assert out.executed is True
    assert out.answer_source == "executed_observation"
    assert out.executed_value == "moderate"
    assert out.execution_path == "react_agent"


def test_react_only_structural_rejection_survives_serialization() -> None:
    from flashfusion.baselines.react_only import run_react_only
    from flashfusion.pipeline.executor import ExecutionDetails, ReActResult

    query = "Forecast pothole repairs"
    r = _result("REACT_ONLY", query)

    structured = ReActResult(
        raw_answer="REJECT: Missing required dataset concept(s): pothole repair labels/history.",
        trace="trace",
        rejected=True,
        rejection_reason="Missing required dataset concept(s): pothole repair labels/history.",
        answer_source="structured_rejection",
        executed_value=None,
        details=ExecutionDetails(
            final_code="",
            tries=0,
            attempts=[],
            rejected=True,
            rejection_reason="Missing required dataset concept(s): pothole repair labels/history.",
            answer_source="structured_rejection",
            executed_value=None,
        ),
    )

    with patch("flashfusion.baselines.react_only.ExecutionLayer") as execution_layer_cls:
        executor = execution_layer_cls.return_value
        executor.execute_single.return_value = structured

        out = run_react_only(query, _df(), _client(), r)

    payload = dataclasses.asdict(out)
    assert payload["rejected"] is True
    assert payload["rejection_reason"]
    assert payload["execution_path"] == "react_reject"
    assert payload["answer_source"] == "structured_rejection"


def test_wellmax_executes_grounded_query_without_guardrail() -> None:
    from flashfusion.baselines.wellmax_only import run_wellmax_only

    query = "Compare sedentary and locomotion magnitude."
    r = _result("WELLMAX_ONLY", query)

    with patch("flashfusion.baselines.wellmax_only.Stage1_ConceptExtraction") as s1_cls, patch(
        "flashfusion.baselines.wellmax_only.Stage2_SchemaGrounding"
    ) as s2_cls, patch(
        "flashfusion.baselines.wellmax_only.Stage3_SubqueryGeneration"
    ) as s3_cls, patch(
        "flashfusion.baselines.wellmax_only.ExecutionLayer"
    ) as execution_layer_cls:
        s1_cls.return_value.run.return_value = {"DATA": ["magnitude"], "REASONING": ["sedentary"]}
        s2_cls.return_value.run.return_value = {
            "raw_grounding": "MAPPINGS:\n  sedentary -> D,E",
            "mappings": ["sedentary -> D,E"],
            "unmappable": [],
        }
        s3_cls.return_value.run.return_value = {
            "sub_queries": ["[FILTER] activity_label in D,E", "[AGGREGATE] mean magnitude"],
            "synthesis_hint": "Compare means",
        }

        executor = execution_layer_cls.return_value
        executor.execute_single.return_value = ("answer", "trace", MagicMock(final_code="code", tries=2))

        out = run_wellmax_only(query, _df(), _client(), r)

    executor.guardrail.assert_not_called()
    assert executor.execute_single.call_count == 1
    grounded_query_arg = executor.execute_single.call_args[0][0]
    assert "Concept-to-column mappings" in grounded_query_arg
    assert out.executed is True
    assert out.rejected is False
    assert out.stages_run == ["S1", "S2", "S3", "agent"]


def test_flash_fusion_rejection_sets_explanation() -> None:
    from flashfusion.baselines.flash_fusion import run_flash_fusion
    from flashfusion.pipeline.operators import GuardrailAndPlan

    query = "What is average heart rate during jogging?"
    r = _result("FLASH_FUSION", query)

    verdict = GuardrailAndPlan(
        in_scope=False, rejection_reason="heart_rate is not in schema", plan=None
    )

    with patch(
        "flashfusion.baselines.flash_fusion.request_guardrail_and_plan",
        return_value=_guardrail_return(verdict),
    ), patch("flashfusion.baselines.flash_fusion.ExecutionLayer") as execution_layer_cls:
        out = run_flash_fusion(query, _df(), _client(), r)

    execution_layer_cls.return_value.execute_single.assert_not_called()
    assert out.rejected is True
    assert out.executed is False
    assert out.execution_path == "guardrail_reject"
    assert "heart_rate is not in schema" in out.rejection_reason
    assert out.stages_run == ["guardrail_plan"]


def test_flash_fusion_typed_path_never_invokes_react() -> None:
    """The default path executes typed operators in-process with no synthesis call."""
    from flashfusion.baselines.flash_fusion import run_flash_fusion
    from flashfusion.pipeline.operators import GuardrailAndPlan

    query = "What is the maximum x observed in this dataset?"
    r = _result("FLASH_FUSION", query)
    plan = _plan({"op": "AGGREGATE_COLUMN", "column": "x", "aggregate": "max"})

    with patch(
        "flashfusion.baselines.flash_fusion.request_guardrail_and_plan",
        return_value=_guardrail_return(GuardrailAndPlan(in_scope=True, plan=plan)),
    ), patch("flashfusion.baselines.flash_fusion.ExecutionLayer") as execution_layer_cls:
        out = run_flash_fusion(query, _df(), _client(), r)

    execution_layer_cls.return_value.execute_single.assert_not_called()
    assert out.executed is True
    assert out.execution_path == "typed_operator"
    assert out.plan_validation_stage_failed == ""
    assert out.operators_used == ["AGGREGATE_COLUMN"]
    assert out.answer == "The result is 0.2"
    assert out.stages_run == [
        "guardrail_plan",
        "plan_validated",
        "typed_exec",
    ]
    execution_layer_cls.return_value.synthesize.assert_not_called()


def test_flash_fusion_formats_ranked_temporal_window_answer() -> None:
    from flashfusion.baselines.flash_fusion import run_flash_fusion
    from flashfusion.pipeline.operators import GuardrailAndPlan

    query = "If we group the data into 1-minute intervals, which time window has the highest mean instability score?"
    r = _result("FLASH_FUSION", query)
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2025-06-06 16:00:10",
                    "2025-06-06 16:01:00",
                    "2025-06-06 16:01:20",
                    "2025-06-06 16:01:40",
                ]
            ),
            "instability_score": [4.8, 6.0, 5.8, 5.807],
        }
    )
    plan = _plan(
        {
            "op": "DERIVE_BIN",
            "column": "timestamp",
            "kind": "temporal",
            "freq": "1min",
            "result": "minute_window",
        },
        {
            "op": "GROUP_AGGREGATE",
            "group_by": ["minute_window"],
            "aggregate": "mean",
            "column": "instability_score",
        },
        {"op": "RANK_GROUPS", "direction": "max"},
    )

    with patch(
        "flashfusion.baselines.flash_fusion.request_guardrail_and_plan",
        return_value=_guardrail_return(GuardrailAndPlan(in_scope=True, plan=plan)),
    ), patch("flashfusion.baselines.flash_fusion.ExecutionLayer") as execution_layer_cls:
        out = run_flash_fusion(query, df, _client(), r)

    execution_layer_cls.return_value.execute_single.assert_not_called()
    assert out.executed is True
    assert "minute window" in out.answer
    assert "2025-06-06T16:01:00" in out.answer
    assert "5.8690" in out.answer


def test_flash_fusion_falls_back_to_react_when_vocabulary_cannot_express_query() -> None:
    """in_scope with no plan is a coverage gap: fall back, never improvise an
    operator inline."""
    from flashfusion.baselines.flash_fusion import run_flash_fusion
    from flashfusion.pipeline.operators import GuardrailAndPlan

    query = "Which user's resting duration exceeds their dynamic duration most?"
    r = _result("FLASH_FUSION", query)

    verdict = GuardrailAndPlan(
        in_scope=True, plan=None, ambiguous_concepts=["resting duration margin"]
    )

    with patch(
        "flashfusion.baselines.flash_fusion.request_guardrail_and_plan",
        return_value=_guardrail_return(verdict),
    ), patch(
        "flashfusion.baselines.flash_fusion.FF_FALLBACK_GROUNDING", False
    ), patch(
        "flashfusion.baselines.flash_fusion.log_operator_gap"
    ) as gap_log, patch(
        "flashfusion.baselines.flash_fusion.ExecutionLayer"
    ) as execution_layer_cls:
        executor = execution_layer_cls.return_value
        executor.execute_single.return_value = (
            "Subject 1601",
            "trace",
            MagicMock(final_code="code", tries=2, attempts=[]),
        )
        executor.synthesize.return_value = "Subject 1601 has the largest margin."
        out = run_flash_fusion(query, _df(), _client(), r)

    gap_log.assert_called_once()
    assert gap_log.call_args.kwargs["stage"] == "no_plan"
    assert out.execution_path == "react_fallback"
    assert out.plan_validation_stage_failed == "no_plan"
    assert out.executed is True
    assert executor.execute_single.call_args.args[0] == query


def test_flash_fusion_can_disable_react_fallback_for_typed_plan_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flashfusion.baselines import flash_fusion
    from flashfusion.pipeline.operators import GuardrailAndPlan

    query = "Which user's resting duration exceeds their dynamic duration most?"
    r = _result("FLASH_FUSION", query)
    verdict = GuardrailAndPlan(
        in_scope=True, plan=None, ambiguous_concepts=["resting duration margin"]
    )
    monkeypatch.setattr(flash_fusion, "FF_REACT_FALLBACK", False)

    with patch(
        "flashfusion.baselines.flash_fusion.request_guardrail_and_plan",
        return_value=_guardrail_return(verdict),
    ), patch(
        "flashfusion.baselines.flash_fusion.log_operator_gap"
    ) as gap_log, patch(
        "flashfusion.baselines.flash_fusion.ExecutionLayer"
    ) as execution_layer_cls:
        out = flash_fusion.run_flash_fusion(query, _df(), _client(), r)

    gap_log.assert_called_once()
    execution_layer_cls.assert_not_called()
    assert out.execution_path == "typed_plan_unavailable"
    assert out.plan_validation_stage_failed == "no_plan"
    assert out.executed is False
    assert out.rejected is False
    assert out.answer == ""
    assert out.stages_run == ["guardrail_plan", "typed_plan_unavailable"]


def test_flash_fusion_rejects_when_plan_names_a_column_the_dataset_lacks() -> None:
    """A missing field is a verdict about the question, not a vocabulary gap.

    ReAct cannot invent the column either — it can only hallucinate a number —
    so Gate 2 terminates the query instead of falling back.
    """
    from flashfusion.baselines.flash_fusion import run_flash_fusion
    from flashfusion.pipeline.operators import GuardrailAndPlan

    query = "What is the average heart rate?"
    r = _result("FLASH_FUSION", query)
    plan = _plan({"op": "AGGREGATE_COLUMN", "column": "heart_rate", "aggregate": "mean"})

    with patch(
        "flashfusion.baselines.flash_fusion.request_guardrail_and_plan",
        return_value=_guardrail_return(GuardrailAndPlan(in_scope=True, plan=plan)),
    ), patch(
        "flashfusion.baselines.flash_fusion.FF_FALLBACK_GROUNDING", False
    ), patch(
        "flashfusion.baselines.flash_fusion.log_operator_gap"
    ) as gap_log, patch(
        "flashfusion.baselines.flash_fusion.ExecutionLayer"
    ) as execution_layer_cls:
        out = run_flash_fusion(query, _df(), _client(), r)

    execution_layer_cls.return_value.execute_single.assert_not_called()
    assert gap_log.call_args.kwargs["stage"] == "scope"
    assert out.plan_validation_stage_failed == "scope"
    assert out.execution_path == "scope_reject"
    assert out.rejected is True
    assert out.executed is False
    assert out.missing_columns == ["heart_rate"]
    assert out.typed_plan == {}


def test_flash_fusion_predictive_query_is_planned_by_lm() -> None:
    from flashfusion.baselines.flash_fusion import run_flash_fusion
    from flashfusion.pipeline.operators import GuardrailAndPlan

    query = (
        "Sort all WISDM rows by timestamp in ascending order, using subject_id as "
        "the tie-breaker. Use the first 80% of rows for training and the final 20% "
        "as the chronological holdout. Train a random forest model using the "
        "features x, y and z. Predict the activity label for the first row in the "
        "holdout set."
    )
    r = _result("FLASH_FUSION", query)
    plan = _plan(
        {
            "op": "PREDICTIVE_PIPELINE",
            "model": "random_forest",
            "feature_columns": ["x", "y", "z"],
            "target_column": "activity_label",
            "sort_by": ["timestamp", "subject_id"],
            "train_fraction": 0.8,
            "holdout_row": "first",
            "target_label": "activity",
        }
    )

    with patch(
        "flashfusion.baselines.flash_fusion.request_guardrail_and_plan",
        return_value=_guardrail_return(GuardrailAndPlan(in_scope=True, plan=plan)),
    ) as plan_call, patch(
        "flashfusion.baselines.flash_fusion.ExecutionLayer"
    ) as execution_layer_cls:
        execution_layer_cls.return_value.synthesize.return_value = "Predicted A."
        out = run_flash_fusion(query, _df(), _client(), r)

    plan_call.assert_called_once()
    execution_layer_cls.return_value.execute_single.assert_not_called()
    assert out.plan_source == "llm"
    assert out.execution_path == "typed_operator"
    assert "guardrail_plan" in out.stages_run
    assert out.typed_plan["steps"][0]["feature_columns"] == ["x", "y", "z"]
    assert out.typed_plan["steps"][0]["model"] == "random_forest"
    assert out.typed_plan["steps"][0]["sort_by"] == ["timestamp", "subject_id"]


@pytest.mark.parametrize(
    "model",
    [
        "logistic_regression",
        "random_forest",
        "one_nearest_neighbor",
        "hist_gradient_boosting",
    ],
)
def test_predictive_models_survive_the_typed_path(model: str) -> None:
    """The predictive benchmark variants may differ only by typed model enum."""
    from flashfusion.baselines.flash_fusion import run_flash_fusion
    from flashfusion.pipeline.operators import GuardrailAndPlan

    query = "Predict the activity label for the first chronological holdout row."
    plan = _plan(
        {
            "op": "PREDICTIVE_PIPELINE",
            "model": model,
            "feature_columns": ["x", "y", "z"],
            "target_column": "activity_label",
            "sort_by": ["timestamp", "subject_id"],
            "train_fraction": 0.8,
            "holdout_row": "first",
            "filter_column": None,
            "filter_value": None,
            "target_from_non_empty": False,
            "target_label": "activity",
        }
    )
    execution = MagicMock(
        ok=True,
        value="Walking",
        trace="predictive trace",
        code="predictive code",
        steps=["PREDICTIVE_PIPELINE"],
        latency_ms=1.0,
    )

    with patch(
        "flashfusion.baselines.flash_fusion.request_guardrail_and_plan",
        return_value=_guardrail_return(GuardrailAndPlan(in_scope=True, plan=plan)),
    ), patch(
        "flashfusion.baselines.flash_fusion.execute_plan", return_value=execution
    ):
        out = run_flash_fusion(query, _df(), _client(), _result("FLASH_FUSION", query))

    assert out.plan_source == "llm"
    assert out.execution_path == "typed_operator"
    assert out.typed_plan["steps"][0]["model"] == model
    # The router must never strip the predictive bucket from a predictive query.
    assert "PREDICTIVE_PIPELINE" in out.operator_route_candidate_ops


def test_autoiot_paper_requires_tavily_key() -> None:
    from flashfusion.baselines.autoiot_paper import run_autoiot_paper

    query = "Find the average acceleration magnitude for walking."
    r = _result("AUTOIOT_PAPER", query)

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
            run_autoiot_paper(query, _df(), _client(), r)


def test_runner_dispatches_autoiot_paper_mode() -> None:
    client = _client()
    runner = BaselineRunner(mode="AUTOIOT_PAPER", df=_df(), client=client)

    with patch("flashfusion.baselines.autoiot_paper.run_autoiot_paper") as fn:
        runner.run("Compare mean x by activity")

    fn.assert_called_once()


def test_autoiot_paper_uses_generated_search_queries_for_tavily() -> None:
    from flashfusion.baselines import autoiot_paper

    query = "Find average magnitude while walking"
    r = _result("AUTOIOT_PAPER", query)

    stage_inputs: dict[str, str] = {}

    def fake_invoke(client, stage, system_prompt, user_input):
        stage_inputs[stage] = user_input
        if stage == "autoiot_terms":
            return "magnitude"
        if stage == "autoiot_search_queries":
            return "wisdm magnitude walking"
        if stage == "autoiot_design_high":
            return "Step 1: prepare"
        if stage == "autoiot_design_detail":
            return "Step 1: prepare\n- clean data"
        if stage.startswith("autoiot_module_gen_"):
            return "```python\ndef module_part():\n    return 1\n```"
        if stage == "autoiot_code_integration":
            return "```python\ndef run():\n    return 1\n```"
        if stage.startswith("autoiot_improve_"):
            return "tighten aggregation"
        if stage == "autoiot_select":
            return "1"
        return ""

    class FakeExecutionLayer:
        def __init__(self, df, client):
            pass

        def execute_single(self, query_text):
            return (
                "ok",
                "Observation: success",
                MagicMock(final_code="result = 1", tries=1, attempts=[]),
            )

    tavily_calls: list[str] = []

    def fake_tavily_search(**kwargs):
        tavily_calls.append(kwargs["query"])
        return [{"url": "https://example.com", "content": "context"}]

    with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}, clear=True), patch.object(
        autoiot_paper, "AUTOIOT_PAPER_ITERATIONS", 2
    ), patch.object(
        autoiot_paper, "_invoke", side_effect=fake_invoke
    ), patch.object(
        autoiot_paper, "ExecutionLayer", FakeExecutionLayer
    ), patch.object(
        autoiot_paper, "_tavily_search", side_effect=fake_tavily_search
    ):
        out = autoiot_paper.run_autoiot_paper(query, _df(), _client(), r)

    assert "wisdm magnitude walking" in tavily_calls
    assert "autoiot_search_queries" in out.stages_run
    assert "autoiot_module_gen" in out.stages_run
    assert "autoiot_code_integration" in out.stages_run
    assert set(out.stage_latency_s) == {"s1", "s2", "s3", "guardrail", "agent"}
    assert all(value >= 0.0 for value in out.stage_latency_s.values())
    operations = {event["operation"] for event in out.stage_events}
    assert {"extract_terms", "generate_search_queries", "retrieve_context"}.issubset(operations)
    assert {"design_high_level", "design_detail"}.issubset(operations)
    assert {"integrate_modules", "execute_round_1", "execute_round_2"}.issubset(operations)
    assert {"collect_feedback_round_1", "refine_round_1", "select_best_version"}.issubset(operations)


def test_autoiot_paper_improvement_prompt_uses_execution_feedback() -> None:
    from flashfusion.baselines import autoiot_paper

    query = "Find average magnitude while walking"
    r = _result("AUTOIOT_PAPER", query)

    improve_inputs: list[str] = []

    def fake_invoke(client, stage, system_prompt, user_input):
        if stage == "autoiot_terms":
            return "magnitude"
        if stage == "autoiot_search_queries":
            return "wisdm magnitude"
        if stage == "autoiot_design_high":
            return "Step 1: prepare"
        if stage == "autoiot_design_detail":
            return "Step 1: prepare\n- clean data"
        if stage.startswith("autoiot_module_gen_"):
            return "```python\ndef module_part():\n    return 1\n```"
        if stage == "autoiot_code_integration":
            return "```python\ndef run():\n    return 1\n```"
        if stage.startswith("autoiot_correct_"):
            return "```python\ndef run():\n    return 2\n```"
        if stage.startswith("autoiot_improve_"):
            improve_inputs.append(user_input)
            return "use corrected code"
        if stage == "autoiot_select":
            return "1"
        return ""

    class FakeExecutionLayer:
        def __init__(self, df, client):
            pass

        def execute_single(self, query_text):
            details = MagicMock(
                final_code="",
                tries=1,
                attempts=[{"attempt": 1, "ok": False, "output": "NameError: x is not defined"}],
            )
            return ("[ERROR] NameError", "Observation: NameError: x is not defined", details)

    with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}, clear=True), patch.object(
        autoiot_paper, "AUTOIOT_PAPER_ITERATIONS", 2
    ), patch.object(
        autoiot_paper, "_invoke", side_effect=fake_invoke
    ), patch.object(
        autoiot_paper, "ExecutionLayer", FakeExecutionLayer
    ), patch.object(
        autoiot_paper, "_tavily_search", return_value=[]
    ):
        autoiot_paper.run_autoiot_paper(query, _df(), _client(), r)

    assert len(improve_inputs) == 1
    assert "Execution stderr" in improve_inputs[0]
    assert "NameError: x is not defined" in improve_inputs[0]
    assert any(event["operation"] == "correct_round_1" for event in r.stage_events)


def test_hargpt_paper_classification_happy_path() -> None:
    from flashfusion.baselines import hargpt_paper

    query = "What activity is user 1600 doing based on these IMU readings?"
    r = _result("HARGPT_PAPER", query)

    with patch.object(
        hargpt_paper,
        "_invoke_rewritten",
        return_value="Step-by-step analysis...\nFinal answer: Walking",
    ):
        out = hargpt_paper.run_hargpt_paper(query, _df(), _client(), r)

    assert out.rejected is False
    assert out.executed is False
    assert out.answer == "Walking"
    assert "hargpt_wisdm_window" in out.stages_run
    assert "hargpt_wisdm_rewrite" in out.stages_run
    assert "hargpt_wisdm_infer" in out.stages_run
    assert "hargpt_wisdm_parse" in out.stages_run
    assert out.execution_attempts


def test_hargpt_paper_non_classification_query_uses_best_effort() -> None:
    from flashfusion.baselines import hargpt_paper

    query = "What is the maximum recorded x-acceleration for user 15?"
    r = _result("HARGPT_PAPER", query)

    with patch.object(hargpt_paper, "_invoke_rewritten", return_value="Final answer: 0.2") as fake_invoke:
        out = hargpt_paper.run_hargpt_paper(query, _df(), _client(), r)

    fake_invoke.assert_called_once()
    assert out.rejected is False
    assert out.executed is False
    assert out.answer == "0.2"


def test_hargpt_paper_non_imu_schema_uses_best_effort() -> None:
    from flashfusion.baselines import hargpt_paper

    query = "What activity is this ECG trace showing?"
    r = _result("HARGPT_PAPER", query)
    ecg_df = pd.DataFrame({"record_id": [101], "MLII": [0.1], "time_s": [0.0]})

    with patch.object(hargpt_paper, "_invoke_rewritten", return_value="Final answer: Best effort"):
        out = hargpt_paper.run_hargpt_paper(query, ecg_df, _client(), r)

    assert out.rejected is False
    assert out.executed is False
    assert "hargpt_wisdm_rewrite" in out.stages_run


def test_runner_dispatches_hargpt_paper_mode() -> None:
    client = _client()
    runner = BaselineRunner(mode="HARGPT_PAPER", df=_df(), client=client)

    with patch("flashfusion.baselines.hargpt_paper.run_hargpt_paper") as fn:
        runner.run("What activity is user 1600 doing?")

    fn.assert_called_once()


def test_runner_dispatches_llmsense_paper_mode() -> None:
    client = _client()
    runner = BaselineRunner(mode="LLMSENSE_PAPER", df=_df(), client=client)

    with patch("flashfusion.baselines.llmsense_paper.run_llmsense_paper") as fn:
        runner.run("Summarize user activities")

    fn.assert_called_once()


def test_llmsense_paper_short_trace_uses_narration_path() -> None:
    from flashfusion.baselines.llmsense_paper import run_llmsense_paper

    query = "What activities appear in this trace?"
    r = _result("LLMSENSE_PAPER", query)

    with patch("flashfusion.baselines.llmsense_paper._stage_narrate", return_value=("narrative", 2)) as narrate_fn, patch(
        "flashfusion.baselines.llmsense_paper._stage_summarize"
    ) as summarize_fn, patch(
        "flashfusion.baselines.llmsense_paper._stage_reason", return_value="answer"
    ) as reason_fn:
        out = run_llmsense_paper(query, _df(), _client(), r)

    narrate_fn.assert_called_once()
    summarize_fn.assert_not_called()
    reason_fn.assert_called_once()
    assert out.answer == "answer"
    assert out.trace == "narrative"
    assert out.executed is False
    assert out.rejected is False
    assert out.judge_verdict == {}
    assert out.stages_run == ["N_narrate", "R_reason"]


def test_llmsense_paper_long_trace_uses_summarization_path() -> None:
    from flashfusion.baselines.llmsense_paper import run_llmsense_paper

    query = "Which users show transitions?"
    r = _result("LLMSENSE_PAPER", query)

    long_df = pd.DataFrame(
        {
            "subject_id": [1600] * 130,
            "activity_label": ["A"] * 130,
            "timestamp": list(range(130)),
            "x": [0.1] * 130,
            "y": [0.2] * 130,
            "z": [0.3] * 130,
        }
    )

    with patch("flashfusion.baselines.llmsense_paper._stage_narrate") as narrate_fn, patch(
        "flashfusion.baselines.llmsense_paper._stage_summarize", return_value=("summary", 130)
    ) as summarize_fn, patch(
        "flashfusion.baselines.llmsense_paper._stage_reason", return_value="answer"
    ) as reason_fn:
        out = run_llmsense_paper(query, long_df, _client(), r)

    narrate_fn.assert_not_called()
    summarize_fn.assert_called_once()
    reason_fn.assert_called_once()
    assert out.answer == "answer"
    assert out.trace == "summary"
    assert out.executed is False
    assert out.rejected is False
    assert out.judge_verdict == {}
    assert out.stages_run == ["S_summarize", "R_reason"]


def _ecg_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "record_id": ["100", "100"],
            "time_s": [0.0, 0.003],
            "MLII": [0.96, 0.97],
            "V1": [0.01, 0.02],
            "annotation": ["N", "N"],
        }
    )


def _bus_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": ["2024-01-01 08:00:00", "2024-01-01 08:01:00"],
            "latitude": [51.5, 51.51],
            "longitude": [-0.1, -0.11],
            "accel_mean": [0.05, 0.08],
            "accel_variance": [0.001, 0.003],
        }
    )


def test_hargpt_paper_ecg_fallback_uses_narrative_path() -> None:
    from flashfusion.baselines import hargpt_paper

    query = "What is the dominant rhythm in this ECG segment?"
    r = _result("HARGPT_PAPER", query)

    with patch.object(
        hargpt_paper,
        "_invoke_rewritten",
        return_value="Step 1: signals appear normal.\nFinal answer: Normal sinus rhythm",
    ):
        out = hargpt_paper.run_hargpt_paper(query, _ecg_df(), _client(), r)

    assert out.rejected is False
    assert out.executed is False
    assert out.answer == "Normal sinus rhythm"
    assert "hargpt_ecg_window" in out.stages_run
    assert "hargpt_ecg_rewrite" in out.stages_run
    assert "hargpt_ecg_infer" in out.stages_run
    assert "hargpt_ecg_parse" in out.stages_run


def test_hargpt_paper_bus_fallback_uses_narrative_path() -> None:
    from flashfusion.baselines import hargpt_paper

    query = "Are there any high-vibration segments in this bus route?"
    r = _result("HARGPT_PAPER", query)

    with patch.object(
        hargpt_paper,
        "_invoke_rewritten",
        return_value="Step 1: accel variance spikes detected.\nFinal answer: High vibration road segment identified",
    ):
        out = hargpt_paper.run_hargpt_paper(query, _bus_df(), _client(), r)

    assert out.rejected is False
    assert out.executed is False
    assert out.answer == "High vibration road segment identified"
    assert "hargpt_bus_window" in out.stages_run
    assert "hargpt_bus_rewrite" in out.stages_run
    assert "hargpt_bus_infer" in out.stages_run
    assert "hargpt_bus_parse" in out.stages_run


def test_hargpt_paper_records_budget_metadata() -> None:
    from flashfusion.baselines import hargpt_paper

    query = "What activity is user 1600 doing based on these IMU readings?"
    r = _result("HARGPT_PAPER", query)

    with patch.object(
        hargpt_paper,
        "_invoke_rewritten",
        return_value="Final answer: Walking",
    ):
        out = hargpt_paper.run_hargpt_paper(query, _df(), _client(), r)

    assert out.execution_attempts
    attempt = out.execution_attempts[-1]
    assert attempt["budget_tokens_est"] > 0
    assert attempt["est_prompt_tokens"] > 0
    assert 0 < attempt["context_pct_window"] <= 100
    assert 0 < attempt["context_pct_budget"] <= 100
    assert attempt["prefilter_rows"] >= attempt["rows_used"]
    assert isinstance(attempt["prefilter_applied"], bool)


def test_hargpt_paper_prefilter_applies_on_large_input() -> None:
    from flashfusion.baselines import hargpt_paper

    query = "What activity is user 1600 doing based on these IMU readings?"
    r = _result("HARGPT_PAPER", query)
    large_df = pd.DataFrame(
        {
            "subject_id": [1600] * 30000,
            "activity_label": ["A"] * 30000,
            "timestamp": list(range(30000)),
            "x": [0.1] * 30000,
            "y": [0.2] * 30000,
            "z": [0.3] * 30000,
            "magnitude": [0.374] * 30000,
            "activity_name": ["Walking"] * 30000,
        }
    )

    with patch.object(
        hargpt_paper,
        "_invoke_rewritten",
        return_value="Final answer: Walking",
    ):
        out = hargpt_paper.run_hargpt_paper(query, large_df, _client(), r)

    attempt = out.execution_attempts[-1]
    assert attempt["prefilter_applied"] is True
    assert attempt["rows_used"] < len(large_df)
    assert attempt["prefilter_rows"] < len(large_df)
