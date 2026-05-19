from pathlib import Path
import logging

from chimera_memory import server


def test_main_starts_bootstrap_in_background_by_default(monkeypatch):
    calls = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            calls.append(("thread.start", self.name, self.daemon))

    class FakeServer:
        def run(self, *, transport):
            calls.append(("run", transport))

    monkeypatch.delenv("CHIMERA_MEMORY_STARTUP_BOOTSTRAP", raising=False)
    monkeypatch.setattr(server, "_configure_diagnostic_logging", lambda: Path("server.log"))
    monkeypatch.setattr(server, "create_server", lambda: calls.append("create") or FakeServer())
    monkeypatch.setattr(server, "_bootstrap_startup_services", lambda: calls.append("bootstrap"))
    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    server.main()

    assert calls == [
        "create",
        ("thread.start", "chimera-memory-startup-bootstrap", True),
        ("run", "stdio"),
    ]


def test_main_sync_bootstrap_keeps_indexer_reference_until_shutdown(monkeypatch):
    calls = []

    class FakeIndexer:
        def stop_watching(self):
            calls.append("stop_watching")

    class FakeServer:
        def run(self, *, transport):
            calls.append(("run", transport))

    monkeypatch.setenv("CHIMERA_MEMORY_STARTUP_BOOTSTRAP", "sync")
    monkeypatch.setattr(server, "_configure_diagnostic_logging", lambda: Path("server.log"))
    monkeypatch.setattr(server, "create_server", lambda: calls.append("create") or FakeServer())
    monkeypatch.setattr(server, "_bootstrap_startup_services", lambda: calls.append("bootstrap") or FakeIndexer())

    server.main()

    assert calls == [
        "create",
        "bootstrap",
        ("run", "stdio"),
        "stop_watching",
    ]


def test_bootstrap_starts_live_workers_before_prewarm(monkeypatch):
    calls = []

    monkeypatch.setattr(server, "_start_transcript_indexer", lambda: calls.append("indexer") or object())
    monkeypatch.setattr(server, "_start_transcript_embedding_worker", lambda: calls.append("embedder") or object())
    monkeypatch.setattr(server, "_start_memory_enhancement_worker", lambda: calls.append("enhancement") or object())
    monkeypatch.setattr(server, "_start_cm_health_worker", lambda worker_states=None: calls.append(("health", worker_states)) or object())
    monkeypatch.setattr(server, "_prewarm_embeddings", lambda: calls.append("prewarm"))

    server._bootstrap_startup_services()

    assert calls == [
        "indexer",
        "embedder",
        "enhancement",
        (
            "health",
            {
                "transcript_indexer": True,
                "transcript_embedding_worker": True,
                "memory_enhancement_worker": True,
            },
        ),
        "prewarm",
    ]


def test_enhancement_worker_disabled_by_env(monkeypatch):
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_WORKER", "false")

    assert server._start_memory_enhancement_worker() is None


def test_enhancement_worker_starts_dry_run_by_default(monkeypatch):
    calls = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            calls.append(("thread.start", self.name, self.daemon))

    monkeypatch.delenv("CHIMERA_MEMORY_ENHANCEMENT_WORKER", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE", raising=False)
    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    handle = server._start_memory_enhancement_worker()

    assert calls == [("thread.start", "chimera-memory-enhancement-worker", True)]
    assert handle is not None
    assert handle["mode"] == "dry_run"


def test_background_bootstrap_logs_failures(monkeypatch, caplog):
    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            self.target()

    def fail_bootstrap():
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "_bootstrap_startup_services", fail_bootstrap)
    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    with caplog.at_level(logging.ERROR, logger="chimera_memory.startup"):
        server._start_background_bootstrap()

    assert "startup bootstrap failed" in caplog.text
