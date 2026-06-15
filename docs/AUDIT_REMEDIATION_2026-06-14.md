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
- [x] ec-04: dry_run short-circuits the provider sidecar (no network on the floor).
- [x] cm-ent-006: edge dates normalized to ISO before temporal comparison.
- [x] pc-05: enhancement request never egresses an absolute source path.
- [x] wcp-04: auto-capture credential gate scans raw inputs (regression test).
- [x] imp-03: ChatGPT import credential gate scans the raw conversation.
- [x] ghh-04: memory_diagnose(health) no longer writes (repair) on a read.
- [x] hermes-002: Gemini cloudcode adapter honors the caller timeout (post+stream).

## Hermes setup command (parity with `codex install`) — DONE

- [x] `chimera-memory hermes template|doctor|install` (new `hermes_setup.py`).
      template prints the indexer env + paste-in MCP config block; doctor is
      read-only (session store, parse smoke, harness resolution); install writes
      per-persona launcher scripts under `~/.chimera-memory/hermes/` and never
      mutates Hermes's comment-rich config.yaml. Verified on real `asa` data.

## Medium severity — landed (batches G–J + extras)

- [x] cli-04, cli-07 (CLI persona-dir validation, conn-leak/busy_timeout).
- [x] cli-02/cli-03 covered by the cli-01 top-level handler (no raw-traceback leak).
- [x] ec-01 (worker path leak), wcp-03 (export containment), schema-db-01/10
      (db_split close + busy_timeout), codex-setup-2 (stale snake_case mcpServers).
- [x] wsm-04 (worker prewarm off), se-02 (RRF-dominant rerank), se-06 (not_built),
      mfr-04 (recall fingerprint dedup), mfr-03 (batched reinforce + ISO ts).
- [x] pc-03 (cost-cap rolling window + lock), cm-ent-002 (evidence-keyed edges),
      gsr-11 (safe prune), gsr-03 (symlink containment), gsr-04 (truncated-queue
      auto-promote fails closed).
- [x] imp-05 (per-conversation import isolation), imp-06 (gmail streaming + limit),
      smr-05 (secondary-process prewarm), schema-db-06 (NULL-content dedup),
      hc-05/smr-07 (per-thread memory connection), cm-ent-003 (dead index migration).

## Deliberately deferred (with reasons)

- gsr-05 (seed rollback on index failure): a correct rollback needs
  backup-before-overwrite (overwritten files have no backup to restore); the
  failure is already surfaced (receipt non-OK) and self-heals on the next
  reindex, so a partial rollback risks deleting wanted files. Needs a design pass.
- oauth-04 (duplicate provider-login pool overwrite): genuine product decision —
  overwrite-on-refresh vs pool-distinct-accounts vs error. Needs intent.
- se-03 (dead `consolidate_old_entries`): unreferenced, zero runtime impact;
  flagged for a dedicated dead-code removal, not bundled with behavior changes.

The Critical + all 16 High + the large majority of Medium findings plus the full
harness identification work and the Hermes setup command are complete and tested
(full suite green). Remaining items are the three deferred above plus Low-severity
polish catalogued in `.claude/audit-findings.json`.
