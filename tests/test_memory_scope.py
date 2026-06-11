import sqlite3
from pathlib import Path

from chimera_memory.db import TranscriptDB
from chimera_memory.memory import (
    full_reindex,
    index_file,
    init_memory_tables,
    memory_query,
    memory_search,
    memory_stats,
    start_memory_watcher,
)
from chimera_memory.memory_observability import memory_recall_trace_query
from chimera_memory.memory_scope import (
    global_memory_root,
    project_memory_root,
    project_memory_roots,
    project_workspace_root,
    workspace_root_from_project_root,
)


def _write(path: Path, marker: str, frontmatter: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = frontmatter or "type: procedural\nimportance: 7\n"
    path.write_text(f"---\n{body}---\n{marker}\n", encoding="utf-8")


def _paths(rows: list[dict]) -> set[tuple[str, str, str | None]]:
    return {
        (
            str(row["persona"]),
            str(row["relative_path"]),
            row.get("project_id"),
        )
        for row in rows
    }


def test_index_file_records_inferred_memory_scope(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    persona_file = tmp_path / "asa.md"
    shared_file = tmp_path / "shared.md"
    project_file = tmp_path / "project.md"
    _write(persona_file, "asa marker")
    _write(shared_file, "shared marker")
    _write(project_file, "project marker", "type: procedural\nmemory_scope: project\nproject_id: ProjectChimera\n")

    assert index_file(conn, "asa", "memory/asa.md", persona_file)
    assert index_file(conn, "shared", "team.md", shared_file)
    assert index_file(conn, "project:ProjectChimera", "memory/status.md", project_file)

    rows = conn.execute(
        """
        SELECT persona, relative_path, memory_scope, project_id
        FROM memory_files
        ORDER BY relative_path
        """
    ).fetchall()

    assert ("asa", "memory/asa.md", "persona", None) in rows
    assert ("shared", "team.md", "global", None) in rows
    assert ("project:ProjectChimera", "memory/status.md", "project", "ProjectChimera") in rows


def test_global_memory_root_falls_back_to_chimera_memory_home(monkeypatch) -> None:
    monkeypatch.delenv("CHIMERA_MEMORY_GLOBAL_ROOT", raising=False)

    assert str(global_memory_root()).replace("\\", "/").endswith("/.chimera-memory/global-memory")


def test_auto_scope_includes_persona_project_and_global_only(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    fixtures = [
        ("asa", "memory/asa.md", "asa.md", "scope marker asa", "type: procedural\nimportance: 7\n"),
        ("sarah", "memory/sarah.md", "sarah.md", "scope marker sarah", "type: procedural\nimportance: 7\n"),
        ("shared", "team.md", "shared.md", "scope marker global", "type: procedural\nimportance: 7\n"),
        (
            "project:ProjectChimera",
            "memory/pc.md",
            "pc.md",
            "scope marker pc",
            "type: procedural\nmemory_scope: project\nproject_id: ProjectChimera\n",
        ),
        (
            "project:ChimeraMemory",
            "memory/cm.md",
            "cm.md",
            "scope marker cm",
            "type: procedural\nmemory_scope: project\nproject_id: ChimeraMemory\n",
        ),
    ]
    for persona, relative_path, filename, marker, frontmatter in fixtures:
        path = tmp_path / filename
        _write(path, marker, frontmatter)
        assert index_file(conn, persona, relative_path, path)

    auto = memory_search(conn, "scope marker", persona="asa", project_id="ProjectChimera", limit=10)
    assert _paths(auto) == {
        ("asa", "memory/asa.md", None),
        ("shared", "team.md", None),
        ("project:ProjectChimera", "memory/pc.md", "ProjectChimera"),
    }

    persona_only = memory_search(
        conn,
        "scope marker",
        persona="asa",
        project_id="ProjectChimera",
        scope="persona",
        limit=10,
    )
    assert _paths(persona_only) == {("asa", "memory/asa.md", None)}

    project_only = memory_query(conn, project_id="ProjectChimera", scope="project", limit=10)
    assert _paths(project_only) == {("project:ProjectChimera", "memory/pc.md", "ProjectChimera")}

    global_only = memory_search(conn, "scope marker", persona="asa", scope="global", limit=10)
    assert _paths(global_only) == {("shared", "team.md", None)}


def test_direct_retrieval_filters_global_rows_outside_active_root(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    active_global_root = tmp_path / "active-global"
    stale_global_root = tmp_path / "stale-global"
    project_file = tmp_path / "repo" / ".chimera-memory" / "memory" / "project.md"

    _write(active_global_root / "active.md", "root boundary marker active")
    _write(stale_global_root / "stale.md", "root boundary marker stale")
    _write(
        project_file,
        "root boundary marker project",
        "type: procedural\nimportance: 7\nmemory_scope: project\nproject_id: ChimeraMemory\n",
    )

    assert index_file(conn, "global", "active.md", active_global_root / "active.md")
    assert index_file(conn, "global", "stale.md", stale_global_root / "stale.md")
    assert index_file(conn, "project:ChimeraMemory", "memory/project.md", project_file)

    search_rows = memory_search(
        conn,
        "root boundary marker",
        project_id="ChimeraMemory",
        limit=10,
        global_root=active_global_root,
    )
    query_rows = memory_query(
        conn,
        fm_type="procedural",
        project_id="ChimeraMemory",
        limit=10,
        global_root=active_global_root,
    )
    stats = memory_stats(conn, project_id="ChimeraMemory", global_root=active_global_root)

    assert _paths(search_rows) == {
        ("global", "active.md", None),
        ("project:ChimeraMemory", "memory/project.md", "ChimeraMemory"),
    }
    assert _paths(query_rows) == {
        ("global", "active.md", None),
        ("project:ChimeraMemory", "memory/project.md", "ChimeraMemory"),
    }
    assert stats["total_files"] == 2
    assert stats["by_persona"] == {"global": 1, "project:ChimeraMemory": 1}
    traces = memory_recall_trace_query(conn, limit=5)
    trace_by_tool = {trace["tool_name"]: trace for trace in traces}
    assert trace_by_tool["memory_search"]["request_payload"]["global_root_filter_enabled"] is True
    assert trace_by_tool["memory_query"]["request_payload"]["global_root_filter_enabled"] is True


def test_full_reindex_discovers_global_and_current_project_layers(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    personas = root / "personas"
    global_root = root / "global-memory"
    project_root = root / "ProjectChimera" / ".chimera-memory"

    _write(personas / "developer" / "asa" / "memory" / "asa.md", "layer marker asa")
    _write(personas / "researcher" / "sarah" / "memory" / "sarah.md", "layer marker sarah")
    _write(root / "shared" / "team.md", "layer marker shared")
    _write(global_root / "charles.md", "layer marker global")
    _write(
        project_root / "memory" / "status.md",
        "layer marker project",
        "type: procedural\nmemory_scope: project\nproject_id: ProjectChimera\n",
    )

    monkeypatch.setenv("TRANSCRIPT_PERSONA", "asa")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "ProjectChimera")

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    full_reindex(conn, personas, embed=False)

    rows = memory_search(conn, "layer marker", persona="asa", project_id="ProjectChimera", limit=10)
    assert _paths(rows) == {
        ("asa", "memory/asa.md", None),
        ("shared", "team.md", None),
        ("global", "charles.md", None),
        ("project:ProjectChimera", "memory/status.md", "ProjectChimera"),
    }
    assert memory_search(conn, "sarah", persona="asa", project_id="ProjectChimera") == []


def test_start_memory_watcher_handles_no_project_roots(tmp_path: Path, monkeypatch) -> None:
    _patch_fake_watcher(monkeypatch)
    personas = tmp_path / "personas"
    (personas / "developer" / "asa" / "memory").mkdir(parents=True)
    monkeypatch.delenv("CHIMERA_CLIENT", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOTS", raising=False)
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(tmp_path / "missing-global"))

    observer = start_memory_watcher(object(), personas)

    assert observer is not None
    assert observer.started is True
    assert observer.scheduled == [(str(personas), True)]


def test_codex_global_only_reindex_skips_persona_tree(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    personas = root / "personas"
    global_root = root / "global-memory"

    _write(personas / "developer" / "asa" / "memory" / "asa.md", "codex global only marker asa")
    _write(personas / "researcher" / "sarah" / "memory" / "sarah.md", "codex global only marker sarah")
    _write(root / "shared" / "team.md", "codex global only marker shared")
    _write(global_root / "charles.md", "codex global only marker global")

    monkeypatch.delenv("TRANSCRIPT_PERSONA", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOTS", raising=False)
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    full_reindex(conn, personas, embed=False)

    rows = memory_search(conn, "codex global only marker", limit=10)
    assert _paths(rows) == {
        ("shared", "team.md", None),
        ("global", "charles.md", None),
    }


def test_full_reindex_skips_hidden_global_and_project_child_paths(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    personas = root / "personas"
    global_root = root / "global-memory"
    project_root = root / "ProjectChimera" / ".chimera-memory"

    _write(root / "shared" / "team.md", "hidden skip visible shared marker")
    _write(global_root / "visible.md", "hidden skip visible global marker")
    _write(global_root / ".shadow" / "secret.md", "concealedglobalmarker")
    _write(global_root / ".secret.md", "concealedrootmarker")
    _write(
        project_root / "memory" / "visible.md",
        "hidden skip visible project marker",
        "type: procedural\nmemory_scope: project\nproject_id: ProjectChimera\n",
    )
    _write(
        project_root / "memory" / ".shadow" / "secret.md",
        "concealedprojectmarker",
        "type: procedural\nmemory_scope: project\nproject_id: ProjectChimera\n",
    )

    monkeypatch.delenv("TRANSCRIPT_PERSONA", raising=False)
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "ProjectChimera")

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    full_reindex(conn, personas, embed=False)

    visible = memory_search(conn, "hidden skip visible", project_id="ProjectChimera", limit=10)
    assert _paths(visible) == {
        ("shared", "team.md", None),
        ("global", "visible.md", None),
        ("project:ProjectChimera", "memory/visible.md", "ProjectChimera"),
    }
    assert memory_search(conn, "concealedglobalmarker", project_id="ProjectChimera", limit=10) == []
    assert memory_search(conn, "concealedrootmarker", project_id="ProjectChimera", limit=10) == []
    assert memory_search(conn, "concealedprojectmarker", project_id="ProjectChimera", limit=10) == []


def test_codex_global_only_reindex_cleanup_preserves_out_of_scope_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path
    personas = root / "personas"
    global_root = root / "global-memory"
    asa = personas / "developer" / "asa" / "memory" / "asa.md"
    live_global = global_root / "live.md"
    stale_global = global_root / "stale.md"
    _write(asa, "cleanup boundary persona marker")
    _write(live_global, "cleanup boundary live global marker")
    _write(stale_global, "cleanup boundary stale global marker")

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    assert index_file(conn, "asa", "memory/asa.md", asa)
    assert index_file(conn, "global", "live.md", live_global)
    assert index_file(conn, "global", "stale.md", stale_global)
    conn.commit()
    stale_global.unlink()

    monkeypatch.delenv("TRANSCRIPT_PERSONA", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOTS", raising=False)
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))

    full_reindex(conn, personas, embed=False)

    rows = conn.execute(
        """
        SELECT persona, relative_path
        FROM memory_files
        ORDER BY persona, relative_path
        """
    ).fetchall()
    assert rows == [
        ("asa", "memory/asa.md"),
        ("global", "live.md"),
    ]


def test_codex_global_only_watcher_skips_persona_tree(tmp_path: Path, monkeypatch) -> None:
    _patch_fake_watcher(monkeypatch)
    personas = tmp_path / "personas"
    shared_root = tmp_path / "shared"
    global_root = tmp_path / "global-memory"
    for root in (personas / "developer" / "asa" / "memory", shared_root, global_root):
        root.mkdir(parents=True)

    monkeypatch.delenv("TRANSCRIPT_PERSONA", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOTS", raising=False)
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))

    observer = start_memory_watcher(object(), personas)

    assert observer is not None
    assert observer.started is True
    assert observer.scheduled == [
        (str(shared_root), True),
        (str(global_root), True),
    ]


def test_start_memory_watcher_schedules_non_persona_project_and_global_roots(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_fake_watcher(monkeypatch)
    personas = tmp_path / "personas"
    shared_root = tmp_path / "shared"
    global_root = tmp_path / "global-memory"
    pc_root = tmp_path / "ProjectChimera" / ".chimera-memory"
    pa_root = tmp_path / "PersonifyAgents" / ".chimera-memory"
    for root in (personas, shared_root, global_root, pc_root, pa_root):
        root.mkdir(parents=True)

    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))
    monkeypatch.setenv(
        "CHIMERA_MEMORY_PROJECT_ROOTS",
        f"ProjectChimera={pc_root};PersonifyAgents={pa_root}",
    )

    observer = start_memory_watcher(object(), personas)

    assert observer is not None
    assert observer.started is True
    assert observer.scheduled == [
        (str(shared_root), True),
        (str(global_root), True),
        (str(pa_root), True),
        (str(pc_root), True),
    ]


def test_project_only_reindex_skips_persona_tree_when_no_persona(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    personas = root / "personas"
    project_root = root / "ChimeraMemory" / ".chimera-memory"

    _write(personas / "developer" / "asa" / "memory" / "asa.md", "project only marker asa")
    _write(personas / "researcher" / "sarah" / "memory" / "sarah.md", "project only marker sarah")
    _write(root / "shared" / "team.md", "project only marker shared")
    _write(
        project_root / "memory" / "status.md",
        "project only marker repo",
        "type: procedural\nmemory_scope: project\nproject_id: ChimeraMemory\n",
    )

    monkeypatch.delenv("TRANSCRIPT_PERSONA", raising=False)
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "ChimeraMemory")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(root / "missing-global"))

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    full_reindex(conn, personas, embed=False)

    rows = memory_search(conn, "project only marker", project_id="ChimeraMemory", limit=10)
    assert _paths(rows) == {
        ("shared", "team.md", None),
        ("project:ChimeraMemory", "memory/status.md", "ChimeraMemory"),
    }


class _FakeObserver:
    instances: list["_FakeObserver"] = []

    def __init__(self) -> None:
        self.scheduled: list[tuple[str, bool]] = []
        self.handlers: list[object] = []
        self.daemon = False
        self.started = False
        _FakeObserver.instances.append(self)

    def schedule(self, handler, path: str, recursive: bool = False) -> None:
        self.handlers.append(handler)
        self.scheduled.append((path, recursive))

    def start(self) -> None:
        self.started = True


def _patch_fake_watcher(monkeypatch) -> None:
    _FakeObserver.instances = []
    monkeypatch.setattr("watchdog.observers.Observer", _FakeObserver)


class _FakeFsEvent:
    def __init__(self, path: Path) -> None:
        self.is_directory = False
        self.src_path = str(path)


def test_start_memory_watcher_indexes_events_from_each_project_root(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_fake_watcher(monkeypatch)
    personas = tmp_path / "personas"
    shared_root = tmp_path / "shared"
    global_root = tmp_path / "global-memory"
    pc_root = tmp_path / "ProjectChimera" / ".chimera-memory"
    pa_root = tmp_path / "PersonifyAgents" / ".chimera-memory"
    for root in (personas / "developer" / "asa" / "memory", shared_root, global_root, pc_root, pa_root):
        root.mkdir(parents=True)

    monkeypatch.delenv("TRANSCRIPT_PERSONA", raising=False)
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))
    monkeypatch.setenv(
        "CHIMERA_MEMORY_PROJECT_ROOTS",
        f"ProjectChimera={pc_root};PersonifyAgents={pa_root}",
    )

    db = TranscriptDB(tmp_path / "watcher.db")
    with db.connection() as conn:
        init_memory_tables(conn)

    observer = start_memory_watcher(db, personas)
    assert observer is not None
    assert len(observer.handlers) == len(observer.scheduled)
    handler = observer.handlers[0]

    pc_file = pc_root / "memory" / "watcher-pc.md"
    pa_file = pa_root / "memory" / "watcher-pa.md"
    private_file = personas / "developer" / "asa" / "memory" / "private.md"
    _write(
        pc_file,
        "multi watcher event pc marker",
        "type: procedural\nmemory_scope: project\nproject_id: ProjectChimera\n",
    )
    _write(
        pa_file,
        "multi watcher event pa marker",
        "type: procedural\nmemory_scope: project\nproject_id: PersonifyAgents\n",
    )
    _write(private_file, "multi watcher event private marker")

    handler.on_created(_FakeFsEvent(pc_file))
    handler.on_created(_FakeFsEvent(pa_file))
    handler.on_created(_FakeFsEvent(private_file))

    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT persona, relative_path, memory_scope, project_id
            FROM memory_files
            ORDER BY project_id, relative_path
            """
        ).fetchall()
    rows = [tuple(row) for row in rows]

    assert rows == [
        ("project:PersonifyAgents", "memory/watcher-pa.md", "project", "PersonifyAgents"),
        ("project:ProjectChimera", "memory/watcher-pc.md", "project", "ProjectChimera"),
    ]


def test_start_memory_watcher_skips_hidden_child_path_events(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_fake_watcher(monkeypatch)
    personas = tmp_path / "personas"
    shared_root = tmp_path / "shared"
    global_root = tmp_path / "global-memory"
    project_root = tmp_path / "ProjectChimera" / ".chimera-memory"
    for root in (personas, shared_root, global_root, project_root):
        root.mkdir(parents=True)

    monkeypatch.delenv("TRANSCRIPT_PERSONA", raising=False)
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "ProjectChimera")

    db = TranscriptDB(tmp_path / "watcher.db")
    with db.connection() as conn:
        init_memory_tables(conn)

    observer = start_memory_watcher(db, personas)
    assert observer is not None
    handler = observer.handlers[0]

    hidden_global = global_root / ".shadow" / "secret.md"
    hidden_project = project_root / "memory" / ".shadow" / "secret.md"
    visible_global = global_root / "visible.md"
    _write(hidden_global, "watcher hidden global marker")
    _write(
        hidden_project,
        "watcher hidden project marker",
        "type: procedural\nmemory_scope: project\nproject_id: ProjectChimera\n",
    )
    _write(visible_global, "watcher visible global marker")

    handler.on_created(_FakeFsEvent(hidden_global))
    handler.on_created(_FakeFsEvent(hidden_project))
    handler.on_created(_FakeFsEvent(visible_global))

    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT persona, relative_path, memory_scope, project_id
            FROM memory_files
            ORDER BY relative_path
            """
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("global", "visible.md", "global", None),
    ]


