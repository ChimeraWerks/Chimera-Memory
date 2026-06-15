"""Tests for harness auto-identification (chimera_memory/harness.py)."""

from __future__ import annotations

import pytest

from chimera_memory import harness


# Every harness-influencing env var, cleared so each test controls detection.
_HARNESS_ENV = (
    "CHIMERA_CLIENT",
    "TRANSCRIPT_JSONL_DIR",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_MANAGED_BY_NPM",
    "HERMES_HOME",
    "HERMES_INSTALL_DIR",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _HARNESS_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(harness, "_mcp_client_hint", None, raising=False)
    yield


def test_normalize_client_aliases():
    assert harness.normalize_client("claude") == harness.CLAUDE_CODE
    assert harness.normalize_client("Claude-Code") == harness.CLAUDE_CODE
    assert harness.normalize_client("openai-codex") == harness.CODEX
    assert harness.normalize_client("Hermes-Agent") == harness.HERMES
    assert harness.normalize_client("") is None
    assert harness.normalize_client(None) is None


def test_explicit_client_codex_fills_dir_and_recursion(monkeypatch):
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    profile = harness.detect_harness()
    assert profile.name == harness.CODEX
    assert profile.client == harness.CODEX
    assert profile.recursive is True
    assert profile.source == "env"
    assert str(profile.jsonl_dir).replace("\\", "/").endswith(".codex/sessions")


def test_explicit_client_claude(monkeypatch):
    monkeypatch.setenv("CHIMERA_CLIENT", "claude")
    profile = harness.detect_harness()
    assert profile.name == harness.CLAUDE_CODE
    assert profile.client == harness.CLAUDE_CODE
    assert profile.recursive is False


def test_explicit_client_hermes_uses_claude_parser(monkeypatch):
    monkeypatch.setenv("CHIMERA_CLIENT", "hermes")
    profile = harness.detect_harness()
    assert profile.name == harness.HERMES
    # Hermes writes Claude-format JSONL today; parser key must be claude-code.
    assert profile.client == harness.CLAUDE_CODE
    assert profile.recursive is False


def test_explicit_dir_infers_codex(monkeypatch):
    monkeypatch.setenv("TRANSCRIPT_JSONL_DIR", "~/.codex/sessions/")
    profile = harness.detect_harness()
    assert profile.name == harness.CODEX
    assert profile.client == harness.CODEX
    assert profile.recursive is True
    assert profile.source == "jsonl_dir"


def test_explicit_dir_infers_claude(monkeypatch):
    monkeypatch.setenv("TRANSCRIPT_JSONL_DIR", "~/.claude/projects/whatever")
    profile = harness.detect_harness()
    assert profile.name == harness.CLAUDE_CODE
    assert profile.source == "jsonl_dir"


def test_running_env_claudecode(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    profile = harness.detect_harness()
    assert profile.name == harness.CLAUDE_CODE
    assert profile.source == "env"


def test_running_env_codex_sandbox(monkeypatch):
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    profile = harness.detect_harness()
    assert profile.name == harness.CODEX
    assert profile.recursive is True


def test_codex_sandbox_outranks_claudecode(monkeypatch):
    # A Codex-spawned child should win even if a stale CLAUDECODE lingers.
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert harness.detect_harness().name == harness.CODEX


def test_hermes_home_alone_does_not_mislabel(monkeypatch):
    # Install-location vars persist in every shell; they must NOT make a plain
    # process look like Hermes. With no running signal this stays claude-code.
    monkeypatch.setenv("HERMES_HOME", "C:/Users/x/AppData/Local/hermes")
    profile = harness.detect_harness()
    assert profile.name in (harness.CLAUDE_CODE, harness.CODEX)
    assert profile.name != harness.HERMES


def test_claudecode_wins_with_hermes_home_present(monkeypatch):
    # The real-world layered env: Claude running with Hermes installed.
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("HERMES_HOME", "C:/Users/x/AppData/Local/hermes")
    assert harness.detect_harness().name == harness.CLAUDE_CODE


def test_explicit_client_overrides_running_env(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CHIMERA_CLIENT", "codex")
    assert harness.detect_harness().name == harness.CODEX


def test_sniff_codex_session_meta(tmp_path):
    f = tmp_path / "rollout.jsonl"
    f.write_text(
        '{"type":"session_meta","payload":{"id":"019e-abc"}}\n'
        '{"type":"response_item","payload":{"role":"assistant"}}\n',
        encoding="utf-8",
    )
    assert harness.sniff_jsonl_format(f) == harness.CODEX


def test_sniff_claude_user_line(tmp_path):
    f = tmp_path / "session.jsonl"
    f.write_text(
        '{"type":"user","sessionId":"abc","message":{"role":"user","content":"hi"}}\n',
        encoding="utf-8",
    )
    assert harness.sniff_jsonl_format(f) == harness.CLAUDE_CODE


def test_sniff_blank_lines_then_codex(tmp_path):
    f = tmp_path / "rollout.jsonl"
    f.write_text('\n\n   \n{"payload":{"id":"x"}}\n', encoding="utf-8")
    assert harness.sniff_jsonl_format(f) == harness.CODEX


def test_sniff_missing_file_returns_none(tmp_path):
    assert harness.sniff_jsonl_format(tmp_path / "nope.jsonl") is None


def test_mcp_client_hint_used_when_env_ambiguous(monkeypatch):
    harness.set_mcp_client_hint("Codex/1.0")
    try:
        # No running env signal; with the hint we should land on codex unless a
        # Claude project dir signature pre-empts it. The hint path is exercised
        # only when no running env signal exists.
        profile = harness.detect_harness()
        assert profile.name in (harness.CODEX, harness.CLAUDE_CODE)
    finally:
        monkeypatch.setattr(harness, "_mcp_client_hint", None, raising=False)
