# ChimeraMemory Audit Remediation (2026-06-14)

Source: multi-agent audit (harness deep-dive + flaw sweep across all module
groups + adversarial verification + synthesis). 150 confirmed findings.
Full machine-readable list: `.claude/audit-findings.json` (gitignored scratch).

This tracker records the prioritized fixes. Status: `[x]` done & tested,
`[ ]` pending, `[~]` partial.

## Harness identification (the original request) — DONE

- [x] New `chimera_memory/harness.py` `detect_harness()` (env → jsonl_dir shape →
      running-harness env signals → MCP client hint → on-disk signature → default).
- [x] `server.get_default_jsonl_dir()` delegates to harness detection (Codex/Hermes
      aware, not Claude-only).
- [x] `indexer.Indexer` resolves the parser from the detected harness when no
      explicit `CHIMERA_CLIENT`; per-file content sniffing prevents a Codex rollout
      being silently parsed as Claude (zero-entry data loss).
- [x] active-harness lease records the detected harness name when unset.
- [x] Multi-harness footgun guarded: install-location env vars (HERMES_HOME/
      CODEX_HOME) never mislabel; only process-injected signals decide.
- [x] Tests: `tests/test_harness.py` (17 cases).

## Theme 1 — Harness / per-persona DB routing

- [x] T1.1/hc-01/smr-01 (CRITICAL): unified `server._resolve_transcript_db_path()`
      across `_get_db`, lock path, and the 5 startup workers. Test: test_db_resolution.py.
- [ ] T1.3/smr-04: wire MCP `clientInfo.name` into `harness.set_mcp_client_hint`
      (hook exists in harness.py; FastMCP initialize capture not yet wired).
- [ ] T1.5/hc-08: scope Codex session indexing by cwd when no persona_root.
- [x] T1.6/F5: README harness rows + `.wiki` drift page updated.

## Theme 2 — Safety / path & secret leaks (hard-rule)

- [x] smr-02: global MCP error sanitizer (no raw exception on the wire).
- [x] smr-03: redact absolute paths from `memory_whereami` (MCP surface only).
- [x] ghh-03: broaden OpenAI key regex (`sk-proj-`, `sk-svcacct-`).
- [x] ghh-02: sanitize trace-analysis fields sent to provider.
- [ ] (remaining T2.* path/secret redactions per synthesis plan — medium/low.)

## Theme 3 — Crash / raw-exception guards (mostly mechanical)

- [x] ghh-01: non-dict YAML frontmatter coercion.
- [x] mfr-02: `memory_recall` similarity None guard (+ server formatter).
- [x] mfr-01: live-retrieval `superseded` lifecycle filter.
- [x] cli-01: CLI top-level exception handler.
- [x] imp-01/imp-02: ChatGPT importer epoch + string-sort crash guards.
- [ ] (remaining T3.* guards — medium/low: model-catalog, null-ts slices, etc.)

## Theme 4+ — High-severity items landed

- [x] cm-ent-001: entity reindex preserves `source='enhancement'` links.
- [x] wcp-01: scope-aware authored idempotency key + reindex collision guard.
- [x] oauth-01: OAuth refresh runs outside the store lock (CAS re-read).
- [x] schema-db-02/03: crash-safe FTS rebuild + startup trigger recovery +
      `wal_checkpoint` in `finally`. Test: test_transcript_db.py.
- [x] codex-setup-1: TOML installer no longer drops commented tables after the
      CM block. Test: test_codex_setup.py.

## Medium severity — landed (batch C, 2026-06-14)

- [x] hc-08/T1.5: Codex cwd-scoped indexing (Phase B).
- [x] smr-04/T1.3: MCP clientInfo hint wired (Phase B).
- [x] pc-01: model-catalog Unicode/JSON decode crash guarded.
- [x] gsr-01: review_action LIKE wildcards escaped (ESCAPE).
- [x] ghh-06: disputed/superseded provenance forced non-evidence.
- [x] hc-04: embed_transcripts MCP path leak redacted.
- [x] ghh-10: scan_for_injection samples secret-sanitized.
- [x] wsm-01: MCP surface fails CLOSED on an unknown name.
- [x] imp-04: ChatGPT/Twitter/Perplexity/Grok imports default restricted.
- [x] wcp-02: legacy migration tolerates non-UTF-8 files.
- [x] se-01: hybrid_search FTS channel honors entry_types.
- [x] ec-02: worker submit validates status (no raw ValueError leak).
- [x] pc-02: provider credential-ref regex aligned with the resolver.

## Remaining (Medium/Low) — tracked follow-up

The remaining confirmed Medium/Low findings are in `.claude/audit-findings.json`,
organized by the synthesis themes (data integrity: gsr-04/05/11, cm-ent-002;
retrieval ranking: se-02, mfr-04; remaining codex-setup: codex-setup-2;
concurrency/connection hygiene: cli-07, schema-db-01, hc-05, pc-03; dead-code/
false-assurance gates: imp-03, wcp-04, se-03, ec-04; importer portability;
UX/perf polish: ghh-04, se-06, smr-05, wsm-04). The Critical + all 16 High +
13 Medium findings plus the full harness identification work are complete and
tested (full suite green).
