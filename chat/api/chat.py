"""Vercel serverless handler for /api/chat.

Domain-agnostic data exploration interface backed by OpenRouter and the Flash-Fusion
analysis pipeline.  Loads actual datasets into Pandas DataFrames and drives
a pandas agent (concept extraction → schema grounding → sub-query generation
→ agent execution → synthesis) for grounded, data-backed responses.

New datasets can be added to DATASET_REGISTRY without any other code changes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _load_local_env() -> None:
    if load_dotenv is None:
        return
    chat_root = Path(__file__).resolve().parents[1]
    for env_name in (".env.local", ".env"):
        env_path = chat_root / env_name
        if env_path.exists():
            load_dotenv(env_path, override=False)


_load_local_env()

LOGGER = logging.getLogger("flash_fusion.api.chat")

# ── Path setup for playground imports ───────────────────────
_CHAT_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _CHAT_ROOT.parent

# Make the playground package importable from the API handler.
sys.path.insert(0, str(_CHAT_ROOT / "playground"))
sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402
from langchain_openrouter import ChatOpenRouter  # noqa: E402
from playground import (  # noqa: E402
    load_data,
    export_ecg_record_to_csv,
    list_ecg_records,
    build_column_metadata,
    meta_to_str,
    BaselineRunner,
    RunResult,
    LLMClient,
    Stage1_ConceptExtraction,
    Stage2_SchemaGrounding,
    _strip_provider_prefix,
)
from flashfusion.baselines.flash_fusion import run_flash_fusion  # noqa: E402
from flashfusion.baselines.flash_fusion_cache import run_flash_fusion_cache  # noqa: E402
from flashfusion.pipeline.runner import (  # noqa: E402
    LLMClient as TypedLLMClient,
    RunResult as TypedRunResult,
)

# ── Dataset registry ────────────────────────────────────────
# Maps domain key → path relative to _CHAT_ROOT.
# Files live in chat/data/ so they are tracked by git (not affected by the
# root-level `data/` gitignore rule). Add new datasets here; no other code
# changes required.
DATASET_REGISTRY: dict[str, str] = {
    "bus": "data/bus/bus_data.csv",              # 192 KB  — committed directly
    "imu": "data/imu/WISDM_ar_v1.1_raw.txt",   #  48 MB  — Git LFS
    "ecg": "data/ecg/100.csv",                  #  27 MB  — Git LFS (record 100)
}

LOCAL_DATASET_REGISTRY: dict[str, Path] = {
    "bus": _PROJECT_ROOT / "data" / "bus" / "bus_data.csv",
    "imu": _PROJECT_ROOT / "data" / "AutoIOT_dataset" / "IMU" / "WISDM_ar_v1.1_raw.txt",
    "ecg": _PROJECT_ROOT / "data" / "AutoIOT_dataset" / "ECG.0" / "tmp_csv",
}

DEFAULT_ECG_RECORD = "100"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_PRODUCTION")
FULL_PLANNING_MODEL = os.environ.get("FULL_PLANNING_MODEL", "openrouter/auto")
GROUNDING_MODEL = os.environ.get("GROUNDING_MODEL", "openrouter/auto")

DOMAIN_ROUTER_MODEL = os.environ.get("DOMAIN_ROUTER_MODEL", "openrouter/auto")
DOMAIN_ROUTER_MIN_CONF = float(os.environ.get("DOMAIN_ROUTER_MIN_CONF", "0.42"))
DOMAIN_ROUTER_MIN_MARGIN = float(os.environ.get("DOMAIN_ROUTER_MIN_MARGIN", "0.06"))

# ── Module-level DataFrame cache (survives warm invocations) ─
_df_cache: dict[str, pd.DataFrame] = {}
_path_cache: dict[str, str] = {}


def _safe_listdir(path: Path) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except Exception:
        return []


def _path_debug_snapshot(domain: str, ecg_record: str | None = None) -> dict[str, Any]:
    """Collect lightweight runtime path diagnostics for dataset resolution."""
    rel = DATASET_REGISTRY.get(domain)
    chat_candidate = (_CHAT_ROOT / rel) if rel else None
    local_candidate = LOCAL_DATASET_REGISTRY.get(domain)

    ecg_record_name = ecg_record or DEFAULT_ECG_RECORD
    local_record_candidate: Path | None = None
    if domain == "ecg" and local_candidate is not None:
        local_record_candidate = local_candidate / f"{ecg_record_name}.csv"

    return {
        "cwd": os.getcwd(),
        "handler_file": str(Path(__file__).resolve()),
        "chat_root": str(_CHAT_ROOT),
        "project_root": str(_PROJECT_ROOT),
        "domain": domain,
        "ecg_record": ecg_record_name,
        "registry_relative": rel,
        "chat_candidate": str(chat_candidate) if chat_candidate else None,
        "chat_candidate_exists": bool(chat_candidate and chat_candidate.exists()),
        "chat_candidate_is_file": bool(chat_candidate and chat_candidate.is_file()),
        "local_candidate": str(local_candidate) if local_candidate else None,
        "local_candidate_exists": bool(local_candidate and local_candidate.exists()),
        "local_candidate_is_file": bool(local_candidate and local_candidate.is_file()),
        "local_ecg_record_candidate": (
            str(local_record_candidate) if local_record_candidate else None
        ),
        "local_ecg_record_exists": bool(local_record_candidate and local_record_candidate.is_file()),
        "chat_root_children": _safe_listdir(_CHAT_ROOT),
        "chat_data_children": _safe_listdir(_CHAT_ROOT / "data"),
        "chat_data_bus_children": _safe_listdir(_CHAT_ROOT / "data" / "bus"),
        "chat_data_imu_children": _safe_listdir(_CHAT_ROOT / "data" / "imu"),
        "chat_data_ecg_children": _safe_listdir(_CHAT_ROOT / "data" / "ecg"),
    }


def _resolve_data_path(domain: str, ecg_record: str | None = None) -> str:
    """Return the absolute path to the data file for *domain*.

    Paths in DATASET_REGISTRY are relative to _CHAT_ROOT (i.e. the chat/
    subdirectory), so they resolve correctly both locally and on Vercel.
    If the registry entry is already a readable file, it is used as-is;
    otherwise (legacy: raw ECG directory) export is attempted.
    """
    local_path = LOCAL_DATASET_REGISTRY.get(domain)
    if local_path is None:
        raise ValueError(f"Unknown domain: {domain}")
    if domain == "ecg":
        record = ecg_record or DEFAULT_ECG_RECORD
        local_record = local_path / f"{record}.csv"
        if local_record.is_file():
            return str(local_record)
    elif local_path.is_file():
        return str(local_path)

    rel = DATASET_REGISTRY[domain]
    abs_path = str(_CHAT_ROOT / rel)
    if os.path.isfile(abs_path):
        return abs_path
    # Fallback for local dev: if path is a raw ECG directory, convert on the fly.
    if domain == "ecg" and os.path.isdir(abs_path):
        record = ecg_record or DEFAULT_ECG_RECORD
        return export_ecg_record_to_csv(abs_path, record)
    debug = _path_debug_snapshot(domain, ecg_record)
    LOGGER.error(
        "Dataset path resolution failed domain=%s details=%s",
        domain,
        json.dumps(debug, ensure_ascii=True),
    )
    raise FileNotFoundError(f"Dataset not found at: {abs_path}")


def _get_dataframe(domain: str, ecg_record: str | None = None) -> pd.DataFrame:
    """Load (and cache) the DataFrame for *domain*."""
    cache_key = f"{domain}:{ecg_record or ''}"
    if cache_key not in _df_cache:
        path = _resolve_data_path(domain, ecg_record)
        df, _ = load_data(path)
        _df_cache[cache_key] = df
        _path_cache[cache_key] = path
    return _df_cache[cache_key]


def _get_cached_path(domain: str, ecg_record: str | None = None) -> str:
    cache_key = f"{domain}:{ecg_record or ''}"
    if cache_key in _path_cache:
        return _path_cache[cache_key]
    return _resolve_data_path(domain, ecg_record)


def _dataset_provenance(df: pd.DataFrame, source_path: str) -> dict[str, Any]:
    try:
        source = str(Path(source_path).relative_to(_PROJECT_ROOT))
    except ValueError:
        source = source_path
    return {
        "rows": len(df),
        "columns": list(df.columns),
        "source": source,
        "is_full_source": str(source_path).startswith(str(_PROJECT_ROOT / "data")),
    }


def _typed_response(
    result: TypedRunResult, domain: str, dataset: dict[str, Any]
) -> dict[str, Any]:
    """Serialize the typed pipeline's user-facing result and audit trail."""
    return {
        "reply": result.answer,
        "domain": domain,
        "grounded": result.executed,
        "dataset": dataset,
        "typed": {
            "execution_path": result.execution_path,
            "plan_source": result.plan_source,
            "validation_failure": result.plan_validation_stage_failed,
            "rejected": result.rejected,
            "rejection_reason": result.rejection_reason,
            "typed_plan": result.typed_plan,
            "operators_used": result.operators_used,
            "route": {
                "candidate_ops": result.operator_route_candidate_ops,
                "excluded_buckets": result.operator_route_excluded_buckets,
                "matched_rules": result.operator_route_matched_rules,
                "used_full_fallback": result.operator_route_full_fallback,
            },
            "trace": result.trace,
            "execution_certificate": result.typed_execution_certificate,
            "stage_latency_s": result.stage_latency_s,
            "cache_grounding_failure": result.cache_grounding_failure,
            "raw_plan": result.raw_plan,
        },
        "stages": result.stages_run,
        "usage": {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": result.input_tokens + result.output_tokens,
            "cost_usd": result.cost_usd,
            "latency_s": result.latency_s,
        },
    }

