# Wiki Log

## [2026-06-09] init | repo wiki initialized

## [2026-06-09] ingest | initial Chimera-Memory source synthesis

- Captured source pointers for root docs, agent docs, deep architecture docs, package metadata, CI, server/MCP code, and module ownership docs.
- Added compiled pages for source policy, current repo state, runtime/module architecture, MCP/CLI surfaces, federated scope, enhancement boundaries, validation/vendor sync, and open drift.
- Rewrote root `AGENTS.md` as a compact routing hub that points agents through `.wiki/` and task-relevant canonical docs.

## [2026-06-09] export | global packet written to `.wiki/exports/latest-packet.json`

## [2026-06-09] export | global packet written to `.wiki/exports/latest-packet.json`

## [2026-06-10] update | context-pack quality gate documented

- Documented live, deterministic context-pack quality gating for global/project
  curated-memory recall.
- Noted that weak global matches should become traced misses instead of prompt
  evidence, while relevant global/current-project rows still survive.

## [2026-06-10] update | MCP memory-use instructions documented

- Documented live MCP server instructions for memory tool routing.
- Clarified that MCP instructions guide tool use but do not mechanically inject
  memory without a Codex-side hook, wrapper, or harness.

## [2026-06-10] update | Codex prompt-context wrapper documented

- Documented `chimera-memory codex context` as the no-persona Codex Desktop/CLI
  wrapper path for mechanical pre-turn evidence.
- Recorded the fail-closed project-id rule and idempotent CM-prefix stripping.
- Captured Windows stdin BOM normalization as part of the Codex wrapper boundary.
- Added hook-safe `--prompt-file` and `--previous-context-file` input paths.

## [2026-06-10] update | live retrieval scope policy documented

- Documented that `memory_live_retrieval_check` now uses shared
  persona/project/global scope filtering before suggesting memory.
- Recorded that Codex project MCP surface exposes the scoped read-only live
  retrieval checker.

## [2026-06-10] update | shared relevance gate documented

- Added `memory_relevance.py` as the shared deterministic quality gate for live
  retrieval and context packs.
- Documented that weak broad global/project matches are filtered before live
  retrieval suggestions as well as prompt context packs.

## [2026-06-10] update | semantic recall similarity floor documented

- Added a default `memory_recall` similarity floor to suppress weak semantic
  top-N noise in scoped global/project recall.
- Documented that callers may lower `min_similarity` explicitly for diagnostics.

## [2026-06-10] update | direct retrieval governance defaults documented

- Documented default `memory_search`, `memory_query`, and `memory_recall`
  exclusion of restricted, blocked-lifecycle, and non-evidence rows.
- Added explicit opt-in language for restricted/blocked review or debug access.

## [2026-06-10] update | scoped stats and provenance lookup documented

- Documented that `memory_stats`, `memory_source_refs`, and `memory_artifacts`
  now use the same live scope and default governance filters as retrieval.
- Recorded the single-project discovery rule that explicit
  `CHIMERA_MEMORY_PROJECT_ID` wins over folder-derived ids.

## [2026-06-10] update | Codex CLI memory exec documented

- Added `chimera-memory codex exec` as the Codex CLI launcher form of the
  no-persona project prompt wrapper.
- Recorded that wrapped memory context is fed to `codex exec -` through stdin,
  not through the child process command line.

## [2026-06-10] update | project transcript fallback documented

- Added opt-in project transcript snippets for Codex prompt wrapping.
- Documented the session-`cwd` workspace boundary so transcript fallback cannot
  search all local transcript history as automatic prompt evidence.

## [2026-06-10] update | direct semantic recall quality gate documented

- Extended `memory_recall` to use the shared query-term quality gate after the
  semantic similarity floor.
- Recorded that `min_similarity=0.0` remains the explicit raw diagnostic escape
  hatch and disables the quality gate.

## [2026-06-10] update | Codex prompt option documented

- Added explicit `--prompt` support for `chimera-memory codex context` and
  `chimera-memory codex exec` so manual diagnostics do not accidentally hit
  `--prompt-file` abbreviation behavior.
- Kept stdin and `--prompt-file` as the documented hook-safe input paths.

## [2026-06-10] update | transcript fallback observability documented

- Added sanitized `codex_transcript_context` recall traces for opt-in Codex
  project transcript fallback.
- Recorded `codex_transcript_context_*` audit events so future diagnostics can
  distinguish curated-memory misses from transcript fallback evidence.

## [2026-06-10] update | recall trace count semantics documented

- Updated recall trace recording so `result_count` can represent the filtered
  candidate/result set before limit or token-budget selection.
- Preserved `returned_count` as the number of surfaced trace items and recorded
  the same distinction in `recall_requested` audit payloads.

## [2026-06-10] update | exact search trace counts documented

- Updated `memory_search` traces to count total FTS matches after scope,
  governance, synthesis, and source-reference filters before applying the
  caller's requested limit.

## [2026-06-10] update | structured query trace counts documented

- Updated `memory_query` traces to count total structured matches after scope,
  governance, synthesis, and source-reference filters before applying the
  caller's requested limit.
- Recorded only `source_uri_supplied` in structured-query trace payloads so raw
  source identifiers do not leak into observability rows.
- Matched exact `memory_search` trace payload behavior to the same redaction
  rule.

## [2026-06-10] update | sidecar transport errors sanitized

- Drained small unauthorized HTTP sidecar request bodies before returning
  `auth_error` so Windows clients receive the bounded JSON error instead of a
  raw socket abort.
- Sanitized OS-level client transport errors to bounded availability failures
  without echoing request bodies or tokens.

## [2026-06-10] update | codex doctor context traces documented

- Added `codex doctor` checks for the latest context trace and latest returned
  context trace without exposing prompt text or memory bodies.
- Documented that MCP tools are on-demand and mechanical prompt evidence still
  requires `codex context`, `codex exec`, or another hook/harness.

## [2026-06-10] update | MCP context status diagnostic documented

- Added `memory_diagnose(mode="context")` for a compact, body-safe report of
  latest context attempts, latest returned context, and the wrapper/harness
  prompt-injection boundary.

## [2026-06-10] update | context diagnostics show local time

- Added shared diagnostic timestamp formatting so Codex/context diagnostics show
  stored UTC timestamps plus local-time companions.
- Documented that this avoids ambiguity when UTC trace rows fall on the next
  calendar date from the user's local day.

## [2026-06-10] update | benign asyncio disconnect logs filtered

- Added a narrow logging filter for Windows asyncio proactor connection resets
  during local HTTP MCP client disconnects.
- Kept unrelated asyncio errors visible so operational logs still expose real
  failures.

## [2026-06-10] update | stale active harness leases ignored

- Active-harness diagnostics now ignore same-host leases whose process IDs are
  no longer live, avoiding false conflict warnings after local MCP restarts.
- Live concurrent harnesses remain warning-only conflicts.

## [2026-06-10] fix | gaps diagnostic dependency declared

