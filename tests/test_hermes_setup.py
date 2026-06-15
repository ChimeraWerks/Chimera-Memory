"""Tests for the Hermes setup helpers and CLI wiring."""

from __future__ import annotations

import sys

import pytest

from chimera_memory import hermes_setup


def test_indexer_env_has_required_keys():
    env = hermes_setup.build_hermes_indexer_env("asa")
    assert env["CHIMERA_CLIENT"] == "hermes"
    assert env["CHIMERA_PERSONA_NAME"] == "asa"
    assert env["TRANSCRIPT_PERSONA"] == "asa"
    assert env["TRANSCRIPT_JSONL_DIR"].replace("\\", "/").endswith(".hermes/profiles/asa/sessions")


def test_persona_is_sanitized_no_traversal():
    # A path-traversal persona must not escape the profiles root.
    d = str(hermes_setup.hermes_sessions_dir("../../etc")).replace("\\", "/")
    assert ".." not in d
    assert "/.hermes/profiles/" in d


def test_mcp_config_block_is_persona_memory_surface():
    block = hermes_setup.build_hermes_mcp_config_block("asa")
    assert "mcp_servers:" in block
    assert "chimera-memory:" in block
    assert "'hermes'" in block  # CHIMERA_CLIENT
    assert "persona_memory" in block  # least-privilege surface for a query client


def test_template_shape():
    result = hermes_setup.render_hermes_template("asa")
    assert result["ok"] is True
    assert result["persona"] == "asa"
    assert "backfill" in result["backfill_command"]
    assert "CHIMERA_CLIENT" in result["indexer_env"]


def test_install_dry_run_then_write(tmp_path, monkeypatch):
    monkeypatch.setattr(hermes_setup, "_launcher_dir", lambda: tmp_path / "hermes")

    dry = hermes_setup.install_hermes_indexer("asa", write=False)
    assert dry["ok"] is True and dry["written"] is False
    assert not (tmp_path / "hermes").exists()

    wrote = hermes_setup.install_hermes_indexer("asa", write=True)
    assert wrote["ok"] is True and wrote["written"] is True
    ps1 = tmp_path / "hermes" / "index-asa.ps1"
    sh = tmp_path / "hermes" / "index-asa.sh"
    assert ps1.exists() and sh.exists()
    ps_text = ps1.read_text(encoding="utf-8")
    assert "CHIMERA_CLIENT" in ps_text and "hermes" in ps_text
    # The bash launcher single-quotes env values.
    assert "export CHIMERA_CLIENT='hermes'" in sh.read_text(encoding="utf-8")


def test_install_requires_persona():
    result = hermes_setup.install_hermes_indexer("", write=False)
    assert result["ok"] is False


def test_cli_hermes_install_does_not_collide_with_command_dest(monkeypatch):
    """Regression: a --command flag must not overwrite the top-level subparser dest."""
    import chimera_memory.cli as cli

    captured = {}

    def spy(args):
        captured["command"] = args.command
        captured["hermes_command"] = args.hermes_command
        captured["cm_command"] = args.cm_command

    monkeypatch.setattr(cli, "_run_hermes", spy)
    monkeypatch.setattr(sys, "argv", ["chimera-memory", "hermes", "install", "--persona", "asa"])
    cli.main()
    assert captured["command"] == "hermes"
    assert captured["hermes_command"] == "install"
    assert captured["cm_command"] == "chimera-memory"
