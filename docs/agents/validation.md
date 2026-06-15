# Validation

## Default Order

1. Run the smallest focused check that proves the change.
2. Run `python -m py_compile` for touched runtime modules when imports or syntax risk changed.
3. Run broader pytest when behavior touches shared code, public surfaces, or core retrieval/indexing.
4. Check `git diff` and `git status --short`.
5. Report pass, fail, or not-run clearly.

## Docs-Only Agent Setup

For changes limited to `AGENTS.md`, `CLAUDE.md`, or `docs/agents/`:

```powershell
git diff -- AGENTS.md CLAUDE.md docs/agents
git status --short
```

Manual checks:

- `AGENTS.md` has a `Start Here` section.
- Every file under `docs/agents/` is indexed from `docs/agents/README.md`.
- Every playbook is routed from `AGENTS.md` and has `Read this when` plus `Do not read this when`.
- `CLAUDE.md` points to `AGENTS.md`.
- Paths and commands are accurate for this repo.

## Runtime Module Changes

Compile touched modules:

```powershell
python -m py_compile chimera_memory/<module>.py
```

Run the focused pytest file for the touched area:

```powershell
python -m pytest tests/test_<area>.py
```

Then run full pytest when the change touches shared behavior:

```powershell
python -m pytest
```

## Core Indexing/Search/Parser Changes

When touching `memory.py`, `indexer.py`, `parser.py`, `search.py`,
`embeddings.py`, persona scoping, or transcript DB behavior, also run:

```powershell
python tests/test_persona_scope.py
python tests/test_memory_watcher.py
python tests/test_indexer.py
python tests/test_search.py
python tests/test_parser.py
```

## Focused Test Map

- Schema: `tests/test_memory_schema_hygiene.py`
- Governance: `tests/test_memory_governance.py`
- Observability: `tests/test_memory_observability.py`
- Health: `tests/test_memory_health.py`
- Live retrieval: `tests/test_memory_live_retrieval.py`
- Context packs: `tests/test_memory_context_pack.py`
- Retrieval trace analysis: `tests/test_memory_retrieval_trace_analysis.py`
- Review: `tests/test_memory_review.py`
- Auto-capture: `tests/test_memory_auto_capture.py`
- Authored writeback: `tests/test_memory_authored_writeback.py`
- Entities: `tests/test_memory_entities.py`
- Entity wiki: `tests/test_memory_entity_wiki.py`
- Memory-file edges: `tests/test_memory_file_edges.py`
- Edge classifier: `tests/test_memory_file_edge_classifier.py`
- Pyramid summaries: `tests/test_memory_pyramid.py`
- Profile export: `tests/test_memory_profile_export.py`
- Importers: `tests/test_memory_import_*.py`
- Enhancement contract and sidecar: `tests/test_memory_enhancement.py`, `tests/test_memory_enhancement_sidecar.py`
- Provider policy, catalog, governor, runner, sidecar, HTTP/model clients, OAuth: `tests/test_memory_enhancement_provider*.py`, `tests/test_memory_model_catalog.py`, `tests/test_memory_provider_governor.py`, `tests/test_memory_enhancement_runner.py`, `tests/test_memory_enhancement_http_client.py`, `tests/test_memory_enhancement_model_client.py`, `tests/test_memory_enhancement_oauth*.py`
- Queue and workers: `tests/test_memory_enhancement_queue.py`, `tests/test_memory_enhancement_worker.py`, `tests/test_memory_cli_worker_supervisor.py`
- CLI enhance: `tests/test_cli_enhance.py`
- Codex setup/parser: `tests/test_codex_setup.py`, `tests/test_codex_parser.py`
- MCP/server startup and persona surface: `tests/test_server_startup.py`, `tests/test_persona_tool_surface.py`, `tests/test_whereami.py`

## Completion Rules

- Do not call work complete with failing validation unless the user explicitly accepts the risk.
- If a check was skipped, say why.
- If a test command is expected to be long or environment-dependent, run the focused proof first and report the remaining risk.
