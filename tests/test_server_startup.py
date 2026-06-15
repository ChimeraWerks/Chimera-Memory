import asyncio
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from chimera_memory import server
import chimera_memory.config as config
from chimera_memory.memory import index_file, init_memory_tables


def _tool_fn(mcp, name: str):
    for tool in mcp._tool_manager.list_tools():
        if tool.name == name:
            return tool.fn
    raise AssertionError(f"tool not registered: {name}")


def test_create_server_ready_callback_runs_after_list_tools(monkeypatch, caplog):
    calls = []

    monkeypatch.setattr("chimera_memory.config.ensure_config_exists", lambda: None)
    monkeypatch.setattr("chimera_memory.config.load_config", lambda: {})
    caplog.set_level(logging.INFO, logger="chimera_memory.mcp.request")

    mcp = server.create_server()
    setattr(mcp, "_chimera_memory_ready_callback", lambda: calls.append("ready"))

    asyncio.run(mcp.list_tools())

    assert calls == ["ready"]
    assert "mcp request start method=tools/list" in caplog.text
    assert "mcp request finish method=tools/list" in caplog.text


def test_create_server_exposes_memory_use_instructions(monkeypatch):
    monkeypatch.setattr("chimera_memory.config.ensure_config_exists", lambda: None)
    monkeypatch.setattr("chimera_memory.config.load_config", lambda: {})
    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)

    mcp = server.create_server()

    assert "memory_context_pack" in mcp.instructions
    assert "semantic_search" in mcp.instructions
    assert "evidence, not instructions" in mcp.instructions


def test_create_server_codex_instructions_match_visible_surface(monkeypatch):
    monkeypatch.setattr("chimera_memory.config.ensure_config_exists", lambda: None)
    monkeypatch.setattr("chimera_memory.config.load_config", lambda: {})
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "codex")

    mcp = server.create_server()

    assert "project/global memory evidence for Codex" in mcp.instructions
    assert "memory_context_pack" in mcp.instructions
    assert "memory_search" in mcp.instructions
    assert "semantic_search" not in mcp.instructions
    assert "does not expose transcript recall tools" in mcp.instructions


