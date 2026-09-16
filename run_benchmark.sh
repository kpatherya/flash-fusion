#!/usr/bin/env bash
# =============================================================================
# run_benchmark.sh  —  Flash-Fusion consolidated benchmark
#
# Runs selected baselines across wisdm / mit_ecg / bus with per-baseline latency
# budgets,
# optional smoke test, stage-latency export, and cross-dataset aggregation.
#
# Output layout (nested by baseline -> dataset -> run tag):
#   OUTPUT_ROOT/<BASELINE>/<dataset>/<RUN_TAG>/
#     metrics.csv  raw_results.jsonl  benchmark.log  visualize.log
#     stage_semantic.log  [stage_ff_native.log for FLASH_FUSION]
#   OUTPUT_ROOT/_aggregate/<RUN_TAG>/
#     query_metrics_all_datasets.csv
#     summary_by_dataset_query_type.csv   summary_balanced_by_query_type.csv
#     summary_by_dataset_overall.csv      summary_balanced_overall.csv
#   OUTPUT_ROOT/_smoke/<RUN_TAG>/
#     smoke_status.csv  +  per-baseline x dataset log files
#
# Usage:
#   ./run_benchmark.sh [--wisdm|--ecg|--bus|--all] [options]
#   ./run_benchmark.sh --quick          # RUNS=1, QUERIES=1,5,9, smoke off
#   ./run_benchmark.sh --help
#
# Key env overrides:
#   OUTPUT_ROOT              (default: flashfusion/results/ablations)
#   RUN_TAG                  (default: run_YYYYMMDD_HHMMSS)
#   MODEL                    (default: meta-llama/llama-3.3-70b-instruct)
#   BASELINES                comma-separated
#                            (default: FLASH_FUSION,FF_NO_PRUNING,FF_NO_PLANNING)
#   DATASETS                 comma-separated: wisdm,mit_ecg,bus (default: all 3)
#   QUERIES                  comma-separated IDs or "all" (default: all)
#   RUNS                     integer (default: 1)
#   MAX_LATENCY              if set, overrides all per-baseline budgets
#   MAX_LATENCY_FLASH_FUSION        (default: 60s)
#   MAX_LATENCY_FF_NO_PRUNING       (default: 60s)
#   MAX_LATENCY_FF_NO_PLANNING      (default: 60s)
#   MAX_LATENCY_REACT_ONLY          (default: 60s)
#   MAX_LATENCY_HARGPT_PAPER        (default: 300s)
#   MAX_LATENCY_LLMSENSE_PAPER      (default: 300s)
#   MAX_LATENCY_AUTOIOT_PAPER       (default: 360s)
#   SMOKE_TEST               1=run smoke tests before main run (default: 1)
#   SMOKE_QUERIES            (default: 1,5,9)
#   SMOKE_MAX_LATENCY        (default: 30s)
#   SMOKE_ABORT_ON_FAIL      1=abort if smoke fails (default: 1)
#   AUTOIOT_DEBUG            1=enable AutoIOT debug logging (propagated to subprocess)
#   DEBUG_BENCHMARK          1=verbose debug output + API connectivity probe
# =============================================================================

: <<'NOTE'
NOTE: commands to run (july 2, 2026) ---

# Run once per baseline; paste into terminal sequentially.
RUN_TAG=july26_full RUNS=3 BASELINES=FLASH_FUSION    ./run_benchmark.sh
RUN_TAG=july26_full RUNS=3 BASELINES=HARGPT_PAPER    ./run_benchmark.sh
RUN_TAG=july26_full RUNS=3 BASELINES=LLMSENSE_PAPER  ./run_benchmark.sh
RUN_TAG=july26_full RUNS=3 BASELINES=REACT_ONLY      ./run_benchmark.sh
RUN_TAG=july26_full RUNS=3 BASELINES=AUTOIOT_PAPER   ./run_benchmark.sh
NOTE

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    set -a; source "${SCRIPT_DIR}/.env"; set +a
fi

