import sqlite3
from pathlib import Path

from chimera_memory.memory import (
    index_file,
    init_memory_tables,
    memory_audit_query,
    memory_enhancement_claim_next,
    memory_enhancement_complete,
    memory_enhancement_enqueue,
    memory_enhancement_enqueue_authored,
    memory_worker_budget,
    memory_worker_claim_next,
    memory_worker_heartbeat,
    memory_worker_submit_result,
    memory_entity_connections,
    memory_entity_query,
)


def _index_memory(conn: sqlite3.Connection, tmp_path: Path, name: str = "target.md") -> None:
    memory_file = tmp_path / name
    memory_file.write_text(
        "\n".join(
            [
                "---",
                "type: procedural",
                "importance: 6",
                "tags: [sidecar]",
                "---",
                "Sidecar queue target body.",
            ]
        ),
        encoding="utf-8",
    )
    assert index_file(conn, "asa", name, memory_file)


def test_memory_enhancement_enqueue_builds_pending_job(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)

    result = memory_enhancement_enqueue(
        conn,
        file_path="target.md",
        requested_provider="local",
        requested_model="dry-run",
    )

    assert result["ok"] is True
    assert result["enqueued"] is True
    job = result["job"]
    assert job["status"] == "pending"
    assert job["persona"] == "asa"
    assert job["requested_provider"] == "local"
    assert job["requested_model"] == "dry-run"
    assert job["request_payload"]["task"] == "extract_memory_metadata"
    assert job["request_payload"]["policy"]["content_is_untrusted"] is True
    assert "Sidecar queue target body." in job["request_payload"]["wrapped_content"]

    events = memory_audit_query(conn, event_type="memory_enhancement_enqueued", persona="asa")
    assert len(events) == 1
    assert events[0]["payload"]["job_id"] == job["job_id"]


def test_memory_enhancement_enqueue_dedupes_active_job(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)

    first = memory_enhancement_enqueue(conn, file_path="target.md")
    second = memory_enhancement_enqueue(conn, file_path="target.md")

    assert first["enqueued"] is True
    assert second["enqueued"] is False
    assert second["job"]["job_id"] == first["job"]["job_id"]


def test_memory_enhancement_claim_and_complete_success(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)
    enqueued = memory_enhancement_enqueue(conn, file_path="target.md")

    claimed = memory_enhancement_claim_next(conn, persona="asa")

    assert claimed is not None
    assert claimed["job_id"] == enqueued["job"]["job_id"]
    assert claimed["status"] == "running"
    assert claimed["attempt_count"] == 1
    assert claimed["locked_at"]

    completed = memory_enhancement_complete(
        conn,
        job_id=claimed["job_id"],
        status="succeeded",
        response_payload={
            "memory_type": "lesson",
            "summary": "Queue outputs stay review gated.",
            "topics": ["queue", "sidecar"],
            "people": ["Charles"],
            "projects": ["PA"],
            "tools": ["Codex"],
            "confidence": 0.88,
        },
    )

    assert completed["ok"] is True
    job = completed["job"]
    assert job["status"] == "succeeded"
    assert job["locked_at"] is None
    assert job["result_payload"]["memory_type"] == "lesson"
    assert job["result_payload"]["review_status"] == "pending"
    assert job["result_payload"]["can_use_as_instruction"] is False
    assert memory_entity_query(conn, query="Charles", entity_type="person")[0]["file_count"] == 1
    assert memory_entity_query(conn, query="PA", entity_type="project")[0]["file_count"] == 1
    connections = memory_entity_connections(conn, entity_name="Charles", entity_type="person")
    assert {row["canonical_name"] for row in connections} == {"PA", "Codex", "queue", "sidecar"}

    events = memory_audit_query(conn, persona="asa")
    event_types = {event["event_type"] for event in events}
    assert "memory_enhancement_started" in event_types
    assert "memory_enhancement_completed" in event_types
    completed_events = [event for event in events if event["event_type"] == "memory_enhancement_completed"]
    assert completed_events[0]["payload"]["entities"] == {"link_count": 5, "edge_count": 10}


