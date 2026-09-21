"""
pipeline/runner.py — LLM client, result dataclass, and baseline runner.

Classes:
  LLMCallLog    — dataclass recording per-LLM-call usage metrics
    LLMClient     — wraps a chat model client, accumulates call logs, computes totals
  RunResult     — dataclass capturing the full output of one (baseline, query) run
  BaselineRunner — dispatches to the correct baseline implementation

See CLAUDE.md §pipeline/runner.py for full implementation specifications.
Reference: chat/playground/playground.py ~lines 474–900.
"""

from __future__ import annotations

import os
import time
import warnings
from dataclasses import dataclass, field

import pandas as pd
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openrouter import ChatOpenRouter

try:
    from langchain_groq import ChatGroq

    _ChatGroq = ChatGroq
except ImportError:
    _ChatGroq = None  # type: ignore[assignment,misc]

try:
    from langchain_ollama import ChatOllama

    _ChatOllama = ChatOllama
except ImportError:
    _ChatOllama = None  # type: ignore[assignment,misc]

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

try:
    from openrouter.errors.responsevalidationerror import (
        ResponseValidationError as _OpenRouterResponseValidationError,
    )
except ImportError:
    _OpenRouterResponseValidationError = None  # type: ignore[assignment,misc]

try:
    from openrouter.errors.badrequestresponse_error import (
        BadRequestResponseError as _OpenRouterBadRequestResponseError,
    )
except ImportError:
    _OpenRouterBadRequestResponseError = None  # type: ignore[assignment,misc]

from flashfusion.baselines.flash_fusion_policy import (
    LEGACY_POLICY_ALIASES,
    POLICIES,
    is_flash_fusion_policy,
    resolve_policy,
    run_with_policy,
)
from flashfusion.config import (
    DEFAULT_LIGHT_MODEL,
    FLASH_FUSION_PREDICTIVE_TIMEOUT_S,
    MODEL_INVOCATION_CONFIG,
    MODEL_RATE_PER_1M_TOKENS,
)
from flashfusion.pipeline.operators import planner_cache_key


# ---------------------------------------------------------------------------
# _UsageCapture — callback to extract real token counts from API responses
# ---------------------------------------------------------------------------

class _UsageCapture(BaseCallbackHandler):
    """LangChain callback that reads token counts from the OpenRouter API response.

    OpenRouter always returns native-tokenizer usage in every response via
    ``AIMessage.usage_metadata`` (populated by langchain_openrouter).  No
    heuristics or estimation are used.

    Prompt-cache metrics are best-effort: providers without prefix caching simply
    never populate them, so zero means "not observed", never "no saving".
    """

    def __init__(self) -> None:
        super().__init__()
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.reasoning_tokens: int = 0
        self.cached_tokens: int = 0
        self.cache_write_tokens: int = 0
        self.cache_discount_usd: float = 0.0
        # Real dollar cost as billed by OpenRouter (included automatically in
        # every response). ``has_real_cost`` distinguishes "not reported" from a
        # genuine $0.00 so callers never mistake silence for a free call.
        self.real_cost_usd: float = 0.0
        self.has_real_cost: bool = False

    def on_llm_end(self, response: LLMResult, **kwargs: object) -> None:
        for gen_list in response.generations:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                um = getattr(msg, "usage_metadata", None) if msg is not None else None
                if um:
                    self.input_tokens += int(um.get("input_tokens", 0))
                    self.output_tokens += int(um.get("output_tokens", 0))
                    details = um.get("input_token_details") or {}
                    self.cached_tokens += int(details.get("cache_read", 0) or 0)
                    self.cache_write_tokens += int(details.get("cache_creation", 0) or 0)
                    output_details = um.get("output_token_details") or {}
                    self.reasoning_tokens += int(
                        output_details.get("reasoning", 0)
                        or output_details.get("reasoning_tokens", 0)
                        or 0
                    )
                meta = getattr(msg, "response_metadata", None) if msg is not None else None
                if isinstance(meta, dict) and "cost" in meta:
                    self.real_cost_usd += float(meta["cost"])
                    self.has_real_cost = True
                self._read_raw_usage(meta)
        self._read_raw_usage(response.llm_output)

    def _read_raw_usage(self, payload: object) -> None:
        """Fall back to OpenRouter's raw ``usage`` shape when LangChain drops it."""
        if not isinstance(payload, dict):
            return
        usage = payload.get("token_usage") or payload.get("usage")
        if isinstance(usage, dict):
            prompt_details = usage.get("prompt_tokens_details") or {}
            if isinstance(prompt_details, dict) and not self.cached_tokens:
                self.cached_tokens += int(prompt_details.get("cached_tokens", 0) or 0)
                self.cache_write_tokens += int(
                    prompt_details.get("cache_write_tokens", 0) or 0
                )
            completion_details = usage.get("completion_tokens_details") or {}
            if isinstance(completion_details, dict) and not self.reasoning_tokens:
                self.reasoning_tokens += int(
                    completion_details.get("reasoning_tokens", 0) or 0
                )
            if "cost" in usage and not self.has_real_cost:
                self.real_cost_usd += float(usage["cost"])
                self.has_real_cost = True
        discount = payload.get("cache_discount")
        if isinstance(discount, (int, float)):
            self.cache_discount_usd += float(discount)


