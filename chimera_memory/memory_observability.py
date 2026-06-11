"""Recall trace and audit-event helpers for ChimeraMemory."""

from __future__ import annotations

import json
import sqlite3
import uuid

from .memory_display import (
    is_safe_relative_path_text,
    local_path_fingerprint,
    looks_like_local_path_reference,
    redact_local_path_references,
    safe_local_path_reference_display,
    safe_memory_relative_path_display,
    safe_memory_text_display,
)
from .sanitizer import sanitize_content


def _json_text(value: object) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, default=str)


def _json_object(text: str | None) -> object:
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def record_memory_audit_event(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    persona: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    trace_id: str | None = None,
    payload: object | None = None,
    actor: str = "system",
    commit: bool = True,
) -> str:
    """Record a memory audit event and return its event id."""
    event_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO memory_audit_events (
            event_id, event_type, actor, persona, target_kind,
            target_id, trace_id, payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            event_type,
            actor,
            persona,
            target_kind or "",
            target_id or "",
            trace_id or "",
            _json_text(payload),
        ),
    )
    if commit:
        conn.commit()
    return event_id


def record_memory_recall_trace(
    conn: sqlite3.Connection,
    *,
    tool_name: str,
    query_text: str,
    persona: str | None,
    requested_limit: int,
    results: list[dict],
    result_count: int | None = None,
    request_payload: object | None = None,
    response_policy: object | None = None,
    runtime_name: str | None = None,
    runtime_version: str | None = None,
    task_id: str | None = None,
    flow_id: str | None = None,
    channel_kind: str | None = None,
    channel_id: str | None = None,
) -> str:
    """Record a recall request and its returned items."""
    trace_id = str(uuid.uuid4())
    returned_count = len(results)
    selected_result_count = max(returned_count, _safe_int(result_count, returned_count))
    conn.execute(
        """
        INSERT INTO memory_recall_traces (
            trace_id, tool_name, persona, query_text, requested_limit,
            result_count, returned_count, runtime_name, runtime_version,
            task_id, flow_id, channel_kind, channel_id, request_payload,
            response_policy
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trace_id,
            tool_name,
            persona,
            query_text,
            requested_limit,
            selected_result_count,
            returned_count,
            runtime_name or "",
            runtime_version or "",
            task_id or "",
            flow_id or "",
            channel_kind or "",
            channel_id or "",
            _json_text(request_payload),
            _json_text(response_policy),
        ),
    )

    for rank, result in enumerate(results, start=1):
        target_kind = str(result.get("target_kind") or "memory_file")
        target_id = str(result.get("target_id") or "").strip()
        result_metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        metadata = {
            "importance": result.get("importance"),
            "status": result.get("status"),
            "about": result.get("about"),
            "snippet_chars": len(str(result.get("snippet") or "")),
            **result_metadata,
        }
        file_id = result.get("id")
        db_file_id = file_id if target_kind == "memory_file" and isinstance(file_id, int) else None
        conn.execute(
            """
            INSERT INTO memory_recall_items (
                trace_id, file_id, rank, similarity, ranking_score, returned,
                used, ignored_reason, path, persona, relative_path, fm_type,
                metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                db_file_id,
                rank,
                result.get("similarity"),
                result.get("ranking_score") or result.get("similarity"),
                1,
                0,
                "",
                result.get("path") or "",
                result.get("persona") or "",
                result.get("relative_path") or "",
                result.get("type") or "",
                _json_text(metadata),
            ),
        )
        record_memory_audit_event(
            conn,
            "memory_returned",
            persona=result.get("persona") or persona,
            target_kind=target_kind,
            target_id=target_id or str(file_id or result.get("path") or ""),
            trace_id=trace_id,
            payload={"rank": rank, "tool_name": tool_name},
            commit=False,
        )

    record_memory_audit_event(
        conn,
        "recall_requested",
        persona=persona,
        target_kind="memory_recall",
        target_id=trace_id,
        trace_id=trace_id,
        payload={
            "tool_name": tool_name,
            "requested_limit": requested_limit,
            "result_count": selected_result_count,
            "returned_count": returned_count,
        },
        commit=False,
    )
    conn.commit()
    return trace_id


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_trace_path(value: object, *, fallback_path: object = "") -> tuple[str, str]:
    text = str(value or "").strip()
    fallback = str(fallback_path or "").strip()
    fingerprint_source = fallback or text
    fingerprint = local_path_fingerprint(fingerprint_source)
    return safe_memory_relative_path_display(text, fallback_path=fallback), fingerprint


