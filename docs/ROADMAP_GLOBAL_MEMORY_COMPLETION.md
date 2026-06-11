# ChimeraMemory Global Completion Roadmap

Status key: `[x]` done, `[~]` active, `[ ]` pending.

## Operating Policy

- [x] Do not work on persona-specific memories for this goal.
- [x] Remove human-in-the-loop as a blocking requirement.
- [x] Replace manual approval gates with explicit automated trust policies,
  deterministic checks, audit receipts, rollback, and opt-in config.
- [x] Keep generated/imported/sidecar-produced memory provenance visible so
  automation can distinguish trusted, fallback, cached, generated, probe, and
  review-gated inputs.

## 1. Proven Baseline

- [x] Import Codex OAuth into the user-global CM auth store.
- [x] Restart the shared HTTP sidecar on current repo code.
- [x] Verify `codex doctor` reports `sidecar_health`.
- [x] Verify OpenAI Spark provider path:
  `openai/gpt-5.3-codex-spark`.
- [x] Verify live sidecar provider smoke succeeds with user OAuth.
- [x] Run full Python test suite.

## 2. Automated Promotion Policy

- [x] Define global-memory trust profiles for automated promotion.
- [x] Add config keys for no-human global promotion mode, defaulting safe/off.
- [x] Implement policy-as-code gates for promotion eligibility:
  provenance, source kind, sensitivity, injection scan, duplicate/superseded
  checks, instruction-grade readiness, and rollback metadata.
- [x] Add dry-run and write-mode CLI receipts for automated global promotion.
- [x] Add tests proving unsafe, sensitive, or weak-provenance memories do not
  become instruction-grade automatically.
- [x] Update docs so "human review" is not required when trusted automation is
  explicitly enabled.

## 3. Real Codex Injection Proof

- [x] Run `chimera-memory codex context` with global scope and confirm global
  evidence is returned.
- [x] Run real `chimera-memory codex exec --receipt-only --json` with global
  context and confirm prompt injection, stdin delivery, and delivery audit.
- [x] Confirm `codex doctor` reports real returned delivery, not only smoke.
- [x] Add or extend regression tests for the receipt fields that prove real
  Codex prompt augmentation.

Receipt: real `codex exec` delivery trace
`6a0c1e82-f156-454a-a02a-ab60d9cfdc71` returned 2 global cards with
`prompt_injected=true`, `subprocess_stdin_delivered=true`,
`real_delivery_recorded=true`, and `transport=stdin`.

## 4. Global Corpus Readiness

- [x] Inventory active global memory files and DB rows.
- [x] Identify pending, evidence-only, blocked, stale, duplicate, weak-about,
  and outside-root global rows.
- [x] Seed or repair high-value global memories needed for agent operation.
- [x] Reindex global memory and verify default-available and instruction-grade
  counts.
- [x] Add quality receipts for search/query/recall coverage without exposing
  memory bodies or raw paths.

Receipt: `global inspect --json` reports 2 markdown files, 2 indexed rows,
2 default-available rows, 2 instruction-grade rows, 0 pending review rows,
0 guard findings, and 0 outside-root rows.

## 5. Retrieval Quality And Traces

- [x] Build acceptance queries for global operational memory.
- [x] Measure `memory_context_pack`, `memory_search`, `memory_query`, and
  semantic recall against those queries.
- [x] Tighten ranking or metadata where global memory is missed or noisy.
- [x] Confirm public traces omit prompt text, memory bodies, credential-like
  values, and raw local paths.
- [x] Add focused regression tests for the chosen acceptance queries.

Receipt: acceptance queries for forward momentum, team knowledge, and global
operating memory return both global cards through context, FTS search,
structured query, and semantic recall. Hyphenated terms such as
`forward-momentum` are split for relevance matching.

## 6. Sidecar Persistence

- [x] Verify Windows autostart task or startup integration uses the repo venv,
  user-global state root, user-global OAuth store, global root, Codex MCP
  surface, and OpenAI provider affinity.
- [x] Restart through the persistent mechanism and rerun doctor/provider smoke.
- [x] Confirm stale-source detection warns after code changes and clears after
  restart.
- [x] Document the exact recovery command and expected safe receipts.

Recovery command:

```powershell
.\scripts\start-cm-http.ps1 -Port 8766 -GlobalRoot "$env:USERPROFILE\.chimera-memory\global-memory" -StateRoot "$env:USERPROFILE\.chimera-memory" -OAuthStore "$env:USERPROFILE\.chimera-memory\auth.json" -Provider openai -EnableProviderWorker -Replace
```

Receipt: Startup-folder command `ChimeraMemoryHttpMcp.cmd` cold-started the
listener, `codex doctor --json` returned `status=ok`, source freshness cleared,
and live provider smoke succeeded with `openai/gpt-5.3-codex-spark`.

## 7. Subagent Lanes

- [x] Diagnostics lane: audit doctor/traces/provider smoke for false positives.
- [x] Retrieval lane: evaluate global corpus search and context-pack quality.
- [x] Persistence lane: verify sidecar startup, logs, and source freshness.
- [x] Governance lane: review automated promotion policy and rollback receipts.
- [x] Docs lane: keep README, agent commands, module layout, and wiki aligned.

## 8. Shipping Boundary

- [ ] Separate current dirty worktree into coherent commits or a clear handoff.
- [x] Run focused tests for changed areas.
- [x] Run full `python -m pytest`.
- [x] Run wiki lint.
- [x] Run `git diff --check`.
- [ ] Sync into PersonifyAgents vendor copy if this runtime behavior must ship
  there.
- [ ] Run PA vendor/runtime checks if synced.

## 9. Final Acceptance

- [x] Fresh `codex doctor --json` is `ok`.
- [x] Fresh live provider smoke succeeds with Spark and user OAuth.
- [x] Fresh real Codex exec receipt proves global memory prompt injection.
- [x] Global corpus has useful default-available memory.
- [x] No persona-specific memory work was performed.
- [ ] Final handoff lists receipts, risks, changed files, and exact recovery
  commands.