- Declared `networkx` as a runtime dependency because
  `memory_diagnose(mode="gaps")` uses graph analysis at runtime.
- Verified the live gaps diagnostic returns a graph summary instead of a missing
  dependency error.

## [2026-06-10] update | no-persona global authored writes

- Added explicit global scope support for structured authored memory writes
  through `memory_remember(scope="global")` and
  `chimera-memory enhance authored-write --scope global`.
- Fixed authored writeback sensitivity checks so request contracts and closed
  topic enums do not force every authored memory into restricted retrieval.

## [2026-06-10] fix | watcher schedules all project roots

- Fixed the memory file watcher to schedule every configured project memory
  root instead of only the last `CHIMERA_MEMORY_PROJECT_ROOTS` entry.
- Added coverage that watcher startup works when no project roots are present
  and that persona, shared, global, and multiple project roots are all watched.

## [2026-06-10] fix | codex global-only skips persona trees

- Tightened no-persona discovery and watcher startup so Codex/global-only and
  project-root runtimes skip private persona trees while still indexing and
  watching shared, global, and explicit project roots.
- Kept legacy multi-persona aggregation available only for unscoped admin-style
  runs that are not Codex/project configured.

## [2026-06-10] fix | codex sidecar global root diagnostics

- Codex project-mode template/install/startup paths now configure a CM-local
  global memory root and create it before watcher startup where the flow owns
  process launch.
- Health snapshots now include a path-safe runtime profile so `codex doctor`
  can warn when a reachable shared HTTP sidecar is not actually running as
  no-persona Codex project+global memory or lacks a global root.
- The runtime profile now separates global-root existence from indexed/default
  available global corpus counts, making an empty global memory corpus visible
  without treating it as a setup failure.
- `codex doctor` now overlays live `memory_files` global corpus counts when the
  transcript DB is readable, preventing stale low-cadence health snapshots from
  hiding already indexed global files.
- Empty global corpus diagnostics now include the operator fix path: add or
  promote global memories, or start the sidecar with a populated global root.
- Added `chimera-memory global seed`, a dry-run-first no-persona path for
  copying reviewed markdown into a configured global root and indexing it as
  `memory_scope=global`.
- Added `chimera-memory global inspect`, a read-only global corpus receipt for
  root existence, filesystem markdown counts, DB counts, and index drift.
- Global CLI helpers now default to `~/.chimera-memory/global-memory` when no
  `CHIMERA_MEMORY_GLOBAL_ROOT` is inherited, avoiding the legacy Claude global
  root footgun for Codex Desktop/CLI shells.
- `global seed` now supports repeatable include/exclude relative globs so mixed
  shared/global sources can seed reviewed global files without copying roster,
  relationship, image-feedback, or other persona-specific shared files.
- Added `chimera-memory global reindex`, a dry-run-first global-root-only DB
  repair command with explicit `--write` and opt-in `--prune-missing`.
- Write-mode global seed/reindex operations now record compact path-safe audit
  events with counts, filters, root provenance, fingerprints, and affected
  relative paths.
- Write-mode global seed/reindex now stamp missing or ambiguous global
  governance frontmatter before indexing, keeping imported global files
  evidence-only and pending review unless they already carry explicit confirmed
  instruction-grade provenance.
- Write-mode global seed/reindex now run the memory guard over selected files
  before copying, stamping, or indexing; credential, injection, or hidden-content
  findings fail closed with path-safe type/count receipts and no unsafe samples.
- `global inspect` now separates active target-root indexed/available counts
  from indexed global rows outside that root, with path-safe outside-row
  fingerprints for legacy shared/global overlap diagnostics.
- `memory_context_pack` now deduplicates post-quality-gate candidates by
  normalized content fingerprint and global relative path, preserving trace
  policy counts so shared/global overlap is visible without duplicating prompt
  evidence.
- The shared `global_memory_root()` helper now falls back to
  `~/.chimera-memory/global-memory`, aligning server, health, promotion, and
  authored global-write paths with Codex no-persona setup.
- Server-side memory helper paths now use the shared personas-dir resolver
  instead of the stale hard-coded ChimeraPersonas fallback.
- `memory_remember` write receipts now include path-safe indexing proof
  (`indexed` and `file_id`) so global writes can be verified immediately.
- Exact `memory_search` now applies the shared deterministic quality gate after
  FTS candidate selection, filtering weak broad-term global matches before
  returning results.
- Added `chimera-memory global review`, a preview-first durable review path for
  global-root markdown files. Write mode requires an explicit reviewer, preserves
  the markdown body, updates frontmatter, reindexes the reviewed file as
  `memory_scope=global`, writes a `memory_review_actions` row, and records a
  path-safe `global_memory_*` audit event. `confirm` is the explicit global
  instruction promotion action; other review outcomes keep the file out of
  instruction use.
- `codex doctor` now runs an in-memory global context smoke using indexed global
  metadata. This checks whether the `codex context` wrapper would return prompt
  evidence now while avoiding live trace writes, prompt text in reports, and
  memory body exposure.
- `codex doctor --json` now exposes a `context_delivery` receipt separating
  generic context traces, real `codex-context` wrapper traces, returned wrapper
  traces, and the no-write global smoke result, so sidecar reachability and
  wrapper capability are not mistaken for actual Codex prompt delivery.
- Global corpus diagnostics now distinguish default-available global evidence
  from confirmed instruction-grade global files. `codex doctor` reports this
  even before the first health snapshot when the live DB is readable.
- `chimera-memory codex exec --json` now summarizes child stdout/stderr by
  default and includes raw output only with explicit `--include-output`.
- `codex doctor` now performs a local HTTP MCP initialize identity check for
  shared sidecars, distinguishing an open TCP port from a ChimeraMemory MCP
  endpoint.
- `codex doctor` now emits `cm_health_freshness`, warning when the latest health
  snapshot is older than the freshness threshold so stale worker receipts do not
  masquerade as current health.
- `codex doctor` now emits `cm_real_wrapper_delivery_recency`, keeping
  historical wrapper delivery separate from fresh current-session prompt
  evidence.
- Context-pack cards now expose review/use-state authority markers such as
  `review=pending`, `evidence-only`, and `needs-confirmation`; the Codex
  grounding rule treats those records as unconfirmed leads rather than settled
  instructions.
- Full-reindex cleanup now prunes only rows under roots managed by the current
  discovery run. No-persona Codex/global/project reindexing preserves
  pre-existing persona-root rows when the persona tree was intentionally skipped.
- Global review write mode now re-runs the memory guard before review outcomes
  that would leave a file available to default global retrieval. Unsafe global
  files are blocked from promotion as evidence/instruction but can still be
  rejected, disputed, superseded, or restricted out of default retrieval.
- Global seed/reindex write receipts now return non-OK when governance stamping
  or indexing reports per-file errors, preventing partial global-memory repair
  runs from looking successful.
