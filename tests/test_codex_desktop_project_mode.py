import asyncio
import json
import sqlite3
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


async def _call_tool(mcp, name: str, arguments: dict):
    return await mcp._tool_manager.call_tool(name, arguments)


def _tool_text(result) -> str:
    if isinstance(result, list):
        return "\n".join(str(getattr(item, "text", item)) for item in result)
    return str(getattr(result, "text", result))


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
        paths["global"] / "global.md",
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
    } <= tools
    assert "memory_promote_snapshot" not in tools
    assert "memory_review" not in tools
    assert "discord_recall_index" not in tools
    assert "discord_detail" not in tools
    assert "semantic_search" not in tools
    assert "session_list" not in tools
    assert "memory_import_chatgpt_export" not in tools
    assert "transcript_backfill" not in tools
    assert "project/global memory evidence for Codex" in mcp.instructions
    assert "semantic_search" not in mcp.instructions
    assert "does not expose transcript recall tools" in mcp.instructions


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

    stats = _tool_fn(mcp, "memory_stats")()
    assert "**Total files:** 2" in stats
    assert "project:ChimeraMemory: 1" in stats
    assert "global: 1" in stats
    assert "asa" not in stats

    query = _tool_fn(mcp, "memory_query")(type="procedural", scope="project", project_id="ChimeraMemory")
    assert "memory/desktop.md" in query
    assert "project:ChimeraMemory" in query

    recall = _tool_fn(mcp, "memory_recall")("Codex Desktop project marker", limit=5)
    assert "memory/desktop.md" in recall
    assert "private.md" not in recall
    strict_recall = _tool_fn(mcp, "memory_recall")(
        "Codex Desktop project marker",
        limit=5,
        min_similarity=1.1,
    )
    assert strict_recall == "No similar memories found."

    pack = _tool_fn(mcp, "memory_context_pack")(
        current_context="Need Codex Desktop project marker memory now.",
        previous_context="Earlier work was unrelated.",
        force=True,
        limit=5,
    )
    assert "Memory context pack ready." in pack
    assert "memory/desktop.md" in pack
    assert "Private persona marker" not in pack

    live = _tool_fn(mcp, "memory_live_retrieval_check")(
        current_context="Need Codex Desktop project marker memory now.",
        previous_context="Earlier work was unrelated.",
        force=True,
        limit=5,
    )
    assert "memory/desktop.md" in live
    assert "project:ChimeraMemory" in live
    assert "private.md" not in live

    diagnose = _tool_fn(mcp, "memory_diagnose")(mode="whereami")
    payload = json.loads(diagnose)
    assert payload["resolved"]["transcript_persona"] is None
    assert payload["resolved"]["project_id"] == "ChimeraMemory"
    assert payload["resolved"]["project_root"] == str(paths["project"])
    assert payload["resolved"]["global_root"] == str(paths["global"])
    assert payload["provenance"]["global_root"] == {"source": "env", "key": "CHIMERA_MEMORY_GLOBAL_ROOT"}

    context_status = _tool_fn(mcp, "memory_diagnose")(mode="context")
    assert "CM context status" in context_status
    assert "memory_context_pack" in context_status
    assert "Latest returned context:" in context_status
    assert "mechanical prompt evidence requires a Codex wrapper" in context_status
    assert "(local " in context_status
    assert "Need Codex Desktop project marker memory now" not in context_status
    assert "Persona-only-secret" not in context_status

    tools = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert "discord_recall_index" not in tools
    assert "semantic_search" not in tools


