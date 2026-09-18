Please revise the Flash-Fusion baseline implementation and benchmark integration so that we can run reliable, interpretable ablations of the system’s three components:

1. caching,
2. operator pruning, and
3. planner prompting/guidance.

Start by inspecting the current baseline implementations, benchmark dispatch, result-writing code, visualization inputs, and the most recent ablation outputs. In particular, determine why the existing ablation runs do not currently produce trustworthy comparisons. Treat the existing `flash_fusion.py` and `flash_fusion_cache.py` behavior as the starting point, not as an assumed correct experimental design.

## Goal

Create ablations that isolate the effect of a single component. Each ablation should differ from the full Flash-Fusion configuration in only one intended dimension:

- Full Flash-Fusion: cache enabled, operator pruning enabled, planner guidance enabled.
- No-cache: cache disabled; pruning and planner guidance unchanged.
- No-pruning: operator pruning disabled; cache and planner guidance unchanged.
- No-prompting: planner-specific chaining guidance/examples disabled; cache and pruning unchanged.

Do not make the ablations cumulative unless there is a separate, clearly labeled diagnostic reason to do so. The primary reported comparisons should support component-level claims rather than conflate multiple removals.

## Terminal runbook (copy/paste)

Use the canonical primary policy labels for component-level ablations:

- `FF_FULL` (cache on, pruning on, guidance on)
- `FF_NO_CACHE`
- `FF_NO_PRUNE`
- `FF_NO_PROMPT`

### 1) Quick smoke check (single dataset)

```bash
python -m flashfusion.eval.benchmark \
   --dataset bus \
   --data data/bus/bus_data_enriched_behavior.csv \
   --ground-truth flashfusion/eval/ground_truth/ground_truth_bus.json \
   --baselines FF_FULL,FF_NO_CACHE,FF_NO_PRUNE,FF_NO_PROMPT \
   --queries 1,5,9,13 \
   --runs 1 \
   --interleave-policies \
   --query-rewording paired \
   --prompt-cache-warmup \
   --cache-prewarm-hybrid \
   --output flashfusion/results/ablations/smoke_bus
```

### 2) Full primary ablation run per dataset

```bash
python -m flashfusion.eval.benchmark \
   --dataset wisdm \
   --data data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt \
   --ground-truth flashfusion/eval/ground_truth/ground_truth_wisdm.json \
   --baselines FF_FULL,FF_NO_CACHE,FF_NO_PRUNE,FF_NO_PROMPT \
   --queries all \
   --runs 3 \
   --interleave-policies \
   --query-rewording paired \
   --prompt-cache-warmup \
   --cache-prewarm-hybrid \
   --output flashfusion/results/ablations/primary/wisdm

python -m flashfusion.eval.benchmark \
   --dataset mit_ecg \
   --data data/AutoIOT_dataset/ECG.0/MIT_arrythmia_v1.txt \
   --ground-truth flashfusion/eval/ground_truth/ground_truth_mit_ecg.json \
   --baselines FF_FULL,FF_NO_CACHE,FF_NO_PRUNE,FF_NO_PROMPT \
   --queries all \
   --runs 3 \
   --interleave-policies \
   --query-rewording paired \
   --prompt-cache-warmup \
   --cache-prewarm-hybrid \
   --output flashfusion/results/ablations/primary/mit_ecg

python -m flashfusion.eval.benchmark \
   --dataset bus \
   --data data/bus/bus_data_enriched_behavior.csv \
   --ground-truth flashfusion/eval/ground_truth/ground_truth_bus.json \
   --baselines FF_FULL,FF_NO_CACHE,FF_NO_PRUNE,FF_NO_PROMPT \
   --queries all \
   --runs 3 \
   --interleave-policies \
   --query-rewording paired \
   --prompt-cache-warmup \
   --cache-prewarm-hybrid \
   --output flashfusion/results/ablations/primary/bus
```

### 3) Collect and inspect outputs

```bash
# Per-dataset core outputs
find flashfusion/results/ablations/primary -name metrics.csv -o -name raw_results.jsonl | sort

# Example: inspect one metrics file quickly
python - <<'PY'
import pandas as pd
df = pd.read_csv("flashfusion/results/ablations/primary/bus/metrics.csv")
cols = [
      "baseline", "query_id", "gt_score", "latency_s", "cost_usd",
      "policy_name", "policy_cache_enabled", "policy_pruning_enabled",
      "policy_planner_guidance_enabled", "cache_outcome",
      "planner_candidate_op_count", "planner_prefix_chars", "execution_path"
]
cols = [c for c in cols if c in df.columns]
print(df[cols].head(20).to_string(index=False))
PY

# Optional: regenerate comparison plots for one run folder
python -m flashfusion.eval.visualize_comparison \
   --metrics flashfusion/results/ablations/primary/bus/metrics.csv \
   --dataset bus \
   --output flashfusion/results/ablations/primary/bus
```

### 4) If using the shell wrapper, override legacy defaults explicitly