- Global seed/reindex now skip indexing files whose governance stamp failed in
  the same run, preventing unstamped imported markdown from entering global
  retrieval as accidental instruction-grade memory.
- Global seed/reindex receipts now also treat index skips as a non-OK outcome,
  even if a lower helper fails to increment a specific error counter.
- Global inspect now includes a read-only memory guard scan with sanitized
  finding counts and relative paths, making unsafe manual edits visible without
  running a write-capable seed or reindex command.
- `codex doctor` now reports optional `chimera-memory` wrapper command
  availability separately from HTTP MCP sidecar health, so a missing PATH shim
  is visible without making a reachable sidecar look broken.
- Write-mode global seed now fails closed before copying or indexing when any
  selected file has an unresolved target conflict, and JSON receipts report
  `ok: false` with `conflict_count` instead of relying only on the CLI exit code.
- Global review listings now include governance-repair files, not only explicit
  pending review files. Items expose sanitized review reasons and governance
  flags for missing policy keys, parse errors, wrong scope, or unsafe
  instruction-grade state.
- Codex/no-persona MCP context tools now accept JSON null for optional identity
  and routing fields, normalizing null `persona`, `project_id`,
  `previous_context`, and `scope` to empty/no-persona defaults instead of
  failing FastMCP validation.

## [2026-06-11] fix | codex global retrieval and delivery provenance

- Codex/no-persona MCP read tools now fail closed when `scope=auto` or
  `scope=project` has no resolved project id, and reject `scope=all` on the
  Codex surface. `scope=global` remains available for explicit global-only
  recall.
- Codex prompt-context traces now carry `delivery_mode`, while non-dry-run
  `chimera-memory codex exec` records a safe `codex_prompt_delivered` audit
  event only after the Codex subprocess returns. Doctor diagnostics reserve
  real delivery for that post-run event instead of inferring it from
  `actor=codex-context`.
- Restored the repo-scoped Codex doctor happy-path test, whose assertions had
  been stranded behind an unrelated helper return.
- Global review default-retrieval guard checks now use
  `exclude_from_default_search`, matching indexing and context retrieval.

## [2026-06-11] fix | global seed mixed-source guard

- `chimera-memory global seed` now records a `mixed_source_guard` receipt for
  selected roster, relationship, image-feedback, persona/private, or
  persona-prefixed paths.
- Write-mode seed fails closed before copying, stamping, indexing, or auditing
  when a broad source selection would import mixed shared/persona-style files.
  Operators can avoid the block with explicit include/exclude filters or with
  `--allow-mixed-source` for a reviewed compatibility import.

## [2026-06-11] improve | global review reason triage

- `chimera-memory global review` list receipts now include `summary.reason_counts`
  plus separate all-pending, matching, returned, and truncated counts.
- Added repeatable `--reason <REASON>` filtering over sanitized review reasons,
  allowing operators to focus global review on blockers such as
  `pending_review`, `missing_required_governance`, or `non_global_scope` without
  exposing memory bodies.

## [2026-06-11] improve | global review confirm guard preview

- `chimera-memory global review` list receipts now include sanitized
  confirm-action guard previews for pending files, surfacing files that would be
  blocked by instruction-grade confirmation before an operator attempts a write.
- The CLI text output reports the confirm-guard blocked count, while JSON
  receipts expose only finding type/count and relative path, not memory bodies,
  guard patterns, or samples.

## [2026-06-11] improve | global review action guard receipts

- Human-readable `chimera-memory global review --relative-path ... --action ...`
  output now reports sanitized review-guard required, blocked-file, and finding
  counts on previews, successful writes, and failed writes.
- Failed unsafe `confirm --write` attempts now show the same guard counts in text
  mode that JSON already carried, without exposing memory bodies, guard samples,
  or patterns.

## [2026-06-11] improve | codex doctor global review readiness

- `chimera-memory codex doctor` now checks the no-persona global review queue
  when a project/global Codex runtime is configured.
- The diagnostic reports sanitized pending/reason counts plus confirm-guard
  blocked/finding counts, warning when pending global memory would be blocked by
  instruction-grade confirmation without exposing file bodies or raw paths.

## [2026-06-11] improve | global review filtered summaries

- `chimera-memory global review --reason ...` receipts now include
  `matching_summary` and `returned_summary` alongside the all-pending `summary`.
- Filtered human output reports matching review reasons and matching
  confirm-guard blocked counts, so all-pending unsafe files outside the filter
  do not get mistaken for risks in the currently reviewed slice.

## [2026-06-11] fix | global review parse-error remediation

- Global review actions can now remediate malformed-frontmatter files by treating
  the original source text as the preserved markdown body under repaired review
  frontmatter.
- Malformed sources are reported as pending/untrusted before review, and unsafe
  parse-error files still run through the post-review memory guard before any
  default-retrievable outcome can be written.

## [2026-06-11] fix | global review restore on index failure

- Write-mode global review now attempts to restore the original markdown if the
  post-write index/review-audit step fails or raises.
- Failure receipts include a `restore` object and set `written: false` when the
  restore succeeds, preventing silent DB/markdown drift after partial review
  writes.

## [2026-06-11] fix | parse-error confirm guard preview

- Global review listings now build confirm-guard previews for
  malformed-frontmatter sources through the same preserved-body repair path used
  by review actions.
- Codex doctor global-review diagnostics now count unsafe malformed sources in
  sanitized confirm-guard blocked/finding totals without exposing source text.

## [2026-06-11] fix | shared HTTP stale runtime guard

- `scripts/start-cm-http.ps1` now refuses to silently accept an existing
  ChimeraMemory listener on the configured port when that listener was launched
  from a different Python runtime than the repo-local `.venv`.
- Operators get an explicit stale PID list and must rerun with `-Replace` after
  confirming replacement.

## [2026-06-11] improve | codex doctor listener runtime check

- `chimera-memory codex doctor` now inspects local HTTP listener ownership on
  Windows and warns when the sidecar port is owned by a Python runtime that does
  not match the doctor/repo runtime.
- The warning is path-safe: reports include owner counts, process names, and
  stale PIDs, not raw process commands or executable paths.

## [2026-06-11] improve | global inspect authority summary

- `chimera-memory global inspect` receipts now include a filesystem-frontmatter
  `authority` summary for evidence-enabled, trusted instruction-grade,
  pending-review, evidence-only, confirmation-gated, and unsafe
  instruction-grade global files.
- Human-readable `global inspect` output now reports trusted instruction-grade
  and review-gated counts so retrievable evidence is not mistaken for settled
  instruction.

## [2026-06-11] improve | global review confirm-guard filter

- `chimera-memory global review --reason confirm_guard_blocked` now filters to
  files whose sanitized confirm-action preview would be blocked by the memory
  guard.
- The virtual reason also surfaces otherwise confirmed instruction-grade global
  files when unsafe body content would make confirmation unsafe.

## [2026-06-11] improve | global reindex authority summary

