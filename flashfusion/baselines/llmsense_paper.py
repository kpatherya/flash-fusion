"""LLMSENSE_PAPER baseline.

Implements a two-tier narration pipeline:
- Stage N: narrate short traces directly
- Stage S: summarize long traces in chunks
- Stage R: reason over narrative text only

This baseline never executes pandas code.
"""

from __future__ import annotations

import io
import random

import pandas as pd
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from flashfusion.config import (
    LLMSENSE_HISTORY_HOURS,
    LLMSENSE_MAX_ROWS_DIRECT,
    LLMSENSE_MAX_SUMMARIZE_CHUNKS,
    LLMSENSE_NARRATIVE_MAX_CHARS,
    LLMSENSE_ROWS_PER_CHUNK_BUS,
    LLMSENSE_ROWS_PER_CHUNK_ECG,
    LLMSENSE_ROWS_PER_CHUNK_WISDM,
    LLMSENSE_SENSOR_HZ,
    LLMSENSE_SUMMARY_WINDOW_MIN,
)
from flashfusion.pipeline.runner import LLMClient, RunResult
from flashfusion.prompts.llmsense_prompts import (
    NARRATION_OBJECTIVE,
    NARRATION_PROMPT_TEMPLATE,
    REASONING_PROMPT_TEMPLATE,
    SUMMARIZATION_PROMPT_TEMPLATE,
    DATASET_BUS,
    DATASET_MIT_ECG,
    DATASET_WISDM,
    build_dataset_context,
    get_narration_requirements,
    get_reasoning_dataset_label,
)


# Empirically, WISDM CSV consumes substantially more tokens per row than the
# fixed row caps assume. Keep table inputs below roughly 80k tokens even for
# token-dense rows, leaving ample context and output room on 128k models.
_MAX_TABLE_CHARS = 160_000


def _df_to_table_string(df: pd.DataFrame, max_rows: int = 200) -> str:
    """Render a compact CSV prefix within a conservative prompt-size budget."""
    sample = df.head(max_rows)
    buf = io.StringIO()
    sample.to_csv(buf, index=False, float_format="%.4f")
    table = buf.getvalue()
    if len(table) <= _MAX_TABLE_CHARS:
        return table

    prefix = table[:_MAX_TABLE_CHARS]
    last_newline = prefix.rfind("\n")
    return prefix[: last_newline + 1] if last_newline >= 0 else prefix


def _infer_dataset_name(df: pd.DataFrame) -> str:
    columns = set(df.columns)
    if {"x", "y", "z", "activity_label"}.issubset(columns):
        return DATASET_WISDM
    if {"MLII", "V1", "record_id", "time_s"}.issubset(columns):
        return DATASET_MIT_ECG
    if {"latitude", "longitude", "accel_mean", "accel_variance"}.issubset(columns):
        return DATASET_BUS
    return DATASET_WISDM


def _build_context(dataset: str, hz: float = LLMSENSE_SENSOR_HZ) -> str:
    return build_dataset_context(dataset, hz)


def _needs_summarization(df: pd.DataFrame) -> bool:
    return len(df) > LLMSENSE_MAX_ROWS_DIRECT


def _max_rows_for_dataset(dataset: str) -> int:
    """Rows to pass per LLM call, targeting 95% of the 128k context window."""
    if dataset == DATASET_MIT_ECG:
        return LLMSENSE_ROWS_PER_CHUNK_ECG
    if dataset == DATASET_BUS:
        return LLMSENSE_ROWS_PER_CHUNK_BUS
    return LLMSENSE_ROWS_PER_CHUNK_WISDM


def _subject_chunks(sub_df: pd.DataFrame) -> list[pd.DataFrame]:
    """Chunk per subject using configured summary window and history limit."""
    rows_per_window = max(1, int(LLMSENSE_SENSOR_HZ * 60 * LLMSENSE_SUMMARY_WINDOW_MIN))
    max_rows = max(rows_per_window, int(LLMSENSE_SENSOR_HZ * 3600 * LLMSENSE_HISTORY_HOURS))
    limited = sub_df.head(max_rows)
    return [limited.iloc[i : i + rows_per_window] for i in range(0, len(limited), rows_per_window)]


def _stage_narrate(df: pd.DataFrame, client: LLMClient, dataset: str) -> tuple[str, int]:
    max_rows = _max_rows_for_dataset(dataset)
    rows_seen = min(len(df), max_rows)
    context = _build_context(dataset)
    requirements = get_narration_requirements(dataset)
    prompt_text = NARRATION_PROMPT_TEMPLATE.format(
        objective=NARRATION_OBJECTIVE,
        context=context,
        narration_requirements=requirements,
        data_table=_df_to_table_string(df, max_rows=max_rows),
    )
    chain = ChatPromptTemplate.from_template("{prompt}") | client.llm | StrOutputParser()
    return client.invoke_chain(chain, {"prompt": prompt_text}, stage="N_narrate"), rows_seen


