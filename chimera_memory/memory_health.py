"""Health checks for the CM background intelligence layer."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .embeddings import TRANSCRIPT_EMBEDDABLE_TYPES, init_embedding_table
from .memory_observability import record_memory_audit_event

_STATUS_RANK = {"ok": 0, "degraded": 1, "broken": 2}


DEFAULT_THRESHOLDS = {
    "unembedded_degraded": 100,
    "unembedded_broken": 10_000,
    "oldest_unembedded_degraded_seconds": 10 * 60,
    "oldest_unembedded_broken_seconds": 60 * 60,
    "enhancement_pending_degraded_seconds": 60 * 60,
    "enhancement_pending_broken_seconds": 24 * 60 * 60,
}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(value: str | None, now: datetime) -> float | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed).total_seconds())


def _worst(*statuses: str) -> str:
    return max(statuses, key=lambda status: _STATUS_RANK.get(status, 0))


def _check_embeddings(conn: sqlite3.Connection, thresholds: dict[str, int], now: datetime) -> dict[str, Any]:
    init_embedding_table(conn)
    placeholders = ",".join("?" * len(TRANSCRIPT_EMBEDDABLE_TYPES))
    eligible, embedded, pending = conn.execute(
        f"""
        SELECT
            COUNT(*) AS eligible,
            COUNT(e.transcript_id) AS embedded,
            COUNT(*) - COUNT(e.transcript_id) AS pending
        FROM transcript t
        LEFT JOIN transcript_embeddings e ON e.transcript_id = t.id
        WHERE t.content IS NOT NULL
          AND t.content != ''
          AND t.entry_type IN ({placeholders})
        """,
        TRANSCRIPT_EMBEDDABLE_TYPES,
    ).fetchone()
    latest_embedded = conn.execute(
        f"""
        SELECT MAX(t.timestamp)
        FROM transcript_embeddings e
        JOIN transcript t ON t.id = e.transcript_id
        WHERE t.entry_type IN ({placeholders})
        """,
        TRANSCRIPT_EMBEDDABLE_TYPES,
    ).fetchone()[0]
    oldest_unembedded = conn.execute(
        f"""
        SELECT MIN(t.timestamp)
        FROM transcript t
        LEFT JOIN transcript_embeddings e ON e.transcript_id = t.id
        WHERE e.transcript_id IS NULL
          AND t.content IS NOT NULL
          AND t.content != ''
          AND t.entry_type IN ({placeholders})
        """,
        TRANSCRIPT_EMBEDDABLE_TYPES,
    ).fetchone()[0]
    oldest_unembedded_age = _age_seconds(oldest_unembedded, now)

    status = "ok"
    if eligible and not embedded:
        status = "broken"
    elif pending >= thresholds["unembedded_broken"]:
        status = "broken"
    elif pending >= thresholds["unembedded_degraded"]:
        status = "degraded"
    elif oldest_unembedded_age is not None:
        if oldest_unembedded_age >= thresholds["oldest_unembedded_broken_seconds"]:
            status = "broken"
        elif oldest_unembedded_age >= thresholds["oldest_unembedded_degraded_seconds"]:
            status = "degraded"

    return {
        "status": status,
        "eligible": int(eligible or 0),
        "embedded": int(embedded or 0),
        "pending": int(pending or 0),
        "latest_embedded_timestamp": latest_embedded,
        "oldest_unembedded_timestamp": oldest_unembedded,
        "oldest_unembedded_age_seconds": oldest_unembedded_age,
    }


def _check_enhancement_queue(conn: sqlite3.Connection, now: datetime, thresholds: dict[str, int]) -> dict[str, Any]:
    status_counts = {
        str(row[0]): int(row[1])
        for row in conn.execute(
            "SELECT status, COUNT(*) FROM memory_enhancement_jobs GROUP BY status"
        ).fetchall()
    }
    oldest_pending = conn.execute(
        """
        SELECT created_at
        FROM memory_enhancement_jobs
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT 1
        """
    ).fetchone()
    oldest_pending_at = oldest_pending[0] if oldest_pending else None
    oldest_pending_age = _age_seconds(oldest_pending_at, now)

    status = "ok"
    if oldest_pending_age is not None:
        if oldest_pending_age >= thresholds["enhancement_pending_broken_seconds"]:
            status = "broken"
        elif oldest_pending_age >= thresholds["enhancement_pending_degraded_seconds"]:
            status = "degraded"

    return {
        "status": status,
        "counts": status_counts,
        "oldest_pending_created_at": oldest_pending_at,
        "oldest_pending_age_seconds": oldest_pending_age,
    }


def _provider_profile() -> dict[str, Any]:
    try:
        from .memory_enhancement_provider import resolve_enhancement_provider_plan, safe_provider_receipt

        plan = resolve_enhancement_provider_plan(os.environ)
        receipt = safe_provider_receipt(plan, os.environ)
        selected_provider = str(receipt.get("selected_provider") or "")
        selected_model = str(receipt.get("selected_model") or "")
        selected_candidate = {}
        candidates = receipt.get("candidates") if isinstance(receipt.get("candidates"), list) else []
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("provider_id") == selected_provider:
                selected_candidate = candidate
                break
        return {
            "status": "ok",
            "selected_provider": selected_provider,
            "selected_model": selected_model,
            "provider_affinity": str(receipt.get("provider_affinity") or ""),
            "credential_ref_present": bool(selected_candidate.get("credential_ref_present")),
            "uses_user_oauth": bool(selected_candidate.get("uses_user_oauth")),
            "requires_network": bool(selected_candidate.get("requires_network")),
            "live": False,
        }
    except Exception:
        return {"status": "unavailable"}


def _selected_provider(provider_profile: dict[str, Any] | None = None) -> str:
    profile = provider_profile if isinstance(provider_profile, dict) else _provider_profile()
    return str(profile.get("selected_provider") or "") if profile.get("status") == "ok" else ""


def _check_provider_drift(conn: sqlite3.Connection, provider_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = _selected_provider(provider_profile)
    drift_count = 0
    if selected:
        drift_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_enhancement_jobs
                WHERE status IN ('pending', 'running')
                  AND requested_provider IS NOT NULL
                  AND requested_provider != ''
                  AND requested_provider != ?
                """,
                (selected,),
            ).fetchone()[0]
        )
    return {
        "status": "degraded" if drift_count else "ok",
        "selected_provider": selected,
        "drift_count": drift_count,
    }