export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
export TRANSFORMERS_NO_ADVISORY_WARNINGS="${TRANSFORMERS_NO_ADVISORY_WARNINGS:-1}"

if [[ -f ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

# ── Default configuration ─────────────────────────────────────────────────────
OUTPUT_ROOT="${OUTPUT_ROOT:-flashfusion/results/ablations}"
RUN_TAG="${RUN_TAG:-run_$(date +%Y%m%d_%H%M%S)}"
MODEL="${MODEL:-meta-llama/llama-3.3-70b-instruct}"
BASELINES="${BASELINES:-FLASH_FUSION,FF_NO_PRUNING,FF_NO_PLANNING}"
DATASETS="${DATASETS:-wisdm,mit_ecg,bus}"
QUERIES="${QUERIES:-all}"
RUNS="${RUNS:-1}"

MAX_LATENCY_FLASH_FUSION="${MAX_LATENCY_FLASH_FUSION:-60.0}"
MAX_LATENCY_FF_NO_PRUNING="${MAX_LATENCY_FF_NO_PRUNING:-60.0}"
MAX_LATENCY_FF_NO_PLANNING="${MAX_LATENCY_FF_NO_PLANNING:-60.0}"
MAX_LATENCY_REACT_ONLY="${MAX_LATENCY_REACT_ONLY:-60.0}"
MAX_LATENCY_HARGPT_PAPER="${MAX_LATENCY_HARGPT_PAPER:-300.0}"
MAX_LATENCY_LLMSENSE_PAPER="${MAX_LATENCY_LLMSENSE_PAPER:-300.0}"
MAX_LATENCY_AUTOIOT_PAPER="${MAX_LATENCY_AUTOIOT_PAPER:-360.0}"
MAX_LATENCY="${MAX_LATENCY:-}"

SMOKE_TEST="${SMOKE_TEST:-1}"
SMOKE_QUERIES="${SMOKE_QUERIES:-1,5,9}"
SMOKE_MAX_LATENCY="${SMOKE_MAX_LATENCY:-30.0}"
SMOKE_ABORT_ON_FAIL="${SMOKE_ABORT_ON_FAIL:-1}"

AUTOIOT_DEBUG="${AUTOIOT_DEBUG:-0}"
export AUTOIOT_DEBUG  # propagate into benchmark subprocess

DEBUG_BENCHMARK="${DEBUG_BENCHMARK:-0}"

WISDM_DATA="${WISDM_DATA:-data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt}"
MIT_ECG_DATA="${MIT_ECG_DATA:-data/AutoIOT_dataset/ECG.0/MIT_arrythmia_v1.txt}"
BUS_DATA="${BUS_DATA:-data/bus/bus_data_enriched_behavior.csv}"
GT_WISDM="${GT_WISDM:-flashfusion/eval/ground_truth/ground_truth_wisdm.json}"
GT_MIT_ECG="${GT_MIT_ECG:-flashfusion/eval/ground_truth/ground_truth_mit_ecg.json}"
GT_BUS="${GT_BUS:-flashfusion/eval/ground_truth/ground_truth_bus.json}"

# ── CLI parsing ───────────────────────────────────────────────────────────────
print_help() {
    cat <<'EOF'
Usage:
  ./run_benchmark.sh [--wisdm|--ecg|--bus|--all] [options]

Dataset selection (default: all three):
  --all                  wisdm + mit_ecg + bus (default)
  --wisdm                Only wisdm
  --ecg                  Only mit_ecg
  --bus                  Only bus

Options:
  --baselines <csv>      Comma-separated baselines
                           (default: FLASH_FUSION,FF_NO_PRUNING,FF_NO_PLANNING)
  --queries <csv|all>    Query IDs e.g. 1,5,9 or all (default: all)
  --runs <n>             Number of repeated runs (default: 1)
  --max-latency <s>      Single timeout for all baselines (overrides per-baseline)
  --model <name>         LLM model override
  --no-smoke             Skip smoke test
  --quick                RUNS=1, QUERIES=1,5,9, smoke off
  -h, --help             Show this help

Output: OUTPUT_ROOT/<BASELINE>/<dataset>/<RUN_TAG>/
Default OUTPUT_ROOT: flashfusion/results/ablations

Debug env vars: AUTOIOT_DEBUG=1, DEBUG_BENCHMARK=1
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)              DATASETS="wisdm,mit_ecg,bus"; shift ;;
        --wisdm)            DATASETS="wisdm"; shift ;;
        --ecg|--mit-ecg|--mit_ecg) DATASETS="mit_ecg"; shift ;;
        --bus)              DATASETS="bus"; shift ;;
        --baselines)        BASELINES="${2:-}"; shift 2 ;;
        --queries)          QUERIES="${2:-}"; shift 2 ;;
        --runs)             RUNS="${2:-}"; shift 2 ;;
        --max-latency)      MAX_LATENCY="${2:-}"; shift 2 ;;
        --model)            MODEL="${2:-}"; shift 2 ;;
        --no-smoke)         SMOKE_TEST="0"; shift ;;
        --quick)            RUNS="1"; QUERIES="1,5,9"; SMOKE_TEST="0"; shift ;;
        -h|--help)          print_help; exit 0 ;;
        *) echo "ERROR: Unknown option: $1"; echo "Run ./run_benchmark.sh --help"; exit 1 ;;
    esac
