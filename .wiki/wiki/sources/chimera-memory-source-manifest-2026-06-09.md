---
id: chimera-memory-source-manifest-2026-06-09
title: Chimera-Memory Source Manifest
scope: repo
kind: source
status: active
trust: high
created: 2026-06-09
updated: 2026-06-09
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - AGENTS.md
  - README.md
  - docs/agents/token-efficient-usage.md
  - docs/agents/repo-map.md
  - docs/agents/boundaries.md
  - docs/agents/security.md
  - docs/agents/validation.md
  - docs/MODULE_LAYOUT.md
  - docs/FEDERATED_MEMORY_SCOPE.md
  - docs/MEMORY_ENHANCEMENT_SIDECAR.md
  - docs/MEMORY_ENHANCEMENT_CLI_WORKER.md
  - chimera_memory/server.py
  - chimera_memory/mcp_surface.py
  - .github/workflows/ci.yml
---

# Chimera-Memory Source Manifest

This page maps the sources used by the compiled wiki. Update it when major docs,
tests, public surfaces, or validation behavior move.

## Strong Sources

- Current code and tests are strongest for implemented behavior.
- `.github/workflows/ci.yml` is authoritative for current CI.
- `chimera_memory/server.py` owns MCP registration and startup workers.
- `chimera_memory/mcp_surface.py` owns MCP tool filtering.
- `chimera_memory/cli.py` owns the console command surface.
- `docs/agents/boundaries.md`, `docs/agents/security.md`, and
  `docs/agents/validation.md` are the active agent policy docs.
- `docs/MODULE_LAYOUT.md` is the deepest module ownership source.

## Product And User Sources

- `README.md` is the public user reference for setup, tool descriptions, config,
  env vars, roadmap, and examples.
- `docs/agents/token-efficient-usage.md` is the best route for agents trying to
  avoid loading the full README.

## Design Sources

- `docs/FEDERATED_MEMORY_SCOPE.md` defines global/project/persona scope policy,
  promotion, and persona tool-surface expectations.
- `docs/MEMORY_ENHANCEMENT_SIDECAR.md` defines the enhancement contract,
  provider policy, generated synthesis policy, shadow mode, and writeback gates.
- `docs/MEMORY_ENHANCEMENT_CLI_WORKER.md` defines the official-CLI worker
  transport, worker-only tool surface, and supervisor safeguards.
- `docs/CODEX_DESKTOP_SCOPE_AND_CODE_AUDIT.md` captures no-persona Codex project
  mode, validation receipts, and current refactor risks.

## Known Drift

- `docs/OB1_COMPARISON.md` still says CM is stdio-only in its historical OB1
  comparison, which is stale for streamable HTTP.
- Some provider/sidecar docs intentionally mix implemented status with future
  plans. Read the status paragraph and current code before treating a section as
  either shipped or pending.

## How To Use

Use this manifest as navigation and drift tracking. Read the underlying source
before making behavior-changing edits.
