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
    memory_worker_has_pending_job,
    memory_worker_heartbeat,
    memory_worker_submit_result,
    memory_entity_connections,
    memory_entity_query,
)
from chimera_memory.memory_enhancement_queue import safe_enhancement_receipt


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


def test_safe_enhancement_receipt_redacts_body_and_raw_paths(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)

    result = memory_enhancement_enqueue(conn, file_path="target.md")
    safe = safe_enhancement_receipt(result)
    serialized = str(safe).replace("\\", "/")

    assert result["job"]["path"].replace("\\", "/").startswith(str(tmp_path).replace("\\", "/"))
    assert "Sidecar queue target body." in result["job"]["request_payload"]["wrapped_content"]
    assert str(tmp_path).replace("\\", "/") not in serialized
    assert "Sidecar queue target body." not in serialized
    assert safe["job"]["path"] == "target.md"
    assert safe["job"]["path_fingerprint"]
    assert safe["job"]["request_payload"]["task"] == "extract_memory_metadata"
    assert "wrapped_content" in safe["job"]["request_payload"]["redacted_fields"]


def test_memory_enhancement_enqueue_dedupes_active_job(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)

    first = memory_enhancement_enqueue(conn, file_path="target.md")
    second = memory_enhancement_enqueue(conn, file_path="target.md")

    assert first["enqueued"] is True
    assert second["enqueued"] is False
    assert second["job"]["job_id"] == first["job"]["job_id"]


def test_memory_enhancement_enqueue_debounces_recent_same_fingerprint(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)

    first = memory_enhancement_enqueue(conn, file_path="target.md")
    claimed = memory_enhancement_claim_next(conn, persona="asa")
    assert claimed is not None
    memory_enhancement_complete(
        conn,
        job_id=claimed["job_id"],
        status="succeeded",
        response_payload={"summary": "Done.", "confidence": 0.8},
    )

    second = memory_enhancement_enqueue(conn, file_path="target.md")

    assert first["enqueued"] is True
    assert second["enqueued"] is False
    assert second["reason"] == "recent_duplicate"
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


def test_memory_worker_has_pending_job_filters_persona_and_provider(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)
    memory_enhancement_enqueue(conn, file_path="target.md", requested_provider="anthropic")

    assert memory_worker_has_pending_job(conn, persona="asa", provider="anthropic") is True
    assert memory_worker_has_pending_job(conn, persona="asa", provider="openai") is False
    assert memory_worker_has_pending_job(conn, persona="sarah", provider="anthropic") is False
    assert memory_worker_has_pending_job(conn, persona="asa") is True


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
    usage = conn.execute(
        """
        SELECT provider, transport, credential_mode, worker_id, job_id,
               status, tokens_in, tokens_out, latency_ms
        FROM memory_provider_usage_events
        """
    ).fetchone()
    # ec-06: CLI worker usage is BYOK, not user-OAuth; the ledger must reflect that.
    assert usage == ("openai", "cli_worker", "byok", "owner-worker", claimed["job"]["job_id"], "succeeded", 0, 0, 123)


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
        actual_provider="google",
    )

    assert result["ok"] is False
    assert "unknown result fields" in result["error"]
    job = conn.execute(
        "SELECT status, locked_by_worker FROM memory_enhancement_jobs WHERE job_id = ?",
        (claimed["job"]["job_id"],),
    ).fetchone()
    assert job == ("running", "owner-worker")


