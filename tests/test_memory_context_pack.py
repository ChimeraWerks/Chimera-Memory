import sqlite3
from pathlib import Path

from chimera_memory.memory import index_file, init_memory_tables, memory_audit_query, memory_recall_trace_query
from chimera_memory.memory_context_pack import memory_context_pack, strip_memory_context


def _write_memory(path: Path, frontmatter: list[str], body: str) -> None:
    path.write_text(
        "\n".join(["---", *frontmatter, "---", body]),
        encoding="utf-8",
    )


def test_context_pack_skips_without_topic_shift_and_audits() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = memory_context_pack(
        conn,
        current_context="memory broker context pack",
        previous_context="memory broker context pack",
        persona="asa",
    )

    assert result["ok"] is True
    assert result["retrieved"] is False
    assert result["reason"] == "no_topic_shift"
    assert result["context_block"] == ""
    assert memory_recall_trace_query(conn, tool_name="memory_context_pack") == []
    events = memory_audit_query(conn, event_type="memory_context_pack_skipped", persona="asa")
    assert len(events) == 1


def test_context_pack_returns_fenced_scoped_cards_and_trace(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    normal = tmp_path / "broker.md"
    restricted = tmp_path / "restricted.md"
    other = tmp_path / "other.md"
    synthesis = tmp_path / "synthesis.md"
    _write_memory(
        normal,
        ["type: procedural", "importance: 9", "about: Hermes-style memory broker"],
        "Hermes context broker retrieves bounded memory cards before each turn.",
    )
    _write_memory(
        restricted,
        [
            "type: semantic",
            "importance: 10",
            "sensitivity_tier: restricted",
            "about: restricted broker note",
        ],
        "Restricted Hermes context broker note should not auto-inject.",
    )
    _write_memory(
        other,
        ["type: procedural", "importance: 9", "about: Sarah broker note"],
        "Sarah-only Hermes context broker note should stay outside Asa scope.",
    )
    _write_memory(
        synthesis,
        [
            "type: semantic",
            "importance: 9",
            "exclude_from_default_search: true",
            "about: generated broker synthesis",
        ],
        "Generated synthesis about Hermes context broker should be excluded by default.",
    )
    assert index_file(conn, "asa", "memory/broker.md", normal)
    assert index_file(conn, "asa", "memory/restricted.md", restricted)
    assert index_file(conn, "sarah", "memory/other.md", other)
    assert index_file(conn, "asa", "memory/synthesis.md", synthesis)

    result = memory_context_pack(
        conn,
        current_context="Need Hermes context broker automatic memory cards now.",
        previous_context="Earlier topic was oauth setup.",
        persona="asa",
        limit=5,
        force=True,
    )

    assert result["ok"] is True
    assert result["retrieved"] is True
    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "memory/broker.md"
    assert "<chimera-memory-context" in result["context_block"]
    assert "Recalled ChimeraMemory context" in result["context_block"]
    assert "Restricted" not in result["context_block"]
    assert "Sarah-only" not in result["context_block"]
    assert "Generated synthesis" not in result["context_block"]

    traces = memory_recall_trace_query(conn, tool_name="memory_context_pack", include_items=True)
    assert len(traces) == 1
    assert traces[0]["trace_id"] == result["trace_id"]
    assert traces[0]["items"][0]["relative_path"] == "memory/broker.md"

    events = memory_audit_query(conn, event_type="memory_context_pack_returned", persona="asa")
    assert len(events) == 1
    assert events[0]["trace_id"] == result["trace_id"]


def test_context_pack_filters_weak_global_matches(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    generic = tmp_path / "generic.md"
    _write_memory(
        generic,
        ["type: semantic", "importance: 9", "about: general team memory"],
        "This is a general shared memory note for broad team context. It mentions stopping working without durable setup details.",
    )
    assert index_file(conn, "shared", "team/generic.md", generic)

    result = memory_context_pack(
        conn,
        current_context="memory codex desktop automatic injection supervisor",
        project_id="Chimera-Memory",
        scope="auto",
        force=True,
    )

    assert result["ok"] is True
    assert result["retrieved"] is True
    assert result["returned_count"] == 0
    assert result["context_block"] == ""
    traces = memory_recall_trace_query(conn, tool_name="memory_context_pack")
    assert traces[0]["response_policy"]["quality_gate"]["filtered_count"] == 1


def test_context_pack_prefers_relevant_project_over_weak_global(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    generic = tmp_path / "generic.md"
    project = tmp_path / "codex-injection.md"
    _write_memory(
        generic,
        ["type: semantic", "importance: 9", "about: general team memory"],
        "This is a general shared memory note for broad team context. It mentions stopping working without durable setup details.",
    )
    _write_memory(
        project,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: project",
            "project_id: Chimera-Memory",
            "about: Codex Desktop ChimeraMemory automatic injection supervisor",
        ],
        "Codex Desktop automatic injection depends on a supervisor or hook that prepends ChimeraMemory context.",
    )
    assert index_file(conn, "shared", "team/generic.md", generic)
    assert index_file(conn, "project:Chimera-Memory", "memory/codex-injection.md", project)

    result = memory_context_pack(
        conn,
        current_context="memory codex desktop automatic injection supervisor",
        project_id="Chimera-Memory",
        scope="auto",
        force=True,
        limit=5,
    )

    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "memory/codex-injection.md"
    assert result["cards"][0]["memory_scope"] == "project"
    assert "team/generic.md" not in result["context_block"]


def test_context_pack_keeps_relevant_global_memory(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    global_memory = tmp_path / "codex-global.md"
    _write_memory(
        global_memory,
        [
            "type: procedural",
            "importance: 8",
            "about: global Codex Desktop automatic injection supervisor policy",
        ],
        "Global memory says Codex Desktop automatic injection needs a hook or supervisor to prepend context.",
    )
    assert index_file(conn, "shared", "codex/global-injection.md", global_memory)

    result = memory_context_pack(
        conn,
        current_context="memory codex desktop automatic injection supervisor",
        project_id="Chimera-Memory",
        scope="auto",
        force=True,
        limit=5,
    )

    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "codex/global-injection.md"
    assert result["cards"][0]["memory_scope"] == "global"


def test_context_pack_filters_global_rows_outside_active_root(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    active_root = tmp_path / "active-global"
    outside_root = tmp_path / "old-global"
    active = active_root / "active.md"
    outside = outside_root / "outside.md"
    active.parent.mkdir(parents=True)
    outside.parent.mkdir(parents=True)
    _write_memory(
        active,
        ["type: procedural", "importance: 5", "about: active global root retrieval marker"],
        "Active global root retrieval marker should survive filtering.",
    )
    _write_memory(
        outside,
        ["type: procedural", "importance: 10", "about: outside global root retrieval marker"],
        "Outside global root retrieval marker must not be injected.",
    )
    assert index_file(conn, "global", "active.md", active)
    assert index_file(conn, "global", "outside.md", outside)

    result = memory_context_pack(
        conn,
        current_context="global root retrieval marker",
        scope="global",
        global_root=active_root,
        force=True,
        limit=5,
    )

    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "active.md"
    assert "Active global root retrieval marker" in result["context_block"]
    assert "Outside global root retrieval marker" not in result["context_block"]
    traces = memory_recall_trace_query(conn, tool_name="memory_context_pack")
    assert traces[0]["request_payload"]["global_root_filter_enabled"] is True
    assert str(active_root) not in str(traces[0])


def test_context_pack_labels_pending_global_memory_as_non_authoritative(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    global_memory = tmp_path / "pending-global.md"
    _write_memory(
        global_memory,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: global",
            "provenance_status: imported",
            "review_status: pending",
            "can_use_as_instruction: false",
            "can_use_as_evidence: true",
            "requires_user_confirmation: true",
            "about: pending global Codex wrapper policy",
        ],
        "Pending global memory says Codex wrapper evidence must be visibly non-authoritative.",
    )
    assert index_file(conn, "global", "pending-global.md", global_memory)

    result = memory_context_pack(
        conn,
        current_context="pending global Codex wrapper evidence non-authoritative",
        scope="global",
        force=True,
        limit=5,
    )

    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "pending-global.md"
    assert result["cards"][0]["can_use_as_instruction"] is False
    assert "review=pending" in result["context_block"]
    assert "evidence-only" in result["context_block"]
    assert "needs-confirmation" in result["context_block"]


def test_context_pack_labels_non_active_lifecycle_global_memory(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    global_memory = tmp_path / "archived-global.md"
    _write_memory(
        global_memory,
        [
            "type: procedural",
            "importance: 9",
            "memory_scope: global",
            "provenance_status: user_confirmed",
            "review_status: confirmed",
            "lifecycle_status: archived",
            "can_use_as_instruction: true",
            "can_use_as_evidence: true",
            "requires_user_confirmation: false",
            "about: archived global lifecycle marker",
        ],
        "Archived global lifecycle marker can be evidence but must not look current.",
    )
    assert index_file(conn, "global", "archived-global.md", global_memory)

    result = memory_context_pack(
        conn,
        current_context="archived global lifecycle marker",
        scope="global",
        force=True,
        limit=5,
    )

    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "archived-global.md"
    assert "review=confirmed" in result["context_block"]
    assert "lifecycle=archived" in result["context_block"]
    assert "evidence-only" not in result["context_block"]
    assert "needs-confirmation" not in result["context_block"]


def test_context_pack_does_not_fallback_to_raw_path_when_relative_path_missing(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    global_memory = tmp_path / "global-root" / "absolute-fallback.md"
    global_memory.parent.mkdir()
    _write_memory(
        global_memory,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: global",
            "about: absolute fallback leak marker",
        ],
        "Absolute fallback leak marker should use a synthetic context label.",
    )
    assert index_file(conn, "global", "absolute-fallback.md", global_memory)
    file_id = conn.execute(
        "SELECT id FROM memory_files WHERE relative_path = ?",
        ("absolute-fallback.md",),
    ).fetchone()[0]
    conn.execute("UPDATE memory_files SET relative_path = '' WHERE id = ?", (file_id,))

    result = memory_context_pack(
        conn,
        current_context="absolute fallback leak marker",
        scope="global",
        force=True,
        limit=5,
    )

    assert result["returned_count"] == 1
    assert str(global_memory) not in result["context_block"]
    assert f"global#{file_id}" in result["context_block"]


def test_context_pack_sanitizes_path_shaped_db_relative_path(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    global_memory = tmp_path / "global-root" / "path-shaped.md"
    global_memory.parent.mkdir()
    _write_memory(
        global_memory,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: global",
            "about: path-shaped context label marker",
        ],
        "Path-shaped context label marker should never expose local parent directories.",
    )
    assert index_file(conn, "global", "path-shaped.md", global_memory)
    file_id = conn.execute(
        "SELECT id FROM memory_files WHERE relative_path = ?",
        ("path-shaped.md",),
    ).fetchone()[0]
    unsafe_relative_path = str(global_memory)
    conn.execute(
        "UPDATE memory_files SET relative_path = ? WHERE id = ?",
        (unsafe_relative_path, file_id),
    )

    result = memory_context_pack(
        conn,
        current_context="path-shaped context label marker",
        scope="global",
        force=True,
        limit=5,
    )

    rendered = result["context_block"].replace("\\", "/")
    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == unsafe_relative_path
    assert "path-shaped.md" in rendered
    assert str(tmp_path).replace("\\", "/") not in rendered
    assert unsafe_relative_path.replace("\\", "/") not in rendered


def test_context_pack_sanitizes_prompt_prose_paths_and_secrets(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    global_memory = tmp_path / "global-root" / "safe-prose.md"
    global_memory.parent.mkdir()
    fake_pat = "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ123456"
    raw_auth_path = "C:/Users/test/.codex/auth.json"
    _write_memory(
        global_memory,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: global",
            f"about: safe prose marker {raw_auth_path} {fake_pat}",
        ],
        f"Safe prose marker body cites {raw_auth_path} with {fake_pat}.",
    )
    assert index_file(conn, "global", "safe-prose.md", global_memory)

    result = memory_context_pack(
        conn,
        current_context="safe prose marker",
        scope="global",
        force=True,
        limit=5,
    )

    rendered = result["context_block"].replace("\\", "/")
    assert result["returned_count"] == 1
    assert "local-path:auth.json" in rendered
    assert "<REDACTED:github-pat>" in rendered
    assert raw_auth_path not in rendered
    assert ".codex/auth.json" not in rendered
    assert "ghp_" not in rendered


def test_context_pack_keeps_relevant_global_body_match(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    global_memory = tmp_path / "global-body.md"
    _write_memory(
        global_memory,
        ["type: procedural", "importance: 8", "about: generic global process note"],
        "Codex Desktop automatic injection requires a supervisor hook to prepend ChimeraMemory context.",
    )
    assert index_file(conn, "shared", "global/body-only.md", global_memory)

    result = memory_context_pack(
        conn,
        current_context="memory codex desktop automatic injection supervisor",
        project_id="Chimera-Memory",
        scope="auto",
        force=True,
        limit=5,
    )

    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "global/body-only.md"
    assert "Codex Desktop automatic injection" in result["context_block"]


def test_context_pack_matches_hyphenated_global_terms(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    global_memory = tmp_path / "forward-momentum.md"
    _write_memory(
        global_memory,
        [
            "memory_scope: global",
            "provenance_status: auto_confirmed",
            "review_status: confirmed",
            "can_use_as_instruction: true",
            "can_use_as_evidence: true",
            "requires_user_confirmation: false",
        ],
        "The forward-momentum preset keeps Codex work moving without repeated approval checks.",
    )
    assert index_file(conn, "global", "modes/forward-momentum.md", global_memory)

    result = memory_context_pack(
        conn,
        current_context="forward momentum Codex operating memory",
        scope="global",
        force=True,
        limit=5,
    )

    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "modes/forward-momentum.md"
    assert result["cards"][0]["query_match_profile"]["specific_match_count"] >= 2
    assert "forward" in result["cards"][0]["query_match_profile"]["matched_terms"]
    assert "momentum" in result["cards"][0]["query_match_profile"]["matched_terms"]


def test_context_pack_semantic_only_global_rescue(monkeypatch, tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    global_memory = tmp_path / "semantic-rescue.md"
    _write_memory(
        global_memory,
        ["type: procedural", "importance: 8", "about: bridge policy"],
        "The local service bridge must place recovered evidence before the model call.",
    )
    assert index_file(conn, "shared", "global/semantic-rescue.md", global_memory)
    file_id = conn.execute(
        "SELECT id FROM memory_files WHERE relative_path = ?",
        ("global/semantic-rescue.md",),
    ).fetchone()[0]

    from chimera_memory.embeddings import pack_embedding

    conn.execute(
        "INSERT INTO memory_embeddings (file_id, embedding, embedded_at) VALUES (?, ?, 0)",
        (file_id, pack_embedding([1.0, 0.0, 0.0])),
    )
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0, 0.0])

    result = memory_context_pack(
        conn,
        current_context="codex desktop automatic injection supervisor",
        project_id="Chimera-Memory",
        scope="auto",
        force=True,
        limit=5,
    )

    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "global/semantic-rescue.md"
    assert result["cards"][0]["query_match_profile"]["specific_match_count"] == 0
    assert result["cards"][0]["semantic_score"] == 1.0


def test_context_pack_filters_weak_globals_without_crowding_relevant_rows(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    for index in range(3):
        weak = tmp_path / f"weak-{index}.md"
        _write_memory(
            weak,
            ["type: semantic", "importance: 10", "about: broad shared memory context"],
            f"Shared office memory context note {index} mentions stopping working without durable setup details.",
        )
        assert index_file(conn, "shared", f"weak/{index}.md", weak)

    relevant_global = tmp_path / "relevant-global.md"
    relevant_project = tmp_path / "relevant-project.md"
    _write_memory(
        relevant_global,
        [
            "type: procedural",
            "importance: 7",
            "about: Codex Desktop automatic injection supervisor global fallback",
        ],
        "Global fallback: Codex Desktop automatic injection requires a supervisor or hook.",
    )
    _write_memory(
        relevant_project,
        [
            "type: procedural",
            "importance: 7",
            "memory_scope: project",
            "project_id: Chimera-Memory",
            "about: ChimeraMemory Codex Desktop automatic injection project setup",
        ],
        "Project setup: ChimeraMemory Codex Desktop automatic injection should use a hook or wrapper.",
    )
    assert index_file(conn, "shared", "global/relevant.md", relevant_global)
    assert index_file(conn, "project:Chimera-Memory", "memory/relevant.md", relevant_project)

    result = memory_context_pack(
        conn,
        current_context="memory codex desktop automatic injection supervisor",
        project_id="Chimera-Memory",
        scope="auto",
        force=True,
        limit=2,
    )

    assert {card["relative_path"] for card in result["cards"]} == {
        "global/relevant.md",
        "memory/relevant.md",
    }
    assert result["filtered_count"] == 3


def test_context_pack_dedupes_global_relative_path_overlap(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    first = tmp_path / "root-a" / "TEAM_KNOWLEDGE.md"
    second = tmp_path / "root-b" / "TEAM_KNOWLEDGE.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    _write_memory(
        first,
        ["type: procedural", "importance: 8", "about: canonical global duplicate marker"],
        "Canonical global duplicate marker should appear once in context.",
    )
    _write_memory(
        second,
        ["type: procedural", "importance: 7", "about: canonical global duplicate marker"],
        "Canonical global duplicate marker should appear once in context.",
    )
    assert index_file(conn, "shared", "TEAM_KNOWLEDGE.md", first)
    assert index_file(conn, "global", "TEAM_KNOWLEDGE.md", second)

    result = memory_context_pack(
        conn,
        current_context="canonical global duplicate marker",
        scope="global",
        force=True,
        limit=5,
    )

    assert result["raw_result_count"] == 2
    assert result["result_count"] == 1
    assert result["duplicate_filtered_count"] == 1
    assert result["returned_count"] == 1
    assert result["context_block"].count("TEAM_KNOWLEDGE.md") == 1
    traces = memory_recall_trace_query(conn, tool_name="memory_context_pack")
    assert traces[0]["response_policy"]["dedupe"]["removed_count"] == 1


def test_context_pack_dedupes_exact_content_fingerprint_overlap(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    content = (
        "---\n"
        "type: procedural\n"
        "importance: 8\n"
        "about: exact duplicate global content marker\n"
        "---\n"
        "Exact duplicate global content marker should appear once.\n"
    )
    first = tmp_path / "one.md"
    second = tmp_path / "two.md"
    first.write_text(content, encoding="utf-8")
    second.write_text(content, encoding="utf-8")
    assert index_file(conn, "global", "global/one.md", first)
    assert index_file(conn, "global", "global/two.md", second)

    result = memory_context_pack(
        conn,
        current_context="exact duplicate global content marker",
        scope="global",
        force=True,
        limit=5,
    )

    assert result["raw_result_count"] == 2
    assert result["result_count"] == 1
    assert result["duplicate_filtered_count"] == 1
    assert result["returned_count"] == 1
    assert result["context_block"].count("Exact duplicate global content marker") == 1


def test_context_pack_no_persona_project_scope_excludes_persona_private_exact_match(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    private = tmp_path / "private.md"
    _write_memory(
        private,
        ["type: procedural", "importance: 10", "about: private exact recall marker"],
        "Private exact Codex Desktop automatic injection supervisor marker.",
    )
    assert index_file(conn, "asa", "memory/private.md", private)

    scoped = memory_context_pack(
        conn,
        current_context="private exact codex desktop automatic injection supervisor marker",
        project_id="Chimera-Memory",
        scope="auto",
        force=True,
        limit=5,
    )
    assert scoped["returned_count"] == 0

    unscoped = memory_context_pack(
        conn,
        current_context="private exact codex desktop automatic injection supervisor marker",
        scope="all",
        force=True,
        limit=5,
    )
    assert unscoped["returned_count"] == 1
    assert unscoped["cards"][0]["relative_path"] == "memory/private.md"


def test_context_pack_allows_restricted_and_synthesis_only_when_explicit(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    restricted = tmp_path / "restricted.md"
    synthesis = tmp_path / "synthesis.md"
    _write_memory(
        restricted,
        ["type: semantic", "sensitivity_tier: restricted", "importance: 8"],
        "Restricted broker memory can appear only when explicitly requested.",
    )
    _write_memory(
        synthesis,
        ["type: semantic", "exclude_from_default_search: true", "importance: 8"],
        "Synthesis broker memory can appear only when explicitly requested.",
    )
    assert index_file(conn, "asa", "memory/restricted.md", restricted)
    assert index_file(conn, "asa", "memory/synthesis.md", synthesis)

    default = memory_context_pack(
        conn,
        current_context="broker memory explicit request",
        persona="asa",
        force=True,
    )
    assert default["returned_count"] == 0

    included = memory_context_pack(
        conn,
        current_context="broker memory explicit request",
        persona="asa",
        force=True,
        include_restricted=True,
        include_synthesis=True,
    )
    assert {card["relative_path"] for card in included["cards"]} == {
        "memory/restricted.md",
        "memory/synthesis.md",
    }


def test_context_pack_respects_token_budget(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    for idx in range(5):
        path = tmp_path / f"memory-{idx}.md"
        _write_memory(
            path,
            ["type: procedural", "importance: 7"],
            f"Hermes broker memory card {idx} " + ("detail " * 80),
        )
        assert index_file(conn, "asa", f"memory/card-{idx}.md", path)

    result = memory_context_pack(
        conn,
        current_context="Hermes broker memory card detail",
        persona="asa",
        force=True,
        limit=5,
        token_budget=160,
    )

    assert 1 <= result["returned_count"] < 5
    assert result["token_estimate"] <= 160
    traces = memory_recall_trace_query(conn, tool_name="memory_context_pack")
    assert traces[0]["result_count"] == 5
    assert traces[0]["returned_count"] == result["returned_count"]


def test_strip_memory_context_removes_supported_fences() -> None:
    text = (
        "hello\n"
        "<chimera-memory-context trace_id=\"x\">secret</chimera-memory-context>\n"
        "<memory-context>legacy</memory-context>\n"
        "<supermemory-context>provider</supermemory-context>\n"
        "world"
    )

    assert strip_memory_context(text) == "hello\n\n\n\nworld"
