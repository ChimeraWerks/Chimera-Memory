# ChimeraMemory Agent Instructions

`AGENTS.md` is the hard-rule routing hub. `CLAUDE.md` imports it so Claude Code
stays synchronized. Use `.wiki/` as the compiled living design wiki for current
repo understanding; keep broad architecture summaries there instead of
duplicating them here.

## Purpose

ChimeraMemory indexes local agent transcripts and curated markdown memories into
SQLite, serves them through CLI/MCP surfaces, and preserves scoped memory across
Claude Code, Codex, Hermes, and standalone users.

The baseline is local-first: SQLite, markdown plus YAML frontmatter, local
fastembed/BGE embeddings, MCP stdio or local streamable HTTP, and explicit
global/project/persona scope boundaries.

## Start Here

Read in this order for normal repo work:

1. `AGENTS.md`
2. `.wiki/SCHEMA.md`
3. `.wiki/index.md`
4. `.wiki/repo-brief.md`
5. `.wiki/wiki/sources/chimera-memory-source-manifest-2026-06-09.md`
6. `docs/agents/token-efficient-usage.md`
7. Only the task-relevant wiki page, `docs/agents/*` page, and source files

Use `README.md` as the public product/tool reference, not a default read-through.
Use `docs/MODULE_LAYOUT.md` when deciding where code belongs.

## Wiki / Living Design Wiki

`.wiki/` is the repo-local compiled LDD for agents. It organizes current memory
architecture, scope policy, module ownership, MCP/CLI surfaces, enhancement
boundaries, vendor sync, and known doc drift.

Current front-door pages:

- `.wiki/repo-brief.md`
- `.wiki/wiki/decisions/source-of-truth-and-scope-policy.md`
- `.wiki/wiki/synthesis/current-repo-state.md`
- `.wiki/wiki/systems/runtime-architecture-and-module-ownership.md`
- `.wiki/wiki/systems/mcp-cli-and-service-surfaces.md`
- `.wiki/wiki/systems/federated-scope-and-memory-governance.md`
- `.wiki/wiki/systems/enhancement-workers-and-provider-boundaries.md`
- `.wiki/wiki/questions/drift-and-open-decisions.md`

Treat wiki pages as synthesis, not sole truth. Behavior-changing claims must be
checked against current code, `AGENTS.md`, `README.md`, and routed docs.

Update `.wiki/` when work changes durable project understanding:

- local-first architecture or retrieval core
- transcript, curated-memory, scope, or governance contracts
- MCP tool surfaces, CLI commands, config keys, env vars, or setup flows
- module ownership, import direction, facade/re-export behavior, or public APIs
- enhancement sidecar, worker, provider, OAuth, queue, or budget boundaries
- importer, auto-capture, authored writeback, review, profile export, or
  generated metadata policy
- service-mode or startup worker policy
- contradictions found or resolved

Do not update `.wiki/` for trivial edits, temporary experiments, local DB state,
transcript contents, secrets, or generated caches.

When updating `.wiki/`:

1. Edit the relevant compiled page under `.wiki/wiki/`.
2. Cite source files in frontmatter or prose.
3. Label behavior-relevant provenance: `live`, `cached`, `fallback`,
   `generated`, `user_supplied`, `probe`, `review_gated`, or `evidence_only`.
4. Update `.wiki/index.md` when adding, removing, renaming, or archiving pages.
5. Update `.wiki/repo-brief.md` when boot assumptions change.
6. Append `.wiki/log.md`.

If a local page has cross-repo value, export a packet:

```powershell
python "$env:USERPROFILE\.codex\skills\chimera-wiki\scripts\chimera_wiki.py" export --root .
```

Do not import into a global hub unless a hub path is configured or Charles asks
for hub work.

## Source Of Truth

Canonical order:

1. Current code, scripts, and package metadata for implemented behavior.
2. `AGENTS.md` for hard agent routing and safety rules.
3. `docs/agents/token-efficient-usage.md`, `docs/agents/boundaries.md`,
   and `docs/agents/security.md` for active operating policy.
4. `.wiki/` for compiled synthesis, current-state navigation, and drift
   tracking.
5. `README.md` for the public user-facing reference.
6. Deep docs under `docs/` for design history, module maps, scope policy,
   enhancement contracts, and migration runbooks.
7. Runtime DBs, transcript JSONL, generated caches, worker homes, local auth
   stores, and installed/vendor copies as noncanonical outputs unless a task
   explicitly says otherwise.

When docs disagree, prefer current code for implemented behavior and record
meaningful drift in `.wiki/wiki/questions/drift-and-open-decisions.md`.

## Hard Architecture Rules

- Keep CM local-first by default: SQLite, local files, local embeddings, local
  CLI/MCP surfaces.
- Do not add Supabase, Postgres, pgvector, hosted vector DBs, cloud persistence,
  or cloud LLM requirements to the baseline path.
- Do not replace FTS5 plus vector search, Reciprocal Rank Fusion, and re-ranking
  without empirical receipts.
- Preserve persona scoping. `TRANSCRIPT_PERSONA`, `CHIMERA_PERSONA_ID`,
  project ids, and cross-persona folder rules are privacy boundaries.
- Generated, imported, auto-captured, and sidecar-produced memory starts as
  review-gated, evidence-only metadata unless human review or trusted provenance
  promotes it.
- Browser/client/MCP/user-facing output must not leak raw paths, raw commands,
  secrets, tokens, auth file contents, provider stderr, or unfiltered exceptions.
- Runtime-critical operational comments must include why, scar, and source. If
  you cannot name the scar, do not add the comment.
- Never commit runtime DBs, session transcripts, tokens, `.env`, local auth
  files, generated worker homes, or generated caches.

## Module Ownership

`chimera_memory/memory.py` is the public facade and compatibility surface. Do not
add new schema, review, sidecar, audit, importer, provider, OAuth, or worker
logic directly to it. Put behavior in the focused module that owns it, then
re-export through `memory.py` only when compatibility requires it.

Use `docs/MODULE_LAYOUT.md` and
`.wiki/wiki/systems/runtime-architecture-and-module-ownership.md` before moving
logic between modules.

Allowed import shape:

```text
memory.py facade -> focused modules -> lower-level helpers
schema/governance/observability -> near-stdlib, no behavior-module imports
```

Avoid focused modules importing `memory.py`, schema importing behavior modules,
review and queue importing each other, or provider/OAuth code inside queue
modules.

## MCP, CLI, And Enhancement Boundaries

- The authoritative MCP registration lives in `chimera_memory/server.py`; tool
  filtering lives in `chimera_memory/mcp_surface.py`.
- Normal persona work should use the persona belt: `memory_context_pack`,
  `memory_recall`, `memory_remember`, `memory_promote_snapshot`,
  `memory_review`, and `memory_diagnose`.
- Use `CHIMERA_MEMORY_MCP_SURFACE=codex` for Codex Desktop project mode.
- Use `CHIMERA_MEMORY_MCP_SURFACE=worker` only for enhancement workers.
- Provider-backed enhancement is explicit opt-in behind sidecar/runner,
  credential-reference, budget-governor, queue, and review boundaries.
- `dry_run` enhancement remains the no-provider floor.
- CLI workers must use the worker-only MCP surface and return results through
  worker submit tools, not free-form stdout scraping.

## Final Response

Include what changed, key files, assumptions, risks, and useful next steps.

## Ports

Dev ports & Caddy hosts: see CHIMERA-PORTS.md.
