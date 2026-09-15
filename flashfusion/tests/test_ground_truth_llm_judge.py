from __future__ import annotations

from flashfusion.eval.ground_truth import GroundTruthEntry
from flashfusion.eval.ground_truth_llm_judge import (
    _resolve_candidate_code,
    judge_rows_with_llm,
)
from flashfusion.eval.queries import DATASET_WISDM, get_queries


def test_resolve_candidate_code_prefers_final_code():
    row = {
        "final_code": "result = 1",
        "execution_attempts": [{"code": "result = 2"}],
        "trace": "Action Input: result = 3",
    }
    assert _resolve_candidate_code(row) == "result = 1"


def test_resolve_candidate_code_prefers_typed_execution_certificate():
    row = {
        "execution_path": "typed_operator_cache",
        "typed_execution_certificate": {
            "certificate_status": "ok",
            "typed_plan_sha256": "abc123",
            "operators_used": ["FILTER_COMPARE", "AGGREGATE_COLUMN"],
            "rows_scanned": 10,
            "rows_after_filter": 2,
            "latency_ms": 5.0,
            "result": 42,
        },
        "final_code": "result = broken()",
    }
    resolved = _resolve_candidate_code(row)
    assert resolved == "result = broken()"


def test_resolve_candidate_code_falls_back_to_last_attempt_code():
    row = {
        "final_code": "",
        "execution_attempts": [
            {"code": "df = df[df['x'] > 0]"},
            {"code": "result = len(df)"},
        ],
    }
    assert _resolve_candidate_code(row) == "df = df[df['x'] > 0]\nresult = len(df)"


def test_resolve_candidate_code_uses_typed_execution_certificate_when_code_missing():
    row = {
        "execution_path": "typed_operator_cache",
        "typed_execution_certificate": {
            "certificate_status": "ok",
            "typed_plan_sha256": "abc123",
            "operators_used": ["FILTER_COMPARE", "COUNT_ROWS"],
            "rows_scanned": 10,
            "rows_after_filter": 2,
            "latency_ms": 5.0,
            "result": 2,
            "code": "df = df[df['x'] > 0]\nresult = len(df)",
        },
        "final_code": "",
        "execution_attempts": [],
    }
    resolved = _resolve_candidate_code(row)
    assert resolved.startswith("TYPED_EXECUTION_CERTIFICATE")
    assert "abc123" in resolved


def test_resolve_candidate_code_falls_back_to_trace_action_input():
    row = {
        "final_code": "",
        "execution_attempts": [],
        "trace": "Thought: x\nAction Input: result = 99\nObservation: ok",
    }
    assert _resolve_candidate_code(row) == "result = 99"


def test_resolve_candidate_code_returns_empty_when_unavailable():
    row = {"final_code": "", "execution_attempts": [], "trace": ""}
    assert _resolve_candidate_code(row) == ""


def test_judge_rows_with_llm_accepts_expected_rejection(monkeypatch):
    queries = get_queries(DATASET_WISDM)
    q9 = next(q for q in queries if q["id"] == 9)

    ground_truth_by_id = {
        9: GroundTruthEntry(
            query_id=9,
            query_text=q9["text"],
            reference_answer="Reject: out of scope.",
            expected_rejection=True,
        )
    }

    rows = [
        {
            "baseline": "REACT_ONLY",
            "query": q9["text"],
            "answer": "This is out of scope for the dataset, so I cannot answer.",
            "executed": True,
            "rejected": False,
            "final_code": "",
            "execution_attempts": [],
            "trace": "",
        }
    ]

    class _DummyPrompt:
        def __or__(self, other):
            return self

    class _DummyLLM:
        def __ror__(self, other):
            return self

        def __or__(self, other):
            return self

    class _DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            self.llm = _DummyLLM()

        def invoke_chain(self, chain, inputs, stage: str) -> str:
            return (
                '{"verdict":"PASS","reason":"Rejects as out of scope.",' 
                '"ground_truth_sanity":"SOUND","ground_truth_note":""}'
            )

    monkeypatch.setattr(
        "flashfusion.eval.ground_truth_llm_judge.ChatPromptTemplate.from_messages",
        lambda *args, **kwargs: _DummyPrompt(),
    )
    monkeypatch.setattr(
        "flashfusion.eval.ground_truth_llm_judge.LLMClient",
        _DummyClient,
    )

    judged = judge_rows_with_llm(
        rows=rows,
        ground_truth_by_id=ground_truth_by_id,
        dataset=DATASET_WISDM,
        model_name="test-model",
        api_key="test-key",
    )

    assert len(judged) == 1
    assert judged.loc[0, "llm_verdict"] == "PASS"
    assert judged.loc[0, "llm_score"] == 1.0


