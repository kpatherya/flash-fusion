#!/usr/bin/env bash
# =============================================================================
# run_react_flashfusion_qwen_all_datasets.sh
#
# Run Flash-Fusion ablation benchmarks sequentially across bus, WISDM,
# and MIT ECG.
#
# Output layout:
#   flashfusion/results/ablations/
#     FLASH_FUSION/
#       bus/
#       wisdm/
#       mit_ecg/
#     FF_NO_PRUNING/
#       bus/
#       wisdm/
#       mit_ecg/
#     FF_NO_PLANNING/
#       bus/
#       wisdm/
#       mit_ecg/
#
# Usage:
#   chmod +x flashfusion/eval/run_react_flashfusion_qwen_all_datasets.sh
#   ./flashfusion/eval/run_react_flashfusion_qwen_all_datasets.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.venv/bin/activate"
fi

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
fi

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON="${PYTHON:-${REPO_ROOT}/.venv/bin/python}"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="${PYTHON:-python3}"
else
    PYTHON="${PYTHON:-python}"
fi

if [[ -z "${OPENROUTER_API_KEY:-}" && -z "${GROQ_API_KEY:-}" ]]; then
    echo "[ERROR] Missing API key. Set OPENROUTER_API_KEY or GROQ_API_KEY." >&2
    exit 1
fi

OUTPUT_ROOT="${OUTPUT_ROOT:-flashfusion/results/ablations}"
RUNS="${RUNS:-3}"

ts() {
    date "+%Y-%m-%d %H:%M:%S"
}

log() {
    echo "[$(ts)] $*"
}

run_one() {
    local baseline="$1"
    local dataset="$2"
    local data_path="$3"
    local gt_path="$4"
    local output_dir="${OUTPUT_ROOT}/${baseline}/${dataset}"

    mkdir -p "${output_dir}"

    log "[Start] baseline=${baseline} dataset=${dataset} output=${output_dir}"
    "${PYTHON}" -u -m flashfusion.eval.benchmark \
      --dataset "${dataset}" \
      --data "${data_path}" \
      --baselines "${baseline}" \
      --queries all \
      --runs "${RUNS}" \
      --ground-truth "${gt_path}" \
      --output "${output_dir}"
    log "[Done] baseline=${baseline} dataset=${dataset}"
}

log "Running FLASH_FUSION, FF_NO_PRUNING, and FF_NO_PLANNING across all three datasets"
log "Output root: ${OUTPUT_ROOT}"
log "Runs per benchmark: ${RUNS}"

for baseline in FLASH_FUSION FF_NO_PRUNING FF_NO_PLANNING; do
    run_one \
      "${baseline}" \
      bus \
      data/bus/bus_data_enriched_behavior.csv \
      flashfusion/eval/ground_truth/ground_truth_bus.json

    run_one \
      "${baseline}" \
      wisdm \
      data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt \
      flashfusion/eval/ground_truth/ground_truth_wisdm.json

    run_one \
      "${baseline}" \
      mit_ecg \
      data/AutoIOT_dataset/ECG.0/MIT_arrythmia_v1.txt \
      flashfusion/eval/ground_truth/ground_truth_mit_ecg.json
done

log "All runs complete. Results under ${OUTPUT_ROOT}/"