_AUDIT_PATH_KEYS = {
    "path",
    "paths",
    "root",
    "roots",
    "dir",
    "dirs",
    "directory",
    "directories",
    "file",
    "files",
    "db",
    "output_dir",
    "import_path",
    "vault_path",
    "export_path",
    "source_path",
    "target_path",
    "written_files",
}


_AUDIT_REDACT_KEYS = {
    "access_token",
    "api_key",
    "args",
    "argv",
    "auth",
    "auth_json",
    "body",
    "card_text",
    "command",
    "command_preview",
    "content",
    "context_block",
    "credential",
    "credential_ref",
    "credential_value",
    "current_context",
    "id_token",
    "memory_body",
    "password",
    "previous_context",
    "prompt",
    "prompt_text",
    "provider_stderr",
    "provider_stdout",
    "query_text",
    "raw_command",
    "raw_output",
    "raw_prompt",
    "raw_stderr",
    "raw_stdout",
    "refresh_token",
    "secret",
    "session_text",
    "stderr",
    "stdout",
    "token",
    "tokens",
    "wrapped_content",
}


_TRACE_QUERY_TEXT_OMIT_TOOLS = {
    "codex_transcript_context",
    "memory_context_pack",
    "memory_live_retrieval",
}


def _audit_key_is_path_like(key: object) -> bool:
    text = str(key or "").strip().lower()
    if text in _AUDIT_PATH_KEYS:
        return True
    return text.endswith((
        "_path",
        "_paths",
        "_root",
        "_roots",
        "_dir",
        "_dirs",
        "_directory",
        "_directories",
        "_file",
        "_files",
    ))


def _audit_key_is_sensitive(key: object) -> bool:
    text = str(key or "").strip().lower()
    if text in _AUDIT_REDACT_KEYS:
        return True
    return text.endswith((
        "_api_key",
        "_body",
        "_command",
        "_content",
        "_credential",
        "_password",
        "_prompt",
        "_secret",
        "_stderr",
        "_stdout",
        "_token",
    ))


def _redacted_audit_value(value: object, *, key: object) -> dict[str, object]:
    if isinstance(value, dict):
        kind = "object"
        size = len(value)
    elif isinstance(value, (list, tuple)):
        kind = "array"
        size = len(value)
    elif isinstance(value, str):
        kind = "string"
        size = len(value)
    elif value is None:
        kind = "null"
        size = 0
    else:
        kind = type(value).__name__
        size = 1
    return {
        "redacted": True,
        "reason": "sensitive_audit_field",
        "field": str(key or ""),
        "value_type": kind,
        "size": size,
    }


def _sanitize_audit_string(text: str) -> str:
    sanitized = sanitize_content(text) or ""
    return redact_local_path_references(sanitized)


