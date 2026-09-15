"""
config.py — Flash-Fusion global constants.

Import this module everywhere instead of hard-coding values.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# LLM model pricing (USD per 1M tokens, as of 2026-05)
# Override individual rates with environment variables:
#   MODEL_RATE_INPUT_<MODEL_KEY>   e.g. MODEL_RATE_INPUT_LLAMA_3_3_70B=0.59
# ---------------------------------------------------------------------------
MODEL_RATE_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    "meta-llama/llama-3.3-70b-instruct": {
        "input": 0.59,
        "output": 0.79,
    },
    "meta-llama/llama-3.3-70b-versatile": {
        "input": 0.59,
        "output": 0.79,
    },
    "meta-llama/llama-4-scout-17b-16e-instruct": {
        "input": 0.11,
        "output": 0.34,
    },
    "openrouter/auto": {
        "input": 0.15,
        "output": 0.60,
    },
    "meta-llama/llama-3.1-8b-instruct": {
        "input": 0.05,
        "output": 0.08,
    },
    "qwen/qwen3-30b-a3b": {
        "input": 0.12,
        "output": 0.50,
    },
    "qwen/qwen3-30b-a3b-instruct-2507": {
        "input": 0.05,
        "output": 0.19,
    },
    "meta-llama/llama-3.2-1b-instruct": {
        "input": 0.027,
        "output": 0.201,
    },
    # OpenRouter listing used in grounding-size benchmark.
    # If provider pricing changes, override with MODEL_RATE_INPUT/OUTPUT env vars.
    "meta-llama/llama-3.2-3b-instruct": {
        "input": 0.04,
        "output": 0.08,
    },
    # Groq native model ID used for the Flash-Fusion cache/S1/S2 light model.
    # llama-3.1-8b-instant was retired by Groq; replaced with allam-2-7b.
    "allam-2-7b": {
        "input": 0.00,
        "output": 0.00,
    },
    # Local Ollama-served light model; no per-token API cost.
    "ollama/qwen2.5:3b-instruct": {
        "input": 0.00,
        "output": 0.00,
    },
    "google/gemma-4-31b-it": {
        "input": 0.12,
        "output": 0.35,
    },
    "qwen/qwen-2.5-7b-instruct": {
        "input": 0.07,
        "output": 0.07,
    },
    # OpenRouter listing used in grounding-size benchmark.
    "google/gemma-3-12b-it": {
        "input": 0.10,
        "output": 0.30,
    },
    # OpenRouter listing used in grounding-size benchmark.
    "qwen/qwen3-14b": {
        "input": 0.08,
        "output": 0.24,
    },
    "qwen/qwen-2.5-72b-instruct": {
        "input": 0.12,
        "output": 0.39,
    },
    "ibm-granite/granite-4.2-8b": {
        "input": 0.05,
        "output": 0.10,
    },
    # Explicit `cache_control` prompt caching is documented for qwen3-max, not
    # for the 2.5 line. Use this model when measuring prefix-cache hit rates.
    "qwen/qwen3-max": {
        "input": 1.20,
        "output": 6.00,
    },
}

# Default model used when --model is not supplied to the CLI
DEFAULT_MODEL = "qwen/qwen3-max"
DEFAULT_LIGHT_MODEL = "ibm-granite/granite-4.2-8b"

# ---------------------------------------------------------------------------
# Per-model invocation overrides passed to the chat-model constructor.
# Use this to pin providers, disable reasoning, set response_format, etc.
# Keys are model identifiers that match MODEL_RATE_PER_1M_TOKENS keys.
# ---------------------------------------------------------------------------
MODEL_INVOCATION_CONFIG: dict[str, dict[str, Any]] = {
    "qwen/qwen3-30b-a3b": {
        # Qwen3 supports a thinking/non-thinking dual mode. For the Flash-Fusion
        # light model we want fast, deterministic, non-thinking output.
        "reasoning": {"enabled": False},
        "max_tokens": 128,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        # Pin to DeepInfra's fp8 endpoint for this model.
        "provider": {
            "order": ["DeepInfra"],
            "allow_fallbacks": False,
        },
    },
    "qwen/qwen3-30b-a3b-instruct-2507": {
        # only has a non-thinking mode - this variant specifically
        "reasoning": {"enabled": False},
        "max_tokens": 128,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    },
    "ibm-granite/granite-4.2-8b": {
        "max_tokens": 150,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    },
    "meta-llama/llama-3.2-3b-instruct": {
        "max_tokens": 150,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    },
    "google/gemma-3-12b-it": {
        "max_tokens": 150,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    },
    "qwen/qwen3-14b": {
        # Qwen3 dual-mode: keep grounding deterministic/non-thinking.
        "reasoning": {"enabled": False},
        "max_tokens": 150,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    },
}

# ---------------------------------------------------------------------------
# Agent execution limits
# ---------------------------------------------------------------------------
AGENT_MAX_ITERATIONS: int = 6          # LangChain AgentExecutor max_iterations
RESILIENT_PARSER_MAX_IDENTICAL: int = 2  # consecutive identical outputs before fallback
RESILIENT_PARSER_MAX_FAILURES: int = 2   # consecutive parse failures before fallback
EXECUTION_AGENT_BACKEND_DEFAULT: str = "auto"  # auto -> safe on macOS, classic elsewhere
AGENT_SAFE_MAX_ATTEMPTS: int = 5  # codegen+execute retries for safe backend
AGENT_SAFE_CODE_TIMEOUT_S: float = 90.0  # hard timeout for each safe code execution attempt
FLASH_FUSION_PREDICTIVE_TIMEOUT_S: float = 90.0  # hard timeout for predictive deterministic execution

# ---------------------------------------------------------------------------
# Stage retry limits
# ---------------------------------------------------------------------------
STAGE1_MAX_RETRIES: int = 1   # retries when both DATA and REASONING lists are empty
STAGE2_MAX_RETRIES: int = 1   # retries when no MAPPINGS lines found

# ---------------------------------------------------------------------------
# Sub-query decomposition
# ---------------------------------------------------------------------------
VALID_OPS: frozenset[str] = frozenset(
    {"FILTER", "AGGREGATE", "GROUPBY", "CORRELATE", "WINDOW", "RANK"}
)

# ---------------------------------------------------------------------------
# Accuracy scoring thresholds (used by eval/metrics.py)
# ---------------------------------------------------------------------------
ACCURACY_PASS_SCORE: float = 1.0   # executed=True AND judge==PASS
ACCURACY_EXEC_SCORE: float = 0.5   # executed=True AND (judge==FAIL OR no judge)
ACCURACY_FAIL_SCORE: float = 0.0   # rejected OR not executed

# ---------------------------------------------------------------------------
# Token estimation coefficient (chars → approximate tokens)
# len(text.split()) * TOKEN_ESTIMATE_MULTIPLIER
# ---------------------------------------------------------------------------
TOKEN_ESTIMATE_MULTIPLIER: float = 1.3

# ---------------------------------------------------------------------------
# Default dataset paths (relative to repo root flash-fusion/)
# ---------------------------------------------------------------------------
WISDM_DEFAULT_PATH: str = "data/AutoIOT_dataset/IMU/WISDM_ar_v1.1_raw.txt"
WISDM_ARFF_DIR: str = "data/AutoIOT_dataset/IMU/wisdm-dataset/arff_files"

# ---------------------------------------------------------------------------
# AutoIOT paper-faithful baseline defaults
# ---------------------------------------------------------------------------
AUTOIOT_PAPER_ITERATIONS: int = 5
AUTOIOT_PAPER_REQUIRE_TAVILY: bool = True
AUTOIOT_PAPER_MAX_TERMS: int = 6
AUTOIOT_PAPER_MAX_URLS_PER_TERM: int = 2
AUTOIOT_PAPER_HTTP_TIMEOUT_S: float = 12.0

# ---------------------------------------------------------------------------
# LLMSense baseline defaults
# ---------------------------------------------------------------------------
LLMSENSE_MAX_ROWS_DIRECT: int = 120
LLMSENSE_SUMMARY_WINDOW_MIN: int = 30
LLMSENSE_HISTORY_HOURS: int = 6
LLMSENSE_SENSOR_HZ: float = 20.0
# Per-dataset row caps for Stage N (direct narration) and Stage S (per-chunk table size).
# Derived from 80% of the 128k context window (102,400 tokens) — matches HARGPT row caps.
# 80% leaves headroom so prefill time does not exceed the API read timeout.
LLMSENSE_ROWS_PER_CHUNK_WISDM: int = 5120   # ~20 tok/row → 102,400 tok (80.0% of 128k)
LLMSENSE_ROWS_PER_CHUNK_ECG: int = 5700     # ~18 tok/row → 102,600 tok (80.2%)
LLMSENSE_ROWS_PER_CHUNK_BUS: int = 1860     # ~55 tok/row → 102,300 tok (79.9%); dataset is only 1,219 rows
# Narrative char cap for Stage R to stay within 80% of the 128k context window.
# 300k chars ≈ 100k real tokens at ~3 chars/token, leaving ~25k tokens for prompt + query.
LLMSENSE_NARRATIVE_MAX_CHARS: int = 300_000
# Max total Stage-S LLM calls per query across all groups/chunks.
# ECG has 48 record groups × up to 12 sub-chunks = 576 potential calls;
# capping at 3 keeps benchmark cost and latency manageable.
LLMSENSE_MAX_SUMMARIZE_CHUNKS: int = 3
