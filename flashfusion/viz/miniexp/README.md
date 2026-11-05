# Flash-Fusion Mini-Experiments
This directory contains scaffold scripts for three mini-experiments designed to evaluate different aspects of the Flash-Fusion pipeline.
## Experiments
### 1. Latency vs. Chunks (`latencychunks.py`)
**Purpose:** Measure how TTFT (Time To First Token) and input cost change as the number of data chunks in the input prompt increases.
**Hypothesis:** As chunk count increases, both TTFT and E2E latency should increase linearly due to increased context length.
**Usage:**
```bash
# Basic run with default settings (bus dataset, chunks [1,2,4,8,16,32])
python -m flashfusion.miniexp.latencychunks
# Custom chunk counts
python -m flashfusion.miniexp.latencychunks --chunks 1 5 10 20 40
# With plotting
python -m flashfusion.miniexp.latencychunks --plot
# Use different dataset
python -m flashfusion.miniexp.latencychunks --dataset wisdm --plot
# Use different model
python -m flashfusion.miniexp.latencychunks --model meta-llama/llama-3.1-8b-instruct
```
**Outputs:**
- `results/latency_vs_chunks.csv` - Raw data
- `results/latency_vs_chunks.png` - Visualization (if --plot is used)
**Key Metrics:**
- TTFT (Time To First Token) in milliseconds
- Input cost (USD), which increases with every prompt token
- E2E (End-to-End) latency in milliseconds
- Number of rows per chunk
- Number of LLM calls
---

Note!! Accuracy vs query size is run for different dataset sizes.
It also records the latency stages.
So you could easily get the latency stage metrics for when dataset size % is at 100.
That would conclude your latency stage mini-experiment as well! Shooting two birds with one stone.
### 2. Dataset Size vs. Query Accuracy (`accuracysize.py`)
**Purpose:** Investigate how query accuracy changes as we vary the dataset size.
**Hypothesis:** Accuracy should remain relatively stable across different dataset sizes for well-grounded queries, though latency may increase.
**Usage:**
```

OpenRouter's Auto Router can be used for a larger-context comparison. Set the
context budget to the model's advertised limit and keep the provider/model
configuration recorded with the CSV:

```bash
python -m flashfusion.viz.miniexp.latencychunks \
  --model openrouter/auto \
  --context-window-tokens 2000000 \
  --chunks 100 500 1000 2000 4000 \
  --dataset ecg \
  --data-path data/AutoIOT_dataset/ECG.0/tmp_csv/100.csv \
  --plot
```

The main figure reports estimated input cost separately from TTFT. This makes the
streaming point explicit: streaming can reduce peak memory or time-to-first
token, but it does not remove the per-token input charge.bash

To generate only a single-axis cost figure from saved trials:

```bash
MPLBACKEND=Agg python -m flashfusion.viz.miniexp.latencychunks \
  --csv-input flashfusion/viz/miniexp/results/latency_trials.csv \
  --output-dir flashfusion/viz/miniexp/results \
  --cost-only --context-window-tokens 2000000 \
  --layout single --xscale log --dataset-label ECG \
  --total-rows 650000 --rows-per-chunk 19
