# Chimera-Memory Source Pointers

Collected: 2026-06-09
Collector: Codex
Provenance: live local repo inspection

This raw file records the sources consulted for the initial Chimera-Memory wiki
build. It is a pointer capture, not a copied snapshot of every source.

## Consulted Source Files

- `AGENTS.md` - previous agent front door and current lift status.
- `README.md` - public overview, setup, CLI, MCP tools, config, schema, roadmap, and env vars.
- `pyproject.toml` - package metadata, dependencies, optional extras, and console script.
- `.github/workflows/ci.yml` - current remote CI matrix and commands.
- `CLAUDE.md` - Claude Code pointer to `AGENTS.md`.
- `install-codex.ps1` - Windows Codex setup helper.
- `scripts/bootstrap-cm-venv.ps1`, `scripts/start-cm-http.ps1`, `scripts/install-cm-http-autostart.ps1` - Windows venv, local HTTP server, and autostart helpers.
- `docs/agents/README.md` - active agent docs index.
- `docs/agents/token-efficient-usage.md` - shortest safe route through docs and tools.
- `docs/agents/repo-map.md` - top-level layout, runtime entry points, focused modules, and test map.
- `docs/agents/commands.md` - setup, CLI, MCP, enhancement, test, and config commands.
- `docs/agents/boundaries.md` - architectural non-negotiables, module ownership, and import direction.
- `docs/agents/security.md` - local-first, persona, sensitive-file, provider, subprocess, migration, and generated metadata safety.
- `docs/agents/validation.md` - validation order and focused test map.
- `docs/MODULE_LAYOUT.md` - detailed module ownership and import direction.
- `docs/FEDERATED_MEMORY_SCOPE.md` - global/project/persona scope and persona tool-surface policy.
- `docs/MEMORY_ENHANCEMENT_SIDECAR.md` - sidecar contract, provider policy, shadow mode, generated synthesis, and writeback policy.
- `docs/MEMORY_ENHANCEMENT_CLI_WORKER.md` - CLI worker transport, worker-only tool surface, supervision, and budget posture.
- `docs/ACTIVE_HARNESS_LEASE.md` - warning-only active harness lease behavior.
- `docs/CODEX_DESKTOP_SCOPE_AND_CODE_AUDIT.md` - no-persona Codex project mode, validation receipts, and refactor risks.
- `docs/MIGRATION_PIPELINE.md` - legacy migration workflow and hard stops.
- `docs/OB1_COMPARISON.md` - historical OB1 lift rationale and remaining comparisons.
- `chimera_memory/mcp_surface.py` - authoritative MCP surface filter.
- `chimera_memory/server.py` - MCP server, tool registration, startup workers, and streamable HTTP entry.
- `chimera_memory/cli.py` - console script command surface.
- `chimera_memory/codex_setup.py` - Codex config template, install, doctor, and HTTP/stdio detection behavior.
- `tests/` - focused test map and current coverage surface.

## Live Worktree Observation

At collection time, `git status --short --branch` reported a clean worktree on
`master...origin/master`.

## Noted Drift

- `README.md` roadmap still says GitHub Actions CI is future even though
  `.github/workflows/ci.yml` exists.
- `README.md` roadmap still lists HTTP/SSE service-mode as future, while the
  CLI/server currently support `streamable-http`; broader service-mode ownership
  remains a separate unresolved architecture decision.
- Some docs still call CLI worker or provider runner pieces future while
  shipped slices exist.
- `docs/agents/repo-map.md` says no `.github` or `scripts` directory existed at
  the agent setup audit, but both exist now.
- `README.md` lists `networkx` in compatibility/dependencies text, while
  `pyproject.toml` and `uv.lock` do not make it a required dependency; current
  code treats graph analysis support as optional.
- `pyproject.toml` still describes only Claude Code transcript indexing even
  though current docs and code support Claude Code, Codex, and Hermes.
