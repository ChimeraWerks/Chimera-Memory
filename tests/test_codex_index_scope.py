"""Codex no-persona project-root indexing scope (T1.5 / hc-08)."""

from __future__ import annotations

from pathlib import Path

from chimera_memory.db import TranscriptDB
from chimera_memory.indexer import Indexer


_SCOPE_ENV = (
    "CHIMERA_CLIENT",
    "CHIMERA_PERSONA_ROOT",
    "CHIMERA_MEMORY_PROJECT_ROOT",
    "CHIMERA_MEMORY_PROJECT_ROOTS",
    "TRANSCRIPT_JSONL_DIR",
)


def _clear(monkeypatch):
    for name in _SCOPE_ENV:
        monkeypatch.delenv(name, raising=False)


def _codex_indexer(tmp_path, monkeypatch, *, cwd_value):
    db = TranscriptDB(tmp_path / "t.db")
    indexer = Indexer(db, tmp_path / "sessions", parser_format="codex")
    monkeypatch.setattr(indexer.parser, "extract_session_metadata", lambda path: {"cwd": cwd_value})
    return indexer


def test_collect_project_roots_reads_both_env(monkeypatch, tmp_path):
    _clear(monkeypatch)
    a = tmp_path / "proj-a"
    b = tmp_path / "proj-b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(a))
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOTS", str(b))
    roots = Indexer._collect_project_roots()
    assert len(roots) == 2


def test_codex_no_roots_indexes_all(monkeypatch, tmp_path):
    _clear(monkeypatch)
    indexer = _codex_indexer(tmp_path, monkeypatch, cwd_value="C:/anywhere/else")
    # No persona root and no project root -> historical index-all behavior.
    assert indexer._should_index_file(tmp_path / "sessions" / "rollout.jsonl") is True


def test_codex_project_root_scopes_in_and_out(monkeypatch, tmp_path):
    _clear(monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(proj))

    inside = _codex_indexer(tmp_path, monkeypatch, cwd_value=str(proj / "sub"))
    assert inside._should_index_file(tmp_path / "sessions" / "rollout.jsonl") is True

    outside = _codex_indexer(tmp_path, monkeypatch, cwd_value=str(tmp_path / "other"))
    assert outside._should_index_file(tmp_path / "sessions" / "rollout.jsonl") is False


def test_cwd_under_any_root_helper(monkeypatch, tmp_path):
    _clear(monkeypatch)
    indexer = _codex_indexer(tmp_path, monkeypatch, cwd_value="x")
    roots = ["c:/github/proj"]
    assert indexer._cwd_under_any_root("c:/github/proj", roots) is True
    assert indexer._cwd_under_any_root("c:/github/proj/sub", roots) is True
    assert indexer._cwd_under_any_root("c:/github/projector", roots) is False
    assert indexer._cwd_under_any_root(None, roots) is False
