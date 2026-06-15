---
id: chimera-memory-runtime-architecture-and-module-ownership
title: Runtime Architecture And Module Ownership
scope: repo
kind: system
status: active
trust: high
created: 2026-06-09
updated: 2026-06-11
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - docs/agents/repo-map.md
  - docs/agents/boundaries.md
  - docs/MODULE_LAYOUT.md
  - chimera_memory/memory_relevance.py
  - chimera_memory/memory_live_retrieval.py
  - chimera_memory/codex_context.py
  - tests/test_codex_context.py
  - tests/test_memory_live_retrieval.py
  - pyproject.toml
---

# Runtime Architecture And Module Ownership

## Package Shape

ChimeraMemory is a Python 3.10+ package named `chimera-memory` with console
script:

```text
chimera-memory = chimera_memory.cli:main
```

Core dependencies include `watchdog`, `fastembed`, `httpx`, `pyyaml`, and
optional `mcp`, `gpu`, and `dev` extras.

## Facade Rule

`chimera_memory/memory.py` remains the public facade and compatibility surface.
It owns file discovery, persona-scoped indexing orchestration, search/recall
orchestration, stats, consolidation, watcher integration, and compatibility
re-exports.

Do not add new schema, review, sidecar, audit, importer, provider, OAuth, or
worker logic directly to `memory.py`. Place new behavior in the focused module
that owns it, then re-export only if compatibility requires it.

## Focused Ownership

- `memory_schema.py`: SQLite DDL and additive migrations.
- `memory_governance.py`: provenance, lifecycle, review, sensitivity, and
  instruction-grade trust rules.
- `memory_observability.py`: recall traces, recall items, audit events, safe
  JSON payload helpers, and read-side trace/audit redaction for public
  diagnostics.
- `memory_health.py`: health snapshots and cheap background checks.
- `memory_live_retrieval.py` and `memory_context_pack.py`: proactive recall and
  bounded context packs.
- `memory_relevance.py`: shared deterministic relevance gates for weak broad
  matches, traceable filtering policy, and context-fence cleaning for
  `chimera-memory-context`, `chimera-transcript-context`, legacy
  `memory-context`, and `supermemory-context` blocks.
- `memory_live_retrieval.py`: proactive recall planning must run term
  extraction over cleaned context text so prior injected memory or transcript
  evidence cannot become fresh topic-shift signal.
- `memory_scope.py`: global/project/persona scope normalization, project-root
  resolution, and SQL scope filters. Explicit `CHIMERA_MEMORY_PROJECT_ID`
  controls single-project indexing; folder-derived ids are fallback.
- `harness.py`: active-harness identification (Claude Code / Codex / standalone
  Hermes) for transcript indexing. Near-stdlib, never raises, never leaks paths.
  Explicit env wins; otherwise process-injected running signals
  (`CLAUDECODE`/`CODEX_SANDBOX`, not install vars) > session-dir signature >
  per-file content sniff > Claude default. Consulted by
  `server.get_default_jsonl_dir`, `indexer` parser selection, and the
  active-harness lease.
- `hermes_setup.py`: standalone Hermes setup helpers (template/doctor/install).
  Never mutates Hermes `config.yaml`; persona-scoped and path-safe; `install`
  writes per-persona launcher scripts and defaults to dry-run.
- `memory.py`: compatibility facade plus low-level discovery/index/watch glue.
  Full-reindex and watcher discovery skip hidden/cache/auth/symlink child paths
  under managed roots without rejecting configured hidden roots themselves.
- `transcript_context.py`: bounded Codex transcript fallback snippets, filtered
  to sessions whose `cwd` is inside the current project workspace.
- `codex_context.py`: no-persona Codex Desktop/CLI prompt-context wrapping for
  project/global memory evidence.
- `memory_review.py`: manual review transitions and audit logging.
- `memory_auto_capture.py` and `memory_authored_writeback.py`: governed memory
  write planning and safe persistence.
- `memory_entities.py`, `memory_entity_wiki.py`, `memory_file_edges.py`, and
  `memory_file_edge_classifier.py`: entity graph and typed reasoning edges.
- `memory_pyramid.py` and `memory_profile_export.py`: summaries and portable
  exports.
- `memory_import_*.py`: source-specific import parsing and governed write plans.
- `memory_enhancement*.py`, `memory_provider_governor.py`,
  `memory_cli_worker_supervisor.py`, and `enhancement_worker.py`: enhancement,
  queue, provider, budget, OAuth, worker, and runner behavior.
- `memory_frontmatter.py`: shared frontmatter parsing.

## Import Direction

Allowed shape:

```text
memory.py facade
  imports focused modules

focused modules
  import lower-level helpers or explicitly allowed sibling helpers

schema/governance/observability
  stay near-stdlib and avoid behavior-module imports
```

Avoid focused modules importing `memory.py`, schema importing behavior modules,
review and queue importing each other, or provider/OAuth code inside queue
modules.

## Test Strategy

Most features have a focused test file under `tests/`. Use the focused test
first, compile touched runtime modules on import-risk changes, then broaden to
full pytest when shared behavior or public surfaces move.
