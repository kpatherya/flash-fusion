"""
baselines/flash_fusion.py — Flash-Fusion baseline.

Default path (one LLM round-trip, no codegen, no sandbox):

    query
    -> single structured guardrail+plan call
      -> Gate 1: Pydantic structural validation   (microseconds)
      -> Gate 2: DataFrame schema validation      (microseconds)
    -> execute_plan(df, plan)  — typed operators, in-process
    -> local result formatting

Fallback path (ReAct) is entered ONLY when:
  * the planner returns in_scope=True but no plan (operator vocabulary gap), or
  * Gate 1 fails (malformed/unknown operator), or
  * Gate 2 fails (unknown column / wrong dtype), or
  * execution of a validated plan fails.

Every fallback is recorded via ``log_operator_gap()`` for offline review. The
vocabulary is never extended inside a live request — that would reintroduce the
arbitrary-code-execution risk typed operators exist to remove.

Instrumentation (see RunResult): ``execution_path``,
``plan_validation_stage_failed``, ``typed_plan``, ``operators_used``,
``plan_source``, plus per-stage latency in ``stage_latency_s``.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import time
from typing import Any

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from flashfusion.config import FLASH_FUSION_PREDICTIVE_TIMEOUT_S
from flashfusion.pipeline.executor import ExecutionLayer
from flashfusion.pipeline.loader import build_column_metadata, meta_to_str
from flashfusion.pipeline.operator_router import (
    BUCKET_FULL,
    OperatorRoute,
    route_operator_bucket,
)
from flashfusion.pipeline.operators import (
    NORMALIZATION_VERSION,
    DeterministicPlan,
    ParsedGuardrail,
    PlanSchemaError,
    StructuralValidationError,
    build_planner_prefix,
    build_vocabulary_spec,
    execute_plan,
    log_operator_gap,
    parse_guardrail_response,
    planner_prefix_digest,
    planner_prefix_version,
    structural_validate,
    validate_plan_against_dataframe,
)
from flashfusion.pipeline.runner import LLMClient, RunResult
from flashfusion.prompts.templates import PLANNER_DYNAMIC_SUFFIX_TEMPLATE

FF_DEBUG = os.getenv("FF_DEBUG", "").lower() in ("1", "true", "yes")
FF_PROGRESS = os.getenv("FF_PROGRESS", "").lower() in ("1", "true", "yes")

#: Run concept extraction + schema grounding before the ReAct fallback. This
#: costs two extra LLM calls, but only on the small subset the typed vocabulary
#: cannot express — the fast path stays at a single round-trip.
FF_FALLBACK_GROUNDING = os.getenv("FF_FALLBACK_GROUNDING", "1").lower() in (
    "1",
    "true",
    "yes",
)

PATH_GUARDRAIL_REJECT = "guardrail_reject"
PATH_TYPED_OPERATOR = "typed_operator"
PATH_REACT_FALLBACK = "react_fallback"
#: Gate 2 found the plan referencing a field this dataset does not have. That is a
#: verdict about the question, not a gap in the vocabulary, so it is terminal — the
#: ReAct fallback cannot conjure a column either, it can only hallucinate one.
PATH_SCOPE_REJECT = "scope_reject"

#: Used when no query is available to route on (prefix warming).
_FULL_ROUTE = OperatorRoute(
    candidate_ops=BUCKET_FULL,
    excluded_buckets=(),
    matched_rules=(),
    used_full_fallback=True,
)


# These caches only prepare immutable, byte-identical message components. They
# intentionally do not issue an LLM request: warming a provider prompt cache
# would itself be a billable planning call and distort benchmark comparisons.
_PLANNER_PREFIX_CACHE: dict[tuple[str, str], tuple[SystemMessage, str]] = {}
_PLANNER_SUFFIX_PREFIX_CACHE: dict[tuple[str, str], str] = {}


def _debug(message: str) -> None:
    if FF_DEBUG:
        print(f"[FF_DEBUG] {message}", file=sys.stderr, flush=True)


def _progress(message: str) -> None:
    """Print progress updates when FF_PROGRESS=1, for diagnosing stalls."""
    if FF_PROGRESS:
        print(f"[PROGRESS] {message}", file=sys.stderr, flush=True)


def _planner_prefix_message(
    client: LLMClient, route: OperatorRoute | None = None
) -> tuple[SystemMessage, str]:
    """Return the planner prefix message and its exact text for one route.

    The prefix is still byte-stable per (session, route), but the prompt cache is
    now partitioned by operator route instead of being one global entry — the
    accepted cost of dropping the full vocabulary from every planner call.
    """
    route = route or _FULL_ROUTE
    key = (getattr(client, "session_key", ""), route.route_key)
    cached = _PLANNER_PREFIX_CACHE.get(key)
    if cached is None:
        text = build_planner_prefix(build_vocabulary_spec(route.candidate_ops))
        message = SystemMessage(
            content=[
                {
                    "type": "text",
                    "text": text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        )
        cached = (message, text)
        _PLANNER_PREFIX_CACHE[key] = cached
    return cached


def _planner_suffix_prefix(meta_str: str, client: LLMClient, dataset: str = "") -> str:
    """Return the cached dynamic prompt through its final QUESTION field."""
    fingerprint = schema_fingerprint(meta_str)
    key = (getattr(client, "session_key", ""), f"{dataset or '(unnamed)'}:{fingerprint}")
    suffix_prefix = _PLANNER_SUFFIX_PREFIX_CACHE.get(key)
    if suffix_prefix is None:
        suffix_prefix = PLANNER_DYNAMIC_SUFFIX_TEMPLATE.format(
            dataset=dataset or "(unnamed)",
            schema_fingerprint=fingerprint,
            column_metadata=meta_str,
            query="",
        )
        _PLANNER_SUFFIX_PREFIX_CACHE[key] = suffix_prefix
    return suffix_prefix


def warm_flash_fusion_prefix(df: pd.DataFrame, client: LLMClient) -> None:
    """Prepare planner message components for a DataFrame without an LLM call.

    Only the full-vocabulary prefix is warmed: the narrowed prefixes depend on
    the query, so they are built lazily on first use of each route.
    """
    meta_str = meta_to_str(build_column_metadata(df))
    _planner_prefix_message(client)
    _planner_suffix_prefix(meta_str, client)


def prewarm_flash_fusion_prompt_cache(
    df: pd.DataFrame, client: LLMClient, queries: list[str]
) -> int:
    """Populate provider caches for the static planner prefixes used by *queries*.

    Each request has the identical cache-marked system prefix used by the
    planner, the same model session, and a disposable one-token completion.
    Benchmark callers must use a distinct setup client so warmup usage stays
    outside timed per-query metrics.
    """
    meta_str = meta_to_str(build_column_metadata(df))
    unique_routes: dict[str, OperatorRoute] = {}
    for query in queries:
        route = route_operator_bucket(query, list(df.columns))
        unique_routes[route.route_key] = route
    for route in unique_routes.values():
        prefix_message, _ = _planner_prefix_message(client, route)
        suffix = _planner_suffix_prefix(meta_str, client) + "Prompt-cache warmup."
        client.warm_prompt_cache(
            [prefix_message, HumanMessage(content=suffix)],
            stage="ff_planner_prompt_cache_warmup",
        )
    return len(unique_routes)


def _call_log_length(client: LLMClient) -> int:
    call_log = getattr(client, "call_log", None)
    return len(call_log) if isinstance(call_log, list) else 0


def _record_call_usage(r: RunResult, client: LLMClient, start_index: int, prefix: str) -> None:
    """Store aggregate usage from calls appended after ``start_index``."""
    call_log = getattr(client, "call_log", None)
    calls = call_log[start_index:] if isinstance(call_log, list) else []
    setattr(r, f"{prefix}_input_tokens", sum(call.input_tokens for call in calls))
    setattr(r, f"{prefix}_output_tokens", sum(call.output_tokens for call in calls))
    setattr(r, f"{prefix}_cost_usd", sum(call.cost_usd for call in calls))


def schema_fingerprint(meta_str: str) -> str:
    """Short stable digest of the schema block, logged so two runs can be compared."""
    return hashlib.sha256(meta_str.encode("utf-8")).hexdigest()[:16]


def typed_plan_digest(plan: DeterministicPlan) -> str:
    """Digest of the *validated* plan — the determinism harness compares these."""
    payload = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _format_typed_execution_value(value: Any) -> str:
    """Render typed execution values into a stable answer string."""
    if isinstance(value, dict) and len(value) == 2:
        window_key = next((k for k in value if "window" in k.lower()), None)
        if window_key is not None:
            metric_key = next(k for k in value if k != window_key)
            metric_value = value[metric_key]
            if isinstance(metric_value, float):
                metric_text = f"{metric_value:.4f}"
            else:
                metric_text = str(metric_value)
            return (
                f"The {window_key.replace('_', ' ')} starting at "
                f"{value[window_key]} has {metric_key.replace('_', ' ')} "
                f"{metric_text}."
            )
    return f"The result is {value}"


# ---------------------------------------------------------------------------
# Timeout helper
# ---------------------------------------------------------------------------


class _FlashFusionTimeoutError(TimeoutError):
    """Raised when a Flash-Fusion execution path exceeds its allotted time."""


def _run_with_timeout(
    fn: Any,
    timeout_s: float,
    *,
    timeout_message: str = "Operation timed out",
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Run a callable with a hard timeout and raise a structured timeout error."""
    if kwargs is None:
        kwargs = {}

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeoutError:
            raise _FlashFusionTimeoutError(timeout_message)


