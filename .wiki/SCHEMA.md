# Wiki Schema

Kind: repo
Name: Chimera-Memory
Schema version: 1

## Purpose

This is a repo-local Chimera wiki. Raw sources are immutable. Synthesized pages live under `wiki/`. `index.md` is navigation. `log.md` is append-only.

## Required Page Frontmatter

```yaml
---
id: stable-slug
title: Human Title
scope: repo | global | imported
kind: source | concept | decision | system | operation | lesson | question | synthesis | repo-capsule
status: draft | active | stale | contested | superseded | archived
trust: high | medium | low
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources:
  - raw/sources/example.md
---
```

## Rules

- Read `index.md` before opening pages.
- Capture source snapshots or source pointers under `raw/`.
- Cite raw sources or canonical repo docs for behavior-relevant claims.
- Keep pages atomic; split pages over roughly 300 lines.
- Update `index.md` and append `log.md` after every write.
- Promote only cross-repo material to the global hub.
- Mark conflicts as `status: contested` instead of overwriting silently.
