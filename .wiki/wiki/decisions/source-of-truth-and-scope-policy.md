---
id: chimera-memory-source-of-truth-and-scope-policy
title: Source Of Truth And Scope Policy
scope: repo
kind: decision
status: active
trust: high
created: 2026-06-09
updated: 2026-06-09
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - AGENTS.md
  - docs/agents/boundaries.md
  - docs/agents/security.md
  - docs/FEDERATED_MEMORY_SCOPE.md
  - chimera_memory/memory_governance.py
  - chimera_memory/memory_scope.py
---

# Source Of Truth And Scope Policy

## Decision

ChimeraMemory is local-first by default and treats memory scope as a privacy
boundary. Current code, tests, and CI are authoritative for implemented behavior;
the wiki is compiled navigation and synthesis.

## Source Order

1. Current code, tests, package metadata, scripts, and CI.
2. `AGENTS.md` for hard agent rules.
3. Active agent docs under `docs/agents/`.
4. `.wiki/` for current-state synthesis and drift tracking.
5. `README.md` for user-facing reference.
6. Deep docs under `docs/` for design history and detailed contracts.
7. Runtime DBs, transcript logs, generated caches, worker homes, local auth
   stores, and vendor copies as noncanonical outputs.

## Scope Rule

ChimeraMemory has three retrieval tiers:

- `global`: agency-wide shared memory.
- `project`: repo/project memory isolated by `project_id`.
- `persona`: private persona memory that never crosses personas automatically.

Default persona recall is:

```text
current persona + current project + global
```

Default no-persona Codex project recall is:

```text
current project + global
```

Cross-persona private recall is not a normal v1 feature. A persona memory that
should become shared must be promoted upward as a snapshot.

## Baseline Technology Policy

Keep the default path on SQLite, markdown plus YAML frontmatter, local
fastembed/BGE embeddings, and local MCP/CLI surfaces. Optional providers,
sidecars, and CLI workers are explicit boundaries, not baseline requirements.

## Generated Memory Policy

Generated, imported, auto-captured, and sidecar-produced memories or metadata
start as review-gated evidence. Instruction-grade use requires either manual
review that stamps `user_confirmed` provenance or explicitly enabled trusted
automation that stamps `auto_confirmed` provenance.