# ---------------------------------------------------------------------------
# Single structured LLM call — guardrail verdict + candidate plan
# ---------------------------------------------------------------------------


def request_guardrail_and_plan(
    query: str,
    meta_str: str,
    client: LLMClient,
    dataset: str = "",
    route: OperatorRoute | None = None,
) -> tuple[ParsedGuardrail | None, str, str, str]:
    """Ask for the scope verdict and a candidate plan in one round-trip.

    The planner contract goes in the system message and varies only with the
    operator route; the dataset schema and the question go in the human message.

    Returns:
        (parsed, dynamic_suffix, structural_error, prefix_text). ``parsed`` is
        None when the response could not be structurally validated (Gate 1).
    """
    suffix = _planner_suffix_prefix(meta_str, client, dataset) + query
    # Messages are passed as objects, not through a template: the prefix is full
    # of literal braces from the operator JSON spec, and any interpolation pass
    # over it would both fail and break byte-stability.
    #
    # The prefix is sent as a single content block with an explicit `cache_control`
    # breakpoint. Providers with *automatic* caching (OpenAI, DeepSeek, Gemini,
    # Grok) ignore the marker and cache the prefix anyway; providers that require
    # an *explicit* breakpoint (Anthropic, Alibaba Qwen — see
    # OPERATOR_VOCABULARY_SPEC's caching note) only get cache hits with this
    # marker present. OpenRouter translates/drops the field per-provider, so it
    # is safe to always send it.
    prefix_message, prefix_text = _planner_prefix_message(client, route)
    messages = [prefix_message, HumanMessage(content=suffix)]
    
    # Diagnostic logging for stall investigation
    _progress(f"  → Prompt size: prefix={len(prefix_text)} chars, suffix={len(suffix)} chars, total={len(prefix_text) + len(suffix)}")
    _progress(f"  → Calling LLM API (model={client.model_name})...")
    
    raw = client.invoke_messages(messages, stage="guardrail_plan")
    
    _progress(f"  → LLM response received (length={len(str(raw))} chars)")
    _progress("  → Parsing response...")
    
    try:
        result = parse_guardrail_response(raw), suffix, "", prefix_text
        _progress("  → Response parsed successfully")
        return result
    except (StructuralValidationError, ValueError) as exc:
        _progress(f"  → Response parsing failed: {exc}")
        return None, suffix, str(exc), prefix_text


