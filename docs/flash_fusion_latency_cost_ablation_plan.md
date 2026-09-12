# Flash-Fusion Latency and Cost Ablation Plan

Status: Planned experiment; no behavior changes in this document

## Decision

Measure the following four policies on the same benchmark queries, datasets,
repetitions, models, and retry settings:

| Code | Display label | Cache | Pruned vocabulary | Planner chaining guidance/examples |
| --- | --- | --- | --- | --- |
| `FLASH_FUSION` | Flash-Fusion | enabled | enabled | enabled |
| `FLASH_FUSION_NO_CACHE` | Flash-Fusion (-cache) | disabled | enabled | enabled |
| `FLASH_FUSION_NO_CACHE_NO_PRUNING` | Flash-Fusion (-cache -pruning) | disabled | disabled | enabled |
| `FLASH_FUSION_NO_CACHE_NO_PRUNING_NO_PLANNING` | Flash-Fusion (-cache -pruning -planning) | disabled | disabled | disabled |

`FLASH_FUSION` is the deployed full policy: it first attempts exact or
semantic skeleton reuse, uses light-model parameter grounding on an accepted
cache entry, and otherwise runs the pruned full planner. The current
`FLASH_FUSION_CACHE` code path supplies this behavior and should remain a
backward-compatible implementation alias during migration.

The final policy is deliberately not a no-validation baseline. It still sends
the complete typed/Pydantic operator field signatures, associated operator and
field descriptions, and JSON output contract, then runs the identical
structural and DataFrame-schema validation gates. It removes only the
planner-specific instructions and worked operator-chaining examples that help
the LLM decide how to compose a multi-step plan.

## Causal Questions

The main comparisons support this cumulative ablation ladder:

| Paired contrast | Component isolated | Claim supported |
| --- | --- | --- |
| `FLASH_FUSION` vs. `FLASH_FUSION_NO_CACHE` | Cache | Net effect of exact plus semantic cache reuse, including lookup, light grounding, cache failures, and normal fallback. |
| `FLASH_FUSION_NO_CACHE` vs. `FLASH_FUSION_NO_CACHE_NO_PRUNING` | Operator pruning | Effect of reducing the planner's supplied operator vocabulary while retaining its planning guidance, validators, executor, and fallback. |
| `FLASH_FUSION_NO_CACHE_NO_PRUNING` vs. `FLASH_FUSION_NO_CACHE_NO_PRUNING_NO_PLANNING` | Planning guidance/examples | Effect of the prompt material that teaches the LLM how to chain the supplied typed operators. |

The cache comparison is an end-to-end policy effect. The second and third
comparisons are clean adjacent ablations because neither policy uses cache.
Do not add all three deltas to claim independent savings across the entire
system; cache hits change which requests reach the planner.

## Why These Components

### Cache policy

`flashfusion/baselines/flash_fusion_cache.py` replaces the full planner on an
accepted cache hit with cache lookup/matching, a light-model grounding call,
the normal typed validators, and deterministic execution. On every cache
failure it invokes the normal Flash-Fusion planner. Thus its observed delta is
the operational cost of the complete cache policy, not merely an optimistic
cache-hit microbenchmark.

### Operator pruning

`flashfusion/baselines/flash_fusion.py` routes each query through
`route_operator_bucket` before its single structured guardrail-and-plan call.
The router is deterministic and only removes vocabulary buckets; it does not
choose a plan. It changes the planner-prefix size, input tokens, prompt-cache
key, and potentially plan/fallback behavior. The no-pruning variant must
replace the query route with `_FULL_ROUTE` while leaving every downstream
operation unchanged.

### Planning guidance and examples

`flashfusion/pipeline/operators.py` constructs the planner prefix from a
complete vocabulary specification plus role, scope, planning, no-invention,
and output-contract sections. The vocabulary description includes both the
typed operator/Pydantic descriptions that remain in this ablation and
planner-specific usage prose plus worked operator-chain examples that do not.

The `-planning` condition must retain the complete, unpruned operator
signatures and descriptions, aggregate enums, role/scope constraints,
no-invention rules, and strict JSON output grammar. It must remove
planner-only composition material:

- worked multi-step operator-chain examples
- operator usage prose that prescribes sequencing or composition
- the `PLANNING` instructions that teach mapping from question intent to
  multi-step chains

It must not request hidden chain-of-thought. The observable output remains one
typed JSON plan, with the same tokens/model/decode settings and the same
validators as the other policies.

## Explicitly Excluded Main-Figure Ablations

Do not place these in the three primary ablation figures:

- Removing Pydantic structural validation or DataFrame schema validation.
  These gates are part of the system's safety contract; removing them can
  create cheap invalid results rather than a meaningful efficiency baseline.
- Disabling semantic hard compatibility gates. This is appropriate only for an
  offline false-positive-reuse audit, never a production comparison.
- Disabling pruning only after a cache miss. That is a useful miss-conditioned
  diagnostic, but it is not a component-isolating population: cache outcomes
  determine which requests receive the treatment.
- Removing local metadata construction, typed execution, Pydantic structural
  validation, or DataFrame schema validation. These are part of the executable
  safety contract and must remain in every ablation.

## Implementation Plan

### 1. Make policy selection explicit

Add a narrowly scoped Flash-Fusion policy/configuration object, or equivalent
keyword arguments, owned by `flashfusion/baselines/flash_fusion.py` and
`flashfusion/baselines/flash_fusion_cache.py`:

- `cache_enabled: bool`
- `operator_pruning_enabled: bool`
- `planner_guidance_enabled: bool`
- `baseline_code: str`

