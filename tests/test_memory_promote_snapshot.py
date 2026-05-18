import sqlite3
from pathlib import Path

import yaml

from chimera_memory.memory import (
    index_file,
    init_memory_tables,
    memory_audit_query,
    memory_promote_snapshot,
    memory_search,
)


def _write_memory(path: Path, marker: str = "source marker") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                "type: procedural",
                "importance: 8",
                "tags:",
                "  - promotion",
                "---",
                marker,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    end = raw.find("\n---", 3)
    return yaml.safe_load(raw[3:end].strip())


def test_promote_snapshot_preview_does_not_write(tmp_path: Path, monkeypatch) -> None:
    personas_dir = tmp_path / "personas"
    source = personas_dir / "developer" / "asa" / "memory" / "procedural" / "source.md"
    project_root = tmp_path / "ProjectChimera" / ".chimera-memory"
    _write_memory(source)
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    assert index_file(conn, "asa", "memory/procedural/source.md", source)

    result = memory_promote_snapshot(
        conn,
        personas_dir,
        persona="asa",
        source_file_path="memory/procedural/source.md",
        destination_scope="project",
        project_id="ProjectChimera",
    )

    assert result["ok"] is True
    assert result["written"] is False
    assert result["target_relative_path"] == "memory/procedural/source.md"
    assert not (project_root / "memory" / "procedural" / "source.md").exists()
    events = memory_audit_query(conn, event_type="memory_promote_snapshot_planned", persona="asa")
    assert len(events) == 1


def test_promote_snapshot_writes_project_scope_with_provenance(tmp_path: Path, monkeypatch) -> None:
    personas_dir = tmp_path / "personas"
    source = personas_dir / "developer" / "asa" / "memory" / "procedural" / "source.md"
    project_root = tmp_path / "ProjectChimera" / ".chimera-memory"
    _write_memory(source, marker="project promotion marker")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    assert index_file(conn, "asa", "memory/procedural/source.md", source)

    result = memory_promote_snapshot(
        conn,
        personas_dir,
        persona="asa",
        source_file_path="memory/procedural/source.md",
        destination_scope="project",
        project_id="ProjectChimera",
        write=True,
        approved_by="charles",
    )

    target = project_root / "memory" / "procedural" / "source.md"
    assert result["ok"] is True
    assert result["written"] is True
    assert target.exists()

    frontmatter = _frontmatter(target)
    assert frontmatter["memory_scope"] == "project"
    assert frontmatter["project_id"] == "ProjectChimera"
    assert frontmatter["promoted_from"]["persona"] == "asa"
    assert frontmatter["promoted_from"]["path"] == "memory/procedural/source.md"
    assert len(frontmatter["promoted_from"]["source_content_hash"]) == 64
    assert frontmatter["promotion"]["approved_by"] == "charles"

    rows = memory_search(
        conn,
        "project promotion marker",
        persona="sarah",
        project_id="ProjectChimera",
        scope="project",
    )
    assert [(row["persona"], row["memory_scope"], row["project_id"]) for row in rows] == [
        ("project:ProjectChimera", "project", "ProjectChimera")
    ]


def test_promote_snapshot_rejects_duplicate_target(tmp_path: Path, monkeypatch) -> None:
    personas_dir = tmp_path / "personas"
    source = personas_dir / "developer" / "asa" / "memory" / "procedural" / "source.md"
    project_root = tmp_path / "ProjectChimera" / ".chimera-memory"
    target = project_root / "memory" / "procedural" / "source.md"
    _write_memory(source)
    _write_memory(target, marker="existing target")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = memory_promote_snapshot(
        conn,
        personas_dir,
        persona="asa",
        source_file_path="memory/procedural/source.md",
        destination_scope="project",
        project_id="ProjectChimera",
        write=True,
        approved_by="charles",
    )

    assert result["ok"] is False
    assert "duplicate target" in result["error"]
    assert target.read_text(encoding="utf-8").find("existing target") != -1
    events = memory_audit_query(conn, event_type="memory_promote_snapshot_rejected", persona="asa")
    assert len(events) == 1


def test_project_promotion_rejects_targets_outside_project_memory_subtrees(tmp_path: Path, monkeypatch) -> None:
    personas_dir = tmp_path / "personas"
    source = personas_dir / "developer" / "asa" / "memory" / "procedural" / "source.md"
    project_root = tmp_path / "ProjectChimera" / ".chimera-memory"
    _write_memory(source)
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = memory_promote_snapshot(
        conn,
        personas_dir,
        persona="asa",
        source_file_path="memory/procedural/source.md",
        destination_scope="project",
        project_id="ProjectChimera",
        target_relative_path="loose/source.md",
        write=True,
        approved_by="charles",
    )

    assert result["ok"] is False
    assert "memory/ or project/" in result["error"]
    assert not (project_root / "loose" / "source.md").exists()


def test_promote_snapshot_rejects_source_outside_persona_memory(tmp_path: Path, monkeypatch) -> None:
    personas_dir = tmp_path / "personas"
    persona_root = personas_dir / "developer" / "asa"
    source = persona_root / "private.md"
    project_root = tmp_path / "ProjectChimera" / ".chimera-memory"
    _write_memory(source)
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = memory_promote_snapshot(
        conn,
        personas_dir,
        persona="asa",
        source_file_path="private.md",
        destination_scope="project",
        project_id="ProjectChimera",
        write=True,
        approved_by="charles",
    )

    assert result["ok"] is False
    assert "memory/ or reading/" in result["error"]


def test_global_promotion_requires_approval_and_survives_origin_deletion(tmp_path: Path, monkeypatch) -> None:
    personas_dir = tmp_path / "personas"
    source = personas_dir / "developer" / "asa" / "memory" / "procedural" / "global-source.md"
    global_root = tmp_path / "global-memory"
    _write_memory(source, marker="global promotion marker")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))

    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    missing_approval = memory_promote_snapshot(
        conn,
        personas_dir,
        persona="asa",
        source_file_path="memory/procedural/global-source.md",
        destination_scope="global",
        write=True,
    )
    assert missing_approval["ok"] is False
    assert "approved_by" in missing_approval["error"]

    result = memory_promote_snapshot(
        conn,
        personas_dir,
        persona="asa",
        source_file_path="memory/procedural/global-source.md",
        destination_scope="global",
        write=True,
        approved_by="charles",
    )

    target = global_root / "memory" / "procedural" / "global-source.md"
    assert result["ok"] is True
    assert target.exists()
    frontmatter = _frontmatter(target)
    assert frontmatter["memory_scope"] == "global"
    assert "project_id" not in frontmatter

    source.unlink()
    assert target.exists()

    rows = memory_search(conn, "global promotion marker", persona="sarah", scope="global")
    assert [(row["persona"], row["memory_scope"]) for row in rows] == [("global", "global")]