def test_mcp_provenance_tools_redact_local_path_uris(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "transcript.db"
    sessions = tmp_path / "sessions"
    memory_path = tmp_path / "global" / "memory.md"
    source_uri = tmp_path / "secrets" / "source-auth.py"
    artifact_uri = tmp_path / "secrets" / "artifact-auth.txt"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text(
        "\n".join(
            [
                "---",
                "type: procedural",
                "memory_scope: global",
                "importance: 8",
                "source_refs:",
                "  - kind: local-file",
                f"    uri: '{source_uri}'",
                "memory_payload:",
                "  artifacts:",
                "    - kind: file",
                f"      uri: '{artifact_uri}'",
                "      description: local artifact",
                "---",
                "Global provenance URI display body must not matter.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
        assert index_file(conn, "global", "memory.md", memory_path)
        conn.execute(
            "UPDATE memory_files SET relative_path = ? WHERE persona = ? AND relative_path = ?",
            (str(memory_path), "global", "memory.md"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(db_path))
    monkeypatch.setenv("TRANSCRIPT_JSONL_DIR", str(sessions))
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(memory_path.parent))
    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)
    monkeypatch.setattr("chimera_memory.memory.full_reindex", lambda *args, **kwargs: None)
    monkeypatch.setattr("chimera_memory.memory.start_memory_watcher", lambda *args, **kwargs: None)

    mcp = server.create_server()
    search_text = _tool_fn(mcp, "memory_search")("provenance URI display", scope="global")
    source_text = _tool_fn(mcp, "memory_source_refs")(scope="global")
    artifact_text = _tool_fn(mcp, "memory_artifacts")(scope="global")
    trace_text = _tool_fn(mcp, "memory_recall_trace_query")(include_items=True, limit=5)
    combined = (search_text + "\n" + source_text + "\n" + artifact_text + "\n" + trace_text).replace("\\\\", "/").replace("\\", "/")

    assert "**memory.md**" in search_text
    assert "local-path:source-auth.py" in source_text
    assert "local-path:artifact-auth.txt" in artifact_text
    assert "global:memory.md" in source_text
    assert "global:memory.md" in artifact_text
    assert "fingerprint=" in source_text
    assert "fingerprint=" in artifact_text
    assert str(source_uri).replace("\\", "/") not in combined
    assert str(artifact_uri).replace("\\", "/") not in combined
    assert str(tmp_path).replace("\\", "/") not in combined


def test_main_defers_bootstrap_until_tools_list_by_default(monkeypatch):
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
            getattr(self, "_chimera_memory_ready_callback")()

    monkeypatch.delenv("CHIMERA_MEMORY_STARTUP_BOOTSTRAP", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_STARTUP_BOOTSTRAP_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)
    monkeypatch.setattr(server, "_configure_diagnostic_logging", lambda: Path("server.log"))
    monkeypatch.setattr(server, "create_server", lambda: calls.append("create") or FakeServer())
    monkeypatch.setattr(server, "_bootstrap_startup_services", lambda: calls.append("bootstrap"))
    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    server.main()

    assert calls == [
        "create",
        ("run", "stdio"),
        ("thread.start", "chimera-memory-startup-bootstrap", True),
    ]


def test_main_can_start_bootstrap_in_background_immediately(monkeypatch):
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

    monkeypatch.setenv("CHIMERA_MEMORY_STARTUP_BOOTSTRAP", "background")
    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)
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


def test_main_can_run_streamable_http_transport(monkeypatch):
    calls = []

    class FakeServer:
        def run(self, *, transport):
            calls.append(("run", transport))

    monkeypatch.setenv("CHIMERA_MEMORY_STARTUP_BOOTSTRAP", "false")
    monkeypatch.setattr(server, "_configure_diagnostic_logging", lambda: Path("server.log"))
    monkeypatch.setattr(
        server,
        "create_server",
        lambda host="127.0.0.1", port=8000: calls.append(("create", host, port)) or FakeServer(),
    )

    server.main(transport="streamable-http", host="127.0.0.1", port=8765)

    assert calls == [
        ("create", "127.0.0.1", 8765),
        ("run", "streamable-http"),
    ]


def test_asyncio_disconnect_filter_suppresses_only_benign_proactor_reset() -> None:
    filter_ = server._AsyncioDisconnectNoiseFilter()
    benign_exc = ConnectionResetError(10054, "connection reset")
    benign = logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
        args=(),
        exc_info=(ConnectionResetError, benign_exc, None),
    )
    other_callback = logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception in callback other_callback()",
        args=(),
        exc_info=(ConnectionResetError, benign_exc, None),
    )
    real_error = logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
        args=(),
        exc_info=(RuntimeError, RuntimeError("boom"), None),
    )

    assert filter_.filter(benign) is False
    assert filter_.filter(other_callback) is True
    assert filter_.filter(real_error) is True


def test_asyncio_disconnect_filter_install_is_idempotent() -> None:
    logger = logging.getLogger("asyncio")
    original_filters = list(logger.filters)
    try:
        logger.filters = [
            existing
            for existing in logger.filters
            if not isinstance(existing, server._AsyncioDisconnectNoiseFilter)
        ]

        server._install_asyncio_disconnect_log_filter()
        server._install_asyncio_disconnect_log_filter()

        installed = [
            existing
            for existing in logger.filters
            if isinstance(existing, server._AsyncioDisconnectNoiseFilter)
        ]
        assert len(installed) == 1
    finally:
        logger.filters = original_filters


def test_main_skips_bootstrap_for_worker_surface(monkeypatch):
    calls = []

    class FakeServer:
        def run(self, *, transport):
            calls.append(("run", transport))

    monkeypatch.delenv("CHIMERA_MEMORY_STARTUP_BOOTSTRAP", raising=False)
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "worker")
    monkeypatch.setattr(server, "_configure_diagnostic_logging", lambda: Path("server.log"))
    monkeypatch.setattr(server, "create_server", lambda: calls.append("create") or FakeServer())
    monkeypatch.setattr(server, "_bootstrap_startup_services", lambda: calls.append("bootstrap"))

    server.main()

    assert calls == [
        "create",
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


def test_bootstrap_starts_enhancement_before_embedding_and_prewarm(monkeypatch):
    calls = []
    lease = SimpleNamespace(path=Path("lease.lock"), release=lambda: None)

    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)
    monkeypatch.setenv("CHIMERA_MEMORY_PREWARM_EMBEDDINGS", "true")
    monkeypatch.setattr(server, "_startup_maintenance_lease", None)
    monkeypatch.setattr(server, "_try_acquire_startup_maintenance_lease", lambda: lease)
    monkeypatch.setattr(server, "_start_transcript_indexer", lambda: calls.append("indexer") or object())
    monkeypatch.setattr(server, "_start_memory_file_indexer", lambda: calls.append("memory") or object())
    monkeypatch.setattr(server, "_memory_file_watcher_expected", lambda: True)
    monkeypatch.setattr(server, "_start_transcript_embedding_worker", lambda: calls.append("embedder") or object())
    monkeypatch.setattr(server, "_start_memory_enhancement_worker", lambda: calls.append("enhancement") or object())
    monkeypatch.setattr(server, "_start_cm_health_worker", lambda worker_states=None: calls.append(("health", worker_states)) or object())
    monkeypatch.setattr(server, "_prewarm_embeddings", lambda: calls.append("prewarm"))

    server._bootstrap_startup_services()

    assert calls == [
        "indexer",
        "memory",
        "enhancement",
        "embedder",
        (
            "health",
            {
                "transcript_indexer": True,
                "memory_file_watcher": True,
                "transcript_embedding_worker": True,
                "memory_enhancement_worker": True,
            },
        ),
        "prewarm",
    ]


