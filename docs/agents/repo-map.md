# Repository Map

## What This Repo Is

ChimeraMemory is a Python package and MCP server that indexes local agent
transcripts and curated markdown memories into SQLite. It serves Claude Code,
Codex, Hermes, and standalone users.

## Top-Level Layout

- `chimera_memory/` - runtime package, MCP server, CLI, indexing, retrieval, governance, importers, enhancement, and provider helpers
- `tests/` - pytest and legacy standalone tests covering parser, indexing, retrieval, governance, imports, workers, and provider boundaries
- `docs/` - architecture, OB1 comparison, sidecar, worker, migration, scope, and harness docs
- `docs/agents/` - coding-agent navigation and playbooks
- `.githooks/` - repository git hooks
- `.github/` - GitHub Actions workflows
- `scripts/` - Windows/bootstrap/startup helper scripts
- `.chimera-memory/` - local runtime state; ignored and not for commits
- `.venv/` - local virtual environment; ignored and not for commits
- `README.md` - human-facing overview, setup, MCP tools, CLI, config, schema, roadmap
- `pyproject.toml` - package metadata, dependencies, optional dev/MCP extras, console script
- `uv.lock` - locked Python dependency graph
- `install-codex.ps1` - Windows helper for editable install plus Codex MCP setup
- `AGENTS.md` - canonical agent instructions and routing hub
- `CLAUDE.md` - thin Claude Code pointer to `AGENTS.md`

Use the commands that exist in `.github/`, `scripts/`, `pyproject.toml`, and
the focused docs. Do not invent CI or service commands that are not present.

## Runtime Entry Points

- `chimera_memory/cli.py` - `chimera-memory` console script
- `chimera_memory/server.py` - MCP stdio server and tool surface
- `chimera_memory/memory.py` - public facade and compatibility surface for curated memory operations
- `chimera_memory/indexer.py` - transcript JSONL indexing and watcher behavior
- `chimera_memory/search.py` - transcript recall, FTS, vector/hybrid search support
- `chimera_memory/parser.py` and `chimera_memory/codex_setup.py` - transcript parsing and Codex integration helpers

## Focused Memory Modules

Use `docs/MODULE_LAYOUT.md` as the exhaustive source, but the main ownership
shape is:

- Schema and migrations: `memory_schema.py`
- Governance and trust metadata: `memory_governance.py`
- Recall traces and audits: `memory_observability.py`
- Health snapshots: `memory_health.py`
- Live retrieval, relevance gates, and context packs: `memory_live_retrieval.py`, `memory_relevance.py`, `memory_context_pack.py`
- Human review: `memory_review.py`
- Auto-capture and authored writeback: `memory_auto_capture.py`, `memory_authored_writeback.py`
- Entity graph and memory-file edges: `memory_entities.py`, `memory_entity_wiki.py`, `memory_file_edges.py`, `memory_file_edge_classifier.py`
- Pyramid summaries and profile export: `memory_pyramid.py`, `memory_profile_export.py`
- Importers: `memory_import_*.py`
- Enhancement contract, queue, runner, provider policy, model client, OAuth, HTTP sidecar, provider sidecar, worker supervisor: `memory_enhancement*.py`, `memory_provider_governor.py`, `memory_cli_worker_supervisor.py`, `enhancement_worker.py`
- Frontmatter parsing: `memory_frontmatter.py`

## Test Layout

Tests are mostly one file per module or feature. Prefer the focused test first,
then broaden:

- Parser/index/search/persona: `test_parser.py`, `test_indexer.py`, `test_search.py`, `test_persona_scope.py`, `test_memory_watcher.py`
- Governance/review/observability/schema: `test_memory_governance.py`, `test_memory_review.py`, `test_memory_observability.py`, `test_memory_schema_hygiene.py`
- Enhancement/provider/worker: `test_memory_enhancement*.py`, `test_cli_enhance.py`, `test_memory_provider_governor.py`
- Imports: `test_memory_import_*.py`
- Entity/edges/pyramid/profile: `test_memory_entities.py`, `test_memory_file_edges.py`, `test_memory_pyramid.py`, `test_memory_profile_export.py`
- Codex integration: `test_codex_setup.py`, `test_codex_parser.py`
- MCP/server startup: `test_server_startup.py`, `test_persona_tool_surface.py`, `test_whereami.py`

## Important Existing Docs

- `docs/MODULE_LAYOUT.md` is the deepest current map of module ownership and test mapping.
- `docs/MEMORY_ENHANCEMENT_SIDECAR.md` defines the sidecar contract, threat model, writeback policy, provider boundaries, and failure categories.
- `docs/MEMORY_ENHANCEMENT_CLI_WORKER.md` defines the CLI-worker transport and
  current Codex/Claude/Antigravity supervisor slices.
- `docs/MIGRATION_PIPELINE.md` describes legacy memory migration and hard stops.
- `docs/FEDERATED_MEMORY_SCOPE.md` describes federated memory storage and query policy.
- `docs/ACTIVE_HARNESS_LEASE.md` describes warning-only active harness lease behavior.