# ---------------------------------------------------------------------------
# ReAct fallback prompt
# ---------------------------------------------------------------------------
# (NOTE): is S1/S2 even needed? ReAct-Only worked fine even on ambiguous queries
# that would have benefitted from concept-to-column matching

def build_react_query(
    query: str, grounding: str = "", ambiguous_concepts: list[str] | None = None
) -> str:
    """Build the ReAct prompt used whenever the typed path cannot serve a query.

    Concept-to-column grounding is included when available: a fallback happens
    precisely because the typed plan was insufficient, so the agent benefits
    from the mapping as scaffolding while reasoning over the raw DataFrame.
    """
    sections = [query]
    # if grounding.strip():
    #     sections.append(
    #         "Concept-to-column grounding produced by schema analysis "
    #         "(use these exact column names; derive anything else from them):\n"
    #         f"{grounding.strip()}"
    #     )
    # if ambiguous_concepts:
    #     sections.append(
    #         "Concepts with no literal column — resolve them from the schema: "
    #         + ", ".join(ambiguous_concepts)
    #     )
    return "\n\n".join(sections)


def _ground_for_fallback(
    query: str, df: pd.DataFrame, meta_str: str, client: LLMClient, r: RunResult
) -> str:
    """Run concept extraction + schema grounding for the ReAct fallback subset."""
    if not FF_FALLBACK_GROUNDING:
        return ""
    from flashfusion.pipeline.stages import (
        Stage1_ConceptExtraction,
        Stage2_SchemaGrounding,
    )

    try:
        concepts = Stage1_ConceptExtraction(client.light).run(query, df)
        r.s1_concepts = concepts
        r.stages_run.append("S1")
        grounding = Stage2_SchemaGrounding(client.light).run(
            concepts, query, meta_str, df
        )
        r.s2_grounding = grounding["raw_grounding"]
        r.s2_filtered_concepts = grounding.get("filtered_concepts", {})
        r.stages_run.append("S2")
        return grounding["raw_grounding"]
    except Exception as exc:  # noqa: BLE001 — grounding is best-effort scaffolding
        _debug(f"Fallback grounding failed ({exc}); using bare query.")
        return ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_flash_fusion(
    query: str,
    df,
    client: LLMClient,
    r: RunResult,
    timeout_s: float | None = None,
) -> RunResult:
    """Execute the Flash-Fusion pipeline for one query."""
    effective_timeout = (
        timeout_s if timeout_s is not None else FLASH_FUSION_PREDICTIVE_TIMEOUT_S
    )
    existing_stage_latency_s = (
        dict(r.stage_latency_s) if isinstance(r.stage_latency_s, dict) else {}
    )
    stage_latency_s: dict[str, float] = {
        "column_metadata": 0.0,
        "operator_route": 0.0,
        "guardrail+plan": 0.0,
        "schema_validation": 0.0,
        "typed_exec": 0.0,
        "agent": 0.0,
    }
    stage_latency_s.update(existing_stage_latency_s)
    r.stage_latency_s = dict(stage_latency_s)

    def record(stage: str, started: float) -> None:
        stage_latency_s[stage] = stage_latency_s.get(stage, 0.0) + max(
            0.0, time.time() - started
        )
        r.stage_latency_s = dict(stage_latency_s)

    last_stage = "init"
    try:
        last_stage = "column_metadata"
        started = time.time()
        meta_str = meta_to_str(build_column_metadata(df))
        record("column_metadata", started)
        ambiguous: list[str] = []
        gap_stage = ""
        gap_error = ""
        raw_plan_payload: Any = None

        # --- Deterministic operator router (no LLM call) --------------------
        # Elimination, not selection: buckets are dropped only when a named rule
        # fires against them, and anything ambiguous falls back to the full
        # vocabulary. The router never decides what the plan is — it only narrows
        # what the planner is shown.
        last_stage = "operator_route"
        _progress("Stage: operator_route (deterministic, no LLM)")
        started = time.time()
        route = route_operator_bucket(query, list(df.columns))
        record("operator_route", started)
        r.operator_route_excluded_buckets = list(route.excluded_buckets)
        r.operator_route_matched_rules = list(route.matched_rules)
        r.operator_route_full_fallback = route.used_full_fallback
        r.operator_route_candidate_ops = sorted(route.candidate_ops)
        _progress(
            f"  → Routed to {len(route.candidate_ops)} operators: {', '.join(sorted(route.candidate_ops))}"
        )
        _progress(f"  → Excluded buckets: {route.excluded_buckets or '(none)'}")
        _progress(f"  → Matched rules: {route.matched_rules or '(none)'}")
        _debug(
            f"Operator route: {len(route.candidate_ops)} ops, "
            f"excluded={route.excluded_buckets}, rules={route.matched_rules}"
        )

        # --- Single structured call: guardrail verdict + candidate plan -----
        r.plan_source = "llm"
        r.ff_planner_used = True
        last_stage = "guardrail_plan"
        r.guardrail_input = query
        _progress(f"Stage: guardrail+plan (LLM call with {len(route.candidate_ops)} operators)")
        started = time.time()
        planner_call_start = _call_log_length(client)
        (
            parsed_result,
            dynamic_suffix,
            structural_error,
            prefix_text,
        ) = request_guardrail_and_plan(query, meta_str, client, route=route)
        r.ff_planner_latency_s = max(0.0, time.time() - started)
        _record_call_usage(r, client, planner_call_start, "ff_planner")
        record("guardrail+plan", started)
        r.stages_run.append("guardrail_plan")
        r.guardrail_input = dynamic_suffix
        r.planner_prefix_version = planner_prefix_version(prefix_text)
        r.planner_prefix_sha256 = planner_prefix_digest(prefix_text)
        r.planner_cache_key = client.session_key
        r.schema_fingerprint = schema_fingerprint(meta_str)
        r.normalization_version = NORMALIZATION_VERSION

        parsed = parsed_result.parsed if parsed_result is not None else None
        if parsed_result is not None:
            raw_plan_payload = parsed_result.raw
            r.raw_plan = parsed_result.raw
            r.normalization_actions = list(parsed_result.normalization_actions)

        if parsed is None:
            gap_stage, gap_error = "structural", structural_error
            _debug(f"Gate 1 (structural) failed: {structural_error}")
            plan: DeterministicPlan | None = None
        elif not parsed.in_scope:
            reason = (
                parsed.rejection_reason
                or "The query cannot be answered from the available columns."
            )
            r.execution_path = PATH_GUARDRAIL_REJECT
            r.rejected = True
            r.executed = False
            r.rejection_reason = reason
            r.alignment_explanation = (
                "Rejected by the guardrail because the query cannot be "
                f"answered from available dataset fields. Reason: {reason}"
            )
            r.answer = (
                f"Query rejected. Reason: {reason}. This request is not "
                "supported by the current dataset schema or task scope."
            )
            return r
        else:
            ambiguous = list(parsed.ambiguous_concepts)
            r.ambiguous_concepts = ambiguous
            plan = parsed.plan
            if plan is None:
                gap_stage = "no_plan"
                gap_error = (
                    "planner returned no plan; unresolved: "
                    f"{ambiguous or ['(unspecified)']}"
                )

        # --- Gate 2: DataFrame schema validation ----------------------------
        if plan is not None:
            last_stage = "schema_validation"
            _progress("Stage: schema_validation (Gate 2)")
            started = time.time()
            raw_plan_payload = plan.model_dump(mode="json")
            try:
                validate_plan_against_dataframe(plan, df)
                record("schema_validation", started)
                r.typed_plan = raw_plan_payload
                r.typed_plan_sha256 = typed_plan_digest(plan)
                r.operators_used = plan.operators_used
                r.stages_run.append("plan_validated")
            except PlanSchemaError as exc:
                record("schema_validation", started)
                gap_stage, gap_error = "schema", str(exc)
                plan = None
                _debug(f"Gate 2 (schema) failed: {exc}")
                if exc.missing_columns:
                    # The plan asked for a field the dataset does not measure.
                    # No amount of agentic retrying creates that column, so
                    # stop here rather than letting ReAct invent a number.
                    missing = sorted(exc.missing_columns)
                    reason = (
                        "The dataset has no field(s) "
                        + ", ".join(repr(c) for c in missing)
                        + " required to answer this question."
                    )
                    r.execution_path = PATH_SCOPE_REJECT
                    r.plan_validation_stage_failed = "scope"
                    r.missing_columns = missing
                    r.rejected = True
                    r.executed = False
                    r.rejection_reason = reason
                    r.alignment_explanation = (
                        "Rejected at schema validation: the planner referenced "
                        f"non-existent column(s) {missing}."
                    )
                    r.answer = (
                        f"Query rejected. Reason: {reason} This request is not "
                        "supported by the current dataset schema."
                    )
                    log_operator_gap(
                        query=query,
                        stage="scope",
                        error=str(exc),
                        raw_plan=raw_plan_payload,
                    )
                    return r

        # --- Typed operator execution ---------------------------------------
        if plan is not None:
            last_stage = "typed_exec"
            _progress(f"Stage: typed_exec (executing {len(plan.operators_used)} operators)")
            started = time.time()
            try:
                execution = _run_with_timeout(
                    execute_plan,
                    effective_timeout,
                    args=(df, plan),
                    timeout_message=(
                        f"Flash-Fusion execution exceeded {effective_timeout:.0f}s timeout"
                    ),
                )
            except _FlashFusionTimeoutError as exc:
                record("typed_exec", started)
                r.execution_path = PATH_TYPED_OPERATOR
                r.plan_validation_stage_failed = "execution"
                r.deterministic_fallback_reason = str(exc)
                r.typed_execution_certificate = {
                    "certificate_status": "execution_timeout",
                    "execution_path": PATH_TYPED_OPERATOR,
                    "typed_plan_sha256": r.typed_plan_sha256,
                    "operators_used": list(plan.operators_used),
                    "error": str(exc),
                }
                r.stages_run.append("typed_exec_timeout")
                r.answer = str(exc)
                r.trace = f"Timed out after {effective_timeout:.0f}s in typed execution."
                r.executed = False
                return r
            record("typed_exec", started)

            if execution.ok:
                r.execution_path = PATH_TYPED_OPERATOR
                r.plan_validation_stage_failed = ""
                r.answer = _format_typed_execution_value(execution.value)
                r.trace = execution.trace
                r.final_code = execution.code
                r.agent_tries = len(execution.steps)
                r.execution_attempts = list(execution.steps)
                r.executed = True
                r.typed_execution_certificate = {
                    "certificate_status": "ok",
                    "execution_path": PATH_TYPED_OPERATOR,
                    "typed_plan_sha256": r.typed_plan_sha256,
                    "operators_used": list(execution.operators_used),
                    "rows_scanned": execution.rows_scanned,
                    "rows_after_filter": execution.rows_after_filter,
                    "latency_ms": execution.latency_ms,
                    "result": execution.value,
                }
                r.stages_run.append("typed_exec")
                _debug(f"Typed execution ok in {execution.latency_ms:.1f}ms")
            else:
                gap_stage, gap_error = "execution", execution.error or "unknown"
                r.typed_execution_certificate = {
                    "certificate_status": "execution_error",
                    "execution_path": PATH_TYPED_OPERATOR,
                    "typed_plan_sha256": r.typed_plan_sha256,
                    "operators_used": list(plan.operators_used),
                    "error": gap_error,
                }
                plan = None
                _debug(f"Typed execution failed: {gap_error}")

        # --- ReAct fallback --------------------------------------------------
        if plan is None:
            _progress(f"Stage: react_fallback (reason: {gap_stage})")
            log_operator_gap(
                query=query,
                stage=gap_stage or "no_plan",
                error=gap_error,
                raw_plan=raw_plan_payload,
            )
            r.execution_path = PATH_REACT_FALLBACK
            r.plan_validation_stage_failed = gap_stage or "no_plan"
            r.deterministic_fallback_reason = f"{gap_stage}: {gap_error}"
            r.stages_run.append("react_fallback")

            last_stage = "fallback_grounding"
            started = time.time()
            # grounding = _ground_for_fallback(query, df, meta_str, client, r)
            # record("s2", started)

            react_query = build_react_query(query)
            r.react_query = react_query
            r.grounded_query = react_query

            last_stage = "agent"
            _progress("Stage: agent (ReAct execution)")
            started = time.time()
            try:
                raw_answer, trace, details = _run_with_timeout(
                    ExecutionLayer(df, client).execute_single,
                    effective_timeout,
                    args=(react_query,),
                    timeout_message=(
                        f"Flash-Fusion execution exceeded {effective_timeout:.0f}s timeout"
                    ),
                )
            except _FlashFusionTimeoutError as exc:
                record("agent", started)
                r.stages_run.append("agent_timeout")
                r.answer = str(exc)
                r.trace = f"Timed out after {effective_timeout:.0f}s in ReAct fallback."
                r.executed = False
                return r
            record("agent", started)
            r.answer = raw_answer
            r.trace = trace
            r.final_code = details.final_code or ""
            r.agent_tries = details.tries
            r.execution_attempts = list(details.attempts)
            r.executed = True
            r.stages_run.append("agent")

        return r
    except Exception as exc:
        if FF_DEBUG:
            import traceback

            print(f"[FF_DEBUG] Flash-Fusion FAILED at {last_stage}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        r.answer = f"[ERROR in {last_stage}] {type(exc).__name__}: {exc}"
        r.alignment_explanation = f"Flash-Fusion failed during {last_stage}: {exc}"
        r.executed = False
        raise