def test_bootstrap_skips_redundant_prewarm_when_embedding_worker_owns_model(monkeypatch):
    calls = []
    lease = SimpleNamespace(path=Path("lease.lock"), release=lambda: None)

    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PREWARM_EMBEDDINGS", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_TRANSCRIPT_EMBEDDING_WORKER", raising=False)
    monkeypatch.setattr(server, "_startup_maintenance_lease", None)
    monkeypatch.setattr(server, "_try_acquire_startup_maintenance_lease", lambda: lease)
    monkeypatch.setattr(server, "_start_transcript_indexer", lambda: calls.append("indexer") or object())
    monkeypatch.setattr(server, "_start_memory_file_indexer", lambda: calls.append("memory") or object())
    monkeypatch.setattr(server, "_memory_file_watcher_expected", lambda: True)
    monkeypatch.setattr(server, "_start_transcript_embedding_worker", lambda: calls.append("embedder") or object())
    monkeypatch.setattr(server, "_start_memory_enhancement_worker", lambda: calls.append("enhancement") or object())
    monkeypatch.setattr(server, "_start_cm_health_worker", lambda worker_states=None: calls.append("health") or object())
    monkeypatch.setattr(server, "_prewarm_embeddings", lambda: calls.append("prewarm"))

    server._bootstrap_startup_services()

    assert "embedder" in calls
    assert "prewarm" not in calls


def test_bootstrap_skips_live_workers_for_worker_surface(monkeypatch):
    calls = []

    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "worker")
    monkeypatch.setattr(server, "_start_transcript_indexer", lambda: calls.append("indexer") or object())
    monkeypatch.setattr(server, "_start_memory_file_indexer", lambda: calls.append("memory") or object())
    monkeypatch.setattr(server, "_start_transcript_embedding_worker", lambda: calls.append("embedder") or object())
    monkeypatch.setattr(server, "_start_memory_enhancement_worker", lambda: calls.append("enhancement") or object())
    monkeypatch.setattr(server, "_start_cm_health_worker", lambda worker_states=None: calls.append("health") or object())
    monkeypatch.setattr(server, "_prewarm_embeddings", lambda: calls.append("prewarm"))

    assert server._bootstrap_startup_services() is None
    assert calls == []


def test_bootstrap_treats_absent_memory_roots_as_expected(monkeypatch):
    calls = []
    lease = SimpleNamespace(path=Path("lease.lock"), release=lambda: None)

    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PREWARM_EMBEDDINGS", raising=False)
    monkeypatch.setattr(server, "_startup_maintenance_lease", None)
    monkeypatch.setattr(server, "_try_acquire_startup_maintenance_lease", lambda: lease)
    monkeypatch.setattr(server, "_start_transcript_indexer", lambda: calls.append("indexer") or object())
    monkeypatch.setattr(server, "_start_memory_file_indexer", lambda: calls.append("memory") or object())
    monkeypatch.setattr(server, "_memory_file_watcher_expected", lambda: False)
    monkeypatch.setattr(server, "_start_transcript_embedding_worker", lambda: calls.append("embedder") or object())
    monkeypatch.setattr(server, "_start_memory_enhancement_worker", lambda: calls.append("enhancement") or object())
    monkeypatch.setattr(server, "_start_cm_health_worker", lambda worker_states=None: calls.append(("health", worker_states)) or object())

    server._bootstrap_startup_services()

    assert "memory" not in calls
    assert (
        "health",
        {
            "transcript_indexer": True,
            "memory_file_watcher": True,
            "transcript_embedding_worker": True,
            "memory_enhancement_worker": True,
        },
    ) in calls


