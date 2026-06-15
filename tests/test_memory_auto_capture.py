import sqlite3
from pathlib import Path

from chimera_memory.memory import (
    init_memory_tables,
    memory_audit_query,
    memory_auto_capture_session_close,
    memory_review_pending,
)
from chimera_memory.memory_auto_capture import parse_action_items


def _personas_dir(tmp_path: Path) -> Path:
    personas = tmp_path / "personas"
    (personas / "developer" / "asa").mkdir(parents=True)
    return personas


def test_parse_action_items_from_session_text() -> None:
    items = parse_action_items(
        "\n".join(
            [
                "Normal note.",
                "ACT NOW: ship the dashboard review surface",
                "- [ ] verify provider smoke harness",
                "TODO update module docs",
            ]
        )
    )

    assert items == [
        "ship the dashboard review surface",
        "verify provider smoke harness",
        "update module docs",
    ]


def test_auto_capture_preview_audits_without_writing(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    personas = _personas_dir(tmp_path)

    result = memory_auto_capture_session_close(
        conn,
        personas,
        persona="asa",
        title="Day 58 wrap",
        summary="Phase 5e dashboard landed and needs review.",
        act_now_text="ACT NOW: run the provider smoke once credentials exist",
        write=False,
    )

    assert result["ok"] is True
    assert result["written"] is False
    assert result["plan"]["persona"] == "asa"
    assert result["plan"]["action_items"] == ["run the provider smoke once credentials exist"]
    assert not list((personas / "developer" / "asa" / "memory" / "episodes").glob("*.md"))

    events = memory_audit_query(conn, event_type="memory_auto_capture_planned", persona="asa")
    assert len(events) == 1
    assert events[0]["payload"]["action_item_count"] == 1


def test_write_auto_capture_file_does_not_clobber_existing(tmp_path: Path) -> None:
    # wcp-05: an exclusive create avoids a TOCTOU clobber — writing a plan whose
    # target already exists must produce a new (uuid-suffixed) file, not overwrite.
    from chimera_memory.memory_auto_capture import build_auto_capture_plan, write_auto_capture_file

    personas = _personas_dir(tmp_path)
    plan = build_auto_capture_plan(
        persona="asa", title="Same Title", summary="same body", created_at="2026-06-15T00:00:00Z"
    )

    first = write_auto_capture_file(personas, plan)
    assert first["ok"] is True
    first_path = Path(first["path"])
    original = first_path.read_text(encoding="utf-8")

    second = write_auto_capture_file(personas, plan)
    assert second["ok"] is True
    assert Path(second["path"]) != first_path
    assert first_path.read_text(encoding="utf-8") == original


def test_auto_capture_write_creates_review_gated_memory(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)
    personas = _personas_dir(tmp_path)

    result = memory_auto_capture_session_close(
        conn,
        personas,
        persona="asa",
        title="Auto capture ship",
        summary="Auto-capture writes an evidence-only session close memory.",
        act_now_text="- [ ] confirm the memory in review queue",
        source_session_id="session-123",
        write=True,
    )

    assert result["ok"] is True
    assert result["written"] is True
    assert result["relative_path"].startswith("memory/episodes/")
    memory_file = Path(result["path"])
    assert memory_file.exists()
    content = memory_file.read_text(encoding="utf-8")
    assert 'provenance_status: "generated"' in content
    assert 'review_status: "pending"' in content
    assert 'can_use_as_instruction: false' in content
    assert "- confirm the memory in review queue" in content

    row = conn.execute(
        """
        SELECT fm_provenance_status, fm_review_status, fm_can_use_as_instruction,
               fm_can_use_as_evidence, fm_requires_user_confirmation
        FROM memory_files
        WHERE relative_path = ?
        """,
        (result["relative_path"],),
    ).fetchone()
    assert row == ("generated", "pending", 0, 1, 1)
    assert memory_review_pending(conn, persona="asa")[0]["relative_path"] == result["relative_path"]

    events = memory_audit_query(conn, event_type="memory_auto_capture_written", persona="asa")
    assert len(events) == 1
    assert events[0]["payload"]["file_id"] == result["file_id"]


def test_auto_capture_blocks_credential_in_raw_input():
    """The credential gate must scan raw inputs, not the pre-sanitized body (wcp-04)."""
    from chimera_memory.memory_auto_capture import build_auto_capture_plan

    plan = build_auto_capture_plan(
        persona="asa",
        title="Session close",
        summary="leaked key sk-ant-abcdefghijklmnopqrstuvwxyz0123 in notes",
        importance=6,
    )
    assert plan["ok"] is True
    assert any(f.get("type") == "credential" for f in plan["blocking_findings"])
    # ...while the stored body is still sanitized (no raw secret persisted).
    assert "sk-ant-abcdefghijklmnopqrstuvwxyz0123" not in plan["body"]
