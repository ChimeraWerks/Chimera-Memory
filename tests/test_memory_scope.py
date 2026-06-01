import sqlite3
from pathlib import Path

from chimera_memory.memory import full_reindex, index_file, init_memory_tables, memory_query, memory_search
from chimera_memory.memory_scope import project_memory_root, project_memory_roots


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

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    full_reindex(conn, personas, embed=False)

    rows = memory_search(conn, "project only marker", project_id="ChimeraMemory", limit=10)
    assert _paths(rows) == {
        ("shared", "team.md", None),
        ("project:ChimeraMemory", "memory/status.md", "ChimeraMemory"),
    }


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
