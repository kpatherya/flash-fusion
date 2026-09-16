# flashfusion/pipeline/operators.py
"""
Closed, typed operator vocabulary for Flash-Fusion's default execution path.

Design contract
---------------
1. Every operator is a distinct Pydantic model with ``extra="forbid"``. The
   operators are joined into a discriminated union on the ``op`` field, so a
   malformed or unknown operator fails *structurally* — before any data is
   touched — instead of being silently coerced.
2. A plan passes **two gates** before execution:
     a. structural — ``DeterministicPlan.model_validate(...)`` (Pydantic)
     b. schema     — ``validate_plan_against_dataframe(plan, df)``
   Both are pure Python and cost microseconds relative to an LLM call, so
   neither is ever skipped for latency reasons. The guardrail answers "is this
   question answerable in principle"; schema validation answers "did this
   specific generated plan reference real columns correctly". They reason over
   different artifacts and are not redundant.
3. Execution dispatches with ``match`` over the union. There is no
   ``op.upper().strip()`` string dispatch and no ``**kwargs`` passthrough
   anywhere in this module.
4. The vocabulary is **closed**. When a query needs an operator that does not
   exist, ``log_operator_gap()`` records the gap and the caller falls back to
   ReAct for that query. New operators are designed, tested, and versioned
   offline — never invented inside a live request.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

__all__ = [
    "PLAN_VERSION",
    "OPERATOR_VOCABULARY_VERSION",
    "OPERATOR_VOCABULARY_SPEC",
    "ALL_OPERATOR_NAMES",
    "build_vocabulary_spec",
    "build_planner_prefix",
    "planner_prefix_digest",
    "planner_prefix_version",
    "FLASH_FUSION_PLANNER_PREFIX",
    "PLANNER_PREFIX_SHA256",
    "PLANNER_PREFIX_VERSION",
    "planner_cache_key",
    "Aggregate",
    "Comparator",
    "DeterministicPlan",
    "TypedPlan",
    "GuardrailAndPlan",
    "PlanExecution",
    "PlanSchemaError",
    "PlanExecutionError",
    "StructuralValidationError",
    "TypedOperator",
    "structural_validate",
    "parse_guardrail_and_plan",
    "parse_guardrail_response",
    "ParsedGuardrail",
    "NORMALIZATION_VERSION",
    "normalize_raw_plan",
    "normalize_guardrail_payload",
    "validate_plan_against_dataframe",
    "execute_plan",
    "log_operator_gap",
]

PLAN_VERSION = "1"

#: Bumped whenever OPERATOR_VOCABULARY_SPEC or the planner contract text changes.
#: "4" — PARALLEL_AGGREGATE branches now preserve common prefix filters and
#: only zero-fill missing additive aggregates (count and sum).
OPERATOR_VOCABULARY_VERSION = "4"

# ---------------------------------------------------------------------------
# Scalar vocabularies
# ---------------------------------------------------------------------------

Aggregate = Literal[
    "min", "max", "mean", "median", "sum", "count", "std", "var", "nunique", "rms"
]
Comparator = Literal["eq", "ne", "gt", "gte", "lt", "lte"]
Direction = Literal["max", "min"]
BinaryOperation = Literal["add", "subtract", "multiply", "divide", "abs_difference"]
ThresholdStat = Literal["median", "mean", "min", "max"]
CompareMode = Literal["difference", "abs_difference", "ratio"]
CorrelationMethod = Literal["pearson", "spearman", "kendall"]
BinKind = Literal["numeric", "temporal"]
EpochUnit = Literal["s", "ms", "us", "ns"]
PredictiveModel = Literal[
    "logistic_regression",
    "random_forest",
    "one_nearest_neighbor",
    "hist_gradient_boosting",
]
Scalar = Union[str, int, float, bool]

# Aggregates that are only meaningful on a numeric column.
_NUMERIC_ONLY_AGGREGATES: frozenset[str] = frozenset(
    {"mean", "median", "sum", "std", "var", "rms"}
)


# ---------------------------------------------------------------------------
# Operator models
# ---------------------------------------------------------------------------


class _Operator(BaseModel):
    """Base contract shared by every deterministic operator."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FilterCompare(_Operator):
    """Row filter: keep rows where ``column <comparator> value``."""

    op: Literal["FILTER_COMPARE"]
    column: str = Field(min_length=1)
    comparator: Comparator
    value: Scalar


class FilterIn(_Operator):
    """Row filter: keep rows where ``column`` is one of ``values``."""

    op: Literal["FILTER_IN"]
    column: str = Field(min_length=1)
    values: list[Scalar] = Field(min_length=1)


class FilterNotEmpty(_Operator):
    """Row filter: keep rows where ``column`` is non-null and non-blank."""

    op: Literal["FILTER_NOT_EMPTY"]
    column: str = Field(min_length=1)


class FilterEqAggregate(_Operator):
    """Row filter: keep rows where ``column`` equals an aggregate of itself.

    Covers "return every row where X reaches its maximum" without a two-pass
    plan or a placeholder referencing a prior observation.
    """

    op: Literal["FILTER_EQ_AGGREGATE"]
    column: str = Field(min_length=1)
    aggregate: Aggregate


class AggregateColumn(_Operator):
    """Reduce one column of the current frame to a scalar."""

    op: Literal["AGGREGATE_COLUMN"]
    column: str = Field(min_length=1)
    aggregate: Aggregate


class CountRows(_Operator):
    """Count rows remaining in the current frame."""

    op: Literal["COUNT_ROWS"]


class CountDistinct(_Operator):
    """Count distinct non-null values of a column in the current frame."""

    op: Literal["COUNT_DISTINCT"]
    column: str = Field(min_length=1)


class SelectColumn(_Operator):
    """Return the values of a column as a list."""

    op: Literal["SELECT_COLUMN"]
    column: str = Field(min_length=1)
    distinct: bool = False


class DeriveBinary(_Operator):
    """Row-wise arithmetic between two columns into a new named column."""

    op: Literal["DERIVE_BINARY"]
    left: str = Field(min_length=1)
    right: str = Field(min_length=1)
    operation: BinaryOperation
    result: str = Field(min_length=1)


class DeriveVectorMagnitude(_Operator):
    """Row-wise ``sqrt(a^2 + b^2 + c^2)`` — the canonical IoT derived feature."""

    op: Literal["DERIVE_VECTOR_MAGNITUDE"]
    columns: tuple[str, str, str]
    result: str = Field(default="vector_magnitude", min_length=1)


class DeriveBin(_Operator):
    """Bucket a column in either numeric or temporal mode.

    - ``kind="numeric"`` preserves legacy width binning:
      ``floor(col / width) * width``.
    - ``kind="temporal"`` floors timestamps to a pandas frequency via
      ``dt.floor(freq)``. Numeric epoch columns are supported, but require an
      explicit ``epoch_unit`` so no unit guessing occurs.
    """

    op: Literal["DERIVE_BIN"]
    column: str = Field(min_length=1)
    kind: BinKind = "numeric"
    width: float | None = Field(default=None, gt=0.0)
    freq: str | None = None
    epoch_unit: EpochUnit | None = None
    result: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> "DeriveBin":
        if self.kind == "numeric":
            if self.width is None:
                raise ValueError("DERIVE_BIN kind='numeric' requires width.")
            if self.freq is not None:
                raise ValueError("DERIVE_BIN kind='numeric' must not set freq")
            if self.epoch_unit is not None:
                raise ValueError(
                    "DERIVE_BIN kind='numeric' must not set epoch_unit"
                )
            return self

        if self.freq is None or not self.freq.strip():
            raise ValueError("DERIVE_BIN kind='temporal' requires freq")
        if self.width is not None:
            raise ValueError("DERIVE_BIN kind='temporal' must not set width")
        return self


class DeriveDurationSeconds(_Operator):
    """Elapsed seconds between consecutive samples, computed within each group.

    Duration is *never* the sum of a timestamp column — a timestamp is an
    instant, not an interval. This operator materializes the interval first:
    sort by ``group_by + timestamp_column``, take the within-group difference,
    and express it in seconds. Downstream steps then aggregate ``result``
    like any other numeric column.

    ``timestamp_column`` may be datetime-typed or an integer/float epoch
    counter. Both are interpreted at nanosecond resolution (matching pandas'
    ``datetime64[ns]``), so a numeric column must be in nanoseconds.
    """

    op: Literal["DERIVE_DURATION_SECONDS"]
    timestamp_column: str = Field(min_length=1)
    group_by: list[str] = Field(min_length=1)
    result: str = Field(default="dt_s", min_length=1)
    clip_negative: bool = True
    fill_first: float = 0.0


class GroupAggregate(_Operator):
    """Group the current frame by one or more keys and aggregate one column.

    ``freq`` switches to time-bucketed grouping (``pd.Grouper``) and requires a
    single datetime ``group_by`` key. ``column`` may be omitted when
    ``aggregate`` is ``count``, which then yields group sizes.
    """

    op: Literal["GROUP_AGGREGATE"]
    group_by: list[str] = Field(min_length=1)
    aggregate: Aggregate
    column: str | None = None
    freq: str | None = None


class AggregateGroups(_Operator):
    """Reduce the previous GROUP_AGGREGATE result to a scalar."""

    op: Literal["AGGREGATE_GROUPS"]
    aggregate: Aggregate


class RankGroups(_Operator):
    """Return the highest/lowest group from the previous GROUP_AGGREGATE result."""

    op: Literal["RANK_GROUPS"]
    direction: Direction


class RankRows(_Operator):
    """Return the row that maximises/minimises a column, projected to columns."""

    op: Literal["RANK_ROWS"]
    column: str = Field(min_length=1)
    direction: Direction
    return_columns: list[str] = Field(min_length=1)


class SplitByThreshold(_Operator):
    """Name a partition of the ORIGINAL frame split at a statistic of ``column``."""

    op: Literal["SPLIT_BY_THRESHOLD"]
    column: str = Field(min_length=1)
    comparator: Literal["gt", "gte", "lt", "lte"]
    threshold: ThresholdStat = "median"
    label: str = Field(min_length=1)


class SplitByValues(_Operator):
    """Name a partition of the ORIGINAL frame by membership in a value set.

    Partitions are drawn from the original frame, not the possibly-narrowed
    working frame, so two disjoint category groups never collapse to zero rows.
    """

    op: Literal["SPLIT_BY_VALUES"]
    column: str = Field(min_length=1)
    values: list[Scalar] = Field(min_length=1)
    label: str = Field(min_length=1)


class AggregatePartitions(_Operator):
    """Aggregate the same metric across previously named partitions."""

    op: Literal["AGGREGATE_PARTITIONS"]
    partitions: list[str] = Field(min_length=2)
    aggregate: Aggregate
    column: str | None = None


class ComparePartitions(_Operator):
    """Compare the two values produced by AGGREGATE_PARTITIONS."""

    op: Literal["COMPARE_PARTITIONS"]
    mode: CompareMode = "difference"


class CompareValues(_Operator):
    """Compare the two most recent scalar aggregates, from ANY prior source.

    Generalizes COMPARE_PARTITIONS beyond SPLIT_BY_*: the two values being
    compared can come from AGGREGATE_COLUMN or AGGREGATE_GROUPS run in any
    context, including twice in a row after a PARALLEL_AGGREGATE merge (e.g.
    to reduce per-entity branch results down to two comparable scalars).
    Requires exactly two preceding AGGREGATE_COLUMN/AGGREGATE_GROUPS steps
    with no COMPARE_VALUES between them (enforced in schema validation).
    """

    op: Literal["COMPARE_VALUES"]
    mode: CompareMode = "difference"
    label_a: str = Field(default="value_a", min_length=1)
    label_b: str = Field(default="value_b", min_length=1)


class CorrelateColumns(_Operator):
    """Correlation coefficient between two numeric columns of the working frame.

    The only way to answer a "does X correlate with Y" question. Both operands
    must be real numeric columns, so a query about a field this dataset does not
    carry fails schema validation naming that field — which is the honest answer,
    rather than a proxy or an ordinal encoding of an unrelated label.
    """

    op: Literal["CORRELATE_COLUMNS"]
    left: str = Field(min_length=1)
    right: str = Field(min_length=1)
    method: CorrelationMethod = "pearson"


class ParallelAggregateBranch(BaseModel):
    """A single branch of PARALLEL_AGGREGATE: filter → group → aggregate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Filter stage (optional - if None, uses all rows)
    filter_column: str | None = None
    filter_values: list[Scalar] | None = None

    # Group stage
    group_by: list[str] = Field(min_length=1)
    aggregate: Aggregate
    column: str | None = None  # None with aggregate="count" gives group sizes

    # Result naming
    result_column: str = Field(min_length=1)  # name for the aggregated values


class ParallelAggregate(_Operator):
    """Execute multiple independent filter→group→aggregate pipelines, then merge.

    Design rationale:
    - Solves the "compare resting vs. dynamic duration per user" pattern
    - Each branch filters the working frame at operator entry independently
    - All branches must group by the SAME keys (enforced in validation)
    - Results are outer-merged on group keys; only missing counts/sums become 0
    - Working frame becomes the merged result with columns: [group_keys, result1, result2, ...]

    Example ("which entity spent more time in category group A than group B",
    after a DERIVE_DURATION_SECONDS step materialized ``dt_s``):
        {
          "op": "PARALLEL_AGGREGATE",
          "branches": [
            {
              "filter_column": "category_col",
              "filter_values": ["cat_1", "cat_2"],
              "group_by": ["entity_id"],
              "aggregate": "sum",
              "column": "dt_s",
              "result_column": "a_duration"
            },
            {
              "filter_column": "category_col",
              "filter_values": ["cat_3", "cat_4"],
              "group_by": ["entity_id"],
              "aggregate": "sum",
              "column": "dt_s",
              "result_column": "b_duration"
            }
          ]
        }

    Note the aggregated column is the *derived* elapsed-seconds column, never a
    raw timestamp — see ``DeriveDurationSeconds``.
    """

    op: Literal["PARALLEL_AGGREGATE"]
    branches: list[ParallelAggregateBranch] = Field(min_length=2)

    @property
    def shared_group_keys(self) -> list[str]:
        """All branches must group by the same columns."""
        return self.branches[0].group_by


class PredictivePipeline(_Operator):
    """Deterministic chronological train/holdout classification.

    ``feature_columns`` is explicit and required: trained models must be
    reproducible and auditable across runs, so "all remaining numeric columns"
    is not an acceptable specification.
    """

    op: Literal["PREDICTIVE_PIPELINE"]
    model: PredictiveModel
    feature_columns: list[str] = Field(min_length=1)
    target_column: str = Field(min_length=1)
    sort_by: list[str] = Field(min_length=1)
    train_fraction: float = Field(default=0.8, gt=0.0, lt=1.0)
    holdout_row: Literal["first", "last"] = "first"
    filter_column: str | None = None
    filter_value: Scalar | None = None
    target_from_non_empty: bool = False
    target_label: str = Field(default="label", min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _default_blank_target_label(cls, data: Any) -> Any:
        """Planner sometimes emits target_label="" instead of omitting it;
        treat that the same as omitted rather than failing Gate 1."""
        if isinstance(data, dict) and not data.get("target_label"):
            data.pop("target_label", None)
        return data


TypedOperator = Annotated[
    Union[
        FilterCompare,
        FilterIn,
        FilterNotEmpty,
        FilterEqAggregate,
        AggregateColumn,
        CountRows,
        CountDistinct,
        SelectColumn,
        DeriveBinary,
        DeriveVectorMagnitude,
        DeriveBin,
        DeriveDurationSeconds,
        GroupAggregate,
        AggregateGroups,
        RankGroups,
        RankRows,
        SplitByThreshold,
        SplitByValues,
        AggregatePartitions,
        ComparePartitions,
        CompareValues,
        CorrelateColumns,
        ParallelAggregate,
        PredictivePipeline,
    ],
    Field(discriminator="op"),
]

#: Declaration-ordered inventory of the closed vocabulary. Derived from the union
#: itself so it can never drift from the operators that actually validate.
ALL_OPERATOR_NAMES: tuple[str, ...] = tuple(
    get_args(model.model_fields["op"].annotation)[0]
    for model in get_args(get_args(TypedOperator)[0])
)

_ALL_OPERATOR_NAME_SET: frozenset[str] = frozenset(ALL_OPERATOR_NAMES)


class DeterministicPlan(BaseModel):
    """A fully typed, pre-validatable Flash-Fusion execution plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["1"] = PLAN_VERSION
    steps: list[TypedOperator] = Field(min_length=1)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeterministicPlan":
        return cls.model_validate(data)

    @property
    def operators_used(self) -> list[str]:
        return [step.op for step in self.steps]

    @property
    def kind(self) -> str:
        return self.steps[-1].op.lower()