def _check_session_rollups(conn: sqlite3.Connection) -> dict[str, Any]:
    mismatch_count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM sessions s
            JOIN (
                SELECT session_id, COUNT(*) AS actual_count
                FROM transcript
                WHERE entry_type IN ('user_message', 'assistant_message', 'discord_inbound', 'discord_outbound')
                GROUP BY session_id
            ) t ON t.session_id = s.session_id
            WHERE COALESCE(s.exchange_count, 0) != t.actual_count
            """
        ).fetchone()[0]
    )
    zero_with_rows = len(
        conn.execute(
            """
            SELECT s.session_id
            FROM sessions s
            JOIN transcript t ON t.session_id = s.session_id
            WHERE COALESCE(s.exchange_count, 0) = 0
            GROUP BY s.session_id
            HAVING SUM(CASE
                WHEN t.entry_type IN ('user_message', 'assistant_message', 'discord_inbound', 'discord_outbound')
                THEN 1 ELSE 0 END) > 0
            """
        ).fetchall()
    )
    status = "broken" if zero_with_rows else ("degraded" if mismatch_count else "ok")
    return {
        "status": status,
        "mismatch_count": mismatch_count,
        "zero_exchange_sessions_with_rows": zero_with_rows,
    }


def _check_duplicate_capture(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(extra_count), 0)
        FROM (
            SELECT COUNT(*) - 1 AS extra_count
            FROM transcript
            WHERE message_id IS NOT NULL AND message_id != ''
            GROUP BY entry_type, chat_id, message_id
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()
    duplicate_groups = int(row[0] or 0)
    duplicate_extra_rows = int(row[1] or 0)
    return {
        "status": "degraded" if duplicate_groups else "ok",
        "duplicate_groups": duplicate_groups,
        "duplicate_extra_rows": duplicate_extra_rows,
    }


def _check_last_success(conn: sqlite3.Connection) -> dict[str, Any]:
    latest_import = conn.execute("SELECT MAX(updated_at) FROM import_log").fetchone()[0]
    latest_enhancement = conn.execute(
        "SELECT MAX(updated_at) FROM memory_enhancement_jobs WHERE status = 'succeeded'"
    ).fetchone()[0]
    latest_health = conn.execute(
        "SELECT MAX(created_at) FROM memory_audit_events WHERE event_type = 'cm_health_snapshot'"
    ).fetchone()[0]
    return {
        "status": "ok",
        "transcript_import": latest_import,
        "enhancement_success": latest_enhancement,
        "health_snapshot": latest_health,
    }


def _global_memory_counts(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS indexed_count,
            SUM(CASE
                WHEN COALESCE(f.fm_exclude_from_default_search, 0) = 0
                  AND COALESCE(f.fm_can_use_as_evidence, 1) = 1
                  AND COALESCE(f.fm_sensitivity_tier, 'standard') <> 'restricted'
                  AND COALESCE(f.fm_lifecycle_status, 'active') NOT IN ('disputed', 'rejected', 'superseded')
                THEN 1 ELSE 0 END) AS available_count,
            SUM(CASE
                WHEN COALESCE(f.fm_exclude_from_default_search, 0) = 0
                  AND COALESCE(f.fm_can_use_as_evidence, 1) = 1
                  AND COALESCE(f.fm_sensitivity_tier, 'standard') <> 'restricted'
                  AND COALESCE(f.fm_lifecycle_status, 'active') NOT IN ('disputed', 'rejected', 'superseded')
                  AND COALESCE(f.fm_can_use_as_instruction, 1) = 1
                  AND COALESCE(f.fm_review_status, 'confirmed') = 'confirmed'
                  AND COALESCE(f.fm_provenance_status, 'imported') IN ('user_confirmed', 'auto_confirmed')
                THEN 1 ELSE 0 END) AS instruction_grade_count
        FROM memory_files f
        WHERE COALESCE(f.memory_scope, '') = 'global'
        """
    ).fetchone()
    return {
        "indexed": int(row[0] or 0),
        "available": int(row[1] or 0),
        "instruction_grade": int(row[2] or 0),
    }


