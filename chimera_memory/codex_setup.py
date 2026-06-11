"""Codex setup diagnostics for Chimera Memory."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

from .memory_cli_worker_supervisor import DEFAULT_CODEX_MEMORY_WORKER_MODEL
from .paths import persona_transcript_db_path
from .diagnostic_time import format_diagnostic_timestamp


CODEX_MCP_SERVER_NAMES = ("chimera-memory", "chimera_memory")
IDENTITY_ENV = (
    "CHIMERA_PERSONA_ID",
    "CHIMERA_PERSONA_NAME",
    "CHIMERA_PERSONA_ROOT",
    "CHIMERA_PERSONAS_DIR",
    "CHIMERA_SHARED_ROOT",
)
PROJECT_ENV = (
    "CHIMERA_MEMORY_PROJECT_ID",
    "CHIMERA_MEMORY_PROJECT_ROOT",
)
GLOBAL_ENV = (
    "CHIMERA_MEMORY_GLOBAL_ROOT",
)
DEFAULT_CODEX_GLOBAL_ROOT = "~/.chimera-memory/global-memory"
HEALTH_SNAPSHOT_STALE_SECONDS = 15 * 60
REAL_WRAPPER_DELIVERY_RECENT_SECONDS = 24 * 60 * 60
HTTP_LISTENER_SOURCE_FRESHNESS_GRACE_SECONDS = 2
HTTP_LISTENER_RUNTIME_SOURCE_FILES = (
    "server.py",
    "memory.py",
    "memory_context_pack.py",
    "memory_relevance.py",
    "memory_scope.py",
    "memory_health.py",
    "mcp_surface.py",
    "codex_context.py",
    "transcript_context.py",
)
CODEX_CONTEXT_TRACE_EVENT_TYPES = frozenset(
    {
        "codex_prompt_delivered",
        "codex_transcript_context_miss",
        "codex_transcript_context_returned",
        "codex_transcript_context_skipped",
        "codex_prompt_delivery_failed",
        "memory_context_pack_miss",
        "memory_context_pack_returned",
        "memory_context_pack_skipped",
    }
)
CODEX_CONTEXT_DELIVERY_KIND_ALIASES = {
    "real": "real_exec_delivery",
    "real_exec": "real_exec_delivery",
    "real_exec_delivery": "real_exec_delivery",
    "delivered": "real_exec_delivery",
    "failed": "exec_delivery_failed",
    "failure": "exec_delivery_failed",
    "exec_delivery_failed": "exec_delivery_failed",
    "prompt": "prompt_construction",
    "prompt_construction": "prompt_construction",
    "construction": "prompt_construction",
    "diagnostic": "diagnostic_smoke",
    "diagnostic_smoke": "diagnostic_smoke",
    "smoke": "diagnostic_smoke",
    "context": "context_trace",
    "context_trace": "context_trace",
}


def default_codex_mcp_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def build_codex_mcp_config(
    *,
    persona: str = "",
    jsonl_dir: str = "~/.codex/sessions/",
    command: str = "chimera-memory",
    server_name: str = "chimera-memory",
    persona_id: str = "",
    persona_name: str = "",
    persona_root: str = "",
    personas_dir: str = "",
    shared_root: str = "",
    project_id: str = "",
    project_root: str = "",
    global_root: str = "",
) -> dict[str, Any]:
    """Build a safe Codex MCP config template.

    The template only contains paths and non-secret identity fields. It never
    reads the user's current config and never emits raw credentials.
    """
    persona = persona.strip()
    persona_id = persona_id.strip()
    persona_name = persona_name.strip()
    project_requested = bool(project_id.strip() or project_root.strip() or not (persona or persona_id or persona_name))
    selected_project_root = _default_project_root(project_root)
    selected_project_id = _safe_project_id(project_id or _project_id_from_root(selected_project_root))
    selected_global_root = _default_global_root(global_root) if project_requested else global_root.strip()
    server_command, server_args = _server_launch(command)
    server_name = server_name.strip()
    if not server_name:
        raise ValueError("server_name is required")

    env: dict[str, str] = {
        "TRANSCRIPT_JSONL_DIR": jsonl_dir.strip() or "~/.codex/sessions/",
        "CHIMERA_CLIENT": "codex",
        "CHIMERA_MEMORY_MCP_SURFACE": _default_codex_mcp_surface(
            "",
            project_profile=not (persona or persona_id or persona_name),
        ),
    }
    if persona or persona_id or persona_name:
        env["TRANSCRIPT_PERSONA"] = persona or persona_name or _persona_name_from_id(persona_id)
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
    if project_requested:
        env["CHIMERA_MEMORY_PROJECT_ID"] = selected_project_id
        env["CHIMERA_MEMORY_PROJECT_ROOT"] = selected_project_root
        env["CHIMERA_MEMORY_GLOBAL_ROOT"] = selected_global_root

    return {
        "mcpServers": {
            server_name: {
                "command": server_command,
                "args": server_args,
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
    project_id: str = "",
    project_root: str = "",
    global_root: str = "",
    jsonl_dir: str = "~/.codex/sessions/",
    command: str = "chimera-memory",
    server_name: str = "chimera-memory",
    import_history: bool = True,
    mcp_surface: str = "",
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
    project_requested = bool(project_id.strip() or project_root.strip() or not (persona_name or persona_id))
    selected_project_root = _default_project_root(project_root)
    selected_project_id = _safe_project_id(project_id or _project_id_from_root(selected_project_root))
    selected_global_root = _default_global_root(global_root) if project_requested else global_root.strip()

    server_command, server_args = _server_launch(command)
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
    selected_mcp_surface = _default_codex_mcp_surface(mcp_surface, project_profile=not (persona_name or persona_id))
    env = _build_codex_install_env(
        persona=persona_name,
        persona_id=persona_id,
        persona_root=persona_root,
        project_id=selected_project_id if project_requested else "",
        project_root=selected_project_root if project_requested else "",
        global_root=selected_global_root if project_requested else "",
        jsonl_dir=jsonl_dir,
        import_history=import_history,
        mcp_surface=selected_mcp_surface,
        provider=selected_provider,
        oauth_store=resolved_oauth_store,
        enable_provider_worker=enable_provider_worker,
    )
    worker_transport = _provider_worker_transport(selected_provider, enable_provider_worker)
    provider_auth = _maybe_import_provider_auth(
        provider_id=selected_provider,
        reuse_provider_auth=reuse_provider_auth,
        oauth_store=resolved_oauth_store,
        hermes_home=hermes_home,
        claude_credentials_path=claude_credentials_path,
        codex_auth_path=codex_auth_path,
    )
    servers[configured_name] = {
        "command": server_command,
        "args": server_args,
        "env": env,
    }

    backup_path = ""
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        if project_requested and selected_project_root:
            Path(selected_project_root).expanduser().mkdir(parents=True, exist_ok=True)
        if selected_global_root:
            Path(selected_global_root).expanduser().mkdir(parents=True, exist_ok=True)
        if existed:
            backup_path = _backup_path_for(path)
            shutil.copy2(path, backup_path)
        if _is_toml_config(path):
            _write_codex_toml_server(path, configured_name, servers[configured_name])
        else:
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
        "memory_profile": "persona" if persona_name or persona_id else "project",
        "project_id": selected_project_id if project_requested else "",
        "project_root": selected_project_root if project_requested else "",
        "global_root_configured": bool(selected_global_root),
        "import_history": import_history,
        "mcp_surface": selected_mcp_surface,
        "provider": selected_provider or "dry_run",
        "provider_auth": provider_auth,
        "provider_worker_mode": worker_transport["mode"],
        "provider_worker_runtime": worker_transport["runtime"],
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
        f"Memory profile: {result.get('memory_profile') or 'persona'}",
        f"Import history: {'enabled' if result.get('import_history') else 'disabled'}",
        f"MCP surface: {result.get('mcp_surface')}",
        f"Provider: {result.get('provider')}",
        f"Provider worker: {result.get('provider_worker_mode')}",
    ]
    worker_runtime = str(result.get("provider_worker_runtime") or "")
    if worker_runtime:
        lines.append(f"Provider worker runtime: {worker_runtime}")
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
        "transport": "",
        "env_keys": [],
        "runtime_fields": [],
        "provider_smoke": None,
        "global_memory_recommendations": [],
        "context_delivery": {
            "latest_trace": None,
            "latest_returned_trace": None,
            "latest_codex_context_trace": None,
            "latest_codex_context_returned_trace": None,
            "latest_real_wrapper_trace": None,
            "latest_real_wrapper_returned_trace": None,
            "latest_real_wrapper_delivery_recency": None,
            "global_context_smoke": None,
            "prompt_boundary": "MCP tools are on-demand; prompt evidence requires codex context, codex exec, or another hook/harness.",
        },
        "checks": checks,
    }

    if not path.is_file():
        _check(checks, "config_exists", "error", "Codex MCP config file does not exist.")
        return _finalize(result)
    _check(checks, "config_exists", "ok", "Codex MCP config file exists.")

    try:
        data = _load_codex_config_data(path)
    except ValueError as exc:
        _check(checks, "parse_config", "error", str(exc))
        return _finalize(result)
    if not isinstance(data, Mapping):
        _check(checks, "parse_config", "error", "Codex MCP config root must be an object.")
        return _finalize(result)
    result["parse_ok"] = True
    parser_name = "TOML" if _is_toml_config(path) else "JSON"
    _check(checks, "parse_config", "ok", f"Codex MCP config parses as {parser_name}.")

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

    url = str(server.get("url") or "").strip()
    if url:
        result["transport"] = "http"
        _check_http_mcp_url(checks, url)
        env = server.get("env")
        if isinstance(env, Mapping):
            result["env_keys"] = sorted(str(key) for key in env.keys())
            _check(checks, "env", "info", "HTTP MCP env is configured on this entry; the shared server process must still receive its runtime env.")
            runtime_values, resolved_fields = _resolve_codex_runtime(env)
            result["runtime_fields"] = resolved_fields
            db_path = runtime_values.get("TRANSCRIPT_DB_PATH", "")
            expect_project_runtime = (
                not runtime_values.get("TRANSCRIPT_PERSONA")
                and bool(runtime_values.get("CHIMERA_MEMORY_PROJECT_ID") or runtime_values.get("CHIMERA_MEMORY_PROJECT_ROOT"))
            )
            global_root = runtime_values.get("CHIMERA_MEMORY_GLOBAL_ROOT", "")
        else:
            _check(checks, "env", "info", "HTTP MCP config has no server env; set runtime env on the shared server process.")
            db_path = _default_transcript_db_path()
            expect_project_runtime = True
            global_root = _doctor_default_global_root()
        health_payload = _check_latest_health_snapshot(
            checks,
            db_path,
            expect_codex_project_runtime=expect_project_runtime,
            global_root=global_root,
        )
        _check_provider_smoke_plan(
            checks,
            result,
            env=env if isinstance(env, Mapping) else {},
            env_source="http_config" if isinstance(env, Mapping) else "doctor_process",
            health_payload=health_payload,
        )
        if expect_project_runtime:
            _check_global_review_queue(
                checks,
                global_root=global_root,
                db_path=db_path,
                recommendations=result["global_memory_recommendations"],
            )
        delivery = result["context_delivery"] if isinstance(result.get("context_delivery"), dict) else None
        _check_latest_context_traces(checks, db_path, delivery=delivery)
        _check_codex_global_context_smoke(
            checks,
            db_path,
            global_root=global_root,
            delivery=delivery,
            require_global_root=expect_project_runtime,
        )
        _check_real_wrapper_effectiveness(checks, delivery)
        _check_prompt_context_boundary(checks)
        if isinstance(delivery, dict):
            delivery["recommendations"] = _codex_context_delivery_recommendations(delivery)
        return _finalize(result)

    result["transport"] = "stdio"
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
    project_configured = bool(
        runtime_values.get("CHIMERA_MEMORY_PROJECT_ID") or runtime_values.get("CHIMERA_MEMORY_PROJECT_ROOT")
    )

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
    elif project_configured:
        _check(
            checks,
            "env:TRANSCRIPT_PERSONA",
            "ok",
            "No persona configured; Codex uses repo-scoped project memory.",
        )
    else:
        _check(checks, "env:TRANSCRIPT_PERSONA", "warning", "TRANSCRIPT_PERSONA could not be resolved.")

    has_identity_env = any(runtime_values.get(key) for key in IDENTITY_ENV)
    missing_identity = [
        field["name"]
        for field in resolved_fields
        if field["name"] in IDENTITY_ENV and field["status"] == "missing"
    ]
    if missing_identity and (persona or has_identity_env):
        _check(
            checks,
            "identity_env",
            "warning",
            "Persona identity env is incomplete. Derivation could not fill every field.",
            {"missing_keys": missing_identity},
        )
    elif not persona and project_configured:
        _check(checks, "identity_env", "ok", "Persona identity is intentionally unset for repo-scoped Codex memory.")
    else:
        _check(checks, "identity_env", "ok", "Persona identity resolves via explicit and derived fields.")

    if not persona and project_configured:
        missing_project = [key for key in PROJECT_ENV if not runtime_values.get(key)]
        if missing_project:
            _check(
                checks,
                "project_env",
                "warning",
                "Project memory env is incomplete. Set CHIMERA_MEMORY_PROJECT_ROOT for repo-scoped writes.",
                {"missing_keys": missing_project},
            )
        else:
            _check(checks, "project_env", "ok", "Project memory identity resolves for repo-scoped Codex memory.")
        _check_global_memory_env(checks, runtime_values.get("CHIMERA_MEMORY_GLOBAL_ROOT", ""))

    db_source = _runtime_source(resolved_fields, "TRANSCRIPT_DB_PATH")
    if db_source == "derived:CHIMERA_PERSONA_ID":
        _check(
            checks,
            "cm_health",
            "info",
            "CM health snapshot skipped: TRANSCRIPT_DB_PATH is derived from persona identity.",
        )
    else:
        health_payload = _check_latest_health_snapshot(
            checks,
            runtime_values.get("TRANSCRIPT_DB_PATH", ""),
            expect_codex_project_runtime=not persona and project_configured,
            global_root=runtime_values.get("CHIMERA_MEMORY_GLOBAL_ROOT", ""),
        )
        _check_provider_smoke_plan(checks, result, env=env, env_source="config", health_payload=health_payload)
    if db_source == "derived:CHIMERA_PERSONA_ID":
        _check_provider_smoke_plan(checks, result, env=env, env_source="config")
    if not persona and project_configured:
        _check_global_review_queue(
            checks,
            global_root=runtime_values.get("CHIMERA_MEMORY_GLOBAL_ROOT", ""),
            db_path=runtime_values.get("TRANSCRIPT_DB_PATH", ""),
            recommendations=result["global_memory_recommendations"],
        )
    delivery = result["context_delivery"] if isinstance(result.get("context_delivery"), dict) else None
    _check_latest_context_traces(checks, runtime_values.get("TRANSCRIPT_DB_PATH", ""), delivery=delivery)
    _check_codex_global_context_smoke(
        checks,
        runtime_values.get("TRANSCRIPT_DB_PATH", ""),
        global_root=runtime_values.get("CHIMERA_MEMORY_GLOBAL_ROOT", ""),
        delivery=delivery,
        require_global_root=not persona and project_configured,
    )
    _check_real_wrapper_effectiveness(checks, delivery)
    _check_prompt_context_boundary(checks)
    if isinstance(delivery, dict):
        delivery["recommendations"] = _codex_context_delivery_recommendations(delivery)

    return _finalize(result)


def format_codex_doctor_report(result: Mapping[str, Any]) -> str:
    """Render a human-readable report without raw env values."""
    status = str(result.get("status") or "unknown").upper()
    lines = [
        f"Codex ChimeraMemory setup: {status}",
        f"Config: {result.get('config_path')}",
        f"Server: {result.get('server_name') or 'not configured'}",
    ]
    transport = str(result.get("transport") or "")
    if transport:
        lines.append(f"Transport: {transport}")
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
    global_recommendations = result.get("global_memory_recommendations")
    if isinstance(global_recommendations, list) and global_recommendations:
        lines.append("")
        lines.append("Global memory recommendations:")
        for item in global_recommendations:
            if not isinstance(item, Mapping):
                continue
            command = str(item.get("command") or "")
            suffix = f" Command: {command}" if command else ""
            lines.append(f"- {item.get('message', '')}{suffix}")
    delivery = result.get("context_delivery")
    if isinstance(delivery, Mapping):
        recommendations = delivery.get("recommendations")
        if isinstance(recommendations, list) and recommendations:
            lines.append("")
            lines.append("Context delivery recommendations:")
            for item in recommendations:
                if not isinstance(item, Mapping):
                    continue
                command = str(item.get("command") or "")
                suffix = f" Command: {command}" if command else ""
                lines.append(f"- {item.get('message', '')}{suffix}")
    return "\n".join(lines)


def _read_codex_config_for_install(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {"mcpServers": {}}, False
    data = _load_codex_config_data(path)
    if not isinstance(data, dict):
        raise ValueError("Codex MCP config root must be an object")
    return data, True


def _backup_path_for(path: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return str(path.with_name(f"{path.name}.bak-{stamp}"))


def _build_codex_install_env(
    *,
    persona: str,
    persona_id: str,
    persona_root: str,
    project_id: str,
    project_root: str,
    global_root: str,
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
        "CHIMERA_MEMORY_MCP_SURFACE": mcp_surface,
        "CHIMERA_MEMORY_STARTUP_BOOTSTRAP": "post_ready",
        "CHIMERA_MEMORY_TRANSCRIPT_EMBEDDING_WORKER": "true",
        "CHIMERA_MEMORY_HEALTH_WORKER": "true",
    }
    if provider and provider != "dry_run":
        env["CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_AFFINITY"] = provider
    if enable_provider_worker:
        env["CHIMERA_MEMORY_ENHANCEMENT_WORKER"] = "true"
        worker_transport = _provider_worker_transport(provider, enable_provider_worker)
        env["CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE"] = worker_transport["mode"]
        runtime = worker_transport["runtime"]
        if runtime:
            env["CHIMERA_MEMORY_CLI_WORKER_RUNTIME"] = runtime
            env["CHIMERA_MEMORY_CLI_WORKER_EFFORT"] = "medium"
        if runtime == "codex":
            env["CHIMERA_MEMORY_CODEX_WORKER_PROVIDER"] = provider
            env["CHIMERA_MEMORY_CODEX_WORKER_MODEL"] = DEFAULT_CODEX_MEMORY_WORKER_MODEL
        elif runtime == "claude":
            env["CHIMERA_MEMORY_CLAUDE_WORKER_PROVIDER"] = provider
        elif runtime == "agy":
            env["CHIMERA_MEMORY_AGY_WORKER_PROVIDER"] = provider
    else:
        env["CHIMERA_MEMORY_ENHANCEMENT_WORKER"] = "false"
    if persona_id:
        env["CHIMERA_PERSONA_ID"] = persona_id
        derived_name = _persona_name_from_id(persona_id)
        if persona and persona != derived_name:
            env["CHIMERA_PERSONA_NAME"] = persona
    else:
        if persona:
            env["TRANSCRIPT_PERSONA"] = persona
    if project_id:
        env["CHIMERA_MEMORY_PROJECT_ID"] = project_id
    if project_root:
        env["CHIMERA_MEMORY_PROJECT_ROOT"] = project_root
    if global_root:
        env["CHIMERA_MEMORY_GLOBAL_ROOT"] = global_root
    cleaned_root = persona_root.strip()
    if cleaned_root:
        env["CHIMERA_PERSONA_ROOT"] = cleaned_root
    if enable_provider_worker:
        env["CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE"] = "true"
        enqueue_identity = persona.strip() or (_persona_name_from_id(persona_id) if persona_id else "")
        if not enqueue_identity and project_id:
            enqueue_identity = f"project:{project_id}"
        env["CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE_PERSONAS"] = enqueue_identity
    return env


def _default_codex_mcp_surface(value: str, *, project_profile: bool) -> str:
    selected = str(value or "").strip()
    if selected:
        return selected
    return "codex" if project_profile else "persona"


def _provider_worker_transport(provider: str, enabled: bool) -> dict[str, str]:
    if not enabled:
        return {"mode": "dry_run", "runtime": ""}
    if provider == "openai":
        return {"mode": "cli_worker", "runtime": "codex"}
    if provider == "anthropic":
        return {"mode": "cli_worker", "runtime": "claude"}
    if provider == "google":
        return {"mode": "cli_worker", "runtime": "agy"}
    if provider and provider != "dry_run":
        return {"mode": "provider", "runtime": ""}
    return {"mode": "dry_run", "runtime": ""}


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


def _is_toml_config(path: Path) -> bool:
    return path.suffix.lower() == ".toml"


def _load_codex_config_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if _is_toml_config(path):
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"Codex MCP config is not valid TOML: {exc}") from exc
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Codex MCP config is not valid JSON: {exc.msg}.") from exc
    if not isinstance(data, dict):
        raise ValueError("Codex MCP config root must be an object")
    if "mcpServers" not in data and isinstance(data.get("mcp_servers"), Mapping):
        data["mcpServers"] = dict(data["mcp_servers"])
    return data


def _write_codex_toml_server(path: Path, server_name: str, server: Mapping[str, Any]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = _remove_codex_toml_server_blocks(text, {server_name, *CODEX_MCP_SERVER_NAMES})
    block = _render_codex_toml_server(server_name, server)
    prefix = text.rstrip()
    output = f"{prefix}\n\n{block}" if prefix else block
    path.write_text(output.rstrip() + "\n", encoding="utf-8")


def _remove_codex_toml_server_blocks(text: str, server_names: set[str]) -> str:
    skip_tables = set()
    for name in server_names:
        for key in {_toml_table_key(name), name, name.replace("-", "_")}:
            skip_tables.add(f"mcp_servers.{key}")
            skip_tables.add(f"mcp_servers.{key}.env")

    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            table = stripped.strip("[]").strip()
            skipping = table in skip_tables
        if not skipping:
            kept.append(line)
    return "\n".join(kept).rstrip()


def _render_codex_toml_server(server_name: str, server: Mapping[str, Any]) -> str:
    env = server.get("env") if isinstance(server.get("env"), Mapping) else {}
    args = server.get("args") if isinstance(server.get("args"), list) else []
    lines = [
        f"[mcp_servers.{_toml_table_key(server_name)}]",
        f"command = {_toml_string(server.get('command') or '')}",
        "args = [" + ", ".join(_toml_string(arg) for arg in args) + "]",
        "startup_timeout_sec = 30",
        "",
        f"[mcp_servers.{_toml_table_key(server_name)}.env]",
    ]
    for key in sorted(str(key) for key in env):
        lines.append(f"{key} = {_toml_string(env[key])}")
    return "\n".join(lines)


def _toml_table_key(value: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        return value
    return _toml_string(value)


def _toml_string(value: object) -> str:
    return json.dumps(str(value or ""))


def _server_launch(command: str) -> tuple[str, list[str]]:
    text = str(command or "").strip()
    if not text:
        raise ValueError("command is required")
    expanded = Path(os.path.expandvars(os.path.expanduser(text)))
    if expanded.is_file():
        executable = text
        args: list[str] = []
    else:
        try:
            parts = shlex.split(text, posix=os.name != "nt")
        except ValueError as exc:
            raise ValueError("command is invalid") from exc
        parts = [part.strip('"') for part in parts]
        if not parts:
            raise ValueError("command is required")
        executable, *args = parts
    if _is_python_command(executable) and not args:
        args = ["-m", "chimera_memory.cli"]
    if "serve" not in [str(item) for item in args]:
        args.append("serve")
    return executable, args


def _is_python_command(command: str) -> bool:
    return Path(command).name.lower() in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}


def _safe_project_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return clean or "default"


def _default_project_root(value: str | Path | None = "") -> str:
    text = str(value or "").strip()
    if text:
        return text
    return str(Path.cwd() / ".chimera-memory")


def _default_global_root(value: str | Path | None = "") -> str:
    text = str(value or "").strip()
    return text or DEFAULT_CODEX_GLOBAL_ROOT


def _project_id_from_root(value: str | Path) -> str:
    root = Path(value).expanduser()
    if root.name == ".chimera-memory" and root.parent.name:
        return _safe_project_id(root.parent.name)
    return _safe_project_id(root.name)


def _default_transcript_db_path() -> str:
    return str(Path.home() / ".chimera-memory" / "transcript.db")


def _doctor_default_global_root() -> str:
    configured = os.environ.get("CHIMERA_MEMORY_GLOBAL_ROOT", "").strip()
    return configured or DEFAULT_CODEX_GLOBAL_ROOT


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
    project_root = clean.get("CHIMERA_MEMORY_PROJECT_ROOT", "")
    project_id = clean.get("CHIMERA_MEMORY_PROJECT_ID", "") or (_project_id_from_root(project_root) if project_root else "")
    global_root = clean.get("CHIMERA_MEMORY_GLOBAL_ROOT", "")
    jsonl_dir = clean.get("TRANSCRIPT_JSONL_DIR", "") or "~/.codex/sessions/"
    db_path = clean.get("TRANSCRIPT_DB_PATH", "")
    if not db_path and persona_name:
        db_path = str(persona_transcript_db_path(persona_name, persona_id=persona_id or None))
    elif not db_path:
        db_path = _default_transcript_db_path()

    values_and_sources = [
        ("CHIMERA_CLIENT", clean.get("CHIMERA_CLIENT", ""), "explicit" if clean.get("CHIMERA_CLIENT") else "missing"),
        ("TRANSCRIPT_JSONL_DIR", jsonl_dir, "explicit" if clean.get("TRANSCRIPT_JSONL_DIR") else "derived:codex_default"),
        ("CHIMERA_PERSONA_ID", persona_id, "explicit" if persona_id else "missing"),
        ("CHIMERA_PERSONA_NAME", persona_name, "explicit" if clean.get("CHIMERA_PERSONA_NAME") else "derived:CHIMERA_PERSONA_ID"),
        ("TRANSCRIPT_PERSONA", transcript_persona, "explicit" if clean.get("TRANSCRIPT_PERSONA") else "derived:CHIMERA_PERSONA_ID"),
        ("CHIMERA_PERSONA_ROOT", persona_root, "explicit" if persona_root else "missing"),
        ("CHIMERA_PERSONAS_DIR", personas_dir, "explicit" if clean.get("CHIMERA_PERSONAS_DIR") else "derived:CHIMERA_PERSONA_ROOT"),
        ("CHIMERA_SHARED_ROOT", shared_root, "explicit" if clean.get("CHIMERA_SHARED_ROOT") else "derived:CHIMERA_PERSONAS_DIR"),
        ("CHIMERA_MEMORY_PROJECT_ID", project_id, "explicit" if clean.get("CHIMERA_MEMORY_PROJECT_ID") else "derived:CHIMERA_MEMORY_PROJECT_ROOT"),
        ("CHIMERA_MEMORY_PROJECT_ROOT", project_root, "explicit" if project_root else "missing"),
        ("CHIMERA_MEMORY_GLOBAL_ROOT", global_root, "explicit" if global_root else "missing"),
        (
            "TRANSCRIPT_DB_PATH",
            db_path,
            "explicit"
            if clean.get("TRANSCRIPT_DB_PATH")
            else ("derived:CHIMERA_PERSONA_ID" if persona_name else "default"),
        ),
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


def _check_latest_health_snapshot(
    checks: list[dict[str, Any]],
    db_path: str,
    *,
    expect_codex_project_runtime: bool = False,
    global_root: str = "",
) -> dict[str, Any] | None:
    if not db_path:
        _check(checks, "cm_health", "info", "CM health snapshot unavailable: transcript DB path is not resolved.")
        return None
    expanded = Path(os.path.expandvars(os.path.expanduser(db_path)))
    if not expanded.exists():
        _check(checks, "cm_health", "info", "CM health snapshot unavailable: transcript DB does not exist yet.")
        return None
    conn = None
    live_global_counts: dict[str, int] | None = None
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
        live_global_counts = _fetch_live_global_corpus_counts(
            conn,
            global_root=global_root,
            require_global_root=expect_codex_project_runtime,
        )
    except sqlite3.Error:
        _check(checks, "cm_health", "info", "CM health snapshot unavailable: audit table is not initialized yet.")
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    if not row:
        _check(checks, "cm_health", "info", "CM health snapshot unavailable: no snapshot has been recorded yet.")
        if live_global_counts is not None:
            _check_global_corpus_profile(checks, _global_profile_from_live_counts(live_global_counts))
        return None
    _check_health_snapshot_freshness(checks, row[0])
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
    _check_health_runtime_profile(
        checks,
        payload,
        live_global_counts=live_global_counts,
        expect_codex_project_runtime=expect_codex_project_runtime,
    )
    return payload


def _check_health_snapshot_freshness(checks: list[dict[str, Any]], created_at: object) -> None:
    parsed = _parse_diagnostic_timestamp(created_at)
    if parsed is None:
        _check(
            checks,
            "cm_health_freshness",
            "info",
            f"CM health snapshot timestamp could not be parsed: {created_at or '-'}",
        )
        return
    now = datetime.now(timezone.utc)
    age_seconds = max(0, int((now - parsed).total_seconds()))
    if age_seconds > HEALTH_SNAPSHOT_STALE_SECONDS:
        _check(
            checks,
            "cm_health_freshness",
            "warning",
            f"Latest CM health snapshot is stale: {format_diagnostic_timestamp(created_at)}.",
            {"age_seconds": age_seconds, "stale_after_seconds": HEALTH_SNAPSHOT_STALE_SECONDS},
        )
        return
    _check(
        checks,
        "cm_health_freshness",
        "ok",
        f"Latest CM health snapshot is fresh: {format_diagnostic_timestamp(created_at)}.",
        {"age_seconds": age_seconds, "stale_after_seconds": HEALTH_SNAPSHOT_STALE_SECONDS},
    )


def _parse_diagnostic_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _check_provider_smoke_plan(
    checks: list[dict[str, Any]],
    result: dict[str, Any],
    *,
    env: Mapping[str, Any],
    env_source: str,
    health_payload: Mapping[str, Any] | None = None,
) -> None:
    profile = _provider_profile_from_health_payload(health_payload)
    if profile:
        receipt = _provider_smoke_receipt_from_health_profile(profile)
        result["provider_smoke"] = receipt
        _check_provider_smoke_receipt(
            checks,
            receipt,
            env_source="sidecar_health",
        )
        return

    try:
        from .memory_enhancement_provider_smoke import memory_enhancement_provider_smoke

        smoke_env = dict(os.environ)
        smoke_env.update(_clean_env(env))
        receipt = memory_enhancement_provider_smoke(env=smoke_env, live=False)
    except Exception as exc:
        result["provider_smoke"] = {
            "ok": False,
            "status": "failed",
            "live": False,
            "error": {
                "code": "provider_smoke_unavailable",
                "message": "",
                "exception": exc.__class__.__name__,
            },
        }
        _check(
            checks,
            "cm_provider_smoke",
            "warning",
            "Enhancement provider smoke is unavailable.",
            {"env_source": env_source},
        )
        return

    result["provider_smoke"] = receipt
    _check_provider_smoke_receipt(checks, receipt, env_source=env_source)


def _provider_profile_from_health_payload(health_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(health_payload, Mapping):
        return {}
    profile = health_payload.get("provider_profile")
    if not isinstance(profile, Mapping) or profile.get("status") != "ok":
        return {}
    return {
        "selected_provider": str(profile.get("selected_provider") or ""),
        "selected_model": str(profile.get("selected_model") or ""),
        "credential_ref_present": bool(profile.get("credential_ref_present")),
        "uses_user_oauth": bool(profile.get("uses_user_oauth")),
        "requires_network": bool(profile.get("requires_network")),
    }


def _provider_smoke_receipt_from_health_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    selected_provider = str(profile.get("selected_provider") or "")
    selected_model = str(profile.get("selected_model") or "")
    return {
        "ok": True,
        "schema_version": "chimera-memory.provider-smoke.v1",
        "status": "planned",
        "live": False,
        "transport": "sidecar_health",
        "duration_ms": 0,
        "provider": {
            "selected_provider": selected_provider,
            "selected_model": selected_model,
        },
        "expectations": {
            "provider": "",
            "model": "",
            "matched": True,
        },
        "invocation": {
            "provider_id": selected_provider,
            "model": selected_model,
            "credential_ref_present": bool(profile.get("credential_ref_present")),
            "uses_user_oauth": bool(profile.get("uses_user_oauth")),
            "requires_network": bool(profile.get("requires_network")),
            "body_included": False,
        },
        "metadata": {},
        "body_included": False,
    }


def _check_provider_smoke_receipt(
    checks: list[dict[str, Any]],
    receipt: Mapping[str, Any],
    *,
    env_source: str,
) -> None:
    provider = receipt.get("provider") if isinstance(receipt.get("provider"), Mapping) else {}
    selected_provider = str(provider.get("selected_provider") or "")
    selected_model = str(provider.get("selected_model") or "")
    invocation = receipt.get("invocation") if isinstance(receipt.get("invocation"), Mapping) else {}
    details = {
        "env_source": env_source,
        "selected_provider": selected_provider,
        "selected_model": selected_model,
        "credential_ref_present": bool(invocation.get("credential_ref_present")),
        "uses_user_oauth": bool(invocation.get("uses_user_oauth")),
        "requires_network": bool(invocation.get("requires_network")),
        "live": False,
        "transport": str(receipt.get("transport") or ""),
    }
    if not receipt.get("ok"):
        _check(
            checks,
            "cm_provider_smoke",
            "warning",
            "Enhancement provider smoke plan failed.",
            details,
        )
        return
    if selected_provider == "dry_run":
        _check(
            checks,
            "cm_provider_smoke",
            "info",
            "Enhancement provider smoke planned deterministic dry-run; provider-backed enhancement is not selected.",
            details,
        )
        return
    _check(
        checks,
        "cm_provider_smoke",
        "ok",
        (
            "Enhancement provider smoke planned "
            f"{selected_provider}/{selected_model}; "
            f"credential_ref_present={details['credential_ref_present']}, "
            f"uses_user_oauth={details['uses_user_oauth']}. "
            "Run `chimera-memory enhance provider-smoke --live --http-sidecar --json` for live provider proof."
        ),
        details,
    )


def _check_global_memory_env(checks: list[dict[str, Any]], global_root: str) -> None:
    if not global_root:
        _check(
            checks,
            "global_env",
            "warning",
            "Global memory root is not configured for no-persona Codex project memory.",
            {"missing_keys": list(GLOBAL_ENV)},
        )
        return
    status = "ok" if _path_exists(global_root) else "warning"
    message = (
        "Global memory root exists for no-persona Codex project memory."
        if status == "ok"
        else "Global memory root is configured but does not exist yet; create it before starting the watcher."
    )
    _check(checks, "global_env", status, message)


def _check_health_runtime_profile(
    checks: list[dict[str, Any]],
    payload: Mapping[str, Any],
    *,
    live_global_counts: Mapping[str, int] | None,
    expect_codex_project_runtime: bool,
) -> None:
    profile = payload.get("runtime_profile")
    if not isinstance(profile, Mapping):
        _check(
            checks,
            "cm_runtime",
            "info",
            "CM runtime profile unavailable: latest health snapshot was recorded by an older server.",
        )
        if live_global_counts is not None:
            _check_global_corpus_profile(checks, _global_profile_from_live_counts(live_global_counts))
        return

    if profile.get("status") != "ok":
        _check(checks, "cm_runtime", "info", "CM runtime profile unavailable in latest health snapshot.")
        if live_global_counts is not None:
            _check_global_corpus_profile(checks, _global_profile_from_live_counts(live_global_counts))
        return

    profile = dict(profile)
    if live_global_counts is not None:
        profile.update(_global_profile_from_live_counts(live_global_counts))

    client = str(profile.get("client") or "").strip().lower()
    surface = str(profile.get("mcp_surface") or "").strip().lower()
    memory_profile = str(profile.get("memory_profile") or "").strip().lower()
    detail = (
        f"client={client or '-'}, surface={surface or '-'}, profile={memory_profile or '-'}, "
        f"project_root_configured={bool(profile.get('project_root_configured'))}, "
        f"global_root_exists={bool(profile.get('global_root_exists'))}, "
        f"global_available_files={int(profile.get('global_available_file_count') or 0)}/"
        f"{int(profile.get('global_indexed_file_count') or 0)}, "
        f"global_instruction_grade_files={int(profile.get('global_instruction_grade_file_count') or 0)}/"
        f"{int(profile.get('global_available_file_count') or 0)}, "
        f"persona_tree_indexing={bool(profile.get('persona_tree_indexing'))}"
    )
    _check_global_corpus_profile(checks, profile)
    if not expect_codex_project_runtime:
        _check(checks, "cm_runtime", "ok", f"Live CM sidecar runtime profile recorded. Runtime: {detail}.")
        return

    issues: list[str] = []
    if client != "codex":
        issues.append("client is not codex")
    if surface != "codex":
        issues.append("MCP surface is not codex")
    if bool(profile.get("transcript_persona_set")):
        issues.append("TRANSCRIPT_PERSONA is set")
    if memory_profile != "project":
        issues.append("memory profile is not project")
    if not bool(profile.get("project_id_set")):
        issues.append("project id is missing")
    if not bool(profile.get("project_root_configured")):
        issues.append("project root is missing")
    if profile.get("global_root_exists") is False:
        issues.append("global memory root is missing")
    if bool(profile.get("persona_tree_indexing")):
        issues.append("persona tree indexing is enabled")

    if issues:
        _check(
            checks,
            "cm_runtime",
            "warning",
            "Live CM sidecar is not ready for no-persona Codex project+global memory: "
            + "; ".join(issues)
            + f". Runtime: {detail}.",
        )
        return
    _check(
        checks,
        "cm_runtime",
        "ok",
        f"Live CM sidecar runtime matches no-persona Codex project+global memory. Runtime: {detail}.",
    )


def _resolved_global_root(global_root: str) -> Path | None:
    text = str(global_root or "").strip()
    if not text:
        return None
    try:
        return Path(os.path.expandvars(os.path.expanduser(text))).resolve(strict=False)
    except OSError:
        return None


def _path_is_under_root(path_text: object, root: Path) -> bool:
    text = str(path_text or "").strip()
    if not text:
        return False
    try:
        path = Path(os.path.expandvars(os.path.expanduser(text))).resolve(strict=False)
        path.relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _fetch_live_global_corpus_counts(
    conn: sqlite3.Connection,
    *,
    global_root: str = "",
    require_global_root: bool = False,
) -> dict[str, int] | None:
    try:
        rows = conn.execute(
            """
            SELECT
                path,
                CASE
                    WHEN COALESCE(f.fm_exclude_from_default_search, 0) = 0
                      AND COALESCE(f.fm_can_use_as_evidence, 1) = 1
                      AND COALESCE(f.fm_sensitivity_tier, 'standard') <> 'restricted'
                      AND COALESCE(f.fm_lifecycle_status, 'active') NOT IN ('disputed', 'rejected', 'superseded')
                    THEN 1 ELSE 0 END AS available,
                CASE
                    WHEN COALESCE(f.fm_exclude_from_default_search, 0) = 0
                      AND COALESCE(f.fm_can_use_as_evidence, 1) = 1
                      AND COALESCE(f.fm_sensitivity_tier, 'standard') <> 'restricted'
                      AND COALESCE(f.fm_lifecycle_status, 'active') NOT IN ('disputed', 'rejected', 'superseded')
                      AND COALESCE(f.fm_can_use_as_instruction, 1) = 1
                      AND COALESCE(f.fm_review_status, 'confirmed') = 'confirmed'
                      AND COALESCE(f.fm_provenance_status, 'imported') IN ('user_confirmed', 'auto_confirmed')
                    THEN 1 ELSE 0 END AS instruction_grade
            FROM memory_files f
            WHERE COALESCE(f.memory_scope, '') = 'global'
            """
        ).fetchall()
    except sqlite3.Error:
        return None
    root = _resolved_global_root(global_root)
    counts = {
        "indexed": 0,
        "available": 0,
        "instruction_grade": 0,
        "all_indexed": 0,
        "all_available": 0,
        "all_instruction_grade": 0,
        "outside_indexed": 0,
        "outside_available": 0,
        "outside_instruction_grade": 0,
        "root_filtered": 1 if root is not None else 0,
        "root_required": 1 if require_global_root and root is None else 0,
    }
    for path_text, available, instruction_grade in rows:
        is_available = int(available or 0)
        is_instruction_grade = int(instruction_grade or 0)
        counts["all_indexed"] += 1
        counts["all_available"] += is_available
        counts["all_instruction_grade"] += is_instruction_grade
        if root is not None and not _path_is_under_root(path_text, root):
            counts["outside_indexed"] += 1
            counts["outside_available"] += is_available
            counts["outside_instruction_grade"] += is_instruction_grade
            continue
        counts["indexed"] += 1
        counts["available"] += is_available
        counts["instruction_grade"] += is_instruction_grade
    if root is None and require_global_root:
        counts["outside_indexed"] = counts["all_indexed"]
        counts["outside_available"] = counts["all_available"]
        counts["outside_instruction_grade"] = counts["all_instruction_grade"]
    elif root is None:
        counts["indexed"] = counts["all_indexed"]
        counts["available"] = counts["all_available"]
        counts["instruction_grade"] = counts["all_instruction_grade"]
    return {
        key: int(value)
        for key, value in counts.items()
    }


def _global_profile_from_live_counts(live_global_counts: Mapping[str, int]) -> dict[str, int]:
    return {
        "global_indexed_file_count": int(live_global_counts.get("indexed") or 0),
        "global_available_file_count": int(live_global_counts.get("available") or 0),
        "global_instruction_grade_file_count": int(live_global_counts.get("instruction_grade") or 0),
        "all_global_indexed_file_count": int(live_global_counts.get("all_indexed") or 0),
        "outside_global_root_indexed_file_count": int(live_global_counts.get("outside_indexed") or 0),
        "outside_global_root_available_file_count": int(live_global_counts.get("outside_available") or 0),
        "outside_global_root_instruction_grade_file_count": int(
            live_global_counts.get("outside_instruction_grade") or 0
        ),
        "global_root_filtered": bool(live_global_counts.get("root_filtered")),
        "global_root_required": bool(live_global_counts.get("root_required")),
    }


def _check_global_corpus_profile(checks: list[dict[str, Any]], profile: Mapping[str, Any]) -> None:
    if "global_indexed_file_count" not in profile or "global_available_file_count" not in profile:
        return
    indexed = int(profile.get("global_indexed_file_count") or 0)
    available = int(profile.get("global_available_file_count") or 0)
    instruction_grade = int(profile.get("global_instruction_grade_file_count") or 0)
    root_filtered = bool(profile.get("global_root_filtered"))
    root_required = bool(profile.get("global_root_required"))
    all_indexed = int(profile.get("all_global_indexed_file_count") or 0)
    outside_indexed = int(profile.get("outside_global_root_indexed_file_count") or 0)
    outside_available = int(profile.get("outside_global_root_available_file_count") or 0)
    outside_instruction_grade = int(profile.get("outside_global_root_instruction_grade_file_count") or 0)
    if root_required and not root_filtered:
        status = "warning" if all_indexed > 0 else "info"
        _check(
            checks,
            "cm_global_corpus",
            status,
            "No active global memory root is configured for Codex project memory; "
            "indexed global rows are not treated as active global memory until CHIMERA_MEMORY_GLOBAL_ROOT is set.",
            {"all_global_indexed_file_count": all_indexed},
        )
        return
    if indexed <= 0:
        corpus_label = "configured global memory root" if root_filtered else "global memory"
        _check(
            checks,
            "cm_global_corpus",
            "info",
            f"No indexed files are available in the {corpus_label} yet; global memory is wired but the corpus is empty. "
            "Add or promote global memories, or start the sidecar with a global root that contains curated memory files.",
        )
        _check_outside_global_root_rows(
            checks,
            outside_indexed=outside_indexed,
            outside_available=outside_available,
            outside_instruction_grade=outside_instruction_grade,
        )
        return
    corpus_label = "configured global memory corpus" if root_filtered else "global memory corpus"
    _check(
        checks,
        "cm_global_corpus",
        "ok",
        f"Indexed {corpus_label}: {available}/{indexed} files are available to default retrieval.",
    )
    _check_outside_global_root_rows(
        checks,
        outside_indexed=outside_indexed,
        outside_available=outside_available,
        outside_instruction_grade=outside_instruction_grade,
    )
    if available <= 0:
        return
    authority_status = "ok" if instruction_grade > 0 else "info"
    authority_message = (
        f"Instruction-grade global memory: {instruction_grade}/{available} default-available files are confirmed for instruction use."
        if instruction_grade > 0
        else "Global memory is available only as evidence-only or unconfirmed files; confirm reviewed files before treating global memory as instruction."
    )
    _check(checks, "cm_global_authority", authority_status, authority_message)


def _check_outside_global_root_rows(
    checks: list[dict[str, Any]],
    *,
    outside_indexed: int,
    outside_available: int,
    outside_instruction_grade: int,
) -> None:
    if outside_indexed <= 0:
        return
    status = "warning" if outside_available > 0 or outside_instruction_grade > 0 else "info"
    _check(
        checks,
        "cm_global_corpus_outside_root",
        status,
        "Indexed global memory includes "
        f"{outside_indexed} row(s) outside the configured global root "
        f"({outside_available} default-available, {outside_instruction_grade} instruction-grade). "
        "Review/reindex the configured global root before treating outside-root rows as active global memory.",
        {
            "outside_indexed_count": outside_indexed,
            "outside_available_count": outside_available,
            "outside_instruction_grade_count": outside_instruction_grade,
        },
    )


def _check_global_review_queue(
    checks: list[dict[str, Any]],
    *,
    global_root: str,
    db_path: str,
    recommendations: list[dict[str, str]] | None = None,
) -> None:
    root = str(global_root or "").strip()
    if not root:
        _check(
            checks,
            "cm_global_review_queue",
            "info",
            "Global review queue unavailable: no global memory root is configured for Codex project memory.",
        )
        return
    try:
        from .memory_global_review import memory_global_review_pending

        result = memory_global_review_pending(target_root=root, db_path=db_path, limit=0)
    except Exception as exc:
        _check(
            checks,
            "cm_global_review_queue",
            "info",
            "Global review queue unavailable: review receipt could not be built.",
            {"exception": exc.__class__.__name__},
        )
        return
    if not result.get("ok"):
        _check(
            checks,
            "cm_global_review_queue",
            "info",
            f"Global review queue unavailable: {result.get('error', 'unknown error')}.",
        )
        return

    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    pending_count = int(result.get("pending_count") or 0)
    matching_count = int(result.get("matching_count") or pending_count)
    reason_counts = summary.get("reason_counts") if isinstance(summary, Mapping) else {}
    if not isinstance(reason_counts, Mapping):
        reason_counts = {}
    confirm_guard_blocked_count = int(summary.get("confirm_guard_blocked_count") or 0)
    confirm_guard_finding_count = int(summary.get("confirm_guard_finding_count") or 0)
    details = {
        "pending_count": pending_count,
        "matching_count": matching_count,
        "reason_counts": dict(sorted((str(key), int(value or 0)) for key, value in reason_counts.items())),
        "confirm_guard_blocked_count": confirm_guard_blocked_count,
        "confirm_guard_finding_count": confirm_guard_finding_count,
        "global_root_provenance": str(result.get("global_root_provenance") or ""),
    }
    if recommendations is not None:
        recommendations.extend(
            item
            for item in (result.get("recommendations") or [])
            if isinstance(item, dict)
        )
    if pending_count <= 0:
        _check(checks, "cm_global_review_queue", "ok", "Global review queue is clear.", details)
        return

    reason_text = _reason_count_text(reason_counts)
    guard_text = (
        f"; confirm guard blocked files={confirm_guard_blocked_count}, findings={confirm_guard_finding_count}"
        if confirm_guard_blocked_count or confirm_guard_finding_count
        else ""
    )
    status = "warning" if confirm_guard_blocked_count else "info"
    _check(
        checks,
        "cm_global_review_queue",
        status,
        f"Global review queue has {pending_count} file(s) needing review"
        f" ({matching_count} matching current filters); reasons: {reason_text}{guard_text}.",
        details,
    )


def _reason_count_text(reason_counts: Mapping[str, Any]) -> str:
    parts = [
        f"{key}={int(value or 0)}"
        for key, value in sorted((str(key), value) for key, value in reason_counts.items())
    ]
    return ", ".join(parts) if parts else "none"


def inspect_codex_context_traces(
    db_path: str | Path | None = None,
    *,
    limit: int = 10,
    real_only: bool = False,
    delivery_kinds: list[str] | tuple[str, ...] | None = None,
    since: str = "",
) -> dict[str, Any]:
    """Return recent Codex context/delivery traces without prompt or memory text."""
    db = _resolve_context_trace_db_path(db_path)
    db_provenance = "user_supplied" if db_path else "fallback"
    max_items = max(0, min(int(limit), 200))
    since_text = str(since or "").strip()
    since_dt = _parse_codex_trace_since(since_text) if since_text else None
    since_error = bool(since_text and since_dt is None)
    kind_filters, unsupported_kinds = _normalize_codex_delivery_kind_filters(delivery_kinds or [])
    result: dict[str, Any] = {
        "ok": True,
        "db": _diagnostic_path_payload(db, provenance=db_provenance),
        "db_exists": db.exists(),
        "initialized": False,
        "filters": {
            "real_only": bool(real_only),
            "delivery_kinds": kind_filters,
            "since": since_text,
            "since_utc": _format_trace_filter_utc(since_dt) if since_dt else "",
        },
        "returned_count": 0,
        "matching_count": 0,
        "scanned_trace_count": 0,
        "truncated": False,
        "summary": _empty_codex_context_trace_summary(),
        "traces": [],
        "latest_delivery_attempt": None,
        "latest_prompt_construction_trace": None,
        "latest_returned_prompt_construction_trace": None,
        "recommendations": [],
        "prompt_boundary": (
            "MCP tools are on-demand; automatic prompt evidence requires codex context, "
            "codex exec, or another hook/harness. codex context and codex exec --dry-run "
            "are prompt construction, not real Codex subprocess delivery."
        ),
    }
    if unsupported_kinds:
        return _with_codex_context_trace_recommendations({
            **result,
            "ok": False,
            "error": "unsupported codex trace delivery kind filter",
            "unsupported_delivery_kinds": unsupported_kinds,
            "supported_delivery_kinds": sorted(CODEX_CONTEXT_DELIVERY_KIND_ALIASES),
        })
    if since_error:
        return _with_codex_context_trace_recommendations({
            **result,
            "ok": False,
            "error": "invalid codex trace --since timestamp",
            "hint": "Use YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, or an ISO timestamp with timezone such as 2026-06-10T21:00:00Z.",
        })
    if not db.exists():
        return _with_codex_context_trace_recommendations(result)

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db))
        if not _sqlite_table_exists(conn, "memory_recall_traces"):
            return _with_codex_context_trace_recommendations(result)
        result["initialized"] = True
        fetch_limit = 500 if (real_only or since_dt is not None or kind_filters) else max_items + 1
        rows = _fetch_recent_codex_context_trace_rows(conn, limit=fetch_limit)
        result["scanned_trace_count"] = len(rows)
        events_by_trace = _fetch_codex_context_trace_events(
            conn,
            [str(row[1] or "") for row in rows],
        )
        scope_counts_by_trace = _fetch_codex_context_trace_item_scopes(
            conn,
            [str(row[1] or "") for row in rows],
        )
    except sqlite3.Error as exc:
        return _with_codex_context_trace_recommendations({
            **result,
            "ok": False,
            "error": "codex context traces could not be queried",
            "exception": exc.__class__.__name__,
        })
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    traces: list[dict[str, Any]] = []
    latest_delivery_attempt: dict[str, Any] | None = None
    latest_prompt_construction: dict[str, Any] | None = None
    latest_returned_prompt_construction: dict[str, Any] | None = None
    matching_count = 0
    for row in rows:
        if since_dt is not None:
            created_at_dt = _parse_diagnostic_timestamp(row[2])
            if created_at_dt is None or created_at_dt < since_dt:
                continue
        trace_id = str(row[1] or "")
        trace = _codex_context_trace_receipt(
            row,
            events_by_trace.get(trace_id, []),
            returned_scope_counts=scope_counts_by_trace.get(trace_id, {}),
        )
        if latest_delivery_attempt is None and str(trace.get("delivery_kind") or "") in {
            "exec_delivery_failed",
            "real_exec_delivery",
        }:
            latest_delivery_attempt = _codex_context_trace_attempt_payload(trace)
        if str(trace.get("delivery_kind") or "") == "prompt_construction":
            if latest_prompt_construction is None:
                latest_prompt_construction = _codex_context_trace_reference_payload(trace)
            if latest_returned_prompt_construction is None and trace.get("returned_evidence"):
                latest_returned_prompt_construction = _codex_context_trace_reference_payload(trace)
        if real_only and not trace.get("delivered_to_codex_exec"):
            continue
        if kind_filters and str(trace.get("delivery_kind") or "") not in kind_filters:
            continue
        matching_count += 1
        if len(traces) >= max_items:
            continue
        traces.append(trace)

    result["matching_count"] = matching_count
    result["returned_count"] = len(traces)
    result["truncated"] = matching_count > len(traces)
    result["summary"] = _codex_context_trace_summary(traces)
    result["traces"] = traces
    result["latest_delivery_attempt"] = latest_delivery_attempt
    result["latest_prompt_construction_trace"] = latest_prompt_construction
    result["latest_returned_prompt_construction_trace"] = latest_returned_prompt_construction
    return _with_codex_context_trace_recommendations(result)


def _with_codex_context_trace_recommendations(result: dict[str, Any]) -> dict[str, Any]:
    result["recommendations"] = _codex_context_trace_recommendations(result)
    return result


def _normalize_codex_delivery_kind_filters(values: list[str] | tuple[str, ...]) -> tuple[list[str], list[str]]:
    selected: list[str] = []
    unsupported: list[str] = []
    for value in values:
        text = str(value or "").strip().lower().replace("-", "_")
        if not text:
            continue
        normalized = CODEX_CONTEXT_DELIVERY_KIND_ALIASES.get(text)
        if not normalized:
            unsupported.append(str(value))
            continue
        if normalized not in selected:
            selected.append(normalized)
    return selected, unsupported


def _codex_context_trace_recommendations(result: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return body-safe next actions for Codex context trace findings."""
    recommendations: list[dict[str, str]] = []
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    filters = result.get("filters") if isinstance(result.get("filters"), Mapping) else {}
    real_only = bool(filters.get("real_only"))
    kind_filters = {
        str(kind)
        for kind in (filters.get("delivery_kinds") or [])
        if str(kind)
    }
    matching_count = int(result.get("matching_count") or 0)
    returned_count = int(result.get("returned_count") or 0)
    real_delivery_count = int(summary.get("real_delivery_count") or 0)
    failed_delivery_count = int(summary.get("failed_delivery_count") or 0)
    returned_trace_count = int(summary.get("returned_trace_count") or 0)
    failed_delivery_needs_attention = _failed_delivery_needs_attention(result)
    prefer_global_scope = _latest_prompt_construction_prefers_global_scope(result)
    latest_attempt_kind = _latest_delivery_attempt_kind(result)
    has_real_delivery = real_delivery_count > 0 or latest_attempt_kind == "real_exec_delivery"

    if not result.get("db_exists"):
        recommendations.append(
            {
                "code": "trace_db_missing",
                "message": "No recall trace database exists yet; run Codex doctor after the sidecar has started.",
                "command": "chimera-memory codex doctor",
            }
        )
        return recommendations

    if real_only and matching_count <= 0:
        if latest_attempt_kind == "exec_delivery_failed":
            recommendations.extend(_failed_codex_delivery_recommendations())
        recommendations.extend(_no_real_codex_delivery_recommendations(prefer_global_scope=prefer_global_scope))
        return recommendations
    if kind_filters and matching_count <= 0:
        if "real_exec_delivery" in kind_filters:
            if latest_attempt_kind == "exec_delivery_failed":
                recommendations.extend(_failed_codex_delivery_recommendations())
            recommendations.extend(_no_real_codex_delivery_recommendations(prefer_global_scope=prefer_global_scope))
        return recommendations

    if (
        failed_delivery_count > 0
        and failed_delivery_needs_attention
        and latest_attempt_kind == "exec_delivery_failed"
    ):
        recommendations.extend(_failed_codex_delivery_recommendations())

    if returned_count > 0 and not has_real_delivery:
        recommendations.extend(_no_real_codex_delivery_recommendations(prefer_global_scope=prefer_global_scope))
    elif returned_count <= 0 and not real_only:
        recommendations.append(
            {
                "code": "build_context_trace",
                "message": "No Codex context traces are in the selected window; first prove prompt construction without printing memory bodies.",
                "command": "chimera-memory codex context --prompt \"<TASK>\" --receipt-only --json",
            }
        )

    if returned_count > 0 and returned_trace_count <= 0:
        recommendations.append(
            {
                "code": "adjust_context_query",
                "message": "The selected traces did not return memory evidence; try a task-shaped prompt with the relevant project/global terms.",
                "command": "chimera-memory codex context --prompt \"<TASK>\" --receipt-only --json",
            }
        )
    return recommendations


