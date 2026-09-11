# Flash-Fusion ECG Q5, Q6, and Q14: Sanity Checklist and Defensive Change Plan

## Role and operating rules

You are reviewing the `kpatherya/flash-fusion` repository. **Do not change any file yet.** First scan the repository, verify every checklist item below against the current implementation and benchmark artifacts, and then prepare a minimal, defensive implementation plan.

Treat the following as hypotheses to verify, not established facts. Do not claim a cause unless you can cite the exact file path, symbol, and relevant line range. If the implementation differs from this prompt, explain the discrepancy and adjust the plan to the actual code.

The target failures are ECG benchmark queries 5, 6, and 14 from:

- `flashfusion/results/ff_and_react_qwen/FLASH_FUSION/`
- Dataset/report paths may use `ecg` or `mit_ecg`; discover the exact active paths rather than assuming one.

The required outcome is that all three queries complete with the correct answer **and** that the judge receives a valid, faithful execution artifact. Do not solve this by weakening the judge to accept invalid or mismatched code.

## Target behavior

### Q5: average annotated rows per 60-second bin

Expected answer: `98.06451612903226` (display rounding is acceptable if the evaluator permits it).

Intended typed plan shape:

```text
FILTER_COMPARE(record_id == 208)
FILTER_NOT_EMPTY(annotation)
DERIVE_BIN(time_s, 60 seconds)
GROUP_AGGREGATE(count by time_bin_60s)
AGGREGATE_GROUPS(mean)
```

The judge-reported candidate code ended with `result = grouped.mean()` even though `grouped` was undefined. Verify whether this was produced by a typed-operator-to-code renderer, result serializer, ReAct trace formatter, or another reporting path.

### Q6: greatest MLII peak-to-peak range

Expected answer: record `116`, range `10.235`.

Intended semantics:

```text
for each record_id:
    MLII_range = max(MLII) - min(MLII)
return row with maximum MLII_range
```

The judge-reported candidate code used `max_MLII - abs(min_MLII)`. Verify whether this expression originated in code rendering/serialization or in the executed typed plan. `difference` must serialize and execute as `left - right`; `abs_difference` may apply absolute value only to the completed difference, if that is its defined semantic.

### Q14: chronological random-forest prediction

Expected result: annotation prediction `0` for the first chronological holdout row after filtering `record_id == 101`, sorting by `time_s`, and using the first 80% for training with `MLII` and `V1` features.

The failure report shows a 90-second timeout, followed by ReAct fallback. Verify the actual model configuration, dataset/train-split size, timeout owner, typed execution status, and fallback path. Do not assume that the prompt template itself controls random-forest hyperparameters.

## Files and symbols to inspect

Start with these files, then follow call sites, data models, tests, evaluation writers, and judge inputs as needed:

- `flashfusion/pipeline/operators.py`
  - Typed operator definitions, parsing/validation, and execution dispatch.
  - `FILTER_COMPARE`, `FILTER_NOT_EMPTY`, `DERIVE_BIN`, `GROUP_AGGREGATE`, `AGGREGATE_GROUPS`.
  - `PARALLEL_AGGREGATE`, `DERIVE_BINARY`, `RANK_ROWS`.
  - `PREDICTIVE_PIPELINE` and the `random_forest` implementation.
- `flashfusion/prompts/templates.py`
  - The exact typed-plan schema and enum definitions for `<mode>`, `<dir>`, and `<predictive_model>`.
- All code that produces any of the following fields or equivalent names:
  - `candidate_code`
  - `candidate_answer`
  - `candidate_executed`
  - operator traces / typed-plan traces
  - run CSV or JSON result rows
  - markdown reports
  - judge prompts and judge inputs
- The evaluator/judge code that interprets `candidate_code`, candidate answers, and execution status.
- Existing unit/integration/regression tests for typed operators, reporting, evaluation, and predictive pipelines.
- The target result files/reports for Q5, Q6, and Q14, plus one known-good typed-pipeline ECG run if available.

Use repository search to locate the true renderer/serializer. Do not assume it resides in `operators.py` merely because typed execution resides there.

## Validation checklist

### A. Establish the actual data flow

- [ ] Trace a typed plan from LLM output through validation, typed execution, answer formatting, persisted result row, and LLM-judge input.
- [ ] Identify the canonical source of truth for the executed typed plan and result.
- [ ] Identify the precise source of `candidate_code` used by the judge.
- [ ] State whether `candidate_code` is generated deterministically, LLM-generated, reconstructed after execution, or copied from a ReAct/fallback trace.
- [ ] Verify whether the code rendered for a typed execution is actually executed anywhere before persistence.
- [ ] Verify whether a typed plan can execute successfully while its rendered `candidate_code` is syntactically invalid or semantically different.
- [ ] Map which code paths are used in the `typed_operator` path versus the `react_fallback` path.

