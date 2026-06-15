"""Regression tests for persona-aware transcript DB resolution (split-brain fix).

The MCP query tools, the maintenance lock, and the 5 startup workers must all
resolve the SAME transcript DB path. Before this fix the workers ignored persona
identity and wrote indexing into the shared default DB while persona queries read
the per-persona DB (hc-01 / smr-01).
"""

from __future__ import annotations

from pathlib import Path

from chimera_memory import server


_DB_ENV = (
    "TRANSCRIPT_DB_PATH",
    "CHIMERA_PERSONA_ID",
    "CHIMERA_PERSONA_NAME",
    "TRANSCRIPT_PERSONA",
    "CHIMERA_MEMORY_PERSONA_DB_ROOT",
)


def _clear(monkeypatch):
    for name in _DB_ENV:
        monkeypatch.delenv(name, raising=False)


def test_explicit_db_path_wins(monkeypatch, tmp_path):
    _clear(monkeypatch)
    explicit = tmp_path / "custom.db"
    monkeypatch.setenv("TRANSCRIPT_DB_PATH", str(explicit))
    monkeypatch.setenv("CHIMERA_PERSONA_ID", "developer/asa")
    assert server._resolve_transcript_db_path() == str(explicit)


def test_blank_db_path_falls_through_to_default(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TRANSCRIPT_DB_PATH", "   ")
    # A blank env var must NOT resolve to "" (the old .get(key, default) bug).
    resolved = server._resolve_transcript_db_path()
    assert resolved
    assert resolved == str(server.get_default_db_path())


def test_persona_maps_to_per_persona_db(monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setenv("CHIMERA_MEMORY_PERSONA_DB_ROOT", str(tmp_path / "personas"))
    monkeypatch.setenv("CHIMERA_PERSONA_ID", "developer/asa")
    monkeypatch.setenv("CHIMERA_PERSONA_NAME", "asa")
    resolved = Path(server._resolve_transcript_db_path())
    assert resolved.name == "transcript.db"
    parts = resolved.parts
    assert "developer" in parts and "asa" in parts
    assert str(tmp_path / "personas") in str(resolved)


def test_no_persona_uses_shared_default(monkeypatch):
    _clear(monkeypatch)
    assert server._resolve_transcript_db_path() == str(server.get_default_db_path())


def test_workers_and_query_tools_agree(monkeypatch, tmp_path):
    """The whole point: every site resolves to the same path for a persona."""
    _clear(monkeypatch)
    monkeypatch.setenv("CHIMERA_MEMORY_PERSONA_DB_ROOT", str(tmp_path / "personas"))
    monkeypatch.setenv("CHIMERA_PERSONA_ID", "developer/asa")
    monkeypatch.setenv("CHIMERA_PERSONA_NAME", "asa")

    from chimera_memory.identity import load_identity_from_env

    identity = load_identity_from_env()
    # _get_db passes the in-scope identity; workers/lock call with no arg.
    with_identity = server._resolve_transcript_db_path(identity)
    without_identity = server._resolve_transcript_db_path()
    assert with_identity == without_identity