#: Alias used by flashfusion/scripts/run_typed_operators.py.
TypedPlan = DeterministicPlan


class GuardrailAndPlan(BaseModel):
    """Single-round-trip guardrail verdict + candidate plan.

    ``extra="ignore"`` applies to this wrapper only — the plan and every
    operator inside it still forbid unknown fields, so nothing untyped can
    reach execution.
    """

    model_config = ConfigDict(extra="ignore")

    in_scope: bool
    rejection_reason: str | None = None
    ambiguous_concepts: list[str] = Field(default_factory=list)
    plan: DeterministicPlan | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PlanSchemaError(ValueError):
    """Raised when a structurally valid plan does not fit the DataFrame schema.

    ``missing_columns`` distinguishes "this dataset has no such field" from every
    other schema failure. A missing field is a scope verdict, not a planning bug,
    so the caller rejects terminally instead of falling back to a free-form agent
    that would be tempted to synthesize the values.
    """

    def __init__(self, message: str, missing_columns: set[str] | None = None) -> None:
        super().__init__(message)
        self.missing_columns: set[str] = set(missing_columns or ())


class PlanExecutionError(RuntimeError):
    """Raised when a validated plan fails at execution time."""


#: Re-exported so callers can catch structural failures without importing pydantic.
StructuralValidationError = ValidationError


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------


@dataclass
class PlanExecution:
    """Outcome of running one DeterministicPlan against a DataFrame."""

    value: Any = None
    ok: bool = False
    error: str | None = None
    plan_kind: str = ""
    rows_scanned: int = 0
    rows_after_filter: int | None = None
    columns_used: list[str] = field(default_factory=list)
    operators_used: list[str] = field(default_factory=list)
    code: str = ""
    trace: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Value coercion + shared helpers
# ---------------------------------------------------------------------------


def _coerce_value(series: pd.Series, value: Any) -> Any:
    """Coerce a JSON scalar into something comparable with ``series``' dtype."""
    if isinstance(value, str):
        value = value.strip()

    if pd.api.types.is_datetime64_any_dtype(series):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return pd.Timestamp(value)
        parsed = pd.to_datetime(value, errors="coerce")
        if parsed is pd.NaT:
            raise PlanSchemaError(f"Cannot compare datetime column against {value!r}")
        return parsed

    if pd.api.types.is_bool_dtype(series):
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)

    if pd.api.types.is_numeric_dtype(series):
        if isinstance(value, (bool, int, float)):
            return value
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise PlanSchemaError(
                f"Cannot compare numeric column against {value!r}"
            ) from exc
        return int(numeric) if numeric.is_integer() else numeric

    return str(value)


def _compare(series: pd.Series, comparator: str, value: Any) -> pd.Series:
    match comparator:
        case "eq":
            return series == value
        case "ne":
            return series != value
        case "gt":
            return series > value
        case "gte":
            return series >= value
        case "lt":
            return series < value
        case "lte":
            return series <= value
    raise PlanExecutionError(f"Unsupported comparator: {comparator!r}")


def _comparator_symbol(comparator: str) -> str:
    match comparator:
        case "eq":
            return "=="
        case "ne":
            return "!="
        case "gt":
            return ">"
        case "gte":
            return ">="
        case "lt":
            return "<"
        case "lte":
            return "<="
    raise PlanExecutionError(f"Unsupported comparator: {comparator!r}")


def _aggregate_series(series: pd.Series, aggregate: str) -> Any:
    match aggregate:
        case "rms":
            values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
            if values.size == 0:
                raise PlanExecutionError("RMS requires at least one numeric value")
            return float(np.sqrt(np.mean(np.square(values))))
        case "nunique":
            return int(series.nunique())
        case "count":
            return int(series.count())
        case _:
            return getattr(series, aggregate)()


def _to_python(value: Any) -> Any:
    """Normalize numpy/pandas scalars so results serialize cleanly."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _bin_series(series: pd.Series, step: "DeriveBin") -> pd.Series:
    """Bucket a series using DERIVE_BIN's explicit numeric/temporal modes."""
    if step.kind == "numeric":
        if step.width is None:
                raise PlanExecutionError("DERIVE_BIN numeric mode requires width.")
        return (series // step.width) * step.width

    if step.freq is None:
        raise PlanExecutionError("DERIVE_BIN temporal mode requires freq")

    if pd.api.types.is_datetime64_any_dtype(series):
        if step.epoch_unit is not None:
            raise PlanExecutionError(
                "DERIVE_BIN temporal mode with datetime source must not set epoch_unit"
            )
        return pd.to_datetime(series, errors="coerce").dt.floor(step.freq)

    if not pd.api.types.is_numeric_dtype(series):
        raise PlanExecutionError(
            "DERIVE_BIN temporal mode requires a datetime or numeric epoch column"
        )

    if step.epoch_unit is None:
        raise PlanExecutionError(
            "DERIVE_BIN temporal mode with numeric source requires epoch_unit"
        )
    return pd.to_datetime(series, unit=step.epoch_unit, errors="coerce").dt.floor(
        step.freq
    )


#: Nanoseconds per second — the resolution both datetime64[ns] and integer
#: epoch timestamp columns are interpreted at by DERIVE_DURATION_SECONDS.
_NANOS_PER_SECOND = 1_000_000_000


def _duration_seconds(frame: pd.DataFrame, step: "DeriveDurationSeconds") -> pd.Series:
    """Within-group elapsed seconds between consecutive rows of ``frame``.

    The result is aligned back to ``frame``'s own index, so the caller can
    assign it as a column regardless of the sort order used internally.
    """
    ordered = frame.sort_values([*step.group_by, step.timestamp_column])
    series = ordered[step.timestamp_column]
    if pd.api.types.is_datetime64_any_dtype(series):
        nanos = series.astype("int64")
    else:
        nanos = pd.to_numeric(series, errors="coerce")

    deltas = nanos.groupby(
        [ordered[key] for key in step.group_by], dropna=False, sort=False
    ).diff()
    deltas = deltas / _NANOS_PER_SECOND
    if step.clip_negative:
        deltas = deltas.clip(lower=0.0)
    # The first row of each group has no predecessor, so diff() left it NaN.
    deltas = deltas.fillna(float(step.fill_first))
    return deltas.reindex(frame.index)


# ---------------------------------------------------------------------------
# Gate 2 — DataFrame schema validation
# ---------------------------------------------------------------------------

#: Aggregates that are well-defined on zero rows. Everything else yields NaN
#: on an empty frame, which would silently pass a wrong answer downstream.
_EMPTY_SAFE_AGGREGATES: frozenset[str] = frozenset({"count", "nunique"})


def _require_non_empty(frame: pd.DataFrame, op: str, aggregate: str | None = None) -> None:
    """Fail loudly rather than let an aggregate over zero rows return NaN."""
    if aggregate is not None and aggregate in _EMPTY_SAFE_AGGREGATES:
        return
    if len(frame) == 0:
        suffix = f" ({aggregate})" if aggregate else ""
        raise PlanExecutionError(
            f"{op}{suffix} received an empty frame — every preceding filter or "
            "split removed all rows, so the aggregate would be undefined"
        )


def _require_column(column: str, available: set[str], op: str) -> None:
    if column not in available:
        raise PlanSchemaError(
            f"{op} references unknown column {column!r}", missing_columns={column}
        )


def _require_numeric(column: str, df: pd.DataFrame, op: str) -> None:
    if column in df.columns and not pd.api.types.is_numeric_dtype(df[column]):
        raise PlanSchemaError(
            f"{op} requires a numeric column; {column!r} has dtype {df[column].dtype}"
        )


def _require_numeric_or_datetime(column: str, df: pd.DataFrame, op: str) -> None:
    if column not in df.columns:
        return
    dtype = df[column].dtype
    if not (
        pd.api.types.is_numeric_dtype(dtype)
        or pd.api.types.is_datetime64_any_dtype(dtype)
    ):
        raise PlanSchemaError(
            f"{op} requires a numeric or datetime column; {column!r} has dtype {dtype}"
        )


def _validate_aggregate(
    column: str | None,
    aggregate: str,
    df: pd.DataFrame,
    available: set[str],
    op: str,
) -> None:
    if column is None:
        if aggregate != "count":
            raise PlanSchemaError(f"{op} requires a column for aggregate {aggregate!r}")
        return
    _require_column(column, available, op)
    if (
        aggregate == "sum"
        and column in df.columns
        and pd.api.types.is_datetime64_any_dtype(df[column])
    ):
        # Summing instants is meaningless — the intent is always elapsed time.
        raise PlanSchemaError(
            f"{op} cannot sum the datetime column {column!r}: a timestamp is an "
            "instant, not a duration. Derive elapsed time first with "
            "DERIVE_DURATION_SECONDS and aggregate that result column instead"
        )
    if aggregate in _NUMERIC_ONLY_AGGREGATES:
        _require_numeric(column, df, op)


def validate_plan_against_dataframe(plan: DeterministicPlan, df: pd.DataFrame) -> None:
    """Gate 2: check a structurally valid plan against this DataFrame's schema.

    Raises:
        PlanSchemaError: unknown column, incompatible dtype, undefined partition,
            or a step that depends on a prior step the plan never emits.
    """
    available: set[str] = {str(c) for c in df.columns}
    partitions: set[str] = set()
    has_group_result = False
    has_partition_aggregate = False
    # Count of AGGREGATE_COLUMN/AGGREGATE_GROUPS steps since the last COMPARE_VALUES
    # (or since the start of the plan) — COMPARE_VALUES requires exactly two.
    pending_scalar_count = 0
    # Grouping keys of the most recent PARALLEL_AGGREGATE, or None if the working
    # frame is not a parallel-aggregate merge. A RANK_ROWS over such a frame must
    # return at least one of these keys, otherwise it identifies no entity.
    parallel_group_keys: list[str] | None = None
    rank_groups_seen = False

    for step in plan.steps:
        if rank_groups_seen:
            raise PlanSchemaError(
                "RANK_GROUPS must be the final step; later steps can overwrite "
                "its ranked result"
            )
        match step:
            case FilterCompare():
                _require_column(step.column, available, step.op)
                if step.column in df.columns:
                    _coerce_value(df[step.column], step.value)

            case FilterIn() | FilterNotEmpty() | CountDistinct() | SelectColumn():
                _require_column(step.column, available, step.op)

            case FilterEqAggregate():
                _validate_aggregate(step.column, step.aggregate, df, available, step.op)

            case AggregateColumn():
                _validate_aggregate(step.column, step.aggregate, df, available, step.op)
                pending_scalar_count += 1

            case CountRows():
                pass

            case DeriveBinary():
                _require_column(step.left, available, step.op)
                _require_column(step.right, available, step.op)
                _require_numeric(step.left, df, step.op)
                _require_numeric(step.right, df, step.op)
                available.add(step.result)

            case DeriveVectorMagnitude():
                for column in step.columns:
                    _require_column(column, available, step.op)
                    _require_numeric(column, df, step.op)
                available.add(step.result)

            case DeriveBin():
                _require_column(step.column, available, step.op)
                if step.kind == "numeric":
                    _require_numeric(step.column, df, step.op)
                else:
                    _require_numeric_or_datetime(step.column, df, step.op)
                    if step.column in df.columns:
                        is_numeric = pd.api.types.is_numeric_dtype(df[step.column])
                        is_datetime = pd.api.types.is_datetime64_any_dtype(df[step.column])
                        if is_numeric and step.epoch_unit is None:
                            raise PlanSchemaError(
                                "DERIVE_BIN kind='temporal' with numeric timestamp "
                                "requires epoch_unit (s|ms|us|ns)"
                            )
                        if is_datetime and step.epoch_unit is not None:
                            raise PlanSchemaError(
                                "DERIVE_BIN kind='temporal' with datetime source must "
                                "not set epoch_unit"
                            )
                available.add(step.result)

            case DeriveDurationSeconds():
                _require_column(step.timestamp_column, available, step.op)
                _require_numeric_or_datetime(step.timestamp_column, df, step.op)
                for key in step.group_by:
                    _require_column(key, available, step.op)
                available.add(step.result)

            case GroupAggregate():
                for key in step.group_by:
                    _require_column(key, available, step.op)
                _validate_aggregate(step.column, step.aggregate, df, available, step.op)
                if step.freq is not None:
                    if len(step.group_by) != 1:
                        raise PlanSchemaError(
                            "GROUP_AGGREGATE with freq requires exactly one group key"
                        )
                    key = step.group_by[0]
                    if key in df.columns and not pd.api.types.is_datetime64_any_dtype(
                        df[key]
                    ):
                        raise PlanSchemaError(
                            f"GROUP_AGGREGATE freq={step.freq!r} requires a datetime "
                            f"column; {key!r} has dtype {df[key].dtype}"
                        )
                has_group_result = True

            case AggregateGroups():
                if not has_group_result:
                    raise PlanSchemaError(
                        "AGGREGATE_GROUPS requires a preceding GROUP_AGGREGATE step"
                    )
                pending_scalar_count += 1

            case RankGroups():
                if not has_group_result:
                    raise PlanSchemaError(
                        "RANK_GROUPS requires a preceding GROUP_AGGREGATE step"
                    )
                rank_groups_seen = True

            case RankRows():
                _require_column(step.column, available, step.op)
                _require_numeric(step.column, df, step.op)
                for column in step.return_columns:
                    _require_column(column, available, step.op)
                if parallel_group_keys is not None and not (
                    set(step.return_columns) & set(parallel_group_keys)
                ):
                    # Without a grouping key the ranked row is a bare number —
                    # it names no entity, so it cannot answer "which X".
                    raise PlanSchemaError(
                        "RANK_ROWS after PARALLEL_AGGREGATE must return at least one "
                        f"of the grouping keys {parallel_group_keys!r} in "
                        f"return_columns; got {step.return_columns!r}, which "
                        "identifies no entity"
                    )

            case SplitByThreshold():
                _require_column(step.column, available, step.op)
                _require_numeric(step.column, df, step.op)
                partitions.add(step.label)

            case SplitByValues():
                _require_column(step.column, available, step.op)
                partitions.add(step.label)

            case AggregatePartitions():
                missing = [p for p in step.partitions if p not in partitions]
                if missing:
                    raise PlanSchemaError(
                        f"AGGREGATE_PARTITIONS references undefined partition(s): {missing}"
                    )
                _validate_aggregate(step.column, step.aggregate, df, available, step.op)
                has_partition_aggregate = True

            case ComparePartitions():
                if not has_partition_aggregate:
                    raise PlanSchemaError(
                        "COMPARE_PARTITIONS requires a preceding AGGREGATE_PARTITIONS step"
                    )

            case CompareValues():
                if pending_scalar_count != 2:
                    raise PlanSchemaError(
                        "COMPARE_VALUES requires exactly two preceding AGGREGATE_COLUMN or "
                        "AGGREGATE_GROUPS steps (with no COMPARE_VALUES between them); "
                        f"found {pending_scalar_count}"
                    )
                pending_scalar_count = 0

            case CorrelateColumns():
                for column in (step.left, step.right):
                    _require_column(column, available, step.op)
                    _require_numeric(column, df, step.op)
                if step.left == step.right:
                    raise PlanSchemaError(
                        f"CORRELATE_COLUMNS: {step.left!r} correlated with itself is "
                        "always 1.0 and answers nothing"
                    )

            case ParallelAggregate():
                # All branches must use the same group_by keys
                reference_keys = step.branches[0].group_by
                for i, branch in enumerate(step.branches):
                    if branch.group_by != reference_keys:
                        raise PlanSchemaError(
                            f"PARALLEL_AGGREGATE: branch {i} has group_by={branch.group_by!r}, "
                            f"expected {reference_keys!r} (all branches must group by same keys)"
                        )

                    # Validate filter column if present
                    if branch.filter_column is not None:
                        _require_column(branch.filter_column, available, "PARALLEL_AGGREGATE")

                    # Validate group keys
                    for key in branch.group_by:
                        _require_column(key, available, "PARALLEL_AGGREGATE")

                    # Validate aggregation
                    _validate_aggregate(
                        branch.column,
                        branch.aggregate,
                        df,
                        available,
                        "PARALLEL_AGGREGATE"
                    )

                # After PARALLEL_AGGREGATE, working frame only has group keys + result columns
                available = {*reference_keys, *(b.result_column for b in step.branches)}
                parallel_group_keys = list(reference_keys)

            case PredictivePipeline():
                for column in step.feature_columns:
                    _require_column(column, available, step.op)
                    _require_numeric(column, df, step.op)
                for column in step.sort_by:
                    _require_column(column, available, step.op)
                if step.filter_column is not None:
                    _require_column(step.filter_column, available, step.op)
                    if step.filter_value is None:
                        raise PlanSchemaError(
                            "PREDICTIVE_PIPELINE filter_column requires filter_value"
                        )
                _require_column(step.target_column, available, step.op)
                if step.target_column in step.feature_columns:
                    raise PlanSchemaError(
                        "PREDICTIVE_PIPELINE target_column must not also be a feature"
                    )


# ---------------------------------------------------------------------------
# Predictive model factory (mirrors eval/build_groundtruth/simple_pred.py)
# ---------------------------------------------------------------------------

PREDICTIVE_RANDOM_SEED = 42

_PREDICTIVE_MODEL_DISPLAY: dict[str, str] = {
    "logistic_regression": "Logistic regression",
    "random_forest": "Random forest",
    "one_nearest_neighbor": "1-nearest-neighbor",
    "hist_gradient_boosting": "Hist gradient boosting",
}


def _build_predictive_model(model: str):
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    match model:
        case "logistic_regression":
            return make_pipeline(
                StandardScaler(),
                LogisticRegression(random_state=PREDICTIVE_RANDOM_SEED, max_iter=2000),
            )
        case "random_forest":
            return RandomForestClassifier(
                n_estimators=150,
                max_depth=20,
                random_state=PREDICTIVE_RANDOM_SEED,
                n_jobs=-1,
            )
        case "hist_gradient_boosting":
            return HistGradientBoostingClassifier(
                max_iter=120,
                learning_rate=0.08,
                max_leaf_nodes=31,
                l2_regularization=1.0,
                random_state=PREDICTIVE_RANDOM_SEED,
            )
        case "one_nearest_neighbor":
            return make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=1))
    raise PlanExecutionError(f"Unsupported predictive model {model!r}")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@dataclass
