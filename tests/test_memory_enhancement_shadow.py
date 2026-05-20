import sqlite3
from pathlib import Path

from chimera_memory.enhancement_worker import run_memory_enhancement_dry_run
from chimera_memory.memory import (
    full_reindex,
    index_file,
    init_memory_tables,
    memory_audit_query,
)
from chimera_memory.memory_enhancement_queue import (
    memory_enhancement_claim_next,
    memory_enhancement_complete,
    memory_enhancement_enqueue,
)
from chimera_memory.memory_enhancement_shadow import (
    memory_enhancement_auto_enqueue_enabled,
    memory_enhancement_shadow_enabled,
    memory_enhancement_shadow_enqueue,
    memory_enhancement_shadow_report,
)


def _write_memory(root: Path, name: str = "shadow.md", *, tags: str = "[shadow, pilot]") -> Path:
    memory_file = root / "personas" / "researcher" / "sarah" / "memory" / name
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text(
        "\n".join(
            [
                "---",
                "type: procedural",
                "importance: 7",
                f"tags: {tags}",
                "about: Existing summary stays authoritative.",
                "---",
                "Shadow pilot should enqueue this real memory file beside the current index.",
            ]
        ),
        encoding="utf-8",
    )
    return memory_file


def test_shadow_requires_explicit_mode_and_persona_allowlist() -> None:
    assert memory_enhancement_shadow_enabled(
        persona="sarah",
        env={"CHIMERA_MEMORY_ENHANCEMENT_SHADOW_MODE": "true"},
    ) is False
    assert memory_enhancement_shadow_enabled(
        persona="asa",
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_SHADOW_MODE": "true",
            "CHIMERA_MEMORY_ENHANCEMENT_SHADOW_PERSONAS": "sarah",
        },
    ) is False
    assert memory_enhancement_shadow_enabled(
        persona="sarah",
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_SHADOW_MODE": "true",
            "CHIMERA_MEMORY_ENHANCEMENT_SHADOW_PERSONAS": "sarah",
        },
    ) is True


def test_shadow_enqueue_is_noop_when_disabled(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    memory_file = tmp_path / "shadow.md"
    memory_file.write_text("---\ntype: semantic\n---\nbody\n", encoding="utf-8")
    assert index_file(conn, "sarah", "shadow.md", memory_file)

    result = memory_enhancement_shadow_enqueue(
        conn,
        file_path="shadow.md",
        persona="sarah",
        reason="test",
        env={},
    )

    assert result == {
        "ok": True,
        "enabled": False,
        "enqueued": False,
        "reason": "auto_enqueue_disabled",
    }
    assert conn.execute("SELECT COUNT(*) FROM memory_enhancement_jobs").fetchone()[0] == 0


def test_auto_enqueue_requires_explicit_mode_and_persona_allowlist() -> None:
    assert memory_enhancement_auto_enqueue_enabled(
        persona="sarah",
        env={"CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE": "true"},
    ) is False
    assert memory_enhancement_auto_enqueue_enabled(
        persona="asa",
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE": "true",
            "CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE_PERSONAS": "sarah",
        },
    ) is False
    assert memory_enhancement_auto_enqueue_enabled(
        persona="sarah",
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE": "true",
            "CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE_PERSONAS": "sarah",
        },
    ) is True


def test_auto_enqueue_queues_without_shadow_mode(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    memory_file = tmp_path / "memory.md"
    memory_file.write_text("---\ntype: semantic\n---\nbody\n", encoding="utf-8")
    assert index_file(conn, "asa", "memory.md", memory_file)

    result = memory_enhancement_shadow_enqueue(
        conn,
        file_path="memory.md",
        persona="asa",
        reason="test",
        env={
            "CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE": "true",
            "CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE_PERSONAS": "asa",
        },
    )

    assert result["enabled"] is True
    assert result["enqueued"] is True
    events = memory_audit_query(conn, event_type="memory_enhancement_shadow_enqueue", persona="asa")
    assert events[0]["payload"]["mode"] == "auto_enqueue"
    assert events[0]["payload"]["shadow_mode"] is False
    assert events[0]["payload"]["auto_enqueue"] is True


def test_full_reindex_auto_enqueues_allowed_shadow_persona(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "agency"
    _write_memory(root)
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_SHADOW_MODE", "true")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_SHADOW_PERSONAS", "sarah")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_SHADOW_PROVIDER", "dry_run")

    updated = full_reindex(conn, root / "personas", embed=False)

    assert updated == 1
    row = conn.execute(
        "SELECT status, persona, requested_provider FROM memory_enhancement_jobs"
    ).fetchone()
    assert row == ("pending", "sarah", "dry_run")
    events = memory_audit_query(conn, event_type="memory_enhancement_shadow_enqueue", persona="sarah")
    assert len(events) == 1
    assert events[0]["payload"]["reason"] == "full_reindex"


def test_shadow_enqueue_uses_resolved_provider_when_no_explicit_hint(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "agency"
    _write_memory(root)
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_SHADOW_MODE", "true")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_SHADOW_PERSONAS", "sarah")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER", "openai,anthropic,dry_run")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_ANTHROPIC_CREDENTIAL_REF", "oauth:anthropic-memory")

    full_reindex(conn, root / "personas", embed=False)

    row = conn.execute(
        "SELECT requested_provider, requested_model FROM memory_enhancement_jobs"
    ).fetchone()
    assert row == ("anthropic", "claude-haiku-4-5")
    events = memory_audit_query(conn, event_type="memory_enhancement_shadow_enqueue", persona="sarah")
    assert events[0]["payload"]["explicit_provider_hint"] is False


def test_shadow_report_compares_completed_metadata(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "agency"
    _write_memory(root, tags="[shadow, pilot]")
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_SHADOW_MODE", "true")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_SHADOW_PERSONAS", "sarah")
    full_reindex(conn, root / "personas", embed=False)

    processed = run_memory_enhancement_dry_run(conn, persona="sarah", limit=1)
    report = memory_enhancement_shadow_report(conn, persona="sarah", limit=5)

    assert len(processed) == 1
    assert report["totals"]["jobs"] == 1
    assert report["totals"]["succeeded"] == 1
    job = report["jobs"][0]
    assert job["status"] == "succeeded"
    comparison = job["comparison"]
    assert comparison["frontmatter_type"] == "procedural"
    assert comparison["type_match"] is True
    assert comparison["topic_overlap_count"] >= 2
    assert comparison["summary_present"] is True
    assert "Shadow pilot should enqueue" not in str(report)


def test_shadow_report_treats_episode_and_episodic_as_type_match(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    memory_file = tmp_path / "episode.md"
    memory_file.write_text("---\ntype: episode\n---\nA real remembered session.\n", encoding="utf-8")
    assert index_file(conn, "asa", "memory/episodes/episode.md", memory_file)
    enqueued = memory_enhancement_enqueue(conn, file_path="memory/episodes/episode.md")
    claimed = memory_enhancement_claim_next(conn, persona="asa")

    memory_enhancement_complete(
        conn,
        job_id=claimed["job_id"],
        status="succeeded",
        response_payload={
            "memory_type": "episodic",
            "summary": "A real remembered session.",
            "topics": ["shadow-pilot"],
        },
    )
    report = memory_enhancement_shadow_report(conn, persona="asa", limit=5)

    assert enqueued["ok"] is True
    assert report["totals"]["type_mismatches"] == 0
    assert report["jobs"][0]["comparison"]["frontmatter_type"] == "episode"
    assert report["jobs"][0]["comparison"]["enhanced_type"] == "episodic"
    assert report["jobs"][0]["comparison"]["type_match"] is True
