"""Codex setup diagnostics for Chimera Memory."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import persona_transcript_db_path


CODEX_MCP_SERVER_NAMES = ("chimera-memory", "chimera_memory")
IDENTITY_ENV = (
    "CHIMERA_PERSONA_ID",
    "CHIMERA_PERSONA_NAME",
    "CHIMERA_PERSONA_ROOT",
    "CHIMERA_PERSONAS_DIR",
    "CHIMERA_SHARED_ROOT",
)


def default_codex_mcp_config_path() -> Path:
    return Path.home() / ".codex" / "mcp_servers.json"


def build_codex_mcp_config(
    *,
    persona: str,
    jsonl_dir: str = "~/.codex/sessions/",
    command: str = "chimera-memory",
    server_name: str = "chimera-memory",
    persona_id: str = "",
    persona_name: str = "",
    persona_root: str = "",
    personas_dir: str = "",
    shared_root: str = "",
) -> dict[str, Any]:
    """Build a safe Codex MCP config template.

    The template only contains paths and non-secret identity fields. It never
    reads the user's current config and never emits raw credentials.
    """
    persona = persona.strip()
    if not persona:
        raise ValueError("persona is required")
    command = command.strip()
    if not command:
        raise ValueError("command is required")
    server_name = server_name.strip()
    if not server_name:
        raise ValueError("server_name is required")

    env: dict[str, str] = {
        "TRANSCRIPT_JSONL_DIR": jsonl_dir.strip() or "~/.codex/sessions/",
        "TRANSCRIPT_PERSONA": persona,
        "CHIMERA_CLIENT": "codex",
    }
    optional_env = {
        "CHIMERA_PERSONA_ID": persona_id,
        "CHIMERA_PERSONA_NAME": persona_name,
        "CHIMERA_PERSONA_ROOT": persona_root,
        "CHIMERA_PERSONAS_DIR": personas_dir,
        "CHIMERA_SHARED_ROOT": shared_root,
    }
    for key, value in optional_env.items():
        cleaned = value.strip()
        if cleaned:
            env[key] = cleaned

    return {
        "mcpServers": {
            server_name: {
                "command": command,
                "args": ["serve"],
                "env": env,
            }
        }
    }


def install_codex_mcp_config(
    *,
    config_path: str | Path | None = None,
    persona: str = "",
    persona_id: str = "",
    persona_root: str = "",
    jsonl_dir: str = "~/.codex/sessions/",
    command: str = "chimera-memory",
    server_name: str = "chimera-memory",
    import_history: bool = True,
    mcp_surface: str = "persona",
    provider: str = "",
    reuse_provider_auth: bool = False,
    oauth_store: str = "",
    enable_provider_worker: bool = False,
    hermes_home: str | Path | None = None,
    claude_credentials_path: str | Path | None = None,
    codex_auth_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Write or update Codex's MCP config for Chimera Memory.

    The installer preserves unrelated MCP servers, writes a timestamped backup
    before modifying an existing config, and reports env keys without values.
    """
    path = Path(config_path).expanduser() if config_path is not None else default_codex_mcp_config_path()
    persona = persona.strip()
    persona_id = persona_id.strip()
    persona_name = persona or _persona_name_from_id(persona_id)
    if not persona_name:
        raise ValueError("persona or persona_id is required")

    command = command.strip()
    if not command:
        raise ValueError("command is required")
    server_name = server_name.strip()
    if not server_name:
        raise ValueError("server_name is required")

    data, existed = _read_codex_config_for_install(path)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers

    configured_name = _configured_server_name(servers) or server_name
    persona_root = persona_root.strip() or _infer_persona_root(persona_id)
    selected_provider = _install_provider_id(provider)
    if reuse_provider_auth and not selected_provider:
        raise ValueError("provider is required when reuse_provider_auth is enabled")
    resolved_oauth_store = oauth_store.strip() or "~/.chimera-memory/auth.json"
    env = _build_codex_install_env(
        persona=persona_name,
        persona_id=persona_id,
        persona_root=persona_root,
        jsonl_dir=jsonl_dir,
        import_history=import_history,
        mcp_surface=mcp_surface,
        provider=selected_provider,
        oauth_store=resolved_oauth_store,
        enable_provider_worker=enable_provider_worker,
    )
    provider_auth = _maybe_import_provider_auth(
        provider_id=selected_provider,
        reuse_provider_auth=reuse_provider_auth,
        oauth_store=resolved_oauth_store,
        hermes_home=hermes_home,
        claude_credentials_path=claude_credentials_path,
        codex_auth_path=codex_auth_path,
    )
    servers[configured_name] = {
        "command": command,
        "args": ["serve"],
        "env": env,
    }

    backup_path = ""
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            backup_path = _backup_path_for(path)
            shutil.copy2(path, backup_path)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    _runtime_values, runtime_fields = _resolve_codex_runtime(env)
    return {
        "ok": True,
        "dry_run": dry_run,
        "config_path": str(path),
        "created": not existed,
        "backup_path": backup_path,
        "server_name": configured_name,
        "env_keys": sorted(env.keys()),
        "runtime_fields": runtime_fields,
        "import_history": import_history,
        "mcp_surface": mcp_surface.strip() or "persona",
        "provider": selected_provider or "dry_run",
        "provider_auth": provider_auth,
        "provider_worker_mode": "provider" if enable_provider_worker else "dry_run",
        "action": "create" if not existed else "update",
    }