The no-cache policies must call the same `run_flash_fusion` path. When pruning
is disabled, force `_FULL_ROUTE`; otherwise preserve
`route_operator_bucket(query, list(df.columns))`. When planning guidance is
disabled, render a new no-guidance planner prefix from the full operator field
signature specification. Do not mutate or delete the normal prompt; give the
ablation a separately versioned/digested prompt constructor so prompt-cache
keys and results remain traceable.

Keep these invariants identical in all four policies:

- full planner model and light grounding model
- provider parameters and decoding configuration
- operator registry, JSON response schema, scope/no-invention constraints, and
  Pydantic field signatures
- typed-plan normalization, structural validation, schema validation, timeout,
  typed execution, and ReAct fallback
- query text, DataFrame copy policy, cache registry content, and contract hash

### 2. Extend benchmark dispatch and provenance

Add the four codes to `BaselineRunner.MODES` and dispatch them through the
policy switches above. Preserve the current `FLASH_FUSION_CACHE` code as a
backward-compatible alias until existing results and scripts have migrated.

Persist the following in every `RunResult` and `metrics.csv` row:

- `ablation_policy` with the three binary switches
- total latency, total input/output tokens, and total provider cost
- full-planner latency/input/output/cost
- light-grounding latency/input/output/cost
- cache lookup, semantic retrieval, compatibility validation, and cache-plan
  validation latency
- deterministic router latency, `operator_route_candidate_ops`, and
  `operator_route_full_fallback`
- planner prompt mode, prompt-prefix digest, character length, and input-token
  count; label modes `full_guidance`, `pruned_guidance`, and
  `full_vocabulary_no_chaining_guidance`
- execution path, cache outcome, cache decision, and fallback reason
- structural/schema/execution failure and fallback recovery indicators

Provider prompt cache warming is allowed only as setup. Record cached-input
and cache-write tokens separately so provider-side reuse remains auditable.

### 3. Run a paired, frozen experiment

Use the same query IDs, wording version, DataFrame, registry snapshot,
semantic index snapshot, model identifiers, temperature, timeout, retry
policy, and repetitions for every policy. The current N=3 protocol may be
retained, but randomize or interleave policy order within each replicate to
reduce provider-load drift.

Prewarm all applicable provider prompt prefixes and the hybrid matcher outside
per-query timing for every policy. Do not let one policy's online cache writes
or provider warmup become available only to later policies. Use read-only,
pre-populated cache registries for this experiment.

Include all query outcomes in the primary means: accepted cache hits, cache
misses, cache grounding failures, full-planner calls, ReAct fallbacks, and
out-of-scope rejections. Report cache-hit-only values only as a supplemental
diagnostic.

### 4. Create the three ablation figures

Extend `flashfusion/viz/measure.py` baseline order, labels, and colors, then
allow the plotting scripts to select the four codes without turning them into
the current cache-hit/cache-miss synthetic copies.

Update these paper outputs:

- accuracy diagram: plot benchmark task score/accuracy for all four policies,
  overall and by query type. Include typed-path, fallback, and rejection rates
  in its companion CSV so accuracy changes can be interpreted.
- latency diagram: update
  `results/primary_visualizations/paper/latency_cost_horizontal_three.pdf` or
  replace it with an explicitly named four-policy latency output. Plot total
  mean latency and paired uncertainty; report median and p95 in the companion
  CSV/table.
- cost diagram: produce a parallel four-policy cost figure from total provider
  cost, with total input/output and cached-input tokens in its companion CSV.
- `results/primary_visualizations/paper/semantic_stage_comparison_overall_log_n3.pdf`:
  show comparable stages: deterministic preparation/routing, cache
  lookup/match plus light grounding, full planning, validation, execution, and
  fallback. Do not silently call cache work "planning" without documenting
  that definition.

The existing visualization-only execution cookie-cut must be disabled for
ablation figures. Copying no-cache execution timing onto cache rows masks real
end-to-end execution differences and invalidates the causal contrasts above.

## Required Reporting

For each policy overall and by query type, report:

- task accuracy/score with paired confidence interval
- mean, median, p95, and paired 95% confidence interval for total latency and
  cost
- total/full-planner/light-grounding input and output tokens, cached input
  tokens, and provider cost
- semantic-stage decomposition and total-stage sum
- cache exact-hit, semantic-hit, miss, hard-gate rejection, grounding failure,
  and post-grounding validation-failure rates
- router candidate-operator count, prompt-prefix size, and full-route rate
- typed-path, guardrail-rejection, schema-scope-rejection, and ReAct-fallback
  proportions
- task score and safety failures so an apparent efficiency gain cannot conceal
  quality loss

Use paired per-query deltas for adjacent contrasts as the headline statistic.
Aggregate bars alone can be distorted when policies fall back on different
queries.

## Acceptance Criteria

1. The four policies differ only in the named cache, pruning, and
  planner-guidance controls.
2. All retain the same typed validation and execution safety path.
3. Raw results make it possible to reconstruct each primary-figure stage and
   each total latency/cost value without visualization-only substitutions.
4. Both PDFs and their companion CSV summaries label policies unambiguously.
5. The report includes quality and fallback rates beside efficiency results.

## Follow-On Diagnostic (Supplement Only)

After the four-policy experiment, a semantic-cache authorization audit may
compare the normal hard-gated matcher against a deliberately unsafe,
non-production gate-free matcher. Report false-positive reuse, abstention, and
correct-authorized-hit rates separately. It must not feed answers, latency, or
cost into the three primary ablation figures.