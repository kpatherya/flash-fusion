#!/usr/bin/env bash
# Generate standard-baseline and Flash-Fusion ablation visualizations.
#
# Output layout:
#   results/primary_visualizations/baselines/
#   results/primary_visualizations/ablations/
#
# Quick usage:
#   RUN_ABLATION_BENCHMARKS=0 ./flashfusion/viz/run_primary_visualizations.sh
#
# If ablation artifacts are missing, run benchmarks first with canonical labels:
#   RUN_TAG=ablations_primary_n3 RUNS=3 \
#   BASELINES=FF_FULL,FF_NO_CACHE,FF_NO_PRUNE,FF_NO_PROMPT \
#   ./run_benchmark.sh --all --queries all
#
# Then point roots (example):
#   FLASH_FUSION_ROOT=flashfusion/results/ablations/FF_NO_CACHE \
#   FF_NO_PRUNING_ROOT=flashfusion/results/ablations/FF_NO_PRUNE \
#   FF_NO_PLANNING_ROOT=flashfusion/results/ablations/FF_NO_PROMPT \
#   ./flashfusion/viz/run_primary_visualizations.sh
#
# By default, runs the two missing N=3 ablation benchmarks before producing
# figures. Set RUN_ABLATION_BENCHMARKS=0 to regenerate figures from existing
# artifacts only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON="${REPO_ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    PYTHON="python"
fi

RUN_ABLATION_BENCHMARKS=0
RUN_TAG="${RUN_TAG:-ablations_n3}"
RUNS="${RUNS:-3}"
ABLATION_RESULTS_ROOT="${ABLATION_RESULTS_ROOT:-flashfusion/results/ablations}"
VIZ_ROOT="${VIZ_ROOT:-results/primary_visualizations}"
BASELINE_VIZ_DIR="${VIZ_ROOT}/baselines"
ABLATION_VIZ_DIR="${VIZ_ROOT}/ablations"

FLASH_FUSION_ROOT="${FLASH_FUSION_ROOT:-flashfusion/results/ff_and_react_qwen/FLASH_FUSION}"
FLASH_FUSION_CACHE_ROOT="${FLASH_FUSION_CACHE_ROOT:-flashfusion/results/ff_hybrid_cache/FLASH_FUSION_CACHE}"
REACT_ROOT="${REACT_ROOT:-flashfusion/results/ff_and_react_qwen/REACT_ONLY}"
EXTRA_HARD_ROOT="${EXTRA_HARD_ROOT:-flashfusion/results/extra_hard}"
FF_NO_PRUNING_ROOT="${FF_NO_PRUNING_ROOT:-${ABLATION_RESULTS_ROOT}/FF_NO_PRUNING}"
FF_NO_PLANNING_ROOT="${FF_NO_PLANNING_ROOT:-${ABLATION_RESULTS_ROOT}/FF_NO_PLANNING}"

mkdir -p "${BASELINE_VIZ_DIR}" "${ABLATION_VIZ_DIR}"

if [[ "${RUN_ABLATION_BENCHMARKS}" == "1" ]]; then
    RUN_TAG="${RUN_TAG}" RUNS="${RUNS}" OUTPUT_ROOT="${ABLATION_RESULTS_ROOT}" \
        BASELINES="FF_NO_PRUNING" ./run_benchmark.sh --all --queries all

    RUN_TAG="${RUN_TAG}" RUNS="${RUNS}" OUTPUT_ROOT="${ABLATION_RESULTS_ROOT}" \
        BASELINES="FF_NO_PLANNING" ./run_benchmark.sh --all --queries all
fi

cd "${SCRIPT_DIR}"

# Standard baselines: FF-cache is the canonical Flash-Fusion baseline.
"${PYTHON}" llamas.py \
    --flash-fusion-cache-root "${FLASH_FUSION_CACHE_ROOT}" \
    --react-root "${REACT_ROOT}" \
    --baseline-set FLASH_FUSION_CACHE,REACT_ONLY,AUTOIOT_PAPER,HARGPT_PAPER,LLMSENSE_PAPER \
    --dataset-baseline-set FLASH_FUSION_CACHE,REACT_ONLY,AUTOIOT_PAPER,HARGPT_PAPER,LLMSENSE_PAPER \
    --query-type-baseline-set FLASH_FUSION_CACHE,REACT_ONLY,AUTOIOT_PAPER,HARGPT_PAPER,LLMSENSE_PAPER \
    --cost-query-type-baseline-set FLASH_FUSION_CACHE,FLASH_FUSION_CACHE_HIT,FLASH_FUSION_CACHE_MISS,REACT_ONLY \
    --extra-hard-root "${EXTRA_HARD_ROOT}" \
    --output-dir "../../${BASELINE_VIZ_DIR}"