- `chimera-memory global reindex` receipts now include selected-file
  filesystem-frontmatter `authority` counts so dry runs show whether selected
  files are evidence-enabled, trusted instruction-grade, pending-review,
  confirmation-gated, or unsafe instruction-grade before indexing/stamping.

## [2026-06-11] improve | global review text targets

- Human-readable `chimera-memory global review` listings now include returned
  root-relative review targets with per-file reasons, indexed state, and
  confirm-guard blocked counts while continuing to omit memory bodies and raw
  absolute file paths.

## [2026-06-11] improve | codex context trace history

- Added `chimera-memory codex traces` to report recent sanitized Codex
  context/delivery traces, classify prompt construction versus diagnostic smoke,
  generic context traces, and real `codex exec` delivery, and support
  `--real-only` without exposing prompt text, memory bodies, raw trace payloads,
  or raw paths.

## [2026-06-11] improve | codex trace date filter

- `chimera-memory codex traces` now accepts `--since` for date-bounded
  diagnostics; explicit timezone timestamps are safest, and date-only values
  are interpreted as the local day start.

## [2026-06-11] improve | codex wrapper project inference

- `chimera-memory codex context` and `chimera-memory codex exec` now infer
  no-persona project id/root from `--project-root`, `--cd`, or the current repo
  directory when safe, while the focused context builder still fails closed
  without an explicit or configured project id.

## [2026-06-11] improve | codex wrapper receipt-only diagnostics

- `chimera-memory codex context` and dry-run `chimera-memory codex exec` now
  support `--receipt-only` so operators can verify scope, counts, and trace ids
  without printing prompt text, memory bodies, or fenced evidence blocks.

## [2026-06-11] fix | memory recall FTS rescue

- `memory_recall` now merges semantic candidates with a strict FTS/body-match
  rescue path so exact global/project memory terms can surface even when their
  embedding score falls below the default semantic floor.
- Recall traces label returned items with sanitized source metadata such as
  `fts_rescue` or `hybrid` and split semantic, FTS, combined, quality-gate, and
  compatibility filtered counts without recording memory bodies.
- Explicit `min_similarity` values above the default disable the rescue so
  stricter semantic diagnostics remain strict.

## [2026-06-11] improve | codex delivery recommendations

- `chimera-memory codex traces` and `codex doctor` now include body-safe
  recommendations when context construction exists but no real `codex exec`
  delivery is recorded.
- Windows HTTP listener diagnostics now include sanitized match-source counts
  so a repo-venv parent launcher can be distinguished from a stale unrelated
  Python listener without exposing raw command lines or executable paths.

## [2026-06-11] improve | codex sidecar source freshness

- `chimera-memory codex doctor` now reports
  `http_listener_source_freshness`, comparing the HTTP listener process start
  time against selected ChimeraMemory runtime source mtimes so a reachable but
  stale loaded sidecar produces a restart warning.

## [2026-06-11] improve | global review recommendations

- `chimera-memory global review` receipts now include body-safe recommendations
  for listing the queue, previewing confirmation, writing confirmation after
  human review, marking reviewed files evidence-only, and inspecting
  confirm-guard blockers.
- `codex doctor` exposes the same global-memory recommendations when the
  no-persona global review queue is not clear.

## [2026-06-11] improve | global review action guidance

- Global review list items now include `action_guidance`, a guard-derived
  per-action matrix for whether confirm/evidence/remediation actions can be
  written without guard blockage, leave the file default-retrievable, or promote
  instruction use.
- Human-readable review targets now summarize the recommended next actions as
  `actions=...` without exposing memory bodies.

## [2026-06-11] improve | global review action recommendations

- Global review action previews and guard-blocked write failures now return
  body-safe `recommendations` derived from the action-guidance matrix.
- Clean previews recommend the exact write command after human review; blocked
  previews avoid a write recommendation and suggest remediation previews such as
  `reject`, `restrict_scope`, `dispute`, or `supersede`.

## [2026-06-11] improve | Codex wrapper launch-failure receipts

- `chimera-memory codex exec` now returns a sanitized failed-launch receipt when
  Codex cannot be started, without exposing raw prompt text, raw command lines,
  raw output, or local exception text.
- Failed wrapped exec attempts record `codex_prompt_delivery_failed`; `codex
  traces` and `codex doctor` classify that state separately from dry-run prompt
  construction and successful real `codex exec` delivery.
- Failed-launch recommendations are recency-aware, so an older failed wrapper
  attempt stops leading diagnostics once a newer real `codex exec` delivery
  exists.

## [2026-06-11] improve | Codex trace delivery-kind filters

- `chimera-memory codex traces` now supports repeatable `--kind` /
  `--delivery-kind` filters for real, failed, prompt-construction, diagnostic,
  and generic context traces.
- Trace receipts include a sanitized `latest_delivery_attempt` computed before
  kind filtering, so failed-only views can still avoid stale failed-launch
  recommendations after a newer real wrapper delivery.

## [2026-06-11] improve | global review queue recommendation guards

- Global review queue recommendations now use per-file action guidance before
  suggesting write commands.
- Guard-blocked default-retrievable files keep preview-confirm guidance but
  replace blocked confirm/evidence-only write suggestions with preview-only
  remediation actions such as reject, restrict-scope, dispute, or supersede.

## [2026-06-11] fix | global missing-frontmatter authority

- Global inspect/reindex/review receipts now treat missing or unrecognized
  global-root frontmatter as imported, pending, evidence-enabled,
  instruction-disabled, and requiring confirmation.
- Confirm-guard previews still scan the preserved source body for unsafe content
  and report sanitized blocked counts without echoing memory bodies.

## [2026-06-11] improve | global wrapper delivery recommendations

- When `codex doctor` global context smoke returns evidence but no real Codex
  exec delivery exists, context-delivery recommendations now include
  `--scope global` on proof and delivery commands.
- This keeps the no-persona global-memory verification path independent of
  project-id inference from the current shell directory.

## [2026-06-11] improve | Codex trace returned-scope metadata

- `chimera-memory codex traces` now includes sanitized request scope metadata
  and returned memory scope counts, such as `returned_scopes=global=1`, without
  printing prompts, memory bodies, raw payloads, or raw paths.
- When no real Codex exec delivery exists and the latest returned prompt
  construction contains only global memory, trace recommendations now use
  `--scope global` for wrapper proof and delivery commands.

## [2026-06-11] improve | global review target inspection

- `chimera-memory global review --relative-path <RELATIVE_PATH>` now inspects a
  single global review target when no action is supplied, returning review
  reasons, frontmatter keys, indexed/default availability, guard status, body
  hash, body length, and recommendations without memory body text.
- The action path still requires `--action`; action previews and write-mode
  review behavior are unchanged.

## [2026-06-11] improve | doctor global review target commands

- Global review queue receipts now keep `first_matching_relative_path` even when
  `--limit 0` returns no file rows, allowing low-volume diagnostics to emit
  concrete body-safe target-inspection commands.