def test_project_root_map_resolves_multiple_project_layers(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    personas = root / "personas"
    pc_root = root / "ProjectChimera" / ".chimera-memory"
    pa_root = root / "PersonifyAgents" / ".chimera-memory"

    _write(personas / "developer" / "asa" / "memory" / "asa.md", "multi project marker asa")
    _write(
        pc_root / "memory" / "status.md",
        "multi project marker pc",
        "type: procedural\nmemory_scope: project\nproject_id: ProjectChimera\n",
    )
    _write(
        pa_root / "memory" / "status.md",
        "multi project marker pa",
        "type: procedural\nmemory_scope: project\nproject_id: PersonifyAgents\n",
    )

    monkeypatch.setenv("TRANSCRIPT_PERSONA", "asa")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(root / "missing-global"))
    monkeypatch.setenv(
        "CHIMERA_MEMORY_PROJECT_ROOTS",
        f"ProjectChimera={pc_root};PersonifyAgents={pa_root}",
    )

    assert project_memory_root("ProjectChimera") == pc_root
    assert project_memory_root("PersonifyAgents") == pa_root
    assert dict(project_memory_roots()) == {
        "PersonifyAgents": pa_root,
        "ProjectChimera": pc_root,
    }

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    full_reindex(conn, personas, embed=False)

    assert _paths(memory_search(conn, "multi project marker", persona="asa", project_id="ProjectChimera", limit=10)) == {
        ("asa", "memory/asa.md", None),
        ("project:ProjectChimera", "memory/status.md", "ProjectChimera"),
    }
    assert _paths(memory_search(conn, "multi project marker", persona="asa", project_id="PersonifyAgents", limit=10)) == {
        ("asa", "memory/asa.md", None),
        ("project:PersonifyAgents", "memory/status.md", "PersonifyAgents"),
    }


def test_explicit_project_id_pairs_with_single_project_root(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "repo-folder" / ".chimera-memory"

    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "ChimeraMemory")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))

    assert project_memory_root("ChimeraMemory") == project_root
    assert dict(project_memory_roots()) == {"ChimeraMemory": project_root}
    assert project_workspace_root("ChimeraMemory") == project_root.parent


def test_project_workspace_root_handles_nested_project_memory_dirs(tmp_path: Path, monkeypatch) -> None:
    memory_root = tmp_path / "repo-folder" / ".chimera-memory" / "memory"

    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "ChimeraMemory")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(memory_root))

    assert project_memory_root("ChimeraMemory") == memory_root
    assert project_workspace_root("ChimeraMemory") == memory_root.parent.parent


def test_workspace_root_from_plain_project_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo-folder"

    assert workspace_root_from_project_root(repo_root) == repo_root.resolve(strict=False)


def test_workspace_root_from_relative_project_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert workspace_root_from_project_root(".") == tmp_path.resolve(strict=False)
