import sqlite3
from pathlib import Path

from chimera_memory.embeddings import pack_embedding
from chimera_memory.memory import index_file, init_memory_tables, memory_recall
from chimera_memory.memory_observability import memory_recall_trace_query


def _write_memory(path: Path, frontmatter: list[str], body: str) -> None:
    path.write_text("\n".join(["---", *frontmatter, "---", body]), encoding="utf-8")


def _embed_file(conn: sqlite3.Connection, file_id: int, vector: list[float]) -> None:
    conn.execute(
        "INSERT INTO memory_embeddings (file_id, embedding, embedded_at) VALUES (?, ?, 0)",
        (file_id, pack_embedding(vector)),
    )


def test_memory_recall_filters_low_similarity_noise(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    relevant = tmp_path / "relevant.md"
    noise = tmp_path / "noise.md"
    _write_memory(
        relevant,
        ["type: procedural", "importance: 8", "about: Codex project recall setup"],
        "Codex project recall setup uses scoped semantic memory.",
    )
    _write_memory(
        noise,
        ["type: semantic", "importance: 10", "about: unrelated archive"],
        "Unrelated archive note should not appear for low similarity semantic recall.",
    )
    assert index_file(conn, "project:Chimera-Memory", "memory/relevant.md", relevant)
    assert index_file(conn, "global", "global/noise.md", noise)
    relevant_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", ("memory/relevant.md",)).fetchone()[0]
    noise_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", ("global/noise.md",)).fetchone()[0]
    _embed_file(conn, relevant_id, [1.0, 0.0, 0.0])
    _embed_file(conn, noise_id, [0.0, 1.0, 0.0])
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0, 0.0])

    results = memory_recall(
        conn,
        "Codex project recall setup",
        project_id="Chimera-Memory",
        limit=5,
    )

    assert [row["relative_path"] for row in results] == ["memory/relevant.md"]
    traces = memory_recall_trace_query(conn, tool_name="memory_recall", include_items=True)
    assert traces[0]["response_policy"]["min_similarity"] == 0.15
    assert traces[0]["response_policy"]["raw_candidate_count"] == 2
    assert traces[0]["response_policy"]["filtered_count"] == 1
    assert len(traces[0]["items"]) == 1


def test_memory_recall_filters_semantic_noise_without_term_coverage(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    relevant = tmp_path / "relevant.md"
    noise = tmp_path / "noise.md"
    _write_memory(
        relevant,
        ["type: procedural", "importance: 8", "about: Codex automatic injection wrapper"],
        "Codex automatic injection wrapper uses scoped ChimeraMemory context.",
    )
    _write_memory(
        noise,
        ["type: semantic", "importance: 10", "about: spatial index archive"],
        "Spatial index archive note has a nearby embedding but no matching Codex terms.",
    )
    assert index_file(conn, "project:Chimera-Memory", "memory/relevant.md", relevant)
    assert index_file(conn, "global", "global/noise.md", noise)
    relevant_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", ("memory/relevant.md",)).fetchone()[0]
    noise_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", ("global/noise.md",)).fetchone()[0]
    _embed_file(conn, relevant_id, [1.0, 0.0])
    _embed_file(conn, noise_id, [0.8, 0.6])
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0])

    results = memory_recall(
        conn,
        "Codex automatic injection wrapper",
        project_id="Chimera-Memory",
        limit=5,
    )

    assert [row["relative_path"] for row in results] == ["memory/relevant.md"]
    traces = memory_recall_trace_query(conn, tool_name="memory_recall")
    assert traces[0]["response_policy"]["similarity_filtered_count"] == 0
    assert traces[0]["response_policy"]["quality_gate"]["filtered_count"] == 1


def test_memory_recall_allows_explicit_lower_similarity_floor(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    noise = tmp_path / "noise.md"
    _write_memory(
        noise,
        ["type: semantic", "importance: 10", "memory_scope: global", "about: low similarity global note"],
        "Low similarity global note can be surfaced when a caller explicitly lowers the floor.",
    )
    assert index_file(conn, "global", "global/noise.md", noise)
    file_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", ("global/noise.md",)).fetchone()[0]
    _embed_file(conn, file_id, [0.0, 1.0, 0.0])
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0, 0.0])

    default_results = memory_recall(conn, "unrelated concept", scope="global", limit=5)
    lowered_results = memory_recall(conn, "unrelated concept", scope="global", limit=5, min_similarity=0.0)

    assert default_results == []
    assert [row["relative_path"] for row in lowered_results] == ["global/noise.md"]


def test_memory_recall_rescues_exact_global_body_match_below_similarity_floor(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    memory = tmp_path / "team.md"
    _write_memory(
        memory,
        ["type: procedural", "importance: 8", "memory_scope: global"],
        "Codex remember forward momentum team knowledge should be visible to no-persona project agents.",
    )
    assert index_file(conn, "global", "TEAM_KNOWLEDGE.md", memory)
    file_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", ("TEAM_KNOWLEDGE.md",)).fetchone()[0]
    _embed_file(conn, file_id, [0.0, 1.0, 0.0])
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0, 0.0])

    results = memory_recall(conn, "codex remember forward momentum team knowledge", scope="global", limit=5)

    assert [row["relative_path"] for row in results] == ["TEAM_KNOWLEDGE.md"]
    assert results[0]["metadata"]["recall_source"] == "fts_rescue"
    traces = memory_recall_trace_query(conn, tool_name="memory_recall", include_items=True)
    assert traces[0]["response_policy"]["similarity_filtered_count"] == 1
    assert traces[0]["response_policy"]["fts_rescue"]["raw_candidate_count"] == 1
    assert traces[0]["items"][0]["metadata"]["recall_source"] == "fts_rescue"


