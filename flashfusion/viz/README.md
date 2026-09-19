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
```

## Output Contract

Baseline outputs are written to `results/primary_visualizations/baselines`:

- `query_accuracy_across_baselines.{png,pdf}`
- `latency_by_semantic_stage.{png,pdf}`
- `cumulative_latency_comparison_log_by_baseline_n3.{png,pdf}`
- `cost_vs_baselines_across_datasets.{png,pdf}`
- `grounding_loss_vs_model_size.{png,pdf,csv}`
- `cache_hit_rate_vs_cost_flash_fusion_vs_react.{png,pdf,csv}`
- `summary_baselines.{csv,md}`

Ablation outputs are written to `results/primary_visualizations/ablations`:

- `query_accuracy_across_ablations.{png,pdf}`
- `latency_by_semantic_stage.{png,pdf}`
- `cumulative_latency_comparison_by_ablation_n3.{png,pdf}`
- `summary_ablations.{csv,md}`

Superseded plotting scripts are retained under `flashfusion/viz/archive` for historical reference and are not part of the generation workflow.
