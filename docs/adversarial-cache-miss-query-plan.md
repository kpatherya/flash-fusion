# Superseded: Adversarial Cache-Miss Query Plan

> Superseded by `docs/adversarial-cache-miss-query-plan-v2.md`. IDs 17--20 are
> now an `extra_hard` compositional-depth ablation rather than four
> operator-vocabulary-gap queries. Follow the v2 plan for prompt definitions,
> result isolation, scoring, and execution.

## Objective

Extend each dataset from 16 to 20 benchmark queries by adding IDs 17--20:
one direct, one intermediate reasoning, one out-of-scope, and one predictive
prompt. The additions are literal-text cache misses and exercise capabilities
outside Flash-Fusion's closed typed operator vocabulary.

The additions must not be represented in either exact or semantic cache
registries. The cache uses dataset-scoped literal equality, so a new prompt
string is sufficient for an exact miss. Verify semantic-registry behavior too
before interpreting an execution as a planner fallback.

## Candidate Queries

| ID | Type | WISDM | MIT-ECG | Bus | Intended typed gap |
|---|---|---|---|---|---|
| 17 | Direct | Lag-1 x autocorrelation | Ljung-Box p-value | Durbin-Watson statistic | Serial statistic or hypothesis test |
| 18 | Reasoning | Grouped magnitude autocorrelation | Annotated-beat MLII-difference autocorrelation | Fully specified CUSUM detector | Grouped sequence transformation or recurrence |
| 19 | Out-of-scope | Future fall-risk probability | One-year sudden-death probability | Future passenger-injury probability | Missing future outcomes and risk labels |
| 20 | Predictive | Isotonic-calibrated logistic probability | Isotonic-calibrated forest probability | Isotonic-calibrated HGB probability | Calibration, temporal CV, and probability output |

The final prompt text and all tie-breaking, sorting, target, and estimator
details live in `flashfusion/eval/queries.py` so that the benchmark has one
authoritative query definition.

## Critique Findings

An independent critique established that the prompts guarantee neither
Flash-Fusion nor ReAct failure. They ensure an exact-cache miss and expose
absent typed operators, but a ReAct agent has arbitrary Python execution and
may implement serial statistics, CUSUM, or calibrated scikit-learn models.
Out-of-scope prompts should be correctly rejected and therefore can increase,
not lower, Flash-Fusion accuracy.

Do not claim target accuracy before the pilot. A result is a valid adversarial
failure only when the judged output fails against complete, independently
computed ground truth and the run trace confirms a cache miss plus normal
Flash-Fusion planning/fallback path.

## Scoring And Ground Truth

Before any scored run, append entries 17--20 to each corresponding
`ground_truth_*.json` file. Each entry must exactly match the query text and
include a deterministic reference answer. Generate in-scope references in a
separate, versioned script using pinned package versions and record:

- Sort order, missing-value handling, tie break, random seed, package version,
  and all estimator/calibration parameters.
- Scalar values rounded only for display, with an acceptance tolerance no wider
  than $10^{-4}$ for p-values and probabilities.
- Expected rejections for ID 19 that explicitly name the absent fields.

The current prose-only LLM-judge format is too permissive to establish a
calibrated probability or p-value result. Add structured numeric assertions or
a deterministic post-judge verifier before treating those rows as evidence.

## Pilot Protocol

1. Confirm IDs 17--20 are absent from exact and semantic registries.
2. Generate and independently validate all 12 ground-truth references.
3. Run each candidate three times for `FLASH_FUSION_CACHE`, `FLASH_FUSION`,
   and `REACT`; retain raw traces, judge outputs, execution paths, and package
   availability.
4. Admit a query only if its answer and execution-path behavior are stable
   across runs. Replace candidates that ReAct solves reliably rather than
   relabeling correct output as failure.
5. Re-run `queryaccuracy.py` on the admitted suite and report results by
   dataset and query type, including cache-hit/miss counts.

## Accuracy Arithmetic

Adding exactly one query to every type changes every per-dataset type bucket
from four to five queries. One failed query in such a bucket gives
$4/5 = 80\%$, not approximately $90\%$. A single failure among all 20 queries
in one dataset gives $19/20 = 95\%$ overall. Therefore the requirements
"one failure per category" and "90%+ per-category accuracy" cannot both hold.
Choose the reporting target before drawing conclusions from the new suite.

## Reproduction Command

After ground truth is complete and the pilot admits the prompts, run the
benchmark using the existing data-path policy and then regenerate the query
type report:

```sh
python queryaccuracy.py \
  --results-root flashfusion/results/ff_hybrid_cache/FLASH_FUSION_CACHE \
  --output ../../results/primary_visualizations/accuracy_by_dataset_query_type_summary.csv
```