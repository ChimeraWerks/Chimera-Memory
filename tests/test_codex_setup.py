from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

from chimera_memory.codex_setup import (
    build_codex_mcp_config,
    format_codex_install_report,
    format_codex_doctor_report,
    install_codex_mcp_config,
    inspect_codex_mcp_config,
)


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_codex_config(jsonl_dir: Path) -> dict:
    return {
        "mcpServers": {
            "chimera-memory": {
                "command": sys.executable,
                "args": ["serve"],
                "env": {
                    "TRANSCRIPT_JSONL_DIR": str(jsonl_dir),
                    "TRANSCRIPT_PERSONA": "asa",
                    "CHIMERA_CLIENT": "codex",
                    "CHIMERA_PERSONA_ID": "developer/asa",
                    "CHIMERA_PERSONA_NAME": "asa",
                    "CHIMERA_PERSONA_ROOT": "C:/Github/ChimeraAgency/personas/developer/asa",
                    "CHIMERA_PERSONAS_DIR": "C:/Github/ChimeraAgency/personas",
                    "CHIMERA_SHARED_ROOT": "C:/Github/ChimeraAgency/shared",
                },
            },
        },
    }


def test_codex_doctor_reports_valid_setup_without_env_values(tmp_path: Path) -> None:
    jsonl_dir = tmp_path / "sessions"
    jsonl_dir.mkdir()
    config_path = tmp_path / "mcp_servers.json"
    payload = _valid_codex_config(jsonl_dir)
    payload["mcpServers"]["chimera-memory"]["env"]["EXTRA_SECRET"] = "secret-token-value"
    _write_config(config_path, payload)

    report = inspect_codex_mcp_config(config_path)
    text = format_codex_doctor_report(report)
    serialized = json.dumps(report)

    assert report["status"] == "ok"
    assert report["server_configured"] is True
    assert "EXTRA_SECRET" in report["env_keys"]
    assert "secret-token-value" not in serialized
    assert "secret-token-value" not in text
    assert "TRANSCRIPT_JSONL_DIR exists." in text


def test_codex_doctor_reports_missing_config(tmp_path: Path) -> None:
    report = inspect_codex_mcp_config(tmp_path / "missing.json")

    assert report["status"] == "error"
    assert report["config_exists"] is False
    assert any(check["name"] == "config_exists" for check in report["checks"])


def test_codex_doctor_rejects_wrong_client_parser(tmp_path: Path) -> None:
    jsonl_dir = tmp_path / "sessions"
    jsonl_dir.mkdir()
    config_path = tmp_path / "mcp_servers.json"
    payload = _valid_codex_config(jsonl_dir)
    payload["mcpServers"]["chimera-memory"]["env"]["CHIMERA_CLIENT"] = "claude"
    _write_config(config_path, payload)

    report = inspect_codex_mcp_config(config_path)

    assert report["status"] == "error"
    assert any(
        check["name"] == "env:CHIMERA_CLIENT"
        and "must be codex" in check["message"]
        for check in report["checks"]
    )


def test_codex_doctor_warns_on_incomplete_identity(tmp_path: Path) -> None:
    jsonl_dir = tmp_path / "sessions"
    jsonl_dir.mkdir()
    config_path = tmp_path / "mcp_servers.json"
    payload = _valid_codex_config(jsonl_dir)
    for key in (
        "CHIMERA_PERSONA_ID",
        "CHIMERA_PERSONA_NAME",
        "CHIMERA_PERSONA_ROOT",
        "CHIMERA_PERSONAS_DIR",
        "CHIMERA_SHARED_ROOT",
    ):
        del payload["mcpServers"]["chimera-memory"]["env"][key]
    _write_config(config_path, payload)

    report = inspect_codex_mcp_config(config_path)
    text = format_codex_doctor_report(report)

    assert report["status"] == "warning"
    assert "Persona identity env is incomplete." in text
    assert "CHIMERA_PERSONA_ID" in text


