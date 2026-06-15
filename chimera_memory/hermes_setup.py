"""Hermes Agent setup helpers for ChimeraMemory.

Parity with ``codex_setup`` but deliberately narrower and safer. Hermes's
``config.yaml`` is a large, comment-rich multi-section file, so this module never
mutates it (that is the same clobbering risk class as the Codex TOML installer).
Instead:

- ``template`` prints the paste-in Hermes ``mcp_servers`` block plus the exact
  standalone-indexer env/command (pure output, zero risk).
- ``doctor`` is read-only: it verifies the persona session store, runs a parse
  smoke, and confirms harness resolution.
- ``install`` writes per-persona launcher scripts under ``~/.chimera-memory`` that
  run ``chimera-memory serve`` with the right env. Dry-run by default.

Standalone Hermes is persona-scoped: a persona is required so CM only ever reads
``~/.hermes/profiles/<persona>/sessions`` and never across personas.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

HERMES_SETUP_SCHEMA_VERSION = "chimera-memory.hermes-setup.v1"
HERMES_SESSION_GLOB = "session_*.json"
_SAFE_PERSONA_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _clean_persona(persona: str) -> str:
    return _SAFE_PERSONA_RE.sub("-", str(persona or "").strip()).strip(".-")


def hermes_home() -> Path:
    """Resolve the Hermes install home from env, else the default Windows path."""
    for var in ("HERMES_HOME", "HERMES_INSTALL_DIR"):
        value = os.environ.get(var, "").strip()
        if value:
            return Path(value).expanduser()
    return Path.home() / "AppData" / "Local" / "hermes"


def hermes_profiles_root() -> Path:
    return Path.home() / ".hermes" / "profiles"


def hermes_sessions_dir(persona: str) -> Path:
    """Per-persona Hermes session dir: ~/.hermes/profiles/<persona>/sessions."""
    return hermes_profiles_root() / _clean_persona(persona) / "sessions"


def build_hermes_indexer_env(
    persona: str,
    *,
    jsonl_dir: str = "",
    persona_id: str = "",
    persona_name: str = "",
    db_path: str = "",
) -> dict[str, str]:
    """Env that makes CM index a Hermes persona's standalone sessions."""
    clean = _clean_persona(persona)
    env = {
        "CHIMERA_CLIENT": "hermes",
        "CHIMERA_PERSONA_NAME": persona_name.strip() or clean,
        "TRANSCRIPT_PERSONA": persona_name.strip() or clean,
        "TRANSCRIPT_JSONL_DIR": jsonl_dir.strip() or str(hermes_sessions_dir(clean)),
    }
    if persona_id.strip():
        env["CHIMERA_PERSONA_ID"] = persona_id.strip()
    if db_path.strip():
        env["TRANSCRIPT_DB_PATH"] = db_path.strip()
    return env


def build_hermes_mcp_config_block(
    persona: str,
    *,
    server_name: str = "chimera-memory",
    command: str = "chimera-memory",
) -> str:
    """YAML block for Hermes config.yaml so Hermes can query CM memory over MCP.

    Printed for the operator to paste; this module never edits config.yaml.
    """
    env = build_hermes_indexer_env(persona)
    env["CHIMERA_MEMORY_MCP_SURFACE"] = "persona_memory"
    lines = [
        "mcp_servers:",
        f"  {server_name}:",
        f"    command: {command}",
        "    args: [serve, --transport, stdio]",
        "    env:",
    ]
    for key in sorted(env):
        lines.append(f"      {key}: {env[key]!r}")
    return "\n".join(lines)


def _persona_session_files(persona: str) -> list[Path]:
    sessions = hermes_sessions_dir(persona)
    try:
        if not sessions.exists():
            return []
        return sorted(sessions.glob(HERMES_SESSION_GLOB))
    except OSError:
        return []


def render_hermes_template(persona: str, *, command: str = "chimera-memory") -> dict[str, Any]:
    """Build a safe, paste-ready Hermes setup template (no writes)."""
    clean = _clean_persona(persona)
    env = build_hermes_indexer_env(clean)
    return {
        "ok": True,
        "schema_version": HERMES_SETUP_SCHEMA_VERSION,
        "persona": clean,
        "sessions_dir_name": ".hermes/profiles/<persona>/sessions",
        "indexer_env": env,
        "backfill_command": f"{command} backfill --client hermes",
        "serve_command": f"{command} serve",
        "mcp_config_block": build_hermes_mcp_config_block(clean, command=command),
    }


