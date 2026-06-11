---
id: chimera-memory-federated-scope-and-memory-governance
title: Federated Scope And Memory Governance
scope: repo
kind: system
status: active
trust: high
created: 2026-06-09
updated: 2026-06-11
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - docs/FEDERATED_MEMORY_SCOPE.md
  - docs/agents/security.md
  - docs/MIGRATION_PIPELINE.md
  - docs/MEMORY_ENHANCEMENT_SIDECAR.md
  - chimera_memory/memory_governance.py
  - chimera_memory/memory_scope.py
  - chimera_memory/memory.py
  - chimera_memory/memory_authored_writeback.py
  - chimera_memory/memory_enhancement.py
  - chimera_memory/memory_relevance.py
  - chimera_memory/memory_live_retrieval.py
  - chimera_memory/memory_context_pack.py
  - chimera_memory/transcript_context.py
  - chimera_memory/memory_global_seed.py
  - chimera_memory/memory_global_review.py
  - chimera_memory/memory_health.py
  - chimera_memory/codex_setup.py
  - tests/test_memory_governance.py
  - tests/test_memory_enhancement.py
  - tests/test_memory_health.py
  - tests/test_codex_setup.py
  - tests/test_memory_global_seed.py
  - tests/test_memory_authored_writeback.py
  - tests/test_codex_desktop_project_mode.py
  - tests/test_cli_enhance.py
  - tests/test_memory_observability.py
  - tests/test_memory_semantic_recall.py
  - tests/test_memory_live_retrieval.py
  - tests/test_memory_context_pack.py
  - tests/test_memory_global_review.py
  - tests/test_memory_scope.py
  - tests/test_memory_schema_hygiene.py
---

# Federated Scope And Memory Governance

## Two Memory Layers

- Transcript layer: harness JSONL from Claude Code, Codex, Hermes, and related
  sources gets parsed, sanitized, indexed, and optionally embedded.
- Curated memory layer: markdown plus YAML frontmatter memories get indexed,
  scored, zoned, reviewed, traced, queried, and promoted.

Both layers are exposed through CLI/MCP surfaces.

For Codex project prompt wrapping, transcript fallback is opt-in and narrower
than general transcript search: `transcript_context.py` only returns snippets
from sessions whose recorded `cwd` is inside the current project workspace.
This avoids using all local transcript history as automatic prompt evidence.

## Scope Tiers

- `global`: agency-wide memory useful across personas and projects.
- `project`: repo/project memory isolated by `project_id`.
- `persona`: private persona memory.

Default recall for persona sessions is persona plus current project plus global.
Default recall for no-persona Codex project sessions is current project plus
global.

The Codex MCP surface is a no-persona surface. Explicit `persona` arguments and
env-derived `TRANSCRIPT_PERSONA` identity are rejected for memory reads, stats,
context packs, live retrieval, authored writes, and persona-scope attempts; they
are not treated as permission to include persona-private memory. Persona memory
access requires a non-Codex persona/admin surface. The persona-facing
`memory_review` queue and persona-source `memory_promote_snapshot` are also not
registered on the Codex surface; no-persona global review flows through
`chimera-memory global review`. Codex
`memory_diagnose` is limited to safe project/global diagnostics: tools, stats,
context, provider plan, worker/health, guard, and whereami. Persona/admin
diagnostics such as zones, traces, audit, harness, gaps, and consolidation are
rejected on the Codex surface.

No-persona Codex project discovery treats explicit `CHIMERA_MEMORY_PROJECT_ID`
as the live indexing identity for the single configured project root. A
folder-derived id is fallback only, which keeps indexing, writes, and query
filters aligned when the repo folder and configured project id differ.

Live no-persona discovery and watcher startup skip the persona tree when either
project roots are configured or the runtime identifies as Codex through
`CHIMERA_CLIENT=codex` or `CHIMERA_MEMORY_MCP_SURFACE=codex`. Shared/global
roots and explicit project roots are still indexed and watched. The watcher
handler also rejects persona paths when the persona tree was intentionally
skipped, so a stray filesystem event cannot bypass the startup schedule. This
is a live privacy boundary, not generated synthesis; the remaining legacy
multi-persona aggregation path is for unscoped admin-style runs that are not
Codex or project-root configured.
Full-reindex cleanup follows the same managed-root boundary: no-persona
Codex/global/project runs may prune stale rows under the active shared, global,
and project roots, but preserve pre-existing persona-root rows when the persona
tree was intentionally skipped. Full-reindex and watcher discovery skip hidden,
cache, auth, and symlink child paths relative to each managed root while still
allowing configured hidden roots such as `.chimera-memory` to serve as project
or global memory roots.

