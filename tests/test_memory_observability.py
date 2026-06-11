import json
import sqlite3
from pathlib import Path

from chimera_memory.memory import (
    index_file,
    init_memory_tables,
    memory_audit_query,
    memory_query,
    memory_recall_trace_query,
    memory_search,
    record_memory_audit_event,
    record_memory_recall_trace,
)
from chimera_memory.memory_context_pack import memory_context_pack
from chimera_memory.memory_live_retrieval import memory_live_retrieval_check


def test_memory_search_records_recall_trace_and_audit_items(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    memory_file = tmp_path / "trace.md"
    memory_file.write_text(
        "---\ntype: procedural\nimportance: 8\nabout: trace testing\n---\nalpha trace marker\n",
        encoding="utf-8",
    )
    assert index_file(conn, "asa", "trace.md", memory_file)

    results = memory_search(conn, "alpha trace", persona="asa", limit=5)
    assert len(results) == 1
    assert results[0]["id"]

    traces = memory_recall_trace_query(conn, persona="asa", tool_name="memory_search", include_items=True)
    assert len(traces) == 1
    assert traces[0]["query_text"] == "alpha trace"
    assert traces[0]["requested_limit"] == 5
    assert traces[0]["returned_count"] == 1
    assert traces[0]["items"][0]["relative_path"] == "trace.md"

    events = memory_audit_query(conn, persona="asa", limit=10)
    event_types = {event["event_type"] for event in events}
    assert "recall_requested" in event_types
    assert "memory_returned" in event_types


def test_memory_search_trace_result_count_preserves_total_matches(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    for index in range(3):
        memory_file = tmp_path / f"trace-{index}.md"
        memory_file.write_text(
            "---\ntype: procedural\nimportance: 8\n---\nalpha trace marker shared\n",
            encoding="utf-8",
        )
        assert index_file(conn, "shared", f"trace-{index}.md", memory_file)

    results = memory_search(conn, "alpha trace", scope="global", limit=1)
    assert len(results) == 1

    traces = memory_recall_trace_query(conn, tool_name="memory_search")
    assert traces[0]["requested_limit"] == 1
    assert traces[0]["result_count"] == 3
    assert traces[0]["returned_count"] == 1
    events = memory_audit_query(conn, event_type="recall_requested")
    assert events[0]["payload"]["result_count"] == 3
    assert events[0]["payload"]["returned_count"] == 1


def test_memory_search_filters_weak_global_broad_term_noise(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    relevant = tmp_path / "relevant.md"
    relevant.write_text(
        "---\ntype: procedural\nimportance: 8\n---\n"
        "codex global live smoke marker 12345 proves exact search quality filtering.\n",
        encoding="utf-8",
    )
    weak = tmp_path / "weak.md"
    weak.write_text(
        "---\ntype: procedural\nimportance: 8\n---\n"
        "A generic global note says someone lives near a workbench.\n",
        encoding="utf-8",
    )
    assert index_file(conn, "global", "memory/relevant.md", relevant)
    assert index_file(conn, "shared", "roster/weak.md", weak)

    results = memory_search(conn, "codex global live smoke marker 12345", scope="global", limit=5)

    assert [row["relative_path"] for row in results] == ["memory/relevant.md"]
    traces = memory_recall_trace_query(conn, tool_name="memory_search")
    assert traces[0]["result_count"] == 2
    assert traces[0]["returned_count"] == 1
    assert traces[0]["response_policy"]["quality_gate"]["filtered_count"] == 1


def test_memory_search_returns_miss_when_only_weak_global_terms_match(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    weak = tmp_path / "weak.md"
    weak.write_text(
        "---\ntype: procedural\nimportance: 8\n---\n"
        "A generic global note says someone lives near a workbench.\n",
        encoding="utf-8",
    )
    assert index_file(conn, "shared", "roster/weak.md", weak)

    results = memory_search(conn, "codex global live smoke marker 12345", scope="global", limit=5)

    assert results == []
    traces = memory_recall_trace_query(conn, tool_name="memory_search")
    assert traces[0]["result_count"] == 1
    assert traces[0]["returned_count"] == 0
    assert traces[0]["response_policy"]["quality_gate"]["filtered_count"] == 1


def test_memory_search_trace_hides_source_uri(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    memory_file = tmp_path / "source.md"
    memory_file.write_text(
        "---\n"
        "type: procedural\n"
        "importance: 8\n"
        "source_refs:\n"
        "  - kind: gmail\n"
        "    uri: sensitive-message-id-123\n"
        "---\n"
        "alpha source marker\n",
        encoding="utf-8",
    )
    assert index_file(conn, "shared", "source.md", memory_file)

    results = memory_search(
        conn,
        "alpha source",
        scope="global",
        source_kind="gmail",
        source_uri="sensitive-message-id-123",
        limit=5,
    )

    assert len(results) == 1
    traces = memory_recall_trace_query(conn, tool_name="memory_search")
    assert traces[0]["request_payload"]["source_uri_supplied"] is True
    assert "sensitive-message-id-123" not in str(traces[0])


def test_recall_trace_items_return_path_safe_payloads(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    memory_file = tmp_path / "trace-root" / "trace-local.md"
    memory_file.parent.mkdir()
    memory_file.write_text(
        "---\ntype: procedural\nimportance: 8\nmemory_scope: global\n---\n"
        "Path safe trace marker should appear in search live retrieval and context pack.",
        encoding="utf-8",
    )
    assert index_file(conn, "global", "trace/path-safe.md", memory_file)

    assert memory_search(conn, "path safe trace marker", scope="global", limit=5)
    live = memory_live_retrieval_check(
        conn,
        current_context="Need path safe trace marker live retrieval now.",
        previous_context="Earlier work was unrelated.",
        scope="global",
        force=True,
        limit=5,
    )
    context = memory_context_pack(
        conn,
        current_context="Need path safe trace marker context pack now.",
        previous_context="Earlier work was unrelated.",
        scope="global",
        force=True,
        limit=5,
    )

    assert live["results"]
    assert context["cards"]
    traces = memory_recall_trace_query(conn, include_items=True, limit=10)
    trace_tools = {trace["tool_name"] for trace in traces}
    assert {"memory_search", "memory_live_retrieval", "memory_context_pack"} <= trace_tools
    payload = json.dumps(traces, sort_keys=True).replace("\\", "/")

    assert str(tmp_path).replace("\\", "/") not in payload
    assert str(memory_file).replace("\\", "/") not in payload
    for trace in traces:
        for item in trace.get("items", []):
            assert item["relative_path"] == "trace/path-safe.md"
            assert item["path"] == "trace-local.md"
            assert item["path_fingerprint"]


def test_recall_trace_query_sanitizes_context_prompt_trace_payloads(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    auth_ref = "C:/Users/test/.codex/auth.json"
    fake_pat = "ghp_" + "A" * 40
    local_file = tmp_path / "private" / "secret-memory.md"
    local_file.parent.mkdir()
    trace_id = record_memory_recall_trace(
        conn,
        tool_name="memory_context_pack",
        query_text=f"context prompt text must not leak {auth_ref} {fake_pat}",
        persona=None,
        requested_limit=1,
        results=[
            {
                "id": 1,
                "path": str(local_file),
                "relative_path": "memory/secret-memory.md",
                "persona": "global",
                "type": "procedural",
                "about": f"Trace about mentions {auth_ref} and {fake_pat}",
                "snippet": f"Snippet mentions {auth_ref} and {fake_pat}",
                "metadata": {
                    "raw_prompt": "metadata prompt should not leak",
                    "source_path": str(local_file),
                    "note": f"Metadata note mentions {auth_ref} and {fake_pat}",
                },
            }
        ],
        request_payload={
            "plan": {
                "query_text": "plan query text must not leak",
                "query_terms": [auth_ref, fake_pat],
                "shift_score": 1.0,
            },
            "raw_prompt": "request prompt should not leak",
            "source_path": str(local_file),
        },
        response_policy={
            "provider_stderr": f"stderr should not leak {auth_ref}",
            "quality_gate": {"reason": f"filtered near {auth_ref} {fake_pat}"},
        },
    )

    traces = memory_recall_trace_query(conn, include_items=True)
    serialized = json.dumps(traces, sort_keys=True).replace("\\\\", "/").replace("\\", "/")

    assert traces[0]["trace_id"] == trace_id
    assert traces[0]["query_text"].startswith("[omitted:")
    assert "context prompt text must not leak" not in serialized
    assert "plan query text must not leak" not in serialized
    assert "request prompt should not leak" not in serialized
    assert "metadata prompt should not leak" not in serialized
    assert "provider_stderr" in serialized
    assert "ghp_" not in serialized
    assert ".codex/auth.json" not in serialized
    assert str(tmp_path).replace("\\", "/") not in serialized
    assert traces[0]["request_payload"]["raw_prompt"]["redacted"] is True
    assert traces[0]["request_payload"]["plan"]["query_text"]["redacted"] is True
    assert traces[0]["response_policy"]["provider_stderr"]["redacted"] is True
    assert traces[0]["items"][0]["metadata"]["raw_prompt"]["redacted"] is True
    assert traces[0]["items"][0]["metadata"]["source_path"].startswith("local-path:secret-memory.md")


def test_memory_audit_query_returns_path_safe_payloads(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    import_root = tmp_path / "exports" / "vault"
    imported_file = import_root / "memory.md"
    output_dir = tmp_path / "profile" / "out"
    record_memory_audit_event(
        conn,
        "memory_import_completed",
        persona="global",
        target_kind="obsidian_import",
        target_id=str(import_root),
        payload={
            "import_path": str(import_root),
            "output_dir": str(output_dir),
            "nested": {"path": str(imported_file)},
            "written_files": [str(imported_file)],
            "relative_path": "memory/imports/obsidian/memory.md",
            "note": "non-path text remains visible",
        },
    )

    events = memory_audit_query(conn, event_type="memory_import_completed")
    payload = json.dumps(events, sort_keys=True).replace("\\", "/")

    assert len(events) == 1
    assert str(tmp_path).replace("\\", "/") not in payload
    assert str(imported_file).replace("\\", "/") not in payload
    assert events[0]["target_id"].startswith("local-path:vault")
    assert events[0]["target_fingerprint"]
    assert events[0]["payload"]["import_path"].startswith("local-path:vault")
    assert events[0]["payload"]["nested"]["path"].startswith("local-path:memory.md")
    assert events[0]["payload"]["written_files"][0].startswith("local-path:memory.md")
    assert events[0]["payload"]["relative_path"] == "memory/imports/obsidian/memory.md"
    assert events[0]["payload"]["note"] == "non-path text remains visible"


def test_memory_audit_query_preserves_nonlocal_uri_targets() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    target_url = "https://example.test/audit/123"
    record_memory_audit_event(
        conn,
        "memory_external_reference",
        persona="global",
        target_kind="external_uri",
        target_id=target_url,
        payload={
            "source_path": "https://example.test/files/report.md",
            "external_path": "gh:ChimeraWerks/Chimera-Memory#123",
            "drive_path": "C:secrets/token.txt",
            "escape_path": "../secrets/token.txt",
        },
    )

    events = memory_audit_query(conn, event_type="memory_external_reference")

    assert len(events) == 1
    assert events[0]["target_id"] == target_url
    assert "target_fingerprint" not in events[0]
    assert events[0]["payload"]["source_path"] == "https://example.test/files/report.md"
    assert events[0]["payload"]["external_path"] == "gh:ChimeraWerks/Chimera-Memory#123"
    assert events[0]["payload"]["drive_path"].startswith("local-path:token.txt")
    assert events[0]["payload"]["escape_path"] == "token.txt"


def test_memory_audit_query_redacts_sensitive_payload_fields() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    record_memory_audit_event(
        conn,
        "memory_sensitive_audit",
        persona="global",
        target_kind="diagnostic",
        target_id="diag-1",
        payload={
            "raw_prompt": "secret prompt should not leak",
            "wrapped_content": "UNTRUSTED MEMORY CONTENT: body should not leak",
            "stdout": "raw stdout should not leak",
            "stderr": (
                "raw stderr C:/Users/test/.codex/auth.json "
                "Bearer abcdefghijklmnopqrstuvwxyz123456"
            ),
            "command": ["codex", "exec", "--prompt", "secret prompt should not leak"],
            "access_token": "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ123456",
            "error": (
                "model failed at C:/Users/test/.codex/auth.json "
                "with Bearer abcdefghijklmnopqrstuvwxyz123456"
            ),
            "status": "failed",
            "error_type": "RuntimeError",
        },
    )

    events = memory_audit_query(conn, event_type="memory_sensitive_audit")
    payload = events[0]["payload"]
    serialized = json.dumps(events, sort_keys=True)

    assert "secret prompt should not leak" not in serialized
    assert "UNTRUSTED MEMORY CONTENT" not in serialized
    assert "raw stdout should not leak" not in serialized
    assert "raw stderr" not in serialized
    assert "ghp_" not in serialized
    assert ".codex/auth.json" not in serialized.replace("\\\\", "/").replace("\\", "/")
    assert payload["raw_prompt"]["redacted"] is True
    assert payload["wrapped_content"]["redacted"] is True
    assert payload["stdout"]["redacted"] is True
    assert payload["stderr"]["redacted"] is True
    assert payload["command"]["redacted"] is True
    assert payload["access_token"]["redacted"] is True
    assert payload["status"] == "failed"
    assert payload["error_type"] == "RuntimeError"
    assert "local-path:auth.json" in payload["error"]
    assert "Bearer <REDACTED>" in payload["error"]


def test_memory_search_excludes_generated_synthesis_by_default(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    atom = tmp_path / "atom.md"
    atom.write_text(
        "---\ntype: procedural\nimportance: 8\n---\nshared synthesis marker\n",
        encoding="utf-8",
    )
    wiki = tmp_path / "wiki.md"
    wiki.write_text(
        "---\ntype: generated_entity_wiki\nexclude_from_default_search: true\n---\nshared synthesis marker\n",
        encoding="utf-8",
    )
    assert index_file(conn, "asa", "atom.md", atom)
    assert index_file(conn, "asa", "wiki.md", wiki)

    default_results = memory_search(conn, "shared synthesis", persona="asa", limit=10)
    assert [row["relative_path"] for row in default_results] == ["atom.md"]

    with_synthesis = memory_search(
        conn,
        "shared synthesis",
        persona="asa",
        limit=10,
        include_synthesis=True,
    )
    assert {row["relative_path"] for row in with_synthesis} == {"atom.md", "wiki.md"}


def test_memory_query_records_trace_with_total_before_limit(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    for index in range(3):
        memory_file = tmp_path / f"query-{index}.md"
        memory_file.write_text(
            "---\ntype: procedural\nimportance: 8\nabout: query tracing\n---\nstructured query marker\n",
            encoding="utf-8",
        )
        assert index_file(conn, "shared", f"query-{index}.md", memory_file)

    results = memory_query(conn, fm_type="procedural", scope="global", limit=1)
    assert len(results) == 1
    assert results[0]["id"]

    traces = memory_recall_trace_query(conn, tool_name="memory_query", include_items=True)
    assert traces[0]["requested_limit"] == 1
    assert traces[0]["result_count"] == 3
    assert traces[0]["returned_count"] == 1
    assert traces[0]["query_text"] == "structured memory query type=procedural scope=global"
    assert traces[0]["items"][0]["relative_path"].startswith("query-")
    events = memory_audit_query(conn, event_type="recall_requested")
    assert events[0]["payload"]["tool_name"] == "memory_query"
    assert events[0]["payload"]["result_count"] == 3
    assert events[0]["payload"]["returned_count"] == 1


def test_memory_query_traces_miss_and_hides_source_uri(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    memory_file = tmp_path / "query.md"
    memory_file.write_text(
        "---\ntype: procedural\nimportance: 8\n---\nstructured query marker\n",
        encoding="utf-8",
    )
    assert index_file(conn, "shared", "query.md", memory_file)

    results = memory_query(
        conn,
        fm_type="semantic",
        scope="global",
        source_kind="gmail",
        source_uri="sensitive-message-id-123",
        limit=5,
    )

    assert results == []
    traces = memory_recall_trace_query(conn, tool_name="memory_query")
    assert traces[0]["result_count"] == 0
    assert traces[0]["returned_count"] == 0
    assert traces[0]["request_payload"]["source_uri_supplied"] is True
    assert "sensitive-message-id-123" not in str(traces[0])


def test_unchanged_index_file_resyncs_frontmatter_policy_columns(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    wiki = tmp_path / "wiki.md"
    wiki.write_text(
        "---\ntype: generated_entity_wiki\nexclude_from_default_search: true\n---\nshared synthesis marker\n",
        encoding="utf-8",
    )
    assert index_file(conn, "asa", "wiki.md", wiki)
    conn.execute("UPDATE memory_files SET fm_exclude_from_default_search = 0")
    conn.commit()

    assert index_file(conn, "asa", "wiki.md", wiki) is False

    assert conn.execute(
        "SELECT fm_exclude_from_default_search FROM memory_files WHERE relative_path = ?",
        ("wiki.md",),
    ).fetchone()[0] == 1


def test_record_memory_recall_trace_handles_empty_results() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    trace_id = record_memory_recall_trace(
        conn,
        tool_name="memory_recall",
        query_text="nothing here",
        persona="asa",
        requested_limit=3,
        results=[],
        request_payload={"concept": "nothing here"},
        response_policy={"ranking": "embedding_cosine"},
    )

    traces = memory_recall_trace_query(conn, include_items=True)
    assert traces[0]["trace_id"] == trace_id
    assert traces[0]["returned_count"] == 0
    assert traces[0]["items"] == []

    events = memory_audit_query(conn, event_type="recall_requested")
    assert len(events) == 1
    assert events[0]["trace_id"] == trace_id


def test_record_memory_recall_trace_preserves_candidate_result_count() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    trace_id = record_memory_recall_trace(
        conn,
        tool_name="memory_context_pack",
        query_text="bounded context",
        persona=None,
        requested_limit=2,
        results=[
            {
                "id": 1,
                "path": "memory/a.md",
                "relative_path": "memory/a.md",
                "type": "procedural",
            }
        ],
        result_count=7,
        response_policy={"ranking": "test"},
    )

    traces = memory_recall_trace_query(conn)
    assert traces[0]["trace_id"] == trace_id
    assert traces[0]["result_count"] == 7
    assert traces[0]["returned_count"] == 1
    events = memory_audit_query(conn, event_type="recall_requested")
    assert events[0]["payload"]["result_count"] == 7
    assert events[0]["payload"]["returned_count"] == 1


def test_memory_audit_query_filters_event_type_and_persona() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    first = record_memory_audit_event(
        conn,
        "memory_written",
        persona="asa",
        target_kind="memory_file",
        target_id="a.md",
        payload={"status": "pending"},
    )
    record_memory_audit_event(
        conn,
        "memory_rejected",
        persona="sarah",
        target_kind="memory_file",
        target_id="b.md",
    )

    events = memory_audit_query(conn, event_type="memory_written", persona="asa")
    assert len(events) == 1
    assert events[0]["event_id"] == first
    assert events[0]["payload"] == {"status": "pending"}