# ---------------------------------------------------------------------------
# LLMCallLog
# ---------------------------------------------------------------------------

@dataclass
class LLMCallLog:
    """Records usage metrics for a single LLM invocation."""
    model: str
    stage: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    cache_discount_usd: float = 0.0


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------

#: Passed to the sampler for reproducibility. Providers that ignore `seed` simply
#: drop it; temperature=0 remains the primary determinism control.
LLM_SEED = 42

#: Models we have already warned about having no configured price, so a long run
#: does not emit one warning per LLM call.
_UNPRICED_MODELS_WARNED: set[str] = set()
_INVOKE_MAX_ATTEMPTS = 3
_INVOKE_BACKOFF_BASE_S = 0.5


def _retry_after_seconds(exc: Exception, attempt: int) -> float:
    """Return a bounded retry delay for retryable provider failures."""
    headers = getattr(exc, "headers", None)
    retry_after = headers.get("retry-after") if headers is not None else None
    try:
        if retry_after is not None:
            return min(max(float(retry_after), 0.0), 8.0)
    except (TypeError, ValueError):
        pass
    return min(_INVOKE_BACKOFF_BASE_S * (2**attempt), 4.0)


def _is_retryable_invocation_error(exc: Exception, httpx_module: object) -> bool:
    if isinstance(exc, getattr(httpx_module, "ReadTimeout")):
        return True
    if bool(
        _OpenRouterResponseValidationError is not None
        and isinstance(exc, _OpenRouterResponseValidationError)
        and getattr(exc, "status_code", None) == 429
    ):
        return True
    if not (
        _OpenRouterBadRequestResponseError is not None
        and isinstance(exc, _OpenRouterBadRequestResponseError)
    ):
        return False

    # OpenRouter can surface an upstream provider outage as HTTP 400 with no
    # actionable detail. Retry only this explicitly transient form; malformed,
    # unauthorized, and context-window requests must fail immediately.
    message = str(exc).strip().lower()
    return message == "provider returned error"


def _build_chat_model(model_name: str, api_key: str, session_key: str):
    """Construct ChatOpenRouter, degrading gracefully if the wrapper is older.

    `x-session-id` pins OpenRouter's sticky routing to one provider so the
    planner's static prefix stays warm; without it the routing key is derived
    from the (query-dependent) opening messages and every request lands cold.
    """
    model_overrides = dict(MODEL_INVOCATION_CONFIG.get(model_name, {}))
    # A model-specific temperature intentionally replaces the generic default;
    # passing both as explicit keywords raises TypeError in Python.
    temperature = model_overrides.pop("temperature", 0)
    base = {
        "model": model_name,
        "api_key": api_key,
        "temperature": temperature,
        "max_retries": 2,
        "timeout": 480_000,  # 480 s in ms; ChatOpenRouter native param (not request_timeout)
    }
    extras = {
        "top_p": 1,
        "seed": LLM_SEED,
        "session_id": session_key[:128],
    }
    # The project configuration uses OpenRouter API names. ChatOpenRouter
    # exposes the provider choice and arbitrary request fields differently.
    # Normalize them before construction so an unsupported keyword never
    # triggers the compatibility fallback that would also discard max_tokens.
    provider = model_overrides.pop("provider", None)
    if provider is not None:
        model_overrides["openrouter_provider"] = provider
    response_format = model_overrides.pop("response_format", None)
    if response_format is not None:
        model_kwargs = dict(model_overrides.get("model_kwargs", {}))
        model_kwargs["response_format"] = response_format
        model_overrides["model_kwargs"] = model_kwargs
    # Per-model overrides (provider pinning, reasoning, response_format, ...)
    # take precedence over the generic determinism settings.
    try:
        return ChatOpenRouter(**base, **extras, **model_overrides)
    except (TypeError, ValueError) as exc:
        if model_overrides:
            # The model-specific options may be newer than the installed wrapper;
            # retry without them so session pinning and seed are preserved.
            try:
                return ChatOpenRouter(**base, **extras)
            except (TypeError, ValueError):
                pass
        warnings.warn(
            f"ChatOpenRouter rejected determinism/cache/provider options ({exc}); "
            "falling back to temperature-only determinism.",
            RuntimeWarning,
            stacklevel=2,
        )
        return ChatOpenRouter(**base)


