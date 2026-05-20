"""SQLite job queue helpers for memory-enhancement sidecar work."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .memory_enhancement import (
    build_authored_memory_enrichment_request,
    build_memory_enhancement_request,
    normalize_authored_memory_writeback,
    normalize_memory_enhancement_response,
)
from .memory_entities import apply_enhancement_entities
from .memory_frontmatter import parse_frontmatter
from .memory_observability import _json_object, _json_text, record_memory_audit_event
from .memory_provider_governor import provider_governor_check, provider_usage_record

ENHANCEMENT_JOB_STATUSES = {"pending", "running", "succeeded", "failed", "skipped"}
WORKER_HEARTBEAT_STATUSES = {"idle", "running", "stopping", "failed"}
WORKER_CAPABILITIES = {"enhancement"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clean_worker_text(value: object, *, max_chars: int = 120) -> str:
    return str(value or "").strip()[:max_chars]


def _diagnostic_int(mapping: dict | None, *keys: str) -> int:
    source = mapping if isinstance(mapping, dict) else {}
    for key in keys:
        try:
            value = int(source.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            return max(0, value)
    return 0


def _find_memory_file_for_enhancement(conn: sqlite3.Connection, file_path: str):
    path = file_path.replace("\\", "/").strip()
    return conn.execute(
        """
        SELECT id, path, persona, relative_path, content_fingerprint
        FROM memory_files
        WHERE path = ? OR relative_path = ? OR path LIKE ?
        ORDER BY CASE
            WHEN path = ? THEN 0
            WHEN relative_path = ? THEN 1
            ELSE 2
        END
        LIMIT 1
        """,
        (path, path, f"%{path}%", path, path),
    ).fetchone()


def _enhancement_job_to_dict(row: sqlite3.Row | tuple | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row[0],
        "job_id": row[1],
        "created_at": row[2],
        "updated_at": row[3],
        "status": row[4],
        "persona": row[5],
        "file_id": row[6],
        "path": row[7],
        "content_fingerprint": row[8],
        "requested_provider": row[9],
        "requested_model": row[10],
        "actual_provider": row[11],
        "actual_model": row[12],
        "request_payload": _json_object(row[13]),
        "result_payload": _json_object(row[14]),
        "error": row[15],
        "attempt_count": row[16],
        "locked_at": row[17],
        "locked_by_worker": row[18] if len(row) > 18 else "",
    }


def _select_enhancement_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT id, job_id, created_at, updated_at, status, persona, file_id,
               path, content_fingerprint, requested_provider, requested_model,
               actual_provider, actual_model, request_payload, result_payload,
               error, attempt_count, locked_at, locked_by_worker
        FROM memory_enhancement_jobs
        WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    return _enhancement_job_to_dict(row)


def memory_enhancement_enqueue(
    conn: sqlite3.Connection,
    *,
    file_path: str,
    requested_provider: str = "",
    requested_model: str = "",
    force: bool = False,
) -> dict:
    """Queue a memory file for sidecar metadata enhancement."""
    memory_row = _find_memory_file_for_enhancement(conn, file_path)
    if memory_row is None:
        return {"ok": False, "error": "memory file not found", "file_path": file_path}

    existing = conn.execute(
        """
        SELECT job_id FROM memory_enhancement_jobs
        WHERE file_id = ? AND status IN ('pending', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (memory_row[0],),
    ).fetchone()
    if existing and not force:
        return {"ok": True, "enqueued": False, "job": _select_enhancement_job(conn, existing[0])}
    if existing and force:
        conn.execute(
            """
            UPDATE memory_enhancement_jobs
               SET status = 'skipped',
                   error = 'superseded by forced enqueue',
                   locked_at = NULL
             WHERE job_id = ?
            """,
            (existing[0],),
        )

    disk_path = Path(memory_row[1])
    try:
        raw_content = disk_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"ok": False, "error": "memory file not readable", "file_path": str(memory_row[1])}

    frontmatter, body = parse_frontmatter(raw_content)
    request_payload = build_memory_enhancement_request(
        content=body,
        persona=str(memory_row[2] or ""),
        source_path=str(memory_row[3] or memory_row[1]),
        existing_frontmatter=frontmatter,
    )
    job_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO memory_enhancement_jobs (
            job_id, status, persona, file_id, path, content_fingerprint,
            requested_provider, requested_model, request_payload
        ) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            memory_row[2],
            memory_row[0],
            memory_row[1],
            memory_row[4],
            requested_provider or "",
            requested_model or "",
            _json_text(request_payload),
        ),
    )
    record_memory_audit_event(
        conn,
        "memory_enhancement_enqueued",
        persona=memory_row[2],
        target_kind="memory_file",
        target_id=str(memory_row[0]),
        payload={"job_id": job_id, "path": memory_row[1]},
        commit=False,
    )
    conn.commit()
    return {"ok": True, "enqueued": True, "job": _select_enhancement_job(conn, job_id)}


