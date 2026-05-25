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

Cross-persona private recall is not a v1 feature. If a persona memory should become shared, it must be promoted upward as a snapshot.

## Storage Mapping

Current v1 mapping:

```text
~/.claude/global-memory/           -> global
<agency-root>/shared/              -> global
<repo>/.chimera-memory/memory/     -> project
<repo>/.chimera-memory/project/    -> project
personas/<role>/<name>/memory/     -> persona
personas/<role>/<name>/reading/    -> persona
```

`<agency-root>/shared/` maps to `global` for v1 because the existing shared directory already means agency-wide shared context. Cross-session or cross-install global memory can be separated later if needed.

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
- Global write authority: persona proposes, Charles approves, then the snapshot is written.
- Existing shared directory: global for v1.

## Persona-Facing Tool Surface

The long MCP surface should not be the default persona belt. Normal personas should reason about six operations:

1. `memory_context_pack` ... build fenced pre-turn memory packs for harness injection.
2. `memory_recall` ... get usable memory.
3. `memory_remember` ... write authored memory.
4. `memory_promote_snapshot` ... publish upward.
5. `memory_review` ... handle pending memories and review actions.
6. `memory_diagnose` ... stats, zones, traces, harnesses, gaps, provider plan, and retrieval analysis.

Current v1 MCP status:

- Implemented: `memory_context_pack`, `memory_recall`, `memory_remember`, `memory_promote_snapshot`, `memory_review`, `memory_diagnose`.
- `memory_promote_snapshot` previews by default. Writes require `write=true` and an explicit `approved_by` value, reject duplicate targets, copy the source body/frontmatter, and stamp `promoted_from` provenance with a source content hash.
- Compatibility: default MCP surface is still `full`, so legacy/admin tools remain registered unless a server opts into filtering.
- Runtime filtering: set `CHIMERA_MEMORY_MCP_SURFACE=persona` to expose the persona memory belt plus transcript recall tools. Set `CHIMERA_MEMORY_MCP_SURFACE=persona_memory` for only the memory belt. Unknown values fall back to `full`.

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
- transcript outbound capture can see current Codex Discord posts

Asa-side live smoke passed after restart on 2026-05-18:

- `memory_diagnose(mode="tools")` returned the five-tool persona belt.
- `memory_diagnose(mode="harness")` returned `chimera-memory.active-harness-lease.v1`, current lease present, conflict count `0`, `warning_only=true`.
- `memory_promote_snapshot(destination_scope="project", project_id="PersonifyAgents", write=false)` previewed successfully.
- `memory_promote_snapshot(..., write=true)` without `approved_by` failed with the approval-required gate.
- Audit query showed `memory_promote_snapshot_planned` and `memory_promote_snapshot_approval_required`.
- `discord_recall_index(direction="outbound")` found the current Asa Discord post.

Still deliberately outside v1:

- Broad legacy memory migration. Keep deferred unless Charles narrows scope.
- CM service-mode architecture. Revisit only if real remaining pain is lifecycle, queues, or shared state rather than tool naming clutter.
- Transcript federation. Requires a transcript visibility policy before merged persona DB views or a central channel archive.
- Shadow enrichment pilot graduation. Requires a separate provider/default-quality decision.