def _is_groq_model(model_name: str) -> bool:
    """Return True if *model_name* should be routed through Groq.

    Supports bare Groq IDs such as ``allam-2-7b``, the explicit ``groq/``
    prefix, and Groq's OpenAI-namespaced GPT-OSS models.
    """
    if not model_name:
        return False
    return (
        model_name.startswith("groq/")
        or model_name.startswith("openai/gpt-oss-")
        or "/" not in model_name
    )


def _canonical_groq_model_name(model_name: str) -> str:
    return model_name.removeprefix("groq/")


def _build_groq_chat_model(model_name: str, api_key: str):
    """Construct a ChatGroq instance for Groq-hosted light models."""
    if _ChatGroq is None:
        raise ImportError(
            "Groq models require langchain-groq. "
            "Install it with: pip install langchain-groq"
        )
    return _ChatGroq(
        model=_canonical_groq_model_name(model_name),
        # groq_api_key=api_key,
        temperature=0,
        max_retries=2,
        timeout=120,
    )


def _is_ollama_model(model_name: str) -> bool:
    """Return True if *model_name* should be routed to a local Ollama server.

    Requires the explicit ``ollama/`` prefix (e.g. ``ollama/qwen2.5:3b-instruct``); bare
    Ollama tags contain no ``/`` and would otherwise be mistaken for Groq IDs
    by ``_is_groq_model``.
    """
    return model_name.startswith("ollama/")


def _canonical_ollama_model_name(model_name: str) -> str:
    return model_name.removeprefix("ollama/")


def _build_ollama_chat_model(model_name: str):
    """Construct a ChatOllama instance for a local Ollama-hosted light model."""
    if _ChatOllama is None:
        raise ImportError(
            "Ollama models require langchain-ollama. "
            "Install it with: pip install langchain-ollama"
        )
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    return _ChatOllama(
        model=_canonical_ollama_model_name(model_name),
        base_url=base_url,
        temperature=0,
    )