def test_judge_rows_with_llm_prefers_explicit_id_over_rewritten_text(monkeypatch):
    ground_truth_by_id = {
        2: GroundTruthEntry(
            query_id=2,
            query_text="Canonical v1 wording",
            reference_answer="42",
            expected_rejection=False,
        )
    }
    rows = [
        {
            "baseline": "FLASH_FUSION_CACHE",
            "query_id": 2,
            "query": "Rewritten wording that is absent from every catalog",
            "answer": "42",
            "executed": True,
            "rejected": False,
        }
    ]

    class _DummyPrompt:
        def __or__(self, other):
            return self

    class _DummyLLM:
        def __ror__(self, other):
            return self

        def __or__(self, other):
            return self

    class _DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            self.llm = _DummyLLM()

        def invoke_chain(self, chain, inputs, stage: str) -> str:
            assert inputs["query_text"] == "Canonical v1 wording"
            return (
                '{"verdict":"PASS","reason":"Same answer.",'
                '"ground_truth_sanity":"SOUND","ground_truth_note":""}'
            )

    monkeypatch.setattr(
        "flashfusion.eval.ground_truth_llm_judge.ChatPromptTemplate.from_messages",
        lambda *args, **kwargs: _DummyPrompt(),
    )
    monkeypatch.setattr(
        "flashfusion.eval.ground_truth_llm_judge.LLMClient",
        _DummyClient,
    )

    judged = judge_rows_with_llm(
        rows=rows,
        ground_truth_by_id=ground_truth_by_id,
        dataset=DATASET_WISDM,
        model_name="test-model",
        api_key="test-key",
    )

    assert len(judged) == 1
    assert int(judged.loc[0, "query_id"]) == 2
    assert judged.loc[0, "query_id_source"] == "explicit"
    assert judged.loc[0, "llm_score"] == 1.0


def test_judge_rows_with_llm_excludes_serialized_code_from_judgment(monkeypatch):
    ground_truth_by_id = {
        19: GroundTruthEntry(
            query_id=19,
            query_text="Return the correlation between bin index and rate.",
            reference_answer="The correlation is -0.460485689017.",
            expected_rejection=False,
        )
    }
    rows = [
        {
            "baseline": "FLASH_FUSION",
            "query_id": 19,
            "query": "Return the correlation between bin index and rate.",
            "answer": "The result is -0.46048568901662706",
            "executed": True,
            "rejected": False,
            "final_code": "df['annotated_rate'] = df['annotated_count'] / df['total_count']",
        }
    ]

    class _DummyPrompt:
        def __or__(self, other):
            return self

    class _DummyLLM:
        def __ror__(self, other):
            return self

        def __or__(self, other):
            return self

    class _DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            self.llm = _DummyLLM()

        def invoke_chain(self, chain, inputs, stage: str) -> str:
            assert stage == "gt_llm_judge"
            assert set(inputs) == {
                "query_text",
                "expected_rejection",
                "ground_truth_answer",
                "rejected",
                "candidate_answer",
            }
            assert "candidate_code" not in inputs
            return (
                '{"verdict":"PASS","reason":"Numeric answer matches ground truth.",'
                '"ground_truth_sanity":"SOUND","ground_truth_note":""}'
            )

    monkeypatch.setattr(
        "flashfusion.eval.ground_truth_llm_judge.ChatPromptTemplate.from_messages",
        lambda *args, **kwargs: _DummyPrompt(),
    )
    monkeypatch.setattr(
        "flashfusion.eval.ground_truth_llm_judge.LLMClient",
        _DummyClient,
    )

    judged = judge_rows_with_llm(
        rows=rows,
        ground_truth_by_id=ground_truth_by_id,
        dataset=DATASET_WISDM,
        model_name="test-model",
        api_key="test-key",
    )

    assert judged.loc[0, "llm_verdict"] == "PASS"
    assert judged.loc[0, "candidate_code"] == rows[0]["final_code"]
