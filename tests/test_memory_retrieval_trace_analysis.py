import json
import sqlite3
from pathlib import Path

from chimera_memory.memory import (
    index_file,
    init_memory_tables,
    memory_audit_query,
    memory_search,
    record_memory_recall_trace,
)
from chimera_memory.memory_retrieval_trace_analysis import (
    StaticMemoryRetrievalTraceAnalysisClient,
    memory_retrieval_trace_analyze,
)


def test_retrieval_trace_analysis_sends_safe_trace_summary(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    target = tmp_path / "charles-deploy.md"
    target.write_text(
        "\n".join(
            [
                "---",
                "type: feedback",
                "importance: 9",
                "about: Charles deployment preferences",
                "---",
                "Always deploy for Charles after building and smoke testing.",
            ]
        ),
        encoding="utf-8",
    )
    assert index_file(conn, "asa", "memory/charles-deploy.md", target)
    assert memory_search(conn, "deploy Charles", persona="asa", limit=3)

    client = StaticMemoryRetrievalTraceAnalysisClient(
        [
            {
                "category": "query_too_vague",
                "secondary_categories": ["wrong_tool_route"],
                "severity": "medium",
                "confidence": 0.88,
                "recommendation": "Try an intent-shaped query before changing ranking.",
                "evidence": ["The trace used a person-shaped query with procedural target intent."],
                "query_expansions": ["Charles deployment preferences", "deploy for Charles rules"],
                "suggested_tool_route": "memory_recall",
            }
        ]
    )

    result = memory_retrieval_trace_analyze(
        conn,
        client=client,
        env={"CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "dry_run"},
        persona="asa",
        limit=1,
    )

    assert result["analysis_count"] == 1
    assert result["category_counts"] == {"query_too_vague": 1}
    assert result["analyses"][0]["suggested_tool_route"] == "memory_recall"
    assert result["analyses"][0]["requires_verification"] is True
    assert "same-persona" in result["analyses"][0]["verification_guidance"]
    assert client.invocations[0]["raw_json"] is True
    assert "Raw memory bodies are intentionally absent" in client.invocations[0]["system_prompt"]
    assert "filename does not mirror the query" in client.invocations[0]["system_prompt"]
    trace = client.invocations[0]["request"]["trace"]
    assert trace["query_text"] == "deploy Charles"
    assert trace["items"][0]["relative_path"] == "memory/charles-deploy.md"
    assert "body" not in trace["items"][0]
    assert "Always deploy" not in str(trace)

    events = memory_audit_query(conn, event_type="memory_retrieval_trace_analysis", persona="asa")
    assert len(events) == 1
    assert events[0]["payload"]["category_counts"] == {"query_too_vague": 1}


def test_retrieval_trace_analysis_omits_context_prompt_and_sanitizes_trace_payload(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    auth_ref = "C:/Users/test/.codex/auth.json"
    fake_pat = "ghp_" + "B" * 40
    local_file = tmp_path / "private" / "context.md"
    local_file.parent.mkdir()
    record_memory_recall_trace(
        conn,
        tool_name="memory_context_pack",
        query_text=f"context analyzer prompt must not leak {auth_ref} {fake_pat}",
        persona=None,
        requested_limit=1,
        results=[
            {
                "id": 1,
                "path": str(local_file),
                "relative_path": "memory/context.md",
                "persona": "global",
                "type": "procedural",
                "about": f"Analyzer metadata mentions {auth_ref} and {fake_pat}",
                "metadata": {
                    "raw_prompt": "analysis metadata prompt must not leak",
                    "source_path": str(local_file),
                },
            }
        ],
        request_payload={
            "plan": {
                "query_text": "analysis plan query must not leak",
                "query_terms": [auth_ref, fake_pat],
                "shift_score": 1.0,
            },
            "raw_prompt": "analysis request prompt must not leak",
        },
        response_policy={
            "raw_prompt": "analysis response prompt must not leak",
            "provider_stderr": f"provider stderr {auth_ref}",
        },
    )
    client = StaticMemoryRetrievalTraceAnalysisClient(
        [
            {
                "category": "ok",
                "secondary_categories": [],
                "severity": "info",
                "confidence": 0.8,
                "recommendation": "No fix needed.",
                "evidence": ["Trace is sanitized."],
                "query_expansions": [],
                "suggested_tool_route": "memory_recall",
            }
        ]
    )

    result = memory_retrieval_trace_analyze(
        conn,
        client=client,
        env={"CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "dry_run"},
        tool_name="memory_context_pack",
        limit=1,
    )
    trace = client.invocations[0]["request"]["trace"]
    serialized = json.dumps(client.invocations[0], sort_keys=True).replace("\\\\", "/").replace("\\", "/")

    assert result["analysis_count"] == 1
    assert trace["query_text"].startswith("[omitted:")
    assert "context analyzer prompt must not leak" not in serialized
    assert "analysis plan query must not leak" not in serialized
    assert "analysis request prompt must not leak" not in serialized
    assert "analysis response prompt must not leak" not in serialized
    assert "analysis metadata prompt must not leak" not in serialized
    assert "ghp_" not in serialized
    assert ".codex/auth.json" not in serialized
    assert str(tmp_path).replace("\\", "/") not in serialized
    assert trace["request_payload"]["plan"]["query_text"]["redacted"] is True
    assert trace["response_policy"]["raw_prompt"]["redacted"] is True
    assert trace["response_policy"]["provider_stderr"]["redacted"] is True
    assert trace["items"][0]["metadata"]["about"].startswith("Analyzer metadata mentions local-path:auth.json")


def test_retrieval_trace_analysis_normalizes_untrusted_model_output() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    conn.execute(
        """
        INSERT INTO memory_recall_traces (
            trace_id, tool_name, persona, query_text, requested_limit,
            result_count, returned_count
        ) VALUES ('trace-1', 'memory_recall', 'asa', 'what should I remember', 5, 0, 0)
        """
    )
    conn.commit()
    client = StaticMemoryRetrievalTraceAnalysisClient(
        [
            {
                "category": "invented_category",
                "secondary_categories": ["diagnostics_noise_pollution", "fake"],
                "severity": "catastrophic",
                "confidence": 9,
                "recommendation": "x" * 1000,
                "evidence": ["e" * 300],
                "query_expansions": ["q1", "q2", "q3", "q4", "q5", "q6"],
                "suggested_tool_route": "magic",
            }
        ]
    )

    result = memory_retrieval_trace_analyze(
        conn,
        client=client,
        env={"CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "dry_run"},
        trace_id="trace-1",
    )

    analysis = result["analyses"][0]
    assert analysis["category"] == "unknown"
    assert analysis["secondary_categories"] == ["diagnostics_noise_pollution"]
    assert analysis["severity"] == "medium"
    assert analysis["confidence"] == 1.0
    assert len(analysis["recommendation"]) == 700
    assert len(analysis["evidence"][0]) == 240
    assert len(analysis["query_expansions"]) == 5
    assert analysis["suggested_tool_route"] == "unknown"
    assert analysis["requires_verification"] is True


def test_retrieval_trace_analysis_marks_ok_as_verified_enough() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    conn.execute(
        """
        INSERT INTO memory_recall_traces (
            trace_id, tool_name, persona, query_text, requested_limit,
            result_count, returned_count
        ) VALUES ('trace-ok', 'memory_recall', 'asa', 'known thing', 5, 1, 1)
        """
    )
    conn.commit()
    client = StaticMemoryRetrievalTraceAnalysisClient(
        [
            {
                "category": "ok",
                "secondary_categories": [],
                "severity": "low",
                "confidence": 0.9,
                "recommendation": "No fix needed.",
                "evidence": ["Top-ranked metadata matches the query."],
                "query_expansions": [],
                "suggested_tool_route": "memory_recall",
            }
        ]
    )

    result = memory_retrieval_trace_analyze(
        conn,
        client=client,
        env={"CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "dry_run"},
        trace_id="trace-ok",
    )

    analysis = result["analyses"][0]
    assert analysis["category"] == "ok"
    assert analysis["requires_verification"] is False
    assert analysis["verification_guidance"] == ""