def test_codex_doctor_accepts_derived_identity_fields(tmp_path: Path) -> None:
    jsonl_dir = tmp_path / "sessions"
    persona_root = tmp_path / "personas" / "developer" / "asa"
    shared_root = tmp_path / "shared"
    jsonl_dir.mkdir()
    persona_root.mkdir(parents=True)
    shared_root.mkdir()
    config_path = tmp_path / "mcp_servers.json"
    payload = {
        "mcpServers": {
            "chimera-memory": {
                "command": sys.executable,
                "args": ["serve"],
                "env": {
                    "TRANSCRIPT_JSONL_DIR": str(jsonl_dir),
                    "CHIMERA_CLIENT": "codex",
                    "CHIMERA_PERSONA_ID": "developer/asa",
                    "CHIMERA_PERSONA_ROOT": str(persona_root),
                },
            },
        },
    }
    _write_config(config_path, payload)

    report = inspect_codex_mcp_config(config_path)
    text = format_codex_doctor_report(report)

    assert report["status"] == "ok"
    fields = {field["name"]: field for field in report["runtime_fields"]}
    assert fields["TRANSCRIPT_PERSONA"]["source"] == "derived:CHIMERA_PERSONA_ID"
    assert fields["CHIMERA_PERSONA_NAME"]["source"] == "derived:CHIMERA_PERSONA_ID"
    assert fields["CHIMERA_PERSONAS_DIR"]["source"] == "derived:CHIMERA_PERSONA_ROOT"
    assert fields["CHIMERA_SHARED_ROOT"]["source"] == "derived:CHIMERA_PERSONAS_DIR"
    assert "TRANSCRIPT_PERSONA: resolved (derived:CHIMERA_PERSONA_ID)" in text
    assert "Persona identity resolves via explicit and derived fields." in text


def test_codex_doctor_accepts_repo_scoped_project_profile(tmp_path: Path) -> None:
    jsonl_dir = tmp_path / "sessions"
    project_root = tmp_path / "repo" / ".chimera-memory"
    jsonl_dir.mkdir()
    project_root.mkdir(parents=True)
    config_path = tmp_path / "mcp_servers.json"
    payload = {
        "mcpServers": {
            "chimera-memory": {
                "command": sys.executable,
                "args": ["serve"],
                "env": {
                    "TRANSCRIPT_JSONL_DIR": str(jsonl_dir),
                    "TRANSCRIPT_DB_PATH": str(tmp_path / "missing-transcript.db"),
                    "CHIMERA_CLIENT": "codex",
                    "CHIMERA_MEMORY_PROJECT_ID": "Chimera-Memory",
                    "CHIMERA_MEMORY_PROJECT_ROOT": str(project_root),
                },
            },
        },
    }
    _write_config(config_path, payload)

    report = inspect_codex_mcp_config(config_path)
    text = format_codex_doctor_report(report)

    assert report["status"] == "ok"
    assert "No persona configured; Codex uses repo-scoped project memory." in text
    assert "Persona identity is intentionally unset for repo-scoped Codex memory." in text
    assert "Project memory identity resolves for repo-scoped Codex memory." in text


