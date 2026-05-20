import sqlite3
from pathlib import Path

from chimera_memory.enhancement_worker import (
    derive_dry_run_metadata,
    run_memory_enhancement_dry_run,
    run_memory_enhancement_fake_worker,
)
from chimera_memory.memory import (
    index_file,
    init_memory_tables,
    memory_audit_query,
    memory_enhancement_enqueue,
)
from chimera_memory.memory_provider_governor import provider_usage_record


def _index_worker_memory(conn: sqlite3.Connection, tmp_path: Path, name: str = "worker.md") -> None:
    memory_file = tmp_path / name
    memory_file.write_text(
        "\n".join(
            [
                "---",
                "type: procedural",
                "importance: 7",
                "tags: [sidecar, queue]",
                "---",
                "Review queued metadata on 2026-05-14.",
                "TODO: wire the cheap model after the dry-run worker.",
            ]
        ),
        encoding="utf-8",
    )
    assert index_file(conn, "asa", name, memory_file)


def test_derive_dry_run_metadata_uses_existing_type_tags_and_body() -> None:
    job = {
        "request_payload": {
            "existing_frontmatter": {"type": "procedural", "tags": ["sidecar"]},
            "wrapped_content": "\n".join(
                [
                    "----- BEGIN UNTRUSTED MEMORY CONTENT -----",
                    "Review queued metadata on 2026-05-14.",
                    "TODO: wire the cheap model after the dry-run worker.",
                    "----- END UNTRUSTED MEMORY CONTENT -----",
                ]
            ),
        }
    }

    metadata = derive_dry_run_metadata(job)

    assert metadata["memory_type"] == "procedural"
    assert metadata["summary"] == "Review queued metadata on 2026-05-14."
    assert "sidecar" in metadata["topics"]
    assert "2026-05-14" in metadata["dates"]
    assert metadata["action_items"] == ["wire the cheap model after the dry-run worker."]
    assert metadata["confidence"] == 0.35


def test_run_memory_enhancement_dry_run_consumes_queue_without_mutating_memory(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_worker_memory(conn, tmp_path)
    enqueued = memory_enhancement_enqueue(conn, file_path="worker.md")

    processed = run_memory_enhancement_dry_run(conn, persona="asa")

    assert len(processed) == 1
    job = processed[0]
    assert job["job_id"] == enqueued["job"]["job_id"]
    assert job["status"] == "succeeded"
    assert job["actual_provider"] == "dry_run"
    assert job["actual_model"] == "deterministic-local"
    assert job["result_payload"]["memory_type"] == "procedural"
    assert job["result_payload"]["review_status"] == "pending"
    assert job["result_payload"]["can_use_as_instruction"] is False

    memory_row = conn.execute(
        """
        SELECT fm_review_status, fm_can_use_as_instruction
        FROM memory_files
        WHERE relative_path = 'worker.md'
        """
    ).fetchone()
    assert memory_row == ("confirmed", 1)

    events = memory_audit_query(conn, persona="asa")
    event_types = {event["event_type"] for event in events}
    assert {
        "memory_enhancement_enqueued",
        "memory_enhancement_started",
        "memory_enhancement_completed",
    }.issubset(event_types)


def test_run_memory_enhancement_dry_run_respects_persona_filter(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_worker_memory(conn, tmp_path, "asa.md")

    sarah_file = tmp_path / "sarah.md"
    sarah_file.write_text("Sarah queue body", encoding="utf-8")
    assert index_file(conn, "sarah", "sarah.md", sarah_file)

    memory_enhancement_enqueue(conn, file_path="asa.md")
    memory_enhancement_enqueue(conn, file_path="sarah.md")

    processed = run_memory_enhancement_dry_run(conn, persona="sarah")

    assert len(processed) == 1
    assert processed[0]["persona"] == "sarah"
    statuses = dict(
        conn.execute(
            "SELECT persona, status FROM memory_enhancement_jobs ORDER BY persona"
        ).fetchall()
    )
    assert statuses == {"asa": "pending", "sarah": "succeeded"}


def test_run_memory_enhancement_fake_worker_uses_worker_protocol(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_worker_memory(conn, tmp_path)
    enqueued = memory_enhancement_enqueue(conn, file_path="worker.md")

    receipt = run_memory_enhancement_fake_worker(
        conn,
        worker_id="fake-codex-worker",
        persona="asa",
        limit=1,
    )

    assert receipt["processed_count"] == 1
    assert receipt["failure_count"] == 0
    job = receipt["processed"][0]
    assert job["job_id"] == enqueued["job"]["job_id"]
    assert job["status"] == "succeeded"
    assert job["locked_by_worker"] == ""
    assert job["actual_provider"] == "dry_run"
    assert job["actual_model"] == "deterministic-local"
    assert job["result_payload"]["memory_type"] == "procedural"
    heartbeat = conn.execute(
        "SELECT status, current_job_id FROM memory_worker_heartbeats WHERE worker_id = ?",
        ("fake-codex-worker",),
    ).fetchone()
    assert heartbeat == ("idle", "")
    event_types = {event["event_type"] for event in memory_audit_query(conn, persona="asa")}
    assert {
        "memory_worker_job_claimed",
        "memory_worker_result_submitted",
        "memory_enhancement_completed",
    }.issubset(event_types)


def test_run_memory_enhancement_fake_worker_respects_governor_before_claim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_PER_MINUTE_CALL_CAP", "1")
    provider_usage_record(conn, provider="openai", transport="cli_worker", status="succeeded")
    _index_worker_memory(conn, tmp_path)
    enqueued = memory_enhancement_enqueue(conn, file_path="worker.md", requested_provider="openai")

    receipt = run_memory_enhancement_fake_worker(
        conn,
        worker_id="fake-openai-worker",
        provider="openai",
        limit=1,
    )

    assert receipt["processed_count"] == 0
    assert receipt["budget_stopped"] is True
    assert receipt["budget"]["reason"] == "per_minute_call_cap"
    row = conn.execute(
        "SELECT status, locked_by_worker FROM memory_enhancement_jobs WHERE job_id = ?",
        (enqueued["job"]["job_id"],),
    ).fetchone()
    assert row == ("pending", "")