class LLMClient:
    """
    Wraps a chat model with call logging and cost estimation.

    One LLMClient instance per (baseline, query) benchmark run so that
    call_log and totals are isolated.

    Usage:
        client = LLMClient(model_name="meta-llama/llama-3.1-8b-instruct", api_key=os.environ["OPENROUTER_API_KEY"])
        result = client.invoke_chain(chain, {"input": "..."}, stage="S1")
        print(client.total_cost_usd())
    """

    def __init__(
        self,
        model_name: str,
        api_key: str,
        light_model_name: str | None = None,
        light_api_key: str | None = None,
        _shared_call_log: list["LLMCallLog"] | None = None,
    ) -> None:
        """
        Args:
            model_name:       Primary model identifier (must be a key in
                              config.MODEL_RATE_PER_1M_TOKENS).
            api_key:          Provider API key for the primary model
                              (OPENROUTER_API_KEY for OpenRouter, GROQ_API_KEY
                              for Groq).
            light_model_name: Optional lighter model used for cheap early stages
                              (e.g. Flash-Fusion S1/S2 and cache grounding). When
                              set and different from model_name, ``self.light`` is
                              a sibling LLMClient bound to that model whose calls
                              are logged into this client's call_log, so
                              cost/latency/token totals remain aggregated on the
                              primary client.
            light_api_key:    Optional separate API key for the light model. Use
                              this when the light model is hosted on a different
                              provider than the primary model (e.g. Groq light
                              with an OpenRouter primary).
            _shared_call_log: Internal — when provided, this instance is a light
                              sibling that shares the primary client's call_log.
        """
        if light_model_name is None and model_name != DEFAULT_LIGHT_MODEL:
            light_model_name = DEFAULT_LIGHT_MODEL

        self.model_name = model_name
        self.session_key = planner_cache_key(model_name, os.getenv("FF_ENV", "dev"))
        if _is_ollama_model(model_name):
            self.llm = _build_ollama_chat_model(model_name)
        elif _is_groq_model(model_name):
            self.llm = _build_groq_chat_model(model_name, api_key)
        else:
            self.llm = _build_chat_model(model_name, api_key, self.session_key)
        # A light sibling shares the primary's call_log so totals aggregate once.
        self.call_log: list[LLMCallLog] = (
            _shared_call_log if _shared_call_log is not None else []
        )
        # Retry overhead is deliberately excluded from benchmark metrics. Only
        # the completed provider attempt is comparable across queries.
        self.last_invocation_latency_s = 0.0
        self.last_retry_overhead_s = 0.0
        if _shared_call_log is not None:
            # This instance IS the light sibling; route .light to itself.
            self.light: "LLMClient" = self
        elif light_model_name and light_model_name != model_name:
            if _is_ollama_model(light_model_name):
                light_key = ""  # ChatOllama needs no API key
            elif _is_groq_model(light_model_name):
                light_key = (
                    light_api_key
                    or os.environ.get("GROQ_API_KEY")
                    or api_key
                )
            else:
                light_key = light_api_key or api_key
            self.light = LLMClient(
                model_name=light_model_name,
                api_key=light_key,
                _shared_call_log=self.call_log,
            )
        else:
            self.light = self

    def invoke_chain(self, chain, inputs: dict, stage: str) -> str:
        """
        Invoke a LangChain chain, record usage, and return the string output.

        Args:
            chain:  Any LangChain Runnable (e.g. prompt | llm | StrOutputParser()).
            inputs: Dict of template variables for the chain.
            stage:  Human-readable label for this call (e.g. "S1", "guardrail").

        Returns:
            String output from the chain.
        """
        return self._invoke(chain, inputs, stage)

    def invoke_messages(self, messages: list, stage: str) -> str:
        """Invoke the chat model on an explicit message list.

        Required for the Flash-Fusion planner: its static prefix is full of
        literal ``{``/``}`` from the operator JSON spec, which a
        ``ChatPromptTemplate`` would try to interpolate. Passing messages
        directly also keeps the prefix byte-identical across requests.
        """
        return self._invoke(self.llm, messages, stage)

    def warm_prompt_cache(self, messages: list, stage: str = "prompt_cache_warmup") -> str:
        """Send a disposable one-token request to populate a provider prompt cache.

        Callers must use a separate client from timed benchmark queries. This
        preserves the provider session and exact static prefix while ensuring
        warmup usage cannot leak into benchmark token or cost totals.
        """
        return self._invoke(self.llm.bind(max_tokens=1), messages, stage)

    def _invoke(self, runnable, payload, stage: str) -> str:
        import sys as _sys
        import httpx as _httpx

        self.last_invocation_latency_s = 0.0
        self.last_retry_overhead_s = 0.0
        capture = _UsageCapture()
        for attempt in range(_INVOKE_MAX_ATTEMPTS):
            attempt_started = time.perf_counter()
            try:
                result = runnable.invoke(payload, config={"callbacks": [capture]})
                latency = time.perf_counter() - attempt_started
                self.last_invocation_latency_s = latency
                break
            except Exception as exc:
                self.last_retry_overhead_s += time.perf_counter() - attempt_started
                if not _is_retryable_invocation_error(exc, _httpx):
                    raise
                if attempt + 1 == _INVOKE_MAX_ATTEMPTS:
                    raise RuntimeError(
                        f"LLM invocation failed after {_INVOKE_MAX_ATTEMPTS} retryable attempts "
                        f"(stage={stage!r})"
                    ) from exc
                retry_delay = _retry_after_seconds(exc, attempt)
                _sys.stdout.write(
                    f"  [WARN invoke_chain] {type(exc).__name__} on attempt "
                    f"{attempt + 1}/{_INVOKE_MAX_ATTEMPTS} (stage={stage!r}); "
                    f"retrying in {retry_delay:.1f}s…\n"
                )
                _sys.stdout.flush()
                time.sleep(retry_delay)
                self.last_retry_overhead_s += retry_delay
        if isinstance(result, str):
            output_text = result
        else:
            output_text = str(getattr(result, "content", result))
        in_tok = capture.input_tokens
        out_tok = capture.output_tokens
        # Prefer OpenRouter's real, provider-billed cost (reflects any prompt-cache
        # discount) over the flat per-token estimate; the estimate is only a
        # fallback for providers/requests that don't report `usage.cost`.
        cost = (
            capture.real_cost_usd
            if capture.has_real_cost
            else self._compute_cost(in_tok, out_tok)
        )
        self.call_log.append(
            LLMCallLog(
                model=self.model_name,
                stage=stage,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_s=latency,
                cost_usd=cost,
                reasoning_tokens=capture.reasoning_tokens,
                cached_tokens=capture.cached_tokens,
                cache_write_tokens=capture.cache_write_tokens,
                cache_discount_usd=capture.cache_discount_usd,
            )
        )
        return output_text

    def _compute_cost(self, in_tok: int, out_tok: int) -> float:
        """
        Compute USD cost from token counts using config.MODEL_RATE_PER_1M_TOKENS.

        An unpriced model would otherwise report $0.00 for an entire benchmark
        run, which reads as a result rather than as missing configuration — so
        warn once instead of returning a silent zero.
        """
        rates = MODEL_RATE_PER_1M_TOKENS.get(self.model_name)
        if rates is None:
            if self.model_name not in _UNPRICED_MODELS_WARNED:
                _UNPRICED_MODELS_WARNED.add(self.model_name)
                warnings.warn(
                    f"No rate configured for model {self.model_name!r}; all "
                    "reported costs for it will be $0.00. Add an entry to "
                    "config.MODEL_RATE_PER_1M_TOKENS.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            rates = {"input": 0.0, "output": 0.0}
        return (
            in_tok * rates.get("input", 0.0) + out_tok * rates.get("output", 0.0)
        ) / 1_000_000

    def total_latency(self) -> float:
        return sum(c.latency_s for c in self.call_log)

    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.call_log)

    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.call_log)

    def total_tokens(self) -> int:
        return self.total_input_tokens() + self.total_output_tokens()

    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.call_log)

    def total_cached_tokens(self) -> int:
        return sum(c.cached_tokens for c in self.call_log)

    def total_cache_write_tokens(self) -> int:
        return sum(c.cache_write_tokens for c in self.call_log)

    def total_cache_discount_usd(self) -> float:
        return sum(c.cache_discount_usd for c in self.call_log)


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """
    Captures the full output of one (baseline, query) benchmark run.

    Fields set by BaselineRunner.run() — do not set manually from outside.
    """
    baseline: str                                    # e.g. "LLM_ONLY"
    model: str                                       # e.g. "llama-3.3-70b-versatile"
    query: str                                       # original query text
    query_id: int = 0                                # stable identity shared by v1/v2/v3; 0 means legacy/unknown

    # Outputs
    answer: str = ""                                 # final natural-language answer
    raw_answer: str = ""                             # pre-synthesis machine answer (dict/scalar repr), "" if synthesis wasn't run or made no change
    trace: str = ""                                  # agent ReAct trace (if executed)

    # Metrics (populated after run completes)
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached_tokens: int = 0                           # prompt tokens served from the provider cache (0 = not observed)
    cache_write_tokens: int = 0
    cache_discount_usd: float = 0.0

    # Execution state
    executed: bool = False                           # True if pandas agent ran code
    stages_run: list = field(default_factory=list)  # e.g. ["S1","S2","S3","guardrail","agent","judge"]
    judge_verdict: dict = field(default_factory=dict)  # {"verdict": "PASS"|"FAIL", "issue": str, ...}
    alignment_explanation: str = ""                   # user-facing alignment/rejection rationale
    rejected: bool = False                           # True if guardrail or S2 rejected query
    rejection_reason: str = ""
    answer_source: str = ""                         # executed_observation | structured_rejection | model_final_answer
    executed_value: object | None = None

    # Agent details
    final_code: str = ""                             # last successfully executed pandas code
    agent_tries: int = 0                             # total agent iterations across sub-queries
    execution_attempts: list = field(default_factory=list)  # per-attempt stats
    deterministic_fallback_reason: str = ""         # why the typed path fell back to ReAct
    guardrail_input: str = ""                         # exact post-S2 prompt sent to guardrail
    grounded_query: str = ""                         # S3-oriented prompt constructed by Flash-Fusion
    react_query: str = ""                            # exact prompt sent to the ReAct agent, if delegated

    # Typed-operator instrumentation (Flash-Fusion). These are the primary
    # signals for the typed-vs-ReAct comparison; stages_run remains a coarse
    # human-readable audit trail only.
    execution_path: str = ""                         # "guardrail_reject" | "typed_operator" | "typed_plan_unavailable" | "react_fallback" | "scope_reject" | "react_agent" | "react_reject"
    plan_validation_stage_failed: str = ""           # "" | "structural" | "schema" | "scope" | "execution" | "no_plan"
    typed_plan: dict = field(default_factory=dict)   # the validated DeterministicPlan, as JSON
    typed_execution_certificate: dict = field(default_factory=dict)  # canonical executed typed provenance
    operators_used: list = field(default_factory=list)  # op names fired, for the offline gap report
    plan_source: str = ""                            # "llm" for planner-originated typed plans
    ambiguous_concepts: list = field(default_factory=list)  # concepts the planner could not resolve literally
    raw_plan: dict = field(default_factory=dict)     # planner output before normalization
    normalization_actions: list = field(default_factory=list)  # named deterministic rewrites applied
    normalization_version: str = ""
    missing_columns: list = field(default_factory=list)  # schema fields the query needs but the dataset lacks
    cache_grounding_failure: dict = field(default_factory=dict)  # failed cache attempt captured before planner fallback

    # Full-planner telemetry (Flash-Fusion only). These remain zero/False for
    # all other baselines and for calls that fail before usage is reported by
    # the provider.
    ff_planner_used: bool = False
    ff_planner_latency_s: float = 0.0
    ff_planner_input_tokens: int = 0
    ff_planner_output_tokens: int = 0
    ff_planner_cost_usd: float = 0.0

    # Deterministic operator router (Flash-Fusion only). Every planner failure
    # must be attributable to the named rule that removed a bucket, so the rules
    # and the buckets they eliminated are recorded on every run.
    operator_route_excluded_buckets: list = field(default_factory=list)
    operator_route_matched_rules: list = field(default_factory=list)
    operator_route_candidate_ops: list = field(default_factory=list)
    operator_route_full_fallback: bool = False

    # --- Flash-Fusion policy provenance ------------------------------------
    # Which of (cache, pruning, planner guidance) were active for this run.
    # Recorded directly rather than inferred from `baseline`, so legacy and
    # current labels can be pooled and so an ablation can never be mislabelled
    # by a call-site override. Populated by
    # baselines.flash_fusion_no_cache.record_policy_provenance().
    policy_name: str = ""                            # e.g. "FF_NO_PRUNE"
    policy_cache_enabled: bool = False
    policy_pruning_enabled: bool = False
    policy_planner_guidance_enabled: bool = False
    policy_role: str = ""                            # full_system | primary_ablation | diagnostic
    policy_reference: str = ""                       # policy this arm is differenced against
    policy_treatment: str = ""                       # the single component this arm removes
    policy_digest: str = ""                          # digest of the settings, label-independent
    route_mode: str = ""                             # "router" (pruned) | "full"
    planner_guidance_mode: str = ""                  # "full" | "none"

    # Pruning / prompting mechanism telemetry. These are the quantities the
    # pruning and prompting treatments actually change, so aggregate claims
    # about either are reproducible from per-query records.
    planner_candidate_op_count: int = 0              # operators shown to the planner
    planner_full_vocabulary: bool = False            # True when no bucket was pruned away
    planner_prefix_chars: int = 0                    # size of the cached system prefix
    planner_suffix_chars: int = 0                    # size of the per-query human message

    # Cache outcome, recorded on the cache path itself rather than derived
    # post hoc from execution_path by the metrics/visualization layer.
    cache_outcome: str = ""                          # exact_hit | semantic_hit | hit_rejected | miss | disabled
    cache_outcome_reason: str = ""                   # lookup status / gate that produced the outcome

    # Prompt-prefix / cache provenance
    planner_prefix_version: str = ""
    planner_prefix_sha256: str = ""
    planner_cache_key: str = ""
    schema_fingerprint: str = ""
    typed_plan_sha256: str = ""                      # stability signal across repeated runs

    # Pipeline stage intermediates (populated by rewriting baselines: WELLMAX_ONLY, FLASH_FUSION)
    s1_concepts: dict = field(default_factory=dict)      # Stage 1 output: {"DATA": [...], "REASONING": [...]}
    s2_grounding: str = ""                               # Stage 2 raw LLM grounding text
    s2_filtered_concepts: dict = field(default_factory=dict)  # concepts sent to S2 grounding LLM after the query-critical filter (pre-repair/pre-validation view)
    s3_sub_queries: list = field(default_factory=list)   # Stage 3 concrete sub-questions
    s3_synthesis_hint: str = ""                          # Stage 3 synthesis guidance string

    # Stage latency telemetry (seconds)
    stage_latency_s: dict = field(default_factory=dict)   # canonical keys depend on baseline
                                                           #   FLASH_FUSION*: guardrail+plan, typed_exec, agent, cache_*
                                                           #   AUTOIOT_PAPER: s1, s2, s3, guardrail, agent
    stage_events: list = field(default_factory=list)       # operation-level stage timing audit trail


