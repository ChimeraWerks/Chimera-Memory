import json
import sqlite3
import time
from pathlib import Path

from chimera_memory.memory_schema import init_memory_tables
from chimera_memory.memory_cli_worker_supervisor import (
    AgyCliWorkerConfig,
    ClaudeCliWorkerConfig,
    CodexCliWorkerConfig,
    agy_worker_command,
    agy_worker_mcp_config,
    agy_worker_prompt,
    claude_worker_command,
    claude_worker_mcp_config,
    claude_worker_prompt,
    codex_worker_command,
    codex_worker_config_toml,
    codex_worker_mcp_config,
    codex_worker_prompt,
    ensure_agy_worker_files,
    ensure_claude_worker_files,
    ensure_codex_worker_files,
    inspect_cli_worker_setup,
    load_agy_cli_worker_config,
    load_claude_cli_worker_config,
    load_codex_cli_worker_config,
    start_agy_cli_worker_once,
    start_claude_cli_worker_once,
    start_claude_cli_worker_supervisor,
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


def _config_without_codex_bypass(tmp_path: Path) -> CodexCliWorkerConfig:
    config = _config(tmp_path)
    return CodexCliWorkerConfig(
        worker_id=config.worker_id,
        provider=config.provider,
        db_path=config.db_path,
        worker_root=config.worker_root,
        codex_home=config.codex_home,
        codex_bin=config.codex_bin,
        mcp_command=config.mcp_command,
        model=config.model,
        bypass_approvals_and_sandbox=False,
        poll_interval_seconds=config.poll_interval_seconds,
        restart_interval_seconds=config.restart_interval_seconds,
        persona=config.persona,
    )


def _claude_config(tmp_path: Path) -> ClaudeCliWorkerConfig:
    return ClaudeCliWorkerConfig(
        worker_id="claude-worker-test",
        provider="anthropic",
        db_path=str(tmp_path / "transcript.db"),
        worker_root=tmp_path / "claude-worker-root",
        claude_bin="claude-test",
        mcp_command="chimera-memory-test",
        model="sonnet",
        persona="sarah",
    )


def _agy_config(tmp_path: Path) -> AgyCliWorkerConfig:
    return AgyCliWorkerConfig(
        worker_id="agy-worker-test",
        provider="google",
        db_path=str(tmp_path / "transcript.db"),
        worker_root=tmp_path / "agy-worker-root",
        agy_home=tmp_path / "agy-home",
        agy_bin="agy-test",
        mcp_command="chimera-memory-test",
        persona="asa",
    )


def test_load_codex_cli_worker_config_uses_isolated_worker_home(tmp_path: Path) -> None:
    env = {
        "CHIMERA_MEMORY_STATE_ROOT": str(tmp_path / "state"),
        "TRANSCRIPT_DB_PATH": str(tmp_path / "db.sqlite"),
        "CHIMERA_MEMORY_CODEX_WORKER_ID": "worker-1",
        "CHIMERA_MEMORY_CODEX_WORKER_PROVIDER": "openai",
        "CHIMERA_MEMORY_CODEX_WORKER_AUTH_PATH": str(tmp_path / "auth.json"),
    }

    config = load_codex_cli_worker_config(env)

    assert config.worker_id == "worker-1"
    assert config.provider == "openai"
    assert config.db_path == str(tmp_path / "db.sqlite")
    assert config.worker_root == tmp_path / "state" / "workers" / "codex-memory-worker"
    assert config.codex_home == config.worker_root / ".codex"
    assert config.codex_auth_path == tmp_path / "auth.json"
    assert config.effort == "medium"
    assert config.bypass_approvals_and_sandbox is True


def test_load_codex_cli_worker_config_uses_explicit_effort(tmp_path: Path) -> None:
    env = {
        "CHIMERA_MEMORY_STATE_ROOT": str(tmp_path / "state"),
        "CHIMERA_MEMORY_CLI_WORKER_EFFORT": "high",
        "CHIMERA_MEMORY_CODEX_WORKER_EFFORT": "xhigh",
    }

    config = load_codex_cli_worker_config(env)

    assert config.effort == "xhigh"


def test_load_codex_cli_worker_config_can_disable_bypass(tmp_path: Path) -> None:
    env = {
        "CHIMERA_MEMORY_STATE_ROOT": str(tmp_path / "state"),
        "CHIMERA_MEMORY_CODEX_WORKER_BYPASS_APPROVALS_AND_SANDBOX": "false",
    }

    config = load_codex_cli_worker_config(env)

    assert config.bypass_approvals_and_sandbox is False


def test_load_codex_cli_worker_config_resolves_codex_shim(tmp_path: Path, monkeypatch) -> None:
    expected = str(tmp_path / "bin" / "codex.cmd")
    monkeypatch.setattr(
        "chimera_memory.memory_cli_worker_supervisor.shutil.which",
        lambda command: expected if command == "codex" else None,
    )
    env = {"CHIMERA_MEMORY_STATE_ROOT": str(tmp_path / "state")}

    config = load_codex_cli_worker_config(env)

    assert config.codex_bin == expected


def test_load_claude_cli_worker_config_uses_worker_root(tmp_path: Path) -> None:
    env = {
        "CHIMERA_MEMORY_STATE_ROOT": str(tmp_path / "state"),
        "TRANSCRIPT_DB_PATH": str(tmp_path / "db.sqlite"),
        "CHIMERA_MEMORY_CLAUDE_WORKER_ID": "claude-worker-1",
        "CHIMERA_MEMORY_CLAUDE_WORKER_PROVIDER": "anthropic",
    }

    config = load_claude_cli_worker_config(env)

    assert config.worker_id == "claude-worker-1"
    assert config.provider == "anthropic"
    assert config.db_path == str(tmp_path / "db.sqlite")
    assert config.worker_root == tmp_path / "state" / "workers" / "claude-memory-worker"
    assert config.effort == "medium"


def test_load_claude_cli_worker_config_uses_explicit_effort(tmp_path: Path) -> None:
    env = {
        "CHIMERA_MEMORY_STATE_ROOT": str(tmp_path / "state"),
        "CHIMERA_MEMORY_CLI_WORKER_EFFORT": "high",
        "CHIMERA_MEMORY_CLAUDE_WORKER_EFFORT": "max",
    }

    config = load_claude_cli_worker_config(env)

    assert config.effort == "max"


def test_load_claude_cli_worker_config_prefers_cmd_shim(tmp_path: Path, monkeypatch) -> None:
    shim = tmp_path / "claude.cmd"

    def fake_which(name: str) -> str | None:
        return str(shim) if name == "claude.cmd" else None

    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.shutil.which", fake_which)

    config = load_claude_cli_worker_config({"CHIMERA_MEMORY_STATE_ROOT": str(tmp_path / "state")})

    assert config.claude_bin == str(shim)


def test_load_agy_cli_worker_config_uses_isolated_worker_home(tmp_path: Path) -> None:
    env = {
        "CHIMERA_MEMORY_STATE_ROOT": str(tmp_path / "state"),
        "TRANSCRIPT_DB_PATH": str(tmp_path / "db.sqlite"),
        "CHIMERA_MEMORY_AGY_WORKER_ID": "agy-worker-1",
        "CHIMERA_MEMORY_AGY_WORKER_PROVIDER": "google",
        "CHIMERA_MEMORY_AGY_BIN": "agy-test",
    }

    config = load_agy_cli_worker_config(env)

    assert config.worker_id == "agy-worker-1"
    assert config.provider == "google"
    assert config.db_path == str(tmp_path / "db.sqlite")
    assert config.worker_root == tmp_path / "state" / "workers" / "agy-memory-worker"
    assert config.agy_home == config.worker_root / ".agy-home"
    assert config.agy_bin == "agy-test"


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


def test_codex_worker_config_toml_uses_current_mcp_shape(tmp_path: Path) -> None:
    config = _config(tmp_path)

    rendered = codex_worker_config_toml(config)

    assert rendered.startswith("# ")
    assert '[mcp_servers."chimera-memory-worker"]' in rendered
    assert 'command = "chimera-memory-test"' in rendered
    assert 'args = ["serve"]' in rendered
    assert '[mcp_servers."chimera-memory-worker".env]' in rendered
    assert 'CHIMERA_MEMORY_MCP_SURFACE = "worker"' in rendered
    assert f'TRANSCRIPT_DB_PATH = "{str(tmp_path / "transcript.db").replace("\\", "\\\\")}"' in rendered


def test_claude_worker_mcp_config_uses_worker_surface_and_disables_nested_workers(tmp_path: Path) -> None:
    config = _claude_config(tmp_path)

    payload = claude_worker_mcp_config(config)

    server = payload["mcpServers"]["chimera-memory-worker"]
    assert server["command"] == "chimera-memory-test"
    assert server["args"] == ["serve"]
    env = server["env"]
    assert env["TRANSCRIPT_DB_PATH"] == str(tmp_path / "transcript.db")
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "worker"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_WORKER"] == "false"
    assert env["CHIMERA_MEMORY_TRANSCRIPT_EMBEDDING_WORKER"] == "false"
    assert env["CHIMERA_MEMORY_HEALTH_WORKER"] == "false"
    assert env["TRANSCRIPT_PERSONA"] == "sarah"


def test_agy_worker_mcp_config_uses_worker_surface_and_disables_nested_workers(tmp_path: Path) -> None:
    config = _agy_config(tmp_path)

    payload = agy_worker_mcp_config(config)

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
    legacy_mcp_config = Path(files["mcp_legacy_json"]).read_text(encoding="utf-8")
    assert "CM Enhancement Worker" in agents
    assert "Do not write memories directly" in agents
    assert '[mcp_servers."chimera-memory-worker"]' in mcp_config
    assert "chimera-memory-worker" in mcp_config
    assert "chimera-memory-worker" in legacy_mcp_config
    assert Path(files["sessions"]).is_dir()
    assert Path(files["logs"]).is_dir()


def test_ensure_codex_worker_files_copies_auth_into_isolated_home(tmp_path: Path) -> None:
    source_auth = tmp_path / "source-auth.json"
    source_auth.write_text('{"access_token":"TEST_ONLY_TOKEN"}\n', encoding="utf-8")
    base = _config(tmp_path)
    config = CodexCliWorkerConfig(
        worker_id=base.worker_id,
        provider=base.provider,
        db_path=base.db_path,
        worker_root=base.worker_root,
        codex_home=base.codex_home,
        codex_auth_path=source_auth,
        codex_bin=base.codex_bin,
        mcp_command=base.mcp_command,
        model=base.model,
        effort=base.effort,
        bypass_approvals_and_sandbox=base.bypass_approvals_and_sandbox,
        poll_interval_seconds=base.poll_interval_seconds,
        restart_interval_seconds=base.restart_interval_seconds,
        persona=base.persona,
    )

    files = ensure_codex_worker_files(config)

    copied = config.codex_home / "auth.json"
    assert files["auth"] == str(copied)
    assert copied.read_text(encoding="utf-8") == source_auth.read_text(encoding="utf-8")


def test_ensure_claude_worker_files_writes_claude_md_and_mcp_config(tmp_path: Path) -> None:
    config = _claude_config(tmp_path)

    files = ensure_claude_worker_files(config)

    claude_md = Path(files["claude"]).read_text(encoding="utf-8")
    mcp_config = Path(files["mcp_config"]).read_text(encoding="utf-8")
    assert "CM Enhancement Worker" in claude_md
    assert "Do not write memories directly" in claude_md
    assert "chimera-memory-worker" in mcp_config
    assert Path(files["sessions"]).is_dir()
    assert Path(files["logs"]).is_dir()


def test_ensure_agy_worker_files_writes_agents_gemini_and_mcp_config(tmp_path: Path) -> None:
    config = _agy_config(tmp_path)

    files = ensure_agy_worker_files(config)

    agents = Path(files["agents"]).read_text(encoding="utf-8")
    gemini = Path(files["gemini"]).read_text(encoding="utf-8")
    mcp_config = Path(files["mcp_config"]).read_text(encoding="utf-8")
    assert "CM Enhancement Worker" in agents
    assert "CM Enhancement Worker" in gemini
    assert "Do not write memories directly" in agents
    assert json.loads(mcp_config) == agy_worker_mcp_config(config)
    assert Path(files["settings"]).exists()
    settings = json.loads(Path(files["settings"]).read_text(encoding="utf-8"))
    assert settings["allowNonWorkspaceAccess"] is False
    assert settings["toolPermission"] == "always-proceed"
    assert Path(files["sessions"]).is_dir()
    assert Path(files["logs"]).is_dir()


def test_codex_worker_command_uses_bypass_for_exec_mcp_approval_compat(tmp_path: Path) -> None:
    config = _config(tmp_path)

    command = codex_worker_command(config)

    assert command[:2] == ["codex-test", "exec"]
    assert "--json" in command
    assert "--ephemeral" in command
    assert "--skip-git-repo-check" in command
    assert "--dangerously-bypass-approvals-and-sandbox" in command
    assert "--sandbox" not in command
    assert "-c" in command
    assert 'model_reasoning_effort="medium"' in command
    assert command[-1] == "-"


def test_codex_worker_command_can_disable_bypass_for_future_codex_versions(tmp_path: Path) -> None:
    config = _config_without_codex_bypass(tmp_path)

    command = codex_worker_command(config)

    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "--sandbox" in command
    assert "read-only" in command


def test_claude_worker_command_is_headless_and_strict_mcp(tmp_path: Path) -> None:
    config = _claude_config(tmp_path)

    command = claude_worker_command(config)

    assert command[0] == "claude-test"
    assert "--print" in command
    assert "--output-format" in command
    assert "stream-json" in command
    assert "--verbose" in command
    assert "--no-session-persistence" in command
    assert "--allowedTools" in command
    allowed_tools = command[command.index("--allowedTools") + 1].split(",")
    assert allowed_tools == [
        "mcp__chimera-memory-worker__memory_worker_heartbeat",
        "mcp__chimera-memory-worker__memory_worker_budget",
        "mcp__chimera-memory-worker__memory_worker_claim_next",
        "mcp__chimera-memory-worker__memory_worker_submit_result",
    ]
    assert "--permission-mode" in command
    assert "dontAsk" in command
    assert "--effort" in command
    assert command[command.index("--effort") + 1] == "medium"
    assert "--mcp-config" in command
    assert "--strict-mcp-config" in command
    assert "--dangerously-skip-permissions" not in command


def test_agy_worker_command_is_headless_sandboxed_and_worker_scoped(tmp_path: Path) -> None:
    config = _agy_config(tmp_path)

    command = agy_worker_command(config)

    assert command[0] == "agy-test"
    assert "--print" in command
    assert "--sandbox" in command
    assert "--add-dir" in command
    assert str(config.worker_root) in command
    assert "--log-file" in command
    assert "--dangerously-skip-permissions" not in command


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


def test_start_claude_cli_worker_once_feeds_prompt_and_mcp_config(tmp_path: Path) -> None:
    config = _claude_config(tmp_path)
    captured = {}
    process = _FakeProcess()

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return process

    handle = start_claude_cli_worker_once(config, popen_factory=fake_popen)

    assert captured["args"] == claude_worker_command(config)
    assert captured["kwargs"]["cwd"] == str(config.worker_root)
    assert "CHIMERA_MEMORY_CLAUDE_WORKER_ID" in captured["kwargs"]["env"]
    assert "memory_worker_claim_next" in process.stdin.text
    assert "provider: anthropic" in process.stdin.text
    assert process.stdin.closed is True
    assert handle.stdout_log.parent == config.worker_root / "logs"
    assert handle.stderr_log.parent == config.worker_root / "logs"
    handle.stop()
    assert process.terminated is True


def test_claude_worker_supervisor_records_launch_failures(tmp_path: Path) -> None:
    db_path = tmp_path / "transcript.db"
    with sqlite3.connect(db_path) as conn:
        init_memory_tables(conn)
        conn.execute(
            """
            INSERT INTO memory_enhancement_jobs (job_id, status, persona, path, requested_provider)
            VALUES ('job-1', 'pending', 'sarah', 'memory/test.md', 'anthropic')
            """
        )
        conn.commit()
    config = ClaudeCliWorkerConfig(
        worker_id="claude-worker-test",
        provider="anthropic",
        db_path=str(db_path),
        worker_root=tmp_path / "claude-worker-root",
        claude_bin="missing-claude",
        mcp_command="chimera-memory-test",
        restart_interval_seconds=0.05,
    )

    def fake_popen(args, **kwargs):
        raise FileNotFoundError("missing-claude")

    handle = start_claude_cli_worker_supervisor(config, popen_factory=fake_popen)
    try:
        deadline = time.time() + 2
        while time.time() < deadline and not handle["state"].get("launch_error_count"):
            time.sleep(0.02)
        assert handle["state"]["launch_error_count"] >= 1
        assert "missing-claude" in str(handle["state"]["last_error"])
    finally:
        handle["stop_event"].set()
        handle["thread"].join(timeout=2)


def test_claude_worker_supervisor_skips_launch_when_queue_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "transcript.db"
    with sqlite3.connect(db_path) as conn:
        init_memory_tables(conn)
    config = ClaudeCliWorkerConfig(
        worker_id="claude-worker-test",
        provider="anthropic",
        db_path=str(db_path),
        worker_root=tmp_path / "claude-worker-root",
        claude_bin="claude-test",
        mcp_command="chimera-memory-test",
        restart_interval_seconds=0.05,
        persona="sarah",
    )
    launches = []

    def fake_popen(args, **kwargs):
        launches.append(args)
        return _FakeProcess()

    handle = start_claude_cli_worker_supervisor(config, popen_factory=fake_popen)
    try:
        deadline = time.time() + 0.2
        while time.time() < deadline:
            time.sleep(0.02)
        assert launches == []
        assert handle["state"]["idle_skip_count"] >= 1
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT status, provider, metadata FROM memory_worker_heartbeats WHERE worker_id = ?",
                ("claude-worker-test",),
            ).fetchone()
        assert row[0] == "idle"
        assert row[1] == "anthropic"
        assert json.loads(row[2])["launch_skipped"] == "no_pending_job"
    finally:
        handle["stop_event"].set()
        handle["thread"].join(timeout=2)