def _authored_payload_fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def memory_enhancement_enqueue_authored(
    conn: sqlite3.Connection,
    *,
    persona: str,
    memory_payload: dict,
    provenance: dict | None = None,
    source_ref: str = "",
    file_id: int | None = None,
    requested_provider: str = "",
    requested_model: str = "",
) -> dict:
    """Queue enrichment for a caller-authored structured memory payload."""
    if file_id:
        existing = conn.execute(
            """
            SELECT job_id FROM memory_enhancement_jobs
            WHERE file_id = ? AND status IN ('pending', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (file_id,),
        ).fetchone()
        if existing:
            return {"ok": True, "enqueued": False, "job": _select_enhancement_job(conn, existing[0])}
    try:
        request_payload = build_authored_memory_enrichment_request(
            memory_payload=memory_payload,
            persona=persona,
            source_ref=source_ref,
            provenance=provenance,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "source_ref": source_ref}

    job_id = str(uuid.uuid4())
    fingerprint = _authored_payload_fingerprint(
        {
            "memory_payload": request_payload.get("memory_payload") or {},
            "provenance": request_payload.get("provenance") or {},
        }
    )
    path = source_ref or str(request_payload["request_id"])
    conn.execute(
        """
        INSERT INTO memory_enhancement_jobs (
            job_id, status, persona, file_id, path, content_fingerprint,
            requested_provider, requested_model, request_payload
        ) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            request_payload.get("persona"),
            file_id,
            path,
            fingerprint,
            requested_provider or "",
            requested_model or "",
            _json_text(request_payload),
        ),
    )
    record_memory_audit_event(
        conn,
        "memory_enhancement_authored_enqueued",
        persona=request_payload.get("persona"),
        target_kind="authored_memory_payload",
        target_id=job_id,
        payload={
            "job_id": job_id,
            "source_ref": source_ref,
            "schema_version": request_payload["schema_version"],
        },
        commit=False,
    )
    conn.commit()
    return {"ok": True, "enqueued": True, "job": _select_enhancement_job(conn, job_id)}