def test_codex_doctor_accepts_url_only_http_transport(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "mcp_servers.json"
    monkeypatch.setattr(
        "chimera_memory.codex_setup._default_transcript_db_path",
        lambda: str(tmp_path / "missing-transcript.db"),
    )
    _write_config(
        config_path,
        {
            "mcpServers": {
                "chimera-memory": {
                    "url": "https://cm.example.test/mcp",
                    "startup_timeout_sec": 30,
                },
            },
        },
    )

    report = inspect_codex_mcp_config(config_path)
    text = format_codex_doctor_report(report)

    assert report["status"] == "ok"
    assert report["transport"] == "http"
    assert "Transport: http" in text
    assert any(check["name"] == "url" and check["status"] == "ok" for check in report["checks"])
    assert not any(check["name"] in {"command", "args"} for check in report["checks"])


def test_codex_doctor_reports_dead_local_http_transport(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "mcp_servers.json"
    monkeypatch.setattr(
        "chimera_memory.codex_setup._default_transcript_db_path",
        lambda: str(tmp_path / "missing-transcript.db"),
    )

    def fail_connect(*args, **kwargs):
        raise OSError("closed")

    monkeypatch.setattr("chimera_memory.codex_setup.socket.create_connection", fail_connect)
    _write_config(
        config_path,
        {
            "mcpServers": {
                "chimera-memory": {
                    "url": "http://127.0.0.1:8766/mcp",
                    "startup_timeout_sec": 30,
                },
            },
        },
    )

    report = inspect_codex_mcp_config(config_path)

    assert report["status"] == "error"
    assert report["transport"] == "http"
    assert any(
        check["name"] == "url_reachable" and "No local MCP server" in check["message"]
        for check in report["checks"]
    )
    assert not any(check["name"] in {"command", "args"} for check in report["checks"])


def test_codex_doctor_summarizes_latest_health_snapshot(tmp_path: Path) -> None:
    jsonl_dir = tmp_path / "sessions"
    jsonl_dir.mkdir()
    db_path = tmp_path / "transcript.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE memory_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            event_type TEXT,
            payload TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO memory_audit_events (created_at, event_type, payload) VALUES (?, ?, ?)",
        (
            "2026-05-19T21:00:00Z",
            "cm_health_snapshot",
            json.dumps(
                {
                    "status": "degraded",
                    "checks": {
                        "workers": {
                            "status": "ok",
                            "transcript_indexer": True,
                            "transcript_embedding_worker": True,
                            "memory_enhancement_worker": True,
                        }
                    },
                }
            ),
        ),
    )
    conn.commit()
    conn.close()
    config_path = tmp_path / "mcp_servers.json"
    payload = _valid_codex_config(jsonl_dir)
    payload["mcpServers"]["chimera-memory"]["env"]["TRANSCRIPT_DB_PATH"] = str(db_path)
    _write_config(config_path, payload)

    report = inspect_codex_mcp_config(config_path)
    text = format_codex_doctor_report(report)

    assert report["status"] == "warning"
    assert "Latest CM health snapshot: degraded" in text
    assert "memory_enhancement_worker=True" in text


def test_codex_install_writes_minimal_config_and_preserves_other_servers(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    jsonl_dir = tmp_path / "sessions"
    persona_root = tmp_path / "personas" / "developer" / "asa"
    jsonl_dir.mkdir()
    persona_root.mkdir(parents=True)
    _write_config(
        config_path,
        {
            "mcpServers": {
                "other-server": {
                    "command": "other",
                    "args": [],
                    "env": {},
                }
            }
        },
    )

    receipt = install_codex_mcp_config(
        config_path=config_path,
        persona_id="developer/asa",
        persona_root=str(persona_root),
        jsonl_dir=str(jsonl_dir),
        command=sys.executable,
        import_history=False,
    )
    text = format_codex_install_report(receipt)
    written = json.loads(config_path.read_text(encoding="utf-8"))
    server = written["mcpServers"]["chimera-memory"]
    env = written["mcpServers"]["chimera-memory"]["env"]

    assert receipt["action"] == "update"
    assert Path(receipt["backup_path"]).is_file()
    assert "other-server" in written["mcpServers"]
    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "chimera_memory.cli", "serve"]
    assert env["CHIMERA_PERSONA_ID"] == "developer/asa"
    assert env["CHIMERA_PERSONA_ROOT"] == str(persona_root)
    assert env["CHIMERA_MEMORY_IMPORT_HISTORY"] == "false"
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "persona"
    assert env["CHIMERA_MEMORY_STARTUP_BOOTSTRAP"] == "post_ready"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_WORKER"] == "false"
    assert env["CHIMERA_MEMORY_TRANSCRIPT_EMBEDDING_WORKER"] == "true"
    assert env["CHIMERA_MEMORY_HEALTH_WORKER"] == "true"
    assert env["CHIMERA_MEMORY_STATE_ROOT"] == "~/.chimera-memory"
    assert "TRANSCRIPT_PERSONA" not in env
    assert "Import history: disabled" in text
    assert "CHIMERA_PERSONA_ID: resolved (explicit)" in text

    doctor = inspect_codex_mcp_config(config_path)
    assert doctor["status"] == "ok"


def test_codex_install_writes_repo_scoped_project_config(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    jsonl_dir = tmp_path / "sessions"
    project_root = tmp_path / "repo" / ".chimera-memory"
    jsonl_dir.mkdir()

    receipt = install_codex_mcp_config(
        config_path=config_path,
        project_id="Chimera Memory!",
        project_root=str(project_root),
        jsonl_dir=str(jsonl_dir),
        command=sys.executable,
        import_history=False,
    )
    written = json.loads(config_path.read_text(encoding="utf-8"))
    env = written["mcpServers"]["chimera-memory"]["env"]
    env["TRANSCRIPT_DB_PATH"] = str(tmp_path / "missing-transcript.db")
    _write_config(config_path, written)

    assert receipt["memory_profile"] == "project"
    assert receipt["project_id"] == "Chimera-Memory"
    assert env["CHIMERA_MEMORY_PROJECT_ID"] == "Chimera-Memory"
    assert env["CHIMERA_MEMORY_PROJECT_ROOT"] == str(project_root)
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "codex"
    assert "TRANSCRIPT_PERSONA" not in env
    assert "CHIMERA_PERSONA_ID" not in env

    doctor = inspect_codex_mcp_config(config_path)
    assert doctor["status"] == "ok"


def test_codex_install_writes_desktop_config_toml(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    jsonl_dir = tmp_path / "sessions"
    project_root = tmp_path / "repo" / ".chimera-memory"
    jsonl_dir.mkdir()
    config_path.write_text(
        "\n".join(
            [
                '[mcp_servers.node_repl]',
                'command = "node_repl.exe"',
                "args = []",
                "",
            ]
        ),
        encoding="utf-8",
    )

    receipt = install_codex_mcp_config(
        config_path=config_path,
        project_id="Chimera Memory!",
        project_root=str(project_root),
        jsonl_dir=str(jsonl_dir),
        command="python -m chimera_memory.cli",
        import_history=False,
    )
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    server = data["mcp_servers"]["chimera-memory"]
    env = server["env"]

    assert receipt["memory_profile"] == "project"
    assert receipt["mcp_surface"] == "codex"
    assert data["mcp_servers"]["node_repl"]["command"] == "node_repl.exe"
    assert server["command"] == "python"
    assert server["args"] == ["-m", "chimera_memory.cli", "serve"]
    assert env["CHIMERA_MEMORY_PROJECT_ID"] == "Chimera-Memory"
    assert env["CHIMERA_MEMORY_PROJECT_ROOT"] == str(project_root)
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "codex"

    monkeypatch.setattr(
        "chimera_memory.codex_setup._default_transcript_db_path",
        lambda: str(tmp_path / "missing-transcript.db"),
    )
    doctor = inspect_codex_mcp_config(config_path)
    assert doctor["status"] == "ok"


def test_codex_install_can_add_project_env_to_persona_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    jsonl_dir = tmp_path / "sessions"
    project_root = tmp_path / "repo" / ".chimera-memory"
    jsonl_dir.mkdir()

    receipt = install_codex_mcp_config(
        config_path=config_path,
        persona_id="developer/asa",
        project_id="ChimeraMemory",
        project_root=str(project_root),
        jsonl_dir=str(jsonl_dir),
        command=sys.executable,
        import_history=False,
    )
    env = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]["chimera-memory"]["env"]

    assert receipt["memory_profile"] == "persona"
    assert receipt["project_id"] == "ChimeraMemory"
    assert env["CHIMERA_PERSONA_ID"] == "developer/asa"
    assert env["CHIMERA_MEMORY_PROJECT_ID"] == "ChimeraMemory"
    assert env["CHIMERA_MEMORY_PROJECT_ROOT"] == str(project_root)
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "persona"


def test_codex_install_dry_run_does_not_write(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"

    receipt = install_codex_mcp_config(
        config_path=config_path,
        persona="asa",
        dry_run=True,
    )

    assert receipt["dry_run"] is True
    assert receipt["action"] == "create"
    assert not config_path.exists()


def test_codex_install_can_reuse_provider_login_without_echoing_tokens(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    jsonl_dir = tmp_path / "sessions"
    codex_auth_path = tmp_path / ".codex" / "auth.json"
    oauth_store = tmp_path / "auth.json"
    jsonl_dir.mkdir()
    codex_auth_path.parent.mkdir()
    codex_auth_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "TEST_ONLY_OPENAI_ACCESS",
                    "refresh_token": "TEST_ONLY_OPENAI_REFRESH",
                }
            }
        ),
        encoding="utf-8",
    )

    receipt = install_codex_mcp_config(
        config_path=config_path,
        persona_id="developer/asa",
        jsonl_dir=str(jsonl_dir),
        command=sys.executable,
        provider="openai",
        reuse_provider_auth=True,
        oauth_store=str(oauth_store),
        codex_auth_path=codex_auth_path,
    )
    text = format_codex_install_report(receipt)
    serialized = json.dumps(receipt)
    env = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]["chimera-memory"]["env"]

    assert receipt["provider"] == "openai"
    assert receipt["provider_auth"]["status"] == "imported"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_AFFINITY"] == "openai"
    assert env["CHIMERA_MEMORY_OAUTH_STORE"] == str(oauth_store)
    assert "Provider auth: imported" in text
    assert "TEST_ONLY_OPENAI_ACCESS" not in serialized
    assert "TEST_ONLY_OPENAI_REFRESH" not in serialized
    assert "TEST_ONLY_OPENAI_ACCESS" not in text
    assert "TEST_ONLY_OPENAI_REFRESH" not in text


