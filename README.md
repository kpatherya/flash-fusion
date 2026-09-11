# Flash-Fusion

<p align="center">
	<img src="chat/public/favicon.svg" width="72" height="72" alt="Flash-Fusion logo">
</p>

<p align="center">
	Expressive, inspectable natural-language analysis for IoT sensor streams.
</p>

<p align="center">
	<a href="https://flash-fusion.vercel.app/">Live chat</a> ·
	<a href="CONTRIBUTING.md">Contributing</a> ·
	<a href="CITATION.cff">Citation</a> ·
	<a href="LICENSE">License</a>
</p>

Flash-Fusion translates a data question into a constrained typed plan, validates
that plan against the live schema, and executes deterministic pandas operators.
Each result carries inspectable routing, plan, validation, cache, and execution
evidence rather than an opaque code-generation attempt.

## Project Components

- `flashfusion/`: typed planning pipeline, operator vocabulary, baselines, evaluation, tests, and visualizations.
- `chat/`: Vercel-hosted interface for bus telemetry, WISDM IMU, and MIT-BIH ECG exploration.
- `data/`: canonical local dataset roots used by evaluation workflows.
- `docs/`: experiment plans, contract notes, cache analysis, and reproducibility material.

## How It Works

1. **Route**: eliminate incompatible operator groups from the closed vocabulary.
2. **Plan**: request one schema-aware structured operator plan.
3. **Validate**: apply structural and live-DataFrame validation gates.
4. **Execute**: run approved operators deterministically in pandas.
5. **Inspect**: return the answer with route, plan, validation, cache, and execution evidence.

The skeleton-cache mode can reuse an exact operator skeleton, re-ground its
parameters to the current schema, and run the same validation gates. The
grounded agent implementation remains available as a comparison baseline.

## Quick Start

Requires Python 3.12 or newer.

```sh
git clone https://github.com/kpath1999/flash-fusion.git
cd flash-fusion
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./flashfusion
pip install -r requirements-research.txt
```

Set an OpenRouter key for local experiments:

```sh
export OPENROUTER_API_KEY="..."
```

Run the tests:

```sh
pytest flashfusion/tests
```

## Run the Chat App

The hosted interface is served from `chat/` and uses `openrouter/auto` for
planning, grounding, and domain routing.

```sh
cd chat
pip install -r requirements.txt
export OPENROUTER_PRODUCTION="..."
vercel dev
```

Use the lightweight health probe to check a deployment without starting a model
request:

```sh
curl -fsS https://flash-fusion.vercel.app/api/health
```

It returns JSON with `status` and `has_api_key`. A `200` response proves that
the Vercel runtime started. `has_api_key: true` confirms that
`OPENROUTER_PRODUCTION` is present in that deployment. Configure the value as a
Vercel Production environment variable and redeploy after changing it.

## Benchmarking

The benchmark runner evaluates Flash-Fusion alongside paper and agent baselines
over WISDM, MIT ECG, and bus datasets. Results are written below
`flashfusion/results/`.

```sh
./run_benchmark.sh --quick
./run_benchmark.sh --bus --baselines FLASH_FUSION --runs 3
```

Run `./run_benchmark.sh --help` for dataset, query, latency, model, and output
configuration.

See [docs/RESULTS_ARTIFACT_POLICY.md](docs/RESULTS_ARTIFACT_POLICY.md) for
which benchmark artifacts are canonical and which are local-only outputs.

## Deployment Footprint

Vercel uses the root `pyproject.toml` to install the production-only dependency
set and launch `api.chat:app`; it can then trace and optimize the function
bundle. The broader `requirements-research.txt` is for local research,
embeddings, visualization, and benchmark workflows. The root `.vercelignore`
excludes canonical datasets and generated artifacts while retaining the bundled
chat data and typed-plan cache needed at runtime. Predictive typed operators
require scikit-learn and remain available in the local research environment
rather than the 225 MB serverless chat bundle.

The chat function explicitly includes its small, tracked demo datasets from
`chat/data/` because Vercel cannot infer dynamically constructed filesystem
paths. Do not add the multi-gigabyte canonical `data/` tree to this bundle.

For full datasets, store immutable source files in object storage such as
Cloudflare R2, Amazon S3, or Google Cloud Storage, and run data-intensive work
in a separately deployed service with persistent disk and sufficient memory.
Vercel should remain the web/API edge layer: it can submit a query to that
service and return its result. Downloading multi-gigabyte inputs into a Vercel
function is unsuitable because function bundles, ephemeral disk, memory, and
execution time are all bounded.

## Contributing

Contributions to typed operators, validation contracts, datasets, benchmarks,
documentation, and the chat experience are welcome. Keep changes focused and
include tests for behavior changes, especially when execution semantics change.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution flow and project
conventions. Issue reports should include the query, dataset, execution mode,
expected result, actual result, and a redacted audit trace.

Use [docs/REPRODUCIBILITY_CHECKLIST.md](docs/REPRODUCIBILITY_CHECKLIST.md)
before publishing result claims or tagging a release.
