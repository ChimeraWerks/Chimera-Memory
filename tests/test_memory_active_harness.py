import sqlite3

from chimera_memory.memory_active_harness import (
    active_harness_report,
    register_active_harness,
    release_active_harness,
)
from chimera_memory.memory_schema import init_memory_tables


def test_register_active_harness_records_warning_only_lease() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = register_active_harness(
        conn,
        persona="asa",
        db_path="C:/tmp/asa/transcript.db",
        lease_id="lease-1",
        runtime_name="test-runtime",
        client="codex",
        now=100.0,
    )

    assert result["lease_id"] == "lease-1"
    assert result["active_count"] == 1
    assert result["conflict_count"] == 0
    assert result["warning_only"] is True
    assert result["warnings"] == []

    report = active_harness_report(
        conn,
        persona="asa",
        db_path="C:/tmp/asa/transcript.db",
        now=101.0,
    )
    assert report["active_count"] == 1
    assert report["leases"][0]["lease_id"] == "lease-1"
    assert report["leases"][0]["runtime_name"] == "test-runtime"


def test_refreshing_same_harness_does_not_create_conflict() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    register_active_harness(
        conn,
        persona="asa",
        db_path="C:/tmp/asa/transcript.db",
        lease_id="lease-1",
        now=100.0,
    )
    result = register_active_harness(
        conn,
        persona="asa",
        db_path="C:/tmp/asa/transcript.db",
        lease_id="lease-1",
        now=120.0,
    )

    assert result["active_count"] == 1
    assert result["conflict_count"] == 0
    assert conn.execute("SELECT COUNT(*) FROM memory_active_harness_leases").fetchone()[0] == 1
    assert conn.execute(
        "SELECT last_seen_at FROM memory_active_harness_leases WHERE lease_id = ?",
        ("lease-1",),
    ).fetchone()[0] == 120.0


def test_second_active_harness_warns_without_blocking() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    register_active_harness(
        conn,
        persona="asa",
        db_path="C:/tmp/asa/transcript.db",
        lease_id="lease-1",
        now=100.0,
    )
    result = register_active_harness(
        conn,
        persona="asa",
        db_path="C:/tmp/asa/transcript.db",
        lease_id="lease-2",
        now=110.0,
    )

    assert result["active_count"] == 2
    assert result["conflict_count"] == 1
    assert result["conflicts"][0]["lease_id"] == "lease-1"
    assert result["warnings"] == [
        "Another active ChimeraMemory harness is using this persona DB. "
        "Warning only: no lock was enforced."
    ]


def test_expired_or_released_harnesses_do_not_warn() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    register_active_harness(
        conn,
        persona="asa",
        db_path="C:/tmp/asa/transcript.db",
        lease_id="expired",
        ttl_seconds=5,
        now=100.0,
    )
    result = register_active_harness(
        conn,
        persona="asa",
        db_path="C:/tmp/asa/transcript.db",
        lease_id="fresh",
        ttl_seconds=5,
        now=110.0,
    )
    assert result["active_count"] == 1
    assert result["conflict_count"] == 0

    assert release_active_harness(conn, lease_id="fresh", now=111.0)
    report = active_harness_report(
        conn,
        persona="asa",
        db_path="C:/tmp/asa/transcript.db",
        now=112.0,
    )
    assert report["active_count"] == 0