- `chimera-memory codex doctor` now surfaces that concrete inspection command
  for the first pending global review target instead of falling back to a
  placeholder `<RELATIVE_PATH>` action command.

## [2026-06-11] improve | Codex exec delivery proof receipts

- `chimera-memory codex exec` receipts now include a body-safe `delivery_proof`
  object that separates prompt construction, wrapped-prompt memory injection,
  subprocess stdin delivery, delivery-event recording, and launch failure.
- Dry-run receipt-only checks can now prove that global memory was injected into
  the wrapped prompt while still clearly reporting that no subprocess stdin
  delivery or real delivery event occurred.

## [2026-06-11] improve | global review first-target guidance

- `chimera-memory global review --limit 0` now retains a body-safe
  `first_matching_target` summary with review reasons, guard counts, indexed
  state, and action guidance while still returning no file rows or memory body
  text.
- Codex doctor and other low-volume diagnostics can now emit the same concrete
  inspect/confirm/evidence-only/remediation recommendations that full queue
  listings provide.

## [2026-06-11] fix | Codex wrapper Windows launch

- `chimera-memory codex exec` now normalizes bare Windows `codex` launches to a
  launchable shim such as `codex.cmd` or `codex.exe`, avoiding the extensionless
  npm shim that caused Python subprocess `PermissionError` before prompt
  delivery.
- A live global wrapper smoke recorded a real `codex_prompt_delivered` event
  with two global memory cards and a successful stdin delivery proof.
- `codex traces --kind failed` now suppresses stale no-real-delivery
  recommendations when the unfiltered latest delivery attempt is a newer real
  wrapper delivery.

## [2026-06-11] improve | global inspect review recommendations

- `chimera-memory global inspect` now includes body-safe global review
  recommendations when review-gated files are present, reusing the durable
  review queue guidance instead of leaving authority gaps as raw counts.
- Human-readable inspect output now lists the same concrete next commands
  without echoing memory body text.

## [2026-06-11] improve | provider credential import diagnostics

- Provider-plan receipts now distinguish missing CM credentials from importable
  Codex/OpenAI OAuth and return a body-safe `import_openai_codex_oauth`
  recommendation without token values.
- Shared HTTP sidecar startup/autostart scripts now carry user-global CM
  state/auth store defaults plus explicit provider/OAuth-store options so
  scheduled starts do not fall back to repo-local dry-run credentials.

## [2026-06-11] fix | retrieval context-fence feedback guard

- Shared relevance cleaning now strips `chimera-transcript-context` fences in
  addition to existing memory-context fences.
- Live retrieval term extraction now uses the shared cleaned context text, so
  prior injected memory or transcript evidence cannot become fresh topic-shift
  signal for global/project recall.

## [2026-06-11] fix | watcher handler project boundary

- Added event-level coverage for multiple configured project roots: create
  events under each root index with the matching `project:<id>`.
- Tightened the watcher handler so no-persona Codex/project mode rejects
  persona-path events even if one reaches the shared handler unexpectedly.

## [2026-06-11] fix | global review relative-path hardening

- `chimera-memory global review --relative-path ...` now rejects leading
  separators and control characters instead of normalizing them into a
  root-relative target.
- Added coverage for body-safe target inspection and review-action resolution
  so global review targets remain explicit root-relative markdown paths.

## [2026-06-11] fix | global review recommendation quoting

- Global review recommendation commands now keep simple relative paths
  double-quoted but switch shell-active targets to PowerShell-safe single-quote
  escaping.
- Added coverage for filenames containing quotes and `$()` so copyable
  recommendation commands do not invite shell expansion.

## [2026-06-11] fix | global reindex prune relative authority

- `chimera-memory global reindex --prune-missing` now derives stale-row
  filter matching and receipt relative paths from each row's resolved path under
  the selected global root, not a drifted stored DB `relative_path`.
- Added regression coverage for filtered prune repair when a global DB row's
  stored relative path contains `../` drift.

## [2026-06-11] fix | global review Windows target aliases

- `chimera-memory global review --relative-path ...` now rejects Windows
  drive-relative aliases such as `C:TEAM_KNOWLEDGE.md` and stream-style `:`
  separators instead of resolving them to a different root-relative file.
- Added target-inspection coverage for drive-relative and stream-separator
  review targets.

## [2026-06-11] fix | context pack raw-path fallback

- `memory_context_pack` prompt-card formatting now uses a root-relative path
  when available or a synthetic scoped ID such as `global#<file_id>` when a
  legacy row lacks `relative_path`.
- Added regression coverage proving a drifted global row cannot place its raw
  filesystem path into the injected context block.

## [2026-06-11] fix | Codex MCP persona bypass

- The Codex no-persona MCP guard now rejects explicit `persona` arguments and
  env-derived `TRANSCRIPT_PERSONA` identity instead of treating them as
  permission to include persona-private memory.
- Wired the guard through `memory_stats`, `memory_remember`, and
  `memory_promote_snapshot` in addition to existing search/recall/context/live
  retrieval tools, with regression coverage for the `Persona-only-secret`
  bypass.

## [2026-06-11] fix | low-level hidden memory discovery

- Full-reindex and watcher discovery now skip hidden/cache/auth/symlink child
  paths under shared, global, project, and persona memory roots while preserving
  configured hidden roots such as `.chimera-memory`.
- Added scope coverage for hidden global/project full-reindex inputs and
  watcher-created hidden child paths.

## [2026-06-11] fix | Codex MCP persona review exposure

- Removed the persona-facing `memory_review` queue from the Codex no-persona MCP
  surface while preserving it on persona/full surfaces.
- Added surface registration tests proving Codex project mode does not register
  `memory_review`.

## [2026-06-11] fix | Codex MCP diagnose surface

- `memory_diagnose` on the Codex no-persona surface now rejects persona/admin
  modes such as zones, traces, trace analysis, audit, harness, gaps, and
  consolidation.
- Codex diagnose tool-surface text now describes project/global diagnostics and
  no longer advertises the persona review queue.

## [2026-06-11] fix | Codex MCP persona promotion exposure

- Removed persona-source `memory_promote_snapshot` from the Codex no-persona MCP
  surface while preserving it on persona/full surfaces.
- Updated Codex surface tests and diagnose text so no-persona Codex exposes
  project/global authored writes but not persona snapshot promotion.

## [2026-06-11] fix | CLI worker doctor readiness receipts

- `chimera-memory enhance worker-doctor` now reports path-safe file-role
  readiness and a redacted command profile instead of raw local paths or launch
  argv.
- Codex/Claude worker readiness now requires copied worker-local auth or
  credentials before `ok=true`; missing credentials are visible as missing
  required roles without exposing filesystem locations.

## [2026-06-11] fix | Codex MCP instruction surface

- MCP server instructions are now surface-aware: Codex project mode advertises
  scoped project/global curated-memory tools and explicitly says generic
  transcript recall tools are absent from the Codex MCP surface.
- Updated Codex/global docs so transcript fallback is routed through the Codex
  wrapper `--include-transcripts` path rather than hidden MCP transcript tools.