def _stage_summarize(df: pd.DataFrame, client: LLMClient, dataset: str) -> tuple[str, int]:
    max_rows = _max_rows_for_dataset(dataset)
    context = _build_context(dataset)
    summaries: list[str] = []
    total_rows_seen = 0

    if "subject_id" in df.columns:
        group_key: str | None = "subject_id"
    elif "record_id" in df.columns:
        group_key = "record_id"
    else:
        group_key = None
    grouped = df.groupby(group_key, sort=True) if group_key else [("all", df)]

    sort_col = "timestamp" if "timestamp" in df.columns else ("time_s" if "time_s" in df.columns else None)

    # Enumerate every (group_id, chunk_idx, total_chunks_in_group, chunk_df) across all groups.
    # DataFrame slices are views, so this is memory-efficient even for large datasets.
    all_chunks: list[tuple[object, int, int, pd.DataFrame]] = []
    for group_id, sub_df in grouped:
        ordered = sub_df.sort_values(sort_col) if sort_col else sub_df
        chunks = _subject_chunks(ordered)
        for idx, chunk in enumerate(chunks, start=1):
            all_chunks.append((group_id, idx, len(chunks), chunk))

    # Randomly sample up to the cap, then re-sort to preserve temporal order in the narrative.
    sampled = random.sample(all_chunks, min(LLMSENSE_MAX_SUMMARIZE_CHUNKS, len(all_chunks)))
    sampled.sort(key=lambda t: (str(t[0]), t[1]))

    for group_id, idx, total_chunks, chunk in sampled:
        total_rows_seen += min(len(chunk), max_rows)
        duration_desc = (
            f"group {group_id}, chunk {idx}/{total_chunks}, "
            f"window={LLMSENSE_SUMMARY_WINDOW_MIN}min, history={LLMSENSE_HISTORY_HOURS}h"
        )
        prompt_text = SUMMARIZATION_PROMPT_TEMPLATE.format(
            objective=NARRATION_OBJECTIVE,
            context=context,
            duration_desc=duration_desc,
            data_table=_df_to_table_string(chunk, max_rows=max_rows),
        )
        chain = ChatPromptTemplate.from_template("{prompt}") | client.llm | StrOutputParser()
        summary = client.invoke_chain(
            chain,
            {"prompt": prompt_text},
            stage=f"S_summarize_group{group_id}_chunk{idx}",
        )
        summaries.append(f"[Group {group_id} - chunk {idx}] {summary}")

    return "\n\n".join(summaries), total_rows_seen


def _stage_reason(
    narrative: str,
    query: str,
    context: str,
    dataset_label: str,
    client: LLMClient,
) -> str:
    prompt_text = REASONING_PROMPT_TEMPLATE.format(
        dataset_label=dataset_label,
        context=context,
        narrative=narrative,
        query=query,
    )
    chain = ChatPromptTemplate.from_template("{prompt}") | client.llm | StrOutputParser()
    return client.invoke_chain(chain, {"prompt": prompt_text}, stage="R_reason")


def run_llmsense_paper(
    query: str,
    df: pd.DataFrame,
    client: LLMClient,
    r: RunResult,
) -> RunResult:
    """Execute the LLMSENSE_PAPER baseline."""
    dataset = _infer_dataset_name(df)
    context = _build_context(dataset)
    dataset_label = get_reasoning_dataset_label(dataset)

    rows_total = len(df)
    if _needs_summarization(df):
        narrative, rows_seen = _stage_summarize(df, client, dataset)
        r.stages_run.append("S_summarize")
    else:
        narrative, rows_seen = _stage_narrate(df, client, dataset)
        r.stages_run.append("N_narrate")

    pct_seen = 100.0 * rows_seen / rows_total if rows_total > 0 else 0.0
    print(
        f"[LLMSENSE] {dataset.upper()} rows_seen={rows_seen:,}/{rows_total:,} ({pct_seen:.4f}%)",
        flush=True,
    )

    if len(narrative) > LLMSENSE_NARRATIVE_MAX_CHARS:
        narrative = narrative[:LLMSENSE_NARRATIVE_MAX_CHARS] + "\n[... narrative truncated to fit context window ...]"

    r.answer = _stage_reason(narrative, query, context, dataset_label, client)
    r.stages_run.append("R_reason")
    r.trace = narrative
    r.executed = False
    r.rejected = False
    r.judge_verdict = {}
    return r