"${PYTHON}" llamas.py \
    --grounding-only \
    --output-dir "../../${BASELINE_VIZ_DIR}" \
    --grounding-plot-output "../../${BASELINE_VIZ_DIR}/grounding_loss_vs_model_size.png" \
    --grounding-plot-csv "../../${BASELINE_VIZ_DIR}/grounding_loss_vs_model_size.csv"

"${PYTHON}" latencystages.py \
    --flash-fusion-cache-root "${FLASH_FUSION_CACHE_ROOT}" \
    --react-root "${REACT_ROOT}" \
    --baseline-set FLASH_FUSION_CACHE,FLASH_FUSION_CACHE_HIT,FLASH_FUSION_CACHE_MISS,REACT_ONLY,AUTOIOT_PAPER \
    --extra-hard-root "${EXTRA_HARD_ROOT}" \
    --output-dir "../../${BASELINE_VIZ_DIR}"

"${PYTHON}" queryaccuracy.py \
    --results-root "${FLASH_FUSION_CACHE_ROOT}" \
    --output "../../${BASELINE_VIZ_DIR}/accuracy_by_dataset_query_type_summary_ff_cache.csv"

# Ablations: normal-query roots plus the extra-hard supplement for all 20 queries.
"${PYTHON}" llamas.py \
    --flash-fusion-root "${FLASH_FUSION_ROOT}" \
    --ff-no-pruning-root "${FF_NO_PRUNING_ROOT}" \
    --ff-no-planning-root "${FF_NO_PLANNING_ROOT}" \
    --baseline-set FLASH_FUSION,FF_NO_PRUNING,FF_NO_PLANNING \
    --dataset-baseline-set FLASH_FUSION,FF_NO_PRUNING,FF_NO_PLANNING \
    --query-type-baseline-set FLASH_FUSION,FF_NO_PRUNING,FF_NO_PLANNING \
    --cost-query-type-baseline-set FLASH_FUSION,FF_NO_PRUNING,FF_NO_PLANNING \
    --extra-hard-root "${EXTRA_HARD_ROOT}" \
    --output-dir "../../${ABLATION_VIZ_DIR}"

"${PYTHON}" latencystages.py \
    --flash-fusion-root "${FLASH_FUSION_ROOT}" \
    --ff-no-pruning-root "${FF_NO_PRUNING_ROOT}" \
    --ff-no-planning-root "${FF_NO_PLANNING_ROOT}" \
    --baseline-set FLASH_FUSION,FF_NO_PRUNING,FF_NO_PLANNING \
    --extra-hard-root "${EXTRA_HARD_ROOT}" \
    --output-dir "../../${ABLATION_VIZ_DIR}"

"${PYTHON}" queryaccuracy.py \
    --results-root "${FLASH_FUSION_ROOT}" \
    --output "../../${ABLATION_VIZ_DIR}/accuracy_by_dataset_query_type_summary_flash_fusion.csv"

"${PYTHON}" queryaccuracy.py \
    --results-root "${FF_NO_PRUNING_ROOT}" \
    --output "../../${ABLATION_VIZ_DIR}/accuracy_by_dataset_query_type_summary_ff_no_pruning.csv"

"${PYTHON}" queryaccuracy.py \
    --results-root "${FF_NO_PLANNING_ROOT}" \
    --output "../../${ABLATION_VIZ_DIR}/accuracy_by_dataset_query_type_summary_ff_no_planning.csv"

echo "Standard baseline figures: ${REPO_ROOT}/${BASELINE_VIZ_DIR}"
echo "Ablation figures: ${REPO_ROOT}/${ABLATION_VIZ_DIR}"