class _State:
    original: pd.DataFrame
    working: pd.DataFrame
    observations: list[Any] = field(default_factory=list)
    partitions: dict[str, pd.DataFrame] = field(default_factory=dict)
    group_result: pd.Series | None = None
    group_keys: list[str] = field(default_factory=list)
    group_label: str = "group"
    group_metric: str = "value"
    group_aggregate: str = "mean"
    partition_result: dict[str, Any] = field(default_factory=dict)
    partition_metric: str = "value"
    columns_used: set[str] = field(default_factory=set)
    # (label, value) pairs from AGGREGATE_COLUMN/AGGREGATE_GROUPS, consumed by COMPARE_VALUES.
    scalar_trail: list[tuple[str, Any]] = field(default_factory=list)

    def use(self, *columns: str) -> None:
        self.columns_used.update(c for c in columns if c)


def _run_predictive(step: PredictivePipeline, state: _State) -> tuple[Any, str]:
    # Predictive execution must honor prior typed filters in the working frame.
    frame = state.working
    state.use(*step.feature_columns, *step.sort_by, step.target_column)

    if step.filter_column is not None:
        state.use(step.filter_column)
        value = _coerce_value(frame[step.filter_column], step.filter_value)
        frame = frame[frame[step.filter_column] == value]
        if frame.empty:
            raise PlanExecutionError(
                f"Predictive filter produced no rows: "
                f"{step.filter_column}=={step.filter_value!r}"
            )

    frame = frame.sort_values(list(step.sort_by)).reset_index(drop=True)

    if step.target_from_non_empty:
        target = (
            frame[step.target_column].astype(str).str.strip().ne("").astype(int).to_numpy()
        )
    else:
        target = frame[step.target_column].astype(str).to_numpy()

    features = frame[list(step.feature_columns)].to_numpy(dtype=float)

    n_rows = len(frame)
    split = max(1, min(int(math.floor(n_rows * step.train_fraction)), n_rows - 1))
    if split >= n_rows:
        raise PlanExecutionError("Predictive split leaves no holdout rows")

    x_train, y_train = features[:split], target[:split]
    holdout_index = split if step.holdout_row == "first" else n_rows - 1
    x_test = features[holdout_index].reshape(1, -1)

    train_classes = pd.unique(y_train)
    if len(train_classes) == 1:
        prediction = train_classes[0]
    else:
        model = _build_predictive_model(step.model)
        model.fit(x_train, y_train)
        prediction = model.predict(x_test)[0]

    display = _PREDICTIVE_MODEL_DISPLAY.get(step.model, step.model)
    answer = (
        f"{display} predicts {step.target_label} "
        f"'{_to_python(prediction)}' for the {step.holdout_row} holdout row."
    )
    code = (
        f"# sort_by={list(step.sort_by)!r} split={split}/{n_rows} "
        f"model={step.model!r} features={list(step.feature_columns)!r}\n"
        f"result = {answer!r}"
    )
    return answer, code