`memory_live_retrieval_check` and `memory_context_pack` both use the shared
scope policy before suggesting or packaging curated memory. Both also use the
shared deterministic relevance gate so weak broad global/project matches become
traced misses instead of suggestions or context cards. Live retrieval is still
dry-run only: it traces and audits suggestions, but does not inject prompt
content by itself.

Recall trace counts distinguish candidate availability from returned context:
`result_count` is the filtered result set before limit or token-budget selection,
while `returned_count` is the number of items actually surfaced. Exact
`memory_search` and structured `memory_query` traces compute this count with the
same scope, governance, and source-reference filters before applying the
caller's requested limit. Exact search and structured query traces keep
sensitive source identifiers out of trace text and payloads by recording only
`source_uri_supplied`.

`memory_recall` uses scoped semantic embeddings with a low default
`min_similarity` floor and the shared deterministic query-term quality gate, so
weak top-N embedding neighbors do not become usable memory by accident. It also
has a live FTS/body-match rescue path for exact curated-memory terms that fall
below the semantic floor; rescued candidates carry source metadata such as
`fts_rescue` or `hybrid` and must meet stricter query-term coverage before they
surface. Explicit floors above the default disable this rescue so stricter
semantic-only diagnostics remain strict. Callers can lower the floor explicitly
for diagnostics, which also disables the quality gate for raw retrieval
inspection.

Default direct curated-memory retrieval (`memory_search`, `memory_query`, and
`memory_recall`), scoped corpus stats, and provenance metadata lookups
(`memory_source_refs`, `memory_artifacts`) exclude restricted,
rejected/disputed/superseded, and non-evidence rows. Restricted or blocked rows
require explicit opt-in for review/debug work; non-evidence rows stay out of
ordinary retrieval and lookup surfaces. When callers supply an active
`global_root`, these direct retrieval and lookup paths also constrain global
rows to indexed files under that root while preserving project and persona rows.
MCP text for provenance lookup results redacts local path-shaped source or
artifact URIs to a filename plus fingerprint; lower-level query APIs retain the
stored URI values for internal review/debug use. Exact `memory_search` still
uses FTS5 OR semantics to form a candidate pool, but then applies the shared
deterministic query-term quality gate before returning rows. This prevents
global/project searches with specific terms from surfacing weak rows that only
matched broad words such as `global`, `memory`, or `project`.

Explicit authored writes can target global memory without a persona source.
`memory_remember(scope="global")` and
`chimera-memory enhance authored-write --scope global` write structured
authored memory under the configured global root, stamp `memory_scope: global`,
and index the file as persona `global`. This is separate from promotion:
promotion snapshots still copy a persona source upward, while no-persona
authored global writes create new global records directly.
MCP `memory_remember` write receipts report relative path, authored identity,
`indexed=true/false`, and `file_id`, but not raw storage paths. This gives
Codex/global writes immediate indexing proof even before the low-cadence health
snapshot updates global corpus counts.

## Context Pack Quality Gate

`memory_context_pack` uses scoped curated-memory candidates as evidence for
pre-turn harness injection, but it must not spend prompt budget on weak global
matches. The live implementation keeps scope filtering first, then applies a
deterministic quality gate before card construction.

The gate treats broad terms such as `memory`, `context`, `project`, `global`,
`session`, `turn`, `stop`, and `working` as insufficient by themselves when a
query has more specific cues. A candidate must match enough specific query
terms, or have very strong semantic evidence, before it can become a context
card. This is live behavior, not a model-generated synthesis: weak global
roster/spatial rows should become traced misses instead of injected evidence,
while relevant global or current-project rows still survive. Scope filtering
still runs before the quality gate, so no-persona project packs can use global
and current-project evidence without admitting persona-private rows. When a
caller supplies an active global root, global candidates are also constrained to
indexed files under that root; outside-root global DB rows cannot spend context
budget or appear in prompt evidence. Live retrieval uses the same active-root
filter before suggesting dry-run proactive recall, so outside-root global rows
cannot appear as active suggestions either. Direct MCP read tools use that same
root boundary for search, structured query, semantic recall, scoped stats, and
provenance lookups, so outside-root global rows cannot be mistaken for active
Codex/global memory through inspection routes.
After the quality gate, context packs collapse duplicate evidence by normalized
content fingerprint and by global relative path. This keeps a legacy shared file
and its CM-local global-root copy from spending prompt budget twice while still
recording dedupe counts in recall trace response policy. Prompt-facing card
labels use root-relative paths when available and otherwise synthetic scoped
IDs, never raw filesystem paths, so drifted legacy rows do not leak local paths
into injected context.
Prompt-card prose, direct MCP retrieval snippets, and `about` text are
display-sanitized for credential-like content and local path references before
they leave CM, while raw stored text remains the matching/ranking source.

