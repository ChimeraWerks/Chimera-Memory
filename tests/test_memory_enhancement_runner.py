import sqlite3
from pathlib import Path

from chimera_memory.memory import (
    index_file,
    init_memory_tables,
    memory_enhancement_enqueue,
)
from chimera_memory.memory_enhancement_runner import (
    COST_CAP_MAX_DEFERRALS,
    StaticMemoryEnhancementClient,
    run_memory_enhancement_provider_batch,
)
from chimera_memory.memory_enhancement_model_client import MemoryEnhancementCostCapError


def _index_runner_memory(conn: sqlite3.Connection, tmp_path: Path, name: str = "runner.md") -> None:
    memory_file = tmp_path / name
    memory_file.write_text(
        "\n".join(
            [
                "---",
                "type: semantic",
                "importance: 6",
                "---",
                "Provider runner should enrich queued metadata without seeing raw credentials.",
            ]
        ),
        encoding="utf-8",
    )
    assert index_file(conn, "asa", name, memory_file)


def test_provider_runner_processes_job_with_injected_client(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_runner_memory(conn, tmp_path)
    enqueued = memory_enhancement_enqueue(conn, file_path="runner.md")
    client = StaticMemoryEnhancementClient(
        [
            {
                "memory_type": "lesson",
                "summary": "Use injected clients for provider work.",
                "topics": ["provider", "sidecar"],
                "confidence": 0.82,
            }
        ]
    )

    receipt = run_memory_enhancement_provider_batch(
        conn,
        client=client,
        env={"CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF": "oauth:openai-memory"},
        persona="asa",
    )

    assert receipt["processed_count"] == 1
    assert receipt["failure_count"] == 0
    assert receipt["llm_call_count"] == 1
    assert receipt["processed"][0]["job_id"] == enqueued["job"]["job_id"]
    assert receipt["provider"]["selected_provider"] == "openai"
    assert "oauth:openai-memory" not in str(receipt)
    assert client.invocations[0]["provider"]["credential_ref"] == "oauth:openai-memory"

    row = conn.execute(
        """
        SELECT status, result_payload, error, actual_provider, actual_model
        FROM memory_enhancement_jobs
        WHERE job_id = ?
        """,
        (enqueued["job"]["job_id"],),
    ).fetchone()
    assert row[0] == "succeeded"
    assert row[2] == ""
    assert row[3] == "openai"
    assert row[4] == "gpt-5.3-codex-spark"
    assert "Use injected clients" in row[1]
    assert '"can_use_as_instruction": false' in row[1]


def test_provider_runner_records_sanitized_failure(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_runner_memory(conn, tmp_path)
    enqueued = memory_enhancement_enqueue(conn, file_path="runner.md")
    client = StaticMemoryEnhancementClient([RuntimeError("unauthorized raw-token-value")])

    receipt = run_memory_enhancement_provider_batch(
        conn,
        client=client,
        env={"CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF": "oauth:openai-memory"},
        persona="asa",
    )

    assert receipt["processed_count"] == 0
    assert receipt["failure_count"] == 1
    assert receipt["failures"][0]["failure_category"] == "auth_error"
    assert "raw-token-value" not in str(receipt)

    row = conn.execute(
        """
        SELECT status, result_payload, error, actual_provider, actual_model
        FROM memory_enhancement_jobs
        WHERE job_id = ?
        """,
        (enqueued["job"]["job_id"],),
    ).fetchone()
    assert row[0] == "failed"
    assert row[2] == "auth_error"
    assert row[3] == "openai"
    assert row[4] == "gpt-5.3-codex-spark"
    assert "auth_error" in row[1]
    assert "raw-token-value" not in row[1]


def test_provider_runner_respects_budget_job_limit(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_runner_memory(conn, tmp_path, "one.md")
    _index_runner_memory(conn, tmp_path, "two.md")
    memory_enhancement_enqueue(conn, file_path="one.md")
    memory_enhancement_enqueue(conn, file_path="two.md")
    client = StaticMemoryEnhancementClient(
        [
            {"memory_type": "semantic", "summary": "first"},
            {"memory_type": "semantic", "summary": "second"},
        ]
    )

    receipt = run_memory_enhancement_provider_batch(
        conn,
        client=client,
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "dry_run",
            "CHIMERA_MEMORY_ENHANCEMENT_MAX_JOBS_PER_RUN": "1",
        },
        limit=10,
    )

    assert receipt["processed_count"] == 1
    assert len(client.invocations) == 1
    statuses = [
        row[0]
        for row in conn.execute(
            "SELECT status FROM memory_enhancement_jobs ORDER BY path"
        ).fetchall()
    ]
    assert statuses == ["succeeded", "pending"]


def test_provider_runner_respects_hard_llm_call_cap_before_claiming(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_runner_memory(conn, tmp_path, "one.md")
    _index_runner_memory(conn, tmp_path, "two.md")
    memory_enhancement_enqueue(conn, file_path="one.md")
    memory_enhancement_enqueue(conn, file_path="two.md")
    client = StaticMemoryEnhancementClient(
        [
            {"memory_type": "semantic", "summary": "first"},
            {"memory_type": "semantic", "summary": "second"},
        ]
    )

    receipt = run_memory_enhancement_provider_batch(
        conn,
        client=client,
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "dry_run",
            "CHIMERA_MEMORY_ENHANCEMENT_MAX_JOBS_PER_RUN": "10",
            "CHIMERA_MEMORY_ENHANCEMENT_PER_MINUTE_CALL_CAP": "10",
            "CHIMERA_MEMORY_ENHANCEMENT_MAX_LLM_CALLS_PER_RUN": "0",
        },
        limit=10,
    )

    assert receipt["processed_count"] == 0
    assert receipt["failure_count"] == 0
    assert receipt["llm_call_count"] == 0
    assert receipt["llm_call_cap"] == 0
    assert client.invocations == []
    statuses = [
        row[0]
        for row in conn.execute(
            "SELECT status FROM memory_enhancement_jobs ORDER BY path"
        ).fetchall()
    ]
    assert statuses == ["pending", "pending"]


def test_provider_runner_respects_shared_provider_governor_before_claiming(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_runner_memory(conn, tmp_path, "one.md")
    memory_enhancement_enqueue(conn, file_path="one.md")
    conn.execute(
        """
        INSERT INTO memory_provider_usage_events (provider, transport, status)
        VALUES ('openai', 'http_oauth', 'succeeded')
        """
    )
    conn.commit()
    client = StaticMemoryEnhancementClient([{"memory_type": "semantic", "summary": "first"}])

    receipt = run_memory_enhancement_provider_batch(
        conn,
        client=client,
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF": "oauth:openai-memory",
            "CHIMERA_MEMORY_ENHANCEMENT_PER_MINUTE_CALL_CAP": "1",
        },
        limit=10,
    )

    assert receipt["processed_count"] == 0
    assert receipt["failure_count"] == 0
    assert receipt["llm_call_count"] == 0
    assert receipt["governor_stopped"] is True
    assert receipt["governor"]["reason"] == "per_minute_call_cap"
    assert client.invocations == []
    row = conn.execute("SELECT status, locked_at FROM memory_enhancement_jobs").fetchone()
    assert row == ("pending", None)


def test_provider_runner_respects_wall_clock_budget_before_next_claim(
    monkeypatch, tmp_path: Path
) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_runner_memory(conn, tmp_path, "one.md")
    _index_runner_memory(conn, tmp_path, "two.md")
    memory_enhancement_enqueue(conn, file_path="one.md")
    memory_enhancement_enqueue(conn, file_path="two.md")
    client = StaticMemoryEnhancementClient(
        [
            {"memory_type": "semantic", "summary": "first"},
            {"memory_type": "semantic", "summary": "second"},
        ]
    )
    ticks = iter([0.0, 0.0, 2.0, 2.0])
    monkeypatch.setattr(
        "chimera_memory.memory_enhancement_runner.time.monotonic",
        lambda: next(ticks),
    )

    receipt = run_memory_enhancement_provider_batch(
        conn,
        client=client,
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "dry_run",
            "CHIMERA_MEMORY_ENHANCEMENT_MAX_JOBS_PER_RUN": "10",
            "CHIMERA_MEMORY_ENHANCEMENT_MAX_RUN_SECONDS": "1",
        },
        limit=10,
    )

    assert receipt["processed_count"] == 1
    assert receipt["wall_clock_stopped"] is True
    assert receipt["wall_clock_budget_seconds"] == 1.0
    assert len(client.invocations) == 1
    statuses = [
        row[0]
        for row in conn.execute(
            "SELECT status FROM memory_enhancement_jobs ORDER BY path"
        ).fetchall()
    ]
    assert statuses == ["succeeded", "pending"]


def test_provider_runner_defers_claimed_job_when_client_cost_cap_hits(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_runner_memory(conn, tmp_path, "one.md")
    memory_enhancement_enqueue(conn, file_path="one.md")
    client = StaticMemoryEnhancementClient(
        [
            MemoryEnhancementCostCapError("memory enhancement cost cap reached: 1 calls"),
        ]
    )

    receipt = run_memory_enhancement_provider_batch(
        conn,
        client=client,
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "dry_run",
            "CHIMERA_MEMORY_ENHANCEMENT_MAX_LLM_CALLS_PER_RUN": "10",
        },
    )

    assert receipt["processed_count"] == 0
    assert receipt["failure_count"] == 1
    assert receipt["failures"][0]["status"] == "deferred"
    row = conn.execute("SELECT status, locked_at, error FROM memory_enhancement_jobs").fetchone()
    assert row == ("pending", None, "quota_exceeded")


def test_provider_runner_skips_poison_cost_cap_job_after_max_deferrals(tmp_path: Path) -> None:
    # ec-11: a job that trips the cost cap on every claim must be skipped after
    # COST_CAP_MAX_DEFERRALS instead of permanently heading the FIFO.
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_runner_memory(conn, tmp_path, "poison.md")
    enqueued = memory_enhancement_enqueue(conn, file_path="poison.md")
    conn.execute(
        "UPDATE memory_enhancement_jobs SET attempt_count = ? WHERE job_id = ?",
        (COST_CAP_MAX_DEFERRALS, enqueued["job"]["job_id"]),
    )
    conn.commit()
    client = StaticMemoryEnhancementClient(
        [MemoryEnhancementCostCapError("memory enhancement cost cap reached: 1 calls")]
    )

    receipt = run_memory_enhancement_provider_batch(
        conn,
        client=client,
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "dry_run",
            "CHIMERA_MEMORY_ENHANCEMENT_MAX_LLM_CALLS_PER_RUN": "10",
        },
    )

    assert receipt["failures"][0]["status"] == "skipped"
    assert receipt["failures"][0]["failure_category"] == "cost_cap_exhausted"
    row = conn.execute("SELECT status, error FROM memory_enhancement_jobs").fetchone()
    assert row == ("skipped", "cost_cap_exhausted")


