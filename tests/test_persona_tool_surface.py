import ast
from pathlib import Path

import chimera_memory.config as config
from chimera_memory.mcp_surface import normalize_mcp_surface, tool_allowed
from chimera_memory.server import create_server


ROOT = Path(__file__).resolve().parents[1]


def _server_functions() -> set[str]:
    tree = ast.parse((ROOT / "chimera_memory" / "server.py").read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _tool_names(server) -> set[str]:
    return {tool.name for tool in server._tool_manager.list_tools()}


def _isolate_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")


def test_persona_facing_alias_tools_are_registered_additively() -> None:
    functions = _server_functions()

    assert {"memory_recall", "memory_remember", "memory_review", "memory_diagnose"} <= functions

    # Compatibility tools stay registered until a later MCP filtering slice.
    assert {"memory_authored_writeback", "memory_review_pending", "memory_review_action"} <= functions


def test_promote_snapshot_is_documented_as_v2_not_implemented() -> None:
    functions = _server_functions()
    doc = (ROOT / "docs" / "FEDERATED_MEMORY_SCOPE.md").read_text(encoding="utf-8")
    server_source = (ROOT / "chimera_memory" / "server.py").read_text(encoding="utf-8")

    assert "memory_promote_snapshot" not in functions
    assert "Planned v2: `memory_promote_snapshot`" in doc
    assert "memory_promote_snapshot - planned v2" in server_source


def test_memory_diagnose_owns_zone_and_trace_inspection() -> None:
    server_source = (ROOT / "chimera_memory" / "server.py").read_text(encoding="utf-8")

    for mode in [
        "tool_surface",
        "zones",
        "traces",
        "trace_analyze",
        "provider_plan",
        "consolidation",
        "whereami",
    ]:
        assert mode in server_source


def test_default_mcp_surface_keeps_legacy_tools_registered(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)

    tools = _tool_names(create_server())

    assert {"memory_recall", "memory_remember", "memory_review", "memory_diagnose"} <= tools
    assert {"memory_authored_writeback", "memory_import_chatgpt_export", "transcript_backfill"} <= tools


def test_persona_mcp_surface_filters_admin_tools(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "persona")

    tools = _tool_names(create_server())

    assert {
        "memory_recall",
        "memory_remember",
        "memory_review",
        "memory_diagnose",
        "discord_recall_index",
        "discord_detail",
    } <= tools
    assert "memory_authored_writeback" not in tools
    assert "memory_import_chatgpt_export" not in tools
    assert "memory_stats" not in tools
    assert "transcript_backfill" not in tools
    assert len(tools) <= 10


def test_mcp_surface_policy_normalizes_unknown_to_full() -> None:
    assert normalize_mcp_surface("persona") == "persona"
    assert normalize_mcp_surface("memory-only") == "persona_memory"
    assert normalize_mcp_surface("wat") == "full"
    assert tool_allowed("memory_import_chatgpt_export", "wat") is True
    assert tool_allowed("memory_import_chatgpt_export", "persona") is False
