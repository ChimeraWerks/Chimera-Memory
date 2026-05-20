"""Provider traffic governor for memory-enhancement transports."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .memory_enhancement_provider import EnhancementBudget, load_enhancement_budget
from .memory_observability import _json_text


def _clean(value: object, *, max_chars: int = 120) -> str:
    return str(value or "").strip()[:max_chars]


def _count_since(conn: sqlite3.Connection, provider: str, cutoff_expr: str) -> int:
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM memory_provider_usage_events
        WHERE provider = ? AND created_at >= {cutoff_expr}
        """,
        (provider,),
    ).fetchone()
    return int(row[0] if row else 0)


def provider_usage_counts(conn: sqlite3.Connection, *, provider: str) -> dict[str, int]:
    """Return provider usage counts for the configured rolling windows."""
    provider = _clean(provider, max_chars=80)
    if not provider:
        return {"minute": 0, "day": 0, "month": 0}
    return {
        "minute": _count_since(conn, provider, "strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-60 seconds')"),
        "day": _count_since(conn, provider, "strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 day')"),
        "month": _count_since(conn, provider, "strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-30 days')"),
    }


def provider_governor_check(
    conn: sqlite3.Connection,
    *,
    provider: str,
    budget: EnhancementBudget | None = None,
    env: Mapping[str, str] | None = None,
    requested_calls: int = 1,
    transport: str = "",
    worker_id: str = "",
) -> dict:
    """Check whether a provider-backed memory call is currently allowed."""
    provider = _clean(provider, max_chars=80)
    transport = _clean(transport, max_chars=80)
    worker_id = _clean(worker_id)
    requested_calls = max(1, int(requested_calls or 1))
    budget = budget or load_enhancement_budget(env or {})
    if not provider or provider == "dry_run":
        return {
            "allowed": True,
            "reason": "local_or_missing_provider",
            "provider": provider,
            "transport": transport,
            "worker_id": worker_id,
            "usage": {"minute": 0, "day": 0, "month": 0},
            "caps": _budget_caps(budget),
        }
    usage = provider_usage_counts(conn, provider=provider)
    caps = _budget_caps(budget)
    if usage["minute"] + requested_calls > budget.per_minute_call_cap:
        reason = "per_minute_call_cap"
        allowed = False
    elif usage["day"] + requested_calls > budget.daily_soft_call_cap:
        reason = "daily_soft_call_cap"
        allowed = False
    elif usage["month"] + requested_calls > budget.monthly_hard_call_cap:
        reason = "monthly_hard_call_cap"
        allowed = False
    else:
        reason = "ok"
        allowed = True
    return {
        "allowed": allowed,
        "reason": reason,
        "provider": provider,
        "transport": transport,
        "worker_id": worker_id,
        "requested_calls": requested_calls,
        "usage": usage,
        "caps": caps,
    }


def provider_usage_record(
    conn: sqlite3.Connection,
    *,
    provider: str,
    transport: str = "",
    credential_mode: str = "",
    worker_id: str = "",
    job_id: str = "",
    status: str = "succeeded",
    failure_category: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    metadata: dict | None = None,
    commit: bool = True,
) -> dict:
    """Record one provider call attempt in the shared traffic ledger."""
    provider = _clean(provider, max_chars=80)
    if not provider or provider == "dry_run":
        return {"ok": True, "recorded": False, "reason": "local_or_missing_provider"}
    status = _clean(status, max_chars=40) or "succeeded"
    if status not in {"succeeded", "failed", "skipped", "deferred"}:
        status = "failed"
    conn.execute(
        """
        INSERT INTO memory_provider_usage_events (
            provider, transport, credential_mode, worker_id, job_id, status,
            failure_category, tokens_in, tokens_out, latency_ms, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider,
            _clean(transport, max_chars=80),
            _clean(credential_mode, max_chars=80),
            _clean(worker_id),
            _clean(job_id),
            status,
            _clean(failure_category, max_chars=80),
            max(0, int(tokens_in or 0)),
            max(0, int(tokens_out or 0)),
            max(0, int(latency_ms or 0)),
            _json_text(metadata if isinstance(metadata, dict) else {}),
        ),
    )
    if commit:
        conn.commit()
    return {"ok": True, "recorded": True, "usage": provider_usage_counts(conn, provider=provider)}


def _budget_caps(budget: EnhancementBudget) -> dict[str, int]:
    return {
        "per_minute_call_cap": int(budget.per_minute_call_cap),
        "daily_soft_call_cap": int(budget.daily_soft_call_cap),
        "monthly_hard_call_cap": int(budget.monthly_hard_call_cap),
    }