def _execute_step(step: TypedOperator, state: _State) -> tuple[Any, str]:
    """Run one typed operator. Returns ``(observation, equivalent_code)``."""
    match step:
        case FilterCompare():
            state.use(step.column)
            value = _coerce_value(state.working[step.column], step.value)
            state.working = state.working[
                _compare(state.working[step.column], step.comparator, value)
            ]
            symbol = _comparator_symbol(step.comparator)
            return (
                f"rows={len(state.working)}",
                f"df = df[df[{step.column!r}] {symbol} {value!r}]",
            )

        case FilterIn():
            state.use(step.column)
            values = [_coerce_value(state.working[step.column], v) for v in step.values]
            state.working = state.working[state.working[step.column].isin(values)]
            return (
                f"rows={len(state.working)}",
                f"df = df[df[{step.column!r}].isin({values!r})]",
            )

        case FilterNotEmpty():
            state.use(step.column)
            series = state.working[step.column]
            mask = series.notna()
            if not pd.api.types.is_numeric_dtype(series):
                mask &= series.astype(str).str.strip().ne("")
            state.working = state.working[mask]
            return (
                f"rows={len(state.working)}",
                f"df = df[df[{step.column!r}].notna() & df[{step.column!r}].astype(str).str.strip().ne('')]",
            )

        case FilterEqAggregate():
            state.use(step.column)
            _require_non_empty(state.working, step.op, step.aggregate)
            target = _aggregate_series(state.working[step.column], step.aggregate)
            state.working = state.working[state.working[step.column] == target]
            return (
                f"rows={len(state.working)} ({step.column}=={_to_python(target)})",
                f"_v = df[{step.column!r}].{step.aggregate}(); "
                f"df = df[df[{step.column!r}] == _v]",
            )

        case AggregateColumn():
            state.use(step.column)
            _require_non_empty(state.working, step.op, step.aggregate)
            value = _to_python(
                _aggregate_series(state.working[step.column], step.aggregate)
            )
            state.observations.append(value)
            state.scalar_trail.append((f"{step.column} {step.aggregate}", value))
            return value, f"result = df[{step.column!r}].{step.aggregate}()"

        case CountRows():
            value = int(len(state.working))
            state.observations.append(value)
            return value, "result = len(df)"

        case CountDistinct():
            state.use(step.column)
            value = int(state.working[step.column].nunique())
            state.observations.append(value)
            return value, f"result = df[{step.column!r}].nunique()"

        case SelectColumn():
            state.use(step.column)
            series = state.working[step.column]
            if step.distinct:
                series = series.drop_duplicates()
            value = [_to_python(v) for v in series.tolist()]
            state.observations.append(value)
            return value, f"result = df[{step.column!r}].tolist()"

        case DeriveBinary():
            state.use(step.left, step.right)
            left = state.working[step.left]
            right = state.working[step.right]
            code_expr = ""
            match step.operation:
                case "add":
                    derived, symbol = left + right, "+"
                    code_expr = f"df[{step.left!r}] + df[{step.right!r}]"
                case "subtract":
                    derived, symbol = left - right, "-"
                    code_expr = f"df[{step.left!r}] - df[{step.right!r}]"
                case "multiply":
                    derived, symbol = left * right, "*"
                    code_expr = f"df[{step.left!r}] * df[{step.right!r}]"
                case "divide":
                    derived, symbol = left / right, "/"
                    code_expr = f"df[{step.left!r}] / df[{step.right!r}]"
                case "abs_difference":
                    derived, symbol = (left - right).abs(), "- (abs)"
                    code_expr = (
                        f"(df[{step.left!r}] - df[{step.right!r}]).abs()"
                    )
            # Apply to both working and original so partitions can access derived columns
            state.working = state.working.assign(**{step.result: derived})
            # Only update original if source columns exist there (they may have been created by PARALLEL_AGGREGATE)
            if step.left in state.original.columns and step.right in state.original.columns:
                left_orig = state.original[step.left]
                right_orig = state.original[step.right]
                match step.operation:
                    case "add":
                        derived_orig = left_orig + right_orig
                    case "subtract":
                        derived_orig = left_orig - right_orig
                    case "multiply":
                        derived_orig = left_orig * right_orig
                    case "divide":
                        derived_orig = left_orig / right_orig
                    case "abs_difference":
                        derived_orig = (left_orig - right_orig).abs()
                state.original = state.original.assign(**{step.result: derived_orig})
            state.use(step.result)
            return (
                f"derived {step.result!r} (rows={len(state.working)})",
                f"df[{step.result!r}] = {code_expr}",
            )

        case DeriveVectorMagnitude():
            a, b, c = step.columns
            state.use(a, b, c)
            derived = (
                state.working[a].pow(2)
                + state.working[b].pow(2)
                + state.working[c].pow(2)
            ).pow(0.5)
            # Apply to both working and original so partitions can access derived columns
            state.working = state.working.assign(**{step.result: derived})
            # Only update original if source columns exist there (they may have been created by PARALLEL_AGGREGATE)
            if all(col in state.original.columns for col in [a, b, c]):
                derived_orig = (
                    state.original[a].pow(2)
                    + state.original[b].pow(2)
                    + state.original[c].pow(2)
                ).pow(0.5)
                state.original = state.original.assign(**{step.result: derived_orig})
            state.use(step.result)
            return (
                f"derived {step.result!r} (rows={len(state.working)})",
                f"df[{step.result!r}] = (df[{a!r}]**2 + df[{b!r}]**2 + df[{c!r}]**2)**0.5",
            )

        case DeriveBin():
            state.use(step.column)
            source = state.working[step.column]
            derived = _bin_series(source, step)
            # Apply to both working and original so partitions can access derived columns
            state.working = state.working.assign(**{step.result: derived})
            # Only update original if source column exists there (it may have been created by PARALLEL_AGGREGATE)
            if step.column in state.original.columns:
                derived_orig = _bin_series(state.original[step.column], step)
                state.original = state.original.assign(**{step.result: derived_orig})
            state.use(step.result)
            if step.kind == "numeric":
                if step.width is None:
                    raise PlanExecutionError("DERIVE_BIN numeric mode requires width")
                code = (
                    f"df[{step.result!r}] = (df[{step.column!r}] // {step.width}) * "
                    f"{step.width}"
                )
                summary = f"derived {step.result!r} (kind=numeric width={step.width})"
            elif pd.api.types.is_datetime64_any_dtype(source):
                code = (
                    f"df[{step.result!r}] = pd.to_datetime(df[{step.column!r}], "
                    f"errors='coerce').dt.floor({step.freq!r})"
                )
                summary = (
                    f"derived {step.result!r} (kind=temporal freq={step.freq!r} "
                    "source=datetime)"
                )
            else:
                code = (
                    f"df[{step.result!r}] = pd.to_datetime(df[{step.column!r}], "
                    f"unit={step.epoch_unit!r}, errors='coerce').dt.floor({step.freq!r})"
                )
                summary = (
                    f"derived {step.result!r} (kind=temporal freq={step.freq!r} "
                    f"epoch_unit={step.epoch_unit!r})"
                )
            return (
                summary,
                code,
            )

        case DeriveDurationSeconds():
            state.use(step.timestamp_column, *step.group_by)
            derived = _duration_seconds(state.working, step)
            state.working = state.working.assign(**{step.result: derived})
            # Mirror into the original frame so SPLIT_BY_* partitions and later
            # PARALLEL_AGGREGATE branches can read the derived column too.
            source_columns = [step.timestamp_column, *step.group_by]
            if all(col in state.original.columns for col in source_columns):
                state.original = state.original.assign(
                    **{step.result: _duration_seconds(state.original, step)}
                )
            state.use(step.result)
            return (
                f"derived {step.result!r} (rows={len(state.working)}, "
                f"total={_to_python(derived.sum())}s)",
                f"df = df.sort_values({[*step.group_by, step.timestamp_column]!r}); "
                f"df[{step.result!r}] = df.groupby({list(step.group_by)!r})"
                f"[{step.timestamp_column!r}].diff().dt.total_seconds()"
                f".clip(lower=0).fillna({step.fill_first!r})",
            )

        case GroupAggregate():
            state.use(*step.group_by, step.column or "")
            _require_non_empty(state.working, step.op, step.aggregate)
            if step.freq is not None:
                grouper = pd.Grouper(key=step.group_by[0], freq=step.freq)
                grouped = state.working.groupby(grouper)
                code_key = f"pd.Grouper(key={step.group_by[0]!r}, freq={step.freq!r})"
            else:
                keys = step.group_by[0] if len(step.group_by) == 1 else list(step.group_by)
                grouped = state.working.groupby(keys, dropna=False)
                code_key = repr(keys)

            if step.column is None:
                series = grouped.size()
                metric = "count"
                code = f"result = df.groupby({code_key}).size()"
            elif step.aggregate == "rms":
                series = grouped[step.column].apply(lambda s: _aggregate_series(s, "rms"))
                metric = step.column
                code = f"result = df.groupby({code_key})[{step.column!r}].apply(rms)"
            else:
                series = grouped[step.column].agg(step.aggregate)
                metric = step.column
                code = (
                    f"result = df.groupby({code_key})[{step.column!r}]"
                    f".{step.aggregate}()"
                )

            state.group_result = series
            state.group_keys = list(step.group_by)
            state.group_label = (
                step.group_by[0] if len(step.group_by) == 1 else "+".join(step.group_by)
            )
            state.group_metric = metric
            state.group_aggregate = step.aggregate
            value = {str(_to_python(k)): _to_python(v) for k, v in series.items()}
            state.observations.append(value)
            return value, code

        case AggregateGroups():
            if state.group_result is None:
                raise PlanExecutionError("AGGREGATE_GROUPS has no grouped result")
            value = _to_python(_aggregate_series(state.group_result, step.aggregate))
            state.observations.append(value)
            state.scalar_trail.append((f"{state.group_metric} {step.aggregate}", value))
            return value, f"result = result.{step.aggregate}()"

        case RankGroups():
            if state.group_result is None or state.group_result.empty:
                raise PlanExecutionError("RANK_GROUPS has no grouped result")
            ranked = state.group_result.dropna()
            if ranked.empty:
                raise PlanExecutionError(
                    "RANK_GROUPS has no non-null grouped values to rank"
                )
            key = (
                ranked.idxmax()
                if step.direction == "max"
                else ranked.idxmin()
            )
            value = {}
            if len(state.group_keys) == 1:
                value[state.group_keys[0]] = _to_python(key)
            elif isinstance(key, tuple) and len(key) == len(state.group_keys):
                for group_key, group_value in zip(state.group_keys, key):
                    value[group_key] = _to_python(group_value)
            else:
                value[state.group_label] = str(_to_python(key))

            metric_key = (
                "count"
                if state.group_metric == "count"
                else f"{state.group_aggregate}_{state.group_metric}"
            )
            value[metric_key] = _to_python(ranked.loc[key])
            state.observations.append(value)
            return value, f"result = result.idx{step.direction}()"

        case RankRows():
            state.use(step.column, *step.return_columns)
            if state.working.empty:
                raise PlanExecutionError("RANK_ROWS received no rows after filtering")
            index = (
                state.working[step.column].idxmax()
                if step.direction == "max"
                else state.working[step.column].idxmin()
            )
            value = {
                column: _to_python(state.working.loc[index, column])
                for column in step.return_columns
            }
            value.setdefault(
                step.column, _to_python(state.working.loc[index, step.column])
            )
            state.observations.append(value)
            return (
                value,
                f"idx = df[{step.column!r}].idx{step.direction}(); "
                f"result = df.loc[idx, {list(step.return_columns)!r}].to_dict()",
            )

        case SplitByThreshold():
            state.use(step.column)
            threshold = getattr(state.original[step.column], step.threshold)()
            subset = state.original[
                _compare(state.original[step.column], step.comparator, threshold)
            ]
            state.partitions[step.label] = subset
            return (
                f"{step.label}: rows={len(subset)} ({step.column} {step.comparator} "
                f"{step.threshold}={_to_python(threshold)})",
                f"{step.label} = df[df[{step.column!r}] {step.comparator} "
                f"df[{step.column!r}].{step.threshold}()]",
            )

        case SplitByValues():
            state.use(step.column)
            values = [_coerce_value(state.original[step.column], v) for v in step.values]
            subset = state.original[state.original[step.column].isin(values)]
            state.partitions[step.label] = subset
            return (
                f"{step.label}: rows={len(subset)}",
                f"{step.label} = df[df[{step.column!r}].isin({values!r})]",
            )

        case AggregatePartitions():
            state.use(step.column or "")
            result: dict[str, Any] = {}
            for label in step.partitions:
                subset = state.partitions.get(label)
                if subset is None:
                    raise PlanExecutionError(f"Unknown partition {label!r}")
                if step.column is None:
                    result[label] = int(len(subset))
                else:
                    _require_non_empty(
                        subset, f"{step.op} partition {label!r}", step.aggregate
                    )
                    result[label] = _to_python(
                        _aggregate_series(subset[step.column], step.aggregate)
                    )
            state.partition_result = result
            state.partition_metric = (
                f"{step.aggregate} {step.column}" if step.column else "row count"
            )
            state.observations.append(result)
            return result, "result = {label: agg(partition) for label in partitions}"

        case ComparePartitions():
            if len(state.partition_result) < 2:
                raise PlanExecutionError(
                    "COMPARE_PARTITIONS requires two aggregated partitions"
                )
            (label_a, value_a), (label_b, value_b) = list(
                state.partition_result.items()
            )[:2]
            match step.mode:
                case "difference":
                    delta: Any = value_a - value_b
                case "abs_difference":
                    delta = abs(value_a - value_b)
                case "ratio":
                    delta = value_a / value_b if value_b else float("nan")
            higher, lower = (
                (label_a, label_b) if value_a >= value_b else (label_b, label_a)
            )
            value = {
                "higher": higher,
                "lower": lower,
                "metric": state.partition_metric,
                label_a: value_a,
                label_b: value_b,
                step.mode: delta,
            }
            state.observations.append(value)
            return value, f"result = compare({label_a}, {label_b}, mode={step.mode!r})"

        case CompareValues():
            if len(state.scalar_trail) < 2:
                raise PlanExecutionError(
                    "COMPARE_VALUES requires two preceding AGGREGATE_COLUMN/"
                    "AGGREGATE_GROUPS steps"
                )
            (metric_a, value_a), (metric_b, value_b) = state.scalar_trail[-2:]
            match step.mode:
                case "difference":
                    delta: Any = value_a - value_b
                case "abs_difference":
                    delta = abs(value_a - value_b)
                case "ratio":
                    delta = value_a / value_b if value_b else float("nan")
            higher, lower = (
                (step.label_a, step.label_b)
                if value_a >= value_b
                else (step.label_b, step.label_a)
            )
            value = {
                "higher": higher,
                "lower": lower,
                step.label_a: value_a,
                step.label_b: value_b,
                f"{step.label_a}_metric": metric_a,
                f"{step.label_b}_metric": metric_b,
                step.mode: delta,
            }
            state.observations.append(value)
            return (
                value,
                f"result = compare({step.label_a}={value_a!r}, "
                f"{step.label_b}={value_b!r}, mode={step.mode!r})",
            )

        case CorrelateColumns():
            state.use(step.left, step.right)
            _require_non_empty(state.working, step.op)
            value = _to_python(
                state.working[step.left].corr(
                    state.working[step.right], method=step.method
                )
            )
            if value is None or (isinstance(value, float) and math.isnan(value)):
                raise PlanExecutionError(
                    f"CORRELATE_COLUMNS: correlation of {step.left!r} and "
                    f"{step.right!r} is undefined (a column has zero variance "
                    "or too few paired observations)"
                )
            state.observations.append(value)
            return (
                value,
                f"result = df[{step.left!r}].corr(df[{step.right!r}], "
                f"method={step.method!r})",
            )

        case ParallelAggregate():
            group_keys = step.shared_group_keys
            state.use(*group_keys)

            # Fork every branch from the same frame at operator entry. This keeps
            # branch filters independent while preserving shared prefix filters.
            branch_base = state.working.copy()
            branch_results: list[pd.DataFrame] = []
            code_lines = ["# PARALLEL_AGGREGATE branches:"]

            for i, branch in enumerate(step.branches):
                branch_df = branch_base.copy()
                df_expr = "df"

                # Apply filter if specified
                if branch.filter_column is not None and branch.filter_values is not None:
                    state.use(branch.filter_column)
                    values = [
                        _coerce_value(branch_base[branch.filter_column], v)
                        for v in branch.filter_values
                    ]
                    branch_df = branch_df[branch_df[branch.filter_column].isin(values)]
                    df_expr = f"df[df[{branch.filter_column!r}].isin({values!r})]"

                # Group and aggregate
                if branch.column is not None:
                    state.use(branch.column)

                _require_non_empty(
                    branch_df, f"{step.op} branch {i}", branch.aggregate
                )

                grouped = branch_df.groupby(group_keys, dropna=False)

                if branch.column is None:
                    # Count group sizes
                    aggregated = grouped.size()
                elif branch.aggregate == "rms":
                    aggregated = grouped[branch.column].apply(
                        lambda s: _aggregate_series(s, "rms")
                    )
                else:
                    aggregated = grouped[branch.column].agg(branch.aggregate)

                # Convert to DataFrame with named result column
                result_df = aggregated.reset_index(name=branch.result_column)
                branch_results.append(result_df)

                agg_method = ".size()" if branch.column is None else f"[{branch.column!r}].{branch.aggregate}()"
                code_lines.append(
                    f"branch_{i} = {df_expr}.groupby({group_keys!r}){agg_method}"
                )

            # Preserve undefined statistics (mean, variance, extrema, etc.) as
            # missing. Only additive empty-group results have a natural zero.
            merged = branch_results[0]
            for i, branch_df in enumerate(branch_results[1:], start=1):
                merged = merged.merge(branch_df, on=group_keys, how="outer")

            result_columns = [branch.result_column for branch in step.branches]
            zero_fill_columns = [
                branch.result_column
                for branch in step.branches
                if branch.aggregate in {"count", "sum"}
            ]
            if zero_fill_columns:
                merged[zero_fill_columns] = merged[zero_fill_columns].fillna(0)

            # Update working frame
            state.working = merged

            observation = {
                "groups": len(merged),
                "columns": [*group_keys, *result_columns]
            }
            state.observations.append(observation)

            code_lines.append(
                f"merged = branch_0.merge(branch_1, on={group_keys!r}, how='outer')"
            )
            if zero_fill_columns:
                code_lines.append(
                    f"merged[{zero_fill_columns!r}] = "
                    f"merged[{zero_fill_columns!r}].fillna(0)"
                )

            return (observation, "\n".join(code_lines))

        case PredictivePipeline():
            value, code = _run_predictive(step, state)
            state.observations.append(value)
            return value, code

    raise PlanExecutionError(f"Unhandled operator: {type(step).__name__}")