## [2026-06-11] fix | imported memory trust boundary

- Imported memory is no longer instruction-grade by provenance alone. Shared
  governance, authored writeback normalization, health counts, Codex doctor
  counts, and global seed/review authority checks now require
  `user_confirmed` provenance for instruction-grade status.
- Legacy imported files that claim confirmed instruction use are flagged for
  global review as unsafe/untrusted instruction claims instead of being counted
  as trusted global operating rules.

## [2026-06-11] fix | whereami global-root provenance

- `memory_whereami` / `memory_diagnose(mode="whereami")` now report the
  resolved global memory root and whether it came from
  `CHIMERA_MEMORY_GLOBAL_ROOT` or the default global-root resolver.
- Codex project-mode tests assert whereami includes global-root provenance, so
  no-persona project/global diagnostics can prove both project and global
  wiring.

## [2026-06-11] fix | Codex global-only stats diagnose

- On the Codex no-persona MCP surface, `memory_diagnose(mode="stats")` now uses
  global-only stats when no project id/root is configured instead of falling
  through to unscoped operator/admin stats.
- Regression coverage asserts direct auto-scoped tools still fail closed
  without a project while diagnose stats reports only global corpus counts.

## [2026-06-11] fix | Windows HTTP sidecar venv owner detection

- `scripts/start-cm-http.ps1` now checks listener owners only for listening
  sockets and accepts the Windows venv-launcher process tree where the socket
  owner is base `python.exe` and the parent process is the repo `.venv` Python.
- Added a script regression test and live-smoked restart/reuse on port 8766 so
  a valid venv-launched sidecar is no longer mistaken for a stale global Python
  listener.

## [2026-06-11] fix | global stamp confirmation gate

- Global seed/reindex governance stamps now force
  `requires_user_confirmation: true` for imported, non-`user_confirmed`, or
  originally non-global files while demoting instruction claims, preventing
  legacy frontmatter from durably saying confirmation is unnecessary.
- Added seed and reindex regressions proving legacy imported instruction claims
  and confirmed project-scope instruction claims are indexed as
  non-instruction, confirmation-gated global evidence.

## [2026-06-11] fix | Codex doctor global-root diagnostics

- `chimera-memory codex doctor` now counts configured-root global DB rows
  separately from indexed global rows outside `CHIMERA_MEMORY_GLOBAL_ROOT` and
  warns with counts when outside-root rows exist.
- The no-write global context smoke masks outside-root global rows in its
  in-memory DB copy, so outside-root rows can no longer prove the configured
  Codex global memory path healthy.

## [2026-06-11] fix | global context active-root filter

- `memory_context_pack` now accepts an active global-root filter and excludes
  global DB rows outside that root while preserving project/persona scope
  behavior.
- MCP `memory_context_pack` and Codex `context`/`exec` wrappers pass the active
  global root when configured, preventing stale outside-root global rows from
  being injected as prompt evidence.

## [2026-06-11] fix | live retrieval synthesis filter

- `memory_live_retrieval_check` now excludes
  `exclude_from_default_search: true` synthesis rows by default and requires
  explicit `include_synthesis=true` to surface generated summaries.
- Added primitive and Codex MCP regressions proving default live retrieval misses
  synthesis-only matches while opt-in retrieval can return them.

## [2026-06-11] fix | Codex context trace ownership

- `chimera-memory codex doctor` now treats only Codex-owned
  `codex-context` audit traces as evidence of Codex prompt-context readiness
  when recall/audit tables exist.
- Generic MCP, persona, or admin context traces remain visible as generic trace
  metadata but no longer make Codex readiness checks report `ok`.

## [2026-06-11] fix | live retrieval active-root filter

- `memory_live_retrieval_check` now accepts an active global-root filter and
  excludes global DB rows outside that root while preserving project/persona
  scope behavior.
- MCP live retrieval passes `CHIMERA_MEMORY_GLOBAL_ROOT` through the shared
  root filter, preventing stale outside-root global rows from being suggested as
  active Codex memory.

## [2026-06-11] fix | direct retrieval active-root filter

- Direct curated-memory reads (`memory_search`, `memory_query`,
  `memory_recall`, `memory_stats`) now accept an active global-root filter and
  exclude outside-root global DB rows while preserving project/persona rows.
- Provenance metadata lookups (`memory_source_refs`, `memory_artifacts`) use
  the same optional root boundary, and Codex MCP wrappers pass
  `CHIMERA_MEMORY_GLOBAL_ROOT` into direct read tools so stale global rows are
  not returned or counted as active Codex memory.

## [2026-06-11] fix | latest Codex wrapper diagnostic

- `chimera-memory codex doctor` now reports the latest real wrapped Codex exec
  attempt even when it returned zero memory cards, instead of leading with an
  older real wrapped attempt that returned evidence.
- Doctor still reports the latest returned real wrapper delivery separately and
  recommends a body-safe context probe when the newest real delivery produced no
  memory evidence.

## [2026-06-11] fix | Codex wrapper default global root

- `chimera-memory codex context` and `codex exec` now resolve global evidence
  through explicit `--global-root`, then `CHIMERA_MEMORY_GLOBAL_ROOT`, then CM's
  default global root, matching MCP/doctor active-root behavior.
- Added a CLI regression proving default-root global prompt wrapping excludes
  outside-root global DB rows even when no root flag or env var is supplied.

## [2026-06-11] improve | Codex doctor real-delivery effectiveness

- `chimera-memory codex doctor` now emits a warning when the no-write global
  context smoke can retrieve memory but the latest real wrapped Codex exec
  delivery returned zero memory cards.
- Added a regression proving that this state is not hidden behind a green setup
  summary and that prompt text and memory body text remain redacted.

## [2026-06-11] improve | global inspect outside-root guidance

- `chimera-memory global inspect` now includes body-safe recommendations when
  indexed global DB rows exist outside the configured global root, making clear
  that active retrieval excludes those rows.
- The human receipt now reports the outside-root row count and points operators
  to path-safe `global inspect --files --json` plus active-root reindexing
  rather than implying outside-root rows should be pruned automatically.

## [2026-06-11] improve | prompt lifecycle authority labels

- Context-pack cards now include `lifecycle=<status>` when a returned memory is
  non-active, so stale or archived global evidence cannot look like current
  settled context just because it is confirmed.
- The Codex prompt grounding rule now treats `lifecycle=stale` and
  `lifecycle=archived` evidence as non-current leads, with regressions covering
  both raw context packs and Codex prompt wrapping.

## [2026-06-11] harden | global maintenance path-safe receipts

- `global review --relative-path --action` receipts no longer return the
  absolute target file path; they keep the relative target, hashes, guard
  counts, and review/audit metadata.
- `global reindex --prune-missing` prune-candidate receipts now mirror
  outside-root inspection safety by returning `relative_path`, `name`, and a
  short `path_fingerprint` instead of raw stale DB paths.

