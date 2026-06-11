import sqlite3
from pathlib import Path

from chimera_memory.memory import (
    index_file,
    init_memory_tables,
    memory_audit_query,
    memory_live_retrieval_check,
    memory_recall_trace_query,
)
from chimera_memory.memory_live_retrieval import build_live_retrieval_plan, extract_live_retrieval_terms


def _write_memory(path: Path, frontmatter: list[str], body: str) -> None:
    path.write_text(
        "\n".join(["---", *frontmatter, "---", body]),
        encoding="utf-8",
    )


def test_live_retrieval_plan_detects_topic_shift() -> None:
    plan = build_live_retrieval_plan(
        previous_context="We are closing workboard triage and Discord gateway cleanup.",
        current_context="Now we are debugging memory provider smoke and sidecar credentials.",
    )

    assert plan["should_retrieve"] is True
    assert plan["shift_score"] >= plan["shift_threshold"]
    assert "memory" in plan["query_terms"]
    assert "sidecar" in plan["query_terms"]


def test_live_retrieval_terms_ignore_prior_cm_context_fences() -> None:
    terms = extract_live_retrieval_terms(
        """
        <chimera-memory-context returned="1">
        Codex Desktop automatic injection supervisor stale evidence.
        </chimera-memory-context>
        <chimera-transcript-context returned="1">
        Sidecar credential OAuth Spark smoke stale transcript.
        </chimera-transcript-context>
        Now debug registry indexing health.
        """,
        limit=20,
    )

    assert terms == ["debug", "registry", "indexing", "health"]


def test_live_retrieval_skips_without_shift_and_audits(monkeypatch) -> None:
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = memory_live_retrieval_check(
        conn,
        previous_context="memory provider smoke sidecar credentials",
        current_context="memory provider smoke sidecar credentials",
        persona="asa",
    )

    assert result["ok"] is True
    assert result["retrieved"] is False
    assert result["reason"] == "no_topic_shift"
    assert result["scope_policy"]["includes"] == ["global", "persona"]
    assert memory_recall_trace_query(conn, tool_name="memory_live_retrieval") == []
    events = memory_audit_query(conn, event_type="memory_live_retrieval_skipped", persona="asa")
    assert len(events) == 1