def execute_plan(df: pd.DataFrame, plan: DeterministicPlan) -> PlanExecution:
    """Execute a validated plan in-process. No codegen, no sandbox, no LLM.

    The caller is expected to have already run both gates
    (``structural_validate`` and ``validate_plan_against_dataframe``). Any
    failure here is returned as ``ok=False`` with an ``error`` message rather
    than raised, so the caller can log a coverage gap and fall back to ReAct.
    """
    started = time.perf_counter()
    state = _State(original=df, working=df)
    steps: list[dict[str, Any]] = []
    code_lines: list[str] = []
    trace_lines: list[str] = []

    def _failure(message: str) -> PlanExecution:
        return PlanExecution(
            ok=False,
            error=message,
            plan_kind=plan.kind,
            rows_scanned=len(df),
            rows_after_filter=len(state.working),
            columns_used=sorted(state.columns_used),
            operators_used=plan.operators_used,
            code="\n".join(code_lines),
            trace="\n".join(trace_lines),
            steps=steps,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    for index, step in enumerate(plan.steps, start=1):
        try:
            observation, code = _execute_step(step, state)
        except (PlanSchemaError, PlanExecutionError) as exc:
            return _failure(f"{step.op}: {exc}")
        except Exception as exc:  # noqa: BLE001 — surfaced as a coverage gap
            return _failure(f"{step.op}: {type(exc).__name__}: {exc}")

        steps.append(
            {
                "step": index,
                "op": step.op,
                "ok": True,
                "output": str(observation),
                "code": code,
                "action_input": code,
            }
        )
        code_lines.append(code)
        trace_lines.extend(
            [
                f"Thought: typed operator step {index} ({step.op})",
                "Action: typed_operator_exec",
                f"Action Input: {code}",
                f"Observation: {observation}",
            ]
        )

    value = (
        state.observations[-1] if state.observations else f"rows={len(state.working)}"
    )
    trace_lines.append(f"Final Answer: {value}")
    return PlanExecution(
        value=value,
        ok=True,
        error=None,
        plan_kind=plan.kind,
        rows_scanned=len(df),
        rows_after_filter=len(state.working),
        columns_used=sorted(state.columns_used),
        operators_used=plan.operators_used,
        code="\n".join(code_lines),
        trace="\n".join(trace_lines),
        steps=steps,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
    )


# ---------------------------------------------------------------------------
# Plan parsing (Gate 1)
# ---------------------------------------------------------------------------


def structural_validate(raw: Any) -> DeterministicPlan:
    """Gate 1: structural validation of a raw plan payload.

    Raises:
        ValidationError: unknown op, missing field, or wrong type.
    """
    if isinstance(raw, DeterministicPlan):
        return raw
    return DeterministicPlan.model_validate(raw)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    body = text[3:]
    if body.lower().startswith("json"):
        body = body[4:]
    closing = body.rfind("```")
    return (body[:closing] if closing != -1 else body).strip()


def _extract_json_object(text: str) -> str:
    """Return the first balanced top-level JSON object in ``text``.

    A naive ``find("{")`` / ``rfind("}")`` span breaks whenever the model wraps
    the plan in prose containing braces, or emits trailing commentary. This
    scanner is brace-depth aware and skips over string literals and escapes, so
    it never alters the decoded content — it only chooses the boundaries.
    """
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
    raise ValueError("No balanced JSON object found in guardrail+plan response")


def parse_guardrail_and_plan(payload: str | dict[str, Any]) -> GuardrailAndPlan:
    """Parse the single-round-trip guardrail+plan response (Gate 1).

    Raises:
        ValidationError: the response is not a valid GuardrailAndPlan.
        ValueError: the response contains no JSON object at all.
    """
    return parse_guardrail_response(payload).parsed


@dataclass
class ParsedGuardrail:
    """Gate 1 output plus the audit trail of what normalization changed."""

    parsed: GuardrailAndPlan
    raw: dict[str, Any]
    normalization_actions: list[str]


def parse_guardrail_response(payload: str | dict[str, Any]) -> ParsedGuardrail:
    """Extract, normalize and structurally validate the planner response."""
    if isinstance(payload, dict):
        raw = payload
    else:
        raw = json.loads(_extract_json_object(_strip_code_fence(payload)))
    normalized, actions = normalize_guardrail_payload(raw)
    return ParsedGuardrail(
        parsed=GuardrailAndPlan.model_validate(normalized),
        raw=raw,
        normalization_actions=actions,
    )


# ---------------------------------------------------------------------------
# Deterministic pre-validation normalization
# ---------------------------------------------------------------------------
#
# This stage runs between JSON extraction and Pydantic validation. It is allowed
# to canonicalize *representation* only. It must never invent a column, infer a
# missing schema field, rewrite a correlation into a difference, or otherwise
# choose a semantic reading of the question — a plan that is semantically wrong
# has to fail loudly rather than be massaged into something executable.

NORMALIZATION_VERSION = "1"

#: Fields whose value is a closed lowercase vocabulary.
_LOWERCASE_ENUM_FIELDS: frozenset[str] = frozenset(
    {
        "aggregate",
        "comparator",
        "direction",
        "operation",
        "kind",
        "epoch_unit",
        "mode",
        "threshold",
        "holdout_row",
        "model",
    }
)

#: Value lists whose order carries no meaning, so a stable order is safe.
_ORDER_FREE_LIST_FIELDS: frozenset[str] = frozenset({"values", "filter_values"})


def _sort_key(value: Any) -> tuple[str, str]:
    return (type(value).__name__, str(value))


def _normalize_step(step: Any, actions: list[str]) -> Any:
    if not isinstance(step, dict):
        return step
    out: dict[str, Any] = {}
    for key, value in step.items():
        if value is None:
            actions.append(f"dropped null field {key!r}")
            continue
        if key == "op" and isinstance(value, str):
            canonical = value.strip().upper()
            if canonical != value:
                actions.append(f"canonicalized op {value!r} -> {canonical!r}")
            out[key] = canonical
            continue
        if key in _LOWERCASE_ENUM_FIELDS and isinstance(value, str):
            canonical = value.strip().lower()
            if canonical != value:
                actions.append(f"canonicalized {key} {value!r} -> {canonical!r}")
            out[key] = canonical
            continue
        if key in _ORDER_FREE_LIST_FIELDS and isinstance(value, list):
            ordered = sorted(value, key=_sort_key)
            if ordered != value:
                actions.append(f"stable-sorted {key}")
            out[key] = ordered
            continue
        if key == "branches" and isinstance(value, list):
            out[key] = [_normalize_step(branch, actions) for branch in value]
            continue
        out[key] = value
    _reject_pseudo_aggregate(out)
    return out


def _reject_pseudo_aggregate(step: dict[str, Any]) -> None:
    """Fail loudly on percentile-shaped aggregate names instead of guessing.

    ``percentile_99`` is not an aggregate this vocabulary can compute; a dataset
    that pre-computes percentiles exposes them as ordinary columns, and silently
    mapping the name to one would be inventing an answer.
    """
    aggregate = step.get("aggregate")
    if not isinstance(aggregate, str):
        return
    stem = aggregate.replace("-", "_").split("_")[0]
    if stem in ("percentile", "quantile", "pctl", "p") or (
        aggregate.startswith("p") and aggregate[1:].isdigit()
    ):
        raise PlanSchemaError(
            f"{step.get('op', 'operator')}: {aggregate!r} is not an aggregate. "
            "Percentiles are not computed by this vocabulary; reference the "
            "pre-computed percentile column directly (e.g. accel_stats_z_p99) "
            "and combine columns with DERIVE_BINARY."
        )


def _rewrite_single_branch_parallel(
    steps: list[Any], actions: list[str]
) -> list[Any]:
    """Rewrite a one-branch PARALLEL_AGGREGATE into its sequential equivalent.

    PARALLEL_AGGREGATE exists to put several independently filtered aggregates
    side by side; with one branch it is just a filter plus a grouped aggregate,
    which the vocabulary already expresses. Only rewritten when the consumer of
    the branch result is unambiguous, because RANK_ROWS-after-PARALLEL and
    RANK_GROUPS-after-GROUP consume different shapes.
    """
    out: list[Any] = []
    index = 0
    while index < len(steps):
        step = steps[index]
        branches = step.get("branches") if isinstance(step, dict) else None
        if (
            not isinstance(step, dict)
            or step.get("op") != "PARALLEL_AGGREGATE"
            or not isinstance(branches, list)
            or len(branches) != 1
        ):
            out.append(step)
            index += 1
            continue

        branch = branches[0]
        if not isinstance(branch, dict):
            out.append(step)
            index += 1
            continue
        result_column = branch.get("result_column")
        nxt = steps[index + 1] if index + 1 < len(steps) else None
        consumer: dict[str, Any] | None = None
        consumed_op = ""
        if nxt is None:
            pass
        elif isinstance(nxt, dict) and nxt.get("op") == "RANK_ROWS" and nxt.get("column") == result_column:
            consumer = {"op": "RANK_GROUPS", "direction": nxt.get("direction")}
            consumed_op = "RANK_ROWS"
        elif isinstance(nxt, dict) and nxt.get("op") == "AGGREGATE_COLUMN" and nxt.get("column") == result_column:
            consumer = {"op": "AGGREGATE_GROUPS", "aggregate": nxt.get("aggregate")}
            consumed_op = "AGGREGATE_COLUMN"
        else:
            out.append(step)
            index += 1
            continue

        if branch.get("filter_column") and branch.get("filter_values"):
            out.append(
                {
                    "op": "FILTER_IN",
                    "column": branch["filter_column"],
                    "values": branch["filter_values"],
                }
            )
        grouped = {
            "op": "GROUP_AGGREGATE",
            "group_by": branch.get("group_by"),
            "aggregate": branch.get("aggregate"),
        }
        if branch.get("column") is not None:
            grouped["column"] = branch["column"]
        out.append(grouped)
        actions.append("rewrote single-branch PARALLEL_AGGREGATE as GROUP_AGGREGATE")
        index += 1
        if consumer is not None:
            out.append(consumer)
            actions.append(f"rewrote {consumed_op} as {consumer['op']}")
            index += 1
    return out


def _rewrite_predictive_prefix_filter(
    steps: list[Any], actions: list[str]
) -> list[Any]:
    """Rewrite FILTER_COMPARE(eq) + PREDICTIVE_PIPELINE into a single predictive step.

    Some sampled plans split the record filter into its own step and leave
    PREDICTIVE_PIPELINE.filter_column/filter_value null. Predictive execution
    owns filtering semantics, so this rewrite preserves intent while ensuring
    downstream execution remains bounded and deterministic.
    """
    out: list[Any] = []
    index = 0
    while index < len(steps):
        current = steps[index]
        nxt = steps[index + 1] if index + 1 < len(steps) else None

        if (
            isinstance(current, dict)
            and isinstance(nxt, dict)
            and current.get("op") == "FILTER_COMPARE"
            and current.get("comparator") == "eq"
            and nxt.get("op") == "PREDICTIVE_PIPELINE"
            and nxt.get("filter_column") is None
            and nxt.get("filter_value") is None
        ):
            merged = dict(nxt)
            merged["filter_column"] = current.get("column")
            merged["filter_value"] = current.get("value")
            out.append(merged)
            actions.append(
                "rewrote FILTER_COMPARE + PREDICTIVE_PIPELINE into inline predictive filter"
            )
            index += 2
            continue

        out.append(current)
        index += 1

    return out


def normalize_raw_plan(plan: Any) -> tuple[Any, list[str]]:
    """Canonicalize a raw plan payload. Returns (normalized, actions)."""
    actions: list[str] = []
    if not isinstance(plan, dict):
        return plan, actions
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return plan, actions
    normalized = [_normalize_step(step, actions) for step in steps]
    normalized = _rewrite_single_branch_parallel(normalized, actions)
    normalized = _rewrite_predictive_prefix_filter(normalized, actions)
    out = dict(plan)
    out["steps"] = normalized
    out.setdefault("version", PLAN_VERSION)
    return out, actions


def normalize_guardrail_payload(payload: Any) -> tuple[Any, list[str]]:
    """Canonicalize the guardrail wrapper and the plan it carries."""
    actions: list[str] = []
    if not isinstance(payload, dict):
        return payload, actions
    out = dict(payload)
    if out.get("plan") is not None:
        out["plan"], actions = normalize_raw_plan(out["plan"])
    return out, actions


# ---------------------------------------------------------------------------
# Offline vocabulary growth — coverage gap log
# ---------------------------------------------------------------------------


def log_operator_gap(
    *,
    query: str,
    stage: str,
    error: str,
    raw_plan: Any = None,
    dataset: str = "",
) -> None:
    """Append a coverage gap to the offline review log.

    Gaps are reviewed **between** runs: a missing operator is designed, tested,
    and versioned into the vocabulary offline. Nothing here mutates the
    vocabulary at request time.

    Args:
        stage: "structural", "schema", "execution", or "no_plan".
    """
    path = Path(
        os.getenv(
            "FF_OPERATOR_GAP_LOG",
            str(Path(__file__).resolve().parents[1] / "results" / "operator_gaps.jsonl"),
        )
    )
    record = {
        "logged_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": dataset,
        "query": query,
        "stage": stage,
        "error": error,
        "raw_plan": raw_plan,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
    except OSError:
        # Gap logging is diagnostic only; never fail a query because of it.
        pass


# ---------------------------------------------------------------------------
# Prompt-facing vocabulary description
# ---------------------------------------------------------------------------

OPERATOR_VOCABULARY_SPEC: str = """\
EXECUTION MODEL:
- Plans are sequential by default: each step reads the current working frame.
- FILTER_* steps narrow the working frame (rows removed).
- DERIVE_* steps add columns to both working and original frames.
- GROUP_AGGREGATE produces an internal grouped result for RANK_GROUPS or AGGREGATE_GROUPS.
  It does NOT create DataFrame columns and does NOT accept result_column.
- PARALLEL_AGGREGATE is the ONLY operator that creates multiple independent branches from
    the working frame at operator entry and produces a merged working frame with new columns.
- After GROUP_AGGREGATE, only RANK_GROUPS or AGGREGATE_GROUPS can consume the result.
- After PARALLEL_AGGREGATE, the working frame contains group keys + result_columns.
- COMPARE_VALUES reduces exactly two preceding AGGREGATE_COLUMN/AGGREGATE_GROUPS scalars into one
  comparison — it works no matter what produced those scalars (a plain filter, a PARALLEL_AGGREGATE
  merge, a GROUP_AGGREGATE). RANK_ROWS/RANK_GROUPS answer "which ROW/GROUP is extreme"; COMPARE_VALUES
  and COMPARE_PARTITIONS answer "what is the difference between these two numbers" — never use
  RANK_ROWS as a substitute for a two-value comparison.

HARD RULES — decide the shape of the plan BEFORE choosing operators:

R1. OVERALL COMPARISON (no entity in the question).
    Trigger words: "overall", "in general", "on average", "across the dataset", "between A and B",
    or any comparison of two label groups that never mentions a user / subject / device / entity.
    REQUIRED SHAPE: SPLIT_BY_VALUES(group_a) -> SPLIT_BY_VALUES(group_b)
                    -> AGGREGATE_PARTITIONS -> COMPARE_PARTITIONS
    This pools every matching row on each side and produces exactly two numbers plus their delta.
    DO NOT use PARALLEL_AGGREGATE here. DO NOT introduce a per-entity grouping layer that the
    question never asked for — a mean-of-per-entity-means is a DIFFERENT number from a pooled mean.

R2. PER-ENTITY COMPARISON (the question names an entity dimension).
    Trigger words: "which user", "which subject", "per subject", "per device", "per entity",
    "for each X", "the user whose ...".
    REQUIRED SHAPE: PARALLEL_AGGREGATE (one branch per filtered subset, all sharing the same
                    group_by entity key) -> optional DERIVE_BINARY -> optional FILTER_COMPARE
                    -> RANK_ROWS (return_columns MUST include the entity key).

R3. DURATION IS NEVER A SUM OF TIMESTAMPS.
    A timestamp is an instant; a duration is an interval between two instants. "How long did X
    last", "total time spent", "duration exceeding" all require elapsed time to be MATERIALIZED
    first with DERIVE_DURATION_SECONDS, then aggregated like any ordinary numeric column:
        DERIVE_DURATION_SECONDS -> sum/mean of the derived result column.
    sum(timestamp_column) is rejected by schema validation and is always wrong.

R4. COMPARE_VALUES OPERATES ON SCALARS THAT WERE ALREADY COMPUTED.
    It takes NO column references at all — it has no "column1"/"column2"/"column" field. It reads
    the two most recent AGGREGATE_COLUMN / AGGREGATE_GROUPS scalars from the plan itself. To
    compare two columns you must first reduce each one with its own AGGREGATE_COLUMN step.

R5. AN AGGREGATE OVER ZERO ROWS IS AN ERROR, NOT A RESULT.
    If a filter or split can empty the frame, the plan fails loudly rather than returning NaN.
    Check that filter values actually exist in the schema's sample values before emitting them.

R6. DURATION MUST BE DERIVED FROM THE FULL TIMELINE, NOT A CATEGORY SUBSET.
    DERIVE_DURATION_SECONDS.group_by is the entity key only. Computing elapsed time only within 
    rows of one category column treats non-adjacent occurrences of that label as continuous, 
    corrupting every downstream sum. Category filtering happens after this step, never inside it.    

OPERATORS:

FILTER_COMPARE      {"op":"FILTER_COMPARE","column":str,"comparator":"eq|ne|gt|gte|lt|lte","value":scalar}
FILTER_IN           {"op":"FILTER_IN","column":str,"values":[scalar,...]}
FILTER_NOT_EMPTY    {"op":"FILTER_NOT_EMPTY","column":str}

FILTER_EQ_AGGREGATE {"op":"FILTER_EQ_AGGREGATE","column":str,"aggregate":AGG}   rows where column == AGG(column)
                    USE FOR: rows where a column reaches its maximum or minimum;
                    this preserves every tied row. Follow with SELECT_COLUMN to return
                    another field from those rows. Never nest an operator object inside
                    FILTER_COMPARE.value; it must always be a literal scalar.

AGGREGATE_COLUMN    {"op":"AGGREGATE_COLUMN","column":str,"aggregate":AGG}
COUNT_ROWS          {"op":"COUNT_ROWS"}
COUNT_DISTINCT      {"op":"COUNT_DISTINCT","column":str}
SELECT_COLUMN       {"op":"SELECT_COLUMN","column":str,"distinct":bool}
DERIVE_BINARY       {"op":"DERIVE_BINARY","left":str,"right":str,"operation":"add|subtract|multiply|divide|abs_difference","result":str}
                    CRITICAL: left and right must be EXISTING COLUMN NAMES (strings), never nested operator objects,
                    and NEVER a numeric literal (e.g. 60000000000) or a time constant — DERIVE_BINARY is
                    column-vs-column arithmetic ONLY. If one side of the arithmetic is a constant/scalar number
                    rather than a real column name, DERIVE_BINARY is the WRONG operator — use DERIVE_BIN instead
                    (see below) when the constant is a bucket width, or set "plan" to null if no operator fits.
                    operation must be an ARITHMETIC operation, never a comparator like "gt" or "lt".
                    Use this ONLY after PARALLEL_AGGREGATE to combine result_column values, or to combine
                    existing columns. Cannot compute medians/aggregates inline — use SPLIT_BY_THRESHOLD for that.
DERIVE_VECTOR_MAGNITUDE {"op":"DERIVE_VECTOR_MAGNITUDE","columns":[str,str,str],"result":str}
DERIVE_BIN          {"op":"DERIVE_BIN","column":str,"kind":"numeric|temporal",
                     "width":number|null,"freq":str|null,"epoch_unit":"s|ms|us|ns"|null,"result":str}
                    NUMERIC MODE (kind="numeric"): floor(col/width)*width for ordinary numeric bucketing.
                    TEMPORAL MODE (kind="temporal"): floor timestamps with ``dt.floor(freq)``.
                    If the source timestamp column is numeric epoch data, epoch_unit is REQUIRED
                    (s|ms|us|ns). No unit guessing is allowed.
                    Canonical template for time-window ranking:
                    DERIVE_BIN(kind="temporal", freq="1min") ->
                    GROUP_AGGREGATE(group_by=[result], aggregate="mean", column=metric) ->
                    RANK_GROUPS(direction="max").

DERIVE_DURATION_SECONDS {"op":"DERIVE_DURATION_SECONDS","timestamp_column":str,"group_by":[str,...],
                     "result":str,"clip_negative":bool,"fill_first":number}
                    USE FOR: any question about elapsed time, time spent, session length, or duration.
                    Sorts by group_by + timestamp_column, takes the difference between consecutive
                    timestamps WITHIN each group, and writes it as seconds into "result" (default
                    "dt_s"). The first row of every group gets "fill_first" (default 0.0), and
                    "clip_negative" (default true) floors negative gaps at zero.
                    group_by must contain ONLY the entity key, NEVER include the category column 
                    you intend to filter by afterward — doing so breaks time-contiguity by grouping 
                    non-adjacent samples of the same category together. Filter by category AFTER 
                    duration is derived, inside PARALLEL_AGGREGATE branches or FILTER_IN, inside 
                    PARALLEL_AGGREGATE branches or FILTER_IN, never inside DERIVE_DURATION_SECONDS's 
                    group_by.
                    timestamp_column must be a datetime column or a numeric nanosecond counter.
                    THIS IS THE ONLY WAY TO EXPRESS DURATION. After it, aggregate "result" normally:
                    AGGREGATE_COLUMN(column="dt_s",aggregate="sum") for a total, or a
                    PARALLEL_AGGREGATE branch with column="dt_s",aggregate="sum" for a per-entity
                    total. NEVER aggregate the timestamp column itself.

GROUP_AGGREGATE     {"op":"GROUP_AGGREGATE","group_by":[str,...],"aggregate":AGG,"column":str|null,"freq":str|null}
                    USE WHEN: One filtered subset needs one grouped metric and the answer is the highest/lowest
                    group or a scalar reduction of that grouped metric.
                    OUTPUT: Internal grouped result consumed ONLY by RANK_GROUPS or AGGREGATE_GROUPS. It has NO
                    name of its own — you can never reference it by a column name like "max_MLII" or
                    "mean_duration" in a later step. GROUP_AGGREGATE does not accept and never produces a
                    "result"/"result_column" field.
                    DO NOT USE: When comparing two or more independently filtered subsets per group.
                    DO NOT USE: For a per-group RANGE/SPREAD question ("largest difference between max and min
                    X per group", "which group has the widest spread of Y"). This requires TWO aggregates
                    (max AND min) available as separate columns simultaneously, which GROUP_AGGREGATE cannot
                    provide — use PARALLEL_AGGREGATE with two branches (same group_by, same column, one branch
                    aggregate="max" and one aggregate="min", each with its own result_column) followed by
                    DERIVE_BINARY(operation="abs_difference") and RANK_ROWS instead. See the PARALLEL_AGGREGATE
                    "per-group range" example below.

AGGREGATE_GROUPS    {"op":"AGGREGATE_GROUPS","aggregate":AGG}      reduce the previous GROUP_AGGREGATE result
RANK_GROUPS         {"op":"RANK_GROUPS","direction":"max|min"}     best group from the previous GROUP_AGGREGATE
                    Output includes winning group key(s) and grouped metric value.
                    Metric field name is ``<aggregate>_<metric>`` (example: ``mean_instability_score``).

RANK_ROWS           {"op":"RANK_ROWS","column":str,"direction":"max|min","return_columns":[str,...]}
                    USE WHEN: You need the row with max/min value from a DataFrame (after filters, derives, or
                    PARALLEL_AGGREGATE). REQUIRES: A working frame with actual rows and columns.

PARALLEL_AGGREGATE  {"op":"PARALLEL_AGGREGATE","branches":[{"filter_column":str|null,"filter_values":[scalar,...]|null,
                     "group_by":[str,...],"aggregate":AGG,"column":str|null,"result_column":str},...]}
                    USE WHEN: The question compares, combines, or ranks metrics from TWO OR MORE independently
                    filtered subsets PER SHARED GROUPING KEY (e.g., "compare resting vs dynamic activity per subject",
                    "which user has the largest difference between X and Y"). There MUST be a grouping dimension
                    (subject_id, user_id, etc.) that appears in every branch's group_by field.
                    DO NOT USE when comparing two halves of the entire dataset with no per-entity grouping — use
                    SPLIT_BY_THRESHOLD + AGGREGATE_PARTITIONS + COMPARE_PARTITIONS for that pattern instead.
                    EXECUTION: Every branch starts from the SAME working frame at operator entry, filters its
                    own rows, groups by the SAME keys, aggregates, then all branch outputs are outer-merged.
                    Therefore a common FILTER_* before PARALLEL_AGGREGATE constrains every branch. Missing
                    count/sum results are filled with 0; missing mean/median/std/var/min/max/rms results remain
                    null because an unobserved measurement is not a measured zero. Arithmetic and correlation
                    then follow pandas missing-value semantics.
                    OUTPUT: A working frame with columns [group_by keys, result_column_1, result_column_2, ...].
                    NEXT STEPS depend on what the question asks for:
                    - "which entity/subject/user is highest/lowest" → RANK_ROWS(column=a result_column).
                    - "what is entity X's difference between the two metrics" → DERIVE_BINARY on the two
                      result_columns, then RANK_ROWS or SELECT_COLUMN.
                    - "what is the OVERALL/AGGREGATE difference between the two metrics across ALL entities"
                      (no single entity singled out) → AGGREGATE_COLUMN(column=result_column_1) then
                      AGGREGATE_COLUMN(column=result_column_2) then COMPARE_VALUES. Do NOT use RANK_ROWS for
                      this — RANK_ROWS picks one entity's row, which silently answers a different question.
                    DO NOT use GROUP_AGGREGATE before, after, or inside this pattern.
                    CRITICAL: group_by must contain at least one column name — NEVER use an empty list.
                    CRITICAL: "column" must be null ONLY when aggregate is "count". For every other aggregate
                    (mean, sum, median, std, var, rms, min, max, nunique) column is REQUIRED and must be a real
                    column name — never leave it null "by default".
                    CRITICAL: if the metric to aggregate is NOT a raw column (e.g. "acceleration magnitude",
                    "vector magnitude", "overall intensity"), it does not exist yet — emit a DERIVE_* step
                    (e.g. DERIVE_VECTOR_MAGNITUDE) BEFORE this operator to materialize it, then reference that
                    step's "result" name as every branch's "column". Derived columns are written to BOTH the
                    working and original frames, so a DERIVE_* step run before PARALLEL_AGGREGATE is visible to
                    every branch.
                    Example (elapsed time per entity — the duration column must be DERIVED first;
                    there is no raw duration column in a sampled sensor table):
                    [{"op":"DERIVE_DURATION_SECONDS","timestamp_column":"timestamp_col",
                      "group_by":["entity_id"],"result":"dt_s","clip_negative":true,"fill_first":0.0},
                     {"op":"PARALLEL_AGGREGATE","branches":[
                       {"filter_column":"category_col","filter_values":["cat_1","cat_2"],
                        "group_by":["entity_id"],"aggregate":"sum","column":"dt_s","result_column":"a_duration"},
                       {"filter_column":"category_col","filter_values":["cat_3","cat_4"],
                        "group_by":["entity_id"],"aggregate":"sum","column":"dt_s","result_column":"b_duration"}
                     ]}]
                    Example (derived metric — a DERIVE_* step must run first, group A vs group B metric
                    PER ENTITY, then find which entity differs most — "per entity"/"which X" is explicit):
                    [{"op":"DERIVE_VECTOR_MAGNITUDE","columns":["c1","c2","c3"],"result":"derived_metric"},
                     {"op":"PARALLEL_AGGREGATE","branches":[
                       {"filter_column":"category_col","filter_values":["cat_1","cat_2"],
                        "group_by":["entity_id"],"aggregate":"mean","column":"derived_metric","result_column":"a_mean_metric"},
                       {"filter_column":"category_col","filter_values":["cat_3","cat_4"],
                        "group_by":["entity_id"],"aggregate":"mean","column":"derived_metric","result_column":"b_mean_metric"}
                     ]},
                     {"op":"RANK_ROWS","column":"b_mean_metric","direction":"max",
                      "return_columns":["entity_id","a_mean_metric","b_mean_metric"]}]
                    Example (per-entity breakdown reduced to ONE overall comparison — "which entity" is NOT
                    asked; the question wants a single overall number, so RANK_ROWS would be wrong here):
                    [{"op":"DERIVE_VECTOR_MAGNITUDE","columns":["c1","c2","c3"],"result":"derived_metric"},
                     {"op":"PARALLEL_AGGREGATE","branches":[
                       {"filter_column":"category_col","filter_values":["cat_1","cat_2"],
                        "group_by":["entity_id"],"aggregate":"mean","column":"derived_metric","result_column":"a_mean_metric"},
                       {"filter_column":"category_col","filter_values":["cat_3","cat_4"],
                        "group_by":["entity_id"],"aggregate":"mean","column":"derived_metric","result_column":"b_mean_metric"}
                     ]},
                     {"op":"AGGREGATE_COLUMN","column":"a_mean_metric","aggregate":"mean"},
                     {"op":"AGGREGATE_COLUMN","column":"b_mean_metric","aggregate":"mean"},
                     {"op":"COMPARE_VALUES","mode":"difference","label_a":"group_a","label_b":"group_b"}]
                    NOTE: this two-level mean-of-per-entity-means is NOT the same number as pooling every row
                    directly. If the question has NO per-entity framing at all ("overall", "in general", no
                    mention of entity/user/per-X), prefer SPLIT_BY_VALUES + AGGREGATE_PARTITIONS +
                    COMPARE_PARTITIONS instead (see below) — it aggregates over rows directly, matching what
                    "overall average" normally means.
                    Example (per-group RANGE: "which group has the largest difference between max and min of
                    a column" — both branches read the SAME column with NO filter, only the aggregate differs;
                    do NOT use GROUP_AGGREGATE for this, it cannot expose two named aggregates at once):
                    [{"op":"PARALLEL_AGGREGATE","branches":[
                       {"filter_column":null,"filter_values":null,
                        "group_by":["group_id"],"aggregate":"max","column":"metric_col","result_column":"max_metric"},
                       {"filter_column":null,"filter_values":null,
                        "group_by":["group_id"],"aggregate":"min","column":"metric_col","result_column":"min_metric"}
                     ]},
                     {"op":"DERIVE_BINARY","left":"max_metric","right":"min_metric","operation":"abs_difference","result":"metric_range"},
                     {"op":"RANK_ROWS","column":"metric_range","direction":"max","return_columns":["group_id","metric_range"]}]

SPLIT_BY_THRESHOLD  {"op":"SPLIT_BY_THRESHOLD","column":str,"comparator":"gt|gte|lt|lte","threshold":"median|mean|min|max","label":str}
SPLIT_BY_VALUES     {"op":"SPLIT_BY_VALUES","column":str,"values":[scalar,...],"label":str}
AGGREGATE_PARTITIONS {"op":"AGGREGATE_PARTITIONS","partitions":[label,label],"aggregate":AGG,"column":str|null}
COMPARE_PARTITIONS  {"op":"COMPARE_PARTITIONS","mode":"difference|abs_difference|ratio"}
                    USE: SPLIT_BY_* + AGGREGATE_PARTITIONS + COMPARE_PARTITIONS for "compare A versus B" questions
                    when the comparison is based on static partitions, not per-group aggregates.
                    Example (comparing above-median vs below-median half by a numeric column):
                    [{"op":"SPLIT_BY_THRESHOLD","column":"numeric_col","comparator":"gt","threshold":"median","label":"above_median"},
                     {"op":"SPLIT_BY_THRESHOLD","column":"numeric_col","comparator":"lte","threshold":"median","label":"below_median"},
                     {"op":"AGGREGATE_PARTITIONS","partitions":["above_median","below_median"],"aggregate":"mean","column":"metric_col"},
                     {"op":"COMPARE_PARTITIONS","mode":"difference"}]
                    Example (overall group A vs group B derived metric, NO per-entity framing — "the overall X
                    between A and B" with no mention of entity/user/per-X means pool ALL matching rows directly):
                    [{"op":"DERIVE_VECTOR_MAGNITUDE","columns":["c1","c2","c3"],"result":"derived_metric"},
                     {"op":"SPLIT_BY_VALUES","column":"category_col","values":["cat_1","cat_2"],"label":"group_a"},
                     {"op":"SPLIT_BY_VALUES","column":"category_col",
                      "values":["cat_3","cat_4"],"label":"group_b"},
                     {"op":"AGGREGATE_PARTITIONS","partitions":["group_a","group_b"],"aggregate":"mean","column":"derived_metric"},
                     {"op":"COMPARE_PARTITIONS","mode":"difference"}]
                    This pattern compares TWO DATASET HALVES (pooled row-level statistic — one number per side).
                    If the question asks to compare metrics PER ENTITY (e.g., "per subject", "per user", "for
                    each X", "which user"), use PARALLEL_AGGREGATE instead.

COMPARE_VALUES      {"op":"COMPARE_VALUES","mode":"difference|abs_difference|ratio","label_a":str,"label_b":str}
                    USE: Generalized version of COMPARE_PARTITIONS — compares the two most recently computed
                    scalar aggregates, from ANY source (not just AGGREGATE_PARTITIONS). REQUIRES exactly two
                    immediately-preceding AGGREGATE_COLUMN or AGGREGATE_GROUPS steps, with nothing else of that
                    kind in between. Typical use: reducing a PARALLEL_AGGREGATE per-entity breakdown down to one
                    overall comparison (see the PARALLEL_AGGREGATE section above for the worked example).
                    DO NOT use after only ONE AGGREGATE_COLUMN/AGGREGATE_GROUPS step, and DO NOT use after
                    AGGREGATE_PARTITIONS (use COMPARE_PARTITIONS for that).
                    TAKES NO COLUMN REFERENCES. The only fields are mode, label_a and label_b — label_a
                    and label_b are display names for the two scalars already on the plan's scalar trail,
                    NOT column names. There is no "column1", "column2", "column", "left" or "right" field;
                    emitting one fails structural validation immediately. To compare two columns, reduce
                    each to a scalar with its own AGGREGATE_COLUMN step first, in the order you want them
                    compared (label_a describes the FIRST scalar, label_b the SECOND).

CORRELATE_COLUMNS   {"op":"CORRELATE_COLUMNS","left":str,"right":str,"method":"pearson|spearman|kendall"}
                    USE FOR: any question phrased as "does X correlate with Y", "is there a relationship
                    between X and Y", "how does X vary with Y". This is the ONLY operator that computes a
                    correlation — never substitute a difference, ratio, or ranking for one, and never
                    reduce a correlation question to RANK_ROWS.
                    left and right must both be REAL numeric schema columns, or the "result" of an
                    earlier DERIVE_* step. If one side of the question names a quantity this dataset does
                    not measure (a patient attribute, an external condition, a count nobody recorded),
                    there is no column to put there: set in_scope=false and name the missing field. Do
                    NOT encode a nominal label column as ordinal numbers to stand in for it, and do NOT
                    invent a "*_proxy" column — an invented operand produces a confident number that
                    answers a question nobody asked.

PREDICTIVE_PIPELINE {"op":"PREDICTIVE_PIPELINE","model":"logistic_regression|random_forest|one_nearest_neighbor|hist_gradient_boosting",
                     "feature_columns":[str,...],"target_column":str,"sort_by":[str,...],"train_fraction":number,
                     "holdout_row":"first|last","filter_column":str|null,"filter_value":scalar|null,
                     "target_from_non_empty":bool,"target_label":str}
                    USE WHEN: the query explicitly asks to train on an in-dataset
                    chronological subset and predict on a holdout row from the
                    same dataset.
                    CRITICAL: model must be one of the exact enum values above.
                    CRITICAL: feature_columns must be listed explicitly and each
                    column must exist in the schema and be numeric.
                    CRITICAL: sort_by must list real schema columns that define
                    chronological ordering before the split.
                    CRITICAL: target_column must be a real schema column and must
                    not appear in feature_columns.
                    CRITICAL: set target_from_non_empty=true only when the query
                    target is "whether <column> is present/non-empty"; otherwise
                    keep it false and predict labels directly from target_column.

AGG is one of: min, max, mean, median, sum, count, std, var, nunique, rms.

WORKED EXAMPLES — three question shapes that are easy to confuse. Substitute the real schema
column names; the placeholder names below are illustrative only.

W1. OVERALL comparison of a DERIVED metric between two label groups.
    Question shape: "Compare <derived metric> between <group A activities> and <group B activities>."
    There is no entity in the question, so there is no per-entity layer in the plan (rule R1).
    [{"op":"DERIVE_VECTOR_MAGNITUDE","columns":["c1","c2","c3"],"result":"derived_metric"},
     {"op":"SPLIT_BY_VALUES","column":"category_col","values":["cat_1","cat_2","cat_3"],"label":"group_a"},
     {"op":"SPLIT_BY_VALUES","column":"category_col","values":["cat_4","cat_5"],"label":"group_b"},
     {"op":"AGGREGATE_PARTITIONS","partitions":["group_a","group_b"],"aggregate":"mean","column":"derived_metric"},
     {"op":"COMPARE_PARTITIONS","mode":"difference"}]
    WRONG for this question: PARALLEL_AGGREGATE grouped by an entity key, then RANK_ROWS — that
    answers "which entity" and silently changes both the statistic and the question.

W2. PER-ENTITY comparison of DURATION, asking which entity exceeds by the largest amount.
    Question shape: "Which <entity> spent more time in <group A> than in <group B>?"
    Elapsed time is derived first (rule R3); the entity key makes this per-entity (rule R2).
    [{"op":"DERIVE_DURATION_SECONDS","timestamp_column":"timestamp_col","group_by":["entity_id"],
      "result":"dt_s","clip_negative":true,"fill_first":0.0},
     {"op":"PARALLEL_AGGREGATE","branches":[
       {"filter_column":"category_col","filter_values":["cat_1","cat_2"],
        "group_by":["entity_id"],"aggregate":"sum","column":"dt_s","result_column":"a_duration"},
       {"filter_column":"category_col","filter_values":["cat_3","cat_4"],
        "group_by":["entity_id"],"aggregate":"sum","column":"dt_s","result_column":"b_duration"}
     ]},
     {"op":"DERIVE_BINARY","left":"a_duration","right":"b_duration","operation":"subtract","result":"duration_delta"},
     {"op":"FILTER_COMPARE","column":"duration_delta","comparator":"gt","value":0},
     {"op":"RANK_ROWS","column":"duration_delta","direction":"max","return_columns":["entity_id","a_duration","b_duration","duration_delta"]}]
    Use "subtract", NOT "abs_difference": "exceeds by the largest amount" is directional, and an
    absolute difference would also rank entities that went the other way. The FILTER_COMPARE keeps
    only entities that genuinely exceed. RANK_ROWS returns the entity key so the answer names someone.

W3. OVERALL comparison of a RAW column between exactly two label groups.
    Question shape: "What is the difference in average <raw column> between <label A> and <label B>?"
    Still an overall comparison (rule R1) — two labels are not two entities. Do not add a per-entity
    aggregation layer.
    [{"op":"SPLIT_BY_VALUES","column":"category_col","values":["cat_1"],"label":"group_a"},
     {"op":"SPLIT_BY_VALUES","column":"category_col","values":["cat_2"],"label":"group_b"},
     {"op":"AGGREGATE_PARTITIONS","partitions":["group_a","group_b"],"aggregate":"mean","column":"metric_col"},
     {"op":"COMPARE_PARTITIONS","mode":"abs_difference"}]
    Use "abs_difference" when the question asks for "the difference" with no direction implied, and
    "difference" when it asks how much A exceeds B.

INVALID PATTERN—never emit:
[{"op":"FILTER_IN",...}, {"op":"GROUP_AGGREGATE",...,"result_column":"X"}, {"op":"FILTER_IN",...}, {"op":"GROUP_AGGREGATE",...,"result_column":"Y"}]
2. NEVER nest an operator object inside another operator's field — all column references must be strings.
3. NEVER use a comparator (gt, lt, eq, etc.) as a DERIVE_BINARY operation — only arithmetic operations allowed.
4. NEVER emit an empty group_by array — it must contain at least one column name.
5. Use PARALLEL_AGGREGATE ONLY when comparing metrics PER ENTITY with a shared grouping key. Use
   SPLIT_BY_THRESHOLD + AGGREGATE_PARTITIONS + COMPARE_PARTITIONS when comparing two halves of the
   entire dataset with no per-entity dimension.
6. Use RANK_GROUPS only after GROUP_AGGREGATE; use RANK_ROWS after DataFrame-producing operations.
7. Use ONLY the operators above and ONLY real column names from the schema.
8. Use PARALLEL_AGGREGATE when two or more independently filtered aggregates must become columns on the same table.
9. NEVER put a numeric literal or time constant (e.g. 60000000000, 3600, 1000) into DERIVE_BINARY's
   left/right fields — those fields are column names only. A constant-vs-column operation (e.g.
   bucketing a timestamp into fixed-width windows) is DERIVE_BIN(column, width, result), not DERIVE_BINARY.
10. NEVER leave PARALLEL_AGGREGATE branch "column" null unless aggregate is "count". If the metric is
    derived (e.g. "magnitude", "vector magnitude", "intensity"), emit DERIVE_VECTOR_MAGNITUDE or another
    DERIVE_* step first, then set "column" to that step's "result" name in every branch.
11. After PARALLEL_AGGREGATE, only group keys + branch result_column names are available to DERIVE_BINARY and RANK_ROWS.
12. Use RANK_GROUPS only after GROUP_AGGREGATE; use RANK_ROWS after DataFrame-producing operations.
13. Use ONLY the operators above and ONLY real column names from the schema.
14. If the question cannot be expressed with these operators, set "plan" to null.
15. NEVER use RANK_ROWS/RANK_GROUPS as a substitute for a two-value comparison. RANK_ROWS/RANK_GROUPS
    answer "which entity/group is extreme" (one row picked out); COMPARE_VALUES/COMPARE_PARTITIONS answer
    "what is the difference between these two numbers" (no entity picked out). If the question has no
    per-entity framing ("overall", "in general", no "per subject"/"per user"/"which X"), the answer is a
    single overall comparison — use COMPARE_VALUES (after two AGGREGATE_COLUMN/AGGREGATE_GROUPS steps) or
    COMPARE_PARTITIONS (after SPLIT_BY_* + AGGREGATE_PARTITIONS), never RANK_ROWS.
16. NEVER invent a column name for a GROUP_AGGREGATE result (e.g. "max_val", "mean_duration") and then
    reference it in DERIVE_BINARY, RANK_ROWS, or any other step — GROUP_AGGREGATE does not name or expose
    a column, only RANK_GROUPS/AGGREGATE_GROUPS may consume it, and doing so will fail schema validation
    with "references unknown column". For a per-group range/spread (max vs min, or any two aggregates of
    the same column needed as separate values), use PARALLEL_AGGREGATE with one branch per aggregate, each
    given an explicit "result_column" name — those are the only per-group aggregate names that legitimately
    exist for later steps to reference. See the PARALLEL_AGGREGATE "per-group range" example above.

REJECTED PATTERNS — each of these fails validation. Do not emit them.

X1. Summing a timestamp to mean "duration".
    REJECTED: {"op":"AGGREGATE_COLUMN","column":"timestamp_col","aggregate":"sum"}
    REJECTED: {"op":"GROUP_AGGREGATE","group_by":["entity_id"],"aggregate":"sum","column":"timestamp_col"}
    REJECTED: a PARALLEL_AGGREGATE branch with "aggregate":"sum","column":"timestamp_col"
    CORRECT:  DERIVE_DURATION_SECONDS(timestamp_column="timestamp_col", group_by=["entity_id"],
              result="dt_s") first, then aggregate "dt_s" with sum. Adding timestamps together
              produces a meaningless number that scales with row count, not with elapsed time.

X2. Passing columns to COMPARE_VALUES.
    REJECTED: {"op":"COMPARE_VALUES","column1":"a_metric","column2":"b_metric"}
    REJECTED: {"op":"COMPARE_VALUES","mode":"difference","column":"a_metric"}
    CORRECT:  {"op":"AGGREGATE_COLUMN","column":"a_metric","aggregate":"mean"},
              {"op":"AGGREGATE_COLUMN","column":"b_metric","aggregate":"mean"},
              {"op":"COMPARE_VALUES","mode":"difference","label_a":"a","label_b":"b"}
    COMPARE_VALUES has exactly three optional fields: mode, label_a, label_b. Any other key is
    rejected structurally because every operator forbids unknown fields.

X3. PARALLEL_AGGREGATE for an overall dataset comparison.
    REJECTED for "compare <metric> between group A and group B overall / in general":
              PARALLEL_AGGREGATE(group_by=["entity_id"], ...) followed by RANK_ROWS
    CORRECT:  SPLIT_BY_VALUES + SPLIT_BY_VALUES + AGGREGATE_PARTITIONS + COMPARE_PARTITIONS (see W1).
    PARALLEL_AGGREGATE requires an entity dimension that the question actually named.

X4. RANK_ROWS after PARALLEL_AGGREGATE without the grouping key.
    REJECTED: {"op":"RANK_ROWS","column":"a_duration","direction":"max","return_columns":["a_duration"]}
    CORRECT:  {"op":"RANK_ROWS","column":"a_duration","direction":"max",
               "return_columns":["entity_id","a_duration"]}
    At least one of the PARALLEL_AGGREGATE group_by keys must appear in return_columns, otherwise
    the result is a number that identifies nobody.

X5. Legacy / invented fields that are not part of this vocabulary.
    REJECTED: "group_columns" (the field is "group_by" on GROUP_AGGREGATE, PARALLEL_AGGREGATE
              branches and DERIVE_DURATION_SECONDS)
    REJECTED: "aggregates":[...] — every operator takes exactly ONE "aggregate" string. To produce
              two aggregates of the same column side by side, use PARALLEL_AGGREGATE with one
              branch per aggregate, each with its own "result_column".
    REJECTED: "result_column" on GROUP_AGGREGATE — only PARALLEL_AGGREGATE branches name a result.
    REJECTED: "as", "alias", "name", "output", "unit", "timestamp" or any other field not listed in
              this spec. Every operator sets extra="forbid"; an unlisted field fails Gate 1.\

X6. Including the category/label column in DERIVE_DURATION_SECONDS.group_by.
    REJECTED: {"op":"DERIVE_DURATION_SECONDS","timestamp_column":"timestamp_col",
               "group_by":["entity_id","category_label"],"result":"dt_s"}
    CORRECT:  {"op":"DERIVE_DURATION_SECONDS","timestamp_column":"timestamp_col",
               "group_by":["entity_id"],"result":"dt_s"}
    Filtering by category happens in the PARALLEL_AGGREGATE branches that consume dt_s,
    never in the group_by of the derivation itself.

X7. Standing in a proxy for a column the dataset does not contain.
    REJECTED: mapping a nominal label column onto invented ordinal numbers so it can be
              correlated or averaged (e.g. treating behaviour categories as a passenger count).
    REJECTED: inventing a "*_proxy" / "*_estimate" / "*_index" column that no DERIVE_* step created.
    REJECTED: answering a correlation question with COMPARE_VALUES, DERIVE_BINARY or RANK_ROWS
              because CORRELATE_COLUMNS had no second real column to use.
    CORRECT:  set "in_scope": false and name the missing field in rejection_reason.
    A dataset that never measured a quantity cannot be made to report it.

X8. Percentiles as aggregate names.
    REJECTED: {"op":"PARALLEL_AGGREGATE","branches":[{...,"aggregate":"percentile_99",...}]}
    REJECTED: "aggregate":"p99" / "quantile_95" / "percentile_1"
    CORRECT:  reference the pre-computed percentile COLUMN by name and combine columns:
              [{"op":"DERIVE_BINARY","left":"metric_p99","right":"metric_p1",
                "operation":"subtract","result":"metric_range"},
               {"op":"RANK_ROWS","column":"metric_range","direction":"max",
                "return_columns":["key_col","metric_range"]}]
    The AGG list is closed; a percentile is never one of its members.
"""


# ---------------------------------------------------------------------------
# Vocabulary narrowing
# ---------------------------------------------------------------------------
#
# The deterministic router in ``flashfusion.pipeline.operator_router`` decides
# which operators a query could possibly need. Rendering only those entries keeps
# the planner contract intact while cutting the prompt down to the operators that
# survived elimination. Parsing happens once at import time; the render itself is
# a pure filter over pre-split, immutable chunks.

_OPERATOR_HEADER_RE = re.compile(r'^([A-Z][A-Z0-9_]*)\s+\{"op":')
_OPERATOR_MENTION_RE = re.compile(r"[A-Z][A-Z0-9_]{3,}")
#: Lines that start a new rule / example / list item even without a blank line.
_SPEC_ITEM_MARKER_RE = re.compile(r"^(?:[WX]?\d+\.|-\s|\[)")
_SPEC_SECTION_HEADER_RE = re.compile(r"^[A-Z][A-Z0-9 ]{3,}[—:]")


def _spec_chunks(lines: list[str]) -> tuple[str, ...]:
    """Group lines into paragraph/list-item chunks that can be dropped as a unit."""
    chunks: list[str] = []
    current: list[str] = []
    previous_blank = True
    for line in lines:
        starts_chunk = bool(line.strip()) and not line[:1].isspace() and (
            previous_blank or _SPEC_ITEM_MARKER_RE.match(line)
        )
        if current and starts_chunk:
            chunks.append("\n".join(current).rstrip())
            current = [line]
        else:
            current.append(line)
        previous_blank = not line.strip()
    if current:
        chunks.append("\n".join(current).rstrip())
    return tuple(chunk for chunk in chunks if chunk.strip())


def _parse_vocabulary_spec(
    spec: str,
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Split the spec into (head chunks, operator blocks, tail chunks)."""
    lines = spec.split("\n")
    first = next(i for i, line in enumerate(lines) if _OPERATOR_HEADER_RE.match(line))

    end = len(lines)
    for i in range(first + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line[:1].isspace() or _OPERATOR_HEADER_RE.match(line):
            continue
        end = i
        break

    blocks: list[tuple[str, str]] = []
    name = ""
    body: list[str] = []
    for line in lines[first:end]:
        match = _OPERATOR_HEADER_RE.match(line)
        if match:
            if name:
                blocks.append((name, "\n".join(body).rstrip()))
            name, body = match.group(1), [line]
        else:
            body.append(line)
    if name:
        blocks.append((name, "\n".join(body).rstrip()))

    return _spec_chunks(lines[:first]), tuple(blocks), _spec_chunks(lines[end:])


_SPEC_HEAD_CHUNKS, _SPEC_OPERATOR_BLOCKS, _SPEC_TAIL_CHUNKS = _parse_vocabulary_spec(
    OPERATOR_VOCABULARY_SPEC
)


def _mentions_only(chunk: str, candidate_ops: frozenset[str]) -> bool:
    """True when every operator this chunk names is still part of the vocabulary."""
    return all(
        token in candidate_ops
        for token in _OPERATOR_MENTION_RE.findall(chunk)
        if token in _ALL_OPERATOR_NAME_SET
    )


def _drop_empty_sections(sections: list[str]) -> list[str]:
    """Remove section headings whose entire body was filtered away."""
    kept: list[str] = []
    for section in reversed(sections):
        is_header = bool(_SPEC_SECTION_HEADER_RE.match(section))
        if is_header and (not kept or _SPEC_SECTION_HEADER_RE.match(kept[0])):
            continue
        kept.insert(0, section)
    return kept


def build_vocabulary_spec(candidate_ops: Iterable[str]) -> str:
    """Render the operator vocabulary restricted to ``candidate_ops``.

    Rules, worked examples, and rejected patterns that reference an operator the
    planner is no longer allowed to emit are dropped with it: a contract that
    describes operators absent from its own vocabulary invites exactly the
    hallucinated steps Gate 1 exists to reject. Returns the full spec verbatim
    (byte-identical) when nothing was narrowed.
    """
    ops = frozenset(candidate_ops)
    if ops >= _ALL_OPERATOR_NAME_SET:
        return OPERATOR_VOCABULARY_SPEC
    sections = [
        *(chunk for chunk in _SPEC_HEAD_CHUNKS if _mentions_only(chunk, ops)),
        *(block for name, block in _SPEC_OPERATOR_BLOCKS if name in ops),
        *(chunk for chunk in _SPEC_TAIL_CHUNKS if _mentions_only(chunk, ops)),
    ]
    return "\n\n".join(_drop_empty_sections(sections)) + "\n"


def _operator_signature(block: str) -> str:
    """Return only the ``{"op": ...}`` JSON signature lines from an operator block.

    Some signatures (e.g. PARALLEL_AGGREGATE, DERIVE_BIN, DERIVE_DURATION_SECONDS)
    wrap onto a second line before the JSON object closes. Taking a fixed first
    line truncates those mid-object, silently dropping trailing fields (e.g.
    PARALLEL_AGGREGATE's group_by/aggregate/column/result_column) and inviting a
    light model to invent replacements. Track brace depth instead so the full
    signature is kept and usage prose after it is dropped.
    """
    sig_lines: list[str] = []
    depth = 0
    for line in block.split("\n"):
        sig_lines.append(line)
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break
    return "\n".join(sig_lines).strip()


def build_compact_operator_spec(candidate_ops: Iterable[str]) -> str:
    """Field signatures only, in ``candidate_ops`` order — no usage prose or examples.

    ``build_vocabulary_spec`` keeps the full rules/examples prose per operator,
    which is what a planner needs to *choose* operators. Cache grounding never
    chooses operators — the skeleton is already fixed — so all that prose is
    pure noise that a small model can lose the step-count/field-name signal in.
    Only the literal ``{"op": ...}`` signature (see ``_operator_signature``) is
    kept per operator, plus the AGG enum line if any signature references it.
    """
    lookup = dict(_SPEC_OPERATOR_BLOCKS)
    seen: set[str] = set()
    lines: list[str] = []
    for name in candidate_ops:
        if name in seen:
            continue
        seen.add(name)
        block = lookup.get(name)
        if block is None:
            continue
        lines.append(_operator_signature(block))
    spec = "\n".join(lines)
    if "AGG" in spec:
        agg_line = next((chunk for chunk in _SPEC_TAIL_CHUNKS if chunk.startswith("AGG is one of")), "")
        if agg_line:
            spec += "\n\n" + agg_line
    return spec


# ---------------------------------------------------------------------------
# Immutable planner prefix — the prompt-cache prefix
# ---------------------------------------------------------------------------
#
# Everything below is byte-stable for a given OPERATOR_VOCABULARY_VERSION. It is
# sent as the planner's *first* message so that providers with prefix caching can
# reuse it across every query and every dataset. Nothing request-specific may be
# interpolated here — no dataset name, schema text, sample row, timestamp,
# request id or query. The dynamic half lives in
# ``flashfusion.prompts.templates.PLANNER_DYNAMIC_SUFFIX_TEMPLATE`` and is sent
# as a later message.

_PLANNER_ROLE_CONTRACT: str = """\
You are a query planner for a pandas DataFrame named `df` holding sensor /
time-series data. You do two jobs in one response: decide whether the question
is answerable from the schema, and if so emit a typed execution plan.

The dataset schema and the question arrive in a later message. Read the operator
vocabulary below first; it is the COMPLETE set of things you are able to express.\
"""

_PLANNER_SCOPE_RULES: str = """\
SCOPE CHECK
  in_scope = true when the answer can be computed from the columns supplied in
  the later message using aggregation, filtering, grouping, ranking, derived
  arithmetic, correlation, or an in-dataset train/predict procedure the question
  itself specifies.
  in_scope = false when the question needs external data, outside domain
  knowledge, personal attributes absent from the schema, or a forecast whose
  inputs cannot be derived from those columns. Give a one-sentence
  rejection_reason in that case and set plan to null.

PLANNING
  Resolve every concept in the question to a real column name yourself. When a
  qualitative term has no literal column (for example "roughness",
  "turbulence", "instability"), pick the closest real column, and also list the
  term in ambiguous_concepts.
  For in-dataset train/predict requests (chronological train/holdout split with
  a prediction on a holdout row), emit a single-step PREDICTIVE_PIPELINE plan.
  Use only supported model values exactly as listed in the operator vocabulary,
  provide explicit feature_columns from real schema columns, set sort_by from
  the chronological ordering requested, and set holdout_row to first or last.
  Do not emit free-form modeling steps or Python code.
  When the question asks to bucket/group a numeric or datetime column into
  fixed-size intervals against a CONSTANT (e.g. "1-minute intervals", "bins of
  width 10"), use DERIVE_BIN with that column and the constant as `width` —
  NEVER DERIVE_BINARY, whose `left`/`right` fields must always be existing
  column names and never a numeric literal or time constant.
  If the question is in scope but CANNOT be expressed with the operators above,
  set plan to null and list the missing capability in ambiguous_concepts. Do
  not invent an operator, and do not emit Python code.

NO INVENTION
  Every column name you emit must appear verbatim in the schema supplied later,
  or be the `result` name of a DERIVE_* step earlier in the same plan. Never
  fabricate a column, a `*_proxy` stand-in, or an ordinal encoding of a nominal
  label to stand in for a field the schema does not contain. If the metric the
  question asks about is absent, that is a rejection, not a substitution.\
"""


def _planner_scope_rules(*, include_planning_guidance: bool) -> str:
    """Return scope/planning contract text for one planner policy variant."""
    if include_planning_guidance:
        return _PLANNER_SCOPE_RULES

    start_marker = "\nPLANNING\n"
    end_marker = "\nNO INVENTION\n"
    if start_marker not in _PLANNER_SCOPE_RULES or end_marker not in _PLANNER_SCOPE_RULES:
        return _PLANNER_SCOPE_RULES
    prefix, tail = _PLANNER_SCOPE_RULES.split(start_marker, 1)
    _, suffix = tail.split(end_marker, 1)
    return f"{prefix}\nNO INVENTION\n{suffix}"

_PLANNER_OUTPUT_CONTRACT: str = """\
Respond with a single JSON object and nothing else:
{"in_scope": bool,
  "rejection_reason": string or null,
  "ambiguous_concepts": [string, ...],
  "plan": {"version": "1", "steps": [ ...operators... ]} or null}\
"""

def build_planner_prefix(
    vocabulary_spec: str = OPERATOR_VOCABULARY_SPEC,
    *,
    include_planning_guidance: bool = True,
) -> str:
    """Assemble the planner prefix around a (possibly narrowed) vocabulary spec.

    The prefix stays byte-stable *for a given spec*, so prompt caching still
    works — but the cache is now partitioned by operator route instead of being
    a single global entry.
    """
    return "\n\n".join(
        [
            _PLANNER_ROLE_CONTRACT,
            f"PLAN_VERSION: {PLAN_VERSION}\n"
            f"OPERATOR_VOCABULARY_VERSION: {OPERATOR_VOCABULARY_VERSION}",
            "Operator vocabulary (this is the COMPLETE set — nothing else exists):\n"
            + vocabulary_spec,
            _planner_scope_rules(
                include_planning_guidance=include_planning_guidance,
            ),
            _PLANNER_OUTPUT_CONTRACT,
        ]
    )


def planner_prefix_digest(prefix: str) -> str:
    """Full digest of the exact prefix bytes sent to the provider."""
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()


def planner_prefix_version(prefix: str) -> str:
    """Short contract+prefix version, logged so two runs can be compared."""
    return hashlib.sha256(
        "|".join((PLAN_VERSION, OPERATOR_VOCABULARY_VERSION, prefix)).encode("utf-8")
    ).hexdigest()[:16]


FLASH_FUSION_PLANNER_PREFIX: str = build_planner_prefix()

PLANNER_PREFIX_SHA256: str = planner_prefix_digest(FLASH_FUSION_PLANNER_PREFIX)

PLANNER_PREFIX_VERSION: str = planner_prefix_version(FLASH_FUSION_PLANNER_PREFIX)


def planner_cache_key(model_id: str, environment: str = "dev") -> str:
    """Stable prompt-cache / sticky-routing key scoped to this exact prefix.

    Deliberately free of per-query entropy: OpenRouter derives its sticky-routing
    key from the opening messages unless a session key is supplied, so a
    per-request value would defeat the cache it is meant to warm.
    """
    return f"flashfusion:{model_id}:{PLANNER_PREFIX_VERSION}:{environment}"
