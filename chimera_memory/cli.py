"""CLI entry point for chimera-memory."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .codex_runtime import codex_executable_for_subprocess


def main():
    parser = argparse.ArgumentParser(
        prog="chimera-memory",
        description="Index local agent session transcripts into queryable SQLite.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # serve: run MCP server
    sub_serve = subparsers.add_parser("serve", help="Run the MCP server")
    sub_serve.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
        help="MCP transport. Use streamable-http for one shared local server.",
    )
    sub_serve.add_argument("--host", default="127.0.0.1", help="HTTP transport bind host")
    sub_serve.add_argument("--port", type=int, default=8000, help="HTTP transport bind port")
    sub_serve.add_argument("--mount-path", default="", help="Optional SSE mount path")

    # backfill: index all historical JSONL files
    sub_bf = subparsers.add_parser("backfill", help="Index all historical JSONL session files")
    sub_bf.add_argument("--jsonl-dir", help="Directory containing JSONL files")
    sub_bf.add_argument("--db", help="Path to transcript.db")
    sub_bf.add_argument("--persona", help="Persona name to tag entries with")
    sub_bf.add_argument("--client", help="Transcript client/parser to use, e.g. claude or codex")

    # stats: show database statistics
    sub_stats = subparsers.add_parser("stats", help="Show transcript database statistics")
    sub_stats.add_argument("--db", help="Path to transcript.db")

    # embed: generate transcript embeddings with visible progress
    sub_embed = subparsers.add_parser("embed", help="Generate transcript embeddings with progress")
    sub_embed.add_argument("--db", help="Path to transcript.db")
    sub_embed.add_argument("--limit", type=int, help="Maximum entries to embed in this run")
    sub_embed.add_argument("--batch-size", type=int, default=64, help="FastEmbed batch size")
    sub_embed.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    # split-db: stage shared transcript DB into per-persona DBs
    sub_split = subparsers.add_parser("split-db", help="Split a shared transcript DB into per-persona DBs")
    sub_split.add_argument("--source", help="Source transcript.db path")
    sub_split.add_argument("--output-root", help="Root for per-persona DBs")
    sub_split.add_argument("--persona", action="append", help="Persona name to split; repeatable. Defaults to all discovered personas")
    sub_split.add_argument("--persona-id", action="append", help="Map persona to role/name id, e.g. sarah=researcher/sarah")
    sub_split.add_argument("--jsonl-dir", action="append", help="Map persona to JSONL dir for import_log filtering, e.g. sarah=~/.claude/projects/...")
    sub_split.add_argument("--apply", action="store_true", help="Write target DBs. Default is dry-run")
    sub_split.add_argument("--replace", action="store_true", help="Replace existing target DBs. Requires --apply")

    # global: no-persona global memory corpus helpers
    sub_global = subparsers.add_parser("global", help="Global memory corpus helpers")
    global_subparsers = sub_global.add_subparsers(dest="global_command")
    sub_global_inspect = global_subparsers.add_parser(
        "inspect",
        help="Inspect configured global memory root and DB index counts",
    )
    sub_global_inspect.add_argument("--global-root", default="", help="Global memory root; defaults to CHIMERA_MEMORY_GLOBAL_ROOT or CM default")
    sub_global_inspect.add_argument("--db", help="Path to transcript.db")
    sub_global_inspect.add_argument("--files", action="store_true", help="Include per-file indexed/unindexed details")
    sub_global_inspect.add_argument("--query", default="", help="Run a read-only global context-pack smoke for this query")
    sub_global_inspect.add_argument("--query-limit", type=int, default=5, help="Maximum memory cards for --query smoke")
    sub_global_inspect.add_argument("--query-token-budget", type=int, default=800, help="Token budget for --query smoke")
    sub_global_inspect.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_global_seed = global_subparsers.add_parser(
        "seed",
        help="Dry-run or copy markdown files into the configured global memory root",
    )
    sub_global_seed.add_argument("--source", required=True, help="Source directory containing curated global markdown")
    sub_global_seed.add_argument("--global-root", default="", help="Target global memory root; defaults to CHIMERA_MEMORY_GLOBAL_ROOT or CM default")
    sub_global_seed.add_argument("--db", help="Path to transcript.db for immediate indexing")
    sub_global_seed.add_argument("--include", action="append", default=[], help="Relative glob to include; repeatable. Defaults to all markdown")
    sub_global_seed.add_argument("--exclude", action="append", default=[], help="Relative glob to exclude; repeatable")
    sub_global_seed.add_argument("--write", action="store_true", help="Copy files and index them. Default is dry-run")
    sub_global_seed.add_argument("--overwrite", action="store_true", help="Overwrite conflicting target files when --write is set")
    sub_global_seed.add_argument("--no-index", action="store_true", help="Do not index copied files after writing")
    sub_global_seed.add_argument(
        "--no-stamp-governance",
        action="store_true",
        help="Do not add safe global governance frontmatter before indexing",
    )
    sub_global_seed.add_argument(
        "--no-guard",
        action="store_true",
        help="Do not block selected files with memory guard findings before writing",
    )
    sub_global_seed.add_argument(
        "--allow-mixed-source",
        action="store_true",
        help="Allow broad seeding from mixed shared/persona-style paths such as roster or relationship folders",
    )
    sub_global_seed.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_global_reindex = global_subparsers.add_parser(
        "reindex",
        help="Dry-run or update DB indexes for one global memory root",
    )
    sub_global_reindex.add_argument("--global-root", default="", help="Global memory root; defaults to CHIMERA_MEMORY_GLOBAL_ROOT or CM default")
    sub_global_reindex.add_argument("--db", help="Path to transcript.db")
    sub_global_reindex.add_argument("--include", action="append", default=[], help="Relative glob to include; repeatable. Defaults to all markdown")
    sub_global_reindex.add_argument("--exclude", action="append", default=[], help="Relative glob to exclude; repeatable")
    sub_global_reindex.add_argument("--write", action="store_true", help="Index files into the DB. Default is dry-run")
    sub_global_reindex.add_argument("--prune-missing", action="store_true", help="With --write, remove stale global DB rows under this root")
    sub_global_reindex.add_argument(
        "--no-stamp-governance",
        action="store_true",
        help="Do not add safe global governance frontmatter before indexing",
    )
    sub_global_reindex.add_argument(
        "--no-guard",
        action="store_true",
        help="Do not block selected files with memory guard findings before indexing",
    )
    sub_global_reindex.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_global_review = global_subparsers.add_parser(
        "review",
        help="List or apply durable review actions for global memory files",
    )
    sub_global_review.add_argument("--global-root", default="", help="Global memory root; defaults to CHIMERA_MEMORY_GLOBAL_ROOT or CM default")
    sub_global_review.add_argument("--db", help="Path to transcript.db")
    sub_global_review.add_argument("--relative-path", default="", help="Global-root-relative markdown file to review")
    sub_global_review.add_argument(
        "--action",
        default="",
        choices=(
            "",
            "confirm",
            "edit",
            "evidence_only",
            "restrict_scope",
            "mark_stale",
            "merge",
            "reject",
            "dispute",
            "supersede",
        ),
        help="Review action. Omit to list pending files or inspect one --relative-path target.",
    )
    sub_global_review.add_argument("--reviewer", default="", help="Reviewer name/id. Required with --write")
    sub_global_review.add_argument("--notes", default="", help="Optional review notes")
    sub_global_review.add_argument(
        "--expect-body-sha256",
        default="",
        help="Optional body SHA256 precondition from target inspection or preview",
    )
    sub_global_review.add_argument("--write", action="store_true", help="Update frontmatter, reindex, and audit. Default is preview/list")
    sub_global_review.add_argument("--reason", action="append", default=[], help="Filter listed files by review reason; repeatable")
    sub_global_review.add_argument("--limit", type=int, default=50, help="Maximum pending files to return when listing")
    sub_global_review.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_global_promote = global_subparsers.add_parser(
        "promote",
        help="Preview or run automated global memory promotion through policy gates",
    )
    sub_global_promote.add_argument("--global-root", default="", help="Global memory root; defaults to CHIMERA_MEMORY_GLOBAL_ROOT or CM default")
    sub_global_promote.add_argument("--db", help="Path to transcript.db")
    sub_global_promote.add_argument("--policy", default="", help="Promotion policy. Defaults to CHIMERA_MEMORY_GLOBAL_AUTO_PROMOTE_POLICY or trusted_clean")
    sub_global_promote.add_argument("--limit", type=int, default=50, help="Maximum pending files to evaluate")
    sub_global_promote.add_argument("--write", action="store_true", help="Promote eligible files. Default is dry-run")
    sub_global_promote.add_argument(
        "--enable-auto-promotion",
        action="store_true",
        help="Explicitly enable write-mode automated promotion for this run",
    )
    sub_global_promote.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    # codex: inspect Codex MCP wiring without exposing raw env values
    sub_codex = subparsers.add_parser("codex", help="Codex integration helpers")
    codex_subparsers = sub_codex.add_subparsers(dest="codex_command")
    sub_codex_doctor = codex_subparsers.add_parser("doctor", help="Check Codex MCP ChimeraMemory setup")
    sub_codex_doctor.add_argument("--config", help="Path to Codex config.toml or legacy mcp_servers.json")
    sub_codex_doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_codex_template = codex_subparsers.add_parser("template", help="Print a safe Codex MCP config template")
    sub_codex_template.add_argument("--persona", default="", help="Optional persona tag for indexed Codex transcripts")
    sub_codex_template.add_argument("--jsonl-dir", default="~/.codex/sessions/", help="Codex JSONL sessions directory")
    sub_codex_template.add_argument(
        "--command",
        dest="server_command",
        default="chimera-memory",
        help="Command Codex should spawn",
    )
    sub_codex_template.add_argument("--server-name", default="chimera-memory", help="MCP server name")
    sub_codex_template.add_argument("--persona-id", default="", help="Optional stable persona id, e.g. developer/asa")
    sub_codex_template.add_argument("--persona-name", default="", help="Optional display persona name")
    sub_codex_template.add_argument("--persona-root", default="", help="Optional persona root directory")
    sub_codex_template.add_argument("--personas-dir", default="", help="Optional personas directory")
    sub_codex_template.add_argument("--shared-root", default="", help="Optional shared memory/root directory")
    sub_codex_template.add_argument("--project-id", default="", help="Optional repo/project memory id for no-persona Codex")
    sub_codex_template.add_argument("--project-root", default="", help="Optional repo/project memory root for no-persona Codex")
    sub_codex_template.add_argument("--global-root", default="", help="Optional global memory root for no-persona Codex")
    sub_codex_install = codex_subparsers.add_parser("install", help="Write or update Codex MCP setup")
    sub_codex_install.add_argument("--config", help="Path to Codex config.toml or legacy mcp_servers.json")
    sub_codex_install.add_argument("--persona", default="", help="Persona tag for indexed Codex transcripts")
    sub_codex_install.add_argument("--persona-id", default="", help="Stable persona id, e.g. developer/asa")
    sub_codex_install.add_argument("--persona-root", default="", help="Persona root directory")
    sub_codex_install.add_argument("--project-id", default="", help="Repo/project memory id for no-persona Codex")
    sub_codex_install.add_argument("--project-root", default="", help="Repo/project memory root for no-persona Codex")
    sub_codex_install.add_argument("--global-root", default="", help="Global memory root for no-persona Codex")
    sub_codex_install.add_argument("--jsonl-dir", default="~/.codex/sessions/", help="Codex JSONL sessions directory")
    sub_codex_install.add_argument(
        "--command",
        dest="server_command",
        default="chimera-memory",
        help="Command Codex should spawn",
    )
    sub_codex_install.add_argument("--server-name", default="chimera-memory", help="MCP server name")
    sub_codex_install.add_argument("--surface", default="", help="MCP tool surface to expose; defaults to codex for project profiles and persona for persona profiles")
    sub_codex_install.add_argument("--provider", default="", help="Optional enhancement provider preference")
    sub_codex_install.add_argument("--reuse-provider-login", action="store_true", help="Import an existing provider login into CM")
    sub_codex_install.add_argument("--oauth-store", default="", help="Optional CM OAuth/auth store path")
    sub_codex_install.add_argument("--enable-provider-worker", action="store_true", help="Let serve use provider-backed enhancement jobs")
    sub_codex_install.add_argument("--hermes-home", default="", help="Optional Hermes home for provider login import")
    sub_codex_install.add_argument("--claude-credentials-path", default="", help="Optional Claude credential path for provider login import")
    sub_codex_install.add_argument("--codex-auth-path", default="", help="Optional Codex auth path for provider login import")
    history_group = sub_codex_install.add_mutually_exclusive_group()
    history_group.add_argument("--import-history", dest="import_history", action="store_true", help="Import existing Codex sessions")
    history_group.add_argument("--no-import-history", dest="import_history", action="store_false", help="Skip existing Codex sessions")
    sub_codex_install.set_defaults(import_history=None)
    sub_codex_install.add_argument("--dry-run", action="store_true", help="Print the install receipt without writing")
    sub_codex_install.add_argument("--yes", action="store_true", help="Accept default prompts")
    sub_codex_install.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_codex_context = codex_subparsers.add_parser(
        "context",
        help="Prefix a Codex prompt with scoped ChimeraMemory evidence",
    )
    sub_codex_context.add_argument("prompt", nargs="?", default="-", help="Prompt text, or '-' / omitted to read stdin")
    sub_codex_context.add_argument("--prompt", dest="inline_prompt", default="", help="Prompt text without using stdin")
    sub_codex_context.add_argument("--db", help="Path to transcript.db")
    sub_codex_context.add_argument("--prompt-file", default="", help="Read prompt text from this file, or '-' for stdin")
    sub_codex_context.add_argument("--previous-context", default="", help="Optional previous turn/topic text")
    sub_codex_context.add_argument("--previous-context-file", default="", help="Read previous turn/topic text from this file, or '-' for stdin")
    sub_codex_context.add_argument("--project-id", default="", help="Optional repo/project memory id")
    sub_codex_context.add_argument("--project-root", default="", help="Project workspace or .chimera-memory root for transcript scoping")
    sub_codex_context.add_argument("--global-root", default="", help="Global memory root for filtering global evidence")
    sub_codex_context.add_argument(
        "--scope",
        choices=("auto", "project", "global"),
        default="auto",
        help="Memory scope for Codex project mode",
    )
    sub_codex_context.add_argument("--limit", type=int, default=5, help="Maximum memory cards")
    sub_codex_context.add_argument("--token-budget", type=int, default=800, help="Context-pack token budget")
    sub_codex_context.add_argument("--shift-threshold", type=float, default=0.55, help="Topic-shift threshold")
    sub_codex_context.add_argument("--no-force", dest="force", action="store_false", help="Skip retrieval unless topic shift is detected")
    sub_codex_context.add_argument("--include-transcripts", action="store_true", help="Add project-scoped transcript snippets when available")
    sub_codex_context.add_argument("--transcript-limit", type=int, default=3, help="Maximum project transcript snippets")
    sub_codex_context.add_argument("--transcript-token-budget", type=int, default=500, help="Transcript snippet token budget")
    sub_codex_context.add_argument("--block-only", action="store_true", help="Print only the memory block, not the full prompt")
    sub_codex_context.add_argument("--receipt-only", action="store_true", help="Print a prompt/body-free context receipt")
    sub_codex_context.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_codex_context.set_defaults(force=True)
    sub_codex_traces = codex_subparsers.add_parser(
        "traces",
        help="Inspect recent Codex context and prompt-delivery traces",
    )
    sub_codex_traces.add_argument("--db", help="Path to transcript.db")
    sub_codex_traces.add_argument("--limit", type=int, default=10, help="Maximum traces to return")
    sub_codex_traces.add_argument("--real-only", action="store_true", help="Show only real codex exec delivery events")
    sub_codex_traces.add_argument(
        "--kind",
        "--delivery-kind",
        dest="delivery_kind",
        action="append",
        default=[],
        help=(
            "Filter by delivery kind; repeatable. "
            "Aliases: real, failed, prompt, diagnostic, context."
        ),
    )
    sub_codex_traces.add_argument("--since", default="", help="Only show traces at or after this date/time")
    sub_codex_traces.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_codex_exec = codex_subparsers.add_parser(
        "exec",
        help="Run codex exec with scoped ChimeraMemory evidence on stdin",
    )
    sub_codex_exec.add_argument("prompt", nargs="?", default="-", help="Prompt text, or '-' / omitted to read stdin")
    sub_codex_exec.add_argument("--prompt", dest="inline_prompt", default="", help="Prompt text without using stdin")
    sub_codex_exec.add_argument("--db", help="Path to transcript.db")
    sub_codex_exec.add_argument("--prompt-file", default="", help="Read prompt text from this file, or '-' for stdin")
    sub_codex_exec.add_argument("--previous-context", default="", help="Optional previous turn/topic text")
    sub_codex_exec.add_argument("--previous-context-file", default="", help="Read previous turn/topic text from this file, or '-' for stdin")
    sub_codex_exec.add_argument("--project-id", default="", help="Optional repo/project memory id")
    sub_codex_exec.add_argument("--project-root", default="", help="Project workspace or .chimera-memory root for transcript scoping")
    sub_codex_exec.add_argument("--global-root", default="", help="Global memory root for filtering global evidence")
    sub_codex_exec.add_argument(
        "--scope",
        choices=("auto", "project", "global"),
        default="auto",
        help="Memory scope for Codex project mode",
    )
    sub_codex_exec.add_argument("--limit", type=int, default=5, help="Maximum memory cards")
    sub_codex_exec.add_argument("--token-budget", type=int, default=800, help="Context-pack token budget")
    sub_codex_exec.add_argument("--shift-threshold", type=float, default=0.55, help="Topic-shift threshold")
    sub_codex_exec.add_argument("--no-force", dest="force", action="store_false", help="Skip retrieval unless topic shift is detected")
    sub_codex_exec.add_argument("--include-transcripts", action="store_true", help="Add project-scoped transcript snippets when available")
    sub_codex_exec.add_argument("--transcript-limit", type=int, default=3, help="Maximum project transcript snippets")
    sub_codex_exec.add_argument("--transcript-token-budget", type=int, default=500, help="Transcript snippet token budget")
    sub_codex_exec.add_argument("--codex-bin", default="", help="Codex executable. Defaults to CHIMERA_MEMORY_CODEX_BIN or codex")
    sub_codex_exec.add_argument("-C", "--cd", default="", help="Working directory for codex exec")
    sub_codex_exec.add_argument("-m", "--model", default="", help="Codex model")
    sub_codex_exec.add_argument("-p", "--profile", default="", help="Codex profile")
    sub_codex_exec.add_argument("-s", "--sandbox", default="", choices=("", "read-only", "workspace-write", "danger-full-access"), help="Codex sandbox mode")
    sub_codex_exec.add_argument("-i", "--image", action="append", default=[], help="Image file to attach to codex exec")
    sub_codex_exec.add_argument("-o", "--output-last-message", default="", help="Codex output-last-message path")
    sub_codex_exec.add_argument("--skip-git-repo-check", action="store_true", help="Pass through to codex exec")
    sub_codex_exec.add_argument("--ephemeral", action="store_true", help="Pass through to codex exec")
    sub_codex_exec.add_argument("--ignore-user-config", action="store_true", help="Pass through to codex exec")
    sub_codex_exec.add_argument("--dangerously-bypass-approvals-and-sandbox", action="store_true", help="Pass through to codex exec")
    sub_codex_exec.add_argument("--json-events", action="store_true", help="Ask codex exec to emit JSONL events")
    sub_codex_exec.add_argument("--dry-run", action="store_true", help="Print the wrapped prompt or JSON receipt without running Codex")
    sub_codex_exec.add_argument("--receipt-only", action="store_true", help="With --dry-run, print a prompt/body-free receipt")
    sub_codex_exec.add_argument("--include-output", action="store_true", help="With --json, include raw codex exec stdout/stderr in the receipt")
    sub_codex_exec.add_argument("--json", action="store_true", help="Emit a machine-readable receipt")
    sub_codex_exec.set_defaults(force=True)

    # hermes: standalone Hermes Agent transcript indexing helpers
    sub_hermes = subparsers.add_parser("hermes", help="Hermes Agent integration helpers")
    hermes_subparsers = sub_hermes.add_subparsers(dest="hermes_command")
    sub_hermes_template = hermes_subparsers.add_parser("template", help="Print a safe Hermes indexer + MCP config template")
    sub_hermes_template.add_argument("--persona", required=True, help="Hermes persona to index (required; scopes to that persona only)")
    sub_hermes_template.add_argument("--command", dest="cm_command", default="chimera-memory", help="chimera-memory command name on PATH")
    sub_hermes_template.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_hermes_doctor = hermes_subparsers.add_parser("doctor", help="Check Hermes standalone indexing setup")
    sub_hermes_doctor.add_argument("--persona", required=True, help="Hermes persona to check")
    sub_hermes_doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_hermes_install = hermes_subparsers.add_parser("install", help="Write per-persona Hermes indexer launcher scripts")
    sub_hermes_install.add_argument("--persona", required=True, help="Hermes persona to index")
    sub_hermes_install.add_argument("--persona-id", default="", help="Optional stable persona id, e.g. developer/asa")
    sub_hermes_install.add_argument("--jsonl-dir", default="", help="Override the Hermes session directory")
    sub_hermes_install.add_argument("--command", dest="cm_command", default="chimera-memory", help="chimera-memory command name on PATH")
    sub_hermes_install.add_argument("--write", action="store_true", help="Actually write the launcher scripts (default is dry-run)")
    sub_hermes_install.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    # enhance: memory-enhancement queue and dry-run helpers
    sub_enhance = subparsers.add_parser("enhance", help="Memory enhancement sidecar helpers")
    enhance_subparsers = sub_enhance.add_subparsers(dest="enhance_command")
    sub_enhance_plan = enhance_subparsers.add_parser("provider-plan", help="Show safe provider-resolution plan")
    sub_enhance_plan.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_provider_smoke = enhance_subparsers.add_parser(
        "provider-smoke",
        help="Safely smoke-check provider selection and optional live sidecar invocation",
    )
    sub_enhance_provider_smoke.add_argument("--live", action="store_true", help="Make a live provider call")
    sub_enhance_provider_smoke.add_argument(
        "--http-sidecar",
        action="store_true",
        help="Route the live call through an ephemeral local HTTP sidecar",
    )
    sub_enhance_provider_smoke.add_argument("--expect-provider", default="", help="Fail if the selected provider differs")
    sub_enhance_provider_smoke.add_argument("--expect-model", default="", help="Fail if the selected model differs")
    sub_enhance_provider_smoke.add_argument("--timeout", type=int, default=30, help="Live smoke timeout in seconds")
    sub_enhance_provider_smoke.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_oauth_list = enhance_subparsers.add_parser("oauth-list", help="List configured provider credentials safely")
    sub_enhance_oauth_list.add_argument("--store", default="", help="Optional OAuth/auth store path")
    sub_enhance_oauth_list.add_argument("--provider", default="", help="Optional provider filter")
    sub_enhance_oauth_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_oauth_import = enhance_subparsers.add_parser("oauth-import", help="Import an existing provider login into CM")
    sub_enhance_oauth_import.add_argument("--provider", required=True, help="Provider id: openai, anthropic, or google")
    sub_enhance_oauth_import.add_argument("--source", default="auto", help="Import source. Defaults to auto")
    sub_enhance_oauth_import.add_argument("--name", default="", help="Optional stored credential name")
    sub_enhance_oauth_import.add_argument("--store", default="", help="Optional OAuth/auth store path")
    sub_enhance_oauth_import.add_argument("--hermes-home", default="", help="Optional Hermes home for imported credentials")
    sub_enhance_oauth_import.add_argument("--claude-credentials-path", default="", help="Optional Claude credential path")
    sub_enhance_oauth_import.add_argument("--codex-auth-path", default="", help="Optional Codex auth path")
    sub_enhance_oauth_import.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_enqueue = enhance_subparsers.add_parser("enqueue", help="Queue an indexed memory file for enhancement")
    sub_enhance_enqueue.add_argument("--db", help="Path to transcript.db")
    sub_enhance_enqueue.add_argument("--file", required=True, help="Indexed memory file path or relative path")
    sub_enhance_enqueue.add_argument("--provider", default="", help="Requested provider hint")
    sub_enhance_enqueue.add_argument("--model", default="", help="Requested model hint")
    sub_enhance_enqueue.add_argument("--force", action="store_true", help="Supersede an existing pending/running job")
    sub_enhance_enqueue.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_authored_enqueue = enhance_subparsers.add_parser(
        "authored-enqueue",
        help="Queue a structured agent-authored memory payload for narrow enrichment",
    )
    sub_enhance_authored_enqueue.add_argument("--db", help="Path to transcript.db")
    sub_enhance_authored_enqueue.add_argument("--persona", required=True, help="Persona writing the payload")
    sub_enhance_authored_enqueue.add_argument("--payload", required=True, help="JSON file containing memory_payload")
    sub_enhance_authored_enqueue.add_argument("--provenance", default="", help="Optional JSON provenance file")
    sub_enhance_authored_enqueue.add_argument("--source-ref", default="", help="Optional source reference")
    sub_enhance_authored_enqueue.add_argument("--provider", default="", help="Requested provider hint")
    sub_enhance_authored_enqueue.add_argument("--model", default="", help="Requested model hint")
    sub_enhance_authored_enqueue.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_authored_write = enhance_subparsers.add_parser(
        "authored-write",
        help="Plan or write a structured authored memory file and queue enrichment",
    )
    sub_enhance_authored_write.add_argument("--db", help="Path to transcript.db")
    sub_enhance_authored_write.add_argument("--personas-dir", default="", help="Root personas directory")
    sub_enhance_authored_write.add_argument("--persona", default="", help="Persona writing the memory")
    sub_enhance_authored_write.add_argument(
        "--scope",
        choices=("persona", "project", "global"),
        default="persona",
        help="Destination scope for the authored memory",
    )
    sub_enhance_authored_write.add_argument("--project-id", default="", help="Project id for --scope project")
    sub_enhance_authored_write.add_argument("--project-root", default="", help="Project memory root for --scope project")
    sub_enhance_authored_write.add_argument("--global-root", default="", help="Global memory root for --scope global")
    sub_enhance_authored_write.add_argument("--payload", required=True, help="YAML file containing structured payload")
    sub_enhance_authored_write.add_argument("--relative-path", default="", help="Optional target relative path")
    sub_enhance_authored_write.add_argument("--write", action="store_true", help="Persist the memory file")
    sub_enhance_authored_write.add_argument("--no-enqueue", action="store_true", help="Do not queue enrichment after write")
    sub_enhance_authored_write.add_argument("--provider", default="", help="Requested provider hint")
    sub_enhance_authored_write.add_argument("--model", default="", help="Requested model hint")
    sub_enhance_authored_write.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_dry_run = enhance_subparsers.add_parser("dry-run", help="Process queued jobs with deterministic local metadata")
    sub_enhance_dry_run.add_argument("--db", help="Path to transcript.db")
    sub_enhance_dry_run.add_argument("--persona", help="Only process jobs for this persona")
    sub_enhance_dry_run.add_argument("--limit", type=int, default=10, help="Maximum jobs to process")
    sub_enhance_dry_run.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_worker_fake = enhance_subparsers.add_parser(
        "worker-fake",
        help="Exercise the CLI-worker protocol with deterministic local metadata",
    )
    sub_enhance_worker_fake.add_argument("--db", help="Path to transcript.db")
    sub_enhance_worker_fake.add_argument("--persona", help="Only process jobs for this persona")
    sub_enhance_worker_fake.add_argument("--worker-id", default="fake-memory-worker", help="Stable fake worker id")
    sub_enhance_worker_fake.add_argument("--provider", default="", help="Optional provider claim and budget scope")
    sub_enhance_worker_fake.add_argument("--limit", type=int, default=10, help="Maximum jobs to process")
    sub_enhance_worker_fake.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_worker_doctor = enhance_subparsers.add_parser(
        "worker-doctor",
        help="Inspect CLI-worker readiness without launching a provider CLI",
    )
    sub_enhance_worker_doctor.add_argument("--runtime", default="codex", help="Worker runtime: codex, claude, or agy")
    sub_enhance_worker_doctor.add_argument("--init", action="store_true", help="Create generated worker files before inspecting")
    sub_enhance_worker_doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_sidecar_run = enhance_subparsers.add_parser("sidecar-run", help="Process queued jobs through an HTTP sidecar")
    sub_enhance_sidecar_run.add_argument("--db", help="Path to transcript.db")
    sub_enhance_sidecar_run.add_argument("--endpoint", required=True, help="Sidecar endpoint URL")
    sub_enhance_sidecar_run.add_argument("--persona", help="Only process jobs for this persona")
    sub_enhance_sidecar_run.add_argument("--limit", type=int, default=10, help="Maximum jobs to process")
    sub_enhance_sidecar_run.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    sub_enhance_sidecar_run.add_argument("--token-env", default="", help="Optional env var containing bearer token")
    sub_enhance_sidecar_run.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub_enhance_sidecar = enhance_subparsers.add_parser("serve-dry-run", help="Run a deterministic local enhancement sidecar")
    sub_enhance_sidecar.add_argument("--host", default="127.0.0.1", help="Bind host")
    sub_enhance_sidecar.add_argument("--port", type=int, default=8944, help="Bind port")
    sub_enhance_sidecar.add_argument("--token-env", default="", help="Optional env var containing bearer token")
    sub_enhance_provider_sidecar = enhance_subparsers.add_parser("serve-provider", help="Run a provider-backed enhancement sidecar")
    sub_enhance_provider_sidecar.add_argument("--host", default="127.0.0.1", help="Bind host")
    sub_enhance_provider_sidecar.add_argument("--port", type=int, default=8944, help="Bind port")
    sub_enhance_provider_sidecar.add_argument("--token-env", default="", help="Optional env var containing sidecar HTTP bearer token")
    sub_enhance_provider_sidecar.add_argument("--provider-token-env", default="", help="Optional env var containing the selected model provider token")
    sub_enhance_grade = enhance_subparsers.add_parser("grade-runs", help="Grade repeated enhancement runs")
    sub_enhance_grade.add_argument("--input", action="append", required=True, help="JSON or JSONL run file; repeatable")
    sub_enhance_grade.add_argument(
        "--expected-action",
        action="append",
        default=[],
        help="Expected core action teaching, e.g. grep-before; repeatable",
    )
    sub_enhance_grade.add_argument("--teachings", default="", help="YAML file containing expected action teachings")
    sub_enhance_grade.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    args = parser.parse_args()

    try:
        if args.command == "serve":
            from .server import main as serve_main
            serve_main(
                transport=args.transport,
                host=args.host,
                port=args.port,
                mount_path=args.mount_path or None,
            )
        elif args.command == "backfill":
            _run_backfill(args)
        elif args.command == "stats":
            _run_stats(args)
        elif args.command == "embed":
            _run_embed(args)
        elif args.command == "split-db":
            _run_split_db(args)
        elif args.command == "codex":
            _run_codex(args)
        elif args.command == "hermes":
            _run_hermes(args)
        elif args.command == "global":
            _run_global(args)
        elif args.command == "enhance":
            _run_enhance(args)
        else:
            parser.print_help()
            sys.exit(1)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # top-level guard: never dump a raw traceback/paths
        if os.environ.get("CHIMERA_MEMORY_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
            raise
        sys.stderr.write(
            f"chimera-memory: '{getattr(args, 'command', None) or 'command'}' failed "
            f"({type(exc).__name__}). Re-run with CHIMERA_MEMORY_DEBUG=1 for the full traceback.\n"
        )
        sys.exit(2)


def _run_backfill(args):
    import logging
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    from .db import TranscriptDB
    from .indexer import Indexer
    from .server import get_default_db_path, get_default_jsonl_dir

    db_path = args.db or str(get_default_db_path())
    jsonl_dir = args.jsonl_dir or str(get_default_jsonl_dir())

    print(f"DB: {db_path}")
    print(f"JSONL dir: {jsonl_dir}")
    print()

    db = TranscriptDB(db_path)
    indexer = Indexer(db, jsonl_dir, persona=args.persona, parser_format=args.client)

    def progress(current, total):
        pct = (current / total * 100) if total else 0
        print(f"\r  [{current}/{total}] {pct:.0f}%", end="", flush=True)

    indexer.backfill(progress_callback=progress)
    print()

    stats = db.stats()
    print(f"Done. {stats['entry_count']:,} entries, {stats['session_count']} sessions, {stats['db_size_mb']:.1f} MB")


def _run_stats(args):
    from .db import TranscriptDB
    from .search import transcript_stats
    from .server import get_default_db_path

    db_path = args.db or str(get_default_db_path())
    db = TranscriptDB(db_path)
    stats = transcript_stats(db)

    print(f"Entries:    {stats['entry_count']:,}")
    print(f"Sessions:   {stats['session_count']}")
    print(f"DB Size:    {stats['db_size_mb']:.1f} MB")
    print(f"Last Entry: {stats.get('last_entry', 'none')}")
    print(f"Indexed:    {stats.get('files_indexed', 0)} files")
    print()
    if stats.get("entry_types"):
        print("Entry Types:")
        for etype, count in stats["entry_types"].items():
            print(f"  {etype}: {count:,}")
    if stats.get("sources"):
        print("Sources:")
        for source, count in stats["sources"].items():
            print(f"  {source}: {count:,}")


def _run_embed(args):
    import logging

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    from .db import TranscriptDB
    from .embeddings import (
        count_unembedded_transcript_entries,
        embed_transcript_entries,
        embedding_runtime_status,
        format_progress_bar,
    )
    from .server import get_default_db_path

    db_path = args.db or str(get_default_db_path())
    db = TranscriptDB(db_path)
    batch_size = max(1, args.batch_size)
    with db.connection() as conn:
        pending = count_unembedded_transcript_entries(conn)
        limit = None if args.limit is None else max(0, args.limit)
        total_to_embed = pending if limit is None else min(pending, limit)
        runtime = embedding_runtime_status()
        if args.json:
            count = embed_transcript_entries(
                db,
                conn,
                batch_size=batch_size,
                limit=limit,
                progress_label="cli transcript embeddings",
                log_progress=False,
            )
            print(
                json.dumps(
                    {
                        "db": db_path,
                        "pending_before": pending,
                        "embedded": count,
                        "pending_after": count_unembedded_transcript_entries(conn),
                        "runtime": runtime,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return

        print(f"DB: {db_path}")
        print(
            "Embedding runtime: "
            f"provider={runtime['provider']} threads={runtime['threads']}/{runtime['cpu_count']} "
            f"cpu_reserve={runtime['cpu_reserve_percent']}%"
        )
        if total_to_embed <= 0:
            print("All eligible transcript entries already have embeddings.")
            return

        print(f"Pending transcript entries: {pending:,}")

        def progress(current, total):
            print(f"\r  {format_progress_bar(current, total)}", end="", flush=True)

        count = embed_transcript_entries(
            db,
            conn,
            batch_size=batch_size,
            progress_callback=progress,
            limit=limit,
            progress_label="cli transcript embeddings",
            log_progress=False,
        )
        print()
        print(f"Done. Embedded {count:,} entries; {count_unembedded_transcript_entries(conn):,} pending.")


def _run_split_db(args):
    from .db_split import parse_mapping, results_to_json, split_db
    from .server import get_default_db_path

    if args.replace and not args.apply:
        print("--replace requires --apply", file=sys.stderr)
        sys.exit(2)

    try:
        persona_ids = parse_mapping(args.persona_id)
        jsonl_dirs = parse_mapping(args.jsonl_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    source = args.source or str(get_default_db_path())
    results = split_db(
        source,
        output_root=args.output_root,
        personas=args.persona,
        persona_ids=persona_ids,
        jsonl_dirs=jsonl_dirs,
        dry_run=not args.apply,
        replace=args.replace,
    )
    print(results_to_json(results))


def _run_global(args):
    if args.global_command == "inspect":
        from .memory_global_seed import inspect_global_memory_corpus

        result = inspect_global_memory_corpus(
            target_root=args.global_root or None,
            db_path=args.db,
            include_files=args.files,
            query=args.query,
            query_limit=args.query_limit,
            query_token_budget=args.query_token_budget,
        )
        database = result.get("database") or {}
        filesystem = result.get("filesystem") or {}
        authority = result.get("authority") or {}
        guard = result.get("guard") or {}
        query_smoke = result.get("query_smoke") if isinstance(result.get("query_smoke"), dict) else {}
        lines = [
            f"Global root exists: {bool(result.get('global_root_exists'))}",
            f"Global root markdown files: {filesystem.get('markdown_file_count', 0)}",
            f"Indexed global memory files: {database.get('global_available_file_count', 0)}/{database.get('global_indexed_file_count', 0)} available",
            f"Trusted instruction-grade global files: {authority.get('trusted_instruction_grade_file_count', 0)}/{authority.get('file_count', 0)}",
            f"Review-gated global files: pending={authority.get('pending_review_file_count', 0)}, requires_confirmation={authority.get('requires_user_confirmation_file_count', 0)}",
            f"Memory guard blocked files: {guard.get('blocked_count', 0)}",
            f"Unindexed root markdown files: {filesystem.get('unindexed_markdown_file_count', 0)}",
            f"Indexed rows missing files: {filesystem.get('indexed_missing_file_count', 0)}",
            f"Indexed global rows outside root: {database.get('outside_target_root_indexed_file_count', 0)}",
            _safe_path_payload_line("Global root", result.get("root")),
        ]
        if query_smoke:
            lines.extend(_global_query_smoke_lines(query_smoke))
        lines.extend(_global_review_recommendation_lines(result))
        _emit_json_or_lines(result, json_output=args.json, lines=lines)
        return

    if args.global_command == "seed":
        from .memory_global_seed import seed_global_memory_corpus

        result = seed_global_memory_corpus(
            args.source,
            target_root=args.global_root or None,
            db_path=args.db,
            write=args.write,
            overwrite=args.overwrite,
            index=not args.no_index,
            stamp_governance=not args.no_stamp_governance,
            guard=not args.no_guard,
            allow_mixed_source=args.allow_mixed_source,
            include_patterns=args.include,
            exclude_patterns=args.exclude,
        )
        counts = result.get("counts") or {}
        if not result.get("ok"):
            _emit_json_or_lines(
                result,
                json_output=args.json,
                lines=[f"Global seed failed: {result.get('error', 'unknown error')}"],
            )
            sys.exit(2)

        if result.get("write"):
            index_result = result.get("index") or {}
            lines = [
                f"Seeded global memory files: {result.get('written_count', 0)}",
                f"Stamped governance on files: {(result.get('governance_stamp') or {}).get('changed_count', 0)}",
                f"Indexed global memory files: {index_result.get('indexed_count', 0)}",
                f"Mixed-source findings: {(result.get('mixed_source_guard') or {}).get('finding_count', 0)}",
                f"Conflicts skipped: {counts.get('conflict', 0)}",
                _safe_path_payload_line("Target root", result.get("target")),
            ]
        else:
            lines = [
                "Global memory seed preview only. Re-run with --write to copy and index.",
                f"Markdown files to copy: {counts.get('copy', 0)}",
                f"Mixed-source blocked files: {(result.get('mixed_source_guard') or {}).get('blocked_count', 0)}",
                f"Memory guard blocked files: {(result.get('guard') or {}).get('blocked_count', 0)}",
                f"Governance stamps needed: {(result.get('governance_stamp') or {}).get('would_change_count', 0)}",
                f"Conflicts: {counts.get('conflict', 0)}",
                f"Skipped files: {counts.get('skip', 0)}",
                _safe_path_payload_line("Target root", result.get("target")),
            ]
        _emit_json_or_lines(result, json_output=args.json, lines=lines)
        if counts.get("conflict", 0):
            sys.exit(1)
        return

    if args.global_command == "reindex":
        from .memory_global_seed import reindex_global_memory_corpus

        result = reindex_global_memory_corpus(
            target_root=args.global_root or None,
            db_path=args.db,
            write=args.write,
            prune_missing=args.prune_missing,
            stamp_governance=not args.no_stamp_governance,
            guard=not args.no_guard,
            include_patterns=args.include,
            exclude_patterns=args.exclude,
        )
        counts = result.get("counts") or {}
        if not result.get("ok"):
            _emit_json_or_lines(
                result,
                json_output=args.json,
                lines=[f"Global reindex failed: {result.get('error', 'unknown error')}"],
            )
            sys.exit(2)
        if result.get("write"):
            index_result = result.get("index") or {}
            prune_result = result.get("prune") or {}
            lines = [
                f"Indexed global memory files: {index_result.get('indexed_count', 0)}",
                f"Stamped governance on files: {(result.get('governance_stamp') or {}).get('changed_count', 0)}",
                f"Changed indexed files: {index_result.get('changed_count', 0)}",
                f"Pruned missing rows: {prune_result.get('pruned_count', 0)}",
                _safe_path_payload_line("Global root", result.get("root")),
            ]
        else:
            lines = [
                "Global memory reindex preview only. Re-run with --write to update the DB.",
                f"Markdown files selected: {counts.get('selected_file_count', 0)}",
                f"Memory guard blocked files: {(result.get('guard') or {}).get('blocked_count', 0)}",
                f"Governance stamps needed: {(result.get('governance_stamp') or {}).get('would_change_count', 0)}",
                f"Skipped files: {counts.get('skipped_file_count', 0)}",
                f"Prune candidates: {counts.get('prune_candidate_count', 0)}",
                _safe_path_payload_line("Global root", result.get("root")),
            ]
        _emit_json_or_lines(result, json_output=args.json, lines=lines)
        return

    if args.global_command == "review":
        from .memory_global_review import (
            memory_global_review_action,
            memory_global_review_pending,
            memory_global_review_target,
        )

        wants_action = bool(args.relative_path or args.action)
        if args.action and not args.relative_path:
            result = {
                "ok": False,
                "error": "--relative-path is required for global review actions",
            }
            _emit_json_or_lines(
                result,
                json_output=args.json,
                lines=["Global review failed: --relative-path is required for global review actions."],
            )
            sys.exit(2)
        if args.relative_path and not args.action:
            result = memory_global_review_target(
                relative_path=args.relative_path,
                target_root=args.global_root or None,
                db_path=args.db,
            )
            if not result.get("ok"):
                _emit_json_or_lines(
                    result,
                    json_output=args.json,
                    lines=[f"Global review target failed: {result.get('error', 'unknown error')}"],
                )
                sys.exit(2)
            lines = [
                "Global memory review target inspection.",
                f"Target: {result.get('relative_path', '')}",
                f"Review status: {result.get('review_status', '')}",
                f"Review reasons: {','.join(str(reason) for reason in (result.get('review_reasons') or [])) or 'none'}",
                f"Requires confirmation: {bool(result.get('requires_user_confirmation'))}",
                f"Instruction-grade: {bool(result.get('can_use_as_instruction'))}",
                f"Evidence-enabled: {bool(result.get('can_use_as_evidence'))}",
                f"Indexed: {bool(result.get('indexed'))}",
                f"Body chars: {int(result.get('body_char_count') or 0)}",
                f"Body SHA256: {result.get('body_sha256', '')}",
                *_review_guard_receipt_lines(result.get("confirm_guard")),
                *_global_review_recommendation_lines(result),
            ]
            _emit_json_or_lines(result, json_output=args.json, lines=lines)
            return
        if wants_action:
            result = memory_global_review_action(
                relative_path=args.relative_path,
                action=args.action,
                reviewer=args.reviewer,
                notes=args.notes,
                expected_body_sha256=args.expect_body_sha256,
                target_root=args.global_root or None,
                db_path=args.db,
                write=args.write,
            )
            if not result.get("ok"):
                _emit_json_or_lines(
                    result,
                    json_output=args.json,
                    lines=[
                        f"Global review failed: {result.get('error', 'unknown error')}",
                        *_review_guard_receipt_lines(result.get("guard")),
                        *_global_review_recommendation_lines(result),
                    ],
                )
                sys.exit(2)
            after = result.get("after") or {}
            if result.get("written"):
                lines = [
                    f"Global memory review written: {result.get('relative_path', '')}",
                    f"Action: {result.get('action', '')}",
                    f"Review status: {after.get('review_status', '')}",
                    f"Instruction-grade: {after.get('can_use_as_instruction', False)}",
                    f"Indexed: {bool(result.get('indexed'))}",
                    *_review_guard_receipt_lines(result.get("guard")),
                    *_global_review_recommendation_lines(result),
                ]
            else:
                guard = result.get("guard") if isinstance(result.get("guard"), dict) else {}
                if int(guard.get("blocked_count") or 0) > 0:
                    preview_status = (
                        "Global memory review preview only. Guard would block this action; "
                        "do not apply it with --write."
                    )
                else:
                    preview_status = (
                        "Global memory review preview only. Guard-clean preview; "
                        "apply only after human review."
                    )
                lines = [
                    preview_status,
                    f"Target: {result.get('relative_path', '')}",
                    f"Action: {result.get('action', '')}",
                    f"Review status after preview: {after.get('review_status', '')}",
                    f"Instruction-grade after preview: {after.get('can_use_as_instruction', False)}",
                    *_review_guard_receipt_lines(result.get("guard")),
                    *_global_review_recommendation_lines(result),
                ]
            _emit_json_or_lines(result, json_output=args.json, lines=lines)
            return

        result = memory_global_review_pending(
            target_root=args.global_root or None,
            db_path=args.db,
            limit=args.limit,
            reasons=args.reason,
        )
        if not result.get("ok"):
            _emit_json_or_lines(
                result,
                json_output=args.json,
                lines=[f"Global review failed: {result.get('error', 'unknown error')}"],
            )
            sys.exit(2)
        summary = result.get("summary") or {}
        matching_summary = result.get("matching_summary") or {}
        reason_counts = summary.get("reason_counts") if isinstance(summary, dict) else {}
        matching_reason_counts = (
            matching_summary.get("reason_counts") if isinstance(matching_summary, dict) else {}
        )
        reason_text = ", ".join(f"{key}={value}" for key, value in (reason_counts or {}).items()) or "none"
        matching_reason_text = (
            ", ".join(f"{key}={value}" for key, value in (matching_reason_counts or {}).items()) or "none"
        )
        lines = [
            f"Pending global memory review files: {result.get('pending_count', 0)}",
            f"Matching files: {result.get('matching_count', result.get('pending_count', 0))}",
            f"Returned files: {result.get('returned_count', 0)}",
            f"Review reasons: {reason_text}",
            f"Confirm guard blocked files: {summary.get('confirm_guard_blocked_count', 0)}",
        ]
        active_reason_filters = bool((result.get("filters") or {}).get("review_reasons"))
        if active_reason_filters:
            lines.append(f"Matching review reasons: {matching_reason_text}")
            lines.append(f"Matching confirm guard blocked files: {matching_summary.get('confirm_guard_blocked_count', 0)}")
        lines.extend(_global_review_target_lines(result))
        lines.extend(_global_review_recommendation_lines(result))
        lines.append(_safe_path_payload_line("Global root", result.get("root")))
        _emit_json_or_lines(result, json_output=args.json, lines=lines)
        return

    if args.global_command == "promote":
        from .memory_global_review import memory_global_auto_promote

        result = memory_global_auto_promote(
            target_root=args.global_root or None,
            db_path=args.db,
            policy=args.policy,
            limit=args.limit,
            write=args.write,
            enabled=args.enable_auto_promotion if args.enable_auto_promotion else None,
        )
        counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        policy = result.get("policy") if isinstance(result.get("policy"), dict) else {}
        lines = [
            (
                "Global auto-promotion written."
                if result.get("write") and result.get("ok")
                else "Global auto-promotion preview."
                if not result.get("write")
                else "Global auto-promotion failed."
            ),
            f"Policy: {policy.get('id', '')}",
            f"Enabled: {bool(result.get('enabled'))}",
            f"Scanned files: {counts.get('scanned_count', 0)}",
            f"Eligible files: {counts.get('eligible_count', 0)}",
            f"Promoted files: {counts.get('promoted_count', 0)}",
            f"Skipped files: {counts.get('skipped_count', 0)}",
            f"Failed files: {counts.get('failed_count', 0)}",
            _safe_path_payload_line("Global root", result.get("root")),
        ]
        if not result.get("ok"):
            lines.insert(1, f"Error: {result.get('error', 'unknown error')}")
        lines.extend(_global_review_recommendation_lines(result))
        _emit_json_or_lines(result, json_output=args.json, lines=lines)
        if not result.get("ok"):
            sys.exit(2)
        return

    print("Missing global command. Try: chimera-memory global inspect", file=sys.stderr)
    sys.exit(2)


def _run_hermes(args):
    from .hermes_setup import (
        inspect_hermes_setup,
        install_hermes_indexer,
        render_hermes_template,
    )

    command = getattr(args, "hermes_command", None)
    if command == "template":
        result = render_hermes_template(args.persona, command=args.cm_command)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"# ChimeraMemory <-> Hermes setup for persona '{result['persona']}'")
            print("\n## Index standalone Hermes sessions (run CM with this env):")
            for key in sorted(result["indexer_env"]):
                print(f"  {key}={result['indexer_env'][key]}")
            print(f"\n  $ {result['backfill_command']}    # one-shot")
            print(f"  $ {result['serve_command']}                 # watch + backfill")
            print("\n## Let Hermes query CM memory (paste into Hermes config.yaml):\n")
            print(result["mcp_config_block"])
        return

    if command == "doctor":
        report = inspect_hermes_setup(args.persona)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"Hermes setup for persona '{report['persona']}': {'OK' if report['ok'] else 'ISSUES'}")
            for check in report["checks"]:
                mark = {"ok": "[ok]", "warn": "[warn]", "error": "[ERR]"}.get(check["status"], "[?]")
                print(f"  {mark} {check['check']}: {check['detail']}")
        if not report["ok"]:
            sys.exit(1)
        return

    if command == "install":
        result = install_hermes_indexer(
            args.persona,
            write=args.write,
            jsonl_dir=args.jsonl_dir,
            persona_id=args.persona_id,
            command=args.cm_command,
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            if not result.get("ok"):
                print(f"Hermes install failed: {result.get('error', 'unknown error')}")
                sys.exit(1)
            verb = "Wrote" if result.get("written") else "Would write (dry-run; pass --write)"
            print(f"{verb} Hermes indexer launchers for persona '{result['persona']}':")
            print(f"  ~/.chimera-memory/hermes/{result['launchers']['powershell_name']}")
            print(f"  ~/.chimera-memory/hermes/{result['launchers']['bash_name']}")
            print("  env:")
            for key in sorted(result["indexer_env"]):
                print(f"    {key}={result['indexer_env'][key]}")
        return

    print("Usage: chimera-memory hermes {template|doctor|install} --persona <name>")
    sys.exit(1)


def _run_codex(args):
    if args.codex_command == "doctor":
        from .codex_setup import format_codex_doctor_report, inspect_codex_mcp_config

        report = inspect_codex_mcp_config(args.config)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_codex_doctor_report(report))

        status = report.get("status")
        if status == "ok":
            sys.exit(0)
        if status == "warning":
            sys.exit(1)
        sys.exit(2)
    if args.codex_command == "template":
        from .codex_setup import build_codex_mcp_config

        config = build_codex_mcp_config(
            persona=args.persona,
            jsonl_dir=args.jsonl_dir,
            command=args.server_command,
            server_name=args.server_name,
            persona_id=args.persona_id,
            persona_name=args.persona_name,
            persona_root=args.persona_root,
            personas_dir=args.personas_dir,
            shared_root=args.shared_root,
            project_id=args.project_id,
            project_root=args.project_root,
            global_root=args.global_root,
        )
        print(json.dumps(config, indent=2))
        return
    if args.codex_command == "install":
        from .codex_setup import format_codex_install_report, install_codex_mcp_config

        import_history = args.import_history
        if import_history is None:
            import_history = _prompt_yes_no(
                "Import existing Codex session history into CM?",
                default=True,
                assume_default=args.yes or args.json,
            )
        try:
            receipt = install_codex_mcp_config(
                config_path=args.config,
                persona=args.persona,
                persona_id=args.persona_id,
                persona_root=args.persona_root,
                project_id=args.project_id,
                project_root=args.project_root,
                global_root=args.global_root,
                jsonl_dir=args.jsonl_dir,
                command=args.server_command,
                server_name=args.server_name,
                import_history=import_history,
                mcp_surface=args.surface,
                provider=args.provider,
                reuse_provider_auth=args.reuse_provider_login,
                oauth_store=args.oauth_store,
                enable_provider_worker=args.enable_provider_worker,
                hermes_home=args.hermes_home or None,
                claude_credentials_path=args.claude_credentials_path or None,
                codex_auth_path=args.codex_auth_path or None,
                dry_run=args.dry_run,
            )
        except ValueError as exc:
            print(f"Codex install failed: {exc}", file=sys.stderr)
            sys.exit(2)
        if args.json:
            print(json.dumps(receipt, indent=2, sort_keys=True))
        else:
            print(format_codex_install_report(receipt))
        return
    if args.codex_command == "context":
        result = _build_cli_codex_context_result(args)
        if not result.get("ok"):
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Codex context failed: {result.get('error', 'unknown error')}", file=sys.stderr)
            sys.exit(2)
        if args.receipt_only:
            receipt = _codex_context_result_receipt(result)
            _emit_json_or_lines(receipt, json_output=args.json, lines=_codex_context_receipt_lines(receipt))
        elif args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.block_only:
            print(result.get("evidence_block") or "", end="" if result.get("evidence_block") else "\n")
        else:
            print(result.get("prompt") or "", end="" if str(result.get("prompt") or "").endswith("\n") else "\n")
        return
    if args.codex_command == "traces":
        from .codex_setup import inspect_codex_context_traces

        result = inspect_codex_context_traces(
            db_path=args.db,
            limit=args.limit,
            real_only=args.real_only,
            delivery_kinds=args.delivery_kind,
            since=args.since,
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            _emit_json_or_lines(result, json_output=False, lines=_codex_context_trace_lines(result))
        if not result.get("ok"):
            sys.exit(2)
        return
    if args.codex_command == "exec":
        result = _build_cli_codex_context_result(args)
        if not result.get("ok"):
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"Codex exec context failed: {result.get('error', 'unknown error')}", file=sys.stderr)
            sys.exit(2)

        command = _codex_exec_command(args)
        wrapped_prompt = str(result.get("prompt") or "")
        receipt = {
            "ok": True,
            "dry_run": bool(args.dry_run),
            "delivery_mode": result.get("delivery_mode"),
            "command_preview": command,
            "injected": bool(result.get("injected")),
            "retrieved": bool(result.get("retrieved")),
            "scope": result.get("scope"),
            "project_id": result.get("project_id"),
            "project_root": result.get("project_root"),
            "trace_id": result.get("trace_id"),
            "returned_count": result.get("returned_count"),
            "transcript_returned_count": result.get("transcript_returned_count"),
            "transcript_raw_candidate_count": result.get("transcript_raw_candidate_count"),
            "transcript_reason": result.get("transcript_reason"),
            "transcript_trace_id": result.get("transcript_trace_id"),
            "transcript_event_id": result.get("transcript_event_id"),
        }
        receipt["delivery_proof"] = _codex_exec_delivery_proof(result, dry_run=bool(args.dry_run))
        if args.dry_run:
            if args.json:
                if args.receipt_only:
                    receipt.update(_codex_context_result_receipt(result))
                else:
                    receipt["prompt"] = wrapped_prompt
                print(json.dumps(receipt, indent=2, sort_keys=True))
            elif args.receipt_only:
                receipt.update(_codex_context_result_receipt(result))
                _emit_json_or_lines(receipt, json_output=False, lines=_codex_context_receipt_lines(receipt))
            else:
                print(wrapped_prompt, end="" if wrapped_prompt.endswith("\n") else "\n")
            return

        try:
            completed = subprocess.run(
                command,
                input=wrapped_prompt,
                text=True,
                cwd=args.cd or None,
                capture_output=bool(args.json),
            )
        except FileNotFoundError as exc:
            try:
                delivery_events = _record_codex_exec_delivery_failure(args, result, exception=exc)
            except Exception:
                delivery_events = [
                    {
                        "event_recorded": False,
                        "error": "codex prompt delivery failure audit failed",
                    }
                ]
            receipt.update(
                {
                    "ok": False,
                    "error": "codex exec launch failed",
                    "hint": "Codex executable was not found. Set --codex-bin or CHIMERA_MEMORY_CODEX_BIN, then retry.",
                    "exception": exc.__class__.__name__,
                    "returncode": 127,
                    "delivery_events": delivery_events,
                    "delivery_proof": _codex_exec_delivery_proof(
                        result,
                        dry_run=False,
                        subprocess_attempted=True,
                        subprocess_started=False,
                        delivery_failed=True,
                        delivery_events=delivery_events,
                        returncode=127,
                    ),
                    "output": _process_output_receipt(stdout=None, stderr=None, include_output=False),
                }
            )
            if args.json:
                print(json.dumps(receipt, indent=2, sort_keys=True))
            else:
                print(f"Codex exec launch failed: {receipt['hint']}", file=sys.stderr)
            sys.exit(127)
        except OSError as exc:
            try:
                delivery_events = _record_codex_exec_delivery_failure(args, result, exception=exc)
            except Exception:
                delivery_events = [
                    {
                        "event_recorded": False,
                        "error": "codex prompt delivery failure audit failed",
                    }
                ]
            receipt.update(
                {
                    "ok": False,
                    "error": "codex exec launch failed",
                    "hint": "Codex could not be launched before prompt delivery. Check --codex-bin and the requested working directory.",
                    "exception": exc.__class__.__name__,
                    "returncode": 1,
                    "delivery_events": delivery_events,
                    "delivery_proof": _codex_exec_delivery_proof(
                        result,
                        dry_run=False,
                        subprocess_attempted=True,
                        subprocess_started=False,
                        delivery_failed=True,
                        delivery_events=delivery_events,
                        returncode=1,
                    ),
                    "output": _process_output_receipt(stdout=None, stderr=None, include_output=False),
                }
            )
            if args.json:
                print(json.dumps(receipt, indent=2, sort_keys=True))
            else:
                print(f"Codex exec launch failed: {receipt['hint']}", file=sys.stderr)
            sys.exit(1)
        try:
            delivery_events = _record_codex_exec_delivery(args, result, returncode=completed.returncode)
        except Exception:
            delivery_events = [
                {
                    "event_recorded": False,
                    "error": "codex prompt delivery audit failed",
                }
            ]
        if args.json:
            receipt.update(
                {
                    "returncode": completed.returncode,
                    "delivery_events": delivery_events,
                    "delivery_proof": _codex_exec_delivery_proof(
                        result,
                        dry_run=False,
                        subprocess_attempted=True,
                        subprocess_started=True,
                        delivery_failed=False,
                        delivery_events=delivery_events,
                        returncode=completed.returncode,
                    ),
                    "output": _process_output_receipt(
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                        include_output=bool(args.include_output),
                    ),
                }
            )
            if args.include_output:
                receipt["stdout"] = completed.stdout
                receipt["stderr"] = completed.stderr
            print(json.dumps(receipt, indent=2, sort_keys=True))
        sys.exit(completed.returncode)

    print("Missing Codex command. Try: chimera-memory codex doctor", file=sys.stderr)
    sys.exit(2)


def _build_cli_codex_context_result(args) -> dict:
    from .codex_context import build_codex_prompt_context

    prompt = _read_cli_text_arg(
        file_path=args.prompt_file,
        inline_text=_codex_inline_prompt_arg(args),
        default_stdin=True,
    )
    previous_context = _read_cli_text_arg(
        file_path=args.previous_context_file,
        inline_text=args.previous_context,
        default_stdin=False,
    )
    conn = _open_memory_db(args.db)
    try:
        return build_codex_prompt_context(
            conn,
            prompt=prompt,
            previous_context=previous_context,
            project_id=_codex_context_project_id(args) or None,
            project_root=_codex_context_project_root(args) or None,
            global_root=_codex_context_global_root(args) or None,
            scope=args.scope,
            limit=args.limit,
            token_budget=args.token_budget,
            shift_threshold=args.shift_threshold,
            force=args.force,
            include_transcripts=args.include_transcripts,
            transcript_limit=args.transcript_limit,
            transcript_token_budget=args.transcript_token_budget,
            delivery_mode=_codex_context_delivery_mode(args),
        )
    finally:
        conn.close()


def _codex_context_delivery_mode(args) -> str:
    command = str(getattr(args, "codex_command", "") or "").strip()
    if command == "exec":
        return "exec_dry_run" if bool(getattr(args, "dry_run", False)) else "exec"
    if command == "context":
        return "context_only"
    return "unknown"


def _record_codex_exec_delivery(args, context_result: dict, *, returncode: int) -> list[dict[str, object]]:
    from .memory_observability import record_memory_audit_event

    trace_specs = [
        ("curated_memory", str(context_result.get("trace_id") or ""), int(context_result.get("returned_count") or 0)),
        (
            "transcript_fallback",
            str(context_result.get("transcript_trace_id") or ""),
            int(context_result.get("transcript_returned_count") or 0),
        ),
    ]
    trace_specs = [(role, trace_id, returned_count) for role, trace_id, returned_count in trace_specs if trace_id]
    if not trace_specs:
        return []

    events: list[dict[str, object]] = []
    conn = _open_memory_db(args.db)
    try:
        for role, trace_id, returned_count in trace_specs:
            event_id = record_memory_audit_event(
                conn,
                "codex_prompt_delivered",
                persona=None,
                target_kind="codex_exec",
                target_id=trace_id,
                trace_id=trace_id,
                payload={
                    "schema_version": "chimera-memory.codex-exec-delivery.v1",
                    "delivery_mode": "exec",
                    "trace_role": role,
                    "returned_count": returned_count,
                    "injected": bool(context_result.get("injected")),
                    "returncode": int(returncode),
                    "transport": "stdin",
                    "command_shape": "codex exec -",
                    "raw_prompt_in_payload": False,
                    "raw_command_in_payload": False,
                    "raw_output_in_payload": False,
                },
                actor="codex-context",
            )
            events.append(
                {
                    "event_id": event_id,
                    "trace_id": trace_id,
                    "trace_role": role,
                    "delivery_mode": "exec",
                }
            )
    finally:
        conn.close()
    return events


def _record_codex_exec_delivery_failure(args, context_result: dict, *, exception: OSError) -> list[dict[str, object]]:
    from .memory_observability import record_memory_audit_event

    trace_specs = [
        ("curated_memory", str(context_result.get("trace_id") or ""), int(context_result.get("returned_count") or 0)),
        (
            "transcript_fallback",
            str(context_result.get("transcript_trace_id") or ""),
            int(context_result.get("transcript_returned_count") or 0),
        ),
    ]
    trace_specs = [(role, trace_id, returned_count) for role, trace_id, returned_count in trace_specs if trace_id]
    if not trace_specs:
        return []

    events: list[dict[str, object]] = []
    conn = _open_memory_db(args.db)
    try:
        for role, trace_id, returned_count in trace_specs:
            event_id = record_memory_audit_event(
                conn,
                "codex_prompt_delivery_failed",
                persona=None,
                target_kind="codex_exec",
                target_id=trace_id,
                trace_id=trace_id,
                payload={
                    "schema_version": "chimera-memory.codex-exec-delivery-failed.v1",
                    "delivery_mode": "exec",
                    "trace_role": role,
                    "returned_count": returned_count,
                    "injected": bool(context_result.get("injected")),
                    "exception": exception.__class__.__name__,
                    "codex_bin_supplied": bool(str(getattr(args, "codex_bin", "") or "").strip()),
                    "cwd_supplied": bool(str(getattr(args, "cd", "") or "").strip()),
                    "transport": "stdin",
                    "command_shape": "codex exec -",
                    "raw_prompt_in_payload": False,
                    "raw_command_in_payload": False,
                    "raw_output_in_payload": False,
                },
                actor="codex-context",
            )
            events.append(
                {
                    "event_id": event_id,
                    "trace_id": trace_id,
                    "trace_role": role,
                    "delivery_mode": "exec",
                    "delivery_failed": True,
                }
            )
    finally:
        conn.close()
    return events


def _codex_inline_prompt_arg(args) -> str:
    optional_prompt = str(getattr(args, "inline_prompt", "") or "")
    if optional_prompt:
        return optional_prompt
    return str(getattr(args, "prompt", "") or "")


def _codex_exec_command(args) -> list[str]:
    command = [_codex_executable_for_subprocess(args.codex_bin), "exec"]
    if args.model:
        command.extend(["--model", args.model])
    if args.profile:
        command.extend(["--profile", args.profile])
    if args.sandbox:
        command.extend(["--sandbox", args.sandbox])
    if args.cd:
        command.extend(["--cd", args.cd])
    for image_path in args.image or []:
        command.extend(["--image", image_path])
    if args.output_last_message:
        command.extend(["--output-last-message", args.output_last_message])
    if args.skip_git_repo_check:
        command.append("--skip-git-repo-check")
    if args.ephemeral:
        command.append("--ephemeral")
    if args.ignore_user_config:
        command.append("--ignore-user-config")
    if args.dangerously_bypass_approvals_and_sandbox:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    if args.json_events:
        command.append("--json")
    command.append("-")
    return command


def _codex_executable_for_subprocess(command: str) -> str:
    return codex_executable_for_subprocess(command)


def _codex_context_project_id(args) -> str:
    from .memory_scope import safe_project_id, workspace_root_from_project_root

    explicit = safe_project_id(getattr(args, "project_id", "") or "")
    if explicit:
        return explicit
    project_root = _codex_context_project_root(args)
    if not project_root:
        return ""
    workspace = workspace_root_from_project_root(project_root)
    if workspace is None:
        return ""
    return safe_project_id(workspace.name) or ""


def _codex_context_project_root(args) -> str:
    explicit = str(getattr(args, "project_root", "") or "").strip()
    if explicit:
        return explicit
    codex_cwd = str(getattr(args, "cd", "") or "").strip()
    if codex_cwd:
        return codex_cwd
    cwd = Path.cwd()
    if (cwd / ".git").exists() or (cwd / ".chimera-memory").exists():
        return str(cwd)
    return ""


def _codex_context_global_root(args) -> str:
    explicit = str(getattr(args, "global_root", "") or "").strip()
    if explicit:
        return explicit
    env_root = os.environ.get("CHIMERA_MEMORY_GLOBAL_ROOT", "").strip()
    if env_root:
        return env_root
    from .memory_scope import global_memory_root

    return str(global_memory_root())


def _read_cli_text_arg(*, file_path: str, inline_text: str, default_stdin: bool) -> str:
    selected_file = str(file_path or "").strip()
    if selected_file:
        if selected_file == "-":
            return sys.stdin.read()
        try:
            return Path(selected_file).read_text(encoding="utf-8-sig")
        except OSError as exc:
            print(f"Unable to read text file: {exc}", file=sys.stderr)
            sys.exit(2)
    if default_stdin and inline_text == "-":
        return sys.stdin.read()
    return str(inline_text or "")


def _process_output_receipt(*, stdout: str | None, stderr: str | None, include_output: bool) -> dict[str, object]:
    return {
        "stdout": _stream_output_receipt(stdout),
        "stderr": _stream_output_receipt(stderr),
        "raw_output_included": bool(include_output),
    }


def _codex_exec_delivery_proof(
    context_result: object,
    *,
    dry_run: bool,
    subprocess_attempted: bool = False,
    subprocess_started: bool = False,
    delivery_failed: bool = False,
    delivery_events: list[dict[str, object]] | None = None,
    returncode: int | None = None,
) -> dict[str, object]:
    events = [event for event in (delivery_events or []) if isinstance(event, dict)]
    recorded_count = sum(1 for event in events if _codex_delivery_event_recorded(event))
    failed_recorded_count = sum(
        1
        for event in events
        if bool(event.get("delivery_failed")) and _codex_delivery_event_recorded(event)
    )
    started = bool(subprocess_started)
    attempted = bool(subprocess_attempted or started)
    return {
        "schema_version": "chimera-memory.codex-exec-delivery-proof.v1",
        "prompt_constructed": isinstance(context_result, dict) and bool(context_result.get("ok")),
        "prompt_injected": isinstance(context_result, dict) and bool(context_result.get("injected")),
        "delivery_mode": str(context_result.get("delivery_mode") or "") if isinstance(context_result, dict) else "",
        "transport": "stdin",
        "dry_run": bool(dry_run),
        "subprocess_attempted": attempted,
        "subprocess_started": started,
        "subprocess_stdin_delivered": started and not bool(dry_run),
        "delivery_failed": bool(delivery_failed),
        "delivery_event_count": len(events),
        "delivery_event_recorded_count": recorded_count,
        "delivery_failure_event_recorded_count": failed_recorded_count,
        "real_delivery_recorded": started and recorded_count > 0,
        "returncode": returncode,
        "raw_prompt_included": False,
        "raw_output_included": False,
    }


def _codex_delivery_event_recorded(event: dict[str, object]) -> bool:
    if event.get("event_recorded") is False:
        return False
    return bool(event.get("event_id") or event.get("trace_id"))


def _stream_output_receipt(text: str | None) -> dict[str, object]:
    value = str(text or "")
    return {
        "present": bool(value),
        "char_count": len(value),
        "line_count": value.count("\n") + (1 if value and not value.endswith("\n") else 0),
    }


def _prompt_yes_no(prompt: str, *, default: bool, assume_default: bool = False) -> bool:
    if assume_default or not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "true", "1", "on"}


def _open_memory_db(db_path: str | None):
    import sqlite3

    from .memory import init_memory_tables
    from .server import get_default_db_path

    path = db_path or str(get_default_db_path())
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        init_memory_tables(conn)
    except Exception:
        conn.close()  # don't leak the handle if schema init fails
        raise
    return conn


def _emit_json_or_lines(payload: object, *, json_output: bool, lines: list[str]) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for line in lines:
        print(line)


def _safe_path_payload_line(label: str, payload: object) -> str:
    if not isinstance(payload, dict):
        return f"{label}:"
    name = str(payload.get("name") or "")
    fingerprint = str(payload.get("fingerprint") or "")
    provenance = str(payload.get("provenance") or "")
    details = ", ".join(
        part
        for part in (
            f"fingerprint={fingerprint}" if fingerprint else "",
            provenance,
        )
        if part
    )
    return f"{label}: {name}" + (f" ({details})" if details else "")


def _review_guard_receipt_lines(guard: object) -> list[str]:
    if not isinstance(guard, dict):
        return []
    return [
        f"Review guard required: {bool(guard.get('required'))}",
        f"Review guard blocked files: {guard.get('blocked_count', 0)}",
        f"Review guard findings: {guard.get('finding_count', 0)}",
    ]


def _global_review_target_lines(result: object) -> list[str]:
    if not isinstance(result, dict):
        return []
    files = result.get("files")
    if not isinstance(files, list) or not files:
        return []
    lines = ["Review targets:"]
    for item in files:
        if not isinstance(item, dict):
            continue
        relative_path = str(item.get("relative_path") or "").replace("\\", "/")
        if not relative_path:
            continue
        reasons = sorted({str(reason) for reason in item.get("review_reasons") or [] if str(reason)})
        reason_text = ",".join(reasons) or "none"
        confirm_guard = item.get("confirm_guard") if isinstance(item.get("confirm_guard"), dict) else {}
        action_guidance = item.get("action_guidance") if isinstance(item.get("action_guidance"), dict) else {}
        recommended_actions = ",".join(
            str(action)
            for action in (action_guidance.get("recommended_next_actions") or [])
            if str(action)
        ) or "none"
        lines.append(
            "  - "
            f"{relative_path}: reasons={reason_text}; "
            f"indexed={bool(item.get('indexed'))}; "
            f"confirm_guard_blocked={int(confirm_guard.get('blocked_count') or 0)}; "
            f"actions={recommended_actions}"
        )
    if result.get("truncated"):
        lines.append(
            "Review target list truncated: "
            f"showing {result.get('returned_count', 0)}/{result.get('matching_count', 0)} matching files"
        )
    return lines if len(lines) > 1 else []


def _global_query_smoke_lines(smoke: object) -> list[str]:
    if not isinstance(smoke, dict):
        return []
    lines = [
        f"Global query smoke status: {smoke.get('status', '')}",
        (
            "Global query smoke returned cards: "
            f"{smoke.get('returned_count', 0)}/{smoke.get('result_count', 0)} "
            f"(raw={smoke.get('raw_result_count', 0)}, filtered={smoke.get('filtered_count', 0)})"
        ),
    ]
    reason = str(smoke.get("reason") or "")
    if reason:
        lines.append(f"Global query smoke reason: {reason}")
    diagnostics = smoke.get("diagnostics") if isinstance(smoke.get("diagnostics"), dict) else {}
    if diagnostics:
        stage = str(diagnostics.get("candidate_stage") or "")
        likely_reason = str(diagnostics.get("likely_reason") or "")
        if stage or likely_reason:
            lines.append(
                "Global query smoke diagnosis: "
                f"stage={stage or 'unknown'}; "
                f"likely_reason={likely_reason or reason or 'unknown'}"
            )
        lines.append(
            "Global query smoke candidate counts: "
            f"raw={int(diagnostics.get('raw_candidate_count') or 0)}, "
            f"quality_filtered={int(diagnostics.get('quality_filtered_count') or 0)}, "
            f"post_quality={int(diagnostics.get('post_quality_candidate_count') or 0)}, "
            f"duplicate_filtered={int(diagnostics.get('duplicate_filtered_count') or 0)}"
        )
        candidate_profiles = diagnostics.get("candidate_profiles")
        if isinstance(candidate_profiles, list) and candidate_profiles:
            lines.append("Global query smoke candidate profiles:")
            for item in candidate_profiles[:10]:
                if not isinstance(item, dict):
                    continue
                relative_path = str(item.get("relative_path") or "").replace("\\", "/")
                if not relative_path:
                    continue
                profile = item.get("query_match_profile") if isinstance(item.get("query_match_profile"), dict) else {}
                matched_terms = ",".join(str(term) for term in profile.get("matched_terms") or [])
                matched_suffix = f"; matched={matched_terms}" if matched_terms else ""
                lines.append(
                    "  - "
                    f"{relative_path} "
                    f"(quality_passed={bool(item.get('quality_gate_passed'))}; "
                    f"coverage={profile.get('coverage', '')}; "
                    f"matches={profile.get('specific_match_count', 0)}/{profile.get('gate_term_count', 0)}"
                    f"{matched_suffix})"
                )
    policy = smoke.get("policy") if isinstance(smoke.get("policy"), dict) else {}
    lines.append(f"Global query smoke root filter: {bool(policy.get('global_root_filter_enabled'))}")
    cards = smoke.get("cards") if isinstance(smoke.get("cards"), list) else []
    if cards:
        lines.append("Global query smoke cards:")
        for item in cards[:10]:
            if not isinstance(item, dict):
                continue
            relative_path = str(item.get("relative_path") or "").replace("\\", "/")
            if not relative_path:
                continue
            meta = (
                f"review={item.get('review_status', '')}; "
                f"instruction={bool(item.get('can_use_as_instruction'))}; "
                f"needs_confirmation={bool(item.get('requires_user_confirmation'))}; "
                f"score={item.get('score', '')}"
            )
            lines.append(f"  - {relative_path} ({meta})")
    return lines


def _global_review_recommendation_lines(result: object) -> list[str]:
    if not isinstance(result, dict):
        return []
    recommendations = result.get("recommendations")
    if not isinstance(recommendations, list) or not recommendations:
        return []
    lines = ["Recommendations:"]
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "")
        suffix = f" Command: {command}" if command else ""
        lines.append(f"  - {item.get('message', '')}{suffix}")
    return lines if len(lines) > 1 else []


def _codex_context_result_receipt(result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        return {
            "ok": False,
            "error": "invalid codex context result",
            "prompt_included": False,
            "evidence_body_included": False,
        }
    prompt_text = str(result.get("prompt") or "")
    evidence_text = str(result.get("evidence_block") or "")
    transcript_text = str(result.get("transcript_block") or "")
    return {
        "ok": bool(result.get("ok")),
        "injected": bool(result.get("injected")),
        "retrieved": bool(result.get("retrieved")),
        "scope": str(result.get("scope") or ""),
        "project_id": str(result.get("project_id") or ""),
        "project_root": str(result.get("project_root") or ""),
        "delivery_mode": str(result.get("delivery_mode") or ""),
        "trace_id": str(result.get("trace_id") or ""),
        "returned_count": int(result.get("returned_count") or 0),
        "result_count": int(result.get("result_count") or 0),
        "raw_result_count": int(result.get("raw_result_count") or 0),
        "filtered_count": int(result.get("filtered_count") or 0),
        "token_estimate": int(result.get("token_estimate") or 0),
        "transcript_returned_count": int(result.get("transcript_returned_count") or 0),
        "transcript_raw_candidate_count": int(result.get("transcript_raw_candidate_count") or 0),
        "transcript_reason": str(result.get("transcript_reason") or ""),
        "transcript_trace_id": str(result.get("transcript_trace_id") or ""),
        "transcript_event_id": str(result.get("transcript_event_id") or ""),
        "prompt_char_count": len(prompt_text),
        "evidence_block_char_count": len(evidence_text),
        "transcript_block_char_count": len(transcript_text),
        "prompt_included": False,
        "evidence_body_included": False,
    }


def _codex_context_receipt_lines(receipt: object) -> list[str]:
    if not isinstance(receipt, dict):
        return ["Codex context receipt unavailable: invalid receipt."]
    if not receipt.get("ok"):
        return [f"Codex context failed: {receipt.get('error', 'unknown error')}"]
    lines = [
        f"Codex context injected: {bool(receipt.get('injected'))}",
        f"Scope: {receipt.get('scope', '')}",
        f"Project: {receipt.get('project_id', '')}",
        f"Delivery mode: {receipt.get('delivery_mode', '')}",
        f"Returned memory cards: {receipt.get('returned_count', 0)}",
        f"Transcript snippets: {receipt.get('transcript_returned_count', 0)}",
        f"Trace: {receipt.get('trace_id', '')}",
        "Prompt/body included: False",
    ]
    proof = receipt.get("delivery_proof")
    if isinstance(proof, dict):
        lines.append(
            "Subprocess stdin delivered: "
            f"{bool(proof.get('subprocess_stdin_delivered'))}; "
            f"real delivery recorded: {bool(proof.get('real_delivery_recorded'))}"
        )
    return lines


def _codex_context_trace_lines(result: object) -> list[str]:
    if not isinstance(result, dict):
        return ["Codex context traces unavailable: invalid receipt."]
    if not result.get("ok"):
        return [f"Codex context traces unavailable: {result.get('error', 'unknown error')}"]
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    lines = [
        f"Codex context traces returned: {result.get('returned_count', 0)}/{result.get('matching_count', 0)}",
        (
            "Trace kinds: "
            f"real_exec_delivery={summary.get('real_delivery_count', 0)}, "
            f"exec_delivery_failed={summary.get('failed_delivery_count', 0)}, "
            f"prompt_construction={summary.get('prompt_construction_count', 0)}, "
            f"diagnostic_smoke={summary.get('diagnostic_smoke_count', 0)}, "
            f"context_trace={summary.get('context_trace_count', 0)}"
        ),
        f"Returned evidence traces: {summary.get('returned_trace_count', 0)}",
        f"Real exec deliveries with evidence: {summary.get('real_delivery_returned_count', 0)}",
    ]
    filters = result.get("filters") if isinstance(result.get("filters"), dict) else {}
    delivery_kinds = [str(kind) for kind in (filters.get("delivery_kinds") or []) if str(kind)]
    if delivery_kinds:
        lines.append("Delivery kind filters: " + ",".join(delivery_kinds))
    traces = result.get("traces") if isinstance(result.get("traces"), list) else []
    if not traces:
        lines.append("No Codex context traces found.")
    else:
        lines.append("Recent Codex context traces:")
        for trace in traces:
            if not isinstance(trace, dict):
                continue
            event_types = ",".join(str(event_type) for event_type in trace.get("event_types") or []) or "none"
            request_scope = str(trace.get("request_scope") or "")
            scope_suffix = f" | scope={request_scope}" if request_scope else ""
            returned_scopes = trace.get("returned_memory_scopes") if isinstance(trace.get("returned_memory_scopes"), dict) else {}
            returned_scope_text = ",".join(
                f"{scope}={int(count or 0)}"
                for scope, count in sorted(returned_scopes.items())
                if int(count or 0) > 0
            )
            returned_scope_suffix = f" | returned_scopes={returned_scope_text}" if returned_scope_text else ""
            lines.append(
                "- "
                f"{trace.get('created_at_display', '')} | "
                f"{trace.get('tool_name', '')} | "
                f"returned {trace.get('returned_count', 0)}/{trace.get('requested_limit', 0)} | "
                f"kind={trace.get('delivery_kind', '')} | "
                f"mode={trace.get('delivery_mode', '')}"
                f"{scope_suffix}"
                f"{returned_scope_suffix} | "
                f"events={event_types} | "
                f"trace={trace.get('trace_id', '')}"
            )
    if result.get("truncated"):
        lines.append(
            "Trace list truncated: "
            f"showing {result.get('returned_count', 0)}/{result.get('matching_count', 0)} matching traces"
        )
    recommendations = result.get("recommendations") if isinstance(result.get("recommendations"), list) else []
    if recommendations:
        lines.append("Recommendations:")
        for item in recommendations:
            if not isinstance(item, dict):
                continue
            command = str(item.get("command") or "")
            suffix = f" Command: {command}" if command else ""
            lines.append(f"- {item.get('message', '')}{suffix}")
    lines.append(_safe_path_payload_line("DB", result.get("db")))
    return lines


def _run_enhance(args):
    if args.enhance_command == "oauth-list":
        from .memory_enhancement_oauth import MemoryEnhancementOAuthStore

        store = MemoryEnhancementOAuthStore(args.store or None)
        credentials = store.list_pooled_credentials(provider_id=args.provider or "")
        active_names = {}
        for credential in credentials:
            if credential.provider_id not in active_names:
                active_names[credential.provider_id] = store.active_pooled_name(credential.provider_id)
        items = []
        for credential in credentials:
            safe = credential.to_safe_dict()
            safe["active"] = credential.id == active_names.get(credential.provider_id)
            items.append(safe)
        payload = {
            "store_path": str(store.path),
            "credential_count": len(items),
            "credentials": items,
        }
        _emit_json_or_lines(
            payload,
            json_output=args.json,
            lines=_oauth_list_lines(payload),
        )
        return

    if args.enhance_command == "oauth-import":
        from .memory_enhancement_oauth import MemoryEnhancementOAuthStore
        from .memory_enhancement_oauth_import import import_memory_enhancement_oauth_credential

        store = MemoryEnhancementOAuthStore(args.store or None)
        try:
            credential = import_memory_enhancement_oauth_credential(
                provider_id=args.provider,
                source=args.source,
                name=args.name,
                store=store,
                hermes_home=args.hermes_home or None,
                claude_credentials_path=args.claude_credentials_path or None,
                codex_auth_path=args.codex_auth_path or None,
            )
        except Exception as exc:
            print(f"OAuth import failed: {exc}", file=sys.stderr)
            sys.exit(2)
        payload = {
            "status": "imported",
            "store_path": str(store.path),
            "credential": credential.to_safe_dict(),
        }
        _emit_json_or_lines(
            payload,
            json_output=args.json,
            lines=[
                f"Imported provider credential: {credential.provider_id}",
                f"Transport: {credential.transport}",
                f"Source: {credential.source}",
                "Credential values are stored locally and are not printed.",
            ],
        )
        return

    if args.enhance_command == "provider-plan":
        from .memory_enhancement_provider import resolve_enhancement_provider_plan, safe_provider_receipt

        receipt = safe_provider_receipt(resolve_enhancement_provider_plan(os.environ), os.environ)
        selected = receipt["selected_provider"]
        model = receipt["selected_model"]
        lines = [
            f"Selected provider: {selected}",
            f"Selected model:    {model}",
            "Credential refs:   hidden; only presence is reported in JSON mode",
        ]
        if receipt.get("recommendations"):
            lines.append("Recommendations:")
            for item in receipt.get("recommendations", []):
                if not isinstance(item, dict):
                    continue
                command = str(item.get("command") or "")
                suffix = f" Command: {command}" if command else ""
                lines.append(f"- {item.get('message', '')}{suffix}")
        _emit_json_or_lines(receipt, json_output=args.json, lines=lines)
        return

    if args.enhance_command == "provider-smoke":
        from .memory_enhancement_provider_smoke import memory_enhancement_provider_smoke

        receipt = memory_enhancement_provider_smoke(
            live=args.live,
            http_sidecar=args.http_sidecar,
            expected_provider=args.expect_provider,
            expected_model=args.expect_model,
            timeout_seconds=args.timeout,
        )
        provider = receipt.get("provider") if isinstance(receipt.get("provider"), dict) else {}
        metadata = receipt.get("metadata") if isinstance(receipt.get("metadata"), dict) else {}
        lines = [
            f"Provider smoke status: {receipt.get('status', '')}",
            f"Selected provider: {provider.get('selected_provider', '')}",
            f"Selected model:    {provider.get('selected_model', '')}",
            f"Live call:         {bool(receipt.get('live'))}",
            f"Transport:         {receipt.get('transport', '')}",
            f"Duration:          {receipt.get('duration_ms', 0)} ms",
            "Credential refs:   hidden; only presence is reported in JSON mode",
        ]
        if metadata:
            lines.extend(
                [
                    f"Metadata summary present: {bool(metadata.get('summary_present'))}",
                    f"Metadata review status:   {metadata.get('review_status', '')}",
                    f"Instruction-grade:        {bool(metadata.get('can_use_as_instruction'))}",
                ]
            )
        if not receipt.get("ok"):
            error = receipt.get("error") if isinstance(receipt.get("error"), dict) else {}
            lines.append(f"Provider smoke failed: {error.get('code', 'unknown_error')}")
            _emit_json_or_lines(receipt, json_output=args.json, lines=lines)
            sys.exit(2)
        _emit_json_or_lines(receipt, json_output=args.json, lines=lines)
        return

    if args.enhance_command == "enqueue":
        from .memory import memory_enhancement_enqueue
        from .memory_enhancement_queue import safe_enhancement_receipt

        conn = _open_memory_db(args.db)
        try:
            result = memory_enhancement_enqueue(
                conn,
                file_path=args.file,
                requested_provider=args.provider,
                requested_model=args.model,
                force=args.force,
            )
        finally:
            conn.close()

        safe_result = safe_enhancement_receipt(result)
        if not result.get("ok"):
            _emit_json_or_lines(
                safe_result,
                json_output=args.json,
                lines=[f"Enhancement enqueue failed: {result.get('error', 'unknown error')}"],
            )
            sys.exit(2)

        job = safe_result.get("job") if isinstance(safe_result, dict) else {}
        job = job if isinstance(job, dict) else {}
        action = "Enqueued" if result.get("enqueued") else "Already queued"
        _emit_json_or_lines(
            safe_result,
            json_output=args.json,
            lines=[
                f"{action} enhancement job: {job.get('job_id', '')}",
                f"Status: {job.get('status', '')}",
                f"Persona: {job.get('persona', '')}",
            ],
        )
        return

    if args.enhance_command == "authored-enqueue":
        from pathlib import Path

        from .memory import memory_enhancement_enqueue_authored
        from .memory_enhancement_queue import safe_enhancement_receipt

        try:
            raw_payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Authored enqueue failed: invalid payload file ({exc.__class__.__name__})", file=sys.stderr)
            sys.exit(2)
        if not isinstance(raw_payload, dict):
            print("Authored enqueue failed: payload must be a JSON object", file=sys.stderr)
            sys.exit(2)

        memory_payload = raw_payload.get("memory_payload") if isinstance(raw_payload.get("memory_payload"), dict) else raw_payload
        provenance = raw_payload.get("provenance") if isinstance(raw_payload.get("provenance"), dict) else {}
        if args.provenance:
            try:
                raw_provenance = json.loads(Path(args.provenance).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"Authored enqueue failed: invalid provenance file ({exc.__class__.__name__})", file=sys.stderr)
                sys.exit(2)
            if not isinstance(raw_provenance, dict):
                print("Authored enqueue failed: provenance must be a JSON object", file=sys.stderr)
                sys.exit(2)
            provenance = raw_provenance

        source_ref = args.source_ref or str(raw_payload.get("source_ref") or "")
        conn = _open_memory_db(args.db)
        try:
            result = memory_enhancement_enqueue_authored(
                conn,
                persona=args.persona,
                memory_payload=memory_payload,
                provenance=provenance,
                source_ref=source_ref,
                requested_provider=args.provider,
                requested_model=args.model,
            )
        finally:
            conn.close()

        safe_result = safe_enhancement_receipt(result)
        if not result.get("ok"):
            _emit_json_or_lines(
                safe_result,
                json_output=args.json,
                lines=[f"Authored enqueue failed: {result.get('error', 'unknown error')}"],
            )
            sys.exit(2)

        job = safe_result.get("job") if isinstance(safe_result, dict) else {}
        job = job if isinstance(job, dict) else {}
        _emit_json_or_lines(
            safe_result,
            json_output=args.json,
            lines=[
                f"Enqueued authored enhancement job: {job.get('job_id', '')}",
                f"Status: {job.get('status', '')}",
                f"Persona: {job.get('persona', '')}",
            ],
        )
        return

    if args.enhance_command == "authored-write":
        from pathlib import Path

        from .memory import memory_authored_writeback
        from .memory_authored_writeback import load_authored_memory_payload
        from .memory_global_seed import cli_global_memory_root
        from .memory_enhancement_queue import safe_enhancement_receipt
        from .memory_scope import current_project_id, project_memory_root, safe_project_id

        try:
            payload = load_authored_memory_payload(args.payload)
        except ValueError as exc:
            print(f"Authored write failed: {exc}", file=sys.stderr)
            sys.exit(2)

        selected_scope = str(args.scope or "persona").strip().lower()
        selected_persona = str(args.persona or "").strip()
        selected_project_id = ""
        selected_project_root = None
        selected_global_root = None
        resolved_personas_dir = str(args.personas_dir or os.environ.get("CHIMERA_PERSONAS_DIR", "")).strip()
        personas_dir = Path(resolved_personas_dir or ".")
        if selected_scope == "persona":
            # Validate the RESOLVED dir (including the CHIMERA_PERSONAS_DIR
            # fallback used just above), not only the --personas-dir flag (cli-04).
            if not selected_persona or not resolved_personas_dir:
                result = {
                    "ok": False,
                    "error": "--persona and --personas-dir are required for persona authored memory",
                }
                _emit_json_or_lines(
                    result,
                    json_output=args.json,
                    lines=[f"Authored write failed: {result['error']}"],
                )
                sys.exit(2)
        elif selected_scope == "project":
            if selected_persona:
                result = {"ok": False, "error": "do not provide --persona with --scope project"}
                _emit_json_or_lines(
                    result,
                    json_output=args.json,
                    lines=[f"Authored write failed: {result['error']}"],
                )
                sys.exit(2)
            selected_project_id = safe_project_id(args.project_id) or current_project_id() or ""
            selected_project_root = (
                Path(args.project_root).expanduser()
                if str(args.project_root or "").strip()
                else project_memory_root(selected_project_id)
            )
            if not selected_project_id or selected_project_root is None:
                result = {"ok": False, "error": "--project-id or CHIMERA_MEMORY_PROJECT_ID plus project root is required"}
                _emit_json_or_lines(
                    result,
                    json_output=args.json,
                    lines=[f"Authored write failed: {result['error']}"],
                )
                sys.exit(2)
            selected_persona = f"project:{selected_project_id}"
        elif selected_scope == "global":
            if selected_persona:
                result = {"ok": False, "error": "do not provide --persona with --scope global"}
                _emit_json_or_lines(
                    result,
                    json_output=args.json,
                    lines=[f"Authored write failed: {result['error']}"],
                )
                sys.exit(2)
            selected_global_root = (
                Path(args.global_root).expanduser()
                if str(args.global_root or "").strip()
                else cli_global_memory_root()
            )
            selected_persona = "global"

        conn = _open_memory_db(args.db)
        try:
            result = memory_authored_writeback(
                conn,
                personas_dir,
                persona=selected_persona,
                payload=payload,
                relative_path=args.relative_path,
                write=args.write,
                enqueue=not args.no_enqueue,
                requested_provider=args.provider,
                requested_model=args.model,
                memory_scope=selected_scope,
                project_id=selected_project_id,
                project_root=selected_project_root,
                global_root=selected_global_root,
                actor="cli",
            )
        finally:
            conn.close()

        if not result.get("ok"):
            _emit_json_or_lines(
                result,
                json_output=args.json,
                lines=[f"Authored write failed: {result.get('error', 'unknown error')}"],
            )
            sys.exit(2)

        if result.get("written"):
            job = ((result.get("enrichment_job") or {}).get("job") or {})
            lines = [
                f"Wrote authored memory: {result.get('relative_path', '')}",
                f"Indexed: {result.get('indexed')}",
                f"Enrichment job: {job.get('job_id', 'not queued')}",
            ]
        else:
            plan = result.get("plan") or {}
            lines = [
                "Authored memory preview only. Re-run with --write to persist.",
                f"Relative path: {plan.get('relative_path', '')}",
                f"Structured rows: {plan.get('request_payload', {}).get('contract', {}).get('structured_field_count', 0)}",
            ]
        safe_result = dict(result)
        if "enrichment_job" in safe_result:
            safe_result["enrichment_job"] = safe_enhancement_receipt(safe_result.get("enrichment_job"))
        _emit_json_or_lines(safe_result, json_output=args.json, lines=lines)
        return

    if args.enhance_command == "dry-run":
        from .enhancement_worker import run_memory_enhancement_dry_run
        from .memory_enhancement_queue import safe_enhancement_receipt

        conn = _open_memory_db(args.db)
        try:
            processed = run_memory_enhancement_dry_run(conn, persona=args.persona, limit=args.limit)
        finally:
            conn.close()

        payload = {
            "processed_count": len(processed),
            "processed": processed,
        }
        safe_payload = safe_enhancement_receipt(payload)
        _emit_json_or_lines(
            safe_payload,
            json_output=args.json,
            lines=[f"Processed enhancement jobs: {len(processed)}"],
        )
        return

    if args.enhance_command == "worker-fake":
        from .enhancement_worker import run_memory_enhancement_fake_worker
        from .memory_enhancement_queue import safe_enhancement_receipt

        conn = _open_memory_db(args.db)
        try:
            receipt = run_memory_enhancement_fake_worker(
                conn,
                worker_id=args.worker_id,
                persona=args.persona,
                provider=args.provider,
                limit=args.limit,
            )
        finally:
            conn.close()

        safe_receipt = safe_enhancement_receipt(receipt)
        _emit_json_or_lines(
            safe_receipt,
            json_output=args.json,
            lines=[
                f"Processed enhancement jobs: {receipt['processed_count']}",
                f"Failed enhancement jobs: {receipt['failure_count']}",
                f"Budget stopped: {receipt['budget_stopped']}",
            ],
        )
        return

    if args.enhance_command == "worker-doctor":
        from .memory_cli_worker_supervisor import inspect_cli_worker_setup

        receipt = inspect_cli_worker_setup(runtime=args.runtime, init=args.init)
        status = "ok" if receipt.get("ok") else "warning"
        lines = [
            f"CLI worker setup: {status}",
            f"Runtime: {receipt.get('runtime')}",
            f"Worker: {receipt.get('worker_id')}",
            f"Provider: {receipt.get('provider')}",
            f"Executable found: {receipt.get('executable_found')}",
            f"Launch performed: {receipt.get('launch_performed')}",
        ]
        _emit_json_or_lines(receipt, json_output=args.json, lines=lines)
        return

    if args.enhance_command == "sidecar-run":
        from .memory_enhancement_http_client import MemoryEnhancementHttpClient
        from .memory_enhancement_runner import run_memory_enhancement_provider_batch

        bearer_token = ""
        if args.token_env:
            bearer_token = os.environ.get(args.token_env, "")
            if not bearer_token:
                print("Bearer token env var is not set", file=sys.stderr)
                sys.exit(2)
        client = MemoryEnhancementHttpClient(
            args.endpoint,
            bearer_token=bearer_token,
            timeout_seconds=args.timeout,
        )
        conn = _open_memory_db(args.db)
        try:
            receipt = run_memory_enhancement_provider_batch(
                conn,
                client=client,
                persona=args.persona,
                limit=args.limit,
            )
        finally:
            conn.close()

        _emit_json_or_lines(
            receipt,
            json_output=args.json,
            lines=[
                f"Processed enhancement jobs: {receipt['processed_count']}",
                f"Failed enhancement jobs: {receipt['failure_count']}",
            ],
        )
        return

    if args.enhance_command == "serve-dry-run":
        from .memory_enhancement_sidecar import run_dry_run_sidecar

        bearer_token = ""
        if args.token_env:
            bearer_token = os.environ.get(args.token_env, "")
            if not bearer_token:
                print("Bearer token env var is not set", file=sys.stderr)
                sys.exit(2)
        print(f"Dry-run memory enhancement sidecar listening on http://{args.host}:{args.port}/enhance")
        run_dry_run_sidecar(args.host, args.port, bearer_token=bearer_token)
        return

    if args.enhance_command == "serve-provider":
        from .memory_enhancement_model_client import ProviderModelMemoryEnhancementClient
        from .memory_enhancement_provider_sidecar import ResolvingMemoryEnhancementProviderClient
        from .memory_enhancement_sidecar import run_provider_sidecar

        bearer_token = ""
        if args.token_env:
            bearer_token = os.environ.get(args.token_env, "")
            if not bearer_token:
                print("Sidecar bearer token env var is not set", file=sys.stderr)
                sys.exit(2)
        provider_token = ""
        if args.provider_token_env:
            provider_token = os.environ.get(args.provider_token_env, "")
            if not provider_token:
                print("Provider token env var is not set", file=sys.stderr)
                sys.exit(2)
        print(f"Provider memory enhancement sidecar listening on http://{args.host}:{args.port}/enhance")
        client = ResolvingMemoryEnhancementProviderClient(
            api_key_client_factory=lambda token: ProviderModelMemoryEnhancementClient(
                bearer_token=token or provider_token
            )
        )
        run_provider_sidecar(
            args.host,
            args.port,
            client=client,
            bearer_token=bearer_token,
        )
        return

    if args.enhance_command == "grade-runs":
        from .memory_enhancement_grading import (
            grade_memory_enhancement_records,
            load_action_teachings,
            load_grade_records,
        )

        records = load_grade_records(args.input)
        expected_actions = load_action_teachings(args.teachings) if args.teachings else args.expected_action
        result = grade_memory_enhancement_records(
            records,
            expected_action_teachings=expected_actions or None,
        )
        lines = [
            f"Models graded: {result['model_count']}",
            "Passing models: " + (", ".join(result["passing_models"]) if result["passing_models"] else "none"),
        ]
        for model in result["models"]:
            verdict = "PASS" if model["gate"]["pass"] else "FAIL"
            scores = model["scores"]
            lines.append(
                f"{model['model_label']}: {verdict} "
                f"entity={scores['typed_entities']['pairwise_mean']:.3f} "
                f"topic={scores['topics']['pairwise_mean']:.3f} "
                f"actions={'PASS' if scores['action_items']['pass'] else 'FAIL'}"
            )
        _emit_json_or_lines(result, json_output=args.json, lines=lines)
        return

    print("Missing enhance command. Try: chimera-memory enhance provider-plan", file=sys.stderr)
    sys.exit(2)


def _oauth_list_lines(payload: dict) -> list[str]:
    lines = [
        f"OAuth store: {payload.get('store_path')}",
        f"Credentials: {payload.get('credential_count', 0)}",
    ]
    for credential in payload.get("credentials", []):
        provider = credential.get("provider_id")
        scheme = credential.get("scheme")
        ref_hash = credential.get("ref_hash_prefix")
        active = "active" if credential.get("active") else "inactive"
        transport = credential.get("transport") or ""
        lines.append(f"- {provider} {scheme}:{ref_hash} {active} transport={transport}")
    return lines


if __name__ == "__main__":
    main()