def test_codex_install_prefers_codex_cli_worker_for_openai_provider(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    jsonl_dir = tmp_path / "sessions"
    jsonl_dir.mkdir()

    receipt = install_codex_mcp_config(
        config_path=config_path,
        persona_id="developer/asa",
        jsonl_dir=str(jsonl_dir),
        command=sys.executable,
        provider="openai",
        enable_provider_worker=True,
    )
    env = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]["chimera-memory"]["env"]
    text = format_codex_install_report(receipt)

    assert receipt["provider_worker_mode"] == "cli_worker"
    assert receipt["provider_worker_runtime"] == "codex"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE"] == "cli_worker"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE"] == "true"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE_PERSONAS"] == "asa"
    assert env["CHIMERA_MEMORY_CLI_WORKER_RUNTIME"] == "codex"
    assert env["CHIMERA_MEMORY_CLI_WORKER_EFFORT"] == "medium"
    assert env["CHIMERA_MEMORY_CODEX_WORKER_PROVIDER"] == "openai"
    assert env["CHIMERA_MEMORY_CODEX_WORKER_MODEL"] == "gpt-5.3-codex-spark"
    assert "Provider worker runtime: codex" in text


def test_codex_install_prefers_claude_cli_worker_for_anthropic_provider(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    jsonl_dir = tmp_path / "sessions"
    jsonl_dir.mkdir()

    receipt = install_codex_mcp_config(
        config_path=config_path,
        persona_id="developer/asa",
        jsonl_dir=str(jsonl_dir),
        command=sys.executable,
        provider="anthropic",
        enable_provider_worker=True,
    )
    env = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]["chimera-memory"]["env"]

    assert receipt["provider_worker_mode"] == "cli_worker"
    assert receipt["provider_worker_runtime"] == "claude"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE"] == "cli_worker"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE"] == "true"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE_PERSONAS"] == "asa"
    assert env["CHIMERA_MEMORY_CLI_WORKER_RUNTIME"] == "claude"
    assert env["CHIMERA_MEMORY_CLI_WORKER_EFFORT"] == "medium"
    assert env["CHIMERA_MEMORY_CLAUDE_WORKER_PROVIDER"] == "anthropic"


