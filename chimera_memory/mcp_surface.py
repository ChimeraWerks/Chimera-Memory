"""MCP tool-surface policy for Chimera Memory."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MCP_SURFACE_ENV = "CHIMERA_MEMORY_MCP_SURFACE"

FULL_SURFACES = frozenset({"", "all", "full", "legacy", "operator", "admin"})

PERSONA_MEMORY_TOOLS = frozenset(
    {
        "memory_recall",
        "memory_remember",
        "memory_review",
        "memory_diagnose",
    }
)

PERSONA_TRANSCRIPT_TOOLS = frozenset(
    {
        "discord_recall",
        "discord_recall_index",
        "discord_detail",
        "semantic_search",
        "session_list",
    }
)

PERSONA_TOOLS = PERSONA_MEMORY_TOOLS | PERSONA_TRANSCRIPT_TOOLS


def normalize_mcp_surface(value: object) -> str:
    """Normalize a configured MCP surface name."""
    surface = str(value or "").strip().lower().replace("-", "_")
    if surface in FULL_SURFACES:
        return "full"
    if surface in {"persona", "personas", "normal"}:
        return "persona"
    if surface in {"persona_memory", "memory", "memory_only"}:
        return "persona_memory"
    return "full"


def resolve_mcp_surface(config: Mapping[str, Any] | None, env: Mapping[str, str] | None) -> str:
    """Resolve MCP surface policy with env overriding config."""
    env = env or {}
    configured = env.get(MCP_SURFACE_ENV)
    if configured is None and config is not None:
        configured = config.get("mcp_surface")
    return normalize_mcp_surface(configured)


def allowed_tools_for_surface(surface: object) -> frozenset[str] | None:
    """Return allowed tool names, or None for the full legacy surface."""
    normalized = normalize_mcp_surface(surface)
    if normalized == "persona":
        return PERSONA_TOOLS
    if normalized == "persona_memory":
        return PERSONA_MEMORY_TOOLS
    return None


def tool_allowed(tool_name: str, surface: object) -> bool:
    """Return whether a tool should be registered for this surface."""
    allowed = allowed_tools_for_surface(surface)
    return allowed is None or tool_name in allowed
