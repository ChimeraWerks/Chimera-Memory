import sqlite3
import json
from datetime import datetime, timezone

import chimera_memory.config as config
from chimera_memory.db import SCHEMA_SQL
from chimera_memory.embeddings import init_embedding_table, pack_embedding
from chimera_memory.memory import index_file, init_memory_tables, memory_audit_query
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


def _write_memory(path, frontmatter: list[str]) -> None:
    path.write_text(
        "\n".join(["---", "type: procedural", "importance: 8", *frontmatter, "---", path.stem, ""]),
        encoding="utf-8",
    )


def test_health_marks_missing_embeddings_not_built_then_ok() -> None:
    conn = _conn()
    transcript_id = _insert_transcript(conn)

    snapshot = collect_cm_health(conn, persona="asa")

    # A never-embedded install is 'not_built', not 'broken' (se-06): the embed
    # worker simply has not run yet, so it must not escalate the overall status.
    assert snapshot["status"] != "broken"
    assert snapshot["checks"]["embeddings"]["status"] == "not_built"
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

    snapshot = collect_cm_health(conn, persona="asa", repair_session_rollups=False)

    assert snapshot["checks"]["session_rollups"]["status"] == "broken"
    assert snapshot["checks"]["session_rollups"]["zero_exchange_sessions_with_rows"] == 1
    assert snapshot["checks"]["duplicate_capture"]["status"] == "degraded"
    assert snapshot["checks"]["duplicate_capture"]["duplicate_groups"] == 1


def test_health_auto_repairs_session_rollup_drift() -> None:
    conn = _conn()
    transcript_id = _insert_transcript(conn, session_id="stale")
    conn.execute(
        "INSERT INTO transcript_embeddings (transcript_id, embedding) VALUES (?, ?)",
        (transcript_id, pack_embedding([0.0] * 384)),
    )
    conn.execute(
        "INSERT INTO sessions (session_id, persona, started_at, ended_at, exchange_count) VALUES (?, ?, ?, ?, ?)",
        ("stale", "asa", "2026-05-19T20:00:00Z", "2026-05-19T20:00:00Z", 23),
    )
    conn.commit()

    snapshot = collect_cm_health(conn, persona="asa")

    assert snapshot["status"] == "ok"
    assert snapshot["checks"]["session_rollups"]["status"] == "ok"
    assert snapshot["checks"]["session_rollups"]["mismatch_count"] == 0
    assert snapshot["checks"]["session_rollups"]["auto_repaired_count"] == 1
    assert conn.execute("SELECT exchange_count FROM sessions WHERE session_id = 'stale'").fetchone()[0] == 1


def test_health_allows_non_conversation_zero_exchange_sessions() -> None:
    conn = _conn()
    _insert_transcript(conn, session_id="system-only", entry_type="system")
    conn.execute(
        "INSERT INTO sessions (session_id, persona, started_at, ended_at, exchange_count) VALUES (?, ?, ?, ?, ?)",
        ("system-only", "asa", "2026-05-19T20:00:00Z", "2026-05-19T20:00:00Z", 0),
    )
    conn.commit()

    snapshot = collect_cm_health(conn, persona="asa")

    assert snapshot["checks"]["session_rollups"]["status"] == "ok"
    assert snapshot["checks"]["session_rollups"]["zero_exchange_sessions_with_rows"] == 0


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


def test_health_snapshot_records_safe_provider_profile_and_drift(monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER", "openai,dry_run")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF", "oauth:openai-memory")
    monkeypatch.delenv("CHIMERA_MEMORY_ENHANCEMENT_ANTHROPIC_CREDENTIAL_REF", raising=False)
    conn = _conn()
    memory_enhancement_enqueue_authored(
        conn,
        persona="global",
        memory_payload={"memory_type": "procedural", "lessons": [{"teaching": "provider drift test"}]},
        source_ref="test",
        requested_provider="anthropic",
    )

    snapshot = collect_cm_health(conn)
    profile = snapshot["provider_profile"]
    text = format_cm_health(snapshot)
    serialized = json.dumps(snapshot)

    assert profile == {
        "status": "ok",
        "selected_provider": "openai",
        "selected_model": "gpt-5.3-codex-spark",
        "provider_affinity": "",
        "credential_ref_present": True,
        "uses_user_oauth": True,
        "requires_network": True,
        "live": False,
    }
    assert snapshot["checks"]["provider_drift"]["selected_provider"] == "openai"
    assert snapshot["checks"]["provider_drift"]["drift_count"] == 1
    assert "provider_profile: provider=openai model=gpt-5.3-codex-spark" in text
    assert "oauth:openai-memory" not in serialized
    assert "provider drift test" not in serialized


