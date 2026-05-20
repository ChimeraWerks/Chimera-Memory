from pathlib import Path

from chimera_memory.memory_cli_worker_supervisor import (
    CodexCliWorkerConfig,
    codex_worker_command,
    codex_worker_mcp_config,
    codex_worker_prompt,
    ensure_codex_worker_files,
    load_codex_cli_worker_config,
    start_codex_cli_worker_once,
)


class _FakeStdin:
    def __init__(self) -> None:
        self.text = ""
        self.closed = False

    def write(self, text: str) -> None:
        self.text += text

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None):
        return 0


def _config(tmp_path: Path) -> CodexCliWorkerConfig:
    return CodexCliWorkerConfig(
        worker_id="codex-worker-test",
        provider="openai",
        db_path=str(tmp_path / "transcript.db"),
        worker_root=tmp_path / "worker-root",
        codex_home=tmp_path / "worker-root" / ".codex",
        codex_bin="codex-test",
        mcp_command="chimera-memory-test",
        model="gpt-test",
        persona="asa",
    )


def test_load_codex_cli_worker_config_uses_isolated_worker_home(tmp_path: Path) -> None:
    env = {
        "CHIMERA_MEMORY_STATE_ROOT": str(tmp_path / "state"),
        "TRANSCRIPT_DB_PATH": str(tmp_path / "db.sqlite"),
        "CHIMERA_MEMORY_CODEX_WORKER_ID": "worker-1",
        "CHIMERA_MEMORY_CODEX_WORKER_PROVIDER": "openai",
    }

    config = load_codex_cli_worker_config(env)

    assert config.worker_id == "worker-1"
    assert config.provider == "openai"
    assert config.db_path == str(tmp_path / "db.sqlite")
    assert config.worker_root == tmp_path / "state" / "workers" / "codex-memory-worker"
    assert config.codex_home == config.worker_root / ".codex"


def test_codex_worker_mcp_config_uses_worker_surface_and_disables_nested_workers(tmp_path: Path) -> None:
    config = _config(tmp_path)

    payload = codex_worker_mcp_config(config)

    server = payload["mcpServers"]["chimera-memory-worker"]
    assert server["command"] == "chimera-memory-test"
    assert server["args"] == ["serve"]
    env = server["env"]
    assert env["TRANSCRIPT_DB_PATH"] == str(tmp_path / "transcript.db")
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "worker"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_WORKER"] == "false"
    assert env["CHIMERA_MEMORY_TRANSCRIPT_EMBEDDING_WORKER"] == "false"
    assert env["CHIMERA_MEMORY_HEALTH_WORKER"] == "false"
    assert env["TRANSCRIPT_PERSONA"] == "asa"


def test_ensure_codex_worker_files_writes_agents_and_mcp_config(tmp_path: Path) -> None:
    config = _config(tmp_path)

    files = ensure_codex_worker_files(config)

    agents = Path(files["agents"]).read_text(encoding="utf-8")
    mcp_config = Path(files["mcp_config"]).read_text(encoding="utf-8")
    assert "CM Enhancement Worker" in agents
    assert "Do not write memories directly" in agents
    assert "chimera-memory-worker" in mcp_config
    assert Path(files["sessions"]).is_dir()
    assert Path(files["logs"]).is_dir()


def test_codex_worker_command_is_headless_and_read_only(tmp_path: Path) -> None:
    config = _config(tmp_path)

    command = codex_worker_command(config)

    assert command[:2] == ["codex-test", "exec"]
    assert "--json" in command
    assert "--sandbox" in command
    assert "read-only" in command
    assert "--ask-for-approval" in command
    assert "never" in command
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert command[-1] == "-"


def test_start_codex_cli_worker_once_feeds_prompt_and_sets_codex_home(tmp_path: Path) -> None:
    config = _config(tmp_path)
    captured = {}
    process = _FakeProcess()

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return process

    handle = start_codex_cli_worker_once(config, popen_factory=fake_popen)

    assert captured["args"] == codex_worker_command(config)
    assert captured["kwargs"]["cwd"] == str(config.worker_root)
    assert captured["kwargs"]["env"]["CODEX_HOME"] == str(config.codex_home)
    assert "memory_worker_claim_next" in process.stdin.text
    assert "provider: openai" in process.stdin.text
    assert process.stdin.closed is True
    assert handle.stdout_log.parent == config.worker_root / "logs"
    assert handle.stderr_log.parent == config.worker_root / "logs"
    handle.stop()
    assert process.terminated is True


def test_codex_worker_prompt_is_bounded_to_one_pass(tmp_path: Path) -> None:
    prompt = codex_worker_prompt(_config(tmp_path))

    assert "Run one bounded worker pass" in prompt
    assert "memory_worker_claim_next" in prompt
    assert "Heartbeat idle and stop" in prompt