# ── Probabilistic domain routing ────────────────────────────
# Uses a small model to score domain likelihoods and falls back to
# deterministic token-profile similarity when the router cannot be used.
_DOMAIN_PROFILES: dict[str, str] = {
    "imu": (
        "WISDM human activity recognition from smartphone accelerometer and time-series motion. "
        "Activities include walking, jogging, upstairs, downstairs, sitting, standing. "
        "Questions often mention activity, movement intensity, transitions, variance, users."
    ),
    "ecg": (
        "Agent ECG data derived from MIT-BIH arrhythmia recordings. "
        "Cardiac waveform and annotations: heart rate, beat types, arrhythmia, PVC, QRS, ST segment, rhythm."
    ),
    "bus": (
        "Bus ride quality and road condition sensing. "
        "Questions about bumps, potholes, route roughness, passenger comfort, aggressive driving, acceleration patterns."
    ),
}


def _normalize_probabilities(raw: dict[str, Any]) -> dict[str, float]:
    probs: dict[str, float] = {d: 0.0 for d in DATASET_REGISTRY}
    for domain in probs:
        try:
            val = float(raw.get(domain, 0.0))
        except (TypeError, ValueError):
            val = 0.0
        probs[domain] = max(0.0, val)

    total = sum(probs.values())
    if total <= 0.0:
        uniform = 1.0 / max(len(probs), 1)
        return {k: uniform for k in probs}
    return {k: round(v / total, 6) for k, v in probs.items()}


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]+", text.lower()) if len(tok) >= 3}


