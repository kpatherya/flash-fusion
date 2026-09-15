"""
eval/ground_truth_llm_judge.py — LLM-based judging against benchmark ground truth.

This module supports two workflows:
1) Standalone: judge existing `raw_results.jsonl` files under eval_results/*_all.
2) Programmatic: judge in-memory RunResult rows emitted by benchmark.py.
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import os
from pathlib import Path
import re
import time
import warnings
from typing import Any

import pandas as pd
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from flashfusion.config import DEFAULT_MODEL
from flashfusion.eval.ground_truth import GroundTruthEntry, load_ground_truth
from flashfusion.eval.build_groundtruth.ground_truth_builder import build_ground_truth
from flashfusion.eval.queries import DATASET_WISDM, SUPPORTED_DATASETS, get_queries
from flashfusion.eval.queries_v2 import get_queries as get_queries_v2
from flashfusion.eval.queries_v3 import get_queries as get_queries_v3
from flashfusion.eval.semantic_scorer import SemanticScorer
from flashfusion.pipeline.loader import load_dataset_by_name
from flashfusion.pipeline.runner import LLMClient, RunResult


_JUDGE_MAX_ATTEMPTS = 4


def _extract_number_values(text: str) -> list[float]:
    vals: list[float] = []
    for match in re.findall(r"-?\d+(?:\.\d+)?", text or ""):
        try:
            vals.append(float(match))
        except ValueError:
            continue
    return vals


def _extract_single_quoted_labels(text: str) -> list[str]:
    return [x.strip().lower() for x in re.findall(r"'([^']+)'", text or "") if x.strip()]


def _first_nonempty_match(pattern: str, text: str) -> str:
    m = re.search(pattern, text or "", flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return str(m.group(1)).strip()


def _parse_llm_judge_payload(llm_raw: str) -> tuple[dict[str, Any], str]:
    parsed = _extract_first_json(llm_raw)
    verdict = str(parsed.get("verdict", "")).upper()
    if verdict in {"PASS", "FAIL"}:
        return parsed, "json"

    # Fallback for truncated JSON responses: salvage key fields with regex.
    salvaged_verdict = _first_nonempty_match(r'"verdict"\s*:\s*"(PASS|FAIL)"', llm_raw).upper()
    if salvaged_verdict not in {"PASS", "FAIL"}:
        return {}, "invalid"

    salvaged: dict[str, Any] = {
        "verdict": salvaged_verdict,
        "reason": _first_nonempty_match(r'"reason"\s*:\s*"([^\"]*)"', llm_raw),
        "ground_truth_sanity": _first_nonempty_match(
            r'"ground_truth_sanity"\s*:\s*"(SOUND|POSSIBLY_WRONG|WRONG)"', llm_raw
        ).upper(),
        "ground_truth_note": _first_nonempty_match(
            r'"ground_truth_note"\s*:\s*"([^\"]*)"', llm_raw
        ),
    }
    return salvaged, "salvaged_truncated_json"


def _deterministic_pass_override(
    *,
    gt_answer: str,
    candidate_answer: str,
    expected_rejection: bool,
    candidate_rejected: bool,
) -> str:
    """Return a non-empty reason when a deterministic PASS override is safe."""
    if expected_rejection or candidate_rejected:
        return ""

    gt_numbers = _extract_number_values(gt_answer)
    cand_numbers = _extract_number_values(candidate_answer)
    if len(gt_numbers) == 1 and cand_numbers:
        target = gt_numbers[0]
        if any(abs(target - val) < 0.01 for val in cand_numbers):
            return "Deterministic override: candidate contains the same primary numeric value as ground truth."

    gt_labels = set(_extract_single_quoted_labels(gt_answer))
    cand_labels = set(_extract_single_quoted_labels(candidate_answer))
    if (
        gt_labels
        and gt_labels.issubset(cand_labels)
        and "predict" in gt_answer.lower()
        and "predict" in candidate_answer.lower()
        and "holdout row" in gt_answer.lower()
        and "holdout row" in candidate_answer.lower()
    ):
        return "Deterministic override: predicted holdout label matches ground truth; wording drift is non-semantic."

    return ""


def _invoke_judge_with_retries(
    *,
    client: LLMClient,
    chain: Any,
    payload: dict[str, str],
) -> tuple[dict[str, Any], str, str, int]:
    """
    Invoke judge chain with retries for provider and malformed-output failures.

    Returns: (parsed_payload, raw_text, parse_status, attempts_used)
    """
    last_error = ""
    last_raw = ""
    last_parse_status = "invalid"

    for attempt in range(1, _JUDGE_MAX_ATTEMPTS + 1):
        try:
            llm_raw = client.invoke_chain(chain, payload, stage="gt_llm_judge")
            last_raw = llm_raw
        except Exception as exc:
            last_error = f"invoke_error:{type(exc).__name__}:{exc}"
            if attempt < _JUDGE_MAX_ATTEMPTS:
                time.sleep(min(0.5 * attempt, 2.0))
                continue
            break

        parsed, parse_status = _parse_llm_judge_payload(llm_raw)
        last_parse_status = parse_status
        if str(parsed.get("verdict", "")).upper() in {"PASS", "FAIL"}:
            return parsed, llm_raw, parse_status, attempt

        last_error = f"parse_error:{parse_status}"
        if attempt < _JUDGE_MAX_ATTEMPTS:
            time.sleep(min(0.35 * attempt, 1.5))

    return (
        {
            "verdict": "FAIL",
            "reason": (
                "Judge infrastructure fallback: unable to obtain valid JSON verdict "
                f"after retries ({last_error or 'unknown_error'})."
            ),
            "ground_truth_sanity": "",
            "ground_truth_note": "",
        },
        last_raw,
        f"fallback:{last_parse_status}:{last_error or 'unknown_error'}",
        _JUDGE_MAX_ATTEMPTS,
    )


def _query_lookup(dataset: str) -> dict[str, int]:
    """Build a guarded text lookup for legacy artifacts without query IDs."""
    lookup: dict[str, int] = {}
    for version, queries in (
        ("v1", get_queries(dataset)),
        ("v2", get_queries_v2(dataset)),
        ("v3", get_queries_v3(dataset)),
    ):
        for query in queries:
            text = str(query["text"])
            query_id = int(query["id"])
            existing = lookup.get(text)
            if existing is not None and existing != query_id:
                raise ValueError(
                    "Conflicting query identity across catalogs: "
                    f"dataset={dataset!r}, version={version!r}, text={text!r}, "
                    f"query_ids=({existing}, {query_id})"
                )
            lookup[text] = query_id
    return lookup


def _resolve_query_id(
    row: dict[str, Any],
    query_lookup: dict[str, int],
    ground_truth_by_id: dict[int, GroundTruthEntry],
) -> tuple[int, str]:
    """Resolve stable identity, preferring the persisted numeric query ID."""
    raw_query_id = row.get("query_id")
    if raw_query_id not in (None, "", 0, "0"):
        try:
            query_id = int(raw_query_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid explicit query_id {raw_query_id!r} in row") from exc
        source = "explicit"
    else:
        query_text = str(row.get("query", ""))
        query_id = query_lookup.get(query_text, 0)
        if query_id == 0:
            raise ValueError(
                "Unable to resolve query identity: result row has no explicit "
                f"query_id and query text matches no known version: {query_text!r}"
            )
        source = "legacy_query_text"
        warnings.warn(
            "Result row has no explicit query_id; resolved it from legacy query "
            f"text as query_id={query_id}. Re-run the benchmark to persist IDs.",
            RuntimeWarning,
            stacklevel=2,
        )

    if query_id not in ground_truth_by_id:
        raise ValueError(
            f"Resolved query_id={query_id} is absent from the loaded ground truth"
        )
    return query_id, source


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + " ...[truncated]"


def _normalize_answer(text: str) -> str:
    """
    Normalize numeric answers for robust comparison.
    
    - Strips trailing sentence-ending periods from numbers
    - Rounds floats to 3 decimal places for consistent formatting
    - Preserves original text structure otherwise
    """
    import re
    
    text = (text or "").strip()
    
    # Pattern: number (possibly negative, with decimals) followed by period at word boundary
    # Replace trailing period only when it's sentence punctuation, not part of number
    def normalize_number(match):
        num_str = match.group(1)
        try:
            # Parse as float and round to 3 decimals
            num = float(num_str)
            # Format with up to 3 decimals, stripping unnecessary trailing zeros
            formatted = f"{num:.3f}".rstrip('0').rstrip('.')
            return formatted
        except (ValueError, OverflowError):
            return num_str
    
    # Match numbers (integer or float, possibly negative) followed by optional period
    # Capture number, normalize it, and remove trailing period if present
    text = re.sub(r'(-?\d+\.?\d*)(?:\.(?=\s|$))?', normalize_number, text)
    
    return text


def _load_jsonl_rows(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSONL at {path}:{lineno}: {e}") from e
            if isinstance(obj, dict):
                obj["_source_file"] = path
                rows.append(obj)
    return rows


def _rows_from_run_results(results: list[RunResult]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in results:
        row = dataclasses.asdict(r)
        row["_source_file"] = "[in_memory_benchmark_run]"
        out.append(row)
    return out


def _extract_first_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    candidate = text[start : end + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def _resolve_candidate_code(row: dict[str, Any]) -> str:
    """Resolve best available generated code from a result row."""
    final_code = str(row.get("final_code", "")).strip()
    if final_code:
        return final_code

    attempts = row.get("execution_attempts", [])
    if isinstance(attempts, list):
        # Prefer reconstructing a full multi-step typed chain when available.
        chain_lines: list[str] = []
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            code_line = str(
                attempt.get("code")
                or attempt.get("action_input")
                or attempt.get("generated_code")
                or ""
            ).strip()
            if code_line:
                chain_lines.append(code_line)
        if len(chain_lines) > 1:
            return "\n".join(chain_lines)

        for attempt in reversed(attempts):
            if not isinstance(attempt, dict):
                continue
            for key in ("code", "generated_code", "final_code", "candidate_code", "action_input"):
                value = str(attempt.get(key, "")).strip()
                if value:
                    return value

    cert = row.get("typed_execution_certificate")
    if (
        str(row.get("execution_path", "")).strip() in {"typed_operator", "typed_operator_cache"}
        and isinstance(cert, dict)
        and cert.get("certificate_status") == "ok"
    ):
        payload = {
            "certificate_status": cert.get("certificate_status"),
            "typed_plan_sha256": cert.get("typed_plan_sha256", ""),
            "operators_used": cert.get("operators_used", []),
            "rows_scanned": cert.get("rows_scanned"),
            "rows_after_filter": cert.get("rows_after_filter"),
            "latency_ms": cert.get("latency_ms"),
            "result": cert.get("result"),
            "code": cert.get("code", ""),
        }
        return "TYPED_EXECUTION_CERTIFICATE\n" + json.dumps(payload, ensure_ascii=False)

    trace = str(row.get("trace", ""))
    if "Action Input:" in trace:
        action_inputs = [
            ln.split("Action Input:", 1)[1].strip()
            for ln in trace.splitlines()
            if "Action Input:" in ln
        ]
        action_inputs = [x for x in action_inputs if x]
        if action_inputs:
            return action_inputs[-1]

    return ""


def build_ground_truth_sanity(
    ground_truth_by_id: dict[int, GroundTruthEntry],
    data_path: str | None,
    dataset: str,
) -> pd.DataFrame:
    """
    Compare current ground truth against deterministic dataset-derived references.

    Returns a row per query with a semantic similarity score and mismatch flags.
    """
    rows: list[dict[str, Any]] = []
    scorer = SemanticScorer()

    rebuilt_by_id: dict[int, dict[str, Any]] = {}
    if data_path:
        df = load_dataset_by_name(data_path, dataset)
        rebuilt = build_ground_truth(df, dataset)
        rebuilt_by_id = {int(x["query_id"]): x for x in rebuilt}

    for qid in sorted(ground_truth_by_id):
        gt = ground_truth_by_id[qid]
        rebuilt = rebuilt_by_id.get(qid)
        rebuilt_answer = ""
        rebuilt_expected_rejection = None
        sim = None
        rejection_match = None
        if rebuilt:
            rebuilt_answer = str(rebuilt.get("reference_answer", ""))
            rebuilt_expected_rejection = bool(rebuilt.get("expected_rejection", False))
            sim = scorer.score(gt.reference_answer, rebuilt_answer)
            rejection_match = gt.expected_rejection == rebuilt_expected_rejection

        rows.append(
            {
                "query_id": qid,
                "query_text": gt.query_text,
                "gt_expected_rejection": gt.expected_rejection,
                "rebuilt_expected_rejection": rebuilt_expected_rejection,
                "expected_rejection_match": rejection_match,
                "semantic_similarity": sim,
                "gt_reference_answer": gt.reference_answer,
                "rebuilt_reference_answer": rebuilt_answer,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    def _flag(row: pd.Series) -> str:
        sim_val = row.get("semantic_similarity")
        rem = row.get("expected_rejection_match")
        if rem is False:
            return "mismatch_expected_rejection"
        if sim_val is None or pd.isna(sim_val):
            return "no_dataset_sanity"
        if float(sim_val) < 0.55:
            return "low_similarity"
        return "ok"

    out["sanity_flag"] = out.apply(_flag, axis=1)
    return out


def judge_rows_with_llm(
    rows: list[dict[str, Any]],
    ground_truth_by_id: dict[int, GroundTruthEntry],
    dataset: str,
    model_name: str,
    api_key: str,
    sanity_df: pd.DataFrame | None = None,
    max_answer_chars: int = 1800,
    max_code_chars: int = 1400,
) -> pd.DataFrame:
    """Judge final candidate answers against their ground-truth references."""
    q_lookup = _query_lookup(dataset)

    client = None
    chain = None

    judged_rows: list[dict[str, Any]] = []
    for row in rows:
        baseline = str(row.get("baseline", "UNKNOWN"))
        qid, query_id_source = _resolve_query_id(
            row,
            q_lookup,
            ground_truth_by_id,
        )

        gt = ground_truth_by_id[qid]
        candidate_code = _resolve_candidate_code(row)

        candidate_answer = str(row.get("answer", ""))

        if chain is None:
            client = LLMClient(model_name=model_name, api_key=api_key)
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You evaluate final benchmark answers against ground-truth answers. "
                        "Judge factual and semantic equivalence by the final answers only; do not infer correctness from code, execution traces, variable names, or intermediate representations. "
                        "Treat equivalent mathematical formulations as the same answer. "
                        "Treat numeric answers as equivalent if they differ by less than 0.01 or represent the same number with different trailing zeros. "
                        "Return JSON only.",
                    ),
                    (
                        "user",
                        """