def test_memory_worker_submit_result_requires_summary_and_provider_on_success(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_memory(conn, tmp_path)
    memory_enhancement_enqueue(conn, file_path="target.md")
    claimed = memory_worker_claim_next(conn, worker_id="owner-worker")

    missing_provider = memory_worker_submit_result(
        conn,
        worker_id="owner-worker",
        job_id=claimed["job"]["job_id"],
        status="succeeded",
        result_payload={"summary": "Useful metadata."},
    )
    empty_summary = memory_worker_submit_result(
        conn,
        worker_id="owner-worker",
        job_id=claimed["job"]["job_id"],
        status="succeeded",
        result_payload={"summary": ""},
        actual_provider="google",
    )

    assert missing_provider["ok"] is False
    assert missing_provider["error"] == "actual_provider is required for succeeded worker result"
    assert empty_summary["ok"] is False
    assert empty_summary["error"] == "summary is required for succeeded worker result"
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
    assert budget["mode"] == "shared_provider_governor"
    assert budget["budget"]["max_output_tokens"] > 0


def test_memory_worker_heartbeat_preserves_provider_when_later_heartbeat_omits_it() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    memory_worker_heartbeat(conn, worker_id="worker-1", provider="google", status="running")
    heartbeat = memory_worker_heartbeat(conn, worker_id="worker-1", status="idle")

    assert heartbeat["ok"] is True
    assert heartbeat["heartbeat"]["provider"] == "google"
    assert heartbeat["heartbeat"]["status"] == "idle"


def test_memory_worker_budget_uses_shared_provider_governor(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_PER_MINUTE_CALL_CAP", "1")
    conn.execute(
        """
        INSERT INTO memory_provider_usage_events (provider, transport, worker_id, status)
        VALUES ('openai', 'cli_worker', 'worker-1', 'succeeded')
        """
    )
    conn.commit()

    budget = memory_worker_budget(conn, worker_id="worker-1", provider="openai")

    assert budget["ok"] is True
    assert budget["allowed"] is False
    assert budget["reason"] == "per_minute_call_cap"
    assert budget["usage"]["minute"] == 1


def test_memory_worker_budget_resolves_empty_provider_from_order(monkeypatch) -> None:
    # ec-09: a worker that omits --provider must not short-circuit the governor;
    # the gate resolves the configured provider and evaluates its real caps.
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER", "openai")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_PER_MINUTE_CALL_CAP", "1")
    conn.execute(
        """
        INSERT INTO memory_provider_usage_events (provider, transport, worker_id, status)
        VALUES ('openai', 'cli_worker', 'worker-1', 'succeeded')
        """
    )
    conn.commit()

    budget = memory_worker_budget(conn, worker_id="worker-1", provider="")

    assert budget["provider"] == "openai"
    assert budget["allowed"] is False
    assert budget["reason"] == "per_minute_call_cap"


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


def test_memory_enhancement_enqueue_authored_dedupes_without_file_id() -> None:
    # ec-10: a file_id-less authored enqueue (e.g. CLI enqueue-authored) must
    # dedupe on the content fingerprint instead of accumulating duplicate jobs.
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    kwargs = dict(
        persona="asa",
        memory_payload={
            "memory_type": "procedural",
            "lessons": [{"teaching": "Dedupe authored enqueues without a file id."}],
        },
        provenance={"status": "generated"},
        source_ref="day62/authored-dedupe",
    )

    first = memory_enhancement_enqueue_authored(conn, **kwargs)
    second = memory_enhancement_enqueue_authored(conn, **kwargs)

    assert first["enqueued"] is True
    assert second["enqueued"] is False
    assert second["job"]["job_id"] == first["job"]["job_id"]
    pending = conn.execute(
        "SELECT COUNT(*) FROM memory_enhancement_jobs WHERE file_id IS NULL AND status = 'pending'"
    ).fetchone()[0]
    assert pending == 1


def test_safe_enhancement_receipt_redacts_worker_request() -> None:
    # ec-08: a claim result carries raw wrapped content + an absolute source path;
    # safe_enhancement_receipt must drop the body and redact the path.
    receipt = {
        "worker_request": {
            "source_ref": {"path": "C:/Users/charl/secret/notes.md"},
            "content": {"text": "raw body referencing C:/Users/charl/secret/notes.md"},
        }
    }

    safe = safe_enhancement_receipt(receipt)

    wr = safe["worker_request"]
    assert wr["content"]["text"] == ""
    assert wr["content"]["redacted"] is True
    assert wr["content"]["chars"] > 0
    assert "C:/Users/charl/secret" not in str(wr["source_ref"]["path"])


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