def _fallback_domain_probabilities(query: str) -> dict[str, float]:
    q_tokens = _tokenize(query)
    if not q_tokens:
        uniform = 1.0 / max(len(DATASET_REGISTRY), 1)
        return {d: uniform for d in DATASET_REGISTRY}

    scores: dict[str, float] = {}
    for domain, profile in _DOMAIN_PROFILES.items():
        d_tokens = _tokenize(profile)
        overlap = len(q_tokens & d_tokens)
        denom = (len(q_tokens) * len(d_tokens)) ** 0.5
        scores[domain] = (overlap / denom) if denom > 0 else 0.0

    return _normalize_probabilities(scores)


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _domain_probabilities_llm(query: str, model: str) -> dict[str, float]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_PRODUCTION is not configured")

    model = _strip_provider_prefix(model)
    domains_json = json.dumps(_DOMAIN_PROFILES, ensure_ascii=True)
    llm = ChatOpenRouter(
        model=model,
        api_key=OPENROUTER_API_KEY,
        temperature=0,
        max_tokens=180,
        max_retries=2,
    )
    completion = llm.invoke(
        [
            (
                "system",
                "You are a domain intent classifier. "
                "Return strict JSON with probabilities for exactly these keys: ecg, imu, bus. "
                "Values must be floats in [0,1] and sum to 1.",
            ),
            (
                "human",
                (
                    f"Domain profiles: {domains_json}\n\n"
                    f"Query: {query}\n\n"
                    "Output JSON only, no explanation. "
                    "Preferred format: {\"ecg\": 0.10, \"imu\": 0.20, \"bus\": 0.70}"
                ),
            ),
        ]
    )
    content = str(getattr(completion, "content", "") or "")
    parsed = _extract_json_object(content or "")
    if "probabilities" in parsed and isinstance(parsed["probabilities"], dict):
        parsed = parsed["probabilities"]
    return _normalize_probabilities(parsed)