def test_bootstrap_skips_live_workers_when_maintenance_lease_is_held(monkeypatch):
    calls = []

    monkeypatch.delenv("CHIMERA_MEMORY_MCP_SURFACE", raising=False)
    monkeypatch.setattr(server, "_startup_maintenance_lease", None)
    monkeypatch.setattr(server, "_try_acquire_startup_maintenance_lease", lambda: None)
    monkeypatch.setattr(server, "_start_transcript_indexer", lambda: calls.append("indexer") or object())
    monkeypatch.setattr(server, "_start_memory_file_indexer", lambda: calls.append("memory") or object())
    monkeypatch.setattr(server, "_start_transcript_embedding_worker", lambda: calls.append("embedder") or object())
    monkeypatch.setattr(server, "_start_memory_enhancement_worker", lambda: calls.append("enhancement") or object())
    monkeypatch.setattr(server, "_start_cm_health_worker", lambda worker_states=None: calls.append("health") or object())
    monkeypatch.setattr(server, "_prewarm_embeddings", lambda: calls.append("prewarm"))

    assert server._bootstrap_startup_services() is None
    # Secondary process: no live workers start, but it still prewarms its own
    # embedding model so its first semantic tool call is not a cold start (smr-05).
    assert calls == ["prewarm"]


def test_startup_maintenance_lease_is_exclusive(monkeypatch, tmp_path):
    lock_path = tmp_path / "startup.lock"
    monkeypatch.setattr(server, "_startup_maintenance_lock_path", lambda: lock_path)

    first = server._try_acquire_startup_maintenance_lease()
    assert first is not None
    try:
        assert server._try_acquire_startup_maintenance_lease() is None
    finally:
        first.release()

    second = server._try_acquire_startup_maintenance_lease()
    assert second is not None
    second.release()


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


def test_enhancement_worker_can_start_cli_worker_supervisor(monkeypatch, tmp_path):
    calls = []

    def fake_load(env):
        calls.append(("load", env["CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE"]))
        return SimpleNamespace(worker_id="worker-1", provider="openai", worker_root=tmp_path / "worker")

    def fake_start(config):
        calls.append(("start", config))
        return {"thread": object(), "stop_event": object()}

    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE", "cli_worker")
    monkeypatch.setenv("CHIMERA_MEMORY_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.load_codex_cli_worker_config", fake_load)
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.start_codex_cli_worker_supervisor", fake_start)

    handle = server._start_memory_enhancement_worker()

    assert calls[0] == ("load", "cli_worker")
    assert calls[1][0] == "start"
    assert calls[1][1].worker_id == "worker-1"
    assert handle is not None
    assert handle["mode"] == "cli_worker"
    assert handle["runtime"] == "codex"


def test_enhancement_worker_can_start_claude_cli_worker_supervisor(monkeypatch, tmp_path):
    calls = []

    def fake_load(env):
        calls.append(("load", env["CHIMERA_MEMORY_CLI_WORKER_RUNTIME"]))
        return SimpleNamespace(worker_id="claude-worker-1", provider="anthropic", worker_root=tmp_path / "worker")

    def fake_start(config):
        calls.append(("start", config))
        return {"thread": object(), "stop_event": object()}

    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE", "cli_worker")
    monkeypatch.setenv("CHIMERA_MEMORY_CLI_WORKER_RUNTIME", "claude")
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.load_claude_cli_worker_config", fake_load)
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.start_claude_cli_worker_supervisor", fake_start)

    handle = server._start_memory_enhancement_worker()

    assert calls[0] == ("load", "claude")
    assert calls[1][0] == "start"
    assert calls[1][1].worker_id == "claude-worker-1"
    assert handle is not None
    assert handle["mode"] == "cli_worker"
    assert handle["runtime"] == "claude"


def test_enhancement_worker_can_start_agy_cli_worker_supervisor(monkeypatch, tmp_path):
    calls = []

    def fake_load(env):
        calls.append(("load", env["CHIMERA_MEMORY_CLI_WORKER_RUNTIME"]))
        return SimpleNamespace(worker_id="agy-worker-1", provider="google", worker_root=tmp_path / "worker")

    def fake_start(config):
        calls.append(("start", config))
        return {"thread": object(), "stop_event": object()}

    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE", "cli_worker")
    monkeypatch.setenv("CHIMERA_MEMORY_CLI_WORKER_RUNTIME", "agy")
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.load_agy_cli_worker_config", fake_load)
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.start_agy_cli_worker_supervisor", fake_start)

    handle = server._start_memory_enhancement_worker()

    assert calls[0] == ("load", "agy")
    assert calls[1][0] == "start"
    assert calls[1][1].worker_id == "agy-worker-1"
    assert handle is not None
    assert handle["mode"] == "cli_worker"
    assert handle["runtime"] == "agy"


