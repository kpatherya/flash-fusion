#!/usr/bin/env bash
# =============================================================================
# run_extra_hard_all_datasets.sh
#
# Run Flash-Fusion, ReAct, and Flash-Fusion with cache across bus, WISDM,
# and MIT ECG on the extra-hard query slice (query IDs 17-20).
#
# Output layout:
#   results/extra_hard/
#     FLASH_FUSION/{bus,wisdm,mit_ecg}/
#     REACT_ONLY/{bus,wisdm,mit_ecg}/
#     FLASH_FUSION_CACHE/{bus,wisdm,mit_ecg}/
#
# Usage:
#   chmod +x flashfusion/eval/run_extra_hard_all_datasets.sh
#   ./flashfusion/eval/run_extra_hard_all_datasets.sh
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

OUTPUT_ROOT="${OUTPUT_ROOT:-flashfusion/eval/results/extra_hard}"
RUNS="${RUNS:-3}"
QUERY_IDS="${QUERY_IDS:-17,18,19,20}"
CACHE_PATH="${CACHE_PATH:-flashfusion/eval/cache/cache_registry.json}"
BENCHMARK_EXTRA_ARGS="${BENCHMARK_EXTRA_ARGS:-}"

ts() {
    date "+%Y-%m-%d %H:%M:%S"
}

log() {
    echo "[$(ts)] $*"
}

semantic_cache_path() {
    local dataset="$1"
    case "${dataset}" in
        bus)
            echo "flashfusion/eval/cache/semantic_registry_bus_v1.json"
            ;;
        wisdm)
            echo "flashfusion/eval/cache/semantic_registry_wisdm_v1.json"
            ;;
        mit_ecg)
            echo "flashfusion/eval/cache/semantic_registry_mit_ecg_v1.json"
            ;;
        *)
            echo "[ERROR] Unknown dataset: ${dataset}" >&2
            return 1
            ;;
    esac
}

run_one() {
    local baseline="$1"
    local dataset="$2"
    local data_path="$3"
    local gt_path="$4"
    local output_dir="${OUTPUT_ROOT}/${baseline}/${dataset}"

    mkdir -p "${output_dir}"

    local args=(
        -u -m flashfusion.eval.benchmark
        --dataset "${dataset}"
        --data "${data_path}"
        --baselines "${baseline}"
        --queries "${QUERY_IDS}"
        --runs "${RUNS}"
        --ground-truth "${gt_path}"
        --output "${output_dir}"
    )

    if [[ "${baseline}" == "FLASH_FUSION_CACHE" ]]; then
        args+=(
            --cache-path "${CACHE_PATH}"
            --semantic-cache-path "$(semantic_cache_path "${dataset}")"
        )
    fi

    log "[Start] baseline=${baseline} dataset=${dataset} queries=${QUERY_IDS} output=${output_dir}"
    # shellcheck disable=SC2086
    "${PYTHON}" "${args[@]}" ${BENCHMARK_EXTRA_ARGS}
    log "[Done] baseline=${baseline} dataset=${dataset}"
}

log "Running extra-hard query slice across all three datasets"
log "Output root: ${OUTPUT_ROOT}"
log "Runs per benchmark: ${RUNS}"
log "Query IDs: ${QUERY_IDS}"

for baseline in REACT_ONLY; do
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