def _safe_audit_text(value: object, *, path_like: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if looks_like_local_path_reference(text):
        return safe_local_path_reference_display(text)
    if path_like and ("://" in text or ":" in text):
        return _sanitize_audit_string(text)
    if path_like and not is_safe_relative_path_text(text):
        return safe_memory_relative_path_display(text)
    return _sanitize_audit_string(text)


def _safe_audit_payload(value: object, *, path_like: bool = False) -> object:
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            if _audit_key_is_sensitive(key):
                result[str(key)] = _redacted_audit_value(item, key=key)
            else:
                result[str(key)] = _safe_audit_payload(item, path_like=path_like or _audit_key_is_path_like(key))
        return result
    if isinstance(value, list):
        return [_safe_audit_payload(item, path_like=path_like) for item in value]
    if isinstance(value, tuple):
        return [_safe_audit_payload(item, path_like=path_like) for item in value]
    if isinstance(value, str):
        return _safe_audit_text(value, path_like=path_like)
    return value


def _safe_recall_trace_query_text(tool_name: object, query_text: object) -> str:
    text = str(query_text or "")
    if not text:
        return ""
    if str(tool_name or "").strip() in _TRACE_QUERY_TEXT_OMIT_TOOLS:
        return f"[omitted: {len(text)} chars of context query text]"
    return safe_memory_text_display(text)


def memory_recall_trace_query(
    conn: sqlite3.Connection,
    *,
    persona: str | None = None,
    tool_name: str | None = None,
    limit: int = 20,
    include_items: bool = False,
) -> list[dict]:
    """Query recent recall traces."""
    conditions, params = [], []
    if persona:
        conditions.append("persona = ?")
        params.append(persona)
    if tool_name:
        conditions.append("tool_name = ?")
        params.append(tool_name)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"""
        SELECT trace_id, created_at, tool_name, persona, query_text,
               requested_limit, result_count, returned_count, request_payload,
               response_policy
        FROM memory_recall_traces
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        params + [max(0, min(limit, 200))],
    ).fetchall()

    traces = []
    for row in rows:
        trace = {
            "trace_id": row[0],
            "created_at": row[1],
            "tool_name": row[2],
            "persona": row[3],
            "query_text": _safe_recall_trace_query_text(row[2], row[4]),
            "requested_limit": row[5],
            "result_count": row[6],
            "returned_count": row[7],
            "request_payload": _safe_audit_payload(_json_object(row[8])),
            "response_policy": _safe_audit_payload(_json_object(row[9])),
        }
        if include_items:
            item_rows = conn.execute(
                """
                SELECT rank, similarity, ranking_score, returned, used,
                       ignored_reason, path, persona, relative_path, fm_type,
                       metadata
                FROM memory_recall_items
                WHERE trace_id = ?
                ORDER BY rank ASC
                """,
                (row[0],),
            ).fetchall()
            trace_items = []
            for item in item_rows:
                safe_path, path_fingerprint = _safe_trace_path(item[6])
                safe_relative_path, relative_fingerprint = _safe_trace_path(item[8], fallback_path=item[6])
                trace_item = {
                    "rank": item[0],
                    "similarity": item[1],
                    "ranking_score": item[2],
                    "returned": bool(item[3]),
                    "used": bool(item[4]),
                    "ignored_reason": _safe_audit_text(item[5]),
                    "path": safe_path,
                    "path_fingerprint": path_fingerprint or relative_fingerprint,
                    "persona": item[7],
                    "relative_path": safe_relative_path,
                    "type": item[9],
                    "metadata": _safe_audit_payload(_json_object(item[10])),
                }
                trace_items.append(trace_item)
            trace["items"] = trace_items
        traces.append(trace)
    return traces


def memory_audit_query(
    conn: sqlite3.Connection,
    *,
    event_type: str | None = None,
    persona: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Query recent memory audit events."""
    conditions, params = [], []
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if persona:
        conditions.append("persona = ?")
        params.append(persona)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"""
        SELECT event_id, created_at, event_type, actor, persona,
               target_kind, target_id, trace_id, payload
        FROM memory_audit_events
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        params + [max(0, min(limit, 500))],
    ).fetchall()
    events = []
    for row in rows:
        raw_target_id = row[6]
        target_id = _safe_audit_text(raw_target_id, path_like=True)
        target_fingerprint = (
            local_path_fingerprint(raw_target_id)
            if looks_like_local_path_reference(raw_target_id)
            else ""
        )
        event = {
            "event_id": row[0],
            "created_at": row[1],
            "event_type": row[2],
            "actor": row[3],
            "persona": row[4],
            "target_kind": row[5],
            "target_id": target_id,
            "trace_id": row[7],
            "payload": _safe_audit_payload(_json_object(row[8])),
        }
        if target_fingerprint:
            event["target_fingerprint"] = target_fingerprint
        events.append(event)
    return events