def test_memory_recall_respects_explicit_stricter_similarity_floor_for_fts_rescue(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    memory = tmp_path / "team.md"
    _write_memory(
        memory,
        ["type: procedural", "importance: 8", "memory_scope: global"],
        "Codex remember forward momentum team knowledge should be visible at the default floor.",
    )
    assert index_file(conn, "global", "TEAM_KNOWLEDGE.md", memory)
    file_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", ("TEAM_KNOWLEDGE.md",)).fetchone()[0]
    _embed_file(conn, file_id, [1.0, 0.0, 0.0])
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0, 0.0])

    results = memory_recall(
        conn,
        "codex remember forward momentum team knowledge",
        scope="global",
        limit=5,
        min_similarity=1.1,
    )

    assert results == []
    traces = memory_recall_trace_query(conn, tool_name="memory_recall")
    assert traces[0]["response_policy"]["fts_rescue"]["reason"] == "min_similarity_above_default"


def test_memory_recall_respects_project_scope_after_similarity_filter(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    current_project = tmp_path / "current.md"
    other_project = tmp_path / "other.md"
    _write_memory(
        current_project,
        [
            "type: procedural",
            "memory_scope: project",
            "project_id: Chimera-Memory",
            "about: scoped semantic recall marker",
        ],
        "Scoped semantic recall marker for current project.",
    )
    _write_memory(
        other_project,
        [
            "type: procedural",
            "memory_scope: project",
            "project_id: Other-Project",
            "about: scoped semantic recall marker",
        ],
        "Scoped semantic recall marker for another project.",
    )
    assert index_file(conn, "project:Chimera-Memory", "memory/current.md", current_project)
    assert index_file(conn, "project:Other-Project", "memory/other.md", other_project)
    current_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", ("memory/current.md",)).fetchone()[0]
    other_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", ("memory/other.md",)).fetchone()[0]
    _embed_file(conn, current_id, [1.0, 0.0, 0.0])
    _embed_file(conn, other_id, [1.0, 0.0, 0.0])
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0, 0.0])

    results = memory_recall(
        conn,
        "scoped semantic recall marker",
        project_id="Chimera-Memory",
        scope="project",
        limit=10,
    )

    assert [row["relative_path"] for row in results] == ["memory/current.md"]


def test_memory_recall_filters_global_rows_outside_active_root(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    active_global_root = tmp_path / "active-global"
    stale_global_root = tmp_path / "stale-global"
    active_global_root.mkdir()
    stale_global_root.mkdir()
    active = active_global_root / "active.md"
    stale = stale_global_root / "stale.md"
    _write_memory(
        active,
        ["type: procedural", "importance: 8"],
        "Semantic root boundary marker active.",
    )
    _write_memory(
        stale,
        ["type: procedural", "importance: 8"],
        "Semantic root boundary marker stale.",
    )
    assert index_file(conn, "global", "active.md", active)
    assert index_file(conn, "global", "stale.md", stale)
    for relative_path in ("active.md", "stale.md"):
        file_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", (relative_path,)).fetchone()[0]
        _embed_file(conn, file_id, [1.0, 0.0, 0.0])
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0, 0.0])

    results = memory_recall(
        conn,
        "Semantic root boundary marker",
        scope="global",
        limit=10,
        global_root=active_global_root,
    )

    assert [row["relative_path"] for row in results] == ["active.md"]
    traces = memory_recall_trace_query(conn, tool_name="memory_recall")
    assert traces[0]["request_payload"]["global_root_filter_enabled"] is True
    assert traces[0]["response_policy"]["raw_candidate_count"] == 1


def test_memory_recall_excludes_restricted_blocked_and_non_evidence_by_default(tmp_path: Path, monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    fixtures = [
        (
            "global/standard.md",
            ["type: procedural", "importance: 8"],
            "Semantic governance marker standard.",
        ),
        (
            "global/restricted.md",
            ["type: procedural", "importance: 8", "sensitivity_tier: restricted"],
            "Semantic governance marker restricted.",
        ),
        (
            "global/blocked.md",
            ["type: procedural", "importance: 8", "lifecycle_status: rejected"],
            "Semantic governance marker blocked.",
        ),
        (
            "global/non-evidence.md",
            ["type: procedural", "importance: 8", "can_use_as_evidence: false"],
            "Semantic governance marker non evidence.",
        ),
    ]
    for relative_path, frontmatter, body in fixtures:
        path = tmp_path / relative_path.replace("/", "-")
        _write_memory(path, frontmatter, body)
        assert index_file(conn, "global", relative_path, path)
        file_id = conn.execute("SELECT id FROM memory_files WHERE relative_path = ?", (relative_path,)).fetchone()[0]
        _embed_file(conn, file_id, [1.0, 0.0, 0.0])
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0, 0.0])

    default_results = memory_recall(conn, "Semantic governance marker", scope="global", limit=10)
    opt_in_results = memory_recall(
        conn,
        "Semantic governance marker",
        scope="global",
        limit=10,
        include_restricted=True,
        include_blocked=True,
    )

    assert [row["relative_path"] for row in default_results] == ["global/standard.md"]
    assert {row["relative_path"] for row in opt_in_results} == {
        "global/standard.md",
        "global/restricted.md",
        "global/blocked.md",
    }