## [2026-06-11] harden | global review skipped-corpus boundary

- Explicit `global review --relative-path` target resolution now rejects hidden,
  auth/cache-style, symlink, and other skipped corpus paths before reading or
  writing, matching global discovery/seeding boundaries.
- Added regressions proving skipped targets cannot be inspected or actioned and
  that their body text remains absent from receipts.

## [2026-06-11] harden | global seed path-safe roots

- `global seed` receipts now report source, target, and index DB locations as
  path-safe payloads with names, provenance labels, and fingerprints instead of
  raw absolute paths.
- Human seed output now prints the same safe target label, and regressions cover
  dry-run JSON, write JSON, nested-root errors, and text preview output.

## [2026-06-11] harden | global inspect, reindex, and review path-safe roots

- `global inspect`, `global reindex`, and `global review` receipts now report
  global root and DB locations as path-safe payloads with names, provenance
  labels, and fingerprints instead of raw absolute paths.
- Human inspect/reindex/review output now prints safe root labels, and
  regressions prove JSON/text receipts omit temp root and DB paths.

## [2026-06-11] harden | Codex trace DB path-safe receipts

- `codex traces` JSON now reports the selected trace DB as a path-safe payload
  with name, provenance, and fingerprint instead of a raw absolute path.
- Human `codex traces` output now prints the same safe DB label, and
  regressions prove JSON/text receipts omit temp DB paths.

## [2026-06-11] implement | global inspect query smoke

- `global inspect --query <TEXT>` now runs a read-only global context-pack
  smoke against an in-memory copy of the selected DB, so operators can prove
  whether active global memory is retrievable for a task without writing recall
  traces or audit rows.
- The `query_smoke` receipt returns counts and safe card metadata only:
  relative paths, governance labels, scores, and query-match profiles, with no
  memory bodies, snippets, card text, prompts, raw DB paths, or raw root paths.

## [2026-06-11] harden | provenance URI MCP display

- `memory_source_refs` and `memory_artifacts` MCP text now redacts local
  path-shaped source/artifact URIs to `local-path:<name>` plus a short
  fingerprint instead of printing raw local paths.
- Lower-level query APIs still retain stored URI values for internal
  review/debug use, and the MCP tools now share the Codex no-persona scope
  guard used by other Codex-safe surfaces.

## [2026-06-11] improve | global query smoke miss diagnostics

- `global inspect --query <TEXT>` miss receipts now include body-safe
  diagnostics for candidate generation, quality-gate filtering, dedupe, and
  packing-stage gaps.
- Human output prints the safe stage/reason and aggregate candidate counts so
  operators can tell a true scoped miss from relevance filtering without
  exposing memory bodies, prompt text, raw roots, or raw DB paths.
- The same miss states now emit body-safe recommendations for reindexing,
  active-root inspection, query refinement, duplicate inspection, or a larger
  query token budget.

## [2026-06-11] harden | global review body hash preconditions

- `global review --relative-path ... --action ...` now accepts
  `--expect-body-sha256 <HASH>` and write mode now requires it, failing closed
  before mutation when the expected hash is missing, invalid, or differs from
  the current reviewed body.
- Body-safe target inspection and preview recommendations include the expected
  body hash when available, preventing stale preview-to-write promotion without
  exposing memory bodies or raw paths.

## [2026-06-11] harden | global inspect dry-run repair recommendations

- `global inspect` and query-smoke missing-DB recommendations now point to
  `chimera-memory global reindex --json` so diagnostics lead with a dry-run
  preview before any DB write or governance stamp.
- Outside-root row guidance still recommends path-safe file inspection, but no
  longer presents `global reindex --write` as the first repair command.

## [2026-06-11] harden | global seed broad include mixed-source guard

- `global seed --include "**/*.md"` no longer bypasses the mixed-source guard
  for selected roster, persona, private, relationship, or image-feedback paths.
- Mixed-source findings are exempted only when the matching include pattern
  names a mixed path segment/prefix, or when `--allow-mixed-source` is supplied
  for an intentional reviewed compatibility import.

## [2026-06-11] harden | Codex doctor rootless global memory

- `chimera-memory codex doctor` now requires an active
  `CHIMERA_MEMORY_GLOBAL_ROOT` before no-persona project diagnostics count live
  global DB rows as active memory.
- Rootless no-persona project diagnostics report indexed all-global rows as
  inactive and skip the no-write global context smoke, preventing stale DB rows
  from proving active Codex global-memory delivery.

## [2026-06-11] harden | global reindex prune side-table cleanup

- `global reindex --prune-missing --write` now manually removes file-owned side
  table rows for pruned global file ids, including source refs, artifacts,
  entity links, file edges, embeddings, FTS rows, and pyramid summaries.
- Nullable historical references on recall items, review actions, and
  enhancement jobs are cleared to `NULL`, so prune cleanup does not depend on
  SQLite foreign-key pragmas being enabled.

## [2026-06-11] harden | global corpus path and review boundaries

- Global seed/inspect/reindex/review skipped-corpus checks now treat reserved
  hidden/cache/auth-style path segments case-insensitively, so Windows-style
  variants such as `Auth/` and `Cache/` are not discoverable or reviewable.
- Global inspect outside-root rows, prune candidates, and query-smoke cards now
  collapse path-shaped stored DB `relative_path` values to filename-only labels
  before returning receipts.
- Settled non-confirm global review actions now write durable
  `user_confirmed` governance while keeping `can_use_as_instruction: false`,
  preventing evidence-only/rejected/stale/superseded decisions from looping in
  the review queue.

## [2026-06-11] harden | retrieval display path boundary

- Added a shared memory path display helper for MCP/prompt text and global
  receipts: safe relative paths remain visible, while absolute/path-shaped DB
  values collapse to filename labels.
- Public `memory_recall_trace_query(include_items=True)` now returns
  display-safe item `path`/`relative_path` labels plus `path_fingerprint`,
  avoiding raw local filesystem paths in trace inspection payloads.
- MCP retrieval, context-pack, live retrieval, source/artifact, review, import,
  graph, pyramid, enhancement, and cognitive report text now routes memory path
  display through the safe-label boundary.

## [2026-06-11] harden | audit query path boundary

- Public `memory_audit_query` now sanitizes path-like target ids and payload
  fields on read, preserving safe relative memory paths while converting local
  filesystem paths to filename/fingerprint receipts.
- The MCP audit display inherits the sanitized query output, closing a second
  observability channel after recall trace item path sanitization.
- Audit sanitizer edge cases preserve non-local URI targets and opaque ids while
  still converting Windows drive paths and relative traversal under path-like
  fields to safe labels.

## [2026-06-11] harden | audit query sensitive payload boundary

- Public `memory_audit_query` now redacts sensitive prompt, body, command,
  process-output, and credential-like payload fields on read and returns compact
  redaction receipts with field/type/size metadata.
