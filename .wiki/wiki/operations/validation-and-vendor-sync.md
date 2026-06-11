---
id: chimera-memory-validation-and-vendor-sync
title: Validation And Vendor Sync
scope: repo
kind: operation
status: active
trust: high
created: 2026-06-09
updated: 2026-06-09
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - docs/agents/validation.md
  - docs/agents/commands.md
  - AGENTS.md
  - .github/workflows/ci.yml
---

# Validation And Vendor Sync

## Docs And Wiki

For docs/wiki-only changes:

```powershell
python "$env:USERPROFILE\.codex\skills\chimera-wiki\scripts\chimera_wiki.py" lint --root .
git diff -- AGENTS.md CLAUDE.md docs/agents .wiki
git status --short
```

Manual checks:

- `AGENTS.md` has `Start Here`.
- `CLAUDE.md` points to `AGENTS.md`.
- Every file under `docs/agents/` is indexed from `docs/agents/README.md`.
- Paths and commands are accurate.

## Runtime Changes

Compile touched runtime modules when imports or syntax risk changed:

```powershell
python -m py_compile chimera_memory/<module>.py
```

Run the focused pytest file for the touched area:

```powershell
python -m pytest tests/test_<area>.py
```

Run the full suite when behavior touches shared code, public surfaces, or core
retrieval/indexing contracts:

```powershell
python -m pytest
```

## Core Retrieval And Parser Changes

When touching `memory.py`, `indexer.py`, `parser.py`, `search.py`,
`embeddings.py`, persona scoping, or transcript DB behavior, also run:

```powershell
python tests/test_persona_scope.py
python tests/test_memory_watcher.py
python tests/test_indexer.py
python tests/test_search.py
python tests/test_parser.py
```

## CI

GitHub Actions CI exists and runs on push and pull request to `master`, across
Ubuntu and Windows with Python 3.10 and 3.12:

```powershell
python -m pip install -e ".[dev,mcp]"
python -m compileall chimera_memory
python -m pytest
```

## PersonifyAgents Vendor Sync

This repo is source of truth. When runtime CM changes must be mirrored and
`../PersonifyAgents` exists:

1. Commit and push CM first.
2. From `../PersonifyAgents`, run `python scripts/sync-chimera-memory.py`.
3. Stage and commit `vendor/chimera-memory/` as `vendor: sync CM <sha>`.
4. Run PA vendor tests plus PA runtime/PWA tests.
5. Push PA and verify CI when runtime behavior changed.

Docs-only agent setup changes do not need vendor sync unless Charles asks.
