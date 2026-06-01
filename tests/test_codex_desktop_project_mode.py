import json
from pathlib import Path

import chimera_memory.config as config
from chimera_memory.server import create_server


def _write_memory(path: Path, frontmatter: list[str], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(["---", *frontmatter, "---", body]), encoding="utf-8")


def _tool_fn(mcp, name: str):
    for tool in mcp._tool_manager.list_tools():
        if tool.name == name:
            return tool.fn
    raise AssertionError(f"tool not registered: {name}")


def _configure_project_env(monkeypatch, tmp_path: Path) -> dict[str, Path]:
    config_dir = tmp_path / "config"
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "CONFIG_PATH", config_dir / "config.yaml")

    paths = {
        "db": tmp_path / "transcript.db",
        "sessions": tmp_path / "sessions",
        "personas": tmp_path / "personas",
        "shared": tmp_path / "shared",
        "global": tmp_path / "global",
        "project": tmp_path / "repo" / ".chimera-memory",
    }
    paths["sessions"].mkdir(parents=True)
    paths["global"].mkdir(parents=True)

    for key in (
        "TRANSCRIPT_PERSONA",
        "CHIMERA_PERSONA_ID",
        "CHIMERA_PERSONA_NAME",
        "CHIMERA_PERSONA_ROOT",
        "CHIMERA_SHARED_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(paths["db"]))
    monkeypatch.setenv("TRANSCRIPT_JSONL_DIR", str(paths["sessions"]))
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    monkeypatch.setenv("CHIMERA_PERSONAS_DIR", str(paths["personas"]))
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(paths["global"]))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "ChimeraMemory")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(paths["project"]))
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "codex")
    return paths


def _seed_memory(paths: dict[str, Path]) -> None:
    _write_memory(
        paths["project"] / "memory" / "desktop.md",
        [
            "type: procedural",
            "importance: 9",
            "memory_scope: project",
            "project_id: ChimeraMemory",
            "about: Codex Desktop project memory",
        ],
        "Codex Desktop project marker proves project scoped recall works.",
    )
    _write_memory(
        paths["shared"] / "global.md",
        [
            "type: semantic",
            "importance: 7",
            "about: shared global memory",
        ],
        "Shared global marker proves global memory remains available.",
    )
    _write_memory(
        paths["personas"] / "developer" / "asa" / "memory" / "private.md",
        [
            "type: procedural",
            "importance: 10",
            "about: private persona memory",
        ],
        "Persona-only-secret phrase must not appear in no persona Codex project mode.",
    )


def _patch_fast_memory_indexing(monkeypatch) -> None:
    monkeypatch.setattr("chimera_memory.memory.start_memory_watcher", lambda *args, **kwargs: None)
    monkeypatch.setattr("chimera_memory.embeddings.embed_text", lambda text: [1.0, 0.0, 0.0])
    monkeypatch.setattr("chimera_memory.embeddings.embed_batch", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])


def test_codex_project_surface_registers_expected_mcp_tools(monkeypatch, tmp_path: Path) -> None:
    _configure_project_env(monkeypatch, tmp_path)

    mcp = create_server()
    tools = {tool.name for tool in mcp._tool_manager.list_tools()}

    assert {
        "memory_context_pack",
        "memory_recall",
        "memory_search",
        "memory_query",
        "memory_remember",
        "memory_diagnose",
        "discord_recall_index",
    } <= tools
    assert "memory_import_chatgpt_export" not in tools
    assert "transcript_backfill" not in tools


def test_codex_project_mcp_memory_tools_use_project_and_global_scope(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()

    search = _tool_fn(mcp, "memory_search")("Codex Desktop project marker", limit=5)
    assert "memory/desktop.md" in search
    assert "project:ChimeraMemory" in search
    assert "Private persona marker" not in search

    no_private = _tool_fn(mcp, "memory_search")("Persona-only-secret", limit=5)
    assert no_private == "No memories found matching your query."

    query = _tool_fn(mcp, "memory_query")(type="procedural", scope="project", project_id="ChimeraMemory")
    assert "memory/desktop.md" in query
    assert "project:ChimeraMemory" in query

    recall = _tool_fn(mcp, "memory_recall")("Codex Desktop project marker", limit=5)
    assert "memory/desktop.md" in recall
    assert "private.md" not in recall

    pack = _tool_fn(mcp, "memory_context_pack")(
        current_context="Need Codex Desktop project marker memory now.",
        previous_context="Earlier work was unrelated.",
        force=True,
        limit=5,
    )
    assert "Memory context pack ready." in pack
    assert "memory/desktop.md" in pack
    assert "Private persona marker" not in pack

    diagnose = _tool_fn(mcp, "memory_diagnose")(mode="whereami")
    payload = json.loads(diagnose)
    assert payload["resolved"]["transcript_persona"] is None
    assert payload["resolved"]["project_id"] == "ChimeraMemory"
    assert payload["resolved"]["project_root"] == str(paths["project"])

    transcript_index = _tool_fn(mcp, "discord_recall_index")(search="anything", limit=5)
    assert transcript_index == "No messages found matching your query."


def test_codex_project_mcp_remember_previews_and_writes_project_memory(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()
    payload_yaml = """
memory_id: codex-desktop-project-write
memory_type: procedural
importance: 8
author: codex
memory_payload:
  decisions:
    - Codex Desktop no-persona mode writes authored memory to project scope.
source_refs: []
provenance:
  default_status: user_confirmed
  confidence: 1.0
  requires_review: false
review_status: confirmed
"""

    preview = _tool_fn(mcp, "memory_remember")(payload_yaml=payload_yaml, write=False, enqueue=False)
    assert "Remember preview only." in preview
    assert "memory/procedural/codex-desktop-project-write.md" in preview

    written = _tool_fn(mcp, "memory_remember")(payload_yaml=payload_yaml, write=True, enqueue=False)
    assert "Remembered memory/procedural/codex-desktop-project-write.md (project:ChimeraMemory)." in written

    target = paths["project"] / "memory" / "procedural" / "codex-desktop-project-write.md"
    content = target.read_text(encoding="utf-8")
    assert "memory_scope: project" in content
    assert "project_id: ChimeraMemory" in content
    assert "Codex Desktop no-persona mode writes authored memory" in content
