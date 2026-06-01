# ChimeraMemory Agent Instructions

`AGENTS.md` is the canonical front door for coding agents in this repo.
`CLAUDE.md` imports it so Claude Code stays synchronized. Deeper guidance lives
under `docs/agents/` and is routed from this file.

## Purpose

ChimeraMemory indexes Claude Code, Codex, and Hermes session transcripts into
queryable local SQLite. It is both a lightweight standalone Python library and
an MCP server for agent integration. The default architecture is local-first:
SQLite, markdown plus YAML frontmatter, fastembed/BGE embeddings, MCP stdio, and
global, project, and persona-scoped memory boundaries.

Two consumers matter:

- Standalone CM: any project that installs `chimera-memory` directly.
- PersonifyAgents vendor copy: PA mirrors this repo under
  `../PersonifyAgents/vendor/chimera-memory/`.

## Start Here

1. Read `docs/agents/token-efficient-usage.md` for the shortest safe path through CM docs, tools, and validation.
2. Read `README.md` only when you need the human-facing overview, CLI, MCP tools, or config reference.
3. Read `docs/agents/repo-map.md` to understand the source, docs, and tests.
4. Read `docs/agents/commands.md` before installing, serving, testing, or using CLI helpers.
5. Read `docs/agents/boundaries.md` before changing architecture or module ownership.
6. Read `docs/agents/validation.md` before finalizing work.
7. Read `docs/agents/security.md` before touching paths, auth, transcripts, network calls, process spawning, migrations, or browser-facing output.
8. Read `docs/agents/README.md` when you need the full agent-doc index.

## Operating Contract

- Inspect relevant code, tests, docs, config, and command surfaces before editing.
- Prefer narrow finished changes over broad partial changes.
- Keep new behavior additive unless Charles explicitly greenlights a replacement.
- Preserve persona scoping. `TRANSCRIPT_PERSONA` and cross-persona folder rules are privacy boundaries.
- Keep generated memory metadata reviewable. Generated write paths default to generated, pending review, evidence-only.
- Do not use `chimera_memory/memory.py` as a dumping ground. It is the facade and compatibility surface.
- Avoid unrelated cleanup, drive-by refactors, and dependency churn.
- If adding an env var or public config key, document it in `README.md` or the relevant docs file.
- If adding a public function re-exported through `memory.py` or package `__init__`, update the facade/re-export and tests.
- User-facing errors should name what happened and what to do next without leaking raw paths, commands, secrets, or stderr to browser/client surfaces.
- Runtime-critical operational comments must include why, scar, source, and test. If you cannot name the scar, do not add the comment.
- Never commit runtime DBs, session transcripts, tokens, `.env`, secrets, local auth files, or generated caches.

## Architecture Rules

- CM stays local-first by default. Do not add Supabase, Postgres, pgvector, cloud LLMs, or hosted services to the baseline path.
- Do not replace the retrieval core without empirical receipts. The current core is FTS5 plus vector search with Reciprocal Rank Fusion and re-ranking.
- Declarative registries are preferred over scattered conditionals.
- Label data provenance explicitly: fallback, live, help_probe, cached, generated, or user_supplied.
- Browser-safe projections must hide raw local paths, commands, secrets, and stderr.
- Schema migrations must be additive and idempotent.
- Optional provider/model work belongs behind explicit sidecar, runner, credential-reference, and budget-governor boundaries.

## Playbook Routing

Read these only when the task matches:

- For multi-file, architecture-sensitive, or refactor work, read `docs/agents/playbooks/implementation-style.md`.
- For CLI, MCP, config, import/export, dashboard, or other user-visible behavior, read `docs/agents/playbooks/user-facing-completeness.md`.
- For bug fixes, validation strategy, review, or final risk assessment, read `docs/agents/playbooks/verification-and-review.md`.
- For auth, OAuth, secrets, filesystem paths, shell commands, subprocesses, network calls, migrations, transcripts, or user data, read `docs/agents/playbooks/security-and-boundaries.md`.

## Current Lift Status

The OB1-inspired lift is implemented through Phase 5e dashboard and
auto-capture plus a first Phase 6 entity-graph slice.

Implemented highlights:

- SQLite hygiene, content fingerprinting, idempotency, partial indexes, Codex commands, and comparison docs.
- Memory-enhancement sidecar spec, queue, deterministic dry-run worker, provider policy, budget caps, credential-reference boundary, safe invocation envelope, and injected-client runner boundary.
- Recall traces, recall items, audit events, review queue, governance metadata, sensitivity tiers, and use-policy fields.
- PWA memory dashboard, session-close auto-capture protocol, live-retrieval dry-run checks, local entity graph, typed file/entity edges, deterministic pyramid summaries, import scaffolding for major sources, and portable profile export.
- `memory.py` has been split into focused schema, governance, observability, review, enhancement queue, frontmatter, import, entity, and provider modules.

Pending larger work:

- Real OAuth/model adapter for memory enhancement.
- Classifier integration for edge creation and additional import pipelines.

Use these references for deeper context:

- `docs/OB1_COMPARISON.md`
- `docs/MEMORY_ENHANCEMENT_SIDECAR.md`
- `docs/MEMORY_ENHANCEMENT_CLI_WORKER.md`
- `docs/MODULE_LAYOUT.md`
- `docs/CODEX_DESKTOP_SCOPE_AND_CODE_AUDIT.md`

## Dual-Source Rule

This repo is the source of truth. When runtime CM code changes, land and verify
the change here first, then mirror into PersonifyAgents if `../PersonifyAgents`
exists:

1. Edit, test, commit, and push in this repo.
2. From `../PersonifyAgents`, run `python scripts/sync-chimera-memory.py`.
3. Stage `vendor/chimera-memory/` and commit in PA as `vendor: sync CM <sha>`.
4. Run PA vendor tests plus PA runtime/PWA tests.
5. Push PA and verify CI when the vendor change affects runtime behavior.

Docs-only agent setup changes do not need the PA vendor sync unless Charles asks
for the agent docs to be mirrored.

## Validation

Run the smallest relevant checks and report pass, fail, or not-run honestly.

Baseline commands:

```powershell
python -m pytest
```

When refactoring imports or touching runtime modules:

```powershell
python -m py_compile chimera_memory/<module>.py
python -m pytest tests/test_<area>.py
```

When touching indexing/search/parser/memory core, also run:

```powershell
python tests/test_persona_scope.py
python tests/test_memory_watcher.py
python tests/test_indexer.py
python tests/test_search.py
python tests/test_parser.py
```

Docs-only agent setup should at minimum verify links, routing, and orphan-free
playbooks. See `docs/agents/validation.md`.

## Final Response

Include what changed, key files, validation run, assumptions, risks or skipped
checks, and useful next steps. Never bury failed validation.