def _no_real_codex_delivery_recommendations(*, prefer_global_scope: bool = False) -> list[dict[str, str]]:
    scope_arg = " --scope global" if prefer_global_scope else ""
    scope_message = (
        " global"
        if prefer_global_scope
        else ""
    )
    return [
        {
            "code": "verify_wrapper_prompt_construction",
            "message": f"Verify the Codex wrapper can build{scope_message} memory context without exposing the wrapped prompt or memory bodies.",
            "command": f"chimera-memory codex exec{scope_arg} --prompt-file <PROMPT_FILE> --receipt-only --dry-run --json",
        },
        {
            "code": "deliver_wrapper_prompt",
            "message": f"Run the wrapper without --dry-run when you want{scope_message} memory context delivered into a real Codex subprocess turn.",
            "command": f"chimera-memory codex exec{scope_arg} --prompt-file <PROMPT_FILE>",
        },
        {
            "code": "codex_desktop_boundary",
            "message": "Codex Desktop MCP tools are on-demand; MCP availability alone does not automatically prepend memory to ordinary chat turns.",
            "command": "",
        },
    ]


def _latest_prompt_construction_prefers_global_scope(result: Mapping[str, Any]) -> bool:
    trace = result.get("latest_returned_prompt_construction_trace")
    if not isinstance(trace, Mapping):
        return False
    return _trace_returned_only_global_memory(trace)


