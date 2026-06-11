"""Scope policy for curated memory retrieval.

CM keeps physical storage simple, but retrieval policy needs to be explicit:
persona-private memory is local, project memory is isolated by project id, and
global memory is safe to include everywhere.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional


MEMORY_SCOPE_PERSONA = "persona"
MEMORY_SCOPE_PROJECT = "project"
MEMORY_SCOPE_GLOBAL = "global"
MEMORY_SCOPE_AUTO = "auto"
MEMORY_SCOPE_ALL = "all"

VALID_MEMORY_SCOPES = {
    MEMORY_SCOPE_PERSONA,
    MEMORY_SCOPE_PROJECT,
    MEMORY_SCOPE_GLOBAL,
}

QUERY_SCOPE_MODES = VALID_MEMORY_SCOPES | {MEMORY_SCOPE_AUTO, MEMORY_SCOPE_ALL}
GLOBAL_PERSONA_NAMES = {"global", "shared"}


def normalize_memory_scope(value: object, *, default: str = MEMORY_SCOPE_PERSONA) -> str:
    text = str(value or "").strip().lower()
    if text in VALID_MEMORY_SCOPES:
        return text
    return default


def project_id_from_persona(persona: str | None) -> str | None:
    text = str(persona or "").strip()
    if text.lower().startswith("project:"):
        return text.split(":", 1)[1].strip() or None
    return None


def safe_project_id(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip(".-")
    return clean or None


def current_project_id() -> str | None:
    explicit = os.environ.get("CHIMERA_MEMORY_PROJECT_ID", "").strip()
    if explicit:
        return safe_project_id(explicit)
    root = _single_project_memory_root()
    if root is not None:
        return _project_id_from_root(root)
    return None


def global_memory_root() -> Path:
    override = os.environ.get("CHIMERA_MEMORY_GLOBAL_ROOT", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".chimera-memory" / "global-memory"


def global_root_filter_values(global_root: str | Path | None) -> tuple[str, str] | None:
    """Return normalized exact/prefix values for active-root global SQL filters."""
    text = str(global_root or "").strip()
    if not text:
        return None
    try:
        root = Path(os.path.expandvars(os.path.expanduser(text))).resolve(strict=False)
    except OSError:
        return None
    normalized = str(root).replace("\\", "/").rstrip("/").lower()
    if not normalized:
        return None
    return normalized, normalized + "/%"


def project_memory_root(project_id: object = "") -> Path | None:
    selected_project_id = safe_project_id(project_id)
    if selected_project_id:
        mapped = _project_memory_root_map().get(selected_project_id)
        if mapped is not None:
            return mapped

    root = _single_project_memory_root()
    if root is None:
        return None
    if not selected_project_id:
        return root
    explicit = safe_project_id(os.environ.get("CHIMERA_MEMORY_PROJECT_ID", ""))
    if explicit == selected_project_id:
        return root
    inferred = _project_id_from_root(root)
    return root if inferred == selected_project_id else None


def workspace_root_from_project_root(root: object) -> Path | None:
    text = str(root or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve(strict=False)
    if path.name in {"memory", "project"} and path.parent.name == ".chimera-memory":
        return path.parent.parent
    if path.name == ".chimera-memory":
        return path.parent
    return path


def project_workspace_root(project_id: object = "") -> Path | None:
    root = project_memory_root(project_id)
    return workspace_root_from_project_root(root) if root is not None else None


def project_memory_roots() -> tuple[tuple[str, Path], ...]:
    roots: dict[str, Path] = {}
    root = _single_project_memory_root()
    if root is not None:
        project_id = safe_project_id(os.environ.get("CHIMERA_MEMORY_PROJECT_ID", "")) or _project_id_from_root(root)
        if project_id:
            roots[project_id] = root
    roots.update(_project_memory_root_map())
    return tuple(sorted(roots.items()))


def _single_project_memory_root() -> Path | None:
    override = os.environ.get("CHIMERA_MEMORY_PROJECT_ROOT", "").strip()
    if not override:
        return None
    return Path(override).expanduser()


def _project_memory_root_map() -> dict[str, Path]:
    raw = os.environ.get("CHIMERA_MEMORY_PROJECT_ROOTS", "").strip()
    if not raw:
        return {}

    items: list[tuple[object, object]] = []
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            items = list(parsed.items())
    else:
        for chunk in raw.split(";"):
            if "=" not in chunk:
                continue
            project_id, root = chunk.split("=", 1)
            items.append((project_id, root))

    result: dict[str, Path] = {}
    for project_id, root in items:
        safe_id = safe_project_id(project_id)
        root_text = str(root or "").strip()
        if safe_id and root_text:
            result[safe_id] = Path(root_text).expanduser()
    return result


def _project_id_from_root(root: Path) -> str | None:
    if root.name == "memory" and root.parent.name:
        return safe_project_id(root.parent.parent.name if root.parent.name == ".chimera-memory" else root.parent.name)
    if root.name == ".chimera-memory" and root.parent.name:
        return safe_project_id(root.parent.name)
    return safe_project_id(root.name)


def infer_memory_scope(
    persona: str,
    frontmatter: dict,
    *,
    relative_path: str = "",
) -> tuple[str, str | None]:
    explicit_scope = str(frontmatter.get("memory_scope") or "").strip().lower()
    persona_project_id = project_id_from_persona(persona)
    default = MEMORY_SCOPE_PROJECT if persona_project_id else MEMORY_SCOPE_PERSONA
    if persona.strip().lower() in GLOBAL_PERSONA_NAMES:
        default = MEMORY_SCOPE_GLOBAL
    scope = normalize_memory_scope(explicit_scope, default=default)

    raw_project_id = (
        frontmatter.get("project_id")
        or frontmatter.get("project")
        or persona_project_id
    )
    project_id = safe_project_id(raw_project_id) if scope == MEMORY_SCOPE_PROJECT else None
    return scope, project_id


def scope_filter_sql(
    *,
    table_alias: str = "f",
    persona: Optional[str] = None,
    project_id: Optional[str] = None,
    scope: str = MEMORY_SCOPE_AUTO,
) -> tuple[str, list[object], dict[str, object]]:
    """Return SQL and params for default CM retrieval scope.

    `auto` with a persona means persona-local + current project + global.
    `auto` without any persona/project remains unscoped for operator/admin calls.
    """
    mode = str(scope or MEMORY_SCOPE_AUTO).strip().lower()
    if mode not in QUERY_SCOPE_MODES:
        mode = MEMORY_SCOPE_AUTO

    selected_project_id = safe_project_id(project_id) or current_project_id()
    policy = {
        "scope": mode,
        "persona": persona,
        "project_id": selected_project_id,
        "includes": [],
    }

    if mode == MEMORY_SCOPE_ALL or (mode == MEMORY_SCOPE_AUTO and not persona and not selected_project_id):
        policy["includes"] = ["all"]
        return "", [], policy

    conditions: list[str] = []
    params: list[object] = []
    prefix = f"{table_alias}." if table_alias else ""

    if mode == MEMORY_SCOPE_PERSONA:
        if not persona:
            return "1=0", [], policy
        policy["includes"] = ["persona"]
        return f"{prefix}memory_scope = ? AND {prefix}persona = ?", [MEMORY_SCOPE_PERSONA, persona], policy

    if mode == MEMORY_SCOPE_PROJECT:
        if not selected_project_id:
            return "1=0", [], policy
        policy["includes"] = ["project"]
        return (
            f"{prefix}memory_scope = ? AND {prefix}project_id = ?",
            [MEMORY_SCOPE_PROJECT, selected_project_id],
            policy,
        )

    if mode == MEMORY_SCOPE_GLOBAL:
        policy["includes"] = ["global"]
        return f"{prefix}memory_scope = ?", [MEMORY_SCOPE_GLOBAL], policy

    # auto
    conditions.append(f"{prefix}memory_scope = ?")
    params.append(MEMORY_SCOPE_GLOBAL)
    policy["includes"].append("global")

    if persona:
        conditions.append(f"({prefix}memory_scope = ? AND {prefix}persona = ?)")
        params.extend([MEMORY_SCOPE_PERSONA, persona])
        policy["includes"].append("persona")

    if selected_project_id:
        conditions.append(f"({prefix}memory_scope = ? AND {prefix}project_id = ?)")
        params.extend([MEMORY_SCOPE_PROJECT, selected_project_id])
        policy["includes"].append("project")

    return "(" + " OR ".join(conditions) + ")", params, policy
