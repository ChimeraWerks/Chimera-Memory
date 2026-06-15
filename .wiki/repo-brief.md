# Repo Wiki Brief

Name: Chimera-Memory
Kind: repo
Updated: 2026-06-12

## What This Wiki Knows

- ChimeraMemory is a local-first Python package and MCP server for indexing agent transcripts and curated markdown memories into SQLite.
- The repo has two memory layers behind one interface: transcript recall and curated memory.
- Scope is a privacy boundary: persona sessions use persona + current project + global; no-persona Codex project mode uses current project + global.
- The active harness (Claude Code, Codex, standalone Hermes) is auto-identified by
  `chimera_memory/harness.py` `detect_harness()` (explicit env > process-injected
  running signals > session-dir signature > per-file content sniff > Claude
  default), so the JSONL dir and parser resolve without per-launch config. Codex
  rollouts and Claude logs are `*.jsonl`; standalone Hermes is per-persona
  `session_*.json` with a native parser. `chimera-memory hermes` sets up Hermes.
- No-persona Codex project discovery uses explicit `CHIMERA_MEMORY_PROJECT_ID`
  as the indexing identity for a single configured project root.
- No-persona Codex MCP read tools fail closed without a resolved project id for
  `auto`/`project` scope and reject `scope=all`; use `scope=global` for
  explicit global-only recall.
- Global seed write mode blocks broad mixed shared/persona-style imports by
  default; use include/exclude filters or `--allow-mixed-source` only after
  review.
- Missing or unrecognized global-memory frontmatter is pending evidence, not
  instruction-grade authority.
- `chimera_memory/memory.py` is the compatibility facade. New schema, review, enhancement, importer, provider, OAuth, worker, and audit behavior belongs in focused modules.
- Generated, imported, auto-captured, and sidecar-produced metadata starts as
  review-gated evidence, not instruction-grade memory, unless trusted automated
  promotion explicitly stamps `auto_confirmed` provenance.
- Streamable HTTP support and GitHub Actions CI are implemented. The remaining
  service-mode question is resident owner-process behavior, not local shared
  HTTP transport.

## Agent Boot

1. Read `SCHEMA.md`.
2. Read `index.md`.
3. Read recent `log.md`.
4. Read `wiki/sources/chimera-memory-source-manifest-2026-06-09.md`.
5. Open only task-relevant wiki pages, routed docs, code, and tests.

Baseline: `python -m pytest -q` should be **841 passed**. The 150-finding audit
(Critical → Low) is fully remediated — see `docs/AUDIT_REMEDIATION_2026-06-14.md`
and the "Audit / Quality Status" section of
`wiki/synthesis/current-repo-state.md`. The only deferred audit item is smr-09
(documented); everything else is fixed or documented won't-fix.

## High-Risk Assumptions

- Do not cross persona or project memory boundaries silently.
- Do not add cloud persistence or hosted LLM requirements to the baseline path.
- Do not treat generated or imported memory as trusted instruction without
  manual review or an explicitly trusted automated promotion policy.
- Do not leak raw local paths, secrets, transcripts, auth files, provider errors, or stderr to client-facing surfaces.
- Do not bulk-format or lint-clean `memory.py` blindly; it carries compatibility re-exports.
