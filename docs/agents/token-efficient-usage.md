# Token-Efficient Agent Usage

Use this guide when you need to work in ChimeraMemory without loading the whole
repo or the full README into context. It is a routing map and tool-choice guide,
not a replacement for the deeper docs.

## One-Screen Model

ChimeraMemory has two memory layers behind one CLI/MCP server:

- Transcript layer: Claude Code, Codex, Hermes, and legacy Discord-shaped
  session JSONL gets parsed, sanitized, indexed into SQLite/FTS5, and
  optionally embedded.
- Curated memory layer: markdown plus YAML frontmatter memories get indexed,
  scored, zoned, reviewed, traced, and queried through the same server.

The baseline stays local-first: SQLite, local files, local fastembed/BGE
embeddings, MCP stdio, and explicit persona/project/global scope boundaries.
Provider-backed enhancement is optional sidecar/worker work and starts as
review-gated evidence, not instruction-grade memory.

## Start With These, Not Everything

For most coding tasks, read in this order:

1. `AGENTS.md` for repo contract, validation, and dual-source rules.
2. This file for token-efficient doc and tool routing.
3. `docs/agents/repo-map.md` only if you need file/module orientation.
4. `docs/agents/commands.md` only before running install, CLI, server, or test commands.
5. `docs/agents/boundaries.md` only before changing module ownership or public surfaces.
6. `docs/agents/security.md` only for paths, secrets, auth, transcripts, imports, subprocesses, migrations, browser/client output, or provider work.
7. The matching playbook from `AGENTS.md` only when the task fits.

Use `README.md` as the public product/tool reference, not as a default
read-through. Use `docs/MODULE_LAYOUT.md` when deciding where code belongs.

## Documentation Routing

| Need | Read |
|---|---|
| Human-facing overview, setup, MCP tool list, config, CLI reference | `README.md` |
| Which module owns a feature or test | `docs/MODULE_LAYOUT.md` |
| Commands and focused test choices | `docs/agents/commands.md`, `docs/agents/validation.md` |
| Architecture and ownership boundaries | `docs/agents/boundaries.md` |
| Persona, secret, path, provider, import, or subprocess safety | `docs/agents/security.md` |
| Enhancement sidecar contract and threat model | `docs/MEMORY_ENHANCEMENT_SIDECAR.md` |
| CLI-worker enhancement transport | `docs/MEMORY_ENHANCEMENT_CLI_WORKER.md` |
| Persona/project/global memory scope and persona tool diet | `docs/FEDERATED_MEMORY_SCOPE.md` |
| Codex Desktop without persona and cleanup/refactor roadmap | `docs/CODEX_DESKTOP_SCOPE_AND_CODE_AUDIT.md` |
| Active harness warning behavior | `docs/ACTIVE_HARNESS_LEASE.md` |
| Legacy memory migration only after explicit curation | `docs/MIGRATION_PIPELINE.md` |
| OB1 comparison and roadmap background | `docs/OB1_COMPARISON.md` |

Do not read every document by default. Search headings first with `rg -n "^#"
README.md docs`, then open the one section that matches the task.

## MCP Tool Choice

The authoritative MCP tool registration is `chimera_memory/server.py`. The
surface filter is `chimera_memory/mcp_surface.py`. The README is the public
reference for what the tools do.

For transcript recall, prefer surface-appropriate compact flows. On current
Codex Desktop/CLI project surfaces, transcript fallback is opt-in through the
Codex wrapper/harness path; generic transcript recall tools are not exposed by
default. On full/persona surfaces with legacy Discord-shaped transcript rows,
use the compact compatibility flow:

1. `discord_recall_index(search="...")` to scan small previews.
2. Pick relevant IDs.
3. `discord_detail(ids=[...])` for full content only where needed.

Use `discord_recall` only when direct full-content recall is actually needed.
Use `semantic_search` for conceptual transcript search. Use `session_list` to
orient by session before pulling content.

For curated memory recall, prefer:

- `memory_stats` for a cheap scoped corpus overview.
- `memory_context_pack` for a bounded, fenced pre-turn pack.
- `memory_recall` for fuzzy/conceptual memory lookup; it filters weak semantic
  hits, low query-term coverage, and unsafe governance states by default, while
  exact FTS/body matches can rescue below-floor semantic hits only when stricter
  term coverage is present. Explicit `min_similarity` values above the default
  disable that rescue.
- `memory_search` for exact FTS5 search; it filters restricted, blocked, and
  non-evidence rows by default.
- `memory_query` for structured filters such as type, importance, status, tags, or `about`.

`memory_search`, `memory_query`, and context-pack/transcript fallback traces
separate candidate availability from returned context: `result_count` is the
filtered result set before limits or token budgets, and `returned_count` is what
actually reached the caller. `memory_query` records only whether `source_uri`
was supplied, not the raw URI value; exact `memory_search` does the same.