def _runtime_profile(conn: sqlite3.Connection, persona: str | None) -> dict[str, Any]:
    """Return a path-safe runtime profile for diagnostics."""
    try:
        from .config import load_config
        from .memory_scope import current_project_id, global_memory_root, project_memory_roots

        config = load_config()
        client = str(config.get("client") or "").strip()
        surface = str(config.get("mcp_surface") or "").strip() or "full"
        transcript_persona = (
            os.environ.get("TRANSCRIPT_PERSONA", "").strip()
            or str(config.get("persona") or "").strip()
            or str(persona or "").strip()
        )
        project_id = current_project_id() or ""
        project_roots = project_memory_roots()
        global_root = global_memory_root()
        global_root_source = "env" if os.environ.get("CHIMERA_MEMORY_GLOBAL_ROOT", "").strip() else "default"
        global_counts = _global_memory_counts(conn)
    except Exception:
        return {"status": "unavailable"}

    persona_set = bool(transcript_persona)
    project_root_configured = bool(project_roots)
    memory_profile = "persona" if persona_set else ("project" if project_root_configured or project_id else "unscoped")
    persona_tree_indexing = not (
        not persona_set
        and (project_root_configured or client.lower() == "codex" or surface.lower() == "codex")
    )
    return {
        "status": "ok",
        "client": client,
        "mcp_surface": surface,
        "memory_profile": memory_profile,
        "transcript_persona_set": persona_set,
        "project_id": project_id,
        "project_id_set": bool(project_id),
        "project_root_configured": project_root_configured,
        "project_roots_count": len(project_roots),
        "global_root_source": global_root_source,
        "global_root_exists": global_root.exists(),
        "global_indexed_file_count": global_counts["indexed"],
        "global_available_file_count": global_counts["available"],
        "global_instruction_grade_file_count": global_counts["instruction_grade"],
        "persona_tree_indexing": persona_tree_indexing,
    }