def format_codex_install_report(result: Mapping[str, Any]) -> str:
    """Render a Codex install receipt without raw env values."""
    prefix = "Codex ChimeraMemory install"
    if result.get("dry_run"):
        prefix += " dry run"
    lines = [
        f"{prefix}: OK",
        f"Config: {result.get('config_path')}",
        f"Action: {result.get('action')}",
        f"Server: {result.get('server_name')}",
        f"Import history: {'enabled' if result.get('import_history') else 'disabled'}",
        f"MCP surface: {result.get('mcp_surface')}",
        f"Provider: {result.get('provider')}",
        f"Provider worker: {result.get('provider_worker_mode')}",
    ]
    provider_auth = result.get("provider_auth")
    if isinstance(provider_auth, Mapping) and provider_auth.get("status") != "not_requested":
        lines.append(f"Provider auth: {provider_auth.get('status')}")
    backup_path = str(result.get("backup_path") or "")
    if backup_path:
        lines.append(f"Backup: {backup_path}")
    env_keys = result.get("env_keys")
    if isinstance(env_keys, list) and env_keys:
        lines.append("Env keys: " + ", ".join(str(key) for key in env_keys))
    runtime_fields = result.get("runtime_fields")
    if isinstance(runtime_fields, list) and runtime_fields:
        lines.append("Runtime fields:")
        for field in runtime_fields:
            if not isinstance(field, Mapping):
                continue
            lines.append(f"  {field.get('name')}: {field.get('status')} ({field.get('source')})")
    lines.append("Next: restart Codex, then run `chimera-memory codex doctor`.")
    return "\n".join(lines)