def _trace_returned_only_global_memory(trace: Mapping[str, Any]) -> bool:
    scope_counts = trace.get("returned_memory_scopes")
    if not isinstance(scope_counts, Mapping) or not scope_counts:
        return False
    active_scopes = {
        str(scope)
        for scope, count in scope_counts.items()
        if int(count or 0) > 0
    }
    return active_scopes == {"global"}


def _failed_codex_delivery_recommendations() -> list[dict[str, str]]:
    return [
        {
            "code": "fix_codex_exec_launch",
            "message": "A wrapped Codex exec attempt failed before prompt delivery; verify the Codex executable and retry with --codex-bin or CHIMERA_MEMORY_CODEX_BIN if needed.",
            "command": "codex --version",
        }
    ]


def _codex_context_delivery_recommendations(delivery: Mapping[str, Any]) -> list[dict[str, str]]:
    prefer_global_scope = _global_context_smoke_returned(delivery)
    if _latest_failed_wrapper_is_current(delivery):
        return [
            *_failed_codex_delivery_recommendations(),
            *_no_real_codex_delivery_recommendations(prefer_global_scope=prefer_global_scope),
        ]
    latest_real = delivery.get("latest_real_wrapper_trace")
    if isinstance(latest_real, Mapping) and int(latest_real.get("returned_count") or 0) <= 0:
        scope_arg = " --scope global" if prefer_global_scope else ""
        scope_text = " global" if prefer_global_scope else ""
        return [
            {
                "code": "latest_real_delivery_no_evidence",
                "message": (
                    f"The latest real Codex exec delivery ran but returned no{scope_text} memory evidence; "
                    "try a task-shaped prompt with the relevant project/global terms before concluding CM influenced that turn."
                ),
                "command": f"chimera-memory codex context{scope_arg} --prompt \"<TASK>\" --receipt-only --json",
            }
        ]
    if not delivery.get("latest_real_wrapper_returned_trace"):
        return _no_real_codex_delivery_recommendations(prefer_global_scope=prefer_global_scope)
    recency = delivery.get("latest_real_wrapper_delivery_recency")
    if isinstance(recency, Mapping) and not recency.get("recent"):
        scope_arg = " --scope global" if prefer_global_scope else ""
        return [
            {
                "code": "refresh_real_delivery",
                "message": "The latest real Codex exec delivery is outside the recency window; run a fresh wrapped Codex turn.",
                "command": f"chimera-memory codex exec{scope_arg} --prompt-file <PROMPT_FILE>",
            }
        ]
    return []