def collect_cm_health(
    conn: sqlite3.Connection,
    *,
    persona: str | None = None,
    worker_states: dict[str, bool] | None = None,
    thresholds: dict[str, int] | None = None,
    now: datetime | None = None,
    repair_session_rollups: bool = True,
) -> dict[str, Any]:
    """Collect a structured health snapshot for CM's automatic background work."""
    from .memory import init_memory_tables

    init_memory_tables(conn)
    repaired_rollups = 0
    if repair_session_rollups:
        from .db import repair_session_rollups as _repair_session_rollups

        repaired_rollups = _repair_session_rollups(conn)
        if repaired_rollups:
            conn.commit()
    now = now or datetime.now(timezone.utc)
    effective_thresholds = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        effective_thresholds.update(thresholds)

    provider_profile = _provider_profile()
    checks = {
        "embeddings": _check_embeddings(conn, effective_thresholds, now),
        "enhancement_queue": _check_enhancement_queue(conn, now, effective_thresholds),
        "provider_drift": _check_provider_drift(conn, provider_profile),
        "session_rollups": _check_session_rollups(conn),
        "duplicate_capture": _check_duplicate_capture(conn),
        "last_success": _check_last_success(conn),
    }
    if repaired_rollups:
        checks["session_rollups"]["auto_repaired_count"] = repaired_rollups
    if worker_states:
        checks["workers"] = {
            "status": "ok" if all(worker_states.values()) else "degraded",
            **worker_states,
        }

    status = _worst(*(check.get("status", "ok") for check in checks.values()))
    return {
        "schema_version": "chimera-memory.health.v1",
        "created_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "persona": persona or "",
        "runtime_profile": _runtime_profile(conn, persona),
        "provider_profile": provider_profile,
        "status": status,
        "checks": checks,
    }


def record_cm_health_snapshot(
    conn: sqlite3.Connection,
    *,
    persona: str | None = None,
    worker_states: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Collect and persist a CM health snapshot as an audit event."""
    snapshot = collect_cm_health(conn, persona=persona, worker_states=worker_states)
    record_memory_audit_event(
        conn,
        "cm_health_snapshot",
        persona=persona,
        target_kind="cm_health",
        target_id=snapshot["status"],
        payload=snapshot,
    )
    return snapshot


def format_cm_health(snapshot: dict[str, Any]) -> str:
    """Format a health snapshot for memory_diagnose(mode='health')."""
    lines = [
        f"CM health: {snapshot.get('status', 'unknown')}",
        f"created_at: {snapshot.get('created_at', '')}",
    ]
    persona = snapshot.get("persona")
    if persona:
        lines.append(f"persona: {persona}")
    runtime_profile = snapshot.get("runtime_profile")
    if isinstance(runtime_profile, dict) and runtime_profile.get("status") == "ok":
        lines.append(
            "runtime_profile: "
            f"client={runtime_profile.get('client') or '-'} "
            f"surface={runtime_profile.get('mcp_surface') or '-'} "
            f"profile={runtime_profile.get('memory_profile') or '-'} "
            f"project_root_configured={bool(runtime_profile.get('project_root_configured'))} "
            f"global_root_exists={bool(runtime_profile.get('global_root_exists'))} "
            f"global_available_files={int(runtime_profile.get('global_available_file_count') or 0)}/"
            f"{int(runtime_profile.get('global_indexed_file_count') or 0)} "
            f"global_instruction_grade_files={int(runtime_profile.get('global_instruction_grade_file_count') or 0)}/"
            f"{int(runtime_profile.get('global_available_file_count') or 0)} "
            f"persona_tree_indexing={bool(runtime_profile.get('persona_tree_indexing'))}"
        )
    provider_profile = snapshot.get("provider_profile")
    if isinstance(provider_profile, dict) and provider_profile.get("status") == "ok":
        lines.append(
            "provider_profile: "
            f"provider={provider_profile.get('selected_provider') or '-'} "
            f"model={provider_profile.get('selected_model') or '-'} "
            f"credential_ref_present={bool(provider_profile.get('credential_ref_present'))} "
            f"uses_user_oauth={bool(provider_profile.get('uses_user_oauth'))} "
            f"requires_network={bool(provider_profile.get('requires_network'))}"
        )
    lines.append("")
    for name, check in snapshot.get("checks", {}).items():
        lines.append(f"{name}: {check.get('status', 'unknown')}")
        for key, value in check.items():
            if key == "status":
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value, sort_keys=True)
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)