## Promotion

Promotion is monotonic upward:

```text
persona -> project -> global
persona -> global
```

Promotion creates a snapshot with origin metadata. It is not a live mount. The
origin can keep evolving privately and deleting the origin does not delete the
snapshot.

## Review And Trust

Generated, imported, auto-captured, and sidecar-produced memory remains
review-gated and evidence-only by default. Instruction-grade use requires
either manual review that stamps `user_confirmed` provenance or explicitly
enabled trusted automation that stamps `auto_confirmed` provenance.

Imported global-root files are stamped as `memory_scope=global`, evidence-only,
pending review, and not instruction-grade unless they already carry explicit
confirmed instruction provenance. For non-`user_confirmed`/`auto_confirmed` files or files whose
original frontmatter was not already `memory_scope: global`, seed and reindex
stamps force `can_use_as_instruction: false` and
`requires_user_confirmation: true` even if legacy frontmatter claimed otherwise,
so durable markdown matches the live imported-memory trust boundary. The durable
global review path is
`chimera-memory global review`: preview by default, `--write --reviewer` for
frontmatter mutation, immediate reindexing as global memory, and path-safe audit
events. Preview-mode reviewed frontmatter is a display-safe view whose string
values are sanitized for local paths and credential-like content; write-mode
persists the canonical reviewed markdown frontmatter. Review targets must be
root-relative markdown paths; leading
separators, Windows drive or stream separators, control characters, `..`,
absolute paths, non-markdown targets, and missing files fail closed. Missing or
unrecognized global-root frontmatter is
also treated as imported, pending, evidence-enabled, instruction-disabled, and
confirmation required in inspect/reindex/review receipts. `confirm` is the
explicit global instruction promotion; evidence-only,
restricted, rejected, stale, merged, disputed, or superseded outcomes remain out
of instruction use. Write-mode review also runs the memory guard before outcomes
that would remain default-retrievable, so manually edited or compatibility
imported unsafe files cannot be promoted into ordinary global evidence or
instruction use without first being cleaned or restricted. The review guard uses
`exclude_from_default_search`, matching the indexing and context-retrieval
surfaces, when deciding whether the post-review file remains default-retrievable.
Body-safe recommendation commands keep simple relative paths double-quoted and
use PowerShell-safe single-quote escaping for shell-active names.

The no-human global promotion path is `chimera-memory global promote`. It is
dry-run by default and writes only when explicitly enabled. The strict
`trusted_clean` policy promotes clean imported pending global files to
`auto_confirmed`; generated, restricted, excluded, malformed, wrong-scope,
duplicate-body, missing-governance, or guard-blocked files are skipped with
body-safe policy reasons instead of becoming instruction-grade memory.

Context packs may still return pending/evidence-only global records as evidence
when they pass scope, safety, and quality gates. Returned cards label authority
with metadata such as `review=pending`, `evidence-only`, `needs-confirmation`,
`lifecycle=stale`, and `lifecycle=archived`; the Codex prompt wrapper tells the
model those records are unconfirmed or non-current leads and not settled
instructions unless confirmed, current, or independently verified.

Restricted sources such as Gmail, Instagram, and Google Activity default to
restricted, pending review, and evidence-only.

## Generated Synthesis

Generated synthesis artifacts, such as entity wiki pages and future dossiers,
are cached views. Default retrieval, stats, and provenance lookup exclude
synthesis rows unless a caller opts in. Context packs and live retrieval use
the same default-search exclusion, which keeps generated summaries from
polluting ordinary recall unless the caller explicitly sets
`include_synthesis=true`.

## Active Harness Lease

The active harness lease is warning-only. CM records which MCP/runtime process
opened a persona memory DB, refreshes the lease, and warns if another live
process uses the same persona DB. It does not lock, kill, or enforce ownership.