def test_health_snapshot_records_sanitized_codex_runtime_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    for key in (
        "TRANSCRIPT_PERSONA",
        "CHIMERA_PERSONA_ID",
        "CHIMERA_MEMORY_PROJECT_ROOTS",
    ):
        monkeypatch.delenv(key, raising=False)
    project_root = tmp_path / "repo" / ".chimera-memory"
    global_root = tmp_path / "global-memory"
    project_root.mkdir(parents=True)
    global_root.mkdir()
    global_ok = tmp_path / "global-ok.md"
    global_confirmed = tmp_path / "global-confirmed.md"
    global_auto_confirmed = tmp_path / "global-auto-confirmed.md"
    global_imported_confirmed = tmp_path / "global-imported-confirmed.md"
    global_restricted = tmp_path / "global-restricted.md"
    project_memory = tmp_path / "project.md"
    _write_memory(global_ok, [])
    _write_memory(
        global_confirmed,
        [
            "provenance_status: user_confirmed",
            "review_status: confirmed",
            "can_use_as_instruction: true",
            "requires_user_confirmation: false",
        ],
    )
    _write_memory(
        global_auto_confirmed,
        [
            "provenance_status: auto_confirmed",
            "review_status: confirmed",
            "can_use_as_instruction: true",
            "requires_user_confirmation: false",
        ],
    )
    _write_memory(
        global_imported_confirmed,
        [
            "provenance_status: imported",
            "review_status: confirmed",
            "can_use_as_instruction: true",
            "requires_user_confirmation: false",
        ],
    )
    _write_memory(global_restricted, ["sensitivity_tier: restricted"])
    _write_memory(project_memory, [])
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "Chimera-Memory")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))

    conn = _conn()
    assert index_file(conn, "global", "memory/global-ok.md", global_ok)
    assert index_file(conn, "global", "memory/global-confirmed.md", global_confirmed)
    assert index_file(conn, "global", "memory/global-auto-confirmed.md", global_auto_confirmed)
    assert index_file(conn, "global", "memory/global-imported-confirmed.md", global_imported_confirmed)
    assert index_file(conn, "global", "memory/global-restricted.md", global_restricted)
    assert index_file(conn, "project:Chimera-Memory", "memory/project.md", project_memory)

    snapshot = collect_cm_health(conn)
    profile = snapshot["runtime_profile"]
    serialized = json.dumps(profile)
    text = format_cm_health(snapshot)

    assert profile["status"] == "ok"
    assert profile["client"] == "codex"
    assert profile["mcp_surface"] == "codex"
    assert profile["memory_profile"] == "project"
    assert profile["transcript_persona_set"] is False
    assert profile["project_id"] == "Chimera-Memory"
    assert profile["project_root_configured"] is True
    assert profile["global_root_source"] == "env"
    assert profile["global_root_exists"] is True
    assert profile["global_indexed_file_count"] == 5
    assert profile["global_available_file_count"] == 4
    assert profile["global_instruction_grade_file_count"] == 2
    assert profile["persona_tree_indexing"] is False
    assert str(tmp_path) not in serialized
    assert "global_available_files=4/5" in text
    assert "global_instruction_grade_files=2/4" in text
    assert str(tmp_path) not in text


def test_health_escalates_when_runtime_profile_unavailable(monkeypatch) -> None:
    # ghh-12: a masked runtime-profile fault must escalate the overall status
    # (not silently report 'ok') and surface a leak-safe class-name reason.
    conn = _conn()
    monkeypatch.setattr(
        "chimera_memory.memory_health._runtime_profile",
        lambda conn, persona: {"status": "unavailable", "reason": "OperationalError"},
    )

    snapshot = collect_cm_health(conn, persona="asa")

    assert snapshot["status"] == "degraded"
    assert snapshot["runtime_profile"]["reason"] == "OperationalError"
    assert "/" not in snapshot["runtime_profile"]["reason"]
    assert "\\" not in snapshot["runtime_profile"]["reason"]
