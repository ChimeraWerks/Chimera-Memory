---
id: chimera-memory-current-repo-state
title: Current Repo State
scope: repo
kind: synthesis
status: active
trust: high
created: 2026-06-09
updated: 2026-06-09
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - README.md
  - AGENTS.md
  - docs/agents/repo-map.md
  - docs/CODEX_DESKTOP_SCOPE_AND_CODE_AUDIT.md
  - .github/workflows/ci.yml
---

# Current Repo State

## Summary

ChimeraMemory is a standalone Python package and MCP server. It indexes local
agent transcript JSONL and curated markdown memories into SQLite, exposes recall
and memory tools over MCP, and provides CLI helpers for setup, indexing,
embedding, enhancement, and Codex configuration.

The repo is clean at initial wiki creation. It has active CI on Ubuntu and
Windows for Python 3.10 and 3.12.

## Active Capabilities

- Transcript indexing, sanitization, FTS5 search, semantic search, and session
  browsing.
- Curated memory indexing from markdown plus YAML frontmatter.
- Local embeddings with fastembed/BGE and CPU/GPU provider selection.
- MCP stdio and streamable HTTP transports.
- MCP surface filtering for `full`, `persona`, `codex`, `persona_memory`, and
  `worker`.
- Codex Desktop/CLI project-mode setup, template, install, and doctor helpers.
- Global/project/persona memory scope with promotion snapshot policy.
- Review queues, recall traces, audit events, governance metadata, sensitivity
  tiers, entity graph, memory-file edges, pyramid summaries, import pipelines,
  profile export, auto-capture, authored writeback, and active harness lease
  diagnostics.
- Enhancement queue, deterministic dry-run worker, provider policy, OAuth import,
  provider runner, HTTP sidecar, and official CLI worker supervisors for Codex,
  Claude Code, and Antigravity.

## Current Larger Risks

- `server.py`, `memory.py`, `memory_cli_worker_supervisor.py`, OAuth, and CLI
  dispatch are large structural hotspots. Split behavior in focused slices, not
  broad rewrites.
- `memory.py` carries compatibility re-exports; do not remove apparently unused
  imports through blind lint cleanup.
- Some docs still use future wording for implemented slices.
- Resident service ownership remains unresolved even though streamable HTTP
  transport exists.

## Agent Implication

Start from the wiki and routed docs, then verify in code/tests. Prefer focused
module and test changes over large cleanup passes.
