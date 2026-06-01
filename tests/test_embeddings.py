import json
from pathlib import Path
import sys
import threading
import types

from chimera_memory.db import TranscriptDB
from chimera_memory import embeddings
from chimera_memory.embeddings import count_unembedded_transcript_entries, embed_transcript_entries


def _clear_embedding_gpu_env(monkeypatch) -> None:
    monkeypatch.delenv("CHIMERA_MEMORY_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_EMBEDDING_DEVICE", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_FASTEMBED_CUDA", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_FASTEMBED_DEVICE_IDS", raising=False)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)


def test_embed_transcript_entries_respects_limit_and_skips_noise(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_MEMORY_EMBEDDING_PROGRESS_PATH", str(tmp_path / "progress.json"))
    monkeypatch.setattr("chimera_memory.embeddings._sleep_for_cpu_reserve", lambda _seconds, _config: None)
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


def test_embed_transcript_entries_reports_progress_and_status_file(tmp_path: Path, monkeypatch) -> None:
    progress_path = tmp_path / "progress.json"
    monkeypatch.setenv("CHIMERA_MEMORY_EMBEDDING_PROGRESS_PATH", str(progress_path))
    monkeypatch.setattr("chimera_memory.embeddings._sleep_for_cpu_reserve", lambda _seconds, _config: None)
    db = TranscriptDB(tmp_path / "transcript.db")
    db.insert_entries(
        [
            {
                "session_id": "s1",
                "entry_type": "user_message",
                "timestamp": "2026-05-19T10:00:00Z",
                "content": "first",
                "source": "codex",
            },
            {
                "session_id": "s1",
                "entry_type": "assistant_message",
                "timestamp": "2026-05-19T10:00:01Z",
                "content": "second",
                "source": "codex",
            },
        ]
    )

    monkeypatch.setattr(
        "chimera_memory.embeddings.embed_batch",
        lambda texts, batch_size=64: ([0.2] * 384 for _text in texts),
    )
    updates = []

    with db.connection() as conn:
        assert embed_transcript_entries(
            db,
            conn,
            batch_size=1,
            progress_callback=lambda current, total: updates.append((current, total)),
            progress_label="test embeddings",
        ) == 2

    assert updates == [(1, 2), (2, 2)]
    status = json.loads(progress_path.read_text(encoding="utf-8"))
    assert status["status"] == "complete"
    assert status["current"] == 2
    assert status["total"] == 2
    assert status["label"] == "test embeddings"
    assert "provider" in status["runtime"]


def test_embedding_runtime_uses_gpu_provider_when_available(monkeypatch) -> None:
    _clear_embedding_gpu_env(monkeypatch)
    monkeypatch.delenv("CHIMERA_MEMORY_EMBEDDING_MAX_THREADS", raising=False)
    monkeypatch.setenv("CHIMERA_MEMORY_EMBEDDING_CPU_RESERVE_PERCENT", "20")
    monkeypatch.setattr(embeddings.os, "cpu_count", lambda: 10)
    monkeypatch.setattr(
        embeddings,
        "_available_onnx_providers",
        lambda: ("DmlExecutionProvider", "CPUExecutionProvider"),
    )

    config = embeddings._resolve_embedding_runtime_config()

    assert config.using_gpu is True
    assert config.provider == "DmlExecutionProvider"
    assert config.providers == ("DmlExecutionProvider", "CPUExecutionProvider")
    assert config.fastembed_cuda is None
    assert config.threads == 8


def test_embedding_runtime_uses_fastembed_cuda_device_ids(monkeypatch) -> None:
    _clear_embedding_gpu_env(monkeypatch)
    monkeypatch.setenv("CHIMERA_MEMORY_FASTEMBED_CUDA", "true")
    monkeypatch.setenv("CHIMERA_MEMORY_FASTEMBED_DEVICE_IDS", "0")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-a23cc3df-ef1a-b47a-20e7-c17dbd96e7fb")
    monkeypatch.setattr(embeddings.os, "cpu_count", lambda: 10)
    monkeypatch.setattr(embeddings, "_available_onnx_providers", lambda: ("CPUExecutionProvider",))

    config = embeddings._resolve_embedding_runtime_config()

    assert config.using_gpu is True
    assert config.provider == "FastEmbed CUDA"
    assert config.providers == ()
    assert config.fastembed_cuda is True
    assert config.fastembed_device_ids == (0,)
    assert config.cuda_visible_devices == "GPU-a23cc3df-ef1a-b47a-20e7-c17dbd96e7fb"


def test_embedding_runtime_cpu_reserve_limits_threads(monkeypatch) -> None:
    _clear_embedding_gpu_env(monkeypatch)
    monkeypatch.setenv("CHIMERA_MEMORY_EMBEDDING_PROVIDER", "cpu")
    monkeypatch.delenv("CHIMERA_MEMORY_EMBEDDING_MAX_THREADS", raising=False)
    monkeypatch.setenv("CHIMERA_MEMORY_EMBEDDING_CPU_RESERVE_PERCENT", "25")
    monkeypatch.setattr(embeddings.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(embeddings, "_available_onnx_providers", lambda: ("CPUExecutionProvider",))

    config = embeddings._resolve_embedding_runtime_config()

    assert config.using_gpu is False
    assert config.provider == "CPUExecutionProvider"
    assert config.threads == 9
    assert config.cpu_reserve_percent == 25
    assert config.fastembed_cuda is False


def test_load_model_passes_fastembed_cuda_without_providers(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class FakeTextEmbedding:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    fake_fastembed = types.SimpleNamespace(TextEmbedding=FakeTextEmbedding)
    monkeypatch.setitem(sys.modules, "fastembed", fake_fastembed)
    monkeypatch.setenv("CHIMERA_MEMORY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        embeddings,
        "_resolve_embedding_runtime_config",
        lambda: embeddings.EmbeddingRuntimeConfig(
            requested_provider="auto",
            provider="FastEmbed CUDA",
            providers=(),
            available_providers=("CPUExecutionProvider",),
            cpu_count=10,
            cpu_reserve_percent=20,
            threads=8,
            using_gpu=True,
            throttle_cpu=True,
            fastembed_cuda=True,
            fastembed_device_ids=(0,),
            cuda_visible_devices="GPU-a23cc3df-ef1a-b47a-20e7-c17dbd96e7fb",
        ),
    )

    embeddings._load_model()

    assert calls == [
        {
            "model_name": embeddings.MODEL_NAME,
            "threads": 8,
            "cache_dir": str(tmp_path / "cache"),
            "cuda": True,
            "device_ids": [0],
        }
    ]


def test_format_progress_bar_is_stable() -> None:
    assert embeddings.format_progress_bar(5, 10, width=10) == "[#####-----]  50.0% 5/10"


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
