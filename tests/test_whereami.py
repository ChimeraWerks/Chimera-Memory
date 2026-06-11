from __future__ import annotations

from pathlib import Path

import chimera_memory.config as config
import chimera_memory.server as server


RUNTIME_ENV_KEYS = [
    "TRANSCRIPT_DB_PATH",
    "TRANSCRIPT_JSONL_DIR",
    "TRANSCRIPT_PERSONA",
    "CHIMERA_PERSONA_ID",
    "CHIMERA_PERSONA_NAME",
    "CHIMERA_PERSONA_ROOT",
    "CHIMERA_PERSONAS_DIR",
    "CHIMERA_SHARED_ROOT",
    "CHIMERA_CLIENT",
    "CHIMERA_MEMORY_PERSONA_DB_ROOT",
    "CHIMERA_MEMORY_PROJECT_ID",
    "CHIMERA_MEMORY_PROJECT_ROOT",
    "CHIMERA_MEMORY_PROJECT_ROOTS",
    "CHIMERA_MEMORY_GLOBAL_ROOT",
]


def _clear_runtime_env(monkeypatch) -> None:
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_memory_whereami_reports_env_overrides(tmp_path: Path, monkeypatch) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")

    persona_root = tmp_path / "personas" / "developer" / "asa"
    shared_root = tmp_path / "shared"
    jsonl_dir = tmp_path / "sessions"
    db_path = tmp_path / "transcript.db"
    global_root = tmp_path / "global-memory"
    project_root = tmp_path / "repo" / ".chimera-memory"
    persona_root.mkdir(parents=True)
    shared_root.mkdir()
    jsonl_dir.mkdir()
    global_root.mkdir()
    project_root.mkdir(parents=True)

    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(db_path))
    monkeypatch.setenv("TRANSCRIPT_JSONL_DIR", str(jsonl_dir))
    monkeypatch.setenv("TRANSCRIPT_PERSONA", "asa")
    monkeypatch.setenv("CHIMERA_PERSONA_ID", "developer/asa")
    monkeypatch.setenv("CHIMERA_PERSONA_NAME", "asa")
    monkeypatch.setenv("CHIMERA_PERSONA_ROOT", str(persona_root))
    monkeypatch.setenv("CHIMERA_PERSONAS_DIR", str(tmp_path / "personas"))
    monkeypatch.setenv("CHIMERA_SHARED_ROOT", str(shared_root))
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    monkeypatch.setenv("CHIMERA_MEMORY_GLOBAL_ROOT", str(global_root))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "ChimeraMemory")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(project_root))

    payload = server.resolve_memory_whereami()

    assert payload["resolved"]["db_path"] == str(db_path)
    assert payload["provenance"]["db_path"] == {"source": "env", "key": "TRANSCRIPT_DB_PATH"}
    assert payload["resolved"]["jsonl_dir"] == str(jsonl_dir)
    assert payload["provenance"]["jsonl_dir"] == {"source": "env", "key": "TRANSCRIPT_JSONL_DIR"}
    assert payload["resolved"]["transcript_persona"] == "asa"
    assert payload["resolved"]["persona_id"] == "developer/asa"
    assert payload["resolved"]["client"] == "codex"
    assert payload["resolved"]["global_root"] == str(global_root)
    assert payload["provenance"]["global_root"] == {"source": "env", "key": "CHIMERA_MEMORY_GLOBAL_ROOT"}
    assert payload["resolved"]["project_id"] == "ChimeraMemory"
    assert payload["resolved"]["project_root"] == str(project_root)
    assert payload["warnings"] == []


def test_memory_whereami_reports_config_and_default_sources(tmp_path: Path, monkeypatch) -> None:
    _clear_runtime_env(monkeypatch)
    config_path = tmp_path / "config.yaml"
    jsonl_dir = tmp_path / "from-config"
    default_db = tmp_path / "default.db"
    default_jsonl = tmp_path / "default-jsonl"
    config_path.write_text(
        f"jsonl_dir: {jsonl_dir}\npersona: sarah\nclient: claude\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(server, "get_default_db_path", lambda: default_db)
    monkeypatch.setattr(server, "get_default_jsonl_dir", lambda: default_jsonl)

    payload = server.resolve_memory_whereami()

    assert payload["resolved"]["db_path"] == str(default_db)
    assert payload["provenance"]["db_path"] == {
        "source": "default",
        "function": "get_default_db_path",
    }
    assert payload["resolved"]["jsonl_dir"] == str(jsonl_dir)
    assert payload["provenance"]["jsonl_dir"]["source"] == "config"
    assert payload["provenance"]["jsonl_dir"]["path"] == str(config_path)
    assert payload["resolved"]["transcript_persona"] == "sarah"
    assert payload["provenance"]["transcript_persona"]["source"] == "config"
    assert payload["resolved"]["client"] == "claude"
    assert payload["provenance"]["client"]["source"] == "config"
    assert payload["resolved"]["persona_id"] is None
    assert payload["provenance"]["persona_id"] == {"source": "missing", "key": "CHIMERA_PERSONA_ID"}
    assert payload["resolved"]["global_root"] == str(Path.home() / ".chimera-memory" / "global-memory")
    assert payload["provenance"]["global_root"] == {
        "source": "default",
        "function": "chimera_memory.memory_scope.global_memory_root",
    }


def test_memory_whereami_warns_when_root_is_overridden_by_explicit_db(tmp_path: Path, monkeypatch) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(tmp_path / "explicit.db"))
    monkeypatch.setenv("CHIMERA_MEMORY_PERSONA_DB_ROOT", str(tmp_path / "personas"))

    payload = server.resolve_memory_whereami()

    assert payload["resolved"]["persona_db_root"] == str(tmp_path / "personas")
    assert "CHIMERA_MEMORY_PERSONA_DB_ROOT is set but TRANSCRIPT_DB_PATH overrides db_path" in payload["warnings"]


def test_memory_whereami_derives_persona_defaults_from_id_and_root(tmp_path: Path, monkeypatch) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    persona_root = tmp_path / "personas" / "developer" / "asa"
    shared_root = tmp_path / "shared"
    persona_root.mkdir(parents=True)
    shared_root.mkdir()
    monkeypatch.setenv("CHIMERA_PERSONA_ID", "developer/asa")
    monkeypatch.setenv("CHIMERA_PERSONA_ROOT", str(persona_root))

    payload = server.resolve_memory_whereami()

    expected_db = Path.home() / ".chimera-memory" / "personas" / "developer" / "asa" / "transcript.db"
    assert payload["resolved"]["db_path"] == str(expected_db)
    assert payload["provenance"]["db_path"] == {"source": "derived", "from": "CHIMERA_PERSONA_ID"}
    assert payload["resolved"]["transcript_persona"] == "asa"
    assert payload["provenance"]["transcript_persona"] == {"source": "derived", "from": "CHIMERA_PERSONA_ID"}
    assert payload["resolved"]["persona_name"] == "asa"
    assert payload["provenance"]["persona_name"] == {"source": "derived", "from": "CHIMERA_PERSONA_ID"}
    assert payload["resolved"]["personas_dir"] == str(tmp_path / "personas")
    assert payload["provenance"]["personas_dir"] == {"source": "derived", "from": "CHIMERA_PERSONA_ROOT"}
    assert payload["resolved"]["shared_root"] == str(shared_root)
    assert payload["provenance"]["shared_root"] == {"source": "derived", "from": "CHIMERA_PERSONAS_DIR"}