def memory_enhancement_claim_next(
    conn: sqlite3.Connection,
    *,
    persona: str | None = None,
) -> dict | None:
    """Claim the next pending sidecar enhancement job."""
    conditions = ["status = 'pending'"]
    params: list[object] = []
    if persona:
        conditions.append("persona = ?")
        params.append(persona)
    row = conn.execute(
        f"""
        SELECT job_id, persona FROM memory_enhancement_jobs
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at ASC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    job_id = row[0]
    now = _utc_now()
    cursor = conn.execute(
        """
        UPDATE memory_enhancement_jobs
           SET status = 'running',
               attempt_count = attempt_count + 1,
               locked_at = ?,
               locked_by_worker = ''
         WHERE job_id = ? AND status = 'pending'
        """,
        (now, job_id),
    )
    if cursor.rowcount != 1:
        conn.commit()
        return None
    record_memory_audit_event(
        conn,
        "memory_enhancement_started",
        persona=row[1],
        target_kind="enhancement_job",
        target_id=job_id,
        payload={},
        commit=False,
    )
    conn.commit()
    return _select_enhancement_job(conn, job_id)


def memory_enhancement_complete(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    status: str,
    response_payload: object | None = None,
    error: str = "",
    actual_provider: str = "",
    actual_model: str = "",
) -> dict:
    """Finish a sidecar enhancement job without mutating memory files."""
    status = status.strip()
    if status not in {"succeeded", "failed", "skipped"}:
        raise ValueError("status must be succeeded, failed, or skipped")
    job = _select_enhancement_job(conn, job_id)
    if job is None:
        return {"ok": False, "error": "enhancement job not found", "job_id": job_id}

    if status == "succeeded":
        response_mapping = response_payload if isinstance(response_payload, dict) else {}
        request_payload = job.get("request_payload") if isinstance(job.get("request_payload"), dict) else {}
        if request_payload.get("task") == "enrich_authored_memory_payload":
            result_payload = normalize_authored_memory_writeback(
                request_payload,
                enrichment_payload=response_mapping,
            )
        else:
            result_payload = normalize_memory_enhancement_response(response_mapping)
        entity_result = apply_enhancement_entities(
            conn,
            file_id=job.get("file_id"),
            metadata=result_payload,
            source="enhancement",
        )
        event_type = "memory_enhancement_completed"
        error_text = ""
    else:
        result_payload = response_payload if isinstance(response_payload, dict) else {}
        entity_result = {"link_count": 0, "edge_count": 0}
        event_type = "memory_enhancement_failed" if status == "failed" else "memory_enhancement_skipped"
        error_text = error or ""

    conn.execute(
        """
        UPDATE memory_enhancement_jobs
           SET status = ?,
               result_payload = ?,
               error = ?,
               actual_provider = COALESCE(NULLIF(?, ''), actual_provider),
               actual_model = COALESCE(NULLIF(?, ''), actual_model),
               locked_at = NULL,
               locked_by_worker = ''
         WHERE job_id = ?
        """,
        (
            status,
            _json_text(result_payload),
            error_text,
            actual_provider,
            actual_model,
            job_id,
        ),
    )
    record_memory_audit_event(
        conn,
        event_type,
        persona=job.get("persona"),
        target_kind="enhancement_job",
        target_id=job_id,
        payload={
            "status": status,
            "file_id": job.get("file_id"),
            "entities": entity_result,
            "actual_provider": actual_provider,
            "actual_model": actual_model,
        },
        commit=False,
    )
    conn.commit()
    return {"ok": True, "job": _select_enhancement_job(conn, job_id)}


def _worker_heartbeat_to_dict(row: sqlite3.Row | tuple | None) -> dict | None:
    if row is None:
        return None
    return {
        "worker_id": row[0],
        "capability": row[1],
        "provider": row[2],
        "status": row[3],
        "current_job_id": row[4],
        "last_seen_at": row[5],
        "metadata": _json_object(row[6]),
    }


def _select_worker_heartbeat(conn: sqlite3.Connection, worker_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT worker_id, capability, provider, status, current_job_id,
               last_seen_at, metadata
        FROM memory_worker_heartbeats
        WHERE worker_id = ?
        """,
        (worker_id,),
    ).fetchone()
    return _worker_heartbeat_to_dict(row)


