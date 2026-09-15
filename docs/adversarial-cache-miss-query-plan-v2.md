# Extra-Hard Compositional-Depth Query Plan (v2)

## Revision Note

This plan supersedes IDs 17–20 in `adversarial-cache-miss-query-plan.md`. The prior
four types (direct, intermediate reasoning, out-of-scope, predictive) tested
whether a typed operator was *missing* from the vocabulary in `operators.py`. That
axis is already covered by IDs 1–16, which include out-of-scope and predictive
cases per dataset. IDs 17–20 now test a different, previously unaddressed axis:
whether the planner can correctly hold state across a *long* chain of operators it
already has. Each replacement query composes six to ten operators from the closed
vocabulary:

```
FilterCompare, FilterIn, FilterNotEmpty, FilterEqAggregate, AggregateColumn,
CountRows, CountDistinct, SelectColumn, DeriveBinary, DeriveVectorMagnitude,
DeriveBin, DeriveDurationSeconds, GroupAggregate, AggregateGroups, RankGroups,
RankRows, SplitByThreshold, SplitByValues, AggregatePartitions,
ComparePartitions, CompareValues, CorrelateColumns, ParallelAggregate,
PredictivePipeline
```

No query below invokes an operator outside this list. A wrong answer here isolates
a planning-depth failure — a dropped stage, a stale intermediate value, an early
truncation — rather than a vocabulary gap. Do not carry over the "one direct, one
intermediate, one out-of-scope, one predictive" requirement from the prior 17–20
design; the four slots are now all `extra_hard`, distinguished from each other by
their operator chain rather than by task type.

The cache-miss requirement from the original plan still applies: IDs 17–20 must be
new literal-text prompts absent from both the exact and semantic cache registries.
Verify semantic-registry behavior before interpreting execution as normal planner
fallback, exactly as before.

This revision adds one further constraint from the pilot owner: results generated
for this ablation batch (IDs 17–20 only, across all three baselines) must land in
a dedicated results directory, isolated from the primary IDs 1–16 results tree.
See "Results Storage" below.

## Replacement Candidate Table

| ID | WISDM (operators) | MIT-ECG (operators) | Bus (operators) |
|---|---|---|---|
| 17 | Dynamic-vs-resting magnitude gap, ranked (7) | Top annotated-beat RMS bin per record (8) | Top-decile instability/variance correlation (7) |
| 18 | Jogging/Walking variance-ratio duration split (10) | Median-split annotated-beat range comparison (9) | North/south roughness dual-metric comparison (9) |
| 19 | Top-user-per-activity magnitude correlation (7) | Per-record window-index/beat-count correlation (6) | Top-3 range-bin behavior distribution (9) |
| 20 | Chronological quintile magnitude/user-count ratio (8) | Cross-metric top-5 intersection duration gap (10) | Roughest/smoothest quartile instability ratio (8) |

## Query Definitions

### WISDM

**ID 17** (7 operators): For each user, derive acceleration magnitude, split rows
into a dynamic partition (Walking, Jogging, Upstairs, Downstairs) and a resting
partition (Sitting, Standing), compute each partition's mean magnitude per user,
then compute the per-user difference (dynamic mean minus resting mean). Rank users
by this difference in descending order and report the top-ranked user_id and its
difference value rounded to two decimals.

Chain: `DeriveVectorMagnitude` → `SplitByValues` → `GroupAggregate` (dynamic) →
`GroupAggregate` (resting) → `ComparePartitions` → `RankRows` → `SelectColumn`.

**ID 18** (10 operators): Filter to users with at least 200 Jogging samples. For
each such user, compute the variance of x-acceleration while Jogging and while
Walking. Keep users where the Jogging variance exceeds 1.5 times the Walking
variance. Among the retained users, bin them by whether total Jogging duration is
above or below the dataset-wide median Jogging duration, and report the count of
retained users in each bin.

Chain: `FilterCompare` (activity=Jogging) → `GroupAggregate` (count per user) →
`FilterCompare` (count ≥ 200) → `GroupAggregate` (variance x, Jogging) →
`GroupAggregate` (variance x, Walking) → `ComparePartitions` (ratio > 1.5) →
`DeriveDurationSeconds` → `AggregateColumn` (dataset median duration) →
`DeriveBin` (above/below median) → `GroupAggregate` (count per bin).

