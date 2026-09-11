# Reproducibility Checklist

Use this checklist before publishing benchmark claims, sharing comparison plots,
or cutting a release.

## Environment

- [ ] Python version is 3.12+ and recorded.
- [ ] Dependency install commands are captured exactly as run.
- [ ] Model provider and model name are documented.
- [ ] Required environment variables are listed without exposing secrets.

## Data and Ground Truth

- [ ] Dataset paths or object-storage URIs are documented.
- [ ] Any preprocessing or filtering steps are documented.
- [ ] Ground-truth files and query IDs are pinned.

## Benchmark Execution

- [ ] Exact benchmark command line is included.
- [ ] Baselines, datasets, query subsets, run count, and timeout settings are recorded.
- [ ] Smoke-test behavior (enabled/disabled) is documented.

## Results and Reporting

- [ ] Summary tables include run tag and commit SHA.
- [ ] Charts include dataset and baseline labels with units.
- [ ] Any exclusions, failures, or abstentions are documented.
- [ ] Claims in README/docs are traceable to committed artifacts.

## Release Gate

- [ ] `./run_benchmark.sh --help` runs with no shell errors.
- [ ] `pytest flashfusion/tests` passes in the maintained development environment.
- [ ] New docs links resolve locally.
