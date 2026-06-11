---
id: chimera-memory-drift-and-open-decisions
title: Drift And Open Decisions
scope: repo
kind: question
status: active
trust: medium
created: 2026-06-09
updated: 2026-06-11
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - README.md
  - docs/OB1_COMPARISON.md
  - docs/MEMORY_ENHANCEMENT_CLI_WORKER.md
  - docs/CODEX_DESKTOP_SCOPE_AND_CODE_AUDIT.md
---

# Drift And Open Decisions

## Current Documentation Drift

- `README.md` Phase 7 still says GitHub Actions CI is future, but
  `.github/workflows/ci.yml` exists and runs compile plus pytest.
- `README.md` Phase 7 lists HTTP/SSE MCP transport for service-mode as future,
  while `chimera-memory serve --transport streamable-http` exists. The still-open
  question is resident owner-process service-mode, not local HTTP transport.
- `docs/OB1_COMPARISON.md` says CM is stdio-only in the OB1 comparison, which is
  stale for streamable HTTP.
- `docs/agents/repo-map.md` calls the CLI worker transport future, while
  `docs/MEMORY_ENHANCEMENT_CLI_WORKER.md` says protocol, exclusion, budget,
  fake-worker, Codex supervisor, Claude supervisor, and Antigravity supervisor
  slices are implemented.
- `docs/agents/repo-map.md` says no `.github` or `scripts` directory existed at
  the agent setup audit. Both exist now.
- Some provider/sidecar docs intentionally mix implemented status with future
  plans. Read the status paragraph and current code before treating a section as
  either shipped or pending.
- `README.md` lists `networkx` as a dependency, but `pyproject.toml` and
  `uv.lock` do not require it and current code treats graph support as optional.
- `pyproject.toml` describes only Claude Code transcript indexing, which is
  narrower than current Claude Code, Codex, and Hermes support.

## Open Decisions

- Decide whether to update README and OB1 comparison roadmap text to distinguish
  implemented streamable HTTP from unresolved service-mode ownership.
- Decide whether to update `docs/agents/repo-map.md` now so future agents do not
  trust its stale no-`.github`/no-`scripts` claim.
- Decide whether README should remove `networkx` from required dependency text
  or pyproject should intentionally add it as an optional extra.
- Decide whether package metadata should be updated to describe Codex and Hermes
  support.
- Decide whether service-mode should become a resident single-owner process per
  persona DB, or stay as optional shared local HTTP for Codex.
- Decide how aggressively to split `server.py`, `cli.py`, `memory.py`,
  `memory_cli_worker_supervisor.py`, and OAuth modules.
- Decide whether to run a standalone formatting pass. Existing docs warn that
  full-repo formatting should be separate from behavior changes.
- Decide when Stage 2 enhancement writeback can graduate beyond shadow/review
  gates.

## Resolved Decisions

- Multi-project live watcher coverage is now covered: every configured
  `CHIMERA_MEMORY_PROJECT_ROOTS` entry is scheduled, create events under each
  root index as the matching `project:<id>`, and no-persona Codex/project mode
  rejects persona-path events at the handler boundary.

## Guidance Until Resolved

Prefer current code, tests, and CI over stale roadmap text. Do not combine broad
formatting, facade cleanup, service-mode work, or provider behavior changes with
unrelated feature work.