### B. Q5 semantic and provenance checks

- [ ] Locate Q5’s actual plan and persisted output/traces in the target run artifacts.
- [ ] Confirm that the typed execution filtered `record_id == 208`.
- [ ] Confirm that “non-empty annotation” excludes nulls and whitespace-only strings.
- [ ] Confirm that the binning expression corresponds to 60-second bins.
- [ ] Confirm that the group aggregation produces counts per bin and the final aggregation takes their mean.
- [ ] Determine whether `grouped` exists in the actual executed computation.
- [ ] Locate the transformation that emitted `grouped.mean()`.
- [ ] Confirm whether the rendered artifact, if executed on the same input, raises an exception or produces the typed-execution result.

### C. Q6 semantic and provenance checks

- [ ] Locate Q6’s actual plan and persisted output/traces in the target run artifacts.
- [ ] Confirm whether the executed typed plan uses `mode="difference"`, `mode="abs_difference"`, or another mode.
- [ ] Confirm the documented and implemented semantics of each mode.
- [ ] Confirm that Q6 computes a range as `max(MLII) - min(MLII)` for every `record_id`.
- [ ] Confirm that the ranking direction is maximum range.
- [ ] Locate the exact code/renderer rule that emitted `max_MLII - abs(min_MLII)`.
- [ ] Determine whether that bad expression was only an explanatory rendering defect or was executed.
- [ ] Verify that record `116` with `10.235` comes from the true range calculation, not from stale state, hard-coded data, or a coincidence.

### D. Renderer/serializer invariants

- [ ] Determine whether the typed-plan renderer has a formal mapping for every operator and mode.
- [ ] Check whether intermediate variable names are declared once, preserved consistently, and referenced only after definition.
- [ ] Check whether branch outputs from `PARALLEL_AGGREGATE` retain stable names through merge/join and subsequent derivations.
- [ ] Check whether code generation can mutate an operator’s arithmetic semantics.
- [ ] Check whether rendered code can silently diverge from the canonical typed plan because of fallback, string substitution, LLM post-processing, or result formatting.
- [ ] Check whether `candidate_code` is a required judge input. If it is optional/explanatory, identify how that contract is represented.
- [ ] Propose the narrowest enforceable invariant: a judge-facing rendered program/trace must be derived from the canonical executed typed plan and must be syntactically valid and result-equivalent on the same input.

### E. Q14 performance and determinism checks

- [ ] Locate the `PREDICTIVE_PIPELINE` branch for `random_forest` and record its exact current hyperparameters.
- [ ] Identify library versions and estimator class actually used.
- [ ] Verify preprocessing: null handling, feature conversion, target creation from `target_from_non_empty`, sort, filter, chronological split, and holdout-row selection.
- [ ] Measure or calculate the input row count after `record_id == 101`, the 80% training size, feature count, class distribution, and whether duplicates/invalid values inflate training work.
- [ ] Identify the precise 90-second timeout source and whether it covers only model fit or the entire agent/query path.
- [ ] Verify why the timeout causes `react_fallback` and whether the fallback retries the same expensive operation.
- [ ] Locate existing benchmark configurations or tests that demonstrate a random forest completing within the budget on comparable data.
- [ ] Test candidate configurations only after confirming the current baseline. Preserve `random_state` and verify that each candidate returns Q14’s required first-holdout prediction `0`.
- [ ] Compare at least these bounded configurations, unless repository conventions justify different values:

```python
# candidate A: smallest conventional bound
RandomForestClassifier(
    n_estimators=32,
    max_depth=10,
    min_samples_leaf=10,
    max_features="sqrt",
    random_state=PREDICTIVE_RANDOM_SEED,
    n_jobs=-1,
)

# candidate B: if A changes the expected prediction or has inadequate margin
RandomForestClassifier(
    n_estimators=64,
    max_depth=12,
    min_samples_leaf=5,
    max_features="sqrt",
    random_state=PREDICTIVE_RANDOM_SEED,
    n_jobs=-1,
)
```

- [ ] Do not introduce a silent model-type substitution as the normal behavior for `random_forest`.
- [ ] If a timeout guard is needed, make it explicit, observable, and testable. It must not report a random-forest result if it actually used a different model.

### F. Judge boundary checks

- [ ] Confirm whether the judge is correctly rejecting Q5 due to undefined `grouped` and Q6 due to the invalid range expression.
- [ ] Do not recommend a blanket judge rule such as “pass whenever the final answer equals reference,” because that would accept unsupported guesses or stale results.
- [ ] If judge changes are necessary, limit them to consuming a canonical structured execution certificate/typed-plan trace rather than a lossy pseudo-code string.
- [ ] Ensure any judge change preserves failure when the executed plan is invalid, unavailable, contradictory, or does not produce the candidate answer.