Use `include_restricted=true` or `include_blocked=true` only for deliberate
review/debug work. Direct retrieval, stats, and provenance metadata lookups
always exclude rows marked `can_use_as_evidence=false`.

For normal persona work, reason in the persona belt from
`docs/FEDERATED_MEMORY_SCOPE.md`:

- `memory_context_pack`
- `memory_recall`
- `memory_remember`
- `memory_promote_snapshot`
- `memory_review`
- `memory_diagnose`

Use `CHIMERA_MEMORY_MCP_SURFACE=codex` for Codex Desktop project mode with the
project/global memory belt, exact `memory_search`, structured `memory_query`,
scoped `memory_stats`, and live-retrieval diagnostics. Codex does not expose
generic transcript recall MCP tools; use the Codex exec wrapper with
`--include-transcripts` for bounded project transcript fallback. Use `persona`
to expose the persona memory belt plus transcript recall tools. Use
`persona_memory` for only the memory belt. Use `worker` only for enhancement
workers.

For Codex CLI prompt wrapping, `chimera-memory codex exec --include-transcripts`
adds bounded snippets only from sessions whose `cwd` is inside the current
project workspace. Use it when curated memory is sparse but project-local
session history is relevant.

For diagnostics, prefer `memory_diagnose` modes before inspecting raw DBs or
logs. Important modes include tools, harness, health, enhancement, and
cli_worker. Use `memory_diagnose(mode="context")` when you need a compact
answer to whether CM has recently attempted or returned prompt-context evidence
without exposing prompt text or memory bodies. Context diagnostics render stored
UTC timestamps with local-time companions so UTC day rollovers are explicit.

For imports and generated memory, use plan/preview modes first. Imported,
generated, auto-captured, and sidecar-produced outputs start as evidence-only
and pending review unless the docs and tests say otherwise.

For enhancement, start with deterministic and safe surfaces:

- `memory_enhancement_provider_plan` or `chimera-memory enhance provider-plan --json`
- `memory_enhancement_enqueue`
- `memory_enhancement_dry_run` or `chimera-memory enhance dry-run`
- worker tools only on the `worker` surface: `memory_worker_claim_next`,
  `memory_worker_submit_result`, `memory_worker_heartbeat`, `memory_worker_budget`

## Coding Workflow

Before editing, locate the owner:

- MCP and startup behavior: `server.py`, `mcp_surface.py`
- CLI: `cli.py`, `codex_setup.py`
- Transcript parsing/index/search: `parser.py`, `indexer.py`, `search.py`, `embeddings.py`
- Curated memory facade and compatibility: `memory.py`
- Focused memory features: use `docs/MODULE_LAYOUT.md`

Keep `memory.py` as facade and compatibility surface. Put new schema, review,
audit, importer, provider, OAuth, sidecar, or worker behavior in the focused
module that owns it, then re-export only when compatibility requires it.

Prefer focused searches over broad reads:

```powershell
rg -n "tool_name|function_name|config_key" chimera_memory tests docs
rg --files chimera_memory tests docs
```

Public surface changes need docs and tests. If you add or change an MCP tool,
CLI command, config key, env var, user-facing receipt, or import/export flow,
update the README or the relevant routed doc.

## Validation Shortcut

For docs-only agent changes:

```powershell
git diff -- AGENTS.md CLAUDE.md docs/agents
git status --short
```

For focused runtime edits:

```powershell
python -m py_compile chimera_memory/<module>.py
python -m pytest tests/test_<area>.py
```

For core parser/index/search/memory behavior, also run:

```powershell
python tests/test_persona_scope.py
python tests/test_memory_watcher.py
python tests/test_indexer.py
python tests/test_search.py
python tests/test_parser.py
```

Run `python -m pytest` when behavior touches shared code, public surfaces, or
retrieval/indexing contracts.

## Do Not Waste Tokens On

- Reading all docs when one routed doc is enough.
- Calling direct full-content transcript recall before trying the compact
  surface-appropriate flow.
- Dumping raw transcripts, DB rows, provider errors, or local paths into browser/client surfaces.
- Treating generated or imported memory as instruction before review.
- Adding new logic to `memory.py` when a focused module owns the behavior.
- Replacing local-first SQLite/FTS5/vector/RRF architecture without empirical receipts.
- Broad prettification, drive-by refactors, or decorative comments.

## Stop And Re-Check When

- A change crosses persona, project, or global memory boundaries.
- A write might touch runtime DBs, transcript JSONL, OAuth/auth files, `.env`, generated worker homes, or provider credentials.
- A provider call, subprocess, sidecar, import, migration, or browser/client output is involved.