def test_memory_enhancement_claim_loser_returns_none(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)
    enqueued = memory_enhancement_enqueue(conn, file_path="target.md")

    class RacingConnection:
        def __init__(self, wrapped: sqlite3.Connection, job_id: int) -> None:
            self._wrapped = wrapped
            self._job_id = job_id
            self._raced = False

        def execute(self, sql, params=()):
            if not self._raced and "UPDATE memory_enhancement_jobs" in sql and "status = 'running'" in sql:
                self._raced = True
                self._wrapped.execute(
                    "UPDATE memory_enhancement_jobs SET status = 'running' WHERE job_id = ?",
                    (self._job_id,),
                )
            return self._wrapped.execute(sql, params)

        def commit(self) -> None:
            self._wrapped.commit()

    racing_conn = RacingConnection(conn, enqueued["job"]["job_id"])

    assert memory_enhancement_claim_next(racing_conn, persona="asa") is None
    job = conn.execute(
        "SELECT status, attempt_count FROM memory_enhancement_jobs WHERE job_id = ?",
        (enqueued["job"]["job_id"],),
    ).fetchone()
    assert job == ("running", 0)
    events = memory_audit_query(conn, event_type="memory_enhancement_started", persona="asa")
    assert events == []


def test_memory_enhancement_complete_failure_records_error(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)
    enqueued = memory_enhancement_enqueue(conn, file_path="target.md")
    claimed = memory_enhancement_claim_next(conn)

    result = memory_enhancement_complete(
        conn,
        job_id=claimed["job_id"],
        status="failed",
        error="model unavailable",
    )

    assert result["ok"] is True
    assert result["job"]["status"] == "failed"
    assert result["job"]["error"] == "model unavailable"
    assert result["job"]["job_id"] == enqueued["job"]["job_id"]

    events = memory_audit_query(conn, event_type="memory_enhancement_failed", persona="asa")
    assert len(events) == 1


def test_memory_worker_claims_job_with_scoped_payload(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)
    enqueued = memory_enhancement_enqueue(conn, file_path="target.md", requested_provider="openai")

    result = memory_worker_claim_next(
        conn,
        worker_id="codex-worker-1",
        capability="enhancement",
        persona="asa",
        provider="openai",
    )

    assert result["ok"] is True
    assert result["job"]["job_id"] == enqueued["job"]["job_id"]
    assert result["job"]["status"] == "running"
    assert result["job"]["locked_by_worker"] == "codex-worker-1"
    assert result["worker_request"]["schema_version"] == "chimera-memory.worker.enhance.v1"
    assert result["worker_request"]["source_ref"]["kind"] == "memory_file"
    assert "UNTRUSTED MEMORY CONTENT" in result["worker_request"]["content"]["text"]
    heartbeat = conn.execute(
        "SELECT status, current_job_id FROM memory_worker_heartbeats WHERE worker_id = ?",
        ("codex-worker-1",),
    ).fetchone()
    assert heartbeat == ("running", enqueued["job"]["job_id"])
    events = memory_audit_query(conn, event_type="memory_worker_job_claimed", persona="asa")
    assert events[0]["payload"]["worker_id"] == "codex-worker-1"


def test_memory_worker_submit_result_requires_job_ownership(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)
    memory_enhancement_enqueue(conn, file_path="target.md")
    claimed = memory_worker_claim_next(conn, worker_id="owner-worker")

    rejected = memory_worker_submit_result(
        conn,
        worker_id="other-worker",
        job_id=claimed["job"]["job_id"],
        status="succeeded",
        result_payload={"summary": "Nope."},
    )

    assert rejected["ok"] is False
    assert rejected["error"] == "worker does not own this job"
    job = conn.execute(
        "SELECT status, locked_by_worker FROM memory_enhancement_jobs WHERE job_id = ?",
        (claimed["job"]["job_id"],),
    ).fetchone()
    assert job == ("running", "owner-worker")


def test_memory_worker_submit_result_completes_owned_job(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)
    memory_enhancement_enqueue(conn, file_path="target.md")
    claimed = memory_worker_claim_next(conn, worker_id="owner-worker")

    result = memory_worker_submit_result(
        conn,
        worker_id="owner-worker",
        job_id=claimed["job"]["job_id"],
        status="succeeded",
        result_payload={
            "memory_type": "lesson",
            "summary": "Worker protocol returns strict JSON.",
            "topics": ["memory-enhancement"],
            "confidence": 0.9,
        },
        actual_provider="openai",
        actual_model="gpt-test",
        diagnostics={"latency_ms": 123},
    )

    assert result["ok"] is True
    assert result["job"]["status"] == "succeeded"
    assert result["job"]["locked_by_worker"] == ""
    assert result["job"]["actual_provider"] == "openai"
    assert result["job"]["result_payload"]["summary"] == "Worker protocol returns strict JSON."
    heartbeat = conn.execute(
        "SELECT status, current_job_id FROM memory_worker_heartbeats WHERE worker_id = ?",
        ("owner-worker",),
    ).fetchone()
    assert heartbeat == ("idle", "")
    events = memory_audit_query(conn, event_type="memory_worker_result_submitted", persona="asa")
    assert events[0]["payload"]["diagnostics"] == {"latency_ms": 123}