def test_start_memory_file_indexer_indexes_and_watches(monkeypatch, tmp_path):
    calls = []

    class FakeConn:
        def __enter__(self):
            calls.append("connect")
            return object()

        def __exit__(self, exc_type, exc, tb):
            calls.append("close")
            return False

    class FakeDB:
        def __init__(self, db_path):
            self.db_path = db_path

        def connection(self):
            return FakeConn()

    observer = object()

    def fake_reindex(conn, personas_dir, embed=True):
        calls.append(("reindex", personas_dir, embed))
        return 2

    def fake_watch(db, personas_dir):
        calls.append(("watch", db.db_path, personas_dir))
        return observer

    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(tmp_path / "transcript.db"))
    monkeypatch.setenv("CHIMERA_PERSONAS_DIR", str(tmp_path / "personas"))
    monkeypatch.setattr("chimera_memory.db.TranscriptDB", FakeDB)
    monkeypatch.setattr("chimera_memory.memory.full_reindex", fake_reindex)
    monkeypatch.setattr("chimera_memory.memory.start_memory_watcher", fake_watch)

    assert server._start_memory_file_indexer() is observer
    assert calls == [
        "connect",
        ("reindex", tmp_path / "personas", False),
        "close",
        ("watch", str(tmp_path / "transcript.db"), tmp_path / "personas"),
    ]


def test_start_memory_file_indexer_skips_worker_surface(monkeypatch):
    monkeypatch.setenv("CHIMERA_MEMORY_MCP_SURFACE", "worker")

    assert server._start_memory_file_indexer() is None


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


def test_start_transcript_indexer_repairs_rollups(monkeypatch, tmp_path, caplog):
    calls = []

    class FakeDB:
        def __init__(self, db_path):
            self.db_path = db_path

        def repair_session_rollups(self):
            calls.append("repair")
            return 2

    class FakeIndexer:
        def __init__(self, db, jsonl_dir, persona=None, parser_format=None):
            self.db = db
            self.jsonl_dir = jsonl_dir
            self.persona = persona
            self.parser_format = parser_format

        def backfill(self):
            calls.append("backfill")
            return {"files": 1}

        def start_watching(self):
            calls.append("watch")
            return object()

    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(tmp_path / "transcript.db"))
    monkeypatch.setenv("TRANSCRIPT_JSONL_DIR", str(tmp_path))
    monkeypatch.setattr("chimera_memory.db.TranscriptDB", FakeDB)
    monkeypatch.setattr("chimera_memory.indexer.Indexer", FakeIndexer)

    with caplog.at_level(logging.INFO, logger="chimera_memory.indexer-bootstrap"):
        assert server._start_transcript_indexer() is not None

    assert calls == ["backfill", "repair", "watch"]
    assert "Repaired 2 session rollup rows" in caplog.text


def test_start_transcript_indexer_can_skip_historical_import(monkeypatch, tmp_path, caplog):
    calls = []

    class FakeDB:
        def __init__(self, db_path):
            self.db_path = db_path

        def repair_session_rollups(self):
            calls.append("repair")
            return 0

    class FakeIndexer:
        def __init__(self, db, jsonl_dir, persona=None, parser_format=None):
            self.db = db
            self.jsonl_dir = jsonl_dir
            self.persona = persona
            self.parser_format = parser_format

        def backfill(self):
            calls.append("backfill")
            return {"files": 1}

        def mark_existing_files_seen(self):
            calls.append("mark_seen")
            return 3

        def start_watching(self):
            calls.append("watch")
            return object()

    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(tmp_path / "transcript.db"))
    monkeypatch.setenv("TRANSCRIPT_JSONL_DIR", str(tmp_path))
    monkeypatch.setenv("CHIMERA_MEMORY_IMPORT_HISTORY", "false")
    monkeypatch.setattr("chimera_memory.db.TranscriptDB", FakeDB)
    monkeypatch.setattr("chimera_memory.indexer.Indexer", FakeIndexer)

    with caplog.at_level(logging.INFO, logger="chimera_memory.indexer-bootstrap"):
        assert server._start_transcript_indexer() is not None

    assert calls == ["mark_seen", "repair", "watch"]
    assert "Historical transcript import disabled" in caplog.text