def test_codex_install_prefers_agy_cli_worker_for_google_provider(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    jsonl_dir = tmp_path / "sessions"
    jsonl_dir.mkdir()

    receipt = install_codex_mcp_config(
        config_path=config_path,
        persona_id="developer/asa",
        jsonl_dir=str(jsonl_dir),
        command=sys.executable,
        provider="google",
        enable_provider_worker=True,
    )
    env = json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]["chimera-memory"]["env"]

    assert receipt["provider_worker_mode"] == "cli_worker"
    assert receipt["provider_worker_runtime"] == "agy"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE"] == "cli_worker"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE"] == "true"
    assert env["CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE_PERSONAS"] == "asa"
    assert env["CHIMERA_MEMORY_CLI_WORKER_RUNTIME"] == "agy"
    assert env["CHIMERA_MEMORY_CLI_WORKER_EFFORT"] == "medium"
    assert env["CHIMERA_MEMORY_AGY_WORKER_PROVIDER"] == "google"


def test_codex_template_builds_safe_config_without_secrets() -> None:
    config = build_codex_mcp_config(
        persona="asa",
        jsonl_dir="~/.codex/sessions",
        persona_id="developer/asa",
        persona_name="asa",
        persona_root="C:/Github/ChimeraAgency/personas/developer/asa",
        personas_dir="C:/Github/ChimeraAgency/personas",
        shared_root="C:/Github/ChimeraAgency/shared",
    )
    text = json.dumps(config)

    server = config["mcpServers"]["chimera-memory"]
    env = server["env"]

    assert server["command"] == "chimera-memory"
    assert server["args"] == ["serve"]
    assert env["TRANSCRIPT_PERSONA"] == "asa"
    assert env["CHIMERA_CLIENT"] == "codex"
    assert env["CHIMERA_PERSONA_ID"] == "developer/asa"
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "persona"
    assert "SECRET" not in text
    assert "TOKEN" not in text


