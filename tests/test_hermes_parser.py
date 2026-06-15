"""Tests for the Hermes Agent per-persona session parser."""

from __future__ import annotations

import json
from pathlib import Path

from chimera_memory.parser import get_parser


def _write_session(tmp_path: Path, name: str = "session_20260101_000000_abc.json") -> Path:
    payload = {
        "session_id": "abc-123",
        "model": "claude-opus-4-8",
        "platform": "hermes",
        "session_start": "2026-01-01T00:00:00Z",
        "last_updated": "2026-01-01T00:05:00Z",
        "system_prompt": "You are helpful.",
        "tools": [{"type": "function", "function": {"name": "x"}}],
        "message_count": 3,
        "messages": [
            {"role": "user", "content": "remember the umbrella plan"},
            {"role": "assistant", "content": [{"type": "text", "text": "noted the umbrella plan"}]},
            {"role": "tool", "content": ""},  # empty -> skipped
        ],
    }
    f = tmp_path / name
    f.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return f


def test_hermes_parser_selected_by_client():
    parser = get_parser("hermes")
    assert parser.format_name == "hermes"
    assert parser.session_glob == "session_*.json"
    assert parser.recursive is False
    # Alias forms resolve too.
    assert get_parser("hermes-agent").format_name == "hermes"


def test_hermes_parser_yields_messages(tmp_path):
    f = _write_session(tmp_path)
    parser = get_parser("hermes")
    entries = list(parser.parse_file(f))
    # 2 non-empty messages (the empty tool message is skipped).
    assert len(entries) == 2
    assert entries[0]["entry_type"] == "user_message"
    assert "umbrella" in entries[0]["content"]
    assert entries[1]["entry_type"] == "assistant_message"
    assert "umbrella plan" in entries[1]["content"]
    assert all(e["source"] == "hermes" for e in entries)


def test_hermes_parser_metadata(tmp_path):
    f = _write_session(tmp_path)
    meta = get_parser("hermes").extract_session_metadata(f)
    assert meta["session_id"] == "abc-123"
    assert meta["exchange_count"] == 3
    assert meta["started_at"] == "2026-01-01T00:00:00Z"
    assert "umbrella" in meta["title"]


def test_hermes_parser_tolerates_garbage(tmp_path):
    bad = tmp_path / "session_bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    entries = list(get_parser("hermes").parse_file(bad))
    assert entries == []
    meta = get_parser("hermes").extract_session_metadata(bad)
    assert meta["session_id"] == "session_bad"  # falls back to stem


def test_hermes_session_files_discovered_by_indexer(tmp_path, monkeypatch):
    """The indexer must discover session_*.json (not just *.jsonl) for Hermes."""
    from chimera_memory.db import TranscriptDB
    from chimera_memory.indexer import Indexer

    for name in ("CHIMERA_PERSONA_ROOT", "CHIMERA_MEMORY_PROJECT_ROOT", "CHIMERA_MEMORY_PROJECT_ROOTS"):
        monkeypatch.delenv(name, raising=False)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    _write_session(sessions)
    (sessions / "request_dump_x.json").write_text("{}", encoding="utf-8")  # must be ignored

    db = TranscriptDB(tmp_path / "t.db")
    ix = Indexer(db, sessions, parser_format="hermes")
    files = ix._session_files()
    assert len(files) == 1
    assert files[0].name.startswith("session_")

    ix.index_file(files[0])
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM transcript WHERE source = 'hermes'"
        ).fetchone()[0]
    assert rows == 2