def test_provider_runner_does_not_double_complete_on_persist_failure(tmp_path: Path, monkeypatch) -> None:
    # ec-03: if completing a succeeded job returns ok=False, the runner must not
    # fall through and re-complete it as failed (which would double-charge usage).
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    _index_runner_memory(conn, tmp_path, "persist.md")
    memory_enhancement_enqueue(conn, file_path="persist.md")
    client = StaticMemoryEnhancementClient(
        [{"memory_type": "lesson", "summary": "ok", "topics": ["x"], "confidence": 0.8}]
    )
    monkeypatch.setattr(
        "chimera_memory.memory_enhancement_runner.memory_enhancement_complete",
        lambda *args, **kwargs: {"ok": False},
    )

    receipt = run_memory_enhancement_provider_batch(
        conn,
        client=client,
        env={"CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF": "oauth:openai-memory"},
        persona="asa",
    )

    assert receipt["processed_count"] == 0
    assert receipt["failure_count"] == 1
    assert receipt["failures"][0]["status"] == "completion_persist_failed"
    # Exactly one usage row (the succeeded one), no second failed row / double charge.
    usage = conn.execute(
        "SELECT status, COUNT(*) FROM memory_provider_usage_events GROUP BY status"
    ).fetchall()
    assert usage == [("succeeded", 1)]
