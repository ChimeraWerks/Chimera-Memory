"""Harness identification for ChimeraMemory.

Resolves which agent harness (Claude Code, Codex, Hermes) is driving the current
process so transcript indexing finds the right session directory and uses the
right parser without every launch having to set ``CHIMERA_CLIENT`` and
``TRANSCRIPT_JSONL_DIR`` by hand.

Design contract (why this module exists):
- Explicit env overrides always win. ``CHIMERA_CLIENT`` and ``TRANSCRIPT_JSONL_DIR``
  short-circuit detection so existing codex_setup installs and any env-driven
  launch keep their exact behavior.
- Detection only fills *unset* fields; the default branch is byte-for-byte the
  historical Claude-Code behavior, so nothing regresses.
- Prefer process-injected "this harness is currently running" signals
  (``CLAUDECODE`` / ``CODEX_SANDBOX``) over install-location signals
  (``HERMES_HOME`` / ``CODEX_HOME``). Scar: on a real machine several harness env
  vars coexist at once (Claude + Hermes-installed + a Codex plugin) because the
  install vars persist in every shell; keying off them would mislabel every
  process. Source: observed live env on the maintainer's box (CLAUDECODE=1 with
  HERMES_HOME set simultaneously).

Near-stdlib by design: imports only the standard library so path/indexer/server
code can consult it without import cycles. ``detect_harness`` never raises and
never emits raw filesystem paths into user/MCP-facing strings (callers log at
debug only).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

CLAUDE_CODE = "claude-code"
CODEX = "codex"
HERMES = "hermes"
UNKNOWN = "unknown"

# Canonical parser/client keys understood by parser.get_parser().
_CLIENT_ALIASES = {
    "claude": CLAUDE_CODE,
    "claude_code": CLAUDE_CODE,
    "claude-code": CLAUDE_CODE,
    "claudecode": CLAUDE_CODE,
    "codex": CODEX,
    "openai-codex": CODEX,
    "openai_codex": CODEX,
    "hermes": HERMES,
    "hermes-agent": HERMES,
    "hermes_agent": HERMES,
}

# Codex rollout sessions live under ~/.codex/sessions, nested by YYYY/MM/DD.
_CODEX_SESSIONS_SUBPATH = (".codex", "sessions")
# Claude Code session logs live under ~/.claude/projects/<munged-cwd>.
_CLAUDE_PROJECTS_SUBPATH = (".claude", "projects")

# Bounded scan budget so signature/content detection stays cheap on huge trees.
_SNIFF_MAX_FILES = 12

# Optional hint set from an MCP clientInfo.name handshake (additive, may be unset).
_mcp_client_hint: str | None = None


@dataclass(frozen=True)
class HarnessProfile:
    """Resolved harness identity used to drive indexing defaults."""

    name: str  # claude-code | codex | hermes | unknown
    client: str | None  # parser key for parser.get_parser(); None lets caller default
    jsonl_dir: Path | None
    recursive: bool
    source: str  # env | jsonl_dir | mcp_client | signature | content | default
    confidence: str  # high | medium | low


def normalize_client(value: object) -> str | None:
    """Map a free-form client/harness string to a canonical key, or None."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    return _CLIENT_ALIASES.get(text, text or None)


