#!/usr/bin/env bash
# Run the grounding smoke benchmark across all datasets.
# Smoke test before a full run (three API calls, one query/run per dataset):
# RUNS=1 QUERY_VERSIONS=v1 QUERY_IDS=2 OUTPUT_ROOT=flashfusion/results/grounding_smoke \
#   bash flashfusion/eval/run_grounding_benchmark.sh
#
# The default configuration produces 16 skeleton-bearing query ids x 3 query
# versions x 3 datasets = 144 result rows for one stage12 model. Out-of-scope
# rejection queries (9-12) intentionally do not participate.

# (KAUSAR) - can create table comparing model grounding capabilities across the three dimensions: accuracy / grounding error, latency, cost; far better coverage!

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.venv/bin/activate"
fi

if [[ -f "${REPO_ROOT}/.keys" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.keys"
    set +a
fi

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON="${PYTHON:-${REPO_ROOT}/.venv/bin/python}"
else
    PYTHON="${PYTHON:-python3}"
fi

PRIMARY_MODEL="${PRIMARY_MODEL:-qwen/qwen3-max}"
LIGHT_MODEL="${LIGHT_MODEL:-meta-llama/llama-3.2-3b-instruct}"
LIGHT_MODELS="${LIGHT_MODELS:-${LIGHT_MODEL}}"
RUNS="${RUNS:-3}"
QUERY_VERSIONS="${QUERY_VERSIONS:-v1,v2,v3}"
OUTPUT_ROOT="${OUTPUT_ROOT:-flashfusion/results/grounding}"
CACHE_PATH="${CACHE_PATH:-flashfusion/eval/cache/cache_registry.json}"

QUERY_IDS="${QUERY_IDS:-1,2,3,4,5,6,7,8,13,14,15,16,17,18,19,20}"
QUERY_IDS_BUS="${QUERY_IDS_BUS:-${QUERY_IDS}}"
QUERY_IDS_WISDM="${QUERY_IDS_WISDM:-${QUERY_IDS}}"
QUERY_IDS_MIT_ECG="${QUERY_IDS_MIT_ECG:-${QUERY_IDS}}"
GROUND_TRUTH_JSON="${GROUND_TRUTH_JSON:-flashfusion/results/grounding/typed_plan_ground_truth_full.json}"

for dataset in bus wisdm mit_ecg; do
    output_dir="${OUTPUT_ROOT}/${dataset}"
    mkdir -p "${output_dir}"
    case "${dataset}" in
        bus) query_ids="${QUERY_IDS_BUS}" ;;
        wisdm) query_ids="${QUERY_IDS_WISDM}" ;;
        mit_ecg) query_ids="${QUERY_IDS_MIT_ECG}" ;;
    esac
    echo "[grounding] dataset=${dataset} models=${LIGHT_MODELS} runs=${RUNS}"
    "${PYTHON}" -u -m flashfusion.eval.benchmark_grounding \
        --dataset "${dataset}" \
        --model "${PRIMARY_MODEL}" \
        --models "${LIGHT_MODELS}" \
        --runs "${RUNS}" \
        --query-versions "${QUERY_VERSIONS}" \
        --query-ids "${query_ids}" \
        --typed-plan-ground-truth-json "${GROUND_TRUTH_JSON}" \
        --require-typed-plan-ground-truth \
        --cache-path "${CACHE_PATH}" \
        --output-dir "${output_dir}" \
        --save-traces
done

echo "[grounding] complete: ${OUTPUT_ROOT}"