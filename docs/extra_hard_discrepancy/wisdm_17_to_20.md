## Query 17

No, **user 23 is incorrect**. 

The code provided in the prompt is `build_ground_truth_mit_ecg` (for the MIT ECG dataset), whereas the benchmark query ran against the **WISDM** dataset (`build_ground_truth_wisdm`). Inspecting how query 17 is computed in the WISDM ground truth builder reveals why user 23 was selected and why that calculation is flawed.

***

### Root Cause in the Ground Truth Builder

In `flashfusion/eval/build_groundtruth/ground_truth_builder.py`, query 17 for WISDM computes the dynamic and resting means using logic equivalent to:

```python
# Intended: filter dynamic vs resting activities
# Flaw: outer join where missing categories get filled with 0.0, or
# an incomplete filter where one branch defaults resting magnitude to 0.0
```

When evaluating subject 23, the calculation assigns a **resting magnitude of 0.0**:
$$\text{resting\_mean\_magnitude} = 0.0$$
$$\text{magnitude\_delta} = 14.393801159315 - 0.0 = 14.393801159315$$

In reality, physical acceleration on an accelerometer cannot have a mean magnitude of zero for a living human performing static activities (sitting/standing on Earth registers approximately $9.8\,\text{m/s}^2$ due to gravity). 

Subject 23 only "won" because their resting magnitude was improperly treated as zero (or dropped/filled with zero), leaving their dynamic magnitude un-subtracted.

***

# WISDM Q17-Q20 discrepancy analysis

## Q17: dynamic-minus-resting magnitude

**Classification:** ground-truth bug plus executor missing-data bug; not a planner failure.

The two per-subject means are measurements. A subject missing one activity family has an undefined comparison, not a measured mean of zero. The old builder and `PARALLEL_AGGREGATE` both outer-joined the branches and filled every missing aggregate with `0.0`. That made subject 23, which has no resting aggregate, appear to have a very large dynamic-minus-resting value. Restricting the comparison to complete pairs with `dropna()` yields subject 24.

The plan shape itself is correct: derive magnitude, independently aggregate the two activity families by `subject_id`, subtract, and rank. ICL cannot repair an executor that rewrites a missing mean to zero. The executor now preserves missing values for non-additive aggregates; only missing `count` and `sum` branch results are zero-filled.

## Q18: variance comparison

No observed winner discrepancy was reported, but it has the same data contract as Q17. Missing variances are now retained as missing and excluded from the paired comparison rather than imputed as zero.

## Q19: Jogging/Walking correlation

**Classification:** ground-truth bug plus executor missing-data bug; not a planning-stage failure.

Subject 9 has Walking rows but no Jogging rows. The old `.fillna(0.0)` introduced an artificial point into the Pearson correlation and produced approximately `0.120499`; pairwise-complete data produces approximately `0.749195`. The builder and staging reference now use `dropna()`.

The earlier note that branch filters were dropped was based on the human-readable code trace, whose formatting omitted a dot before `size()` in count branches. Runtime execution did apply each branch filter. The actual runtime defect was blanket zero imputation after the outer merge.

## Q20: duration comparison

Missing sums remain zero-filled intentionally. Unlike a missing mean or variance, the sum over an absent activity subset represents zero accumulated duration for that subset. No semantic change is required for Q20.

## Resolution

- Ground truth uses complete pairs for Q17-Q19.
- `PARALLEL_AGGREGATE` preserves missing non-additive aggregates.
- The planner contract now states the missing-value policy explicitly. This is a small operator-contract correction, not a new operator or a fundamental expressivity gap.

# Adversarial re-wording strategy (2026-09-15)

After the ground-truth/executor bugs above were fixed, Q18 and Q19 were deliberately reworded to probe the *planner's* correctness rather than the executor's — same underlying question, phrased to make a wrong-but-schema-valid operator chain attractive. Each rewrite targets a specific mechanism, verified against `flashfusion/pipeline/operator_router.py` and/or the `OPERATOR_VOCABULARY_SPEC` planner prompt in `flashfusion/pipeline/operators.py`.

## Q18: router-exclusion trap (signed-difference)

Original wording used explicit comparison/derive vocabulary ("difference", "margin", "exceeds"), which kept the `partition_compare` and `derive` operator buckets in the candidate vocabulary and the planner answered correctly. The rewrite —

> "For every subject_id, compute x-acceleration variance separately while Jogging and while Walking. Return the subject_id for whom Jogging pulls furthest ahead of Walking."

— strips every `COMPARISON_CUES`/`THRESHOLD_CUES`/`DERIVE_CUES` token while keeping `GROUPING_CUES` ("every") and `MULTI_BRANCH_CUES` ("separately"). Confirmed directly against `route_operator_bucket`:

```
excluded= ('correlation', 'derive', 'partition_compare', 'predictive')
candidate_ops= [AGGREGATE_COLUMN, AGGREGATE_GROUPS, COUNT_DISTINCT, COUNT_ROWS, FILTER_COMPARE,
                FILTER_EQ_AGGREGATE, FILTER_IN, FILTER_NOT_EMPTY, GROUP_AGGREGATE, PARALLEL_AGGREGATE,
                RANK_GROUPS, RANK_ROWS, SELECT_COLUMN]
```

`DERIVE_BINARY` and `COMPARE_VALUES` are excluded before the planner LLM ever runs, so it cannot express a signed difference at all and is left to rank by a single raw branch column — a different question, answered with a syntactically valid chain.

## Q19: router-exclusion trap (correlation method) — confirmed live

Rewrite:

> "For every subject_id, compute mean acceleration magnitude while Jogging and while Walking. Report whether subjects who jog harder also walk harder, ranking subjects consistently across both activities."

This avoids every `CORRELATION_CUES` token (`correlat*`, `relationship`, `related`, `associat*`, ...), so `_rule_correlation` excludes the `correlation` bucket and `CORRELATE_COLUMNS` never reaches the planner. Live trace (`python -m flashfusion.eval.trace_query --dataset wisdm --query-id 19`) confirmed the failure mode exactly: the planner produced `FILTER_NOT_EMPTY -> DERIVE_VECTOR_MAGNITUDE -> PARALLEL_AGGREGATE -> RANK_ROWS`, returning the single subject with the highest Jogging magnitude (`subject_id 23`) instead of a correlation coefficient. This is a router-elimination failure, one level earlier and more severe than the originally-intended "planner defaults `method` to pearson instead of spearman" trap — the operator is absent from the candidate vocabulary entirely, not merely mis-parameterized.

The ground-truth reference answer was reworded to lead with the qualitative verdict ("Yes — subjects who jog harder also tend to walk harder: the Spearman rank correlation ... is 0.7038...") so a correct planner run is scored fairly against the literal "report whether" framing of the question.