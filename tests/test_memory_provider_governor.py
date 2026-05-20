import sqlite3

from chimera_memory.memory import init_memory_tables
from chimera_memory.memory_enhancement_provider import EnhancementBudget
from chimera_memory.memory_provider_governor import (
    provider_governor_check,
    provider_usage_counts,
    provider_usage_record,
)


def test_provider_usage_record_and_counts() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    recorded = provider_usage_record(
        conn,
        provider="openai",
        transport="cli_worker",
        credential_mode="oauth",
        worker_id="worker-1",
        job_id="job-1",
        status="succeeded",
        tokens_in=12,
        tokens_out=34,
        latency_ms=56,
    )

    assert recorded["ok"] is True
    assert recorded["recorded"] is True
    assert provider_usage_counts(conn, provider="openai") == {"minute": 1, "day": 1, "month": 1}
    row = conn.execute(
        """
        SELECT provider, transport, credential_mode, worker_id, job_id,
               status, tokens_in, tokens_out, latency_ms
        FROM memory_provider_usage_events
        """
    ).fetchone()
    assert row == ("openai", "cli_worker", "oauth", "worker-1", "job-1", "succeeded", 12, 34, 56)


def test_provider_governor_blocks_when_minute_cap_reached() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    provider_usage_record(conn, provider="openai", transport="http_oauth", status="succeeded")

    check = provider_governor_check(
        conn,
        provider="openai",
        budget=EnhancementBudget(per_minute_call_cap=1, daily_soft_call_cap=10, monthly_hard_call_cap=100),
        transport="http_oauth",
    )

    assert check["allowed"] is False
    assert check["reason"] == "per_minute_call_cap"
    assert check["usage"]["minute"] == 1
    assert check["caps"]["per_minute_call_cap"] == 1


def test_provider_governor_ignores_dry_run() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    check = provider_governor_check(
        conn,
        provider="dry_run",
        budget=EnhancementBudget(per_minute_call_cap=1, daily_soft_call_cap=1, monthly_hard_call_cap=1),
    )
    recorded = provider_usage_record(conn, provider="dry_run")

    assert check["allowed"] is True
    assert recorded["recorded"] is False
    assert provider_usage_counts(conn, provider="dry_run") == {"minute": 0, "day": 0, "month": 0}

