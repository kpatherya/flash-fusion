# Direct prompting: latency and cost vs. chunks (ECG 100.csv)

ECG 100.csv: 650,000 rows -> 34,448 chunks at `--chunk-token-target 200` (~19 rows/chunk).
Real tokens are ~2.02x the chars/4 estimate (~430 tokens/chunk), so the 128k window is
exhausted between 250 and 300 chunks (~0.9% of the file).

## Three runs (run-to-run variation)

```bash
for i in 1 2 3; do
  python -m flashfusion.viz.miniexp.latencychunks \
    --dataset ecg \
    --data-path data/AutoIOT_dataset/ECG.0/tmp_csv/100.csv \
    --model meta-llama/llama-3.3-70b-instruct \
    --chunks 50 100 150 200 250 260 270 280 290 300 \
    --chunk-token-target 200 \
    --retries 1 \
    --output-dir flashfusion/viz/miniexp/results/latency_run$i
done

python -m flashfusion.viz.miniexp.latencychunks \
  --avg-inputs flashfusion/viz/miniexp/results/latency_run{1,2,3}/latency_vs_chunks.csv \
  --output-dir flashfusion/viz/miniexp/results \
  --total-rows 650000 --rows-per-chunk 19 \
  --plot
```

Single-command alternative (calls interleaved across runs, optionally shuffled):

```bash
python -m flashfusion.viz.miniexp.latencychunks \
  --dataset ecg --data-path data/AutoIOT_dataset/ECG.0/tmp_csv/100.csv \
  --chunks 50 100 150 200 250 260 270 280 290 300 \
  --runs 3 --shuffle --seed 0 --retries 1 \
  --output-dir flashfusion/viz/miniexp/results --plot
```

Recommended for stable cost/latency: pin the provider (`--provider <Name>`; check the
provider used in the OpenRouter activity log) and optionally `--lookup-provider`.
`--skip-predicted-overflow` avoids spending calls beyond the calibrated window;
leave it off to verify the boundary empirically.

## Outputs

- `latency_vs_chunks.csv`: one row per trial (run x chunk count), incl. tokens, split cost,
  `prefill_tok_per_s`, `decode_ms_per_token`, `error_type`, `abs_error`, `cost_mismatch`.
- `latency_vs_chunks_summary.csv` / `latency_vs_chunks_avg.csv`: per chunk count mean, SD,
  median, Q25/Q75, `n_success/n_runs`.
- `latency_trials.csv`: combined trials from `--avg-inputs`.
- `latency_vs_chunks.png|pdf`: TTFT/TTLT and cost (per-run scatter, mean +/- SD, X = all runs failed).
- `latency_vs_chunks_extrapolation.png|pdf`: projected prompt tokens and cost to 100% of the data.
- `latency_vs_chunks_accuracy.png|pdf`: |answer - ground-truth mean MLII| vs context size.

## Paper figures (re-plot without new API calls)

```bash
python -m flashfusion.viz.miniexp.latencychunks \
  --csv-input flashfusion/viz/miniexp/results/latency_trials.csv \
  --output-dir flashfusion/viz/miniexp/results \
  --layout single --xscale log --plot
```

- `--layout single` (IEEE column, 3.5 in, 8-9 pt text), `double` (7.16 in), `large` (slides).
- `--xscale log|linear` (default log) and `--yscale linear|log` (log y shows the latency tail).
- PDFs embed TrueType fonts (Type 42) for IEEE PDF eXpress.

## Notes

- Prompt output format is `ANSWER=<number>` and `--max-tokens` defaults to 128, so TTLT
  measures prefill + a short decode rather than model verbosity (`--max-tokens 0` = unbounded).
- `cost_usd` is the provider-reported cost. It is ~5x below the `config.py` rate in earlier
  runs and varied ~2x across chunk counts (provider routing); `cost_mismatch` flags this.
- Failures are classified `overflow` / `rate_limit` / `provider_error` /
  `overflow_suspected` (generic provider error beyond the predicted window).
- Headless/sandboxed shells: set `MPLBACKEND=Agg`.