def inspect_codex_mcp_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Inspect Codex MCP config without exposing raw environment values."""
    path = Path(config_path).expanduser() if config_path is not None else default_codex_mcp_config_path()
    checks: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "config_path": str(path),
        "config_exists": path.is_file(),
        "parse_ok": False,
        "server_name": "",
        "server_configured": False,
        "env_keys": [],
        "runtime_fields": [],
        "checks": checks,
    }

    if not path.is_file():
        _check(checks, "config_exists", "error", "Codex MCP config file does not exist.")
        return _finalize(result)
    _check(checks, "config_exists", "ok", "Codex MCP config file exists.")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _check(checks, "parse_json", "error", f"Codex MCP config is not valid JSON: {exc.msg}.")
        return _finalize(result)
    if not isinstance(data, Mapping):
        _check(checks, "parse_json", "error", "Codex MCP config root must be an object.")
        return _finalize(result)
    result["parse_ok"] = True
    _check(checks, "parse_json", "ok", "Codex MCP config parses as JSON.")

    servers = data.get("mcpServers") or data.get("mcp_servers")
    if not isinstance(servers, Mapping):
        _check(checks, "mcp_servers", "error", "Config must contain an mcpServers object.")
        return _finalize(result)

    server_name = _configured_server_name(servers)
    if not server_name:
        _check(checks, "chimera_server", "error", "No chimera-memory MCP server entry found.")
        return _finalize(result)
    result["server_name"] = server_name
    result["server_configured"] = True
    _check(checks, "chimera_server", "ok", f"Found MCP server entry: {server_name}.")

    server = servers.get(server_name)
    if not isinstance(server, Mapping):
        _check(checks, "server_shape", "error", "chimera-memory server entry must be an object.")
        return _finalize(result)

    command = str(server.get("command") or "").strip()
    if not command:
        _check(checks, "command", "error", "Server command is missing.")
    elif _command_resolves(command):
        _check(checks, "command", "ok", f"Server command resolves: {Path(command).name}.")
    else:
        _check(checks, "command", "warning", f"Server command does not resolve on PATH: {Path(command).name}.")

    args = server.get("args")
    if isinstance(args, list) and "serve" in [str(item) for item in args]:
        _check(checks, "args", "ok", "Server args include serve.")
    else:
        _check(checks, "args", "warning", "Server args should include serve.")

    env = server.get("env")
    if not isinstance(env, Mapping):
        _check(checks, "env", "error", "Server env must be an object.")
        return _finalize(result)
    result["env_keys"] = sorted(str(key) for key in env.keys())
    _check(checks, "env", "ok", "Server env is present. Values are intentionally not reported.")

    runtime_values, resolved_fields = _resolve_codex_runtime(env)
    result["runtime_fields"] = resolved_fields

    client = runtime_values.get("CHIMERA_CLIENT", "")
    if not client:
        _check(checks, "env:CHIMERA_CLIENT", "error", "CHIMERA_CLIENT is required for Codex setup.")
    elif client != "codex":
        _check(checks, "env:CHIMERA_CLIENT", "error", "CHIMERA_CLIENT must be codex for Codex transcripts.")
    else:
        source = _runtime_source(resolved_fields, "CHIMERA_CLIENT")
        _check(checks, "env:CHIMERA_CLIENT", "ok", f"CHIMERA_CLIENT selects the Codex parser ({source}).")

    jsonl_dir = runtime_values.get("TRANSCRIPT_JSONL_DIR", "")
    jsonl_source = _runtime_source(resolved_fields, "TRANSCRIPT_JSONL_DIR")
    if jsonl_dir:
        status = "ok" if _path_exists(jsonl_dir) else "warning"
        message = (
            f"TRANSCRIPT_JSONL_DIR exists. Source: {jsonl_source}."
            if status == "ok"
            else f"TRANSCRIPT_JSONL_DIR does not exist yet. Source: {jsonl_source}."
        )
        _check(checks, "env:TRANSCRIPT_JSONL_DIR", status, message)

    persona = runtime_values.get("TRANSCRIPT_PERSONA", "")
    persona_source = _runtime_source(resolved_fields, "TRANSCRIPT_PERSONA")
    if persona:
        _check(checks, "env:TRANSCRIPT_PERSONA", "ok", f"TRANSCRIPT_PERSONA resolves ({persona_source}).")
    else:
        _check(checks, "env:TRANSCRIPT_PERSONA", "warning", "TRANSCRIPT_PERSONA could not be resolved.")

    missing_identity = [
        field["name"]
        for field in resolved_fields
        if field["name"] in IDENTITY_ENV and field["status"] == "missing"
    ]
    if missing_identity:
        _check(
            checks,
            "identity_env",
            "warning",
            "Persona identity env is incomplete. Derivation could not fill every field.",
            {"missing_keys": missing_identity},
        )
    else:
        _check(checks, "identity_env", "ok", "Persona identity resolves via explicit and derived fields.")

    _check_latest_health_snapshot(checks, runtime_values.get("TRANSCRIPT_DB_PATH", ""))

    return _finalize(result)


def format_codex_doctor_report(result: Mapping[str, Any]) -> str:
    """Render a human-readable report without raw env values."""
    status = str(result.get("status") or "unknown").upper()
    lines = [
        f"Codex ChimeraMemory setup: {status}",
        f"Config: {result.get('config_path')}",
        f"Server: {result.get('server_name') or 'not configured'}",
    ]
    env_keys = result.get("env_keys")
    if isinstance(env_keys, list) and env_keys:
        lines.append("Env keys: " + ", ".join(str(key) for key in env_keys))
    runtime_fields = result.get("runtime_fields")
    if isinstance(runtime_fields, list) and runtime_fields:
        lines.append("Runtime fields:")
        for field in runtime_fields:
            if not isinstance(field, Mapping):
                continue
            status = str(field.get("status") or "?")
            source = str(field.get("source") or "?")
            lines.append(f"  {field.get('name')}: {status} ({source})")
    lines.append("")
    for check in result.get("checks", []):
        if not isinstance(check, Mapping):
            continue
        state = str(check.get("status") or "?").upper()
        lines.append(f"[{state}] {check.get('name')}: {check.get('message')}")
        details = check.get("details")
        if isinstance(details, Mapping) and details.get("missing_keys"):
            lines.append("  missing: " + ", ".join(str(key) for key in details["missing_keys"]))
    return "\n".join(lines)


def _read_codex_config_for_install(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {"mcpServers": {}}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Codex MCP config is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("Codex MCP config root must be an object")
    if "mcpServers" not in data and isinstance(data.get("mcp_servers"), Mapping):
        data["mcpServers"] = dict(data["mcp_servers"])
    return data, True


def _backup_path_for(path: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return str(path.with_name(f"{path.name}.bak-{stamp}"))


def _build_codex_install_env(
    *,
    persona: str,
    persona_id: str,
    persona_root: str,
    jsonl_dir: str,
    import_history: bool,
    mcp_surface: str,
    provider: str,
    oauth_store: str,
    enable_provider_worker: bool,
) -> dict[str, str]:
    env = {
        "TRANSCRIPT_JSONL_DIR": jsonl_dir.strip() or "~/.codex/sessions/",
        "CHIMERA_CLIENT": "codex",
        "CHIMERA_MEMORY_STATE_ROOT": "~/.chimera-memory",
        "CHIMERA_MEMORY_OAUTH_STORE": oauth_store,
        "CHIMERA_MEMORY_IMPORT_HISTORY": "true" if import_history else "false",
        "CHIMERA_MEMORY_MCP_SURFACE": (mcp_surface.strip() or "persona"),
    }
    if provider and provider != "dry_run":
        env["CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_AFFINITY"] = provider
    if enable_provider_worker:
        env["CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE"] = "provider"
    if persona_id:
        env["CHIMERA_PERSONA_ID"] = persona_id
        derived_name = _persona_name_from_id(persona_id)
        if persona and persona != derived_name:
            env["CHIMERA_PERSONA_NAME"] = persona
    else:
        env["TRANSCRIPT_PERSONA"] = persona
    cleaned_root = persona_root.strip()
    if cleaned_root:
        env["CHIMERA_PERSONA_ROOT"] = cleaned_root
    return env


def _install_provider_id(value: str) -> str:
    text = value.strip().lower().replace("-", "_")
    if not text:
        return ""
    aliases = {
        "claude": "anthropic",
        "claude_code": "anthropic",
        "chatgpt": "openai",
        "codex": "openai",
        "gemini": "google",
        "local": "ollama",
        "local_ai": "ollama",
        "openai_compatible": "openai_compatible",
        "lm_studio": "lmstudio",
        "dry": "dry_run",
        "dryrun": "dry_run",
    }
    provider_id = aliases.get(text, text)
    from .memory_enhancement_provider import PROVIDER_IDS

    if provider_id not in PROVIDER_IDS:
        raise ValueError("provider is unsupported")
    return provider_id


def _maybe_import_provider_auth(
    *,
    provider_id: str,
    reuse_provider_auth: bool,
    oauth_store: str,
    hermes_home: str | Path | None,
    claude_credentials_path: str | Path | None,
    codex_auth_path: str | Path | None,
) -> dict[str, Any]:
    if not reuse_provider_auth:
        return {"status": "not_requested"}
    if provider_id not in {"openai", "anthropic", "google"}:
        return {"status": "skipped", "reason": "provider_has_no_oauth_import"}
    try:
        from .memory_enhancement_oauth import MemoryEnhancementOAuthStore
        from .memory_enhancement_oauth_import import import_memory_enhancement_oauth_credential

        store = MemoryEnhancementOAuthStore(oauth_store)
        credential = import_memory_enhancement_oauth_credential(
            provider_id=provider_id,
            source="auto",
            store=store,
            hermes_home=hermes_home,
            claude_credentials_path=claude_credentials_path,
            codex_auth_path=codex_auth_path,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "provider": provider_id,
            "error_type": exc.__class__.__name__,
        }
    return {
        "status": "imported",
        "provider": provider_id,
        "credential": credential.to_safe_dict(),
    }


def _infer_persona_root(persona_id: str) -> str:
    parts = [part.lower() for part in persona_id.replace("\\", "/").split("/") if part.strip()]
    if not parts:
        return ""
    cwd_parts = [part.lower() for part in Path.cwd().parts]
    if len(cwd_parts) >= len(parts) and cwd_parts[-len(parts):] == parts:
        return str(Path.cwd())
    if Path.cwd().name.lower() == parts[-1]:
        return str(Path.cwd())
    return ""


def _configured_server_name(servers: Mapping[str, Any]) -> str:
    for name in CODEX_MCP_SERVER_NAMES:
        if name in servers:
            return name
    return ""


def _command_resolves(command: str) -> bool:
    expanded = Path(os.path.expandvars(os.path.expanduser(command)))
    if expanded.is_absolute() or expanded.parent != Path("."):
        return expanded.exists()
    return shutil.which(command) is not None


def _path_exists(value: str) -> bool:
    return Path(os.path.expandvars(os.path.expanduser(value))).exists()


def _clean_env(env: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): str(value).strip() for key, value in env.items() if str(value).strip()}


def _persona_name_from_id(persona_id: str) -> str:
    parts = [part for part in persona_id.replace("\\", "/").split("/") if part.strip()]
    return parts[-1] if parts else ""


def _derive_personas_dir(persona_root: str, persona_id: str) -> str:
    if not persona_root or not persona_id:
        return ""
    depth = len([part for part in persona_id.replace("\\", "/").split("/") if part.strip()])
    path = Path(persona_root)
    for _ in range(depth):
        path = path.parent
    return str(path)


def _add_runtime_field(fields: list[dict[str, str]], name: str, value: str, source: str) -> None:
    fields.append(
        {
            "name": name,
            "status": "resolved" if value else "missing",
            "source": source if value else "missing",
        }
    )


def _resolve_codex_runtime(env: Mapping[str, Any]) -> tuple[dict[str, str], list[dict[str, str]]]:
    clean = _clean_env(env)
    fields: list[dict[str, str]] = []

    persona_id = clean.get("CHIMERA_PERSONA_ID", "")
    persona_name = clean.get("CHIMERA_PERSONA_NAME", "") or _persona_name_from_id(persona_id)
    transcript_persona = clean.get("TRANSCRIPT_PERSONA", "") or persona_name
    persona_root = clean.get("CHIMERA_PERSONA_ROOT", "")
    personas_dir = clean.get("CHIMERA_PERSONAS_DIR", "") or _derive_personas_dir(persona_root, persona_id)
    shared_root = clean.get("CHIMERA_SHARED_ROOT", "") or (str(Path(personas_dir).parent / "shared") if personas_dir else "")
    jsonl_dir = clean.get("TRANSCRIPT_JSONL_DIR", "") or "~/.codex/sessions/"
    db_path = clean.get("TRANSCRIPT_DB_PATH", "")
    if not db_path and persona_name:
        db_path = str(persona_transcript_db_path(persona_name, persona_id=persona_id or None))

    values_and_sources = [
        ("CHIMERA_CLIENT", clean.get("CHIMERA_CLIENT", ""), "explicit" if clean.get("CHIMERA_CLIENT") else "missing"),
        ("TRANSCRIPT_JSONL_DIR", jsonl_dir, "explicit" if clean.get("TRANSCRIPT_JSONL_DIR") else "derived:codex_default"),
        ("CHIMERA_PERSONA_ID", persona_id, "explicit" if persona_id else "missing"),
        ("CHIMERA_PERSONA_NAME", persona_name, "explicit" if clean.get("CHIMERA_PERSONA_NAME") else "derived:CHIMERA_PERSONA_ID"),
        ("TRANSCRIPT_PERSONA", transcript_persona, "explicit" if clean.get("TRANSCRIPT_PERSONA") else "derived:CHIMERA_PERSONA_ID"),
        ("CHIMERA_PERSONA_ROOT", persona_root, "explicit" if persona_root else "missing"),
        ("CHIMERA_PERSONAS_DIR", personas_dir, "explicit" if clean.get("CHIMERA_PERSONAS_DIR") else "derived:CHIMERA_PERSONA_ROOT"),
        ("CHIMERA_SHARED_ROOT", shared_root, "explicit" if clean.get("CHIMERA_SHARED_ROOT") else "derived:CHIMERA_PERSONAS_DIR"),
        ("TRANSCRIPT_DB_PATH", db_path, "explicit" if clean.get("TRANSCRIPT_DB_PATH") else "derived:CHIMERA_PERSONA_ID"),
    ]
    values: dict[str, str] = {}
    for name, value, source in values_and_sources:
        values[name] = value
        _add_runtime_field(fields, name, value, source)
    return values, fields


def _runtime_field(fields: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for field in fields:
        if field.get("name") == name:
            return field
    return {}


def _runtime_source(fields: list[dict[str, Any]], name: str) -> str:
    return str(_runtime_field(fields, name).get("source") or "missing")


def _check_latest_health_snapshot(checks: list[dict[str, Any]], db_path: str) -> None:
    if not db_path:
        _check(checks, "cm_health", "info", "CM health snapshot unavailable: transcript DB path is not resolved.")
        return
    expanded = Path(os.path.expandvars(os.path.expanduser(db_path)))
    if not expanded.exists():
        _check(checks, "cm_health", "info", "CM health snapshot unavailable: transcript DB does not exist yet.")
        return
    conn = None
    try:
        conn = sqlite3.connect(str(expanded))
        row = conn.execute(
            """
            SELECT created_at, payload
            FROM memory_audit_events
            WHERE event_type = 'cm_health_snapshot'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.Error:
        _check(checks, "cm_health", "info", "CM health snapshot unavailable: audit table is not initialized yet.")
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    if not row:
        _check(checks, "cm_health", "info", "CM health snapshot unavailable: no snapshot has been recorded yet.")
        return
    try:
        payload = json.loads(row[1] or "{}")
    except json.JSONDecodeError:
        payload = {}
    status = str(payload.get("status") or "unknown")
    workers = payload.get("checks", {}).get("workers", {}) if isinstance(payload.get("checks"), Mapping) else {}
    worker_bits = []
    if isinstance(workers, Mapping):
        for key, value in workers.items():
            if key != "status":
                worker_bits.append(f"{key}={bool(value)}")
    state = "ok"
    if status == "broken":
        state = "error"
    elif status == "degraded":
        state = "warning"
    suffix = f"; workers: {', '.join(worker_bits)}" if worker_bits else ""
    _check(checks, "cm_health", state, f"Latest CM health snapshot: {status}{suffix}.")


def _check(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    item: dict[str, Any] = {"name": name, "status": status, "message": message}
    if details:
        item["details"] = dict(details)
    checks.append(item)


def _finalize(result: dict[str, Any]) -> dict[str, Any]:
    statuses = [str(check.get("status") or "") for check in result["checks"]]
    if "error" in statuses:
        result["status"] = "error"
    elif "warning" in statuses:
        result["status"] = "warning"
    else:
        result["status"] = "ok"
    return result
