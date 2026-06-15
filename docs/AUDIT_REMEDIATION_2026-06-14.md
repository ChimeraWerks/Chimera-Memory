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

## Previously deferred — now resolved (Charles-directed)

- [x] gsr-05 (seed rollback): the seed now backs up overwritten files and tracks
      new copies; ANY copy/stamp/index failure rolls back (new files removed,
      overwritten files restored from backup) so a partial write is never left on
      disk. Backups live only for the write and are discarded on success.
      Regression tested (`test_global_seed_rolls_back_on_index_failure`).
- [x] oauth-04 (duplicate provider-login): decision — re-logging the SAME account
      overwrites (correct token refresh), so the overwrite behavior is kept but is
      no longer SILENT: replacing an existing credential under a name logs a note
      ("pass --name to keep both").
- [x] se-03 (dead `consolidate_old_entries`): deleted — it was unreferenced and
      carried latent f-string-SQL / string-date-comparison bugs that never ran.

## Low severity — batch L (2026-06-15)

All 85 low findings were re-verified against current HEAD first (a 44-agent
verification pass): **4 already fixed by the Medium batch, the rest triaged into
fixes vs. documented won't-fix**. Fixes land in tested per-file batches with full
`pytest -q` green after each.

### Already fixed by earlier batches (verified no-op)

- [x] schema-db-03 — `bulk_connection` WAL checkpoint is now in `finally`.
- [x] schema-db-10 — `db_split._connect` sets `busy_timeout=10000` on both paths.
- [x] pc-08 — model-client call counter now guarded by `_CALL_LOCK`.
- [x] wcp-11 — audit-path leak closed centrally in `memory_observability`
      (`_safe_audit_text`/`_safe_audit_payload`); `memory_audit_query` sanitizes.

### Won't-fix (low severity, fix disproportionate/unsafe — rationale recorded)

- [x] codex-setup-4 — context smoke needs the full DB clone for the FTS+vector
      pipeline; "copy only memory_files" would break it. Overhead only.
- [x] se-08 — embedding-progress file is display-only (rows safe via INSERT OR
      IGNORE); pid/lock/heartbeat contract expansion not warranted.
- [x] hc-12 — switching persona-root cwd match from exact to under-root would
      widen a privacy boundary (AGENTS.md); case is already handled.
- [x] mfr-09 — correct fix (UNINDEXED FTS columns) lives in schema and needs a
      destructive FTS rebuild on existing DBs; gate already re-checks coverage.
- [x] mfr-10 — exhaustive in-Python cosine is the documented local-first vector
      path (identical in recall); changing only this site diverges it.
- [x] oauth-08 — duplicated Anthropic OAuth in hermes copy; `print(exc)` is an
      interactive CLI login path (not MCP), and dedup is risky drift surgery.
- [x] oauth-11 — JWT `exp` fallback only fires when both expires_at_ms and
      expires_in are absent (rare); stale token still caught by 401.
- [x] oauth-02 — orphaned loopback child is self-healing (reaped on first
      callback; bounded to the 15-min flow TTL).
- [x] schema-db-05 — additive migration is idempotent (re-run completes any
      half-applied state); explicit-transaction wrap is disproportionate.

### Fixes (per batch)

- [x] cli-08, cli-09 — embed `--limit` rejects negatives / treats 0 as no-cap;
      stdin buffered once so `codex context/exec` can't double-read `-`.
      Tests: `test_codex_context.py` (`_read_cli_text_arg` share, neg-limit).
- [x] codex-setup-3, codex-setup-5, codex-setup-6 — `_parse_diagnostic_timestamp`
      truncates 7-digit fractions for the 3.10 floor; `_resolve_cli_db_path`
      `expandvars` (fixes the review-queue doctor check for all four callers);
      TOML removal buffers comments so a note before a kept table survives.
      Tests: `test_codex_setup.py` (timestamp, comment-before-table).
      (codex-setup-4 won't-fix above.)
- [x] ec-03, ec-05, ec-06, ec-07, ec-08, ec-09, ec-10, ec-11 — runner no longer
      double-completes a succeeded job on persist-failure (ec-03) and skips a
      poison cost-cap job after `COST_CAP_MAX_DEFERRALS` (ec-11); dead Google
      CloudCode discovery/onboarding cluster (14 fns + 2 consts, blocking sleeps)
      removed (ec-05); worker usage ledger labels BYOK/local not always-oauth
      (ec-06); shadow report + claim `worker_request` sanitized (ec-07/ec-08);
      empty-provider worker budget gate resolves the configured provider (ec-09);
      file_id-less authored enqueue dedupes on fingerprint (ec-10). Tests in
      `test_memory_enhancement_{queue,runner}.py` (5 new + 1 updated).
- [x] cm-ent-004, cm-ent-005, cm-ent-007 — `memory_entity_edge_query` excludes
      expired edges by default (`current_only`); override map no longer renames a
      person whose name matches a short override key (person 'Pa' stays 'Pa');
      orphan-entity GC drops co-occurrence-only ghosts. Tests: `test_memory_entities.py`.
- [x] gsr-06, gsr-07, gsr-08 — review guard now always scans and records
      injection findings (block stays coupled to default-availability, so a
      restrict/reject remediation still writes but its findings are recorded);
      `_render_frontmatter_markdown` keeps non-ASCII frontmatter literal
      (`allow_unicode=True`); inspect compares indexed-vs-discovered paths on a
      normcase/normpath canonical form (Windows casing/8.3 drift). Tests:
      `test_memory_global_{review,seed}.py`. (gsr-06 promoted from won't-fix: the
      finding's record-only intent doesn't block remediation.)
- [x] hc-09, hc-11, ghh-12 — indexer memoizes per-file Codex session metadata
      (size+mtime keyed) so a backfill/poll pass doesn't rescan rollouts to EOF
      2-3x (hc-09); `_personas_dir_from_root` over-walk guard returns None instead
      of climbing past the drive root (hc-11); `collect_cm_health` surfaces a
      leak-safe class-name reason for runtime/provider profile faults and folds
      them into overall status (degraded, not silent ok) (ghh-12). Tests:
      `test_identity.py`, `test_memory_health.py`. (hc-12 won't-fix above.)

The Critical + all 16 High + the Medium findings plus the full harness
identification work and the Hermes setup command are complete and tested (full
suite green). The Low-severity polish pass is tracked above.
