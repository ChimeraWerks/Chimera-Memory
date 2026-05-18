# Federated Memory Scope v1

Status: Day 63 policy slice.

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

The long MCP surface should not be the default persona belt. Normal personas should reason about five operations:

1. `memory_recall` ... get usable memory.
2. `memory_remember` ... write authored memory.
3. `memory_promote_snapshot` ... publish upward.
4. `memory_review` ... handle pending memories and review actions.
5. `memory_diagnose` ... stats, zones, traces, gaps, provider plan, and retrieval analysis.

Admin, import, enhancement, entity/wiki, migration, and legacy tools stay available through CLI or operator namespaces. Tool diet comes before service-mode. A resident service with a bad interface just daemonizes the mess.