def memory_worker_heartbeat(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    capability: str = "enhancement",
    provider: str = "",
    status: str = "idle",
    current_job_id: str = "",
    metadata: dict | None = None,
) -> dict:
    """Record liveness for a supervised memory worker."""
    worker_id = _clean_worker_text(worker_id)
    capability = _clean_worker_text(capability, max_chars=80) or "enhancement"
    provider = _clean_worker_text(provider, max_chars=80)
    status = _clean_worker_text(status, max_chars=40) or "idle"
    current_job_id = _clean_worker_text(current_job_id, max_chars=120)
    if not worker_id:
        return {"ok": False, "error": "worker_id is required"}
    if capability not in WORKER_CAPABILITIES:
        return {"ok": False, "error": f"unsupported worker capability: {capability}"}
    if status not in WORKER_HEARTBEAT_STATUSES:
        return {"ok": False, "error": f"unsupported worker status: {status}"}
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO memory_worker_heartbeats (
            worker_id, capability, provider, status, current_job_id,
            last_seen_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(worker_id) DO UPDATE SET
            capability = excluded.capability,
            provider = COALESCE(NULLIF(excluded.provider, ''), memory_worker_heartbeats.provider),
            status = excluded.status,
            current_job_id = excluded.current_job_id,
            last_seen_at = excluded.last_seen_at,
            metadata = excluded.metadata
        """,
        (
            worker_id,
            capability,
            provider,
            status,
            current_job_id,
            now,
            _json_text(metadata if isinstance(metadata, dict) else {}),
        ),
    )
    conn.commit()
    return {"ok": True, "heartbeat": _select_worker_heartbeat(conn, worker_id)}


def _worker_job_payload(job: dict) -> dict:
    request_payload = job.get("request_payload") if isinstance(job.get("request_payload"), dict) else {}
    task = str(request_payload.get("task") or "extract_memory_metadata")
    kind = "authored_memory_payload" if task == "enrich_authored_memory_payload" else "memory_file"
    source_id = str(job.get("file_id") or job.get("job_id") or "")
    source_path = str(request_payload.get("source_path") or job.get("path") or "")
    return {
        "job_id": job.get("job_id"),
        "schema_version": "chimera-memory.worker.enhance.v1",
        "capability": "enhancement",
        "source_ref": {
            "kind": kind,
            "id": source_id,
            "path": source_path,
        },
        "content": {
            "format": "markdown" if kind == "memory_file" else "json",
            "text": str(request_payload.get("wrapped_content") or ""),
        },
        "existing_metadata": request_payload.get("existing_frontmatter") or {},
        "policy": request_payload.get("policy") or {},
        "expected_fields": request_payload.get("expected_fields") or [],
        "output_schema": "strict-json",
        "request_payload": request_payload,
    }


def memory_worker_claim_next(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    capability: str = "enhancement",
    persona: str | None = None,
    provider: str = "",
) -> dict:
    """Claim one pending enhancement job for a supervised CLI worker."""
    worker_id = _clean_worker_text(worker_id)
    capability = _clean_worker_text(capability, max_chars=80) or "enhancement"
    provider = _clean_worker_text(provider, max_chars=80)
    if not worker_id:
        return {"ok": False, "error": "worker_id is required"}
    if capability not in WORKER_CAPABILITIES:
        return {"ok": False, "error": f"unsupported worker capability: {capability}"}

    conditions = ["status = 'pending'"]
    params: list[object] = []
    if persona:
        conditions.append("persona = ?")
        params.append(persona)
    if provider:
        conditions.append("(requested_provider = '' OR requested_provider = ?)")
        params.append(provider)
    row = conn.execute(
        f"""
        SELECT job_id, persona FROM memory_enhancement_jobs
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at ASC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        memory_worker_heartbeat(
            conn,
            worker_id=worker_id,
            capability=capability,
            provider=provider,
            status="idle",
            current_job_id="",
        )
        return {"ok": True, "job": None, "worker_request": None}

    job_id = row[0]
    now = _utc_now()
    cursor = conn.execute(
        """
        UPDATE memory_enhancement_jobs
           SET status = 'running',
               attempt_count = attempt_count + 1,
               locked_at = ?,
               locked_by_worker = ?
         WHERE job_id = ? AND status = 'pending'
        """,
        (now, worker_id, job_id),
    )
    if cursor.rowcount != 1:
        conn.commit()
        return {"ok": True, "job": None, "worker_request": None, "race_lost": True}
    record_memory_audit_event(
        conn,
        "memory_worker_job_claimed",
        persona=row[1],
        target_kind="enhancement_job",
        target_id=job_id,
        payload={"worker_id": worker_id, "capability": capability, "provider": provider},
        commit=False,
    )
    record_memory_audit_event(
        conn,
        "memory_enhancement_started",
        persona=row[1],
        target_kind="enhancement_job",
        target_id=job_id,
        payload={"worker_id": worker_id},
        commit=False,
    )
    conn.commit()
    memory_worker_heartbeat(
        conn,
        worker_id=worker_id,
        capability=capability,
        provider=provider,
        status="running",
        current_job_id=job_id,
    )
    job = _select_enhancement_job(conn, job_id)
    return {"ok": True, "job": job, "worker_request": _worker_job_payload(job or {})}


def _validate_worker_result_payload(result_payload: object) -> tuple[bool, str]:
    if not isinstance(result_payload, dict):
        return False, "result_payload must be a JSON object"
    allowed = {
        "memory_type",
        "summary",
        "entities",
        "relationships",
        "topics",
        "people",
        "projects",
        "tools",
        "action_items",
        "dates",
        "confidence",
        "sensitivity_tier",
    }
    unknown = sorted(str(key) for key in result_payload.keys() if str(key) not in allowed)
    if unknown:
        return False, f"unknown result fields: {', '.join(unknown[:5])}"
    summary = str(result_payload.get("summary") or "").strip()
    if not summary:
        return False, "summary is required for succeeded worker result"
    return True, ""


def memory_worker_submit_result(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    job_id: str,
    status: str,
    result_payload: dict | None = None,
    error: str = "",
    actual_provider: str = "",
    actual_model: str = "",
    diagnostics: dict | None = None,
) -> dict:
    """Submit a structured result for a job owned by a supervised worker."""
    worker_id = _clean_worker_text(worker_id)
    job_id = _clean_worker_text(job_id)
    status = _clean_worker_text(status, max_chars=40)
    if not worker_id:
        return {"ok": False, "error": "worker_id is required"}
    if not job_id:
        return {"ok": False, "error": "job_id is required"}
    job = _select_enhancement_job(conn, job_id)
    if job is None:
        return {"ok": False, "error": "enhancement job not found", "job_id": job_id}
    if job.get("status") != "running":
        return {"ok": False, "error": "enhancement job is not running", "job_id": job_id}
    if str(job.get("locked_by_worker") or "") != worker_id:
        return {"ok": False, "error": "worker does not own this job", "job_id": job_id}
    if status == "succeeded":
        if not actual_provider.strip():
            return {"ok": False, "error": "actual_provider is required for succeeded worker result", "job_id": job_id}
        valid, validation_error = _validate_worker_result_payload(result_payload or {})
        if not valid:
            return {"ok": False, "error": validation_error, "job_id": job_id}
    completed = memory_enhancement_complete(
        conn,
        job_id=job_id,
        status=status,
        response_payload=result_payload if isinstance(result_payload, dict) else {},
        error=error,
        actual_provider=actual_provider,
        actual_model=actual_model,
    )
    if not completed.get("ok"):
        return completed
    provider_usage_record(
        conn,
        provider=actual_provider,
        transport="cli_worker",
        credential_mode="oauth",
        worker_id=worker_id,
        job_id=job_id,
        status=status,
        failure_category=error if status == "failed" else "",
        tokens_in=_diagnostic_int(diagnostics, "tokens_in", "input_tokens"),
        tokens_out=_diagnostic_int(diagnostics, "tokens_out", "output_tokens"),
        latency_ms=_diagnostic_int(diagnostics, "latency_ms"),
        metadata={"source": "memory_worker_submit_result"},
        commit=False,
    )
    record_memory_audit_event(
        conn,
        "memory_worker_result_submitted",
        persona=completed.get("job", {}).get("persona"),
        target_kind="enhancement_job",
        target_id=job_id,
        payload={
            "worker_id": worker_id,
            "status": status,
            "actual_provider": actual_provider,
            "actual_model": actual_model,
            "diagnostics": diagnostics if isinstance(diagnostics, dict) else {},
        },
        commit=False,
    )
    conn.commit()
    memory_worker_heartbeat(
        conn,
        worker_id=worker_id,
        capability="enhancement",
        provider=actual_provider,
        status="idle",
        current_job_id="",
    )
    return {"ok": True, "job": _select_enhancement_job(conn, job_id)}


def memory_worker_budget(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    capability: str = "enhancement",
    provider: str = "",
) -> dict:
    """Return current configured budget caps for a memory worker.

    This first protocol slice exposes configured caps but does not yet maintain
    a persisted consumption ledger.
    """
    worker_id = _clean_worker_text(worker_id)
    capability = _clean_worker_text(capability, max_chars=80) or "enhancement"
    provider = _clean_worker_text(provider, max_chars=80)
    if not worker_id:
        return {"ok": False, "error": "worker_id is required"}
    if capability not in WORKER_CAPABILITIES:
        return {"ok": False, "error": f"unsupported worker capability: {capability}"}
    from .memory_enhancement_provider import load_enhancement_budget

    budget = load_enhancement_budget(os.environ)
    governor = provider_governor_check(
        conn,
        provider=provider,
        budget=budget,
        requested_calls=1,
        transport="cli_worker",
        worker_id=worker_id,
    )
    return {
        "ok": True,
        "allowed": bool(governor.get("allowed", False)),
        "reason": governor.get("reason", ""),
        "worker_id": worker_id,
        "capability": capability,
        "provider": provider,
        "mode": "shared_provider_governor",
        "usage": governor.get("usage", {}),
        "budget": {
            "max_input_tokens": budget.max_input_tokens,
            "max_input_chars": budget.max_input_chars,
            "max_output_tokens": budget.max_output_tokens,
            "max_jobs_per_run": budget.max_jobs_per_run,
            "per_minute_call_cap": budget.per_minute_call_cap,
            "daily_soft_call_cap": budget.daily_soft_call_cap,
            "monthly_hard_call_cap": budget.monthly_hard_call_cap,
            "timeout_seconds": budget.timeout_seconds,
        },
    }
