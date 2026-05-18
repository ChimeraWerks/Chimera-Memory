"""Warning-only active harness lease helpers."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


ACTIVE_HARNESS_SCHEMA_VERSION = "chimera-memory.active-harness-lease.v1"
DEFAULT_LEASE_TTL_SECONDS = 30 * 60


def _json_text(value: object) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, default=str)


def _json_object(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _row_to_lease(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    return {
        "lease_id": row[0],
        "created_at": row[1],
        "last_seen_at": row[2],
        "expires_at": row[3],
        "status": row[4],
        "persona": row[5],
        "process_id": row[6],
        "hostname": row[7],
        "runtime_name": row[8],
        "client": row[9],
        "db_path": row[10],
        "persona_root": row[11],
        "metadata": _json_object(row[12]),
    }


def _active_rows(
    conn: sqlite3.Connection,
    *,
    persona: str | None = None,
    db_path: str | None = None,
    now: float | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    observed_now = float(now if now is not None else time.time())
    conditions = ["status = 'active'", "expires_at >= ?"]
    params: list[Any] = [observed_now]
    if persona:
        conditions.append("persona = ?")
        params.append(persona)
    if db_path:
        conditions.append("db_path = ?")
        params.append(str(Path(db_path).expanduser()))
    rows = conn.execute(
        f"""
        SELECT lease_id, created_at, last_seen_at, expires_at, status,
               persona, process_id, hostname, runtime_name, client,
               db_path, persona_root, metadata
          FROM memory_active_harness_leases
         WHERE {" AND ".join(conditions)}
         ORDER BY last_seen_at DESC, id DESC
         LIMIT ?
        """,
        params + [max(0, min(limit, 200))],
    ).fetchall()
    return [_row_to_lease(row) for row in rows]


def register_active_harness(
    conn: sqlite3.Connection,
    *,
    persona: str | None,
    db_path: str | Path | None,
    lease_id: str | None = None,
    runtime_name: str = "mcp",
    client: str = "",
    persona_root: str | Path | None = None,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    metadata: object | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Register or refresh this runtime and report same-persona conflicts.

    This is deliberately warning-only. It never blocks or releases another
    process. Service-mode or hard locks can layer on top later if the warning
    data proves the risk is real.
    """
    observed_now = float(now if now is not None else time.time())
    normalized_lease_id = lease_id or str(uuid.uuid4())
    normalized_db_path = str(Path(db_path).expanduser()) if db_path else ""
    normalized_persona_root = str(Path(persona_root).expanduser()) if persona_root else ""
    ttl = max(1, int(ttl_seconds))
    expires_at = observed_now + ttl
    hostname = socket.gethostname()
    process_id = os.getpid()
    payload = {
        **(_json_object(_json_text(metadata))),
        "schema_version": ACTIVE_HARNESS_SCHEMA_VERSION,
    }

    conn.execute(
        """
        INSERT INTO memory_active_harness_leases (
            lease_id, created_at, last_seen_at, expires_at, status,
            persona, process_id, hostname, runtime_name, client,
            db_path, persona_root, metadata
        ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(lease_id) DO UPDATE SET
            last_seen_at = excluded.last_seen_at,
            expires_at = excluded.expires_at,
            status = 'active',
            persona = excluded.persona,
            process_id = excluded.process_id,
            hostname = excluded.hostname,
            runtime_name = excluded.runtime_name,
            client = excluded.client,
            db_path = excluded.db_path,
            persona_root = excluded.persona_root,
            metadata = excluded.metadata
        """,
        (
            normalized_lease_id,
            observed_now,
            observed_now,
            expires_at,
            persona or "",
            process_id,
            hostname,
            runtime_name,
            client,
            normalized_db_path,
            normalized_persona_root,
            _json_text(payload),
        ),
    )
    conn.commit()

    active = _active_rows(
        conn,
        persona=persona or "",
        db_path=normalized_db_path,
        now=observed_now,
    )
    conflicts = [lease for lease in active if lease["lease_id"] != normalized_lease_id]
    return {
        "schema_version": ACTIVE_HARNESS_SCHEMA_VERSION,
        "lease_id": normalized_lease_id,
        "persona": persona or "",
        "db_path": normalized_db_path,
        "ttl_seconds": ttl,
        "active_count": len(active),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "warning_only": True,
        "warnings": _warnings(conflicts),
    }


def active_harness_report(
    conn: sqlite3.Connection,
    *,
    persona: str | None = None,
    db_path: str | Path | None = None,
    now: float | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return active harness leases without mutating them."""
    normalized_db_path = str(Path(db_path).expanduser()) if db_path else None
    active = _active_rows(
        conn,
        persona=persona,
        db_path=normalized_db_path,
        now=now,
        limit=limit,
    )
    return {
        "schema_version": ACTIVE_HARNESS_SCHEMA_VERSION,
        "persona": persona or "",
        "db_path": normalized_db_path or "",
        "active_count": len(active),
        "leases": active,
        "warning_only": True,
        "warnings": _warnings(active[1:] if persona and len(active) > 1 else []),
    }


def release_active_harness(
    conn: sqlite3.Connection,
    *,
    lease_id: str,
    now: float | None = None,
) -> bool:
    observed_now = float(now if now is not None else time.time())
    cur = conn.execute(
        """
        UPDATE memory_active_harness_leases
           SET status = 'released',
               last_seen_at = ?,
               expires_at = ?
         WHERE lease_id = ?
        """,
        (observed_now, observed_now, lease_id),
    )
    conn.commit()
    return cur.rowcount > 0


def _warnings(conflicts: list[dict[str, Any]]) -> list[str]:
    if not conflicts:
        return []
    return [
        "Another active ChimeraMemory harness is using this persona DB. "
        "Warning only: no lock was enforced."
    ]