done

IFS=',' read -r -a BASELINE_LIST <<< "${BASELINES}"
IFS=',' read -r -a DATASET_LIST  <<< "${DATASETS}"

# ── Helper functions ──────────────────────────────────────────────────────────
ts()  { date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*"; }

require_file() {
    if [[ ! -f "$1" ]]; then echo "[ERROR] Required file not found: $1" >&2; exit 1; fi
}

dataset_data_path() {
    case "$1" in
        wisdm)   echo "${WISDM_DATA}" ;;
        mit_ecg) echo "${MIT_ECG_DATA}" ;;
        bus)     echo "${BUS_DATA}" ;;
        *) echo "[ERROR] Unknown dataset: $1" >&2; return 1 ;;
    esac
}

dataset_gt_path() {
    case "$1" in
        wisdm)   echo "${GT_WISDM}" ;;
        mit_ecg) echo "${GT_MIT_ECG}" ;;
        bus)     echo "${GT_BUS}" ;;
        *) echo "[ERROR] Unknown dataset: $1" >&2; return 1 ;;
    esac
}

baseline_max_latency() {
    local baseline="$1"
    if [[ -n "${MAX_LATENCY}" ]]; then echo "${MAX_LATENCY}"; return; fi
    local varname="MAX_LATENCY_${baseline}"
    echo "${!varname:-60.0}"
}