def test_codex_template_without_persona_builds_project_profile() -> None:
    config = build_codex_mcp_config(
        project_id="Chimera Memory!",
        project_root="C:/Github/Chimera-Memory/.chimera-memory",
    )
    env = config["mcpServers"]["chimera-memory"]["env"]

    assert env["CHIMERA_MEMORY_PROJECT_ID"] == "Chimera-Memory"
    assert env["CHIMERA_MEMORY_PROJECT_ROOT"] == "C:/Github/Chimera-Memory/.chimera-memory"
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "codex"
    assert "TRANSCRIPT_PERSONA" not in env


def test_codex_template_splits_python_module_command() -> None:
    command = f'"{sys.executable}" -m chimera_memory.cli'

    config = build_codex_mcp_config(project_id="ChimeraMemory", command=command)
    server = config["mcpServers"]["chimera-memory"]

    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "chimera_memory.cli", "serve"]


def test_codex_template_with_persona_can_include_project_env() -> None:
    config = build_codex_mcp_config(
        persona_id="developer/asa",
        project_id="ChimeraMemory",
        project_root="C:/Github/Chimera-Memory/.chimera-memory",
    )
    env = config["mcpServers"]["chimera-memory"]["env"]

    assert env["TRANSCRIPT_PERSONA"] == "asa"
    assert env["CHIMERA_PERSONA_ID"] == "developer/asa"
    assert env["CHIMERA_MEMORY_PROJECT_ID"] == "ChimeraMemory"
    assert env["CHIMERA_MEMORY_PROJECT_ROOT"] == "C:/Github/Chimera-Memory/.chimera-memory"
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "persona"


