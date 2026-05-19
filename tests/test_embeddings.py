from pathlib import Path
import threading

from chimera_memory.db import TranscriptDB
from chimera_memory import embeddings
from chimera_memory.embeddings import count_unembedded_transcript_entries, embed_transcript_entries


def test_embed_transcript_entries_respects_limit_and_skips_noise(tmp_path: Path, monkeypatch) -> None:
    db = TranscriptDB(tmp_path / "transcript.db")
    db.insert_entries(
        [
            {
                "session_id": "s1",
                "entry_type": "discord_inbound",
                "timestamp": "2026-05-19T10:00:00Z",
                "content": "embed me first",
                "source": "discord",
                "message_id": "m1",
            },
            {
                "session_id": "s1",
                "entry_type": "assistant_message",
                "timestamp": "2026-05-19T10:00:01Z",
                "content": "embed me second",
                "source": "cli",
            },
            {
                "session_id": "s1",
                "entry_type": "tool_result",
                "timestamp": "2026-05-19T10:00:02Z",
                "content": "do not embed tool output",
                "source": "tool",
            },
        ]
    )

    def fake_embed_batch(texts: list[str], batch_size: int = 64):
        for _text in texts:
            yield [0.1] * 384

    monkeypatch.setattr("chimera_memory.embeddings.embed_batch", fake_embed_batch)

    with db.connection() as conn:
        assert count_unembedded_transcript_entries(conn) == 2
        assert embed_transcript_entries(db, conn, limit=1) == 1
        assert count_unembedded_transcript_entries(conn) == 1
        assert embed_transcript_entries(db, conn, limit=10) == 1
        assert count_unembedded_transcript_entries(conn) == 0
        assert conn.execute("SELECT COUNT(*) FROM transcript_embeddings").fetchone()[0] == 2


def test_get_model_is_single_flight(monkeypatch) -> None:
    calls = []
    entered = threading.Event()
    release = threading.Event()

    class FakeModel:
        pass

    def fake_load_model():
        calls.append("load")
        entered.set()
        release.wait(timeout=2)
        return FakeModel()

    monkeypatch.setattr(embeddings, "_model", None)
    monkeypatch.setattr(embeddings, "_load_model", fake_load_model)

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(embeddings._get_model()))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    assert entered.wait(timeout=2)
    release.set()
    for thread in threads:
        thread.join(timeout=2)

    assert len(calls) == 1
    assert len(results) == 2
    assert results[0] is results[1]