def test_live_retrieval_returns_suggestions_and_records_trace(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    target = tmp_path / "provider-smoke.md"
    _write_memory(
        target,
        ["type: procedural", "importance: 8", "about: provider smoke harness"],
        "Provider smoke harness verifies sidecar credentials and memory enhancement rails.",
    )
    restricted = tmp_path / "restricted.md"
    _write_memory(
        restricted,
        [
            "type: semantic",
            "importance: 9",
            "sensitivity_tier: restricted",
            "about: restricted provider smoke",
        ],
        "Restricted provider smoke note should not appear in default live retrieval.",
    )
    assert index_file(conn, "asa", "memory/provider-smoke.md", target)
    assert index_file(conn, "asa", "memory/restricted.md", restricted)

    result = memory_live_retrieval_check(
        conn,
        current_context="Need provider smoke sidecar credentials verification now.",
        previous_context="Earlier topic was workboard cleanup.",
        persona="asa",
        force=True,
        limit=5,
    )

    assert result["ok"] is True
    assert result["retrieved"] is True
    assert len(result["results"]) == 1
    assert result["results"][0]["relative_path"] == "memory/provider-smoke.md"
    assert result["trace_id"]

    traces = memory_recall_trace_query(conn, tool_name="memory_live_retrieval", include_items=True)
    assert len(traces) == 1
    assert traces[0]["trace_id"] == result["trace_id"]
    assert traces[0]["items"][0]["relative_path"] == "memory/provider-smoke.md"

    events = memory_audit_query(conn, event_type="memory_live_retrieval_suggested", persona="asa")
    assert len(events) == 1
    assert events[0]["trace_id"] == result["trace_id"]


def test_live_retrieval_excludes_synthesis_by_default_and_allows_opt_in(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    synthesis = tmp_path / "synthesis.md"
    _write_memory(
        synthesis,
        [
            "type: generated_entity_wiki",
            "importance: 8",
            "exclude_from_default_search: true",
            "about: synthesis broker explicit request",
        ],
        "Synthesis broker memory appears only when explicitly requested.",
    )
    assert index_file(conn, "asa", "memory/synthesis.md", synthesis)

    default = memory_live_retrieval_check(
        conn,
        current_context="Need synthesis broker memory explicit request now.",
        previous_context="Earlier topic was unrelated.",
        persona="asa",
        force=True,
        limit=5,
    )
    assert default["ok"] is True
    assert default["retrieved"] is True
    assert default["raw_result_count"] == 0
    assert default["results"] == []

    included = memory_live_retrieval_check(
        conn,
        current_context="Need synthesis broker memory explicit request now.",
        previous_context="Earlier topic was unrelated.",
        persona="asa",
        force=True,
        limit=5,
        include_synthesis=True,
    )
    assert included["ok"] is True
    assert included["retrieved"] is True
    assert included["raw_result_count"] == 1
    assert [row["relative_path"] for row in included["results"]] == ["memory/synthesis.md"]

    traces = memory_recall_trace_query(conn, tool_name="memory_live_retrieval")
    included_trace = next(trace for trace in traces if trace["trace_id"] == included["trace_id"])
    assert included_trace["request_payload"]["include_synthesis"] is True


def test_live_retrieval_project_mode_uses_project_and_global_scope(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    project = tmp_path / "project.md"
    global_memory = tmp_path / "global.md"
    private = tmp_path / "private.md"
    _write_memory(
        project,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: project",
            "project_id: Chimera-Memory",
            "about: Codex live retrieval project wrapper evidence",
        ],
        "Codex live retrieval project wrapper evidence belongs to current project memory.",
    )
    _write_memory(
        global_memory,
        [
            "type: semantic",
            "importance: 7",
            "memory_scope: global",
            "about: Codex live retrieval global wrapper evidence",
        ],
        "Codex live retrieval global wrapper evidence belongs to global memory.",
    )
    _write_memory(
        private,
        [
            "type: procedural",
            "importance: 10",
            "about: Codex live retrieval private wrapper evidence",
        ],
        "Codex live retrieval private wrapper evidence must not appear in project mode.",
    )
    assert index_file(conn, "project:Chimera-Memory", "memory/project-live.md", project)
    assert index_file(conn, "global", "global/live.md", global_memory)
    assert index_file(conn, "asa", "memory/private-live.md", private)

    result = memory_live_retrieval_check(
        conn,
        current_context="Need Codex live retrieval wrapper evidence now.",
        project_id="Chimera-Memory",
        force=True,
        limit=10,
    )

    paths = {row["relative_path"] for row in result["results"]}
    assert "memory/project-live.md" in paths
    assert "global/live.md" in paths
    assert "memory/private-live.md" not in paths
    assert result["scope_policy"]["includes"] == ["global", "project"]

    traces = memory_recall_trace_query(conn, tool_name="memory_live_retrieval", include_items=True)
    assert traces[0]["response_policy"]["scope_policy"]["includes"] == ["global", "project"]


def test_live_retrieval_filters_global_rows_outside_active_root(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    active_root = tmp_path / "active-global"
    outside_root = tmp_path / "old-global"
    active_root.mkdir()
    outside_root.mkdir()
    active = active_root / "inside.md"
    outside = outside_root / "outside.md"
    _write_memory(
        active,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: global",
            "about: active root live retrieval marker",
        ],
        "Active root live retrieval marker belongs to the configured global root.",
    )
    _write_memory(
        outside,
        [
            "type: procedural",
            "importance: 10",
            "memory_scope: global",
            "about: active root live retrieval marker",
        ],
        "Outside root live retrieval marker must not be suggested for the active global root.",
    )
    assert index_file(conn, "global", "global/inside-live.md", active)
    assert index_file(conn, "global", "global/outside-live.md", outside)

    result = memory_live_retrieval_check(
        conn,
        current_context="Need active root live retrieval marker now.",
        project_id="Chimera-Memory",
        force=True,
        limit=10,
        global_root=active_root,
    )

    assert result["raw_result_count"] == 1
    assert [row["relative_path"] for row in result["results"]] == ["global/inside-live.md"]
    assert result["scope_policy"]["global_root_filtered"] is True

    traces = memory_recall_trace_query(conn, tool_name="memory_live_retrieval")
    trace = next(row for row in traces if row["trace_id"] == result["trace_id"])
    assert trace["request_payload"]["global_root_filter_enabled"] is True


def test_live_retrieval_project_scope_excludes_global_and_other_projects(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    current_project = tmp_path / "current-project.md"
    other_project = tmp_path / "other-project.md"
    global_memory = tmp_path / "global.md"
    _write_memory(
        current_project,
        [
            "type: procedural",
            "memory_scope: project",
            "project_id: Chimera-Memory",
            "about: scoped retrieval exact project marker",
        ],
        "Scoped retrieval exact project marker for Chimera-Memory.",
    )
    _write_memory(
        other_project,
        [
            "type: procedural",
            "memory_scope: project",
            "project_id: Other-Project",
            "about: scoped retrieval exact project marker",
        ],
        "Scoped retrieval exact project marker for another project.",
    )
    _write_memory(
        global_memory,
        [
            "type: semantic",
            "memory_scope: global",
            "about: scoped retrieval exact project marker",
        ],
        "Scoped retrieval exact project marker for global memory.",
    )
    assert index_file(conn, "project:Chimera-Memory", "memory/current.md", current_project)
    assert index_file(conn, "project:Other-Project", "memory/other.md", other_project)
    assert index_file(conn, "global", "global/scoped.md", global_memory)

    result = memory_live_retrieval_check(
        conn,
        current_context="Need scoped retrieval exact project marker.",
        project_id="Chimera-Memory",
        scope="project",
        force=True,
        limit=10,
    )

    assert [row["relative_path"] for row in result["results"]] == ["memory/current.md"]
    assert result["scope_policy"]["includes"] == ["project"]


def test_live_retrieval_filters_weak_global_broad_matches(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    weak_global = tmp_path / "weak-global.md"
    relevant_project = tmp_path / "relevant-project.md"
    _write_memory(
        weak_global,
        [
            "type: semantic",
            "importance: 10",
            "memory_scope: global",
            "about: broad memory context project",
        ],
        "Broad memory context project note without useful implementation detail.",
    )
    _write_memory(
        relevant_project,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: project",
            "project_id: Chimera-Memory",
            "about: Codex Desktop automatic injection supervisor setup",
        ],
        "Codex Desktop automatic injection needs a hook or wrapper supervisor.",
    )
    assert index_file(conn, "global", "global/weak-live.md", weak_global)
    assert index_file(conn, "project:Chimera-Memory", "memory/relevant-live.md", relevant_project)

    result = memory_live_retrieval_check(
        conn,
        current_context="Need memory context project Codex Desktop automatic injection supervisor setup.",
        project_id="Chimera-Memory",
        force=True,
        limit=5,
    )

    assert result["raw_result_count"] == 2
    assert result["filtered_count"] == 1
    assert [row["relative_path"] for row in result["results"]] == ["memory/relevant-live.md"]
    traces = memory_recall_trace_query(conn, tool_name="memory_live_retrieval", include_items=True)
    assert traces[0]["response_policy"]["quality_gate"]["filtered_count"] == 1


def test_live_retrieval_quality_gate_miss_when_only_weak_matches(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    weak_global = tmp_path / "weak-global-only.md"
    _write_memory(
        weak_global,
        [
            "type: semantic",
            "importance: 10",
            "memory_scope: global",
            "about: broad memory context project",
        ],
        "Broad memory context project note without useful implementation detail.",
    )
    assert index_file(conn, "global", "global/weak-live-only.md", weak_global)

    result = memory_live_retrieval_check(
        conn,
        current_context="Need memory context project Codex Desktop automatic injection supervisor setup.",
        project_id="Chimera-Memory",
        force=True,
        limit=5,
    )

    assert result["retrieved"] is True
    assert result["results"] == []
    assert result["raw_result_count"] == 1
    assert result["filtered_count"] == 1
    events = memory_audit_query(conn, event_type="memory_live_retrieval_miss")
    assert len(events) == 1
    assert events[0]["payload"]["filtered_count"] == 1


def test_live_retrieval_miss_is_traced_and_silent() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = memory_live_retrieval_check(
        conn,
        current_context="quantum zebra umbrella impossible context",
        persona="asa",
        force=True,
    )

    assert result["ok"] is True
    assert result["retrieved"] is True
    assert result["results"] == []
    assert result["trace_id"]
    events = memory_audit_query(conn, event_type="memory_live_retrieval_miss", persona="asa")
    assert len(events) == 1
