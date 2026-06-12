# Federated Memory Scope v1

Status: Day 63 v1 closed on Asa-side live smoke.

CM has three retrieval tiers:

1. `global` ... agency-wide memory useful across personas and projects, such as Charles's durable work preferences.
2. `project` ... repo or project memory, isolated by `project_id`.
3. `persona` ... private persona memory. This never crosses personas automatically.

Default recall scope is:

```text
current persona + current project + global
```

Codex Desktop can also run without a persona. In that mode the default recall
scope is:

```text
current project + global
```

No-persona Codex profiles must set `CHIMERA_MEMORY_PROJECT_ID` and
`CHIMERA_MEMORY_PROJECT_ROOT`. They intentionally leave `TRANSCRIPT_PERSONA`
unset and must not walk private persona trees. Live discovery and watcher
startup skip the persona tree whenever a runtime has no `TRANSCRIPT_PERSONA`
and is configured for project roots or the Codex client/surface. Shared,
global, and explicit project roots remain indexable/watchable. The watcher
handler also rejects persona paths when that tree was intentionally skipped.
Legacy multi-persona aggregation remains only for unscoped admin-style runs
that are not Codex/project configured.
Full-reindex cleanup uses the same active root boundary as discovery. In
no-persona Codex/global/project mode, cleanup may prune missing rows under the
managed shared/global/project roots, but it must not delete pre-existing rows
from persona roots that this runtime intentionally skipped.
When a single `CHIMERA_MEMORY_PROJECT_ROOT` is configured, the explicit
`CHIMERA_MEMORY_PROJECT_ID` is the indexing identity; folder-derived ids are
fallback only.

Cross-persona private recall is not a v1 feature. If a persona memory should become shared, it must be promoted upward as a snapshot.

## Storage Mapping

Current v1 mapping:

```text
~/.chimera-memory/global-memory/   -> global
<agency-root>/shared/              -> global
<repo>/.chimera-memory/memory/     -> project
<repo>/.chimera-memory/project/    -> project
personas/<role>/<name>/memory/     -> persona
personas/<role>/<name>/reading/    -> persona
```

`<agency-root>/shared/` maps to `global` for v1 because the existing shared directory already means agency-wide shared context. Cross-session or cross-install global memory can be separated later if needed.

The default global-memory helper and Codex no-persona project setup use
`~/.chimera-memory/global-memory`, so shared HTTP sidecars do not depend on the
legacy Claude global-memory directory existing. Doctor/runtime
diagnostics warn when that live global root is missing and separately report
how many indexed global files are available to default retrieval. An empty
global corpus is observable without being treated as a setup failure.

Project memory is discovered only from explicit project-memory subtrees so auth/cache state under `.chimera-memory/` does not get indexed by accident.

## Query Policy

`scope=auto` is the normal persona mode:

- include `memory_scope=global`
- include `memory_scope=project` when `project_id` is known
- include `memory_scope=persona` only for the current persona

Explicit scope modes:

- `scope=persona`: current persona only
- `scope=project`: current project only
- `scope=global`: global only
- `scope=all`: operator/admin mode, not normal persona recall

For no-persona Codex Desktop, `scope=auto` includes only global plus the current
project. Persona-private memory is excluded unless a persona is explicitly set.
Use `CHIMERA_MEMORY_MCP_SURFACE=codex` for the Codex Desktop project surface:
it keeps the normal memory belt plus transcript recall, exact
`memory_search`/`memory_query`, and scoped read-only
`memory_live_retrieval_check`.

Codex prompt wrapping can also opt into project transcript snippets with
`--include-transcripts`. Transcript fallback is filtered by session `cwd` inside
the current project workspace; it must not search the full transcript corpus for
automatic prompt evidence. Each transcript fallback run records a
`codex_transcript_context` recall trace plus a `codex_transcript_context_*`
audit event, but trace items keep transcript bodies and raw workspace paths out
of diagnostic metadata.

## Promotion Policy

Promotion is monotonic upward:

```text
persona -> project -> global
persona -> global
```

Promotion is a publication event, not a live mount.

The promoted file should be a snapshot with origin metadata:

```yaml
memory_scope: project | global
promoted_from:
  persona: asa
  path: memory/procedural/example.md
  promoted_at: 2026-05-18T00:00:00Z
  source_content_hash: ...
```

The origin file can keep evolving privately. The promoted snapshot does not live-sync back, and deleting the origin does not delete the snapshot.

## Edge Cases

- Duplicate canonical target: reject and log; force explicit merge or supersede.
- Origin deletion after promotion: snapshot stays.
- Project isolation: strict. Project memory does not cross into another project unless promoted to global.
- Global write authority: global memory can be written either by an approved
  promotion snapshot or by an explicit no-persona authored global write. Both
  paths must carry review/provenance fields; default retrieval still excludes
  restricted, blocked, and non-evidence rows.
- Existing shared directory: global for v1.

## Persona-Facing Tool Surface

The long MCP surface should not be the default persona belt. Normal personas should reason about six operations:

