# Bus Q17-Q20 discrepancy analysis

## Q20: quartile instability ratio

**Classification:** benchmark construction and artifact-synchronization failure, not evidence that both baselines independently failed the same valid task.

The canonical query asked for a multi-stage calculation:

1. Aggregate `accel_mean` and `accel_variance` per minute.
2. Compute quartiles over the derived per-minute variance.
3. Select top and bottom quartiles.
4. Aggregate `instability_score` within those selected minute sets.
5. Return a ratio rounded to two decimals.

The ground-truth builder did none of those operations. Its Q20 code instead derived `vertical_shock`, filtered aggressive rows, grouped into five-minute windows, and ranked the highest mean. Thus the query text and reference answer described different questions. Neither baseline could match that reference by correctly answering the visible query.

The quartile query also exceeds the current closed typed vocabulary. `GROUP_AGGREGATE` creates an internal series consumable only by `RANK_GROUPS` or `AGGREGATE_GROUPS`; it cannot materialize multiple per-minute metrics for a later quartile split. `SPLIT_BY_THRESHOLD` supports mean, median, min, and max, but not quartiles. Flash-Fusion should therefore return `plan: null` for that wording. ReAct can write the pandas operations, but the intended quartile convention (`qcut` versus numeric quantile boundaries and tie handling) still needs to be specified in ground truth.

## Resolution

Q20 is restored to the already validated typed-compatible query: derive vertical shock range, filter aggressive behavior, aggregate in five-minute windows, and return the highest-mean window. This matches the existing builder and staging harness. It tests composition without requiring an unsupported quartile operator.

If quartile analysis is desired as a future benchmark, add a typed quantile/partition operator first and specify boundary and tie semantics before generating its reference answer.

## Other queries

No discrepancy was identified for bus Q17-Q19.

# Adversarial re-wording strategy (2026-09-15)

Q18 and Q19 were deliberately reworded to probe two loopholes in the planner's own instruction set (`OPERATOR_VOCABULARY_SPEC` in `flashfusion/pipeline/operators.py`), rather than the zero-LLM router used for the WISDM/MIT_ECG rewrites. Both loopholes are cases where the spec disambiguates plan *shape* using a lexical cue instead of a structural check, so a query can satisfy the letter of the rule while still routing to the wrong operator chain. Neither rewrite changed the underlying correct answer, so the ground-truth computation for Q18/Q19 in `ground_truth_builder.py` is unchanged — only `query_text` was updated and the JSON regenerated.

## Q18: entity-heuristic trap

Rule R2 ("PER-ENTITY COMPARISON") triggers `PARALLEL_AGGREGATE` purely on the lexical phrase "for each X"/"per X", without checking whether `X` names a real coarse categorical key. BUS has no subject/device entity, but does expose continuous numeric `latitude`/`longitude` columns. The rewrite —

> "For each recorded latitude reading, derive peak acceleration magnitude from accel_stats_x_p99, accel_stats_y_p99, and accel_stats_z_p99. Report the absolute difference between the mean peak magnitude north versus south of the median latitude."

— uses "for each recorded latitude reading" as R2 bait. `PARALLEL_AGGREGATE(group_by=["latitude"])` is schema-valid (real column, non-empty `group_by`) but groups by near-unique row values instead of the intended two-way north/south split — passing both gates while answering a structurally different question. Correct chain remains `SPLIT_BY_THRESHOLD` + `AGGREGATE_PARTITIONS` + `COMPARE_PARTITIONS` on the median latitude (rule R1).

## Q19: pooled-vs-windowed-mean trap

The spec acknowledges that `PARALLEL_AGGREGATE` reduced via `AGGREGATE_COLUMN`x2 + `COMPARE_VALUES` ("mean-of-per-entity-means") is a *different number* from `SPLIT_BY_VALUES` + `AGGREGATE_PARTITIONS` + `COMPARE_PARTITIONS` (pooled per-row mean) — but only in a soft `NOTE`, not a numbered hard rule. The rewrite —

> "For each 5-minute timestamp window, derive the vertical shock range as accel_stats_z_p99 minus accel_stats_z_p1 and compute its mean separately for aggressive and calm behavior labels. Report the overall aggressive-minus-calm difference across the route."

— adds "for each 5-minute timestamp window" and "separately", which mirrors `PARALLEL_AGGREGATE`'s own docstring language ("independently filtered subsets", "separately"), while still asking for the "overall ... difference across the route" (R1's pooled framing). A planner that follows the windowing bait produces `DERIVE_BIN -> PARALLEL_AGGREGATE(group_by=["window"]) -> AGGREGATE_COLUMN x2 -> COMPARE_VALUES`, a mean-of-window-means that is generally biased relative to the pooled per-row mean whenever aggressive/calm rows are unevenly distributed across windows (Simpson's-paradox-style discrepancy) — both plans are structurally and schema valid; only one matches the ground-truth convention used across the rest of the benchmark.