def inspect_hermes_setup(persona: str) -> dict[str, Any]:
    """Read-only Hermes doctor: session store, parse smoke, harness resolution."""
    clean = _clean_persona(persona)
    checks: list[dict[str, str]] = []

    def _check(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    if not clean:
        _check("persona", "error", "A persona is required for standalone Hermes indexing.")
        return {
            "ok": False,
            "schema_version": HERMES_SETUP_SCHEMA_VERSION,
            "persona": "",
            "checks": checks,
        }

    home = hermes_home()
    _check(
        "hermes_home",
        "ok" if home.exists() else "warn",
        "Hermes home present." if home.exists() else "Hermes home not found (set HERMES_HOME).",
    )

    files = _persona_session_files(clean)
    if files:
        _check("sessions", "ok", f"{len(files)} Hermes session file(s) for this persona.")
    else:
        _check(
            "sessions",
            "warn",
            "No session_*.json found for this persona under ~/.hermes/profiles/<persona>/sessions.",
        )

    # Parse smoke on the newest session (counts only, no content surfaced).
    parsed = 0
    if files:
        try:
            from .parser import get_parser

            entries = list(get_parser("hermes").parse_file(files[-1]))
            parsed = len(entries)
            _check(
                "parse_smoke",
                "ok" if parsed > 0 else "warn",
                f"Newest session parsed to {parsed} entr{'y' if parsed == 1 else 'ies'}.",
            )
        except Exception:
            _check("parse_smoke", "error", "Hermes parser failed on the newest session file.")

    # Harness resolution under a simulated Hermes env.
    try:
        from . import harness

        prev = {k: os.environ.get(k) for k in ("CHIMERA_CLIENT", "CHIMERA_PERSONA_NAME")}
        os.environ["CHIMERA_CLIENT"] = "hermes"
        os.environ["CHIMERA_PERSONA_NAME"] = clean
        try:
            profile = harness.detect_harness()
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        ok = profile.name == "hermes" and profile.client == "hermes"
        _check(
            "harness_resolution",
            "ok" if ok else "error",
            f"detect_harness -> name={profile.name} client={profile.client}.",
        )
    except Exception:
        _check("harness_resolution", "error", "Harness detection raised.")

    overall_ok = all(c["status"] != "error" for c in checks)
    return {
        "ok": overall_ok,
        "schema_version": HERMES_SETUP_SCHEMA_VERSION,
        "persona": clean,
        "session_file_count": len(files),
        "parsed_entries_smoke": parsed,
        "checks": checks,
    }


def _launcher_dir() -> Path:
    return Path.home() / ".chimera-memory" / "hermes"


def install_hermes_indexer(
    persona: str,
    *,
    write: bool = False,
    jsonl_dir: str = "",
    persona_id: str = "",
    command: str = "chimera-memory",
) -> dict[str, Any]:
    """Plan/write per-persona launcher scripts that index Hermes with the right env.

    Never touches Hermes config.yaml. Dry-run by default; pass ``write=True`` to
    create the scripts under ~/.chimera-memory/hermes/.
    """
    clean = _clean_persona(persona)
    if not clean:
        return {"ok": False, "error": "persona required", "schema_version": HERMES_SETUP_SCHEMA_VERSION}

    env = build_hermes_indexer_env(clean, jsonl_dir=jsonl_dir, persona_id=persona_id)
    out_dir = _launcher_dir()
    ps1 = out_dir / f"index-{clean}.ps1"
    sh = out_dir / f"index-{clean}.sh"

    ps_lines = ["# ChimeraMemory Hermes indexer launcher (generated)"]
    ps_lines += [f"$env:{k} = {v!r}" for k, v in sorted(env.items())]
    ps_lines.append(f"& {command} serve")
    ps_text = "\n".join(ps_lines) + "\n"

    sh_lines = ["#!/usr/bin/env bash", "# ChimeraMemory Hermes indexer launcher (generated)", "set -euo pipefail"]
    sh_lines += [f"export {k}={_sh_quote(v)}" for k, v in sorted(env.items())]
    sh_lines.append(f'exec {command} serve')
    sh_text = "\n".join(sh_lines) + "\n"

    plan = {
        "ok": True,
        "schema_version": HERMES_SETUP_SCHEMA_VERSION,
        "persona": clean,
        "write": bool(write),
        "indexer_env": env,
        "launchers": {"powershell_name": ps1.name, "bash_name": sh.name},
        "written": False,
    }
    if not write:
        return plan

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        ps1.write_text(ps_text, encoding="utf-8")
        sh.write_text(sh_text, encoding="utf-8")
        plan["written"] = True
    except OSError as exc:
        plan["ok"] = False
        plan["error"] = f"failed to write launchers: {type(exc).__name__}"
    return plan


def _sh_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"