1. `memory_context_pack` ... build fenced pre-turn memory packs for harness injection.
2. `memory_live_retrieval_check` ... dry-run scoped proactive recall suggestions without injection.
3. `memory_recall` ... get usable semantic memory, with low-similarity hits filtered by default.
4. `memory_remember` ... write authored memory.
5. `memory_promote_snapshot` ... publish upward.
6. `memory_review` ... handle pending memories and review actions.
7. `memory_diagnose` ... stats, zones, context status, traces, harnesses, gaps, provider plan, and retrieval analysis.

Current v1 MCP status:

- Implemented: `memory_context_pack`, `memory_live_retrieval_check`, `memory_recall`, `memory_remember`, `memory_promote_snapshot`, `memory_review`, `memory_diagnose`.
- Default direct retrieval (`memory_search`, `memory_query`, `memory_recall`), corpus stats, and provenance metadata lookup (`memory_source_refs`, `memory_artifacts`) are scope-aware and exclude restricted, rejected/disputed/superseded, and non-evidence rows. Review/debug callers must opt in with `include_restricted` or `include_blocked`; non-evidence rows stay out. MCP text for provenance lookups redacts local path-shaped URIs to a filename plus fingerprint, while lower-level query APIs keep stored URI values for internal review/debug use.
- Direct retrieval traces record candidate availability separately from returned context. `memory_search` and `memory_query` compute `result_count` before the caller's limit is applied, while `returned_count` is the surfaced item count; exact search and structured query traces redact raw `source_uri` values.
- `memory_search` uses the same deterministic query-term quality gate as scoped
  context retrieval. FTS5 still supplies candidates with OR semantics, but rows
  that only match broad terms such as `global` or `memory` are filtered when the
  query contains more specific terms.
- Live retrieval term extraction strips prior `chimera-memory-context`,
  `chimera-transcript-context`, `memory-context`, and `supermemory-context`
  fences before planning recall, so previously injected evidence does not
  become fresh topic-shift signal.
- Generated synthesis rows are excluded from default retrieval, stats, and provenance lookup unless callers explicitly set `include_synthesis`.
- `memory_promote_snapshot` previews by default. Writes require `write=true` and an explicit `approved_by` value, reject duplicate targets, copy the source body/frontmatter, and stamp `promoted_from` provenance with a source content hash.
- `memory_remember` write receipts include the relative path, authored identity,
  `indexed=true/false`, and `file_id` without exposing the raw storage path, so
  Codex/global writes can be verified immediately before the next health
  snapshot updates corpus counts.
- Compatibility: default MCP surface is still `full`, so legacy/admin tools remain registered unless a server opts into filtering.
- Runtime filtering: set `CHIMERA_MEMORY_MCP_SURFACE=persona` to expose the persona memory belt plus transcript recall tools. Set `CHIMERA_MEMORY_MCP_SURFACE=codex` for Codex Desktop project mode with the project/global memory belt, exact memory search/query, scoped stats, and scoped live-retrieval diagnostics; generic transcript recall tools are intentionally absent from this surface. Set `CHIMERA_MEMORY_MCP_SURFACE=persona_memory` for only the memory belt. Unknown values fall back to `full`.

Project writes can target more than one repo without restarting CM per project by setting `CHIMERA_MEMORY_PROJECT_ROOTS`:

```text
CHIMERA_MEMORY_PROJECT_ROOTS=ChimeraMemory=<chimera-memory-root>/.chimera-memory;PersonifyAgents=<personify-agents-root>/.chimera-memory;ProjectChimera=<project-chimera-root>/.chimera-memory
```

The legacy single-project `CHIMERA_MEMORY_PROJECT_ROOT` remains supported. When both are present, the project-id map is used for matching `project_id` values.

Admin, import, enhancement, entity/wiki, migration, and legacy tools should move behind CLI or operator namespaces. Tool diet comes before service-mode. A resident service with a bad interface just daemonizes the mess.

## Day 63 Closeout

V1 is closed when the running MCP process proves these surfaces live:

- persona-facing tool diet is active (`memory_diagnose(mode="tools")`)
- active harness lease diagnostics work (`memory_diagnose(mode="harness")`)
- project promotion preview resolves through `CHIMERA_MEMORY_PROJECT_ROOTS`
- write attempts still require explicit `approved_by`
- promotion attempts write audit rows
- transcript outbound capture can see current harness-originated posts

Asa-side live smoke passed after restart on 2026-05-18:

- `memory_diagnose(mode="tools")` returned the five-tool persona belt.
- `memory_diagnose(mode="harness")` returned `chimera-memory.active-harness-lease.v1`, current lease present, conflict count `0`, `warning_only=true`.
- `memory_promote_snapshot(destination_scope="project", project_id="PersonifyAgents", write=false)` previewed successfully.
- `memory_promote_snapshot(..., write=true)` without `approved_by` failed with the approval-required gate.
- Audit query showed `memory_promote_snapshot_planned` and `memory_promote_snapshot_approval_required`.
- The legacy `discord_recall_index(direction="outbound")` compatibility path
  found the current Asa outbound post in the historical transcript store.

Still deliberately outside v1:

- Broad legacy memory migration. Keep deferred unless Charles narrows scope.
- CM service-mode architecture. Revisit only if real remaining pain is lifecycle, queues, or shared state rather than tool naming clutter.
- Transcript federation. Requires a transcript visibility policy before merged persona DB views or a central channel archive.
- Shadow enrichment pilot graduation. Requires a separate provider/default-quality decision.
