"""eval/queries_v2.py — lightly reworded benchmark queries (version 2).

This module preserves query IDs, complexity labels, operations, and stress notes
from eval/queries.py, and only rewrites the `text` field with small paraphrases.
"""

from __future__ import annotations

import copy
import re

from flashfusion.eval.queries import (
    BUS_QUERIES,
    DATASET_BUS,
    DATASET_MIT_ECG,
    DATASET_WISDM,
    MIT_ECG_QUERIES,
    SUPPORTED_DATASETS,
    WISDM_QUERIES,
)


def _reword_v2(text: str) -> str:
    out = text.strip()
    replacements: tuple[tuple[str, str], ...] = (
        (r"\bWhat is\b", "Could you report"),
        (r"\bHow many\b", "What number of"),
        (r"\bCalculate\b", "Compute"),
        (r"\bIdentify\b", "Determine"),
        (r"\bList all\b", "List every"),
        (r"\bSort all\b", "Order all"),
        (r"\bPredict whether\b", "Estimate whether"),
        (r"\bPredict the\b", "Estimate the"),
        (r"\bBased on\b", "Using"),
        (r"\brecorded\b", "observed"),
    )
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    return out


def _reword_extra_hard_v2(text: str) -> str:
    """Paraphrase only the compositional ablation prompts without changing constraints."""
    out = text.strip()
    replacements: tuple[tuple[str, str], ...] = (
        (r"\bFor each\b", "For every"),
        (r"\bCompute\b", "Calculate"),
        (r"\bFilter\b", "Restrict"),
        (r"\bSplit\b", "Partition"),
    )
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    return out


def _rewrite(queries: list[dict]) -> list[dict]:
    rewritten: list[dict] = []
    for q in queries:
        nq = copy.deepcopy(q)
        source = str(q["text"])
        nq["text"] = (
            _reword_extra_hard_v2(source)
            if int(q["id"]) >= 17
            else _reword_v2(source)
        )
        rewritten.append(nq)
    return rewritten


WISDM_QUERIES: list[dict] = _rewrite(WISDM_QUERIES)
MIT_ECG_QUERIES: list[dict] = _rewrite(MIT_ECG_QUERIES)
BUS_QUERIES: list[dict] = _rewrite(BUS_QUERIES)


def get_queries(dataset: str) -> list[dict]:
    if dataset == DATASET_WISDM:
        return WISDM_QUERIES
    if dataset == DATASET_MIT_ECG:
        return MIT_ECG_QUERIES
    if dataset == DATASET_BUS:
        return BUS_QUERIES
    raise ValueError(f"Unsupported dataset {dataset!r}. Supported: {SUPPORTED_DATASETS}")