def test_start_agy_cli_worker_once_feeds_prompt_and_sets_isolated_home(tmp_path: Path) -> None:
    config = _agy_config(tmp_path)
    captured = {}
    process = _FakeProcess()

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return process

    handle = start_agy_cli_worker_once(config, popen_factory=fake_popen)

    assert captured["args"] == agy_worker_command(config)
    assert captured["kwargs"]["cwd"] == str(config.worker_root)
    assert captured["kwargs"]["env"]["HOME"] == str(config.agy_home)
    assert captured["kwargs"]["env"]["USERPROFILE"] == str(config.agy_home)
    assert "memory_worker_claim_next" in process.stdin.text
    assert "provider: google" in process.stdin.text
    assert process.stdin.closed is True
    assert handle.stdout_log.parent == config.worker_root / "logs"
    assert handle.stderr_log.parent == config.worker_root / "logs"
    handle.stop()
    assert process.terminated is True


def test_codex_worker_prompt_is_bounded_to_one_pass(tmp_path: Path) -> None:
    prompt = codex_worker_prompt(_config(tmp_path))

    assert "Run one bounded worker pass" in prompt
    assert "memory_worker_claim_next" in prompt
    assert "actual_provider=`openai`" in prompt
    assert "Do not submit success with an empty summary" in prompt
    assert "Heartbeat idle with provider `openai`" in prompt