def set_mcp_client_hint(name: object) -> None:
    """Record an MCP clientInfo.name so detection can use it when env is ambiguous.

    Safe no-op for unknown names. Only used as a weak signal below explicit env.
    """
    global _mcp_client_hint
    text = str(name or "").strip().lower()
    if not text:
        return
    if "claude" in text:
        _mcp_client_hint = CLAUDE_CODE
    elif "codex" in text:
        _mcp_client_hint = CODEX
    elif "hermes" in text:
        _mcp_client_hint = HERMES


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def claude_projects_dir_for_cwd(cwd: Path | None = None) -> Path:
    """Replicate Claude Code's project-dir naming: non-alnum chars become '-'.

    Mirrors the legacy server.get_default_jsonl_dir behavior exactly, including
    the case-insensitive fallback scan used on Windows.
    """
    home = Path.home()
    try:
        base = (cwd or Path.cwd()).resolve()
    except OSError:
        base = cwd or Path.cwd()
    project_key = re.sub(r"[^a-zA-Z0-9]", "-", str(base))
    projects_dir = home.joinpath(*_CLAUDE_PROJECTS_SUBPATH)
    exact = projects_dir / project_key
    if exact.exists():
        return exact
    try:
        if projects_dir.exists():
            for child in projects_dir.iterdir():
                if child.is_dir() and child.name.lower() == project_key.lower():
                    return child
    except OSError:
        pass
    return exact


def codex_sessions_dir() -> Path:
    return Path.home().joinpath(*_CODEX_SESSIONS_SUBPATH)


def _client_from_dir(dir_text: str) -> str | None:
    """Infer the harness from a configured JSONL directory path shape."""
    normalized = str(dir_text or "").strip().replace("\\", "/").lower().rstrip("/")
    if not normalized:
        return None
    if "/.codex/sessions" in normalized or normalized.endswith("/.codex/sessions"):
        return CODEX
    if "/.claude/projects" in normalized:
        return CLAUDE_CODE
    return None