def test_memory_worker_submit_result_rejects_unknown_fields(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)
    memory_enhancement_enqueue(conn, file_path="target.md")
    claimed = memory_worker_claim_next(conn, worker_id="owner-worker")

    result = memory_worker_submit_result(
        conn,
        worker_id="owner-worker",
        job_id=claimed["job"]["job_id"],
        status="succeeded",
        result_payload={"summary": "ok", "write_this_file": "no"},
    )

    assert result["ok"] is False
    assert "unknown result fields" in result["error"]
    job = conn.execute(
        "SELECT status, locked_by_worker FROM memory_enhancement_jobs WHERE job_id = ?",
        (claimed["job"]["job_id"],),
    ).fetchone()
    assert job == ("running", "owner-worker")


def test_memory_worker_heartbeat_and_budget() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    heartbeat = memory_worker_heartbeat(
        conn,
        worker_id="worker-1",
        capability="enhancement",
        provider="openai",
        status="idle",
        metadata={"pid": 123},
    )
    budget = memory_worker_budget(conn, worker_id="worker-1", provider="openai")

    assert heartbeat["ok"] is True
    assert heartbeat["heartbeat"]["metadata"] == {"pid": 123}
    assert budget["ok"] is True
    assert budget["mode"] == "configured_caps_only"
    assert budget["budget"]["max_output_tokens"] > 0


def test_memory_enhancement_enqueue_authored_builds_pending_job() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = memory_enhancement_enqueue_authored(
        conn,
        persona="asa",
        memory_payload={
            "memory_type": "procedural",
            "lessons": [{"teaching": "Structured payloads own the memory."}],
            "next_steps": [{"action": "Keep LLM enrichment narrow"}],
        },
        provenance={"status": "generated"},
        source_ref="day61/structured-writeback",
        requested_provider="local",
        requested_model="dry-run",
    )

    assert result["ok"] is True
    job = result["job"]
    assert job["file_id"] is None
    assert job["path"] == "day61/structured-writeback"
    assert job["requested_provider"] == "local"
    assert job["requested_model"] == "dry-run"
    assert job["request_payload"]["task"] == "enrich_authored_memory_payload"
    assert job["request_payload"]["contract"]["action_items"] == ["Keep LLM enrichment narrow"]

    events = memory_audit_query(conn, event_type="memory_enhancement_authored_enqueued", persona="asa")
    assert len(events) == 1
    assert events[0]["payload"]["job_id"] == job["job_id"]


def test_memory_enhancement_complete_authored_uses_agent_fields() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    enqueued = memory_enhancement_enqueue_authored(
        conn,
        persona="asa",
        memory_payload={
            "memory_type": "episode",
            "summary": "Structured writeback was added beside legacy enhancement.",
            "lessons": [{"teaching": "Agent-authored payloads are authoritative."}],
            "next_steps": [{"action": "Preserve structured writeback discipline"}],
            "entities": {"topics": ["writeback discipline"], "projects": ["ChimeraMemory"]},
        },
        provenance={"status": "generated"},
        source_ref="day61/structured-writeback",
    )
    claimed = memory_enhancement_claim_next(conn, persona="asa")

    completed = memory_enhancement_complete(
        conn,
        job_id=claimed["job_id"],
        status="succeeded",
        response_payload={
            "memory_type": "semantic",
            "summary": "Model summary must not win.",
            "action_items": ["Model action must not win."],
            "topics": ["memory enhancement", "not-in-enum"],
            "people": ["Charles"],
            "confidence": 0.8,
        },
    )

    assert completed["ok"] is True
    assert completed["job"]["job_id"] == enqueued["job"]["job_id"]
    result_payload = completed["job"]["result_payload"]
    assert result_payload["schema_version"] == "chimera-memory.authored-writeback.v1"
    assert result_payload["memory_type"] == "episodic"
    assert result_payload["summary"] == "Structured writeback was added beside legacy enhancement."
    assert result_payload["action_items"] == ["Preserve structured writeback discipline"]
    assert result_payload["topics"] == ["writeback-discipline", "memory-enhancement"]
    assert result_payload["people"] == ["Charles"]
    assert result_payload["can_use_as_instruction"] is False
    assert result_payload["review_status"] == "pending"
    assert result_payload["enrichment_status"] == "complete"
    assert memory_entity_query(conn, query="Charles", entity_type="person") == []


def test_memory_enhancement_enqueue_reports_missing_file() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = memory_enhancement_enqueue(conn, file_path="missing.md")

    assert result == {
        "ok": False,
        "error": "memory file not found",
        "file_path": "missing.md",
    }