# ---------------------------------------------------------------------------
# BaselineRunner
# ---------------------------------------------------------------------------

class BaselineRunner:
    """
    Dispatches a query to the correct baseline implementation.

    Supported modes (self.MODES):
        "LLM_ONLY"     — B0: raw 20-row CSV + query → single LLM call
        "WELLMAX_ONLY"  — B3: S1 + S2 + S3 → grounded query → pandas agent
        "REACT_ONLY"  — ReAct: raw query → pandas agent (paper-faithful ReAct)
        "LLMSENSE_PAPER" — narration/summarization + reasoning over narrative text

    Flash-Fusion policy modes — every one of these is the same implementation
    under a different (cache, pruning, planner-guidance) setting, resolved via
    baselines.flash_fusion_policy.resolve_policy(). See that module, and
    docs/flash_fusion_ablation_policy_matrix.md, for the full matrix.

        "FF_FULL"       — cache + pruning + guidance (the full system)
        "FF_NO_CACHE"   — cache off; pruning and guidance unchanged
        "FF_NO_PRUNE"   — pruning off; cache and guidance match FF_NO_CACHE
        "FF_NO_PROMPT"  — planner composition guidance off; cache and pruning
                          match FF_NO_CACHE
        diagnostics: "FF_NO_PRUNE_CACHED", "FF_NO_PROMPT_CACHED",
                     "FF_NO_PRUNE_NO_PROMPT"
        legacy aliases (unchanged semantics, still accepted and still written
        out under their original label): "FLASH_FUSION" -> FF_NO_CACHE,
        "FLASH_FUSION_CACHE" -> FF_FULL, "FF_NO_PRUNING" -> FF_NO_PRUNE,
        "FF_NO_PLANNING" -> FF_NO_PRUNE_NO_PROMPT

    Rewriting baselines derive features only after schema grounding explicitly
    identifies a computation supported by the raw dataset columns.
    """

    #: Non-Flash-Fusion baselines.
    NON_POLICY_MODES: frozenset = frozenset(
        {
            "LLM_ONLY",
            "WELLMAX_ONLY",
            "REACT_ONLY",
            "AUTOIOT_PAPER",
            "HARGPT_PAPER",
            "LLMSENSE_PAPER",
        }
    )

    MODES: frozenset = NON_POLICY_MODES | frozenset(POLICIES) | frozenset(
        LEGACY_POLICY_ALIASES
    )

    def __init__(
        self,
        mode: str,
        df: pd.DataFrame,
        client: LLMClient,
        data_path: str = "WISDM",
        predictive_timeout_s: float | None = None,
        dataset: str | None = None,
        cache_path: str | None = None,
        semantic_cache_path: str | None = None,
        copy_dataframe: bool = True,
    ) -> None:
        """
        Args:
            mode:       One of self.MODES.
            df:         WISDM DataFrame.
            client:     LLMClient for this run.
            data_path:  Descriptive label injected into agent prefix (not a file path).
            dataset:    Dataset key ("wisdm" | "mit_ecg" | "bus"). Required by
                        FLASH_FUSION_CACHE to scope cache lookups; omitting it
                        allows a hit only when the query text is unique across
                        datasets in the registry.
            cache_path: Override for the operator-skeleton cache registry
                        (FLASH_FUSION_CACHE only).
            semantic_cache_path: Optional registry of semantic cache templates
                        (FLASH_FUSION_CACHE only).
            copy_dataframe: Whether to isolate the supplied DataFrame. Set false
                only when the caller manages an immutable shared frame.

        Raises:
            ValueError: If mode is not in self.MODES.
        """
        # DEBUG: Check what df we receive
        import sys
        # print(f"[RUNNER INIT DEBUG] mode={mode}, df len={len(df)}, df cols={list(df.columns) if hasattr(df, 'columns') else 'N/A'}", file=sys.stderr, flush=True)
        # if len(df) > 0:
        #     print(f"[RUNNER INIT DEBUG] df.head(3):\n{df.head(3)}", file=sys.stderr, flush=True)
        
        if mode not in self.MODES:
            raise ValueError(f"mode must be one of {self.MODES}, got {mode!r}")
        self.mode = mode
        self.df = df.copy() if copy_dataframe else df
        self.client = client
        self.data_path = data_path
        self.predictive_timeout_s = predictive_timeout_s
        self.dataset = dataset
        self.cache_path = cache_path
        self.semantic_cache_path = semantic_cache_path
        self.policy = resolve_policy(mode) if is_flash_fusion_policy(mode) else None
        if self.policy is not None:
            from flashfusion.baselines.flash_fusion_no_cache import (
                warm_flash_fusion_prefix,
            )

            # Warm the prefix variant this policy will actually send, so no arm
            # pays a first-call assembly cost another arm avoided.
            warm_flash_fusion_prefix(
                self.df,
                self.client,
                planner_guidance=self.policy.planner_guidance_mode,
            )

    def run(self, query: str) -> RunResult:
        """
        Execute the full baseline pipeline for one query.

        Args:
            query: Raw natural language query string.

        Returns:
            Populated RunResult. latency_s, input_tokens, output_tokens,
            and cost_usd are set from client.call_log after execution.

        Implementation:
            1. r = RunResult(baseline=self.mode, model=self.client.model_name, query=query)
            2. t0 = time.time()
            3. Dispatch to _run_<mode>(query, r)
            4. r.latency_s = time.time() - t0
            5. r.input_tokens  = self.client.total_input_tokens()
            6. r.output_tokens = self.client.total_output_tokens()
            7. r.cost_usd      = self.client.total_cost_usd()
            8. return r
        """
        r = RunResult(
            baseline=self.mode, model=self.client.model_name, query=query
        )
        t0 = time.time()
        input_tokens_before = self.client.total_input_tokens()
        output_tokens_before = self.client.total_output_tokens()
        cost_usd_before = self.client.total_cost_usd()
        cached_tokens_before = self.client.total_cached_tokens()
        cache_write_tokens_before = self.client.total_cache_write_tokens()
        cache_discount_usd_before = self.client.total_cache_discount_usd()

        from flashfusion.baselines.react_only import run_react_only
        from flashfusion.baselines.autoiot_paper import run_autoiot_paper
        from flashfusion.baselines.hargpt_paper import run_hargpt_paper
        from flashfusion.baselines.llmsense_paper import run_llmsense_paper
        from flashfusion.baselines.llm_only import run_llm_only

        if self.policy is not None:
            # One call site for every Flash-Fusion arm. The policy decides
            # cache / pruning / guidance; nothing else about the run differs,
            # so an arm cannot accidentally change a second component.
            run_with_policy(
                query,
                self.df,
                self.client,
                r,
                self.policy,
                timeout_s=self.predictive_timeout_s,
                dataset=self.dataset,
                cache_path=self.cache_path,
                semantic_cache_path=self.semantic_cache_path,
            )
        elif self.mode == "LLM_ONLY":
            run_llm_only(query, self.df, self.client, r)
        elif self.mode == "REACT_ONLY":
            run_react_only(query, self.df, self.client, r)
        elif self.mode == "AUTOIOT_PAPER":
            run_autoiot_paper(query, self.df, self.client, r)
        elif self.mode == "HARGPT_PAPER":
            # DEBUG: Check dataframe before calling HARGPT
            import sys
            print(f"[RUNNER DEBUG] Before HARGPT call - df len={len(self.df)}, cols={list(self.df.columns) if hasattr(self.df, 'columns') else 'N/A'}", file=sys.stderr, flush=True)
            if len(self.df) > 0:
                print(f"[RUNNER DEBUG] df.head(3):\n{self.df.head(3)}", file=sys.stderr, flush=True)
            run_hargpt_paper(query, self.df, self.client, r)
        elif self.mode == "LLMSENSE_PAPER":
            run_llmsense_paper(query, self.df, self.client, r)

        # column_metadata is a one-off DataFrame scan, not query-specific work —
        # exclude it so latency_s reflects time from schema-known onward.
        r.latency_s = time.time() - t0 - r.stage_latency_s.get("column_metadata", 0.0)
        r.input_tokens = self.client.total_input_tokens() - input_tokens_before
        r.output_tokens = self.client.total_output_tokens() - output_tokens_before
        r.cost_usd = self.client.total_cost_usd() - cost_usd_before
        r.cached_tokens = self.client.total_cached_tokens() - cached_tokens_before
        r.cache_write_tokens = self.client.total_cache_write_tokens() - cache_write_tokens_before
        r.cache_discount_usd = self.client.total_cache_discount_usd() - cache_discount_usd_before
        return r

    def _run_llm_only(self, query: str, r: RunResult) -> RunResult:
        """Delegates to baselines.llm_only.run_llm_only."""
        from flashfusion.baselines.llm_only import run_llm_only
        return run_llm_only(query, self.df, self.client, r)

    def _run_react_only(self, query: str, r: RunResult) -> RunResult:
        """Delegates to baselines.react_only.run_react_only."""
        from flashfusion.baselines.react_only import run_react_only
        return run_react_only(query, self.df, self.client, r)

    def _run_flash_fusion(self, query: str, r: RunResult) -> RunResult:
        """Delegates to the policy runner using this runner's active policy."""
        policy = self.policy or resolve_policy("FF_NO_CACHE")
        return run_with_policy(
            query,
            self.df,
            self.client,
            r,
            policy,
            timeout_s=self.predictive_timeout_s,
            dataset=self.dataset,
            cache_path=self.cache_path,
            semantic_cache_path=self.semantic_cache_path,
        )