def _global_context_smoke_returned(delivery: Mapping[str, Any]) -> bool:
    smoke = delivery.get("global_context_smoke")
    return isinstance(smoke, Mapping) and bool(smoke.get("injected")) and int(smoke.get("returned_count") or 0) > 0


def _check_real_wrapper_effectiveness(
    checks: list[dict[str, Any]],
    delivery: Mapping[str, Any] | None,
) -> None:
    if not isinstance(delivery, Mapping):
        return
    latest_real = delivery.get("latest_real_wrapper_trace")
    if not isinstance(latest_real, Mapping) or int(latest_real.get("returned_count") or 0) > 0:
        return
    smoke = delivery.get("global_context_smoke")
    if not _global_context_smoke_returned(delivery) or not isinstance(smoke, Mapping):
        return
    _check(
        checks,
        "cm_real_wrapper_effectiveness",
        "warning",
        "Latest real Codex exec delivery returned no memory evidence even though the Codex global context smoke retrieved memory; that real turn was not memory-augmented by ChimeraMemory.",
        {
            "latest_trace_id": str(latest_real.get("trace_id") or ""),
            "smoke_returned_count": int(smoke.get("returned_count") or 0),
        },
    )


def _failed_delivery_needs_attention(result: Mapping[str, Any]) -> bool:
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    if int(summary.get("failed_delivery_count") or 0) <= 0:
        return False
    if int(summary.get("real_delivery_count") or 0) <= 0:
        return True
    traces = result.get("traces") if isinstance(result.get("traces"), list) else []
    for trace in traces:
        if not isinstance(trace, Mapping):
            continue
        kind = str(trace.get("delivery_kind") or "")
        if kind in {"exec_delivery_failed", "real_exec_delivery"}:
            return kind == "exec_delivery_failed"
    return False