The 200-sample floor is 10 seconds of continuous jogging at WISDM's 20 Hz sampling
rate, the shortest window in which a variance estimate is not dominated by a single
stride. The 1.5x threshold separates the effect from typical inter-user variance
noise. State both rationales in the ground-truth script's comments.

**ID 19** (7 operators): Compute the y-acceleration mean for each (user,
activity_label) group with at least 50 samples. Rank groups within each
activity_label by mean descending. Report, for each activity_label, the user_id
ranked first, then compute the correlation between these top users' overall sample
counts and their average x-acceleration magnitude across all activities.

Chain: `FilterEqAggregate` (group size ≥ 50) → `GroupAggregate` (mean y) →
`RankGroups` (within activity_label) → `SelectColumn` (top user per activity) →
`CountRows` (overall samples for selected users) → `DeriveVectorMagnitude` +
`AggregateColumn` (mean magnitude) → `CorrelateColumns`.

**ID 20** (8 operators): Split the WISDM data chronologically by timestamp into 5
equal-sized partitions. Within each partition, compute the mean acceleration
magnitude and the count of distinct users. Rank the partitions by mean magnitude
descending. Compare the highest-ranked partition to the lowest-ranked partition and
report the ratio of their distinct-user counts.

Chain: `DeriveVectorMagnitude` → `SplitByThreshold` (quintile boundaries) →
`AggregatePartitions` (mean magnitude) → `AggregatePartitions` (CountDistinct user)
→ `RankGroups` → `SelectColumn` (top/bottom partitions) → `ComparePartitions`
(ratio) → `SelectColumn` (final value).

### MIT-ECG

