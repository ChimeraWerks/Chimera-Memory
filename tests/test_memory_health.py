import sqlite3
from datetime import datetime, timezone

from chimera_memory.db import SCHEMA_SQL
from chimera_memory.embeddings import init_embedding_table, pack_embedding
from chimera_memory.memory import init_memory_tables, memory_audit_query
from chimera_memory.memory_enhancement_queue import memory_enhancement_enqueue_authored
from chimera_memory.memory_health import collect_cm_health, format_cm_health, record_cm_health_snapshot


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    init_memory_tables(conn)
    init_embedding_table(conn)
    return conn


def _insert_transcript(conn: sqlite3.Connection, *, session_id: str = "s1", entry_type: str = "user_message") -> int:
    cursor = conn.execute(
        """
        INSERT INTO transcript (session_id, entry_type, timestamp, content, persona, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, entry_type, "2026-05-19T20:00:00Z", "hello memory", "asa", "test"),
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_health_marks_missing_embeddings_broken_then_ok() -> None:
    conn = _conn()
    transcript_id = _insert_transcript(conn)

    snapshot = collect_cm_health(conn, persona="asa")

    assert snapshot["status"] == "broken"
    assert snapshot["checks"]["embeddings"]["status"] == "broken"
    assert snapshot["checks"]["embeddings"]["eligible"] == 1
    assert snapshot["checks"]["embeddings"]["pending"] == 1

    conn.execute(
        "INSERT INTO transcript_embeddings (transcript_id, embedding) VALUES (?, ?)",
        (transcript_id, pack_embedding([0.0] * 384)),
    )
    conn.commit()

    snapshot = collect_cm_health(conn, persona="asa")

    assert snapshot["checks"]["embeddings"]["status"] == "ok"
    assert snapshot["checks"]["embeddings"]["pending"] == 0


def test_health_detects_stale_enhancement_queue() -> None:
    conn = _conn()
    memory_enhancement_enqueue_authored(
        conn,
        persona="asa",
        memory_payload={"memory_type": "procedural", "lessons": [{"teaching": "ship receipts"}]},
        source_ref="test",
    )
    conn.execute(
        "UPDATE memory_enhancement_jobs SET created_at = ?",
        ("2026-05-19T18:00:00Z",),
    )
    conn.commit()

    snapshot = collect_cm_health(
        conn,
        persona="asa",
        now=datetime(2026, 5, 19, 20, 0, tzinfo=timezone.utc),
    )

    assert snapshot["status"] == "degraded"
    assert snapshot["checks"]["enhancement_queue"]["status"] == "degraded"
    assert snapshot["checks"]["enhancement_queue"]["counts"] == {"pending": 1}


def test_health_detects_session_rollup_and_duplicate_drift() -> None:
    conn = _conn()
    _insert_transcript(conn, session_id="s1")
    conn.execute(
        "INSERT INTO sessions (session_id, persona, started_at, ended_at, exchange_count) VALUES (?, ?, ?, ?, ?)",
        ("s1", "asa", "2026-05-19T20:00:00Z", "2026-05-19T20:00:00Z", 0),
    )
    for index in range(2):
        conn.execute(
            """
            INSERT INTO transcript (session_id, entry_type, timestamp, content, persona, source, chat_id, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("s2", "discord_inbound", f"2026-05-19T20:01:0{index}Z", "duplicate", "asa", "discord", "c1", "m1"),
        )
    conn.commit()

    snapshot = collect_cm_health(conn, persona="asa")

    assert snapshot["checks"]["session_rollups"]["status"] == "broken"
    assert snapshot["checks"]["session_rollups"]["zero_exchange_sessions_with_rows"] == 1
    assert snapshot["checks"]["duplicate_capture"]["status"] == "degraded"
    assert snapshot["checks"]["duplicate_capture"]["duplicate_groups"] == 1


def test_record_health_snapshot_writes_audit_event() -> None:
    conn = _conn()

    snapshot = record_cm_health_snapshot(
        conn,
        persona="asa",
        worker_states={"transcript_indexer": True, "transcript_embedding_worker": True},
    )

    events = memory_audit_query(conn, event_type="cm_health_snapshot", persona="asa")
    assert len(events) == 1
    assert events[0]["payload"]["schema_version"] == "chimera-memory.health.v1"
    assert events[0]["payload"]["status"] == snapshot["status"]
    assert events[0]["payload"]["checks"]["workers"]["status"] == "ok"
    assert "CM health:" in format_cm_health(events[0]["payload"])
