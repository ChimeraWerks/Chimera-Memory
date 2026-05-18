"""Snapshot promotion for federated memory layers."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from .memory_auto_capture import resolve_persona_root
from .memory_frontmatter import parse_frontmatter
from .memory_scope import (
    MEMORY_SCOPE_GLOBAL,
    MEMORY_SCOPE_PROJECT,
    current_project_id,
    global_memory_root,
    project_memory_root,
    safe_project_id,
)


IndexFileFunc = Callable[..., bool]
AuditEventFunc = Callable[..., str]

_SOURCE_ROOTS = {"memory", "reading"}
_PROJECT_TARGET_ROOTS = {"memory", "project"}
_VALID_DESTINATION_SCOPES = {MEMORY_SCOPE_PROJECT, MEMORY_SCOPE_GLOBAL}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_slashes(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/")


def _safe_relative_path(value: str, *, field: str) -> tuple[bool, str, str]:
    normalized = _normalize_slashes(value)
    if not normalized:
        return False, "", f"{field} is required"
    path = Path(normalized)
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        return False, "", f"{field} must be a safe relative path"
    if path.suffix.lower() != ".md":
        return False, "", f"{field} must point to a markdown file"
    return True, normalized, ""


def _validate_target_path_for_scope(relative_path: str, destination_scope: str) -> str:
    if destination_scope != MEMORY_SCOPE_PROJECT:
        return ""
    first = relative_path.split("/", 1)[0]
    if first not in _PROJECT_TARGET_ROOTS:
        return "project promotion target_relative_path must start with memory/ or project/"
    return ""


def _resolve_source(personas_dir: Path, persona: str, source_file_path: str) -> dict:
    if not persona.strip():
        return {"ok": False, "error": "persona is required"}
    persona_root = resolve_persona_root(personas_dir, persona)
    if persona_root is None:
        return {"ok": False, "error": f"persona root not found for {persona}"}

    source_text = source_file_path.strip()
    if not source_text:
        return {"ok": False, "error": "source_file_path is required"}

    raw_path = Path(source_text).expanduser()
    candidates: list[Path]
    if raw_path.is_absolute():
        candidates = [raw_path]
    else:
        normalized = Path(_normalize_slashes(source_text))
        candidates = [persona_root / normalized]
        first = normalized.parts[0] if normalized.parts else ""
        if first not in _SOURCE_ROOTS:
            candidates.append(persona_root / "memory" / normalized)

    source_path = next((candidate for candidate in candidates if candidate.exists() and candidate.is_file()), None)
    if source_path is None:
        return {"ok": False, "error": "source file not found"}

    try:
        relative_path = source_path.resolve().relative_to(persona_root.resolve())
    except ValueError:
        return {"ok": False, "error": "source file must be inside the selected persona root"}
    first = relative_path.parts[0] if relative_path.parts else ""
    if first not in _SOURCE_ROOTS:
        return {"ok": False, "error": "source_file_path must be under memory/ or reading/"}

    return {
        "ok": True,
        "persona_root": persona_root,
        "source_path": source_path,
        "source_relative_path": str(relative_path).replace("\\", "/"),
    }


def _default_target_relative(source_relative_path: str) -> str:
    first = source_relative_path.split("/", 1)[0]
    if first in _PROJECT_TARGET_ROOTS:
        return source_relative_path
    return f"memory/{source_relative_path}"


def _destination_root(destination_scope: str, project_id: str) -> dict:
    if destination_scope == MEMORY_SCOPE_GLOBAL:
        return {"ok": True, "root": global_memory_root(), "project_id": None, "index_persona": "global"}

    selected_project_id = safe_project_id(project_id) or current_project_id()
    if not selected_project_id:
        return {"ok": False, "error": "project_id is required for project promotion"}
    root = project_memory_root()
    if root is None:
        return {"ok": False, "error": "CHIMERA_MEMORY_PROJECT_ROOT is required for project promotion"}
    return {
        "ok": True,
        "root": root,
        "project_id": selected_project_id,
        "index_persona": f"project:{selected_project_id}",
    }


def _snapshot_frontmatter(
    frontmatter: dict,
    *,
    destination_scope: str,
    project_id: str | None,
    source_persona: str,
    source_relative_path: str,
    source_hash: str,
    approved_by: str,
    actor: str,
) -> dict:
    snapshot = dict(frontmatter)
    snapshot["memory_scope"] = destination_scope
    if destination_scope == MEMORY_SCOPE_PROJECT:
        snapshot["project_id"] = project_id
    else:
        snapshot.pop("project_id", None)
        snapshot.pop("project", None)
    snapshot["promoted_from"] = {
        "persona": source_persona,
        "path": source_relative_path,
        "promoted_at": _utc_now(),
        "source_content_hash": source_hash,
        "source_memory_scope": str(frontmatter.get("memory_scope") or "persona"),
    }
    snapshot["promotion"] = {
        "approved_by": approved_by,
        "promoted_by": actor,
        "target_scope": destination_scope,
    }
    return snapshot


def _render_markdown(frontmatter: dict, body: str) -> str:
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{yaml_text}\n---\n{body.strip()}\n"


def memory_promote_snapshot(
    conn,
    personas_dir: Path,
    *,
    persona: str,
    source_file_path: str,
    destination_scope: str = MEMORY_SCOPE_PROJECT,
    project_id: str = "",
    target_relative_path: str = "",
    write: bool = False,
    approved_by: str = "",
    actor: str = "agent",
    index_file_func: IndexFileFunc,
    record_audit_event_func: AuditEventFunc,
) -> dict:
    """Preview or write a persona-memory snapshot into project/global scope."""
    selected_persona = persona.strip()
    selected_scope = str(destination_scope or MEMORY_SCOPE_PROJECT).strip().lower().replace("-", "_")
    if selected_scope not in _VALID_DESTINATION_SCOPES:
        return {"ok": False, "error": "destination_scope must be project or global"}

    source_result = _resolve_source(personas_dir, selected_persona, source_file_path)
    if not source_result.get("ok"):
        return source_result
    source_path = Path(source_result["source_path"])
    source_relative_path = str(source_result["source_relative_path"])
    source_content = source_path.read_text(encoding="utf-8", errors="replace")
    source_hash = hashlib.sha256(source_content.encode("utf-8")).hexdigest()
    frontmatter, body = parse_frontmatter(source_content)
    if not isinstance(frontmatter, dict):
        frontmatter = {}

    root_result = _destination_root(selected_scope, project_id)
    if not root_result.get("ok"):
        return root_result
    root = Path(root_result["root"])
    selected_project_id = root_result.get("project_id")
    index_persona = str(root_result["index_persona"])

    target_rel_input = target_relative_path.strip() or _default_target_relative(source_relative_path)
    target_ok, target_rel, target_error = _safe_relative_path(target_rel_input, field="target_relative_path")
    if not target_ok:
        return {"ok": False, "error": target_error}
    target_scope_error = _validate_target_path_for_scope(target_rel, selected_scope)
    if target_scope_error:
        return {"ok": False, "error": target_scope_error}
    target_path = root / Path(target_rel)

    audit_payload = {
        "source_persona": selected_persona,
        "source_relative_path": source_relative_path,
        "source_content_hash": source_hash,
        "destination_scope": selected_scope,
        "project_id": selected_project_id,
        "target_relative_path": target_rel,
        "target_path": str(target_path).replace("\\", "/"),
        "write": bool(write),
        "approved_by": approved_by.strip(),
    }

    if target_path.exists():
        record_audit_event_func(
            conn,
            "memory_promote_snapshot_rejected",
            persona=selected_persona,
            target_kind="memory_file",
            target_id=target_rel,
            payload={**audit_payload, "reason": "duplicate_target"},
            actor=actor,
        )
        return {"ok": False, "error": "duplicate target exists; choose a new target_relative_path or merge explicitly"}

    if write and not approved_by.strip():
        record_audit_event_func(
            conn,
            "memory_promote_snapshot_approval_required",
            persona=selected_persona,
            target_kind="memory_file",
            target_id=target_rel,
            payload=audit_payload,
            actor=actor,
        )
        return {"ok": False, "error": "approved_by is required when write=true"}

    snapshot_fm = _snapshot_frontmatter(
        frontmatter,
        destination_scope=selected_scope,
        project_id=str(selected_project_id) if selected_project_id else None,
        source_persona=selected_persona,
        source_relative_path=source_relative_path,
        source_hash=source_hash,
        approved_by=approved_by.strip(),
        actor=actor,
    )
    snapshot_content = _render_markdown(snapshot_fm, body)

    preview = {
        "ok": True,
        "written": False,
        "destination_scope": selected_scope,
        "project_id": selected_project_id,
        "source_persona": selected_persona,
        "source_relative_path": source_relative_path,
        "source_path": str(source_path).replace("\\", "/"),
        "source_content_hash": source_hash,
        "target_relative_path": target_rel,
        "target_path": str(target_path).replace("\\", "/"),
        "index_persona": index_persona,
        "snapshot_frontmatter": snapshot_fm,
        "body_preview": body[:1200],
    }

    if not write:
        record_audit_event_func(
            conn,
            "memory_promote_snapshot_planned",
            persona=selected_persona,
            target_kind="memory_file",
            target_id=target_rel,
            payload=audit_payload,
            actor=actor,
        )
        return preview

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(snapshot_content, encoding="utf-8")
    indexed = index_file_func(conn, index_persona, target_rel, target_path)
    row = conn.execute(
        "SELECT id FROM memory_files WHERE path = ?",
        (str(target_path).replace("\\", "/"),),
    ).fetchone()
    file_id = row[0] if row else None
    audit_payload.update({"indexed": indexed, "file_id": file_id})
    record_audit_event_func(
        conn,
        "memory_promote_snapshot_written",
        persona=selected_persona,
        target_kind="memory_file",
        target_id=str(file_id or target_rel),
        payload=audit_payload,
        actor=actor,
        commit=False,
    )
    conn.commit()

    preview.update({"written": True, "indexed": indexed, "file_id": file_id})
    return preview