**ID 17** (8 operators): For each record_id, filter to rows with non-empty
annotation, then compute the RMS of MLII within 10-second bins (time_s // 10). Rank
the bins within each record by RMS descending, keep the top bin per record, then
rank records by their top-bin RMS descending and report the top record_id and its
top-bin RMS.

Chain: `FilterNotEmpty` → `DeriveBin` (10-second bins) → `DeriveBinary` (square
MLII) → `AggregateColumn` (mean per bin) + `DeriveBinary` (sqrt) → `RankRows`
(within record) → `SelectColumn` (top bin per record) → `RankRows` (across
records) → `SelectColumn` (final record_id and RMS).

**ID 18** (9 operators): For each record_id, compute the difference between max and
min MLII and the count of annotated beats. Split records into two groups by
whether their annotated-beat count is above or below the dataset median. Within
each group, compute the average MLII range. Compare the two group averages and
report which group has the larger range along with the numeric difference.

Chain: `GroupAggregate` (max MLII) → `GroupAggregate` (min MLII) → `DeriveBinary`
(range) → `FilterNotEmpty` (annotation) → `GroupAggregate` (annotated-beat count)
→ `AggregateColumn` (median count) → `DeriveBin` (above/below median) →
`AggregatePartitions` (mean range per group) → `ComparePartitions`.

**ID 19** (6 operators): For record_id 101, bin time_s into 10-second windows,
count annotated beats per window, then compute the correlation between window
index and annotated-beat count across the record's duration. Report the
correlation coefficient rounded to three decimals.

Chain: `FilterCompare` (record_id=101) → `DeriveBin` (10-second windows) →
`FilterNotEmpty` (annotation) → `GroupAggregate` (count per window) →
`SelectColumn` (window index, count) → `CorrelateColumns`.

**ID 20** (10 operators): Across all records, compute each record's MLII variance
and V1 variance. Rank records by MLII variance descending and separately by V1
variance descending. Identify records that fall in the top 5 of both rankings.
Among these overlapping records, compute the average duration (max time_s) and
compare it to the dataset-wide average duration across all records, reporting the
absolute difference.

Chain: `GroupAggregate` (variance MLII) → `RankRows` → `GroupAggregate` (variance
V1) → `RankRows` → `FilterIn` (top 5, MLII) → `FilterIn` (top 5, V1, intersected)
→ `GroupAggregate` (max time_s, intersecting records) → `AggregateColumn` (mean
duration, intersecting) → `AggregateColumn` (mean duration, all records) →
`CompareValues` (absolute difference).

### Bus

**ID 17** (7 operators): Split timestamps into 1-minute bins. For each bin,
compute mean instability_score and mean accel_variance. Rank bins by mean
instability_score descending, keep the top 10% of bins, then within that top
decile compute the correlation between mean accel_variance and mean
instability_score.

Chain: `DeriveBin` (1-minute bins) → `GroupAggregate` (mean instability) →
`GroupAggregate` (mean accel_variance) → `RankRows` (descending instability) →
`SplitByThreshold` (top decile) → `SelectColumn` (retained bins) →
`CorrelateColumns`.

**ID 18** (9 operators): Compute peak acceleration magnitude per row using the
99th-percentile x/y/z columns. Split rows into a northern half (latitude above
median) and a southern half (latitude at or below median). Within each half,
compute the mean peak magnitude and the count of rows where accel_variance
exceeds 0.20. Compare the two halves on both metrics and report which half is
rougher by both criteria, or state disagreement.

Chain: `DeriveVectorMagnitude` (p99 x/y/z) → `SplitByThreshold` (latitude median)
→ `AggregatePartitions` (mean magnitude, north) → `AggregatePartitions` (mean
magnitude, south) → `FilterCompare` (accel_variance > 0.20) →
`AggregatePartitions` (count, north) → `AggregatePartitions` (count, south) →
`ComparePartitions` (magnitude) → `ComparePartitions` (count).

**ID 19** (9 operators): For each 5-minute time bin, compute the range
(accel_stats_z_p99 minus accel_stats_z_p1) and the mean extreme_event_magnitude.
Rank bins by range descending, keep the top 3 bins, then compute the
behavior-label distribution across just those bins, and report the most frequent
behavior label among them.

Chain: `DeriveBin` (5-minute bins) → `DeriveBinary` (z_p99 − z_p1) →
`GroupAggregate` (mean range per bin) → `GroupAggregate` (mean
extreme_event_magnitude) → `RankRows` (descending range) → `FilterIn` (top 3
bins) → `GroupAggregate` (count by behavior) → `RankGroups` (descending count) →
`SelectColumn` (most frequent label).

**ID 20** (8 operators): Compute per-minute mean accel_mean and mean
accel_variance. Split minutes into quartiles by mean accel_variance. Within the
top quartile (roughest) and bottom quartile (smoothest), compute the average
instability_score. Compare the two quartile averages and report the ratio of
roughest to smoothest instability_score, rounded to two decimals.

Chain: `DeriveBin` (per-minute) → `GroupAggregate` (mean accel_mean) →
`GroupAggregate` (mean accel_variance) → `SplitByThreshold` (quartile cutoffs) →
`AggregatePartitions` (mean instability, top quartile) → `AggregatePartitions`
(mean instability, bottom quartile) → `ComparePartitions` (ratio) →
`SelectColumn` (final rounded value).

## Critique Findings (Updated)

The original critique — that a prompt guarantees neither Flash-Fusion nor ReAct
failure — still holds and applies more strongly here, since every operator in
these chains already exists. A ReAct agent with arbitrary Python execution should
be able to reconstruct any of these chains from first principles; a correct ReAct
answer on IDs 17–20 is not itself evidence of a benchmark flaw, because these
queries are not adversarial to ReAct by design. The adversarial target is
Flash-Fusion's typed planner: a planner that greedily matches operators to
sub-clauses of a long natural-language instruction is more likely to truncate the
plan, reorder a comparison before its inputs are ready, or silently drop a
partition boundary than a planner solving a four-operator query. Treat a stable,
correct ReAct pass alongside a Flash-Fusion failure that reproduces across three
runs as a valid finding; treat a Flash-Fusion pass that matches ground truth by
coincidence (wrong intermediate values, right final rounding) as a false pass and
exclude it — this is why per-stage logging in the scoring section below is
mandatory, not optional.

## Scoring and Ground Truth

Carry over all requirements from the original plan: append entries 17–20 to each
`ground_truth_*.json` before any scored run, generate references in a separate
versioned script with pinned package versions, and record sort order, tie-break
rule, and rounding precision (tolerance no wider than \(10^{-4}\) for correlation
coefficients and ratios).

Add one requirement specific to compositional depth: log the intermediate result
after every operator in the chain, not only the final scalar. Store this as a
`stage_trace` list alongside each ground-truth entry, keyed by operator name and
position (e.g., `stage_2_GroupAggregate_dynamic_mean`). This lets the post-judge
verifier attribute a wrong final answer to the specific stage that diverged,
rather than scoring the entire query pass/fail with no diagnostic value.

### Implemented Ground-Truth Generator

`flashfusion/eval/build_groundtruth/ground_truth_builder.py` computes the
canonical references for all IDs 1--20. The extra-hard staging harnesses under
`flashfusion/eval/build_groundtruth/trace/` validate the typed plans against
independent pandas calculations before query promotion. Regenerate the complete
canonical ground-truth JSON once per dataset before benchmarking:

```sh
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
```

## Paraphrase Generation: v2 and v3

Generate paraphrased versions of the four new queries per dataset (12 base
queries total) into `queries_v2.py` and `queries_v3.py`, following the existing
file structure and `DATASET_WISDM` / `DATASET_MIT_ECG` / `DATASET_BUS` constants
already used in `queries.py`. Instruct the generating model to:

1. Preserve every numeric threshold, column name, entity ID, and tie-break rule
   exactly. A paraphrase that rounds 1.5x to "one and a half times" is acceptable;
   a paraphrase that drops the 200-sample floor or the 0.20 accel_variance cutoff
   invalidates the ground-truth match and must be rejected.
2. Vary sentence structure, clause order, and phrasing of the operator sequence
   (e.g., restate "split into a dynamic partition and a resting partition" as
   "separate dynamic activities from resting activities") without collapsing or
   adding intermediate steps. The v2/v3 text must imply the same operator count
   and the same operator sequence as the v1 query it paraphrases.
3. Confirm each paraphrase is a literal-text miss against both the exact and
   semantic cache registries independently of its v1 counterpart. A paraphrase
   that the semantic registry maps to the v1 entry is a semantic-cache hit by
   design and should be labeled as such, not treated as a planner execution.
4. Reuse the identical ground-truth reference and `stage_trace` from the v1
   entry for scoring; the paraphrase must produce the same final answer and the
   same intermediate values at every stage, since the underlying computation is
   unchanged.
5. Keep IDs consistent across files: `queries.py`, `queries_v2.py`, and
   `queries_v3.py` each define IDs 17–20 for all three datasets, so scripts that
   iterate by ID across files stay aligned.

Do not generate v2/v3 paraphrases for IDs 1–16 as part of this change unless a
separate task requests it; scope this paraphrase pass to the 12 replacement
queries only.

## Operator Skeleton Generation Plan

Before treating any of the 36 prompts (12 base queries × 3 phrasing versions) as
admitted, run the production Flash-Fusion planner against each one through
`build_operator_skeleton_cache.py` to generate the operator skeleton the planner
actually selects, independent of the eval harness. This validates the planner's
real behavior on these prompts, not just the ground-truth intent recorded above.

1. For each of the 36 prompts, invoke the planner in skeleton-generation mode and
   capture the emitted operator sequence, its length, and any discriminator
   values chosen by the `TypedOperator` union (e.g., which `op` field each stage
   resolved to).
2. Compare the emitted sequence against the intended chain documented in this
   plan for that query's base ID. A match requires the same operator count and
   the same operator identities in the same order; a semantically equivalent but
   reordered chain (e.g., computing the resting partition before the dynamic
   partition) is acceptable only if the final `stage_trace` values are identical,
   since operator order can be commutative for some stages but not for
   `ComparePartitions` or `CorrelateColumns`, which depend on both inputs already
   being resolved.
3. Reject and revise any query where the planner's real skeleton has fewer than
   six or more than ten operators, since that means the planner is not exercising
   the intended compositional-depth range regardless of what the prompt asks for.
4. Only after a skeleton passes step 2 and 3, register it in the operator-skeleton
   cache registry alongside its dataset and query ID, tagged as validated. Do not
   register a skeleton produced during a run that also produced a wrong final
   answer; a validated skeleton with an incorrect execution means the plan
   structure is right but a stage's implementation is wrong, and it must be fixed
   before caching, not cached as-is.
5. Re-run skeleton generation independently for the v2 and v3 paraphrases from
   the prior section. A paraphrase that produces a different operator skeleton
   than its v1 counterpart is a planning-robustness failure in its own right and
   should be recorded as a distinct finding, separate from whether either
   skeleton's final answer is correct.
6. Store the full set of validated skeletons (v1, v2, v3 × 4 queries × 3
   datasets = 36 entries) as a versioned artifact alongside the ground-truth
   JSON files, so a future re-run of `queryaccuracy.py` can cross-check observed
   traces against both the ground-truth answer and the validated skeleton shape.

## Results Storage

All results generated while running IDs 17–20 across the three baselines
(`FLASH_FUSION`, `FLASH_FUSION_CACHE`, `REACT`) go under a dedicated directory,
separate from the primary IDs 1–16 results tree at
`flashfusion/results/ff_hybrid_cache/`:

```
results/ff_ablation_react_accuracy/
  FLASH_FUSION/
    wisdm/{17,18,19,20}_{v1,v2,v3}.json
    mit_ecg/{17,18,19,20}_{v1,v2,v3}.json
    bus/{17,18,19,20}_{v1,v2,v3}.json
  FLASH_FUSION_CACHE/
    wisdm/... mit_ecg/... bus/...
  REACT/
    wisdm/... mit_ecg/... bus/...
```

Each per-query file holds the raw trace, the judge output, the execution path
(cache hit/miss, planner fallback, or ReAct tool trace), and the `stage_trace`
comparison against ground truth for that run. Isolating this batch under
`results/ff_ablation_react_accuracy/` keeps the compositional-depth ablation from
mixing into the established IDs 1–16 baselines, so a regression here cannot be
averaged away against IDs 1–16 in the aggregate accuracy figure, and the primary
results tree stays reproducible without rerunning this ablation.

Point every run script and reporting step at this directory for this batch only.
Do not write IDs 1–16 output here, and do not write IDs 17–20 output to
`flashfusion/results/ff_hybrid_cache/`.

## Pilot Protocol (Revised)

1. Confirm IDs 17–20 (all three phrasing versions) are absent from exact and
   semantic cache registries.
2. Generate and independently validate all ground-truth references and
   `stage_trace` values for the 12 base queries.
3. Generate v2 and v3 paraphrases per the section above and validate their
   cache-miss status and ground-truth equivalence.
4. Run the operator-skeleton generation plan for all 36 prompts and register only
   validated skeletons.
5. Run each of the 36 prompts three times for `FLASH_FUSION_CACHE`,
   `FLASH_FUSION`, and `REACT`, writing all output under
   `results/ff_ablation_react_accuracy/<BASELINE>/<dataset>/`; retain raw traces,
   judge outputs, execution paths, and per-stage results.
6. Admit a query-version pair only if its answer, execution-path behavior, and
   operator skeleton are stable across the three runs.
7. Re-run `queryaccuracy.py` against `results/ff_ablation_react_accuracy/` and
   report results by dataset, query ID, and phrasing version, including
   cache-hit/miss counts and skeleton-match rate, as a report distinct from the
   primary IDs 1–16 accuracy summary.

## Accuracy Arithmetic (Revised)

Because IDs 17–20 no longer split into direct/intermediate/out_of_scope/
predictive buckets, drop the original bucket-imbalance argument for this range
and report it as a single `extra_hard_composition` bucket of four queries per
dataset, twelve queries total across datasets, and thirty-six across phrasing
versions. One failed query within a single dataset's four-query
`extra_hard_composition` bucket gives \(3/4 = 75\%\), not the 90%+ target
inherited from other buckets. State explicitly in the results report whether the
90%+ target applies per bucket or only to the full 20-query per-dataset total,
since a single bucket at 75% and an aggregate at 95% are both true
simultaneously and must not be conflated.

## Reproduction Commands

Generate the ablation batch results into the dedicated directory:

```sh
python run_ff_react_operators.sh \
  --query-ids 17,18,19,20 \
  --query-versions v1,v2,v3 \
  --baselines FLASH_FUSION,FLASH_FUSION_CACHE,REACT \
  --results-root results/ff_ablation_react_accuracy
```

Regenerate the query-type report scoped to this batch, keeping it separate from
the primary IDs 1–16 summary:

```sh
python queryaccuracy.py \
  --results-root results/ff_ablation_react_accuracy \
  --output ../../results/primary_visualizations/accuracy_by_dataset_query_type_summary_ablation.csv
```

The primary reproduction command for IDs 1–16 is unchanged and still reads from
`flashfusion/results/ff_hybrid_cache/FLASH_FUSION_CACHE`:

```sh
python queryaccuracy.py \
  --results-root flashfusion/results/ff_hybrid_cache/FLASH_FUSION_CACHE \
  --output ../../results/primary_visualizations/accuracy_by_dataset_query_type_summary.csv
```