def sniff_jsonl_format(path: Path) -> str | None:
    """Return 'codex' | 'claude-code' from the first decodable JSON line, or None.

    Codex rollout lines carry ``type == 'session_meta'`` or a top-level
    ``payload`` object; Claude Code lines carry ``sessionId`` with a chat ``type``.
    Bounded to the first handful of lines so it stays cheap on tail-read files.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            checked = 0
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                checked += 1
                if checked > 8:
                    break
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(obj, dict):
                    continue
                obj_type = str(obj.get("type") or "").strip().lower()
                if obj_type in ("session_meta", "event_msg", "response_item") or isinstance(
                    obj.get("payload"), dict
                ):
                    return CODEX
                if obj.get("sessionId") is not None or obj_type in (
                    "user",
                    "assistant",
                    "system",
                    "queue-operation",
                    "file-history-snapshot",
                ):
                    return CLAUDE_CODE
    except OSError:
        return None
    return None


def _newest_jsonl(root: Path, *, recursive: bool) -> Path | None:
    try:
        if not root.exists():
            return None
        globber = root.rglob if recursive else root.glob
        newest: Path | None = None
        newest_mtime = -1.0
        scanned = 0
        for candidate in globber("*.jsonl"):
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            scanned += 1
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest = candidate
            if scanned >= 500:  # bound work on very large trees
                break
        return newest
    except OSError:
        return None


def _sniff_dir(root: Path, *, recursive: bool) -> str | None:
    newest = _newest_jsonl(root, recursive=recursive)
    if newest is None:
        return None
    return sniff_jsonl_format(newest)


def _profile_for_client(
    client: str,
    dir_override: str,
    *,
    source: str,
    confidence: str,
    cwd: Path | None,
) -> HarnessProfile:
    name = normalize_client(client) or CLAUDE_CODE
    recursive = name == CODEX
    # Hermes writes Claude-format JSONL under ~/.claude/projects (it runs inside
    # Claude Code today), so its parser key and default dir mirror Claude until a
    # native Hermes line schema exists. Scar: README oversells a Hermes parser
    # that does not exist; mapping hermes->claude here keeps indexing correct.
    parser_client = CLAUDE_CODE if name == HERMES else name
    if dir_override:
        jsonl_dir: Path | None = Path(dir_override).expanduser()
    elif name == CODEX:
        jsonl_dir = codex_sessions_dir()
    else:
        jsonl_dir = claude_projects_dir_for_cwd(cwd)
    return HarnessProfile(
        name=name,
        client=parser_client,
        jsonl_dir=jsonl_dir,
        recursive=recursive,
        source=source,
        confidence=confidence,
    )


def _running_harness_from_env() -> str | None:
    """Strong 'this harness is currently driving the process' env signals.

    Uses only vars the active harness injects into spawned children, not
    install-location vars that persist in every shell (HERMES_HOME, CODEX_HOME).
    """
    if (
        _env("CODEX_SANDBOX")
        or _env("CODEX_SANDBOX_NETWORK_DISABLED")
        or _truthy(_env("CODEX_MANAGED_BY_NPM"))
    ):
        return CODEX
    if _truthy(_env("CLAUDECODE")) or _env("CLAUDE_CODE_ENTRYPOINT"):
        return CLAUDE_CODE
    return None


def _detect_from_signatures(cwd: Path | None) -> HarnessProfile | None:
    """Best-effort on-disk signature detection when env is ambiguous.

    Conservative: only returns Codex when a Codex sessions tree exists and the
    cwd-specific Claude project dir does not, so the historical Claude default is
    preserved whenever a Claude project dir is present.
    """
    claude_dir = claude_projects_dir_for_cwd(cwd)
    codex_dir = codex_sessions_dir()
    claude_exists = False
    try:
        claude_exists = claude_dir.exists()
    except OSError:
        claude_exists = False
    if claude_exists:
        return None
    codex_newest = _newest_jsonl(codex_dir, recursive=True)
    if codex_newest is not None and sniff_jsonl_format(codex_newest) == CODEX:
        return HarnessProfile(
            name=CODEX,
            client=CODEX,
            jsonl_dir=codex_dir,
            recursive=True,
            source="signature",
            confidence="medium",
        )
    return None


def detect_harness(*, cwd: Path | None = None) -> HarnessProfile:
    """Resolve the active harness. Never raises.

    Precedence (first match wins):
      1. CHIMERA_CLIENT explicit override (authoritative).
      2. TRANSCRIPT_JSONL_DIR explicit override (infer client from path/content).
      3. Process-injected running-harness env signal (CLAUDECODE / CODEX_SANDBOX).
      4. MCP clientInfo hint, if captured.
      5. On-disk session-dir signature + content sniff (conservative).
      6. Default: historical Claude-Code behavior.
    """
    explicit_client = normalize_client(_env("CHIMERA_CLIENT"))
    explicit_dir = _env("TRANSCRIPT_JSONL_DIR")

    if explicit_client:
        return _profile_for_client(
            explicit_client, explicit_dir, source="env", confidence="high", cwd=cwd
        )

    if explicit_dir:
        inferred = _client_from_dir(explicit_dir)
        if inferred:
            return _profile_for_client(
                inferred, explicit_dir, source="jsonl_dir", confidence="high", cwd=cwd
            )
        sniffed = _sniff_dir(Path(explicit_dir).expanduser(), recursive=True)
        return _profile_for_client(
            sniffed or CLAUDE_CODE,
            explicit_dir,
            source="content" if sniffed else "default",
            confidence="medium" if sniffed else "low",
            cwd=cwd,
        )

    running = _running_harness_from_env()
    if running:
        return _profile_for_client(running, "", source="env", confidence="high", cwd=cwd)

    if _mcp_client_hint:
        return _profile_for_client(
            _mcp_client_hint, "", source="mcp_client", confidence="medium", cwd=cwd
        )

    signature = _detect_from_signatures(cwd)
    if signature is not None:
        return signature

    return _profile_for_client(
        CLAUDE_CODE, "", source="default", confidence="low", cwd=cwd
    )


def detected_client(*, cwd: Path | None = None) -> str | None:
    """Convenience: the parser client key for the detected harness, or None."""
    profile = detect_harness(cwd=cwd)
    return profile.client


def detected_jsonl_dir(*, cwd: Path | None = None) -> Path | None:
    """Convenience: the JSONL session directory for the detected harness."""
    return detect_harness(cwd=cwd).jsonl_dir
