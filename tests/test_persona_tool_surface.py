import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _server_functions() -> set[str]:
    tree = ast.parse((ROOT / "chimera_memory" / "server.py").read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


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