def _detect_domain(
    query: str,
    explicit: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Return (domain, routing diagnostics) using probabilistic scoring."""
    if explicit and explicit in DATASET_REGISTRY:
        explicit_probs = {d: (1.0 if d == explicit else 0.0) for d in DATASET_REGISTRY}
        return explicit, {
            "method": "explicit",
            "probabilities": explicit_probs,
            "confidence": 1.0,
            "margin": 1.0,
            "model": None,
        }

    method = "llm"
    model_used = DOMAIN_ROUTER_MODEL
    try:
        probs = _domain_probabilities_llm(query, DOMAIN_ROUTER_MODEL)
    except Exception as exc:
        LOGGER.warning("Domain LLM router failed; using fallback: %s", exc)
        probs = _fallback_domain_probabilities(query)
        method = "fallback"
        model_used = None

    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    best_domain, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = max(0.0, best_score - second_score)
    ambiguous = best_score < DOMAIN_ROUTER_MIN_CONF or margin < DOMAIN_ROUTER_MIN_MARGIN

    diagnostics: dict[str, Any] = {
        "method": method,
        "model": model_used,
        "probabilities": probs,
        "confidence": round(best_score, 6),
        "margin": round(margin, 6),
        "ambiguous": ambiguous,
        "thresholds": {
            "min_confidence": DOMAIN_ROUTER_MIN_CONF,
            "min_margin": DOMAIN_ROUTER_MIN_MARGIN,
        },
    }
    return (None if ambiguous else best_domain), diagnostics


def _schema_summary(df: pd.DataFrame) -> str:
    """One-line-per-column schema overview for the ambiguity response."""
    meta = build_column_metadata(df)
    return meta_to_str(meta)


def _check_mappability(query: str, df: pd.DataFrame, model: str) -> tuple[str, str, dict[str, Any]]:
    """Run Stage 1 + Stage 2 to determine if the query is answerable.

    Returns (status, message) where status is one of:
      'DIRECT'     — all concepts map; proceed normally
      'PROXY'      — needs proxy columns; surface explanation
      'UNMAPPABLE' — cannot be answered from this dataset
    Falls back to 'DIRECT' on any internal error.
    """
    try:
        llm_client = LLMClient(model=model)
        s1 = Stage1_ConceptExtraction(llm_client)
        concepts = s1.run(query)

        meta = build_column_metadata(df)
        meta_str = meta_to_str(meta)
        s2 = Stage2_SchemaGrounding(llm_client)
        grounding = s2.run(concepts, query, meta_str, {}, df)

        mappings: list[str] = grounding["mappings"]
        unmappable: list[str] = [
            u for u in grounding["unmappable"] if not u.startswith("INVALID:")
        ]
        reasoning_concepts: list[str] = concepts.get("REASONING", [])
        details: dict[str, Any] = {
            "data_concepts": concepts.get("DATA", []),
            "reasoning_concepts": reasoning_concepts,
            "mappings": mappings,
            "unmappable": unmappable,
            "status": "DIRECT",
        }

        if not mappings and unmappable:
            details["status"] = "UNMAPPABLE"
            return (
                "UNMAPPABLE",
                f"I don't have data that can answer that question "
                f"(unmappable concepts: {', '.join(unmappable)}).",
                details,
            )

        if reasoning_concepts and mappings:
            reasoning_lower = {r.lower() for r in reasoning_concepts}
            proxy_lines = [
                m for m in mappings
                if any(r in m.lower() for r in reasoning_lower)
            ]
            if proxy_lines:
                proxy_desc = "; ".join(
                    m.split("→", 1)[1].strip() if "→" in m else m
                    for m in proxy_lines[:2]
                )
                concept_str = ", ".join(reasoning_concepts[:2])
                details["status"] = "PROXY"
                details["proxy_lines"] = proxy_lines
                return (
                    "PROXY",
                    f"The {concept_str} would have to be computed from "
                    f"{proxy_desc}. Would you like me to proceed?",
                    details,
                )

        return "DIRECT", "", details
    except Exception as exc:
        LOGGER.warning("Mappability check failed; defaulting to DIRECT: %s", exc)
        return "DIRECT", "", {
            "status": "DIRECT",
            "error": str(exc),
            "data_concepts": [],
            "reasoning_concepts": [],
            "mappings": [],
            "unmappable": [],
        }


# ── Vercel handler ──────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            content_length = 0
        body = self.rfile.read(content_length)

        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "Invalid JSON"})
            return

        message = (req.get("message") or "").strip()
        if not message:
            self._json_response(400, {"error": "Empty message"})
            return

        model = req.get("model", FULL_PLANNING_MODEL)
        explicit_domain: str | None = req.get("domain")
        ecg_record: str | None = req.get("ecg_record")
        confirmed: bool = req.get("confirmed", False)
        execution_mode = req.get("execution_mode", "agent")
        if execution_mode not in {"agent", "typed_operator", "typed_operator_cache"}:
            self._json_response(400, {"error": "Invalid execution_mode"})
            return

        api_key = OPENROUTER_API_KEY
        if not api_key:
            self._json_response(500, {"error": "OPENROUTER_PRODUCTION is not configured"})
            return

        # ── Domain detection: explicit > probabilistic routing ──────
        domain, routing = _detect_domain(message, explicit_domain)
        if not domain:
            available = ", ".join(sorted(DATASET_REGISTRY.keys()))
            probs = routing.get("probabilities", {})
            probs_str = ", ".join(
                f"{d}: {round(float(probs.get(d, 0.0)) * 100.0, 1)}%"
                for d in sorted(DATASET_REGISTRY)
            )
            self._json_response(200, {
                "reply": (
                    "I couldn't determine the target dataset with high confidence. "
                    f"Current routing probabilities: {probs_str}. "
                    f"Available domains: **{available}**. "
                    "Please select one from the dropdown or mention it in your question."
                ),
                "domain": None,
                "grounded": False,
                "domain_routing": routing,
                "usage": None,
            })
            return

        # ── Load dataset ────────────────────────────────────
        try:
            df = _get_dataframe(domain, ecg_record)
            source_path = _get_cached_path(domain, ecg_record)
        except Exception as exc:
            debug = _path_debug_snapshot(domain, ecg_record)
            LOGGER.exception(
                "Dataset load failure domain=%s details=%s",
                domain,
                json.dumps(debug, ensure_ascii=True),
            )
            payload: dict[str, Any] = {
                "error": f"Failed to load {domain} dataset: {exc}",
            }
            if os.environ.get("FF_DEBUG_DATA_PATHS", "0") == "1":
                payload["dataset_debug"] = debug
            self._json_response(500, payload)
            return

        dataset = _dataset_provenance(df, source_path)

        # ── Mappability gate ("idk" feature) ──────────────
        map_details: dict[str, Any] = {
            "status": "SKIPPED",
            "data_concepts": [],
            "reasoning_concepts": [],
            "mappings": [],
            "unmappable": [],
        }
        if execution_mode == "agent" and not confirmed:
            map_status, map_message, map_details = _check_mappability(message, df, model)

            if map_status == "UNMAPPABLE":
                self._json_response(200, {
                    "reply": map_message or "I don't have data that can answer that question.",
                    "domain": domain,
                    "grounded": False,
                    "idk": True,
                    "domain_routing": routing,
                    "intent_diagnostics": map_details,
                    "usage": None,
                })
                return

            if map_status == "PROXY":
                self._json_response(200, {
                    "reply": map_message,
                    "domain": domain,
                    "grounded": False,
                    "needs_confirmation": True,
                    "domain_routing": routing,
                    "intent_diagnostics": map_details,
                    "usage": None,
                })
                return

        # ── Typed planner / cache demo ─────────────────────
        if execution_mode != "agent":
            try:
                typed_model = _strip_provider_prefix(model)
                client = TypedLLMClient(
                    model_name=typed_model,
                    api_key=api_key,
                    light_model_name=GROUNDING_MODEL,
                )
                result = TypedRunResult(
                    baseline=(
                        "FLASH_FUSION_CACHE"
                        if execution_mode == "typed_operator_cache"
                        else "FLASH_FUSION"
                    ),
                    model=typed_model,
                    query=message,
                )
                if execution_mode == "typed_operator_cache":
                    cache_dataset = "wisdm" if domain == "imu" else domain
                    result = run_flash_fusion_cache(
                        message,
                        df,
                        client,
                        result,
                        dataset=cache_dataset,
                        enable_semantic_matching=False,
                    )
                else:
                    result = run_flash_fusion(message, df, client, result)
                self._json_response(200, _typed_response(result, domain, dataset))
            except Exception as exc:
                LOGGER.exception("Typed pipeline error domain=%s mode=%s", domain, execution_mode)
                self._json_response(502, {"error": f"Typed pipeline error: {exc}"})
            return

        # ── Run Flash-Fusion B4 pipeline ────────────────────
        try:
            runner = BaselineRunner(
                df=df,
                mode="B4",
                model=model,
                source_path=source_path,
            )
            result: RunResult = runner.run(message)

            execution: dict[str, Any] = {
                "code": result.final_executed_code,
                "tries": result.agent_tries,
                "attempts": result.execution_attempts,
                "summary": result.execution_summary,
                "judge": result.judge_verdict,
            }

            if result.execution_attempts:
                LOGGER.info(
                    "Execution diagnostics domain=%s model=%s tries=%d stages=%s summary=%s",
                    domain,
                    model,
                    result.agent_tries,
                    result.stages_run,
                    result.execution_summary,
                )

            self._json_response(200, {
                "reply": result.answer,
                "domain": domain,
                "grounded": result.executed,
                "dataset": dataset,
                "domain_routing": routing,
                "stages": result.stages_run,
                "execution": execution,
                "intent_diagnostics": map_details,
                "usage": {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "total_tokens": result.total_tokens,
                    "cost_usd": result.cost_usd,
                    "latency_s": result.latency_s,
                },
            })
        except Exception as exc:
            self._json_response(502, {"error": f"Pipeline error: {exc}"})

    # ── Helpers ─────────────────────────────────────────────

    def _json_response(self, status: int, data: dict):
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
