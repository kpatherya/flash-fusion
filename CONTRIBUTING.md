# Contributing to Flash-Fusion

<p align="center">
  <img src="chat/public/favicon.svg" width="56" height="56" alt="Flash-Fusion logo">
</p>

Flash-Fusion turns sensor-stream questions into schema-grounded, validated data
operations. Contributions that improve correctness, reproducibility, and
inspection are especially useful.

## Quick Start

Clone the repository and create an isolated Python environment:

Requires Python 3.12 or newer.

```sh
git clone https://github.com/kpath1999/flash-fusion.git
cd flash-fusion
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./flashfusion
pip install -r requirements-research.txt
pytest flashfusion/tests
```

To run the chat application locally, install its extra dependencies and start
Vercel development mode:

```sh
cd chat
pip install -r requirements.txt
vercel dev
```

Set `OPENROUTER_PRODUCTION` in `chat/.env.local`. The hosted chat uses
`openrouter/auto` for planning, grounding, and domain routing.

## Contribution Flow

1. Open an issue for a new operator, dataset, or behavior change before a large implementation.
2. Make a focused branch and add or update tests in `flashfusion/tests/`.
3. Run the focused tests that cover the changed behavior.
4. Submit a pull request with the question/dataset used to validate the change and any expected metric impact.

## Project Guidelines

- Keep data-path handling rooted in the repository `data/` directory.
- Treat the typed operator vocabulary as closed: add operators with validation and execution coverage.
- Do not commit API keys, local `.env` files, generated benchmark outputs, or raw private data.
- Preserve the audit trail so users can inspect routing, grounding, validation, and execution decisions.

## Reporting Issues

Include the query, dataset, selected execution mode, expected result, actual
result, and a redacted error or audit trace. This makes grounded failures
reproducible instead of mysterious.