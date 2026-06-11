import json
import sqlite3
import sys
import threading
from pathlib import Path

import pytest
import yaml

from chimera_memory.cli import main
from chimera_memory.memory import index_file, init_memory_tables, memory_enhancement_enqueue
from chimera_memory.memory_enhancement_oauth import MemoryEnhancementOAuthStore
from chimera_memory.memory_enhancement_oauth_import import import_memory_enhancement_oauth_credential
from chimera_memory.memory_enhancement_sidecar import create_dry_run_sidecar_server


def _index_cli_memory(db_path: Path, memory_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
        memory_path.write_text(
            "\n".join(
                [
                    "---",
                    "type: procedural",
                    "importance: 7",
                    "tags: [cli, sidecar]",
                    "---",
                    "CLI dry-run should process queued metadata on 2026-05-14.",
                    "TODO: keep the real model adapter behind a separate seam.",
                ]
            ),
            encoding="utf-8",
        )
        assert index_file(conn, "asa", memory_path.name, memory_path)
        conn.commit()
    finally:
        conn.close()


def test_cli_enhance_provider_plan_json_excludes_credential_refs(monkeypatch, capsys) -> None:
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF", "oauth:openai-memory")
    monkeypatch.setattr(sys, "argv", ["chimera-memory", "enhance", "provider-plan", "--json"])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_provider"] == "openai"
    assert payload["candidates"][0]["credential_ref_present"] is True
    assert "oauth:openai-memory" not in json.dumps(payload)


def test_cli_enhance_provider_plan_recommends_codex_oauth_import_body_safe(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    codex_path = tmp_path / ".codex" / "auth.json"
    codex_path.parent.mkdir()
    codex_path.write_text(
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
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER", "openai,dry_run")
    monkeypatch.setenv("CHIMERA_MEMORY_CODEX_AUTH_PATH", str(codex_path))
    monkeypatch.setenv("CHIMERA_MEMORY_OAUTH_STORE", str(tmp_path / "empty-auth.json"))
    monkeypatch.delenv("CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF", raising=False)
    monkeypatch.setattr(sys, "argv", ["chimera-memory", "enhance", "provider-plan", "--json"])

    main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["selected_provider"] == "dry_run"
    assert payload["recommendations"][0]["code"] == "import_openai_codex_oauth"
    assert "TEST_ONLY_OPENAI_ACCESS" not in output
    assert "TEST_ONLY_OPENAI_REFRESH" not in output


def test_cli_enhance_provider_smoke_plan_json_is_body_safe(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER", "openai,dry_run")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF", "oauth:openai-memory")
    monkeypatch.setenv("CHIMERA_MEMORY_OAUTH_STORE", str(tmp_path / "auth.json"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["chimera-memory", "enhance", "provider-smoke", "--json"],
    )

    main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ok"] is True
    assert payload["status"] == "planned"
    assert payload["provider"]["selected_provider"] == "openai"
    assert payload["provider"]["selected_model"] == "gpt-5.3-codex-spark"
    assert payload["invocation"]["credential_ref_present"] is True
    assert "oauth:openai-memory" not in output
    assert "Chimera Memory provider smoke" not in output


def test_cli_enhance_provider_smoke_expectation_failure_exits_with_safe_json(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER", "openai,dry_run")
    monkeypatch.setenv("CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF", "oauth:openai-memory")
    monkeypatch.setenv("CHIMERA_MEMORY_OAUTH_STORE", str(tmp_path / "auth.json"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "provider-smoke",
            "--expect-model",
            "not-spark",
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as raised:
        main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert raised.value.code == 2
    assert payload["ok"] is False
    assert payload["status"] == "expectation_failed"
    assert payload["error"]["code"] == "model_mismatch"
    assert "oauth:openai-memory" not in output
    assert "Chimera Memory provider smoke" not in output


def test_cli_enhance_oauth_import_json_excludes_token_values(tmp_path: Path, monkeypatch, capsys) -> None:
    codex_path = tmp_path / ".codex" / "auth.json"
    store_path = tmp_path / "memory-oauth.json"
    codex_path.parent.mkdir()
    codex_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "TEST_ONLY_OPENAI_ACCESS",
                    "refresh_token": "TEST_ONLY_OPENAI_REFRESH",
                    "account_id": "acct_test",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "oauth-import",
            "--provider",
            "openai",
            "--source",
            "codex_cli",
            "--codex-auth-path",
            str(codex_path),
            "--store",
            str(store_path),
            "--json",
        ],
    )

    main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["status"] == "imported"
    assert payload["credential"]["provider_id"] == "openai"
    assert payload["credential"]["value_present"] is True
    assert "TEST_ONLY_OPENAI_ACCESS" not in output
    assert "TEST_ONLY_OPENAI_REFRESH" not in output


def test_cli_enhance_oauth_list_json_excludes_token_values(tmp_path: Path, monkeypatch, capsys) -> None:
    codex_path = tmp_path / ".codex" / "auth.json"
    store_path = tmp_path / "memory-oauth.json"
    codex_path.parent.mkdir()
    codex_path.write_text(
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
    store = MemoryEnhancementOAuthStore(store_path)
    import_memory_enhancement_oauth_credential(
        provider_id="openai",
        source="codex_cli",
        store=store,
        codex_auth_path=codex_path,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "oauth-list",
            "--store",
            str(store_path),
            "--json",
        ],
    )

    main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["credential_count"] == 1
    assert payload["credentials"][0]["provider_id"] == "openai"
    assert payload["credentials"][0]["active"] is True
    assert "TEST_ONLY_OPENAI_ACCESS" not in output
    assert "TEST_ONLY_OPENAI_REFRESH" not in output


def test_cli_enhance_enqueue_and_dry_run_json(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "transcript.db"
    memory_path = tmp_path / "cli-memory.md"
    _index_cli_memory(db_path, memory_path)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "enqueue",
            "--db",
            str(db_path),
            "--file",
            memory_path.name,
            "--json",
        ],
    )
    main()
    enqueue_output = capsys.readouterr().out
    enqueued = json.loads(enqueue_output)
    assert enqueued["ok"] is True
    assert enqueued["job"]["status"] == "pending"
    assert enqueued["job"]["path"] == memory_path.name
    assert enqueued["job"]["path_fingerprint"]
    assert enqueued["job"]["request_payload"]["task"] == "extract_memory_metadata"
    assert "wrapped_content" in enqueued["job"]["request_payload"]["redacted_fields"]
    assert str(tmp_path) not in enqueue_output
    assert "CLI dry-run should process queued metadata" not in enqueue_output

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "dry-run",
            "--db",
            str(db_path),
            "--persona",
            "asa",
            "--json",
        ],
    )
    main()
    processed_output = capsys.readouterr().out
    processed = json.loads(processed_output)
    assert processed["processed_count"] == 1
    assert processed["processed"][0]["status"] == "succeeded"
    assert processed["processed"][0]["result_payload"]["review_status"] == "pending"
    assert processed["processed"][0]["result_payload"]["can_use_as_instruction"] is False
    assert "summary" in processed["processed"][0]["result_payload"]["redacted_fields"]
    assert str(tmp_path) not in processed_output
    assert "CLI dry-run should process queued metadata" not in processed_output


def test_cli_enhance_worker_fake_json(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "transcript.db"
    memory_path = tmp_path / "cli-worker-fake.md"
    _index_cli_memory(db_path, memory_path)
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
        enqueued = memory_enhancement_enqueue(conn, file_path=memory_path.name)
    finally:
        conn.close()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "worker-fake",
            "--db",
            str(db_path),
            "--persona",
            "asa",
            "--worker-id",
            "fake-cli-worker",
            "--json",
        ],
    )
    main()

    output = capsys.readouterr().out
    receipt = json.loads(output)
    assert receipt["processed_count"] == 1
    assert receipt["failure_count"] == 0
    assert receipt["worker_id"] == "fake-cli-worker"
    assert receipt["processed"][0]["job_id"] == enqueued["job"]["job_id"]
    assert receipt["processed"][0]["actual_provider"] == "dry_run"
    assert str(tmp_path) not in output
    assert "CLI dry-run should process queued metadata" not in output


def test_cli_enhance_worker_doctor_json_initializes_without_launching(tmp_path: Path, monkeypatch, capsys) -> None:
    source_auth = tmp_path / "codex-auth.json"
    source_auth.write_text('{"access_token":"TEST_ONLY_TOKEN"}\n', encoding="utf-8")
    monkeypatch.setenv("CHIMERA_MEMORY_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_MEMORY_CODEX_WORKER_AUTH_PATH", str(source_auth))
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.shutil.which", lambda command: command)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "worker-doctor",
            "--runtime",
            "codex",
            "--init",
            "--json",
        ],
    )

    main()

    output = capsys.readouterr().out
    receipt = json.loads(output)
    assert receipt["ok"] is True
    assert receipt["runtime"] == "codex"
    assert receipt["initialized"] is True
    assert receipt["launch_performed"] is False
    assert receipt["credential"] == {"required": True, "present": True, "role": "auth"}
    assert receipt["readiness"]["missing_required_files"] == []
    assert "command_preview" not in receipt
    assert receipt["files"]["mcp_config"]["exists"] is True
    assert receipt["files"]["auth"]["exists"] is True
    assert str(tmp_path) not in output


