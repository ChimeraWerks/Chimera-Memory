---
id: chimera-memory-drift-and-open-decisions
title: Drift And Open Decisions
scope: repo
kind: question
status: active
trust: medium
created: 2026-06-09
updated: 2026-06-12
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - README.md
  - docs/OB1_COMPARISON.md
  - docs/MEMORY_ENHANCEMENT_CLI_WORKER.md
  - docs/CODEX_DESKTOP_SCOPE_AND_CODE_AUDIT.md
---

# Drift And Open Decisions

## Current Documentation Drift

- `docs/OB1_COMPARISON.md` says CM is stdio-only in the OB1 comparison, which is
  stale for streamable HTTP.
- Some provider/sidecar docs intentionally mix implemented status with future
  plans. Read the status paragraph and current code before treating a section as
  either shipped or pending.

## Open Decisions

- Decide whether service-mode should become a resident single-owner process per
  persona DB, or stay as optional shared local HTTP for Codex.
- Decide how aggressively to split `server.py`, `cli.py`, `memory.py`,
  `memory_cli_worker_supervisor.py`, and OAuth modules.
- Decide whether to run a standalone formatting pass. Existing docs warn that
  full-repo formatting should be separate from behavior changes.
- Decide when Stage 2 enhancement writeback can graduate beyond shadow/review
  gates.

## Resolved Decisions

- Harness identification (2026-06-14): added `chimera_memory/harness.py`
  `detect_harness()` and wired it into `server.get_default_jsonl_dir`,
  `indexer.Indexer` parser selection, and the active-harness lease. The runtime
  no longer silently defaults to Claude for Codex/Hermes. Precedence: explicit
  `CHIMERA_CLIENT`/`TRANSCRIPT_JSONL_DIR` → process-injected running-harness env
  (`CLAUDECODE`/`CODEX_SANDBOX`; install-location vars like `HERMES_HOME`/
  `CODEX_HOME` are intentionally ignored because they persist in every shell) →
  on-disk session-dir signature → per-file JSONL content sniff at index time →
  Claude-Code default. Hermes writes Claude-format JSONL, so detected `hermes`
  maps to the Claude parser; a native Hermes parser is still open. README harness
  rows and the "first-class transcript source" claim were corrected to match.
- Persona transcript DB resolution unified (2026-06-14): the MCP query tools, the
  maintenance-lock path, and all five startup workers now share
  `server._resolve_transcript_db_path()`. Previously the workers ignored persona
  identity and split-brained indexing into the shared default DB while persona
  queries read the per-persona DB.
- Multi-project live watcher coverage is now covered: every configured
  `CHIMERA_MEMORY_PROJECT_ROOTS` entry is scheduled, create events under each
  root index as the matching `project:<id>`, and no-persona Codex/project mode
  rejects persona-path events at the handler boundary.
- README Phase 7 now distinguishes implemented GitHub Actions CI and shared
  streamable HTTP transport from the still-open resident service-mode owner
  process question.
- `docs/agents/repo-map.md` now lists `.github/`, `scripts/`, and the current
  CLI-worker supervisor slices.
- Package metadata now names Claude Code, Codex, Hermes, and MCP users.

## Guidance Until Resolved

Prefer current code, tests, and CI over stale roadmap text. Do not combine broad
formatting, facade cleanup, service-mode work, or provider behavior changes with
unrelated feature work.