run_stage_latency_export() {
    local baseline="$1" ds="$2" target_dir="$3" data_path="$4"
    local tmp_stage
    tmp_stage="$(mktemp -d)"

    local qargs=""
    if [[ "${QUERIES}" != "all" ]]; then
        IFS=',' read -r -a qids <<< "${QUERIES}"
        qargs=" --query-ids"
        for qid in "${qids[@]}"; do
            qid="$(echo "${qid}" | xargs)"
            [[ -n "${qid}" ]] && qargs+=" ${qid}"
        done
    fi

    eval "\"${PYTHON}\" -u flashfusion/miniexp/latencystages.py \
        --mode semantic_single \
        --baseline \"${baseline}\" \
        --datasets \"${ds}\" \
        --model \"${MODEL}\" \
        --output-dir \"${tmp_stage}\" \
        --data-path-wisdm \"${data_path}\" \
        --data-path-mit-ecg \"${data_path}\" \
        --data-path-bus \"${data_path}\"${qargs}" \
        >"${target_dir}/stage_semantic.log" 2>&1 || true

    local baseline_lower
    baseline_lower="$(echo "${baseline}" | tr '[:upper:]' '[:lower:]')"
    local src_sem="${tmp_stage}/semantic_single/${baseline_lower}"
    [[ -d "${src_sem}" ]] && cp -f "${src_sem}"/* "${target_dir}/" 2>/dev/null || true

    if [[ "${baseline}" == "FLASH_FUSION" ]]; then
        eval "\"${PYTHON}\" -u flashfusion/miniexp/latencystages.py \
            --mode ff_only \
            --datasets \"${ds}\" \
            --model \"${MODEL}\" \
            --output-dir \"${tmp_stage}\" \
            --data-path-wisdm \"${data_path}\" \
            --data-path-mit-ecg \"${data_path}\" \
            --data-path-bus \"${data_path}\"${qargs}" \
            >"${target_dir}/stage_ff_native.log" 2>&1 || true
        local src_ff="${tmp_stage}/flash_fusion_native"
        [[ -d "${src_ff}" ]] && cp -f "${src_ff}"/* "${target_dir}/" 2>/dev/null || true
    fi

    rm -rf "${tmp_stage}"
}

run_smoke_tests() {
    local smoke_root="${OUTPUT_ROOT}/_smoke/${RUN_TAG}"
    mkdir -p "${smoke_root}"
    local smoke_csv="${smoke_root}/smoke_status.csv"
    echo "baseline,dataset,status,reason,rows,error_rows,log_file" > "${smoke_csv}"

    local baseline ds data_path gt_path smoke_out smoke_log smoke_latency
    for baseline in "${BASELINE_LIST[@]}"; do
        for ds in "${DATASET_LIST[@]}"; do
            data_path="$(dataset_data_path "${ds}")"
            gt_path="$(dataset_gt_path "${ds}")"
            smoke_out="${smoke_root}/${baseline}/${ds}"
            smoke_log="${smoke_root}/${baseline}_${ds}.log"
            mkdir -p "${smoke_out}"

            smoke_latency="$(baseline_max_latency "${baseline}")"
            if (( $(echo "${SMOKE_MAX_LATENCY} < ${smoke_latency}" | bc -l) )); then
                smoke_latency="${SMOKE_MAX_LATENCY}"
            fi
            log "[SMOKE] baseline=${baseline} dataset=${ds} max_latency=${smoke_latency}s"

            if ! "${PYTHON}" -u -m flashfusion.eval.benchmark \
                --dataset "${ds}" \
                --data "${data_path}" \
                --ground-truth "${gt_path}" \
                --baselines "${baseline}" \
                --queries "${SMOKE_QUERIES}" \
                --runs 1 \
                --model "${MODEL}" \
                --max-query-latency "${smoke_latency}" \
                --ground-truth-measurement llm \
                --output "${smoke_out}" \
                >"${smoke_log}" 2>&1; then
                echo "${baseline},${ds},fail,benchmark_command_failed,0,0,${smoke_log}" >> "${smoke_csv}"
                continue
            fi

            local status_line
            status_line="$("${PYTHON}" - "${smoke_out}" <<'PYEOF'
import json, sys
from pathlib import Path
import pandas as pd
out_dir = Path(sys.argv[1])
metrics = out_dir / "metrics.csv"
raw = out_dir / "raw_results.jsonl"
if not metrics.exists():
    print("fail,missing_metrics,0,0"); raise SystemExit(0)
df = pd.read_csv(metrics)
if df.empty:
    print("fail,empty_metrics,0,0"); raise SystemExit(0)
rows = int(len(df))
processed = bool(((df.get("executed", False) == True) | (df.get("rejected", False) == True)).any())
if not processed:
    print(f"fail,no_executed_or_rejected,{rows},0"); raise SystemExit(0)
err_rows = 0
if raw.exists():
    with raw.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(obj.get("answer", "")).startswith("[ERROR"):
                err_rows += 1
verdict = "fail,all_rows_error" if err_rows >= rows else "pass,ok"
print(f"{verdict},{rows},{err_rows}")
PYEOF
)"
            IFS=',' read -r smoke_status smoke_reason smoke_rows smoke_err <<< "${status_line}"
            echo "${baseline},${ds},${smoke_status},${smoke_reason},${smoke_rows},${smoke_err},${smoke_log}" >> "${smoke_csv}"
        done
    done

    log "[SMOKE] Wrote status: ${smoke_csv}"
    local fail_count
    fail_count="$(( $(grep -c ',fail,' "${smoke_csv}" || true) ))"
    if [[ "${fail_count}" -gt 0 ]]; then
        log "[SMOKE] FAILURES=${fail_count}"
        if [[ "${SMOKE_ABORT_ON_FAIL}" == "1" ]]; then
            echo "[ERROR] Smoke test failed. Aborting. See ${smoke_csv}" >&2; exit 1
        fi
    else
        log "[SMOKE] All baseline x dataset checks passed"
    fi
}

# ── Validate pre-conditions ───────────────────────────────────────────────────
if [[ -z "${OPENROUTER_API_KEY:-}" && -z "${GROQ_API_KEY:-}" ]]; then
    echo "[ERROR] Missing API key. Set OPENROUTER_API_KEY or GROQ_API_KEY." >&2; exit 1
fi

if [[ "${BASELINES}" == *"AUTOIOT_PAPER"* && -z "${TAVILY_API_KEY:-}" ]]; then
    echo "[ERROR] AUTOIOT_PAPER requires TAVILY_API_KEY." >&2; exit 1
fi

if ! "${PYTHON}" -c "import matplotlib" >/dev/null 2>&1; then
    echo "[ERROR] matplotlib not installed. Run: ${PYTHON} -m pip install -r requirements.txt" >&2; exit 1
fi

for ds in "${DATASET_LIST[@]}"; do
    require_file "$(dataset_data_path "${ds}")"
    require_file "$(dataset_gt_path "${ds}")"
done

mkdir -p "${OUTPUT_ROOT}" "${OUTPUT_ROOT}/_aggregate/${RUN_TAG}"

# ── Debug probe ───────────────────────────────────────────────────────────────
if [[ "${DEBUG_BENCHMARK}" == "1" ]]; then
    log "[DEBUG] Python        : ${PYTHON}"
    log "[DEBUG] OUTPUT_ROOT   : ${OUTPUT_ROOT}"
    log "[DEBUG] RUN_TAG       : ${RUN_TAG}"
    log "[DEBUG] Baselines     : ${BASELINE_LIST[*]}"
    log "[DEBUG] Datasets      : ${DATASET_LIST[*]}"
    log "[DEBUG] Queries       : ${QUERIES}  Runs: ${RUNS}"
    log "[DEBUG] AUTOIOT_DEBUG : ${AUTOIOT_DEBUG}"
    log "[DEBUG] Probing OpenRouter API..."
    _HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        -H "Authorization: Bearer ${OPENROUTER_API_KEY:-${GROQ_API_KEY:-}}" \
        "https://openrouter.ai/api/v1/models" 2>/dev/null || true)
    log "[DEBUG] openrouter.ai/models HTTP status: ${_HTTP_STATUS}"
    [[ "${_HTTP_STATUS}" != "200" ]] && log "[DEBUG] WARNING: non-200 — check key / connectivity"
fi

# ── Opening banner ────────────────────────────────────────────────────────────
AGG_ROOT="${OUTPUT_ROOT}/_aggregate/${RUN_TAG}"
echo ""
echo "================================================================"
echo "  Flash-Fusion  --  Consolidated Benchmark"
echo "  Timestamp    : $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Run tag      : ${RUN_TAG}"
echo "  Baselines    : ${BASELINES}"
echo "  Datasets     : ${DATASETS}"
echo "  Queries      : ${QUERIES}   Runs: ${RUNS}"
echo "  Output root  : ${OUTPUT_ROOT}"
if [[ -n "${MAX_LATENCY}" ]]; then
    echo "  Max latency  : ${MAX_LATENCY}s (all baselines)"
else
    echo "  Max latency  : FF=${MAX_LATENCY_FLASH_FUSION}s REACT=${MAX_LATENCY_REACT_ONLY}s HARGPT=${MAX_LATENCY_HARGPT_PAPER}s LLMSENSE=${MAX_LATENCY_LLMSENSE_PAPER}s AUTOIOT=${MAX_LATENCY_AUTOIOT_PAPER}s"
fi
echo "  Smoke test   : ${SMOKE_TEST} (queries=${SMOKE_QUERIES}, max=${SMOKE_MAX_LATENCY}s, abort=${SMOKE_ABORT_ON_FAIL})"
echo "  AUTOIOT_DEBUG: ${AUTOIOT_DEBUG}"
echo "================================================================"

# ── Smoke tests ───────────────────────────────────────────────────────────────
if [[ "${SMOKE_TEST}" == "1" ]]; then
    run_smoke_tests
fi

# ── Main benchmark loop (baseline x dataset) ──────────────────────────────────
for baseline in "${BASELINE_LIST[@]}"; do
    for ds in "${DATASET_LIST[@]}"; do
        DATA_PATH="$(dataset_data_path "${ds}")"
        GT_PATH="$(dataset_gt_path "${ds}")"
        TARGET_DIR="${OUTPUT_ROOT}/${baseline}/${ds}/${RUN_TAG}"
        mkdir -p "${TARGET_DIR}"

        QUERY_MAX_LATENCY="$(baseline_max_latency "${baseline}")"
        log "[Benchmark] baseline=${baseline} dataset=${ds} max_latency=${QUERY_MAX_LATENCY}s -> ${TARGET_DIR}"

        "${PYTHON}" -u -m flashfusion.eval.benchmark \
            --dataset "${ds}" \
            --data "${DATA_PATH}" \
            --ground-truth "${GT_PATH}" \
            --baselines "${baseline}" \
            --queries "${QUERIES}" \
            --runs "${RUNS}" \
            --model "${MODEL}" \
            --max-query-latency "${QUERY_MAX_LATENCY}" \
            --ground-truth-measurement llm \
            --output "${TARGET_DIR}" \
            2>&1 | tee "${TARGET_DIR}/benchmark.log"

        log "[Visualize] baseline=${baseline} dataset=${ds}"
        "${PYTHON}" -m flashfusion.eval.visualize_comparison \
            --metrics "${TARGET_DIR}/metrics.csv" \
            --dataset "${ds}" \
            --accuracy-column gt_score \
            --title "${baseline} (${ds})" \
            --output "${TARGET_DIR}" \
            2>&1 | tee "${TARGET_DIR}/visualize.log" || true

        log "[Stage latency] baseline=${baseline} dataset=${ds}"
        run_stage_latency_export "${baseline}" "${ds}" "${TARGET_DIR}" "${DATA_PATH}"
    done
done

# ── Cross-dataset aggregation ─────────────────────────────────────────────────
log "[Summary] Building cross-dataset aggregate tables -> ${AGG_ROOT}"
"${PYTHON}" - "${OUTPUT_ROOT}" "${RUN_TAG}" "${AGG_ROOT}" <<'PYEOF'
import sys
from pathlib import Path
import pandas as pd
from flashfusion.eval.queries import get_queries

output_root = Path(sys.argv[1])
run_tag     = sys.argv[2]
out_root    = Path(sys.argv[3])
out_root.mkdir(parents=True, exist_ok=True)

def to_query_type(c: str) -> str:
    x = (c or "").strip().lower()
    if x == "direct":                      return "direct"
    if x in {"intermediate", "reasoning"}: return "reasoning"
    return "oos"

rows = []
for baseline_dir in sorted(output_root.iterdir()):
    if not baseline_dir.is_dir() or baseline_dir.name.startswith("_"):
        continue
    baseline = baseline_dir.name
    for ds in ("wisdm", "mit_ecg", "bus"):
        metrics_path = baseline_dir / ds / run_tag / "metrics.csv"
        if not metrics_path.exists():
            continue
        df = pd.read_csv(metrics_path)
        if df.empty:
            continue
        qmap = {int(q["id"]): str(q.get("complexity", "")) for q in get_queries(ds)}
        df["dataset"]      = ds
        df["baseline"]     = baseline
        df["query_id"]     = df["query_id"].astype(int)
        df["complexity"]   = df["query_id"].map(qmap).fillna("")
        df["query_type"]   = df["complexity"].map(to_query_type)
        df["total_tokens"] = df["input_tokens"].astype(float) + df["output_tokens"].astype(float)
        rows.append(df)

if not rows:
    print("  Warning: no metrics.csv files found; skipping aggregate."); raise SystemExit(0)

combined = pd.concat(rows, ignore_index=True)
combined.to_csv(out_root / "query_metrics_all_datasets.csv", index=False)

agg_cols = {
    "accuracy":      ("gt_score",      "mean"),
    "latency_s":     ("latency_s",     "mean"),
    "input_tokens":  ("input_tokens",  "mean"),
    "output_tokens": ("output_tokens", "mean"),
    "total_tokens":  ("total_tokens",  "mean"),
    "cost_usd":      ("cost_usd",      "mean"),
    "executed_rate": ("executed",      "mean"),
    "rejected_rate": ("rejected",      "mean"),
    "n":             ("query_id",      "count"),
}

by_ds_qt = (combined
    .groupby(["dataset", "query_type", "baseline"], as_index=False).agg(**agg_cols)
    .sort_values(["dataset", "query_type", "baseline"]))
by_ds_qt.to_csv(out_root / "summary_by_dataset_query_type.csv", index=False)

balanced_qt = (by_ds_qt
    .groupby(["query_type", "baseline"], as_index=False)
    .agg(accuracy=("accuracy","mean"), latency_s=("latency_s","mean"),
         input_tokens=("input_tokens","mean"), output_tokens=("output_tokens","mean"),
         total_tokens=("total_tokens","mean"), cost_usd=("cost_usd","mean"),
         executed_rate=("executed_rate","mean"), rejected_rate=("rejected_rate","mean"))
    .sort_values(["query_type", "baseline"]))
balanced_qt.to_csv(out_root / "summary_balanced_by_query_type.csv", index=False)

by_ds = (combined
    .groupby(["dataset", "baseline"], as_index=False).agg(**agg_cols)
    .sort_values(["dataset", "baseline"]))
by_ds.to_csv(out_root / "summary_by_dataset_overall.csv", index=False)

overall = (by_ds
    .groupby(["baseline"], as_index=False)
    .agg(accuracy=("accuracy","mean"), latency_s=("latency_s","mean"),
         input_tokens=("input_tokens","mean"), output_tokens=("output_tokens","mean"),
         total_tokens=("total_tokens","mean"), cost_usd=("cost_usd","mean"),
         executed_rate=("executed_rate","mean"), rejected_rate=("rejected_rate","mean"))
    .sort_values(["baseline"]))
overall.to_csv(out_root / "summary_balanced_overall.csv", index=False)

for p in ["query_metrics_all_datasets.csv", "summary_by_dataset_query_type.csv",
          "summary_balanced_by_query_type.csv", "summary_by_dataset_overall.csv",
          "summary_balanced_overall.csv"]:
    print(f"  Wrote {out_root / p}")

print()
try:
    from tabulate import tabulate
    print("  Overall balanced summary (mean of per-dataset means):")
    print(tabulate(overall.round(4), headers="keys", tablefmt="github",
                   showindex=False, floatfmt=".4f"))
except ImportError:
    print(overall.round(4).to_string(index=False))
PYEOF

# ── Closing banner ─────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  Complete!"
echo ""
echo "  Output root  : ${OUTPUT_ROOT}"
echo "  Run tag      : ${RUN_TAG}"
echo ""
echo "  Per-run outputs : ${OUTPUT_ROOT}/<BASELINE>/<dataset>/${RUN_TAG}/"
echo "  Aggregate tables: ${AGG_ROOT}/"
if [[ "${SMOKE_TEST}" == "1" ]]; then
    echo "  Smoke report    : ${OUTPUT_ROOT}/_smoke/${RUN_TAG}/smoke_status.csv"
fi
echo "================================================================"
echo ""