Judge whether candidate answer matches ground truth.

Return JSON with keys:
- verdict: PASS | FAIL
- reason: one short sentence
- ground_truth_sanity: SOUND | POSSIBLY_WRONG | WRONG
- ground_truth_note: short note

Rules:
- Compare only the candidate's final answer with the ground-truth answer in the context of the query.
- PASS if the candidate answer is factually and semantically equivalent to the ground truth; FAIL otherwise.
- Do not penalize equivalent mathematical formulations, intermediate representations, variable names, execution details, or formatting differences.
- For numeric values, treat -3.175 and -3.1750 as equivalent and allow minor rounding differences (< 0.01).
- If expected_rejection=true, PASS if the candidate clearly states the request is unanswerable or out of scope.
- If expected_rejection=false and candidate rejects, verdict must be FAIL.

Query:
{query_text}

Expected rejection:
{expected_rejection}

Ground truth answer:
{ground_truth_answer}

Candidate rejected:
{rejected}

Candidate answer:
{candidate_answer}
""",
                    ),
                ]
            )
            chain = prompt | client.llm | StrOutputParser()

        # Normalize answers for robust numeric comparison
        normalized_gt_answer = _normalize_answer(gt.reference_answer)
        normalized_candidate_answer = _normalize_answer(candidate_answer)

        assert client is not None
        parsed, llm_raw, parse_status, llm_attempts = _invoke_judge_with_retries(
            client=client,
            chain=chain,
            payload={
                "query_text": gt.query_text,
                "expected_rejection": str(gt.expected_rejection),
                "ground_truth_answer": normalized_gt_answer,
                "rejected": str(bool(row.get("rejected", False))),
                "candidate_answer": _clip(normalized_candidate_answer, max_answer_chars),
            },
        )

        verdict = str(parsed.get("verdict", "FAIL")).upper()
        if verdict not in {"PASS", "FAIL"}:
            verdict = "FAIL"

        override_reason = ""
        if verdict == "FAIL":
            override_reason = _deterministic_pass_override(
                gt_answer=normalized_gt_answer,
                candidate_answer=normalized_candidate_answer,
                expected_rejection=bool(gt.expected_rejection),
                candidate_rejected=bool(row.get("rejected", False)),
            )
            if override_reason:
                verdict = "PASS"
                parsed["reason"] = override_reason

        score = 1.0 if verdict == "PASS" else 0.0

        judged_rows.append(
            {
                "source_file": str(row.get("_source_file", "")),
                "baseline": baseline,
                "query_id": qid,
                "query_id_source": query_id_source,
                "query_text": gt.query_text,
                "expected_rejection": gt.expected_rejection,
                "gt_reference_answer": gt.reference_answer,
                "candidate_answer": str(row.get("answer", "")),
                "candidate_rejected": bool(row.get("rejected", False)),
                "candidate_executed": bool(row.get("executed", False)),
                "candidate_code": candidate_code,
                "llm_verdict": verdict,
                "llm_score": score,
                "llm_reason": str(parsed.get("reason", "")),
                "gt_sanity": str(parsed.get("ground_truth_sanity", "")),
                "gt_sanity_note": str(parsed.get("ground_truth_note", "")),
                "llm_parse_status": parse_status,
                "llm_attempts": llm_attempts,
                "llm_override_applied": bool(override_reason),
                "llm_raw": llm_raw,
            }
        )

    df = pd.DataFrame(judged_rows)
    if not df.empty:
        df = df.sort_values(["baseline", "query_id"]).reset_index(drop=True)
    return df


def summarize_judgments(judgments_df: pd.DataFrame) -> pd.DataFrame:
    if judgments_df.empty:
        return pd.DataFrame(
            columns=[
                "baseline",
                "pass_rate",
                "fail_rate",
                "count",
            ]
        )

    tmp = judgments_df.copy()
    tmp["is_pass"] = (tmp["llm_verdict"] == "PASS").astype(int)
    tmp["is_fail"] = (tmp["llm_verdict"] == "FAIL").astype(int)

    summary = (
        tmp.groupby("baseline")
        .agg(
            pass_rate=("is_pass", "mean"),
            fail_rate=("is_fail", "mean"),
            count=("query_id", "count"),
        )
        .reset_index()
        .sort_values("pass_rate", ascending=False)
    )
    return summary


def run_llm_ground_truth_judge(
    *,
    rows: list[dict[str, Any]],
    ground_truth_by_id: dict[int, GroundTruthEntry],
    output_dir: str,
    model_name: str,
    api_key: str,
    data_path: str | None = None,
    dataset: str = DATASET_WISDM,
    max_answer_chars: int = 1800,
    max_code_chars: int = 1400,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run full LLM judging workflow and write output artifacts."""
    os.makedirs(output_dir, exist_ok=True)

    sanity_df = build_ground_truth_sanity(
        ground_truth_by_id=ground_truth_by_id,
        data_path=data_path,
        dataset=dataset,
    )
    judgments_df = judge_rows_with_llm(
        rows=rows,
        ground_truth_by_id=ground_truth_by_id,
        dataset=dataset,
        model_name=model_name,
        api_key=api_key,
        sanity_df=sanity_df,
        max_answer_chars=max_answer_chars,
        max_code_chars=max_code_chars,
    )
    summary_df = summarize_judgments(judgments_df)

    judgments_path = os.path.join(output_dir, "llm_judgments.csv")
    summary_path = os.path.join(output_dir, "llm_judgments_summary.csv")
    sanity_path = os.path.join(output_dir, "ground_truth_sanity.csv")

    judgments_df.to_csv(judgments_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    sanity_df.to_csv(sanity_path, index=False)

    with open(os.path.join(output_dir, "llm_judgments.jsonl"), "w", encoding="utf-8") as fh:
        for row in judgments_df.to_dict(orient="records"):
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")

    return judgments_df, summary_df, sanity_df


def _collect_rows(results_files: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in results_files:
        rows.extend(_load_jsonl_rows(p))
    return rows


def _resolve_results_files(results: str | None, results_glob: str | None) -> list[str]:
    files: list[str] = []
    if results:
        for raw in results.split(","):
            p = raw.strip()
            if p:
                files.append(p)
    if results_glob:
        files.extend(glob.glob(results_glob))
    files = sorted({str(Path(p)) for p in files})
    return [p for p in files if Path(p).exists()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "LLM ground-truth judge for benchmark raw_results.jsonl files. "
            "Compares candidate answers against flashfusion/eval/ground_truth/ground_truth_wisdm.json."
        )
    )
    parser.add_argument(
        "--results",
        default=None,
        help="Comma-separated raw_results.jsonl files",
    )
    parser.add_argument(
        "--results-glob",
        default="flashfusion/eval_results/*_all/raw_results.jsonl",
        help="Glob pattern for raw_results.jsonl files",
    )
    parser.add_argument(
        "--ground-truth",
        default="flashfusion/eval/ground_truth/ground_truth_wisdm.json",
        help="Path to ground truth JSON",
    )
    parser.add_argument(
        "--data",
        default=None,
        help="Optional dataset path for deterministic sanity checks",
    )
    parser.add_argument(
        "--dataset",
        default=DATASET_WISDM,
        choices=list(SUPPORTED_DATASETS),
        help="Dataset profile for query lookup and deterministic sanity checks",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"LLM model for judging (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--output",
        default="flashfusion/eval_results/ground_truth_llm_judge",
        help="Output directory for judge artifacts",
    )
    parser.add_argument(
        "--max-answer-chars",
        type=int,
        default=1800,
        help="Max answer chars sent to judge model",
    )
    parser.add_argument(
        "--max-code-chars",
        type=int,
        default=1400,
        help="Max generated-code chars sent to judge model",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("Error: set OPENROUTER_API_KEY (or GROQ_API_KEY for transition compatibility)")

    ground_truth_by_id = load_ground_truth(args.ground_truth)
    files = _resolve_results_files(args.results, args.results_glob)
    if not files:
        raise SystemExit("No results files found. Check --results or --results-glob")

    rows = _collect_rows(files)
    judgments_df, summary_df, sanity_df = run_llm_ground_truth_judge(
        rows=rows,
        ground_truth_by_id=ground_truth_by_id,
        output_dir=args.output,
        model_name=args.model,
        api_key=api_key,
        data_path=args.data,
        dataset=args.dataset,
        max_answer_chars=args.max_answer_chars,
        max_code_chars=args.max_code_chars,
    )

    print(f"Judged {len(judgments_df)} rows from {len(files)} file(s)")
    if not summary_df.empty:
        print("\nLLM Judge Summary:")
        print(summary_df.to_string(index=False))

    if not sanity_df.empty:
        flagged = sanity_df[sanity_df["sanity_flag"] != "ok"]
        print(
            f"\nGround-truth sanity: {len(flagged)} flagged / {len(sanity_df)} total "
            f"(see {os.path.join(args.output, 'ground_truth_sanity.csv')})"
        )


if __name__ == "__main__":
    main()
