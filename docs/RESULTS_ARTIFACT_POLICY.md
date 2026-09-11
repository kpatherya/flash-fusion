# Results Artifact Policy

This repository contains both canonical evidence artifacts and local generated
outputs. Keep them separate so reviewers can distinguish source-of-truth
material from ephemeral run products.

## Canonical Tracked Artifacts

Track only artifacts that are needed to explain or reproduce published claims.
Current canonical categories are:

- Curated visualization assets under `results/` used by public docs/pages.
- Ground-truth fixtures under `flashfusion/eval/ground_truth/` that drive
  benchmark scoring and tests.

If a new artifact becomes canonical, add a short note in this file explaining
why it is retained.

## Local Generated Outputs (Do Not Commit)

Treat the following as local-only by default:

- `flashfusion/results/runs/`
- Any nested `run_*` benchmark folders under `flashfusion/results/`
- Per-run logs and raw outputs such as `raw_results.jsonl`, `benchmark.log`,
  `visualize.log`, and `stage_*.log`

These paths are ignored in `.gitignore` to reduce churn and accidental commits.

## Promoting a Local Artifact to Canonical

When a generated artifact is needed for a paper or release:

1. Copy or distill it into a stable, curated location under `results/`.
2. Add context (dataset, baselines, run tag, and commit SHA) in adjacent docs.
3. Update this policy with the rationale for long-term retention.