```bash
RUN_TAG=ablations_primary_n3 \
RUNS=3 \
BASELINES=FF_FULL,FF_NO_CACHE,FF_NO_PRUNE,FF_NO_PROMPT \
SMOKE_TEST=1 \
./run_benchmark.sh --all --queries all
```

## Requested file organization

Rename the current non-cache baseline implementation from:

`flashfusion/baselines/flash_fusion.py`

to:

`flashfusion/baselines/flash_fusion_no_cache.py`

Update imports, benchmark dispatch, scripts, tests, documentation, and other dependencies accordingly.

Create:

`flashfusion/baselines/flash_fusion_no_prune.py`

This variant should preserve the full-policy behavior as much as possible while disabling only operator pruning. It should not accidentally become a no-cache implementation merely because of how the existing code is organized.

If the current architecture makes a separate no-prompting entry point necessary for clear experiment dispatch, create an appropriately named baseline module as well. Prefer a small shared policy/configuration mechanism over copying substantial orchestration logic across several scripts, but do not over-refactor unrelated code.

Keep a backward-compatible alias or migration path for existing `FLASH_FUSION` / `FLASH_FUSION_CACHE` references if existing scripts or saved experiments still depend on those names. Clearly document the final mapping between legacy names, implementation entry points, and experimental labels.

## Experimental invariants

Across the full system and all ablations, preserve the same:

- benchmark queries, datasets, repetitions, models, decoding parameters, retries, timeouts, and execution environment;
- operator registry, typed operator schemas, JSON response contract, validation gates, execution path, and fallback behavior;
- cache contents and cache-read/write protocol except where caching itself is the treatment;
- data-copy behavior and evaluation/scoring logic.

Do not weaken structural validation, schema validation, safety checks, or typed execution as part of these primary ablations. A cheaper invalid answer is not a meaningful efficiency result.

For the no-pruning condition, use the complete operator vocabulary while preserving the same planner, validation, execution, and fallback pipeline. For the no-prompting condition, retain operator signatures, field descriptions, output grammar, scope constraints, and no-invention rules. Remove only material that teaches or demonstrates planner-specific operator sequencing/composition, such as worked multi-step chaining examples and explicit planning guidance. Do not request hidden reasoning or chain-of-thought.

## Logging and provenance

The recent runs make it difficult to diagnose whether observed differences arise from caching, pruning, prompting, fallback behavior, or instrumentation. Make the logging sufficient to reconstruct the actual execution path for every query and repetition.

Use a common logging/result schema for all Flash-Fusion variants. At minimum, record:

- baseline code and an explicit policy description identifying cache, pruning, and planner-guidance settings;
- query ID, dataset, replicate, model/configuration identifiers, and prompt/version digest;
- accuracy or task score and outcome category;
- end-to-end latency, token counts, and provider cost;
- stage-level latency/cost where available, including routing, cache lookup/matching, cache grounding, full planning, validation, execution, and fallback;
- cache outcome and reason, including exact hit, semantic hit, miss, hard-gate rejection, grounding failure, and post-grounding validation failure;
- routing/pruning metadata, such as candidate operator count, whether the full vocabulary was used, and prompt-prefix size;
- planner prompt mode and enough provenance to distinguish the normal guided prompt from the no-guidance prompt;
- typed-path success, validation failures, schema/scope rejections, execution failures, and ReAct fallback/recovery.

Avoid visualization-only substitutions or copied timing values. The raw results should make all aggregate latency and cost figures reproducible from measured per-query records.

## Evaluation expectations

Ensure the benchmark runner can execute and label all policies consistently. Preserve paired per-query comparisons by using the same query set and repetitions across policies. If possible, interleave policy order within a replicate and perform any prompt-cache warming outside timed measurements so provider load or warmup does not systematically favor one policy.

The expected hypotheses are:

- Removing planner guidance may reduce task accuracy, particularly for multi-step operator composition.
- Removing guidance or pruning may increase planning latency because the planner receives fewer composition hints or a larger operator vocabulary.
- Removing caching may increase latency and provider cost when the full planner replaces accepted cache reuse.

Treat these as hypotheses to test, not conclusions to encode into result summaries.

## Deliverables

1. Implement the renamed and new baseline entry points, with shared internals where that improves consistency.
2. Update all affected imports, dispatch tables, CLI/configuration paths, tests, and documentation.
3. Add or update logging so each policy’s execution path and metrics are auditable.
4. Add focused tests or smoke checks demonstrating that each primary ablation toggles only its intended component.
5. Provide a concise implementation summary that includes:
   - the final policy matrix;
   - changed files and compatibility decisions;
   - the root cause(s) found in the existing ablation setup;
   - commands used for validation;
   - any unresolved experimental limitations or follow-up work.

Avoid unrelated cleanup. Make decisions based on the current repository structure, explain any assumptions, and flag any conflict between existing naming/behavior and the isolation requirement before making a potentially incompatible change.