def test_codex_template_cli_prints_json_without_shadowing_subcommand() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "chimera_memory.cli",
            "codex",
            "template",
            "--persona",
            "asa",
            "--command",
            sys.executable,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout)
    server = payload["mcpServers"]["chimera-memory"]

    assert server["command"] == sys.executable
    assert server["env"]["CHIMERA_CLIENT"] == "codex"


def test_codex_template_cli_prints_project_json_without_persona(tmp_path: Path) -> None:
    project_root = tmp_path / "repo" / ".chimera-memory"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "chimera_memory.cli",
            "codex",
            "template",
            "--project-id",
            "Chimera Memory!",
            "--project-root",
            str(project_root),
            "--command",
            sys.executable,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout)
    env = payload["mcpServers"]["chimera-memory"]["env"]

    assert env["CHIMERA_MEMORY_PROJECT_ID"] == "Chimera-Memory"
    assert env["CHIMERA_MEMORY_PROJECT_ROOT"] == str(project_root)
    assert env["CHIMERA_MEMORY_MCP_SURFACE"] == "codex"
    assert "TRANSCRIPT_PERSONA" not in env


def test_codex_install_cli_dry_run_json(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "chimera_memory.cli",
            "codex",
            "install",
            "--config",
            str(config_path),
            "--persona-id",
            "developer/asa",
            "--command",
            sys.executable,
            "--no-import-history",
            "--dry-run",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(proc.stdout)

    assert receipt["dry_run"] is True
    assert receipt["import_history"] is False
    assert "CHIMERA_MEMORY_IMPORT_HISTORY" in receipt["env_keys"]
    assert not config_path.exists()


def test_codex_install_cli_project_dry_run_json(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    project_root = tmp_path / "repo" / ".chimera-memory"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "chimera_memory.cli",
            "codex",
            "install",
            "--config",
            str(config_path),
            "--project-id",
            "Chimera Memory!",
            "--project-root",
            str(project_root),
            "--command",
            sys.executable,
            "--no-import-history",
            "--dry-run",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(proc.stdout)

    assert receipt["memory_profile"] == "project"
    assert receipt["project_id"] == "Chimera-Memory"
    assert receipt["mcp_surface"] == "codex"
    assert "CHIMERA_MEMORY_PROJECT_ID" in receipt["env_keys"]
    assert "TRANSCRIPT_PERSONA" not in receipt["env_keys"]
    assert not config_path.exists()


def test_codex_install_cli_provider_reuse_json(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    codex_auth_path = tmp_path / ".codex" / "auth.json"
    oauth_store = tmp_path / "auth.json"
    codex_auth_path.parent.mkdir()
    codex_auth_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "TEST_ONLY_OPENAI_ACCESS",
                    "refresh_token": "TEST_ONLY_OPENAI_REFRESH",
                }
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "chimera_memory.cli",
            "codex",
            "install",
            "--config",
            str(config_path),
            "--persona-id",
            "developer/asa",
            "--command",
            sys.executable,
            "--provider",
            "openai",
            "--reuse-provider-login",
            "--oauth-store",
            str(oauth_store),
            "--codex-auth-path",
            str(codex_auth_path),
            "--import-history",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(proc.stdout)

    assert receipt["provider"] == "openai"
    assert receipt["provider_auth"]["status"] == "imported"
    assert "TEST_ONLY_OPENAI_ACCESS" not in proc.stdout
    assert "TEST_ONLY_OPENAI_REFRESH" not in proc.stdout