## Defensive remediation requirements

After the checks are complete, prepare a plan that satisfies all of the following:

1. **One canonical representation.** Typed execution and judge-facing provenance must originate from the same validated typed plan. Avoid separately generated LLM/pseudo-Pandas code for typed runs.
2. **Deterministic rendering.** If source-like code is still needed, render it using deterministic per-operator templates driven by validated operator fields; do not ask an LLM to reconstruct it.
3. **Mode-safe arithmetic.** Define a single mapping for arithmetic modes and use it for execution and rendering. In particular, `difference(a, b)` is `a - b`; it is not `a - abs(b)`.
4. **Stable intermediate names.** The renderer must construct a symbol table or use compositional expressions so every referenced variable is defined in the emitted artifact.
5. **Equivalence gate.** Before persisting judge-facing source-like code, validate that it parses/executes in a constrained environment and produces a normalized result equivalent to canonical typed execution. If that validation cannot be run safely, persist a structured typed-plan certificate instead of unverified code.
6. **No hidden fallback.** Distinguish `typed_operator` success, rendering/provenance failure, and `react_fallback` in result metadata. Do not overwrite a successful typed result with a misleading fallback artifact.
7. **Bounded RF policy.** Put random-forest compute parameters in a named, documented configuration owned by the predictive operator—not in an LLM prompt unless the system deliberately supports validated per-plan resource settings.
8. **Determinism.** Preserve a fixed seed and establish repeatable behavior across benchmark runs.
9. **Minimal scope.** Avoid unrelated refactors, new query-ID special cases, hard-coded expected answers, or global judge leniency.

## Required tests

Specify exact test files/functions to add or extend. The plan must include these tests or repository-equivalent tests:

### Renderer unit tests

- Q5-shaped typed plan renders without undefined variables and evaluates to the same normalized result as typed execution.
- Q6-shaped parallel aggregate with `mode="difference"` renders `max - min`, never `max - abs(min)`.
- A plan with `mode="abs_difference"` renders the repository’s documented absolute-difference semantics distinctly from `difference`.
- Rendering fails closed or emits a structured certificate if a referenced intermediate symbol is missing.

### Execution/provenance integration tests

- A typed run records a canonical plan, execution result, and judge-facing artifact that agree.
- A deliberately corrupted renderer output is rejected before persistence or marked as provenance failure; it must not be sent to the judge as valid executable code.
- A successful typed execution remains classified as `typed_operator`; it does not trigger ReAct merely due to report rendering.

### ECG regression tests

- Q5 returns `98.06451612903226` (or the evaluator’s accepted precision) with valid provenance.
- Q6 returns `record_id == 116` and `MLII_range == 10.235` with valid provenance.
- Q14 completes inside the configured query budget and predicts `0` for the first chronological holdout row under the selected bounded RF configuration.
- Run each regression at least twice and assert equal output with the fixed seed.

### Performance test

- Record training rows, estimator parameters, fit/predict wall time, and total query time for Q14.
- Assert a conservative margin below the 90-second outer timeout; do not define success as merely 89.9 seconds.
- Keep this test hardware-aware if the existing test suite cannot make universal wall-clock guarantees; still provide a reproducible benchmark command and an expected timing envelope for the evaluation environment.

## Required final deliverable

Return a **defensive change plan only**—not a code patch—using this structure:

1. **Evidence table**
   - Finding
   - Exact file path and symbol/line range
   - Evidence from Q5/Q6/Q14 artifacts
   - Confidence and unresolved uncertainty

2. **Root-cause decision**
   - State separately for Q5, Q6, and Q14 whether the hypothesis is confirmed, disproven, or partially confirmed.
   - Clearly distinguish execution bugs from serialization/reporting bugs and timeout/fallback behavior.

3. **Minimal patch plan**
   - Ordered file-by-file changes.
   - Explain the data contract for the canonical typed-plan/provenance representation.
   - Specify the selected RF parameters and why they meet the budget based on measured evidence.
   - Include a rollback or feature-flag approach only if the repository already has an appropriate configuration mechanism.

4. **Test plan**
   - Exact tests, fixtures, commands, expected outputs, and performance acceptance criteria.

5. **Risk review**
   - Backward compatibility of saved result formats.
   - Implications for ReAct fallback and judging.
   - Determinism, resource usage, and benchmark comparability.

6. **No-go conditions**
   - List the observations that would block implementation or require a revised plan, such as the candidate code not actually being judge input, Q6’s executed plan also being wrong, or the bounded RF changing Q14’s required prediction.

Do not propose implementation until you have completed the checks and can support each proposed modification with repository evidence.