def test_codex_project_mcp_diagnose_rejects_persona_admin_modes(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()

    tools = _tool_fn(mcp, "memory_diagnose")(mode="tools")
    assert "Codex project/global memory tools:" in tools
    assert "memory_review - list" not in tools
    assert "Persona review, persona snapshot promotion, and persona-private diagnostics require" in tools

    for mode in ("zones", "traces", "trace_analyze", "audit", "harness", "gaps", "consolidation"):
        result = _tool_fn(mcp, "memory_diagnose")(
            mode=mode,
            persona="asa",
            query="Persona-only-secret",
            include_items=True,
        )
        assert "Codex no-persona MCP surface does not allow persona/admin diagnose mode" in result
        assert "Persona-only-secret" not in result
        assert "private.md" not in result

    context = _tool_fn(mcp, "memory_diagnose")(mode="context", persona="asa")
    assert "Codex no-persona MCP surface does not allow persona-scoped memory" in context
    assert "Persona-only-secret" not in context


def test_codex_project_mcp_rejects_explicit_persona_scope_bypass(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()
    expected = "Codex no-persona MCP surface does not allow persona-scoped memory"

    search = _tool_fn(mcp, "memory_search")("Persona-only-secret", persona="asa", limit=5)
    assert expected in search
    assert "Persona-only-secret" not in search

    query = _tool_fn(mcp, "memory_query")(persona="asa", type="procedural", limit=5)
    assert expected in query
    assert "private.md" not in query

    recall = _tool_fn(mcp, "memory_recall")("Persona-only-secret", persona="asa", limit=5)
    assert expected in recall
    assert "private.md" not in recall

    stats = _tool_fn(mcp, "memory_stats")(persona="asa")
    assert expected in stats
    assert "asa" not in stats

    pack = _tool_fn(mcp, "memory_context_pack")(
        current_context="Need Persona-only-secret marker now.",
        previous_context="Earlier work was unrelated.",
        persona="asa",
        force=True,
        limit=5,
    )
    assert expected in pack
    assert "Persona-only-secret" not in pack

    live = _tool_fn(mcp, "memory_live_retrieval_check")(
        current_context="Need Persona-only-secret marker now.",
        previous_context="Earlier work was unrelated.",
        persona="asa",
        force=True,
        limit=5,
    )
    assert expected in live
    assert "private.md" not in live

    remember = _tool_fn(mcp, "memory_remember")(
        payload_yaml="{}",
        persona="asa",
        write=True,
        enqueue=False,
    )
    assert expected in remember

    assert "memory_promote_snapshot" not in {tool.name for tool in mcp._tool_manager.list_tools()}
    assert {path.relative_to(paths["global"]).as_posix() for path in paths["global"].rglob("*.md")} == {
        "global.md",
    }

    monkeypatch.setenv("TRANSCRIPT_PERSONA", "asa")
    env_search = _tool_fn(mcp, "memory_search")("Persona-only-secret", limit=5)
    assert expected in env_search
    assert "Persona-only-secret" not in env_search


def test_codex_project_context_tools_accept_null_optional_identity(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()

    pack_result = asyncio.run(
        _call_tool(
            mcp,
            "memory_context_pack",
            {
                "current_context": "Need Codex Desktop project marker memory now.",
                "previous_context": None,
                "persona": None,
                "project_id": None,
                "scope": None,
                "force": True,
                "limit": 5,
            },
        )
    )
    pack = _tool_text(pack_result)
    assert "Memory context pack ready." in pack
    assert "memory/desktop.md" in pack
    assert "Private persona marker" not in pack

    live_result = asyncio.run(
        _call_tool(
            mcp,
            "memory_live_retrieval_check",
            {
                "current_context": "Need Codex Desktop project marker memory now.",
                "previous_context": None,
                "persona": None,
                "project_id": None,
                "scope": None,
                "force": True,
                "limit": 5,
            },
        )
    )
    live = _tool_text(live_result)
    assert "Live retrieval suggestions." in live
    assert "memory/desktop.md" in live
    assert "Private persona marker" not in live


def test_codex_project_live_retrieval_excludes_synthesis_by_default(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _write_memory(
        paths["project"] / "memory" / "synthesis-live.md",
        [
            "type: generated_entity_wiki",
            "importance: 8",
            "memory_scope: project",
            "project_id: ChimeraMemory",
            "exclude_from_default_search: true",
            "about: velvet synthesis dossier citadel",
        ],
        "Velvet synthesis dossier citadel marker belongs only to generated project synthesis.",
    )
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()

    default = _tool_fn(mcp, "memory_live_retrieval_check")(
        current_context="Need velvet synthesis dossier citadel now.",
        previous_context="Earlier work was unrelated.",
        force=True,
        limit=5,
    )
    assert "Live retrieval miss." in default
    assert "synthesis-live.md" not in default

    included = _tool_fn(mcp, "memory_live_retrieval_check")(
        current_context="Need velvet synthesis dossier citadel now.",
        previous_context="Earlier work was unrelated.",
        force=True,
        limit=5,
        include_synthesis=True,
    )
    assert "Live retrieval suggestions." in included
    assert "memory/synthesis-live.md" in included


def test_codex_project_live_retrieval_passes_active_global_root(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _patch_fast_memory_indexing(monkeypatch)
    captured: dict[str, object] = {}

    def fake_live_retrieval(_conn, **kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "retrieved": True,
            "trace_id": "fake-live-trace",
            "plan": {"query_text": "active root wrapper marker"},
            "results": [],
        }

    monkeypatch.setattr(
        "chimera_memory.memory.memory_live_retrieval_check",
        fake_live_retrieval,
    )

    mcp = create_server()
    result = _tool_fn(mcp, "memory_live_retrieval_check")(
        current_context="Need active root wrapper marker now.",
        previous_context="Earlier work was unrelated.",
        force=True,
        limit=5,
    )

    assert "Live retrieval miss." in result
    assert captured["global_root"] == paths["global"]
    assert captured["project_id"] is None
    assert captured["scope"] == "auto"


def test_codex_project_direct_retrieval_tools_pass_active_global_root(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _patch_fast_memory_indexing(monkeypatch)
    captured: dict[str, dict[str, object]] = {}

    def fake_search(_conn, *args, **kwargs):
        captured["search"] = kwargs
        return []

    def fake_query(_conn, **kwargs):
        captured["query"] = kwargs
        return []

    def fake_recall(_conn, *args, **kwargs):
        captured["recall"] = kwargs
        return []

    def fake_stats(_conn, *args, **kwargs):
        captured["stats"] = kwargs
        return {
            "total_files": 0,
            "by_type": {},
            "by_status": {},
            "by_persona": {},
        }

    monkeypatch.setattr("chimera_memory.memory.memory_search", fake_search)
    monkeypatch.setattr("chimera_memory.memory.memory_query", fake_query)
    monkeypatch.setattr("chimera_memory.memory.memory_recall", fake_recall)
    monkeypatch.setattr("chimera_memory.memory.memory_stats", fake_stats)

    mcp = create_server()

    assert _tool_fn(mcp, "memory_search")("active root wrapper marker", limit=5) == (
        "No memories found matching your query."
    )
    assert _tool_fn(mcp, "memory_query")(type="procedural", limit=5) == "No memories match your criteria."
    assert _tool_fn(mcp, "memory_recall")("active root wrapper marker", limit=5) == "No similar memories found."
    assert "**Total files:** 0" in _tool_fn(mcp, "memory_stats")()

    assert captured["search"]["global_root"] == paths["global"]
    assert captured["query"]["global_root"] == paths["global"]
    assert captured["recall"]["global_root"] == paths["global"]
    assert captured["stats"]["global_root"] == paths["global"]


def test_codex_project_mcp_retrieval_text_sanitizes_path_shaped_relative_paths(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()
    assert "global.md" in _tool_fn(mcp, "memory_search")("Shared global marker", scope="global", limit=5)

    unsafe_relative_path = str(paths["global"] / "global.md")
    conn = sqlite3.connect(paths["db"])
    try:
        conn.execute(
            "UPDATE memory_files SET relative_path = ? WHERE persona = ? AND relative_path = ?",
            (unsafe_relative_path, "global", "global.md"),
        )
        conn.commit()
    finally:
        conn.close()

    outputs = [
        _tool_fn(mcp, "memory_search")("Shared global marker", scope="global", limit=5),
        _tool_fn(mcp, "memory_query")(type="semantic", scope="global", limit=5),
        _tool_fn(mcp, "memory_recall")("Shared global marker", scope="global", limit=5),
        _tool_fn(mcp, "memory_live_retrieval_check")(
            current_context="Need Shared global marker now.",
            previous_context="Earlier work was unrelated.",
            scope="global",
            force=True,
            limit=5,
        ),
        _tool_fn(mcp, "memory_context_pack")(
            current_context="Need Shared global marker now.",
            previous_context="Earlier work was unrelated.",
            scope="global",
            force=True,
            limit=5,
        ),
    ]
    combined = "\n".join(outputs).replace("\\", "/")

    assert "global.md" in combined
    assert str(paths["global"]).replace("\\", "/") not in combined
    assert unsafe_relative_path.replace("\\", "/") not in combined


def test_codex_project_mcp_retrieval_text_sanitizes_prose_paths_and_secrets(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    fake_pat = "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ123456"
    raw_auth_path = "C:/Users/test/.codex/auth.json"
    _write_memory(
        paths["global"] / "unsafe-prose.md",
        [
            "type: semantic",
            "importance: 9",
            "memory_scope: global",
            f"about: unsafe prose marker {raw_auth_path} {fake_pat}",
        ],
        f"Unsafe prose marker body cites {raw_auth_path} with {fake_pat}.",
    )
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()
    outputs = [
        _tool_fn(mcp, "memory_search")("unsafe prose marker", scope="global", limit=5),
        _tool_fn(mcp, "memory_query")(type="semantic", scope="global", limit=5),
        _tool_fn(mcp, "memory_recall")("unsafe prose marker", scope="global", limit=5),
        _tool_fn(mcp, "memory_live_retrieval_check")(
            current_context="Need unsafe prose marker now.",
            previous_context="Earlier work was unrelated.",
            scope="global",
            force=True,
            limit=5,
        ),
        _tool_fn(mcp, "memory_context_pack")(
            current_context="Need unsafe prose marker now.",
            previous_context="Earlier work was unrelated.",
            scope="global",
            force=True,
            limit=5,
        ),
    ]
    combined = "\n".join(outputs).replace("\\", "/")

    assert "unsafe-prose.md" in combined
    assert "local-path:auth.json" in combined
    assert "<REDACTED:github-pat>" in combined
    assert raw_auth_path not in combined
    assert ".codex/auth.json" not in combined
    assert "ghp_" not in combined


def test_codex_no_persona_mcp_retrieval_fails_closed_without_project_id(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()
    expected = "Codex no-persona MCP surface requires CHIMERA_MEMORY_PROJECT_ID"

    search = _tool_fn(mcp, "memory_search")("Persona-only-secret", limit=5)
    assert expected in search
    assert "Persona-only-secret" not in search

    query = _tool_fn(mcp, "memory_query")(type="procedural", limit=5)
    assert expected in query

    stats = _tool_fn(mcp, "memory_stats")()
    assert expected in stats

    diagnose_stats = _tool_fn(mcp, "memory_diagnose")(mode="stats")
    assert "**Total files:** 1" in diagnose_stats
    assert "global: 1" in diagnose_stats
    assert "project:ChimeraMemory" not in diagnose_stats
    assert "asa" not in diagnose_stats
    assert "Persona-only-secret" not in diagnose_stats

    recall = _tool_fn(mcp, "memory_recall")("Persona-only-secret", limit=5)
    assert expected in recall

    pack = _tool_fn(mcp, "memory_context_pack")(
        current_context="Need Persona-only-secret marker now.",
        previous_context="Earlier work was unrelated.",
        force=True,
        limit=5,
    )
    assert expected in pack

    live = _tool_fn(mcp, "memory_live_retrieval_check")(
        current_context="Need Persona-only-secret marker now.",
        previous_context="Earlier work was unrelated.",
        force=True,
        limit=5,
    )
    assert expected in live

    all_scope = _tool_fn(mcp, "memory_search")("Persona-only-secret", scope="all", limit=5)
    assert "does not allow scope=all" in all_scope

    global_only = _tool_fn(mcp, "memory_search")("Shared global marker", scope="global", limit=5)
    assert "global.md" in global_only
    assert "Persona-only-secret" not in global_only


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
    assert "indexed=True" in written
    assert "file_id=" in written

    target = paths["project"] / "memory" / "procedural" / "codex-desktop-project-write.md"
    content = target.read_text(encoding="utf-8")
    assert "memory_scope: project" in content
    assert "project_id: ChimeraMemory" in content
    assert "Codex Desktop no-persona mode writes authored memory" in content


def test_codex_project_mcp_remember_can_write_global_memory(monkeypatch, tmp_path: Path) -> None:
    paths = _configure_project_env(monkeypatch, tmp_path)
    _seed_memory(paths)
    _patch_fast_memory_indexing(monkeypatch)

    mcp = create_server()
    payload_yaml = """
memory_id: codex-desktop-global-write
memory_type: procedural
importance: 8
author: codex
memory_payload:
  decisions:
    - Codex Desktop no-persona mode can write intentionally global authored memory.
source_refs: []
provenance:
  default_status: user_confirmed
  confidence: 1.0
  requires_review: false
review_status: confirmed
"""

    preview = _tool_fn(mcp, "memory_remember")(
        payload_yaml=payload_yaml,
        scope="global",
        write=False,
        enqueue=False,
    )
    assert "Remember preview only." in preview
    assert "memory/procedural/codex-desktop-global-write.md" in preview

    written = _tool_fn(mcp, "memory_remember")(
        payload_yaml=payload_yaml,
        scope="global",
        write=True,
        enqueue=False,
    )
    assert "Remembered memory/procedural/codex-desktop-global-write.md (global)." in written
    assert "indexed=True" in written
    assert "file_id=" in written

    target = paths["global"] / "memory" / "procedural" / "codex-desktop-global-write.md"
    content = target.read_text(encoding="utf-8")
    assert "memory_scope: global" in content
    assert "project_id:" not in content
    assert "intentionally global authored memory" in content

    query = _tool_fn(mcp, "memory_query")(
        type="procedural",
        scope="global",
        limit=5,
    )
    assert "memory/procedural/codex-desktop-global-write.md" in query
    assert "(global | global)" in query