def test_claude_worker_prompt_is_bounded_to_one_pass(tmp_path: Path) -> None:
    prompt = claude_worker_prompt(_claude_config(tmp_path))

    assert "Run one bounded worker pass" in prompt
    assert "memory_worker_claim_next" in prompt
    assert "actual_provider=`anthropic`" in prompt
    assert "Do not submit success with an empty summary" in prompt
    assert "Heartbeat idle with provider `anthropic`" in prompt


def test_agy_worker_prompt_is_bounded_to_one_pass(tmp_path: Path) -> None:
    prompt = agy_worker_prompt(_agy_config(tmp_path))

    assert "Run one bounded worker pass" in prompt
    assert "memory_worker_claim_next" in prompt
    assert "actual_provider=`google`" in prompt
    assert "Do not submit success with an empty summary" in prompt
    assert "Heartbeat idle with provider `google`" in prompt


def test_inspect_cli_worker_setup_can_initialize_codex_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_MEMORY_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(tmp_path / "transcript.db"))
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.shutil.which", lambda command: command)

    receipt = inspect_cli_worker_setup(runtime="codex", init=True)

    assert receipt["ok"] is True
    assert receipt["runtime"] == "codex"
    assert receipt["initialized"] is True
    assert receipt["launch_performed"] is False
    assert receipt["files"]["agents"]["exists"] is True
    assert receipt["files"]["mcp_config"]["exists"] is True
    assert receipt["command_preview"] == codex_worker_command(load_codex_cli_worker_config())


