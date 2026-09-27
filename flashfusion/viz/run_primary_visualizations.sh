#!/usr/bin/env bash
# Generate the primary baseline and ablation visualizations.
#
# Usage from the repository root:
#   ./flashfusion/viz/run_primary_visualizations.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON="${REPO_ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    PYTHON="python"
fi

OUTPUT_ROOT="${VIZ_ROOT:-${REPO_ROOT}/results/primary_visualizations}"
ALIGN_MODEL="${ALIGN_FF_FULL_MODEL:-mistralai/ministral-8b-2512}"
STRICT_ARGS=()
if [[ "${STRICT:-1}" == "1" ]]; then
    STRICT_ARGS+=(--strict)
fi
ALIGN_ARGS=(--align-ff-full-model "${ALIGN_MODEL}")
if [[ "${NO_ALIGN_FF_FULL:-0}" == "1" ]]; then
    ALIGN_ARGS+=(--no-align-ff-full)
fi

cd "${REPO_ROOT}"
"${PYTHON}" "${SCRIPT_DIR}/primary_visualizations.py" \
    --mode "${MODE:-all}" \
    --output-root "${OUTPUT_ROOT}" \
    "${ALIGN_ARGS[@]}" \
    "${STRICT_ARGS[@]}"