def _latest_delivery_attempt_kind(result: Mapping[str, Any]) -> str:
    attempt = result.get("latest_delivery_attempt")
    if not isinstance(attempt, Mapping):
        return ""
    return str(attempt.get("delivery_kind") or "")


def _latest_failed_wrapper_is_current(delivery: Mapping[str, Any]) -> bool:
    failed = delivery.get("latest_failed_wrapper_trace")
    if not isinstance(failed, Mapping):
        return False
    real = delivery.get("latest_real_wrapper_trace")
    return _failed_wrapper_payload_is_newer(failed, real if isinstance(real, Mapping) else None)


def _failed_wrapper_payload_is_newer(
    failed: Mapping[str, Any] | None,
    real: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(failed, Mapping):
        return False
    if not isinstance(real, Mapping):
        return True
    failed_dt = _parse_diagnostic_timestamp(failed.get("created_at"))
    real_dt = _parse_diagnostic_timestamp(real.get("created_at"))
    if failed_dt is None:
        return False
    if real_dt is None:
        return True
    return failed_dt > real_dt


def _parse_codex_trace_since(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        local_tz = datetime.now().astimezone().tzinfo
        try:
            return datetime.fromisoformat(text).replace(tzinfo=local_tz).astimezone(timezone.utc)
        except ValueError:
            return None
    return _parse_diagnostic_timestamp(text)


def _format_trace_filter_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve_context_trace_db_path(db_path: str | Path | None) -> Path:
    if db_path:
        return Path(os.path.expandvars(os.path.expanduser(str(db_path)))).resolve()
    from .server import get_default_db_path

    return Path(get_default_db_path()).resolve()


def _diagnostic_path_payload(path: Path, *, provenance: str) -> dict[str, str]:
    text = str(path)
    return {
        "name": path.name,
        "provenance": provenance,
        "fingerprint": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    }


def _fetch_recent_codex_context_trace_rows(
    conn: sqlite3.Connection,
    *,
    limit: int,
) -> list[tuple[Any, ...]]:
    if limit <= 0:
        return []
    columns = _sqlite_table_columns(conn, "memory_recall_traces")
    row_id_expr = "id" if "id" in columns else "rowid"
    request_payload_expr = "request_payload" if "request_payload" in columns else "'' AS request_payload"
    response_policy_expr = "response_policy" if "response_policy" in columns else "'' AS response_policy"
    return conn.execute(
        f"""
        SELECT {row_id_expr}, trace_id, created_at, tool_name,
               requested_limit, result_count, returned_count,
               {request_payload_expr}, {response_policy_expr}
        FROM memory_recall_traces
        WHERE tool_name IN ('memory_context_pack', 'codex_transcript_context')
        ORDER BY created_at DESC, {row_id_expr} DESC
        LIMIT ?
        """,
        (max(0, min(int(limit), 500)),),
    ).fetchall()


def _fetch_codex_context_trace_events(
    conn: sqlite3.Connection,
    trace_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    selected_trace_ids = sorted({trace_id for trace_id in trace_ids if trace_id})
    if not selected_trace_ids or not _sqlite_table_exists(conn, "memory_audit_events"):
        return {}
    placeholders = ", ".join("?" for _ in selected_trace_ids)
    rows = conn.execute(
        f"""
        SELECT trace_id, created_at, event_type, actor, target_kind, payload
        FROM memory_audit_events
        WHERE trace_id IN ({placeholders})
        ORDER BY created_at DESC, id DESC
        """,
        selected_trace_ids,
    ).fetchall()
    events_by_trace: dict[str, list[dict[str, Any]]] = {}
    for trace_id, created_at, event_type, actor, target_kind, payload_text in rows:
        trace_text = str(trace_id or "")
        if not trace_text:
            continue
        events_by_trace.setdefault(trace_text, []).append(
            {
                "created_at": str(created_at or ""),
                "event_type": str(event_type or ""),
                "actor": str(actor or ""),
                "target_kind": str(target_kind or ""),
                "payload_text": str(payload_text or ""),
            }
        )
    return events_by_trace


def _fetch_codex_context_trace_item_scopes(
    conn: sqlite3.Connection,
    trace_ids: list[str],
) -> dict[str, dict[str, int]]:
    selected_trace_ids = sorted({trace_id for trace_id in trace_ids if trace_id})
    if (
        not selected_trace_ids
        or not _sqlite_table_exists(conn, "memory_recall_items")
        or not _sqlite_table_exists(conn, "memory_files")
    ):
        return {}
    placeholders = ", ".join("?" for _ in selected_trace_ids)
    try:
        rows = conn.execute(
            f"""
            SELECT i.trace_id,
                   COALESCE(
                       NULLIF(f.memory_scope, ''),
                       CASE
                           WHEN COALESCE(i.persona, '') = 'global' THEN 'global'
                           WHEN COALESCE(i.persona, '') LIKE 'project:%' THEN 'project'
                           WHEN COALESCE(i.persona, '') != '' THEN 'persona'
                           ELSE 'unknown'
                       END
                   ) AS returned_scope,
                   COUNT(*)
            FROM memory_recall_items i
            LEFT JOIN memory_files f ON f.id = i.file_id
            WHERE i.trace_id IN ({placeholders})
              AND COALESCE(i.returned, 0) = 1
            GROUP BY i.trace_id, returned_scope
            """,
            selected_trace_ids,
        ).fetchall()
    except sqlite3.Error:
        return {}
    counts_by_trace: dict[str, dict[str, int]] = {}
    for trace_id, scope, count in rows:
        trace_text = str(trace_id or "")
        if not trace_text:
            continue
        scope_text = str(scope or "unknown").strip().lower() or "unknown"
        if scope_text not in {"global", "project", "persona", "unknown"}:
            scope_text = "unknown"
        counts_by_trace.setdefault(trace_text, {})[scope_text] = int(count or 0)
    return counts_by_trace


def _codex_context_trace_receipt(
    row: tuple[Any, ...],
    events: list[dict[str, Any]],
    *,
    returned_scope_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    (
        _row_id,
        trace_id,
        created_at,
        tool_name,
        requested_limit,
        result_count,
        returned_count,
        request_payload,
        response_policy,
    ) = row
    context_events = [
        event
        for event in events
        if str(event.get("event_type") or "") in CODEX_CONTEXT_TRACE_EVENT_TYPES
    ]
    event_types = [str(event.get("event_type") or "") for event in context_events if event.get("event_type")]
    actors = sorted({str(event.get("actor") or "") for event in context_events if event.get("actor")})
    delivery_event_types = sorted({event_type for event_type in event_types if event_type.startswith("codex_")})
    delivered_to_codex_exec = any(
        str(event.get("event_type") or "") == "codex_prompt_delivered"
        and str(event.get("actor") or "") == "codex-context"
        for event in context_events
    )
    delivery_failed = any(
        str(event.get("event_type") or "") == "codex_prompt_delivery_failed"
        and str(event.get("actor") or "") == "codex-context"
        for event in context_events
    )
    delivery_mode = _context_trace_delivery_mode(
        *(event.get("payload_text") for event in context_events),
        request_payload,
        response_policy,
    )
    delivery_kind = _codex_context_delivery_kind(
        delivery_mode=delivery_mode,
        delivered_to_codex_exec=delivered_to_codex_exec,
        delivery_failed=delivery_failed,
        actors=actors,
    )
    request_metadata = _context_trace_request_metadata(request_payload)
    receipt = {
        "trace_id": str(trace_id or ""),
        "created_at": str(created_at or ""),
        "created_at_display": format_diagnostic_timestamp(created_at),
        "tool_name": str(tool_name or ""),
        "requested_limit": int(requested_limit or 0),
        "candidate_count": int(result_count or 0),
        "returned_count": int(returned_count or 0),
        "returned_evidence": int(returned_count or 0) > 0,
        "delivery_mode": delivery_mode,
        "delivery_kind": delivery_kind,
        "delivered_to_codex_exec": delivered_to_codex_exec,
        "delivery_failed": delivery_failed,
        "actors": actors,
        "event_types": sorted(set(event_types)),
        "delivery_event_types": delivery_event_types,
        "event_count": len(context_events),
    }
    receipt.update(request_metadata)
    scope_counts = {
        str(scope): int(count or 0)
        for scope, count in sorted((returned_scope_counts or {}).items())
        if int(count or 0) > 0
    }
    if scope_counts:
        receipt["returned_memory_scopes"] = scope_counts
    return receipt


def _context_trace_request_metadata(request_payload: object) -> dict[str, Any]:
    payload = _json_mapping(request_payload)
    metadata: dict[str, Any] = {}
    scope = str(payload.get("scope") or "").strip().lower().replace("-", "_")
    if scope in {"auto", "project", "global", "all"}:
        metadata["request_scope"] = scope
    if "project_id" in payload:
        metadata["project_id_supplied"] = bool(str(payload.get("project_id") or "").strip())
    if "project_root_supplied" in payload:
        metadata["project_root_supplied"] = bool(payload.get("project_root_supplied"))
    return metadata


def _codex_context_trace_reference_payload(trace: Mapping[str, Any]) -> dict[str, Any]:
    payload = _codex_context_trace_attempt_payload(trace)
    for key in ("request_scope", "project_id_supplied", "project_root_supplied", "returned_memory_scopes"):
        if key in trace:
            payload[key] = trace[key]
    return payload


def _codex_context_trace_attempt_payload(trace: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": str(trace.get("trace_id") or ""),
        "created_at": str(trace.get("created_at") or ""),
        "created_at_display": str(trace.get("created_at_display") or ""),
        "tool_name": str(trace.get("tool_name") or ""),
        "delivery_kind": str(trace.get("delivery_kind") or ""),
        "delivery_mode": str(trace.get("delivery_mode") or ""),
        "returned_count": int(trace.get("returned_count") or 0),
        "returned_evidence": bool(trace.get("returned_evidence")),
    }


def _codex_context_delivery_kind(
    *,
    delivery_mode: str,
    delivered_to_codex_exec: bool,
    delivery_failed: bool,
    actors: list[str],
) -> str:
    if delivered_to_codex_exec:
        return "real_exec_delivery"
    if delivery_failed:
        return "exec_delivery_failed"
    if delivery_mode == "diagnostic_smoke":
        return "diagnostic_smoke"
    if "codex-context" in actors or delivery_mode in {"context_only", "exec_dry_run"}:
        return "prompt_construction"
    return "context_trace"


def _empty_codex_context_trace_summary() -> dict[str, int]:
    return {
        "trace_count": 0,
        "returned_trace_count": 0,
        "real_delivery_count": 0,
        "real_delivery_returned_count": 0,
        "failed_delivery_count": 0,
        "failed_delivery_returned_count": 0,
        "prompt_construction_count": 0,
        "diagnostic_smoke_count": 0,
        "context_trace_count": 0,
    }


def _codex_context_trace_summary(traces: list[dict[str, Any]]) -> dict[str, int]:
    summary = _empty_codex_context_trace_summary()
    summary["trace_count"] = len(traces)
    for trace in traces:
        if trace.get("returned_evidence"):
            summary["returned_trace_count"] += 1
        kind = str(trace.get("delivery_kind") or "")
        if kind == "real_exec_delivery":
            summary["real_delivery_count"] += 1
            if trace.get("returned_evidence"):
                summary["real_delivery_returned_count"] += 1
        elif kind == "exec_delivery_failed":
            summary["failed_delivery_count"] += 1
            if trace.get("returned_evidence"):
                summary["failed_delivery_returned_count"] += 1
        elif kind == "prompt_construction":
            summary["prompt_construction_count"] += 1
        elif kind == "diagnostic_smoke":
            summary["diagnostic_smoke_count"] += 1
        else:
            summary["context_trace_count"] += 1
    return summary


def _sqlite_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _check_latest_context_traces(
    checks: list[dict[str, Any]],
    db_path: str,
    *,
    delivery: dict[str, Any] | None = None,
) -> None:
    if not db_path:
        _check(checks, "cm_context_trace", "info", "CM context trace unavailable: transcript DB path is not resolved.")
        return
    expanded = Path(os.path.expandvars(os.path.expanduser(db_path)))
    if not expanded.exists():
        _check(checks, "cm_context_trace", "info", "CM context trace unavailable: transcript DB does not exist yet.")
        return
    conn = None
    try:
        conn = sqlite3.connect(str(expanded))
        latest = conn.execute(
            """
            SELECT trace_id, created_at, tool_name, requested_limit, result_count, returned_count
            FROM memory_recall_traces
            WHERE tool_name IN ('memory_context_pack', 'codex_transcript_context')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        latest_returned = conn.execute(
            """
            SELECT trace_id, created_at, tool_name, requested_limit, result_count, returned_count
            FROM memory_recall_traces
            WHERE tool_name IN ('memory_context_pack', 'codex_transcript_context')
              AND returned_count > 0
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        latest_codex_context = None
        latest_codex_context_returned = None
        latest_wrapper = None
        latest_wrapper_returned = None
        latest_wrapper_failed = None
        has_audit_events = _sqlite_table_exists(conn, "memory_audit_events")
        if has_audit_events:
            latest_codex_context = _latest_context_trace_for_actor(conn, actor="codex-context")
            latest_codex_context_returned = _latest_context_trace_for_actor(
                conn,
                actor="codex-context",
                returned_only=True,
            )
            latest_wrapper = _latest_context_trace_for_actor(
                conn,
                actor="codex-context",
                event_types={"codex_prompt_delivered"},
            )
            latest_wrapper_returned = _latest_context_trace_for_actor(
                conn,
                actor="codex-context",
                returned_only=True,
                event_types={"codex_prompt_delivered"},
            )
            latest_wrapper_failed = _latest_context_trace_for_actor(
                conn,
                actor="codex-context",
                event_types={"codex_prompt_delivery_failed"},
            )
    except sqlite3.Error:
        _check(checks, "cm_context_trace", "info", "CM context trace unavailable: recall trace table is not initialized yet.")
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    if not latest:
        _check(checks, "cm_context_trace", "info", "No CM context trace has been recorded yet.")
        return
    if delivery is not None:
        delivery["latest_any_trace"] = _context_trace_payload(latest, diagnostic_scope="generic")
        delivery["latest_any_returned_trace"] = (
            _context_trace_payload(latest_returned, diagnostic_scope="generic") if latest_returned else None
        )
        delivery["latest_trace"] = (
            _context_trace_payload(latest_codex_context, diagnostic_scope="codex")
            if latest_codex_context
            else _context_trace_payload(latest, diagnostic_scope="legacy" if not has_audit_events else "generic")
        )
        delivery["latest_returned_trace"] = (
            _context_trace_payload(latest_codex_context_returned, diagnostic_scope="codex")
            if latest_codex_context_returned
            else _context_trace_payload(
                latest_returned,
                diagnostic_scope="legacy" if not has_audit_events else "generic",
            )
            if latest_returned
            else None
        )
        delivery["latest_codex_context_trace"] = (
            _context_trace_payload(latest_codex_context, diagnostic_scope="codex") if latest_codex_context else None
        )
        delivery["latest_codex_context_returned_trace"] = (
            _context_trace_payload(latest_codex_context_returned, diagnostic_scope="codex")
            if latest_codex_context_returned
            else None
        )
        delivery["latest_real_wrapper_trace"] = (
            _context_trace_payload(latest_wrapper, diagnostic_scope="codex") if latest_wrapper else None
        )
        delivery["latest_real_wrapper_returned_trace"] = (
            _context_trace_payload(latest_wrapper_returned, diagnostic_scope="codex") if latest_wrapper_returned else None
        )
        delivery["latest_failed_wrapper_trace"] = (
            _context_trace_payload(latest_wrapper_failed, diagnostic_scope="codex") if latest_wrapper_failed else None
        )
    if not has_audit_events:
        _check(checks, "cm_context_trace", "ok", _context_trace_message("Latest CM context trace", latest))
    elif latest_codex_context:
        _check(
            checks,
            "cm_context_trace",
            "ok",
            _context_trace_message("Latest Codex-owned CM context trace", latest_codex_context),
        )
    else:
        _check(
            checks,
            "cm_context_trace",
            "info",
            _context_trace_message("Latest generic CM context trace is not Codex-owned", latest)
            + " It does not prove Codex prompt-context readiness.",
        )
    if not has_audit_events and latest_returned:
        _check(
            checks,
            "cm_context_returned",
            "ok",
            _context_trace_message("Latest returned CM context", latest_returned),
        )
    elif latest_codex_context_returned:
        _check(
            checks,
            "cm_context_returned",
            "ok",
            _context_trace_message("Latest returned Codex-owned CM context", latest_codex_context_returned),
        )
    elif latest_returned:
        _check(
            checks,
            "cm_context_returned",
            "info",
            _context_trace_message("Latest returned generic CM context is not Codex-owned", latest_returned)
            + " It does not prove Codex prompt-context readiness.",
        )
    else:
        _check(checks, "cm_context_returned", "info", "No CM context trace has returned evidence yet.")
    if latest_codex_context_returned:
        _check(
            checks,
            "cm_codex_context_builder",
            "ok",
            _context_trace_message("Latest Codex context builder trace", latest_codex_context_returned),
        )
    elif latest_codex_context:
        _check(
            checks,
            "cm_codex_context_builder",
            "info",
            _context_trace_message("Latest Codex context builder trace returned no evidence", latest_codex_context),
        )
    else:
        _check(
            checks,
            "cm_codex_context_builder",
            "info",
            "No Codex context builder trace has been recorded yet.",
        )
    if latest_wrapper:
        latest_wrapper_returned_count = int(latest_wrapper[5] or 0)
        if latest_wrapper_returned_count > 0:
            _check(
                checks,
                "cm_real_wrapper_delivery",
                "ok",
                _context_trace_message("Latest real Codex exec delivery", latest_wrapper),
            )
        else:
            _check(
                checks,
                "cm_real_wrapper_delivery",
                "info",
                _context_trace_message("Latest real Codex exec delivery trace returned no evidence", latest_wrapper),
            )
        _check_real_wrapper_delivery_recency(checks, latest_wrapper, delivery=delivery)
        if latest_wrapper_returned and latest_wrapper_returned[0] != latest_wrapper[0]:
            _check(
                checks,
                "cm_real_wrapper_returned",
                "ok",
                _context_trace_message("Latest returned real Codex exec delivery", latest_wrapper_returned),
            )
    elif latest_wrapper_returned:
        _check(
            checks,
            "cm_real_wrapper_delivery",
            "ok",
            _context_trace_message("Latest real Codex exec delivery", latest_wrapper_returned),
        )
        _check_real_wrapper_delivery_recency(checks, latest_wrapper_returned, delivery=delivery)
    else:
        _check(
            checks,
            "cm_real_wrapper_delivery",
            "info",
            "No real Codex exec delivery event has been recorded yet; `chimera-memory codex context` and `chimera-memory codex exec --dry-run` only prove prompt construction.",
        )
    failed_wrapper_is_current = _failed_wrapper_payload_is_newer(
        _context_trace_payload(latest_wrapper_failed),
        _context_trace_payload(latest_wrapper),
    )
    if latest_wrapper_failed and failed_wrapper_is_current:
        _check(
            checks,
            "cm_wrapper_delivery_failure",
            "info",
            _context_trace_message("Latest Codex exec delivery attempt failed before prompt delivery", latest_wrapper_failed),
        )


def _check_real_wrapper_delivery_recency(
    checks: list[dict[str, Any]],
    row: tuple[Any, ...],
    *,
    delivery: dict[str, Any] | None = None,
) -> None:
    trace = _context_trace_payload(row)
    parsed = _parse_diagnostic_timestamp(trace.get("created_at") if trace else None)
    if parsed is None:
        if delivery is not None:
            delivery["latest_real_wrapper_delivery_recency"] = {
                "status": "info",
                "recent": False,
                "recent_after_seconds": REAL_WRAPPER_DELIVERY_RECENT_SECONDS,
            }
        _check(
            checks,
            "cm_real_wrapper_delivery_recency",
            "info",
            "Latest real Codex exec delivery timestamp could not be parsed.",
        )
        return
    age_seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    recent = age_seconds <= REAL_WRAPPER_DELIVERY_RECENT_SECONDS
    payload = {
        "status": "ok" if recent else "info",
        "recent": recent,
        "age_seconds": age_seconds,
        "recent_after_seconds": REAL_WRAPPER_DELIVERY_RECENT_SECONDS,
    }
    if delivery is not None:
        delivery["latest_real_wrapper_delivery_recency"] = payload
    if recent:
        _check(
            checks,
            "cm_real_wrapper_delivery_recency",
            "ok",
            f"Latest real Codex exec delivery is recent: {trace['created_at_display']}.",
            {"age_seconds": age_seconds, "recent_after_seconds": REAL_WRAPPER_DELIVERY_RECENT_SECONDS},
        )
        return
    _check(
        checks,
        "cm_real_wrapper_delivery_recency",
        "info",
        f"Latest real Codex exec delivery is older than the recency window: {trace['created_at_display']}. "
        "Run `chimera-memory codex exec` without --dry-run to deliver fresh prompt evidence to Codex.",
        {"age_seconds": age_seconds, "recent_after_seconds": REAL_WRAPPER_DELIVERY_RECENT_SECONDS},
    )


def _latest_context_trace_for_actor(
    conn: sqlite3.Connection,
    *,
    actor: str,
    returned_only: bool = False,
    event_types: set[str] | None = None,
    delivery_modes: set[str] | None = None,
) -> tuple[Any, ...] | None:
    returned_clause = "AND t.returned_count > 0" if returned_only else ""
    rows = conn.execute(
        f"""
        SELECT t.trace_id, t.created_at, t.tool_name, t.requested_limit,
               t.result_count, t.returned_count, a.actor, a.event_type,
               a.payload, t.request_payload, t.response_policy
        FROM memory_recall_traces t
        JOIN memory_audit_events a ON a.trace_id = t.trace_id
        WHERE t.tool_name IN ('memory_context_pack', 'codex_transcript_context')
          AND a.actor = ?
          {returned_clause}
        ORDER BY t.created_at DESC, t.id DESC
        LIMIT 100
        """,
        (actor,),
    ).fetchall()
    selected_event_types = set(event_types or ())
    selected_delivery_modes = {str(mode or "").strip().lower().replace("-", "_") for mode in (delivery_modes or set())}
    for row in rows:
        event_type = str(row[7] or "")
        if selected_event_types and event_type not in selected_event_types:
            continue
        delivery_mode = _context_trace_delivery_mode(row[8], row[9], row[10])
        if selected_delivery_modes and delivery_mode not in selected_delivery_modes:
            continue
        return (*row[:7], delivery_mode, event_type)
    return None


def _check_codex_global_context_smoke(
    checks: list[dict[str, Any]],
    db_path: str,
    *,
    global_root: str = "",
    delivery: dict[str, Any] | None = None,
    require_global_root: bool = False,
) -> None:
    if not db_path:
        _check(checks, "cm_global_context_smoke", "info", "Codex global context smoke skipped: transcript DB path is not resolved.")
        return
    expanded = Path(os.path.expandvars(os.path.expanduser(db_path)))
    if not expanded.exists():
        _check(checks, "cm_global_context_smoke", "info", "Codex global context smoke skipped: transcript DB does not exist yet.")
        return
    if require_global_root and _resolved_global_root(global_root) is None:
        if delivery is not None:
            delivery["global_context_smoke"] = {
                "status": "skipped",
                "reason": "global_root_missing",
                "returned_count": 0,
                "injected": False,
                "trace_written": False,
            }
        _check(
            checks,
            "cm_global_context_smoke",
            "warning",
            "Codex global context smoke skipped: CHIMERA_MEMORY_GLOBAL_ROOT is not configured for project memory.",
        )
        return

    source_conn: sqlite3.Connection | None = None
    conn: sqlite3.Connection | None = None
    try:
        source_conn = sqlite3.connect(str(expanded))
        conn = sqlite3.connect(":memory:")
        source_conn.backup(conn)
        _mask_outside_global_root_rows(conn, global_root=global_root)
        query = _global_context_smoke_query(conn)
        if not query:
            _check(
                checks,
                "cm_global_context_smoke",
                "info",
                "Codex global context smoke skipped: no default-available global memory metadata is indexed yet.",
            )
            return

        from .codex_context import build_codex_prompt_context

        result = build_codex_prompt_context(
            conn,
            prompt=query,
            scope="global",
            limit=3,
            token_budget=600,
            force=True,
            include_transcripts=False,
            delivery_mode="diagnostic_smoke",
        )
    except sqlite3.Error:
        _check(checks, "cm_global_context_smoke", "info", "Codex global context smoke unavailable: memory tables are not initialized yet.")
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if source_conn is not None:
            try:
                source_conn.close()
            except Exception:
                pass

    if not result.get("ok"):
        _check(
            checks,
            "cm_global_context_smoke",
            "warning",
            "Codex global context smoke failed before building a prompt wrapper.",
        )
        return

    returned_count = int(result.get("returned_count") or 0)
    if returned_count > 0 and result.get("injected"):
        if delivery is not None:
            delivery["global_context_smoke"] = {
                "status": "ok",
                "returned_count": returned_count,
                "injected": True,
                "trace_written": False,
            }
        _check(
            checks,
            "cm_global_context_smoke",
            "ok",
            f"Codex global context smoke returned {returned_count} memory card(s) through the prompt wrapper.",
            {"returned_count": returned_count},
        )
        return
    if delivery is not None:
        delivery["global_context_smoke"] = {
            "status": "warning",
            "returned_count": returned_count,
            "injected": bool(result.get("injected")),
            "trace_written": False,
        }
    _check(
        checks,
        "cm_global_context_smoke",
        "warning",
        "Codex global context smoke returned no prompt evidence even though default-available global memory metadata is indexed.",
        {"returned_count": returned_count},
    )


def _global_context_smoke_query(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT relative_path, fm_about, fm_type, fm_tags
        FROM memory_files
        WHERE COALESCE(memory_scope, '') = 'global'
          AND COALESCE(fm_exclude_from_default_search, 0) = 0
          AND COALESCE(fm_can_use_as_evidence, 1) = 1
          AND COALESCE(fm_sensitivity_tier, 'standard') <> 'restricted'
          AND COALESCE(fm_lifecycle_status, 'active') NOT IN ('disputed', 'rejected', 'superseded')
        ORDER BY COALESCE(fm_importance, 0) DESC, updated_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return ""
    relative_path, about, memory_type, tags_json = row
    terms: list[str] = []
    for value in (about, memory_type):
        text = str(value or "").strip()
        if text:
            terms.append(text)
    try:
        tags = json.loads(tags_json or "[]")
    except json.JSONDecodeError:
        tags = []
    if isinstance(tags, list):
        terms.extend(str(tag) for tag in tags[:6] if str(tag or "").strip())
    path_terms = re.sub(r"[^A-Za-z0-9]+", " ", str(relative_path or "")).strip()
    if path_terms:
        terms.append(path_terms)
    query = " ".join(" ".join(str(term).split()) for term in terms if str(term or "").strip())
    return query[:500].strip()


def _mask_outside_global_root_rows(conn: sqlite3.Connection, *, global_root: str = "") -> None:
    root = _resolved_global_root(global_root)
    if root is None:
        return
    try:
        rows = conn.execute(
            """
            SELECT id, path
            FROM memory_files
            WHERE COALESCE(memory_scope, '') = 'global'
            """
        ).fetchall()
    except sqlite3.Error:
        return
    outside_ids = [
        int(file_id)
        for file_id, path_text in rows
        if not _path_is_under_root(path_text, root)
    ]
    if not outside_ids:
        return
    placeholders = ",".join("?" for _ in outside_ids)
    conn.execute(
        f"UPDATE memory_files SET memory_scope = 'global_outside_root' WHERE id IN ({placeholders})",
        outside_ids,
    )


def _context_trace_message(prefix: str, row: tuple[Any, ...]) -> str:
    trace = _context_trace_payload(row)
    delivery_mode = str((trace or {}).get("delivery_mode") or "").strip()
    delivery_suffix = f"; delivery_mode={delivery_mode}" if delivery_mode else ""
    return (
        f"{prefix}: {trace['tool_name']} returned {trace['returned_count']}/"
        f"{trace['requested_limit']} requested at {trace['created_at_display']}; "
        f"candidate_count={trace['candidate_count']}{delivery_suffix}."
    )


def _context_trace_payload(
    row: tuple[Any, ...] | None,
    *,
    diagnostic_scope: str = "",
) -> dict[str, Any] | None:
    if row is None:
        return None
    trace_id, created_at, tool_name, requested_limit, result_count, returned_count, *rest = row
    actor = str(rest[0] or "") if rest else ""
    delivery_mode = str(rest[1] or "") if len(rest) > 1 else ""
    delivery_event_type = str(rest[2] or "") if len(rest) > 2 else ""
    payload = {
        "trace_id": str(trace_id or ""),
        "created_at": str(created_at or ""),
        "created_at_display": format_diagnostic_timestamp(created_at),
        "tool_name": str(tool_name or ""),
        "requested_limit": int(requested_limit or 0),
        "candidate_count": int(result_count or 0),
        "returned_count": int(returned_count or 0),
    }
    if actor:
        payload["actor"] = actor
    if delivery_mode:
        payload["delivery_mode"] = delivery_mode
    if delivery_event_type:
        payload["delivery_event_type"] = delivery_event_type
    selected_scope = str(diagnostic_scope or "").strip().lower().replace("-", "_")
    if selected_scope:
        payload["diagnostic_scope"] = selected_scope
    return payload


def _context_trace_delivery_mode(*payload_texts: object) -> str:
    for text in payload_texts:
        payload = _json_mapping(text)
        mode = str(payload.get("delivery_mode") or "").strip().lower().replace("-", "_")
        if mode:
            return mode
    return "legacy_unknown"


def _json_mapping(text: object) -> Mapping[str, Any]:
    if not text:
        return {}
    try:
        parsed = json.loads(str(text))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _check_prompt_context_boundary(checks: list[dict[str, Any]]) -> None:
    _check(
        checks,
        "codex_prompt_context",
        "info",
        "MCP tools are available on demand; automatic prompt evidence requires `chimera-memory codex context` or `chimera-memory codex exec`.",
    )
    if _command_resolves("chimera-memory"):
        _check(
            checks,
            "codex_wrapper_command",
            "info",
            "Wrapper command `chimera-memory` resolves on PATH for manual Codex prompt wrapping.",
            {"available": True},
        )
    else:
        _check(
            checks,
            "codex_wrapper_command",
            "info",
            "Wrapper command `chimera-memory` does not resolve on PATH; use the repo venv Python module command or install a shim before relying on plain `chimera-memory codex context`.",
            {"available": False},
        )


def _check_http_mcp_url(checks: list[dict[str, Any]], url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        _check(checks, "url", "error", "Server URL must be an http(s) MCP endpoint.")
        return
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        _check(checks, "url", "error", "Server URL contains an invalid port.")
        return

    host_label = f"{parsed.hostname}:{port}"
    _check(checks, "url", "ok", f"Server URL configured for shared HTTP MCP transport at {host_label}.")
    if not _is_local_mcp_host(parsed.hostname):
        _check(checks, "url_reachable", "info", "URL reachability was not checked for a non-local host.")
        return

    try:
        with socket.create_connection((parsed.hostname, port), timeout=0.5):
            pass
    except OSError:
        _check(checks, "url_reachable", "error", "No local MCP server is accepting connections at the configured host and port.")
        return
    _check(checks, "url_reachable", "ok", "Local MCP server is accepting TCP connections.")
    _check_http_listener_runtime(checks, parsed.hostname, port)
    _check_http_mcp_initialize(checks, url)


def _check_http_listener_runtime(checks: list[dict[str, Any]], host: str, port: int) -> None:
    status = _local_http_listener_runtime_status(host, port)
    if not status.get("supported"):
        _check(
            checks,
            "http_listener_runtime",
            "info",
            "Local HTTP listener owner runtime was not inspected on this platform.",
        )
        return
    if not status.get("ok"):
        _check(
            checks,
            "http_listener_runtime",
            "info",
            "Local HTTP listener owner runtime could not be inspected safely.",
        )
        return
    owner_count = int(status.get("owner_count") or 0)
    if owner_count <= 0:
        _check(
            checks,
            "http_listener_runtime",
            "info",
            "Local HTTP listener owner was not reported by the OS.",
        )
        return

    details = {
        "owner_count": owner_count,
        "matching_owner_count": int(status.get("matching_owner_count") or 0),
        "process_names": list(status.get("process_names") or []),
    }
    match_source_counts = status.get("match_source_counts")
    if isinstance(match_source_counts, Mapping) and match_source_counts:
        details["match_source_counts"] = dict(match_source_counts)
    mismatched_pids = [int(pid) for pid in (status.get("mismatched_pids") or []) if str(pid).isdigit()]
    if mismatched_pids:
        details["mismatched_pids"] = mismatched_pids
        _check(
            checks,
            "http_listener_runtime",
            "warning",
            "Local HTTP MCP listener is owned by a Python runtime that does not match this doctor runtime; restart the shared sidecar from the intended ChimeraMemory environment or rerun the startup script with -Replace after confirming the stale PID(s).",
            details,
        )
        return
    _check(
        checks,
        "http_listener_runtime",
        "ok",
        "Local HTTP MCP listener owner matches this doctor runtime.",
        details,
    )
    _check_http_listener_source_freshness(checks, status)


def _local_http_listener_runtime_status(host: str, port: int) -> dict[str, Any]:
    if os.name != "nt":
        return {"supported": False, "ok": False}
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return {"supported": False, "ok": False}

    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$owners = @(Get-NetTCPConnection -State Listen -LocalPort {int(port)} | Select-Object -ExpandProperty OwningProcess -Unique)
$rows = @()
foreach ($owner in $owners) {{
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$owner"
    if ($proc) {{
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)"
        $rows += [pscustomobject]@{{
            ProcessId = [int]$owner
            Name = [string]$proc.Name
            ExecutablePath = [string]$proc.ExecutablePath
            CommandLine = [string]$proc.CommandLine
            CreationDate = if ($proc.CreationDate) {{ [string]$proc.CreationDate.ToUniversalTime().ToString("o") }} else {{ "" }}
            ParentProcessId = [int]$proc.ParentProcessId
            ParentExecutablePath = [string]$parent.ExecutablePath
            ParentCommandLine = [string]$parent.CommandLine
            ParentCreationDate = if ($parent -and $parent.CreationDate) {{ [string]$parent.CreationDate.ToUniversalTime().ToString("o") }} else {{ "" }}
        }}
    }}
}}
@($rows) | ConvertTo-Json -Compress -Depth 3
"""
    try:
        proc = subprocess.run(
            [powershell, "-NoProfile", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=8.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"supported": True, "ok": False}
    if proc.returncode != 0:
        return {"supported": True, "ok": False}

    text = str(proc.stdout or "").strip()
    if not text:
        rows: list[Mapping[str, Any]] = []
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {"supported": True, "ok": False}
        if isinstance(payload, Mapping):
            rows = [payload]
        elif isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, Mapping)]
        else:
            rows = []

    owners: list[dict[str, Any]] = []
    process_names: set[str] = set()
    mismatched_pids: list[int] = []
    match_source_counts: dict[str, int] = {}
    matching_count = 0
    for row in rows:
        pid = int(row.get("ProcessId") or 0)
        name = Path(str(row.get("Name") or "unknown")).name or "unknown"
        process_names.add(name)
        match_source = _listener_owner_doctor_runtime_match_source(
            executable_path=str(row.get("ExecutablePath") or ""),
            command_line=str(row.get("CommandLine") or ""),
            parent_executable_path=str(row.get("ParentExecutablePath") or ""),
            parent_command_line=str(row.get("ParentCommandLine") or ""),
        )
        matches = bool(match_source)
        if matches:
            matching_count += 1
            match_source_counts[match_source] = match_source_counts.get(match_source, 0) + 1
        elif pid:
            mismatched_pids.append(pid)
        owners.append(
            {
                "pid": pid,
                "process_name": name,
                "expected_runtime": matches,
                "match_source": match_source,
                "creation_date": str(row.get("CreationDate") or ""),
                "parent_creation_date": str(row.get("ParentCreationDate") or ""),
            }
        )
    return {
        "supported": True,
        "ok": True,
        "owner_count": len(owners),
        "matching_owner_count": matching_count,
        "match_source_counts": dict(sorted(match_source_counts.items())),
        "mismatched_pids": sorted(set(mismatched_pids)),
        "process_names": sorted(process_names),
        "owners": owners,
    }


def _check_http_listener_source_freshness(checks: list[dict[str, Any]], status: Mapping[str, Any]) -> None:
    freshness = _http_listener_source_freshness_status(status)
    if not freshness.get("supported"):
        return
    if freshness.get("stale"):
        _check(
            checks,
            "http_listener_source_freshness",
            "warning",
            "Local HTTP MCP listener started before current ChimeraMemory runtime source changed; restart the shared sidecar so Codex Desktop uses the latest code.",
            {
                "process_started_at": freshness.get("process_started_at", ""),
                "newest_source_updated_at": freshness.get("newest_source_updated_at", ""),
                "newest_source_file": freshness.get("newest_source_file", ""),
                "stale_by_seconds": int(freshness.get("stale_by_seconds") or 0),
                "checked_file_count": int(freshness.get("checked_file_count") or 0),
            },
        )
        return
    _check(
        checks,
        "http_listener_source_freshness",
        "ok",
        "Local HTTP MCP listener is newer than the checked ChimeraMemory runtime source files.",
        {
            "process_started_at": freshness.get("process_started_at", ""),
            "newest_source_updated_at": freshness.get("newest_source_updated_at", ""),
            "newest_source_file": freshness.get("newest_source_file", ""),
            "checked_file_count": int(freshness.get("checked_file_count") or 0),
        },
    )


def _http_listener_source_freshness_status(
    listener_status: Mapping[str, Any],
    *,
    source_files: list[Path] | None = None,
) -> dict[str, Any]:
    owners = listener_status.get("owners") if isinstance(listener_status.get("owners"), list) else []
    matching_starts: list[datetime] = []
    for owner in owners:
        if not isinstance(owner, Mapping) or not owner.get("expected_runtime"):
            continue
        for key in ("creation_date", "parent_creation_date"):
            parsed = _parse_diagnostic_timestamp(owner.get(key))
            if parsed is not None:
                matching_starts.append(parsed)
                break
    if not matching_starts:
        return {"supported": False, "reason": "missing_process_start"}

    files = list(source_files) if source_files is not None else _http_listener_runtime_source_files()
    newest: tuple[float, Path] | None = None
    checked_count = 0
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        checked_count += 1
        if newest is None or stat.st_mtime > newest[0]:
            newest = (stat.st_mtime, path)
    if newest is None:
        return {"supported": False, "reason": "missing_source_files"}

    process_started_at = min(matching_starts)
    newest_source_at = datetime.fromtimestamp(newest[0], tz=timezone.utc)
    stale_by = int((newest_source_at - process_started_at).total_seconds())
    stale = stale_by > HTTP_LISTENER_SOURCE_FRESHNESS_GRACE_SECONDS
    return {
        "supported": True,
        "stale": stale,
        "process_started_at": process_started_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "newest_source_updated_at": newest_source_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "newest_source_file": newest[1].name,
        "stale_by_seconds": max(0, stale_by),
        "checked_file_count": checked_count,
    }


def _http_listener_runtime_source_files() -> list[Path]:
    root = Path(__file__).resolve().parent
    return [root / name for name in HTTP_LISTENER_RUNTIME_SOURCE_FILES]


def _listener_owner_matches_doctor_runtime(
    *,
    executable_path: str,
    command_line: str,
    parent_executable_path: str = "",
    parent_command_line: str = "",
) -> bool:
    return bool(
        _listener_owner_doctor_runtime_match_source(
            executable_path=executable_path,
            command_line=command_line,
            parent_executable_path=parent_executable_path,
            parent_command_line=parent_command_line,
        )
    )


def _listener_owner_doctor_runtime_match_source(
    *,
    executable_path: str,
    command_line: str,
    parent_executable_path: str = "",
    parent_command_line: str = "",
) -> str:
    expected = _normalized_path_text(sys.executable)
    if not expected:
        return ""
    for source, path in (
        ("owner_executable", executable_path),
        ("parent_executable", parent_executable_path),
    ):
        executable = _normalized_path_text(path)
        if executable and executable == expected:
            return source
    for source, text in (
        ("owner_command_line", command_line),
        ("parent_command_line", parent_command_line),
    ):
        command = os.path.normcase(str(text or ""))
        if command and expected in command:
            return source
    return ""


def _normalized_path_text(value: str) -> str:
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    return os.path.normcase(os.path.abspath(os.path.expanduser(text)))


def _check_http_mcp_initialize(checks: list[dict[str, Any]], url: str) -> None:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "chimera-memory-doctor",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "chimera-memory-codex-doctor", "version": "0"},
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    session_id = ""
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            session_id = str(response.headers.get("mcp-session-id") or "")
            body = response.read(8192).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        _check(
            checks,
            "http_mcp_initialize",
            "error",
            f"Local HTTP endpoint rejected MCP initialize with HTTP {int(exc.code)}.",
        )
        return
    except OSError:
        _check(
            checks,
            "http_mcp_initialize",
            "error",
            "Local HTTP endpoint accepted TCP but did not complete MCP initialize.",
        )
        return
    finally:
        if session_id:
            _close_http_mcp_session(url, session_id)

    parsed = _parse_mcp_initialize_payload(body)
    if not parsed:
        _check(
            checks,
            "http_mcp_initialize",
            "error",
            "Local HTTP endpoint responded, but not with a parseable MCP initialize result.",
        )
        return
    server_name = str(parsed.get("server_name") or "").strip()
    if server_name != "chimera-memory":
        _check(
            checks,
            "http_mcp_initialize",
            "error",
            "Local HTTP endpoint completed MCP initialize, but the server identity is not ChimeraMemory.",
            {"server_name": server_name or "unknown"},
        )
        return
    _check(
        checks,
        "http_mcp_initialize",
        "ok",
        "Local HTTP MCP endpoint completed initialize as ChimeraMemory.",
        {
            "server_name": server_name,
            "protocol_version": str(parsed.get("protocol_version") or ""),
            "tools_capability": bool(parsed.get("tools_capability")),
        },
    )


def _parse_mcp_initialize_payload(text: str) -> dict[str, Any] | None:
    candidates: list[str] = []
    stripped = str(text or "").strip()
    if stripped:
        candidates.append(stripped)
    data_lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if line.startswith("data:"):
            data = line[len("data:") :].strip()
            if data:
                data_lines.append(data)
    if data_lines:
        candidates.append("\n".join(data_lines))
    candidates.extend(data_lines)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        result = payload.get("result")
        if not isinstance(result, Mapping):
            continue
        server_info = result.get("serverInfo")
        if not isinstance(server_info, Mapping):
            continue
        capabilities = result.get("capabilities")
        return {
            "server_name": str(server_info.get("name") or ""),
            "protocol_version": str(result.get("protocolVersion") or ""),
            "tools_capability": isinstance(capabilities, Mapping) and "tools" in capabilities,
        }
    return None


def _close_http_mcp_session(url: str, session_id: str) -> None:
    request = urllib.request.Request(
        url,
        method="DELETE",
        headers={"mcp-session-id": session_id},
    )
    try:
        with urllib.request.urlopen(request, timeout=1.0):
            pass
    except Exception:
        return


def _is_local_mcp_host(host: str) -> bool:
    text = host.strip().lower()
    if text in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return socket.gethostbyname(text).startswith("127.")
    except OSError:
        return False


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