def test_inspect_cli_worker_setup_reports_missing_uninitialized_claude_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CHIMERA_MEMORY_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.shutil.which", lambda command: command)

    receipt = inspect_cli_worker_setup(runtime="claude", init=False)

    assert receipt["ok"] is False
    assert receipt["runtime"] == "claude"
    assert receipt["initialized"] is False
    assert receipt["launch_performed"] is False
    assert receipt["files"]["claude"]["exists"] is False
    assert receipt["command_preview"] == claude_worker_command(load_claude_cli_worker_config())


def test_inspect_cli_worker_setup_can_initialize_agy_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHIMERA_MEMORY_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(tmp_path / "transcript.db"))
    monkeypatch.setenv("CHIMERA_MEMORY_AGY_BIN", "agy")
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.shutil.which", lambda command: command)

    receipt = inspect_cli_worker_setup(runtime="agy", init=True)

    assert receipt["ok"] is True
    assert receipt["runtime"] == "agy"
    assert receipt["initialized"] is True
    assert receipt["launch_performed"] is False
    assert receipt["files"]["agents"]["exists"] is True
    assert receipt["files"]["gemini"]["exists"] is True
    assert receipt["files"]["mcp_config"]["exists"] is True
    assert receipt["command_preview"] == agy_worker_command(load_agy_cli_worker_config())
