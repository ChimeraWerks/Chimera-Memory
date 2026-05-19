from pathlib import Path

from chimera_memory.db import TranscriptDB


def test_insert_entries_dedupes_discord_messages_across_sessions(tmp_path: Path) -> None:
    db = TranscriptDB(tmp_path / "transcript.db")

    first = {
        "session_id": "session-one",
        "entry_type": "discord_inbound",
        "timestamp": "2026-05-19T10:00:00Z",
        "content": "same Discord message",
        "persona": "asa",
        "source": "discord",
        "chat_id": "room-1",
        "message_id": "msg-1",
        "author": "Charles",
    }
    duplicate = {**first, "session_id": "session-two"}

    assert db.insert_entries([first]) == 1
    assert db.insert_entries([duplicate]) == 0

    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM transcript").fetchone()[0] == 1
        row = conn.execute(
            "SELECT session_id, message_id FROM transcript WHERE message_id = 'msg-1'"
        ).fetchone()
        assert dict(row) == {"session_id": "session-one", "message_id": "msg-1"}


def test_insert_entries_creates_session_rows_for_direct_writers(tmp_path: Path) -> None:
    db = TranscriptDB(tmp_path / "transcript.db")

    inserted = db.insert_entries(
        [
            {
                "session_id": "direct-outbound",
                "entry_type": "discord_outbound",
                "timestamp": "2026-05-19T10:00:00Z",
                "content": "first",
                "persona": "asa",
                "source": "discord",
                "chat_id": "room-1",
                "message_id": "reply-1",
                "author": "Asa",
            },
            {
                "session_id": "direct-outbound",
                "entry_type": "assistant_message",
                "timestamp": "2026-05-19T10:00:02Z",
                "content": "second",
                "persona": "asa",
                "source": "cli",
                "author": "Asa",
            },
        ]
    )

    assert inserted == 2
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT persona, started_at, ended_at, exchange_count
            FROM sessions
            WHERE session_id = 'direct-outbound'
            """
        ).fetchone()
        assert dict(row) == {
            "persona": "asa",
            "started_at": "2026-05-19T10:00:00Z",
            "ended_at": "2026-05-19T10:00:02Z",
            "exchange_count": 2,
        }