- Non-sensitive error/status fields remain readable after sanitizer and local
  path redaction, so diagnostics can explain failures without exposing raw
  prompts, memory bodies, commands, stderr/stdout, or tokens.

## [2026-06-11] harden | enhancement CLI receipt boundary

- Enhancement queue storage still preserves raw local paths and request payloads
  for workers, but client-facing CLI receipts now sanitize queued/completed job
  JSON before display.
- `enhance enqueue`, `authored-enqueue`, `dry-run`, `worker-fake`, and nested
  authored-write `enrichment_job` receipts now return safe path
  labels/fingerprints and redacted request/result payload fields instead of raw
  local paths, wrapped memory content, authored payload bodies, or body-derived
  metadata.

## [2026-06-11] harden | global review preview frontmatter boundary

- Preview-mode `global review --relative-path --action` receipts now return a
  display-safe `preview_frontmatter` view: string values are passed through
  secret sanitization and local-path redaction before public display.
- Write-mode review still preserves and persists the canonical reviewed
  frontmatter/body content; only the preview receipt is sanitized.

## [2026-06-11] improve | global query smoke candidate profiles

- `global inspect --query <TEXT>` quality-gate miss diagnostics now include
  body-safe candidate profiles: safe relative labels, governance flags, ranking
  scores, quality-gate pass/fail, and query-term coverage.
- Text output prints the same compact profile lines so operators can see whether
  a miss needs more specific task terms or stronger global `about`/`tags`
  metadata, without exposing memory bodies, snippets, prompts, or raw paths.

## [2026-06-11] harden | global query smoke matched terms

- `global inspect --query <TEXT>` now sanitizes query-match `matched_terms`
  before JSON or text display, so useful term-coverage diagnostics do not echo
  credential-shaped prompt terms.
- The smoke remains read-only and still omits memory bodies, snippets, card
  text, prompts, raw DB paths, and raw root paths.

## [2026-06-11] harden | prompt and MCP prose redaction

- Context-pack prompt card prose now sanitizes credential-like values and local
  path references in snippets, `about` fallback text, and truncated card text
  before building injected evidence.
- Codex/global MCP retrieval text (`memory_search`, `memory_query`,
  `memory_recall`, and live retrieval suggestions) now applies the same
  display-time prose sanitization without changing raw DB storage or matching.

## [2026-06-11] harden | recall trace payload boundary

- Public `memory_recall_trace_query` now sanitizes request/response payloads
  and returned item metadata on read, while preserving useful counts, policies,
  safe relative labels, and fingerprints.
- Context-derived trace query text for `memory_context_pack`,
  `memory_live_retrieval`, and `codex_transcript_context` is omitted in public
  trace results because it can contain user prompt text.
- Provider-backed retrieval trace analysis now reuses the same safe trace
  boundary before building model-facing summaries, so raw prompts, local paths,
  process output, and credential-like values are not handed to the analysis
  client.

## [2026-06-11] improve | provider smoke diagnostic

- Added a safe `chimera-memory enhance provider-smoke` receipt for repeatable
  provider/model/OAuth readiness checks without relying on hand-built scripts.
- Plan mode verifies selected provider/model and invocation shape without a
  model call; `--live --http-sidecar` exercises an ephemeral local HTTP sidecar
  plus the resolving provider client.
- Receipts are global/no-persona, non-mutating, and omit credential refs, token
  values, raw smoke content, generated summary text, provider stderr, and raw
  provider responses.

## [2026-06-11] improve | codex doctor provider smoke

- `chimera-memory codex doctor` now includes the same safe plan-mode provider
  smoke, so the main Codex diagnostic reports selected provider/model,
  credential-ref presence, and user-OAuth use without requiring a separate
  command or live model call.
- The doctor receipt stores the safe smoke result under `provider_smoke` and
  emits a `cm_provider_smoke` check; live proof remains explicit through
  `chimera-memory enhance provider-smoke --live --http-sidecar --json`.

## [2026-06-11] fix | sidecar provider profile diagnostics

- Health snapshots now record a safe `provider_profile` with selected
  provider/model plus credential-ref and user-OAuth booleans, without storing
  credential refs, tokens, smoke bodies, or generated provider text.
- Provider drift diagnostics now derive the selected provider from that safe
  receipt instead of a stale nonexistent plan field.
- `codex doctor` now prefers sidecar health provider evidence and falls back to
  local/config plan-mode smoke only when no sidecar profile is recorded, so a
  working OpenAI Spark OAuth sidecar is not misreported as a generic missing
  OpenAI credential path.

## [2026-06-11] improve | no-human global auto-promotion

- Added `chimera-memory global promote` as the no-human global memory promotion
  path. It previews by default and writes only with explicit automation
  enablement.
- Automated promotion records `auto_confirmed` provenance, reindexes the global
  file, writes review/audit receipts, and keeps public receipts body-safe and
  path-safe.
- The strict `trusted_clean` policy skips generated, restricted, excluded,
  malformed, wrong-scope, duplicate-body, missing-governance, and guard-blocked
  files instead of promoting them to instruction-grade authority.

## [2026-06-11] fix | hyphenated global retrieval quality

- Split hyphenated and underscored relevance tokens into component terms inside
  `memory_relevance.py`, preserving strict quality gates while allowing queries
  such as `forward momentum` to match global files named or written as
  `forward-momentum`.
- Added context-pack regression coverage and verified the live global corpus
  returns both default-available instruction-grade cards through context, FTS
  search, structured query, and semantic recall.

## [2026-06-12] docs | post-goal drift cleanup

- Clarified that Discord-named transcript tools are legacy compatibility
  helpers and that current Codex Desktop/CLI work should use scoped
  curated-memory tools plus transcript search where exposed.
- Updated credential governance so configured OAuth/credential refs can run
  unattended with audit provenance instead of implying runtime confirmation is
  required.
- Updated enhancement, migration, README roadmap, repo-map, package metadata,
  and wiki drift notes to reflect trusted automated promotion, Spark/OAuth
  sidecar operation, existing GitHub Actions, existing scripts, streamable HTTP,
  and current Codex/Hermes support.

## 2026-06-14

- Added harness auto-identification (`chimera_memory/harness.py` + wiring in server/indexer/lease) so Codex/Hermes are no longer silently parsed as Claude; per-file JSONL content sniffing prevents silent zero-entry imports. Tests: `tests/test_harness.py`.
- Fixed the persona transcript-DB split-brain: unified `server._resolve_transcript_db_path()` across `_get_db`, the maintenance lock, and the 5 startup workers. Tests: `tests/test_db_resolution.py`.
- Landed the audit High-severity set (frontmatter coercion, OpenAI key regex, live-retrieval superseded filter, recall similarity guard, ChatGPT importer crash guards, CLI top-level handler, MCP error/path-leak sanitizers, trace-analysis egress redaction, entity-link preservation, scope-aware idempotency key, OAuth lock-across-network, FTS staleness recovery, Codex TOML installer data loss).
- Updated `.wiki` drift page and README harness rows to match the new detection behavior.
