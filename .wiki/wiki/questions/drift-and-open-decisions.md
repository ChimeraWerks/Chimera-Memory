---
id: chimera-memory-drift-and-open-decisions
title: Drift And Open Decisions
scope: repo
kind: question
status: active
trust: medium
created: 2026-06-09
updated: 2026-06-15
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - README.md
  - docs/OB1_COMPARISON.md
  - docs/MEMORY_ENHANCEMENT_CLI_WORKER.md
  - docs/CODEX_DESKTOP_SCOPE_AND_CODE_AUDIT.md
  - docs/AUDIT_REMEDIATION_2026-06-14.md
---

# Drift And Open Decisions

## Current Documentation Drift

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
  Claude-Code default. README harness rows and the "first-class transcript source"
  claim were corrected to match.
- Native Hermes parser added (2026-06-14): Hermes has TWO transcript modes. (1)
  Hermes running inside Claude Code writes Claude-format JSONL under
  `~/.claude/projects` and is detected as `claude-code`. (2) The standalone Hermes
  agent writes per-persona whole-file `~/.hermes/profiles/<persona>/sessions/
  session_*.json` — now parsed by a real `HermesParser` (selected via
  `CHIMERA_CLIENT=hermes` or that session-dir shape). Indexer file discovery and
  the watchdog are now parser-aware (`session_glob`: `*.jsonl` for Claude/Codex,
  `session_*.json` for Hermes); whole-file rewrites route through hash-based
  reindex, deduped by the transcript UNIQUE key. Standalone Hermes is
  persona-scoped (requires a persona; never scans across personas). Verified on
  real `asa` data (248 entries from 5 sessions; was 0 before). Open: a
  `chimera-memory hermes install` convenience flow (parity with `codex install`).
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
- Multi-agent audit fully remediated (2026-06-15): the 150-finding audit
  (Critical → Low) is closed. All 85 Low findings were re-verified against HEAD,
  then 71 fixed in 16 tested per-file batches, 4 confirmed already-fixed by the
  Medium batch, and 10 documented won't-fix/deferred with rationale. Durable
  contract reinforcements worth noting: the global review guard now always runs
  `scan_for_injection` and records findings (block stays coupled to
  default-availability, so restrict/reject remediation still writes but its
  findings are persisted, gsr-06); generated-provenance authored memory can no
  longer self-assert `review_status='confirmed'` (clamped to pending, wcp-10); the
  dead Google CloudCode discovery/onboarding cluster was removed from the provider
  sidecar (ec-05). Full tracker: `docs/AUDIT_REMEDIATION_2026-06-14.md`. Suite at
  841 passing (787 baseline + 54 regression tests).

## Guidance Until Resolved

Prefer current code, tests, and CI over stale roadmap text. Do not combine broad
formatting, facade cleanup, service-mode work, or provider behavior changes with
unrelated feature work.
