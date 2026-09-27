# Primary Visualizations

`primary_visualizations.py` is the single entrypoint for the primary Flash-Fusion figures. It normalizes the benchmark metrics from their canonical result roots, joins the requested extra-hard runs, and writes only the paper figures and reproducible summaries.

Run from the repository root:

```bash
./flashfusion/viz/run_primary_visualizations.sh
```

Optional environment variables:

```bash
MODE=baselines ./flashfusion/viz/run_primary_visualizations.sh
MODE=ablations ./flashfusion/viz/run_primary_visualizations.sh
VIZ_ROOT=results/primary_visualizations ./flashfusion/viz/run_primary_visualizations.sh
STRICT=0 ./flashfusion/viz/run_primary_visualizations.sh
ALIGN_FF_FULL_MODEL=mistralai/ministral-8b-2512 ./flashfusion/viz/run_primary_visualizations.sh
NO_ALIGN_FF_FULL=1 ./flashfusion/viz/run_primary_visualizations.sh
```

## FF-full Alignment

By default, the `FLASH_FUSION_CACHE` rows used as `Flash-Fusion` are alignment-adjusted with a grounding miss mask from:

- `flashfusion/results/grounding/<dataset>/grounding_benchmark_raw.jsonl` for Q1-Q16
- `flashfusion/results/grounding/extra_hard/<dataset>/grounding_benchmark_raw.jsonl` for Q17-Q20

Miss-key rows are replaced with planner fallback metrics from:

- `flashfusion/results/ablations/primary` (`FF_NO_CACHE`)
- `flashfusion/results/extra_hard/FLASH_FUSION`

Cache-hit rows remain unchanged. Set `NO_ALIGN_FF_FULL=1` to disable this behavior.

## Output Contract

Baseline outputs are written to `results/primary_visualizations/baselines`:

- `query_accuracy_across_baselines.{png,pdf}`
- `query_accuracy_by_dataset_across_baselines.{png,pdf}`
- `accuracy_by_query_type.{png,pdf}`
- `latency_by_semantic_stage.{png,pdf}`
- `cumulative_latency_comparison_log_by_baseline_n3.{png,pdf}`
- `cost_vs_baselines_across_datasets.{png,pdf}`
- `grounding_loss_vs_model_size.{png,pdf,csv}`
- `cache_hit_rate_vs_cost_flash_fusion_vs_react.{png,pdf,csv}`
- `ff_full_alignment_audit.csv`
- `summary_baselines.{csv,md}`

Ablation outputs are written to `results/primary_visualizations/ablations`:

- `query_accuracy_across_ablations.{png,pdf}`
- `latency_by_semantic_stage.{png,pdf}`
- `cumulative_latency_comparison_by_ablation_n3.{png,pdf}`
- `summary_ablations.{csv,md}`

Superseded plotting scripts are retained under `flashfusion/viz/archive` for historical reference and are not part of the generation workflow.