```

This writes `cost_vs_chunks.png` and `cost_vs_chunks.pdf`, showing average
cost only, scaled as `Cost ($ x 10^-5)`. The red shaded region begins at the
configured context limit.bash
# Basic run with default settings (wisdm dataset, query 1, fractions [0.1,0.25,0.5,0.75,1.0])
python -m flashfusion.miniexp.accuracysize
# Custom sample fractions
python -m flashfusion.miniexp.accuracysize --fractions 0.2 0.4 0.6 0.8 1.0
# Test different query
python -m flashfusion.miniexp.accuracysize --query-id 3
# With plotting
python -m flashfusion.miniexp.accuracysize --plot
# Use different dataset
python -m flashfusion.miniexp.accuracysize --dataset bus --plot
```
**Outputs:**
- `results/accuracy_vs_size.csv` - Raw data
- `results/accuracy_vs_size.png` - Visualization (if --plot is used)
**Key Metrics:**
- Execution success rate
- Query answer
- Latency in seconds
- Cost in USD
- Number of stages executed
**Note:** Ground truth computation for sampled datasets is a placeholder and needs implementation based on query type.
---
### 3. Model Type Variation (`metricstype.py`)
**Purpose:** Test Flash-Fusion with different LLM models to verify that results and metrics remain consistent across model types.
**Hypothesis:** The pipeline should produce consistent accuracy and execution patterns across different models, though latency and cost may vary by model size.
**Usage:**
```bash
# Basic run with default settings (wisdm dataset, queries [1,2,3,4], 3 models)
python -m flashfusion.miniexp.metricstype
# Test specific queries
python -m flashfusion.miniexp.metricstype --query-ids 1 2 5
# Test specific models
python -m flashfusion.miniexp.metricstype --models \
    "meta-llama/llama-3.3-70b-instruct" \
    "meta-llama/llama-3.1-8b-instruct"
# With plotting and analysis
python -m flashfusion.miniexp.metricstype --plot --analyze
# Use different dataset
python -m flashfusion.miniexp.metricstype --dataset bus --plot
```
**Outputs:**
- `results/metrics_vs_model_type.csv` - Raw data
- `results/model_consistency_analysis.csv` - Consistency analysis (if --analyze is used)
- `results/metrics_vs_model_type.png` - Visualization (if --plot is used)
**Key Metrics:**
- Execution success rate by model
- Query rejection rate
- Latency in seconds
- Cost in USD
- Number of input/output tokens
- Number of LLM calls
**Consistency Analysis:**
- Whether all models execute the same queries successfully
- Standard deviation of latency and cost across models
- Execution pattern consistency
---
## Prerequisites
### Environment Variables
All experiments require one of the following API keys:
```bash
export OPENROUTER_API_KEY="your-key-here"
# OR
export GROQ_API_KEY="your-key-here"
```
### Python Dependencies
```bash
pip install pandas matplotlib
```
Make sure the Flash-Fusion package is properly installed:
```bash
pip install -e .
```
---
## Common Options
All experiments support these common options:
- `--dataset <name>`: Dataset to use (wisdm, bus, mit_ecg)
- `--data-path <path>`: Custom path to dataset file
- `--model <name>`: LLM model to use (default: meta-llama/llama-3.3-70b-instruct)
- `--output-dir <path>`: Directory to save results (default: flashfusion/miniexp/results)
- `--plot`: Generate visualization plots
---
## Results Directory
By default, all results are saved to `flashfusion/miniexp/results/`:
```
flashfusion/miniexp/results/
├── latency_vs_chunks.csv
├── latency_vs_chunks.png
├── accuracy_vs_size.csv
├── accuracy_vs_size.png
├── metrics_vs_model_type.csv
├── model_consistency_analysis.csv
└── metrics_vs_model_type.png
```
---
## Example Workflow
Here's a complete workflow to run all three experiments:
```bash
# Set up environment
export OPENROUTER_API_KEY="your-key-here"
# Run all experiments with plotting
python -m flashfusion.miniexp.latencychunks --plot
python -m flashfusion.miniexp.accuracysize --plot
python -m flashfusion.miniexp.metricstype --plot --analyze
# Check results
ls -lh flashfusion/miniexp/results/
```
---
## Customization
Each experiment script is designed to be easily extended:
1. **Custom datasets:** Add new dataset loaders in `flashfusion/pipeline/loader.py`
2. **Custom queries:** Modify the query text or use benchmark queries from `flashfusion/eval/queries.py`
3. **Custom metrics:** Extend the metric collection in each `run_query_with_*` function
4. **Custom plots:** Modify the `plot_results()` function in each script
---
## Notes
- These are scaffold scripts meant to be customized for your specific research needs
- Ground truth computation in `accuracysize.py` is a placeholder and needs query-specific implementation
- All experiments use the Flash-Fusion pipeline; you can adapt them to test other baselines
- For production use, consider adding error handling, logging, and more sophisticated statistical analysis
---
## Troubleshooting
**API Key Not Found:**
```
ValueError: OPENROUTER_API_KEY or GROQ_API_KEY environment variable required
```
→ Set one of the required environment variables
**Dataset Not Found:**
```
Error: Could not load dataset
```
→ Check that dataset paths in `flashfusion/eval/benchmark.py::DEFAULT_DATA_PATHS` are correct
**Import Errors:**
```
ModuleNotFoundError: No module named 'flashfusion'
```
→ Install the package: `pip install -e .` from the repository root
**Out of Memory:**
If experiments fail with large datasets, reduce the sample size or chunk counts.
---
## Contributing
To add a new mini-experiment:
1. Create a new Python file in this directory
2. Follow the structure of existing experiments
3. Add CLI argument parsing with `argparse`
4. Include data collection, analysis, and visualization functions
5. Document in this README
For questions or issues, please open a GitHub issue.