def test_cli_enhance_worker_doctor_json_reports_missing_codex_auth_without_paths(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("CHIMERA_MEMORY_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_MEMORY_CODEX_WORKER_AUTH_PATH", str(tmp_path / "missing-auth.json"))
    monkeypatch.setenv("CHIMERA_MEMORY_CODEX_BIN", str(tmp_path / "bin" / "codex.cmd"))
    monkeypatch.setattr("chimera_memory.memory_cli_worker_supervisor.shutil.which", lambda command: command)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "worker-doctor",
            "--runtime",
            "codex",
            "--init",
            "--json",
        ],
    )

    main()

    output = capsys.readouterr().out
    receipt = json.loads(output)
    assert receipt["ok"] is False
    assert receipt["credential"] == {"required": True, "present": False, "role": "auth"}
    assert "auth" in receipt["readiness"]["missing_required_files"]
    assert receipt["executable"] == "codex.cmd"
    assert "command_preview" not in receipt
    assert str(tmp_path) not in output


def test_cli_enhance_authored_enqueue_json(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "transcript.db"
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
    finally:
        conn.close()
    payload_path = tmp_path / "authored.json"
    payload_path.write_text(
        json.dumps(
            {
                "memory_payload": {
                    "memory_type": "procedural",
                    "lessons": [{"teaching": "Structured writeback keeps LLM enrichment narrow."}],
                    "next_steps": [{"action": "Keep LLM enrichment narrow"}],
                },
                "provenance": {"status": "generated"},
                "source_ref": "day61/structured-writeback",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "authored-enqueue",
            "--db",
            str(db_path),
            "--persona",
            "asa",
            "--payload",
            str(payload_path),
            "--json",
        ],
    )

    main()

    output = capsys.readouterr().out
    enqueued = json.loads(output)
    assert enqueued["ok"] is True
    assert enqueued["job"]["status"] == "pending"
    assert enqueued["job"]["path"] == "day61/structured-writeback"
    assert enqueued["job"]["request_payload"]["task"] == "enrich_authored_memory_payload"
    assert "contract" in enqueued["job"]["request_payload"]["redacted_fields"]
    assert "memory_payload" in enqueued["job"]["request_payload"]["redacted_fields"]
    assert "wrapped_content" in enqueued["job"]["request_payload"]["redacted_fields"]
    assert "Structured writeback keeps LLM enrichment narrow" not in output
    assert "Keep LLM enrichment narrow" not in output


def test_cli_enhance_authored_write_yaml_json(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "transcript.db"
    personas_dir = tmp_path / "personas"
    (personas_dir / "researcher" / "sarah").mkdir(parents=True)
    payload_path = tmp_path / "authored.yaml"
    payload_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "memory_id": "slice-4-writer",
                "memory_type": "procedural",
                "memory_payload": {
                    "lessons": [{"teaching": "Structured writer preserves authored fields."}],
                    "next_steps": [{"action": "Queue narrow enrichment"}],
                    "entities": {"projects": ["ChimeraMemory"], "topics": ["writeback discipline"]},
                },
                "provenance": {
                    "default_status": "user_confirmed",
                    "requires_review": False,
                    "confidence": 1.0,
                },
                "review_status": "confirmed",
                "source_refs": [{"kind": "test", "uri": "cli-authored-write"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "authored-write",
            "--db",
            str(db_path),
            "--personas-dir",
            str(personas_dir),
            "--persona",
            "sarah",
            "--payload",
            str(payload_path),
            "--write",
            "--json",
        ],
    )

    main()

    written = json.loads(capsys.readouterr().out)
    assert written["ok"] is True
    assert written["written"] is True
    assert written["relative_path"] == "memory/procedural/slice-4-writer.md"
    assert Path(written["path"]).exists()
    assert written["enrichment_job"]["job"]["file_id"] == written["file_id"]

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, request_payload FROM memory_enhancement_jobs WHERE file_id = ?",
            (written["file_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "pending"
    assert json.loads(row[1])["task"] == "enrich_authored_memory_payload"


def test_cli_enhance_authored_write_global_scope_without_persona(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "transcript.db"
    global_root = tmp_path / "global-memory"
    payload_path = tmp_path / "global-authored.yaml"
    payload_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "memory_id": "codex-global-cli-write",
                "memory_type": "procedural",
                "memory_payload": {
                    "decisions": [
                        {
                            "what": "Codex CLI can write global authored memory without persona inputs."
                        }
                    ],
                    "entities": {"projects": ["ChimeraMemory"], "topics": ["writeback discipline"]},
                },
                "provenance": {
                    "default_status": "user_confirmed",
                    "requires_review": False,
                    "confidence": 1.0,
                },
                "review_status": "confirmed",
                "source_refs": [{"kind": "test", "uri": "cli-global-authored-write"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "authored-write",
            "--db",
            str(db_path),
            "--scope",
            "global",
            "--global-root",
            str(global_root),
            "--payload",
            str(payload_path),
            "--write",
            "--no-enqueue",
            "--json",
        ],
    )

    main()

    written = json.loads(capsys.readouterr().out)
    assert written["ok"] is True
    assert written["written"] is True
    assert written["relative_path"] == "memory/procedural/codex-global-cli-write.md"
    target = global_root / "memory" / "procedural" / "codex-global-cli-write.md"
    assert Path(written["path"]) == target
    assert target.exists()

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT persona, memory_scope, project_id FROM memory_files WHERE id = ?",
            (written["file_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("global", "global", None)
    assert written["enrichment_job"]["enqueued"] is False


def test_cli_enhance_enqueue_missing_file_exits_cleanly(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "transcript.db"
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "enqueue",
            "--db",
            str(db_path),
            "--file",
            "missing.md",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "Enhancement enqueue failed" in capsys.readouterr().out


def test_cli_enhance_sidecar_run_processes_queued_job(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "transcript.db"
    memory_path = tmp_path / "sidecar-run.md"
    _index_cli_memory(db_path, memory_path)
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
        enqueued = memory_enhancement_enqueue(conn, file_path=memory_path.name)
    finally:
        conn.close()
    assert enqueued["ok"] is True

    fake_token = "TEST_ONLY_SIDE_TOKEN"
    server = create_dry_run_sidecar_server("127.0.0.1", 0, bearer_token=fake_token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("CHIMERA_MEMORY_TEST_SIDECAR_TOKEN", fake_token)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "chimera-memory",
                "enhance",
                "sidecar-run",
                "--db",
                str(db_path),
                "--endpoint",
                f"http://127.0.0.1:{server.server_port}/enhance",
                "--persona",
                "asa",
                "--token-env",
                "CHIMERA_MEMORY_TEST_SIDECAR_TOKEN",
                "--json",
            ],
        )

        main()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    receipt = json.loads(capsys.readouterr().out)
    assert receipt["processed_count"] == 1
    assert receipt["failure_count"] == 0
    assert receipt["processed"][0]["job_id"] == enqueued["job"]["job_id"]
    assert fake_token not in json.dumps(receipt)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, result_payload FROM memory_enhancement_jobs WHERE job_id = ?",
            (enqueued["job"]["job_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "succeeded"
    assert '"can_use_as_instruction": false' in row[1]


def test_cli_enhance_serve_provider_uses_separate_sidecar_and_provider_tokens(monkeypatch, capsys) -> None:
    sidecar_token = "TEST_ONLY_SIDECAR_TOKEN"
    provider_token = "TEST_ONLY_PROVIDER_TOKEN"
    captured = {}

    def fake_run_provider_sidecar(host, port, *, client, bearer_token):
        captured["host"] = host
        captured["port"] = port
        captured["client"] = client
        captured["bearer_token"] = bearer_token

    monkeypatch.setenv("CHIMERA_MEMORY_TEST_SIDECAR_TOKEN", sidecar_token)
    monkeypatch.setenv("CHIMERA_MEMORY_TEST_PROVIDER_TOKEN", provider_token)
    monkeypatch.setattr(
        "chimera_memory.memory_enhancement_sidecar.run_provider_sidecar",
        fake_run_provider_sidecar,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "serve-provider",
            "--host",
            "127.0.0.1",
            "--port",
            "8998",
            "--token-env",
            "CHIMERA_MEMORY_TEST_SIDECAR_TOKEN",
            "--provider-token-env",
            "CHIMERA_MEMORY_TEST_PROVIDER_TOKEN",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8998
    assert captured["bearer_token"] == sidecar_token
    assert captured["client"]._api_key_client_factory("").bearer_token == provider_token
    assert sidecar_token not in output
    assert provider_token not in output


def test_cli_enhance_serve_provider_missing_provider_token_exits_without_env_name(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "enhance",
            "serve-provider",
            "--provider-token-env",
            "CHIMERA_MEMORY_TEST_PROVIDER_TOKEN",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Provider token env var is not set" in captured.err
    assert "CHIMERA_MEMORY_TEST_PROVIDER_TOKEN" not in captured.err
