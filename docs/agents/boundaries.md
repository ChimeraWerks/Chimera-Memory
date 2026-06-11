# Boundaries

## Architectural Non-Negotiables

- Keep CM local-first by default: SQLite, markdown plus YAML frontmatter, local embeddings, MCP stdio.
- Do not add Supabase, Postgres, pgvector, hosted vector DBs, or cloud LLM requirements to the default path.
- Do not replace FTS5 plus vector search, Reciprocal Rank Fusion, and re-ranking without empirical receipts.
- Treat persona scoping as a privacy boundary. Do not ignore `TRANSCRIPT_PERSONA`, persona ids, or cross-persona folder rules.
- Keep generated memory metadata review-gated and evidence-only until human confirmation.
- Add sidecars, traces, governance fields, review queues, adapters, and diagnostics additively.

## Module Ownership

`chimera_memory/memory.py` is the public facade and compatibility layer. It owns
file discovery, persona-scoped indexing orchestration, search/recall
orchestration, stats, consolidation, watcher integration, and re-exports older
callers already use.

Do not add new schema, review, sidecar, audit, importer, provider, OAuth, or
worker logic directly to `memory.py`. Put behavior in the focused module that
owns it, then re-export through `memory.py` only when compatibility requires it.

Use `docs/MODULE_LAYOUT.md` as the detailed source for focused modules and test
mapping.

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

Avoid:

- focused modules importing `memory.py`
- schema importing queue, review, observability, provider, or facade behavior
- review and queue importing each other
- model, OAuth, or HTTP provider logic inside queue modules
- raw credential values in provider policy, queue failures, receipts, audits, or browser/client output

## Focused Ownership Summary

- `memory_schema.py`: SQLite DDL, additive migrations, prerequisite checks, `init_memory_tables`
- `memory_governance.py`: provenance, lifecycle, review, sensitivity, use-policy, instruction-grade trust rules
- `memory_observability.py`: recall traces, recall items, audit events, safe JSON payload helpers
- `memory_health.py`: local health snapshots and cheap background checks
- `memory_provider_governor.py`: provider usage ledger and budget allow/deny checks
- `memory_cli_worker_supervisor.py`: generated worker files, bounded CLI commands, launch/restart scaffolding
- `memory_live_retrieval.py`: deterministic proactive recall planning and miss/suggestion audit logging
- `memory_relevance.py`: shared deterministic candidate relevance gates
- `memory_context_pack.py`: scoped, filtered, token-capped memory context packs
- `memory_retrieval_trace_analysis.py`: post-hoc retrieval diagnostics through injected clients
- `memory_review.py`: human review state transitions and audit logging
- `memory_auto_capture.py`: session-close capture planning, governed markdown rendering, safe writes
- `memory_authored_writeback.py`: structured authored memory write planning and safe persistence
- `memory_entities.py`: local entity graph, entity/file links, explicit entity edges
- `memory_file_edges.py`: typed reasoning edges between memory files
- `memory_pyramid.py`: deterministic multi-resolution summaries
- `memory_import_*.py`: source-specific import parsing, governed markdown planning, safe writes
- `memory_profile_export.py`: portable context exports from reviewed memory
- `memory_enhancement.py`: model-free sidecar request/response contract
- `memory_enhancement_provider.py`: provider priority, model defaults, credential refs, budgets, failure categories
- `memory_model_catalog.py`: offline-first models.dev catalog parser/cache
- `memory_enhancement_runner.py`: injected-client provider runner boundary
- `memory_enhancement_queue.py`: enhancement job persistence and worker protocol
- `memory_frontmatter.py`: markdown frontmatter parsing shared by indexing and enqueue
- `enhancement_worker.py`: deterministic dry-run worker and fake worker harness

## Comment Rule

For runtime, adapter, process, filesystem, browser/server boundary, stream
parser, or CLI shim code, operational comments must include:

- why the code exists
- scar: the failure mode, platform quirk, upstream limit, or production incident
- source: checkable anchor such as an upstream issue, docs URL, ADR, smoke receipt, or named test
- test: the test that keeps the scar handled

If there is no scar, do not write the comment. Self-named helpers and trivial
branches do not need comments.

## Public Surface Changes

When adding or changing public functions, MCP tools, CLI commands, config keys,
or env vars:

- Update README or relevant docs.
- Add or update focused tests.
- Keep user-facing output safe and actionable.
- Preserve compatibility re-exports if callers already import through `memory.py` or package `__init__`.
- Include provenance labels for generated, fallback, cached, help_probe, live, or user_supplied data.

## PersonifyAgents Boundary

This repo is the source of truth. Runtime CM changes land here first. Only after
this repo is tested, committed, and pushed should the PA vendor copy be synced
from `../PersonifyAgents` using `python scripts/sync-chimera-memory.py`.
