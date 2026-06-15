# ChimeraMemory Module Layout

Status: current after the Day 58 memory-module split.

This document explains where future work belongs. The goal is to keep `memory.py` small enough to reason about while preserving its public facade for existing callers.

## Public Facade

`chimera_memory/memory.py` remains the compatibility surface. Existing imports such as `from chimera_memory.memory import memory_review_action` should keep working.

Keep `memory.py` focused on:

- file discovery and persona scoping
- indexing curated markdown memories
- search and recall orchestration
- stats, gaps, consolidation, and watcher integration
- re-exporting focused helpers where older callers already import from `memory.py`

Do not add new sidecar, review, audit, or schema logic directly to `memory.py`.

## Focused Modules

### `memory_schema.py`

Owns SQLite DDL, additive migrations, prerequisite checks, and `init_memory_tables`.

Rules:

- Keep migrations additive and idempotent.
- Do not import focused memory behavior modules from schema code.
- Schema changes need focused tests plus full pytest.

### `memory_governance.py`

Owns memory trust metadata:

- provenance statuses
- lifecycle statuses
- review statuses
- sensitivity tiers
- instruction-grade provenance rules
- frontmatter-to-governance parsing

Rules:

- Generated/agent-written metadata starts as evidence, not instruction.
- Instruction-grade use requires user-confirmed provenance. Imported memory
  remains evidence-only/review-gated until a review path promotes it.
- Keep these helpers pure where possible.

### `memory_scope.py`

Owns global/project/persona scope normalization, project-root resolution, and
SQL scope filters for retrieval surfaces.

Rules:

- Treat persona scope as a privacy boundary.
- Prefer explicit `CHIMERA_MEMORY_PROJECT_ID` over a folder-derived id when a
  single project root is configured.
- `scope=auto` is persona plus current project plus global when a persona is
  known, and current project plus global for no-persona Codex project mode.
- The Codex MCP surface must fail closed rather than falling back to all-memory
  reads when no persona and no project id are resolved; `scope=global` is the
  explicit global-only escape hatch.
- Full-reindex cleanup must prune only rows under roots managed by the current
  discovery run; no-persona Codex/global runs must preserve skipped persona-root
  rows.
- Full-reindex and watcher discovery must skip hidden/cache/auth-style child
  paths under managed roots while still allowing a configured hidden root such
  as `.chimera-memory` itself.
- Operator-wide all-memory reads must be explicit.

### `harness.py`

Owns active-harness identification for transcript indexing (Claude Code, Codex,
Hermes):

- `detect_harness()` -> `HarnessProfile` (name, parser client, jsonl_dir,
  recursive, source, confidence)
- precedence: explicit `CHIMERA_CLIENT`/`TRANSCRIPT_JSONL_DIR` -> process-injected
  running-harness env signals -> on-disk session-dir signature -> per-file content
  sniff -> Claude-Code default
- `sniff_jsonl_format()` content disambiguation (Codex `session_meta`/`payload`
  vs Claude `sessionId`/chat types)
- per-harness default session dirs (Claude projects, `~/.codex/sessions`,
  persona-scoped `~/.hermes/profiles/<persona>/sessions`)

Rules:

- Near-stdlib: import only the standard library; no behavior-module imports.
- Never raise; never emit raw filesystem paths into user/MCP-facing strings.
- Use process-injected "currently running" signals (`CLAUDECODE`/`CODEX_SANDBOX`),
  never install-location vars (`HERMES_HOME`/`CODEX_HOME`) that persist in every
  shell and would mislabel.
- Explicit env always wins; detection only fills unset fields; the default branch
  is byte-for-byte the historical Claude behavior.

### `memory_global_seed.py`

Owns dry-run-first global corpus seeding:

- read-only global-root and DB corpus inspection
- corpus counts for default-available evidence and confirmed instruction-grade
  files
- filesystem-frontmatter authority counts for trusted instruction-grade,
  pending-review, evidence-only, and confirmation-gated files
- read-only guard scans for global-root markdown inspection
- global-root-only DB reindex and optional missing-row pruning
- selected-file authority summaries for reindex dry-runs/writes
- explicit source directory validation
- env/user-supplied/fallback global root targeting for operator CLI flows
- markdown-only copy planning
- include/exclude relative glob filtering for mixed shared/global sources
- hidden/cache/auth-style directory skips
- conflict-safe writes
- memory-guard preflight for selected write-mode files
- immediate indexing as `memory_scope=global`
- safe global-governance frontmatter stamping before write-mode indexing
- compact path-safe audit events for write-mode seed/reindex operations

Rules:

- Never read or write persona-private roots implicitly.
- Keep the source directory explicitly user-supplied.
- Keep inspect read-only; do not create directories or initialize DB tables.
- Inspect guard receipts may include finding type/count and relative path only,
  not unsafe samples or patterns.
- Use include/exclude filters when a reviewed source tree contains roster,
  relationship, image-feedback, or other persona-specific shared files. Broad
  include globs do not count as explicit review of those mixed paths.
- Write-mode seed must fail closed on selected mixed shared/persona-style paths
  unless targeted include filters name those mixed paths or
  `--allow-mixed-source` documents an intentional reviewed compatibility import.
- For operator CLI flows, use `CHIMERA_MEMORY_GLOBAL_ROOT` when present and
  otherwise fall back to `~/.chimera-memory/global-memory`, not the legacy
  Claude global root.
- Default to dry-run; require `--write` for filesystem changes.
- Write-mode seed must fail closed before copying or indexing when any selected
  file has an unresolved target conflict; use `--overwrite` for intentional
  replacement.
- Before write-mode seed/reindex copies or indexes global files, run
  `scan_for_injection` and fail closed on any credential, injection, or
  hidden-content finding. Receipts may include finding type/count and relative
  path only, not samples or patterns. `--no-guard` is compatibility-only.
- Before write-mode seed/reindex indexing, stamp missing or ambiguous global
  governance as imported, evidence-only, pending review, and
  `memory_scope=global` unless the file already carries explicit confirmed
  instruction-grade provenance. `--no-stamp-governance` is compatibility-only.
- Dry-run inspect/reindex authority summaries must treat missing or
  unrecognized frontmatter as imported, pending, evidence-enabled,
  instruction-disabled, and requiring confirmation.
- Write-mode seed/reindex receipts must be non-OK when seed conflicts remain,
  governance stamping or indexing reports per-file errors, or files are skipped
  from indexing; partial filesystem writes are not success.
- Inspect, seed, reindex, and review receipts must represent root and DB
  locations with path-safe payloads (`name`, provenance, fingerprint), not raw
  absolute paths.
- Inspect, outside-root row, prune-candidate, query-smoke card, and query-smoke
  candidate-profile receipts must not echo path-shaped stored DB
  `relative_path` values; collapse unsafe values to filename-only labels.
- Query-smoke query-match profiles may expose useful matched term labels, but
  those labels must be secret-sanitized and local-path-redacted before receipt
  or CLI display.
- Files with governance stamping errors must not be indexed in the same run.
- Reindex must stay scoped to one global root and must not invoke broad
  persona/project `full_reindex` cleanup.
- Prune stale DB rows only when explicitly requested.
- For stale rows under the selected global root, derive prune filter matching
  and receipts from the resolved path's root-relative location, not the stored
  DB `relative_path`.
- Prune must remove file-owned side-table rows for the deleted file id and set
  nullable historical references to `NULL`, so cleanup does not depend on
  SQLite foreign-key pragmas being enabled.
- Audit counts, filters, provenance, fingerprints, and relative paths; do not
  audit memory bodies or raw absolute roots.
- Refuse nested source/target roots to avoid recursive or self-seeding copies.

### `memory_global_review.py`

Owns durable review for global-root markdown files:

- pending global review listing from the configured global root
- governance-repair listing for missing policy keys, parse errors, wrong scope,
  and unsafe instruction-grade state
- sanitized review-reason summaries and filters for operator triage
- path-safe first matching review target metadata and action guidance for
  low-volume diagnostics
- virtual `confirm_guard_blocked` reason filtering for sanitized confirm-preview
  blockers
- human-readable root-relative review target listings with per-file reasons
- body-safe single-target inspection by relative path without review action
- sanitized confirm-action guard previews in review listings, including
  preserved-body previews for malformed-frontmatter sources
- root-relative frontmatter review previews
- display-safe `preview_frontmatter` values for public preview receipts
- body-preserving write-mode frontmatter review actions
- no-human automated global promotion through named trust policies
- memory-guard enforcement before review outcomes that remain default-retrievable
- human-readable action receipts with sanitized review-guard counts
- immediate reindexing as `memory_scope=global` after write-mode review
- review action rows and path-safe audit events for global review actions
- auto-promotion action rows and path-safe audit events for trusted automation

Rules:

- Never read or write persona-private roots.
- Default to preview/list. Manual review actions require `--write` and an
  explicit reviewer before mutating markdown or DB state; automated promotion
  requires `--write` plus explicit automation enablement before mutating state.
- Resolve review targets relative to one global root and refuse absolute paths,
  leading separators, drive or stream separators, control characters, `..`,
  non-markdown targets, and missing files.
- Apply the same case-insensitive hidden/cache/auth-style skipped-corpus
  boundary to explicit review targets that discovery and seeding use for
  implicit scans.
- Review listings may expose sanitized review reasons and governance flags, but
  never memory bodies.
- Low-volume listings may expose a first matching relative path plus a
  body-safe first target summary so diagnostics can recommend concrete
  inspect/confirm/evidence-only/remediation commands without returning file rows
  or memory bodies.
- Target inspection may expose body hashes, body length, frontmatter keys,
  guard counts, and recommendations, but never memory bodies.
- Preview receipts may expose reviewed frontmatter shape, but string values
  must be sanitizer/path-display safe. Do not mutate the canonical write
  frontmatter just to make the preview safe.
- Confirm-action guard previews in review listings may expose finding type/count
  and relative path only, not samples or patterns.
- Review reason filters must use the closed sanitized reason enum and preserve
  all-pending summary counts separately from matching/returned counts.
- Filtered review listings must keep guard/reason counts scoped correctly:
  `summary` for all pending, `matching_summary` for filtered matches, and
  `returned_summary` for the current page.
- Preserve the markdown body byte-for-byte after frontmatter rendering.
- For malformed source frontmatter, treat the source as pending/untrusted and
  preserve the original text as body under repaired review frontmatter.
- For missing or unrecognized source frontmatter, list the source as
  pending/untrusted evidence instead of default instruction authority.
- `confirm` is the manual review action that promotes global memory to
  instruction-grade use. `global promote` is the no-human path and records
  `auto_confirmed` provenance only after named policy gates pass. Other actions
  keep `can_use_as_instruction: false`.
- Settled non-confirm actions such as `evidence_only`, `restrict_scope`,
  `mark_stale`, `merge`, `reject`, and `supersede` are durable
  `user_confirmed` review decisions but remain non-instructional.
- Default-retrieval guard checks must use `exclude_from_default_search`, the
  same key used by indexing and retrieval, not a parallel exclusion key.
- Automated promotion must not rely on default-retrieval guard bypass for
  `exclude_from_default_search`; excluded files are skipped instead of promoted
  to instruction-grade authority.
- Human-readable action output may report guard required/blocked/finding counts,
  but must not print guard samples, patterns, or memory bodies.
- Body-safe recommendation commands must quote unusual relative paths with
  PowerShell-safe single-quote escaping; simple alphanumeric paths may keep the
  existing double-quoted form for readability.
- Review action receipts must use the root-relative target and hashes instead
  of returning the absolute target file path.
- After write-mode review, reindex the same file as persona `global` so the DB
  and markdown agree immediately instead of waiting for a watcher pass.
- If the post-write index/review-audit step fails, attempt to restore the
  original markdown and report the restore outcome.

### `transcript_context.py`

Owns bounded transcript snippets for Codex project prompt fallback.

Rules:

- Treat transcript snippets as evidence, not instructions.
- Only return snippets when a project workspace root is resolved.
- Filter candidates to sessions whose `cwd` is inside the project workspace.
- Do not include raw workspace paths in prompt-facing snippet blocks.
- Record sanitized `codex_transcript_context` recall traces and
  `codex_transcript_context_*` audit events when transcript fallback runs.
- Keep transcript fallback opt-in from `codex_context.py`; curated memory remains
  the default prompt evidence source.

### `memory_observability.py`

Owns recall and audit visibility:

- `memory_recall_traces`
- `memory_recall_items`
- `memory_audit_events`
- trace query helpers
- audit query helpers
- JSON payload serialization helpers
- sanitized non-file recall items, such as transcript fallback evidence

Rules:

- This module must not import review or enhancement queue modules.
- Audit payloads should be structured and safe. Do not write raw secrets.
- Public trace query helpers must return display-safe item path labels plus
  fingerprints, never raw local filesystem paths, even if trace storage
  preserves raw indexed paths for repair/debug internals.
- Public trace query helpers must also sanitize request/response payloads and
  item metadata on read. Context-delivery traces such as `memory_context_pack`,
  `memory_live_retrieval`, and `codex_transcript_context` must omit raw query
  text because it can be derived from a user prompt.
- Public audit query helpers must sanitize path-like target ids and payload
  fields on read; audit storage may preserve raw local paths for internal
  repair/debug use, but caller-visible event payloads must use safe labels or
  fingerprints while preserving non-local URIs and opaque ids.
- Public audit query helpers must return redaction receipts for sensitive
  prompt, body, command, process output, and credential-like payload fields;
  ordinary status and typed error fields should remain readable.
- Recall trace `result_count` is the candidate/result set size before the
  caller's requested limit or token budget is applied; `returned_count` is the
  number of trace items actually returned. Exact `memory_search` and structured
  `memory_query` traces store only `source_uri_supplied`, not the raw URI value.

### `memory_health.py`

Owns CM background-system health snapshots:

- transcript embedding backlog and staleness checks
- enhancement queue age checks
- provider drift checks
- path-safe Codex runtime profile with global availability and
  instruction-grade counts
- session rollup and duplicate-capture checks
- last-success timestamps
- `cm_health_snapshot` audit payloads

Rules:

- Health checks may read transcript and memory sidecar tables.
- Health checks may call observability audit helpers.
- Health checks must not import `memory.py` at module import time.
- Keep checks local and cheap enough for `serve` to run every few minutes.

### `diagnostic_time.py`

Owns user-facing diagnostic timestamp formatting:

- preserves stored UTC timestamps
- appends local-time companions for context and Codex diagnostics
- avoids making trace readers infer local dates across UTC day boundaries

### `memory_provider_governor.py`

Owns shared provider traffic accounting for enhancement transports:

- provider usage ledger writes
- rolling minute/day/month usage counts
- budget-cap allow/deny checks
- shared enforcement surface for HTTP providers and future CLI workers

Rules:

- Store provider/model/transport metadata only. Do not store prompts,
  responses, credential refs, tokens, or raw errors.
- Check budget before claiming queue jobs so denied work stays pending.
- Local deterministic/dry-run work must not consume provider budget.

### `memory_cli_worker_supervisor.py`

Owns headless CLI worker launch scaffolding:

- worker-local `AGENTS.md`
- worker-local `CLAUDE.md`
- worker-local Codex MCP config with `worker` tool surface
- worker-local Claude MCP config with `worker` tool surface
- bounded Codex `exec` command construction
- bounded Claude `--print` command construction
- process launch, restart loop, and log file paths

Rules:

- Supervisor code may spawn CLI processes only when explicitly enabled by env.
- Generated worker MCP config must disable nested CM enhancement, embedding,
  and health workers to avoid recursive process trees.
- Do not copy or print provider credentials. Auth reuse is a user/operator
  setup concern, not supervisor code.
- Worker output must come back through `memory_worker_submit_result`, not
  free-form stdout scraping.

### `memory_live_retrieval.py`

Owns live-retrieval planning lifted from OB1's live retrieval recipe:

- topic-shift cue extraction
- scoped dry-run proactive recall suggestions
- shared relevance quality gating for weak broad matches
- silent miss behavior
- recall trace and audit logging for tuning

Rules:

- Live retrieval must not inject results into prompts by itself.
- Use the shared persona/project/global scope policy before returning
  suggestions.
- Use `memory_relevance.py` for deterministic candidate quality gates.
- Misses should be logged but quiet to the caller unless explicitly queried.
- Exclude restricted memories by default.
- Keep this local and deterministic unless a future classifier adapter is explicitly added.

### `memory_relevance.py`

Owns deterministic candidate-quality helpers shared by live retrieval and
context packs:

- broad query term classification
- candidate/query coverage profiles
- weak-match filtering policy metadata for traces and audits

Rules:

- Keep this local and model-free.
- Preserve traceable policy fields when filtering candidates.
- Do not import behavior modules from here.

### `memory_context_pack.py`

Owns the Hermes-style turn broker primitive:

- topic-shift planning using live-retrieval cues
- hybrid memory-file candidate retrieval
- scope, sensitivity, lifecycle, synthesis, and failure filtering
- shared relevance quality gating for weak broad matches
- duplicate collapse by content fingerprint and global relative path
- token-capped memory-card formatting
- `<chimera-memory-context>` fencing and capture stripping
- recall trace and audit logging for every returned, skipped, or missed pack

Rules:

- This module builds context packs but does not inject them into a harness.
- Treat returned memories as evidence, not instructions.
- Label card authority with review/use-state metadata such as `review=pending`,
  `evidence-only`, `needs-confirmation`, `lifecycle=stale`, and
  `lifecycle=archived`.
- Format prompt-card source labels with root-relative paths or synthetic scoped
  IDs only; never fall back to raw filesystem paths.
- Sanitize prompt-card prose (`about`, snippets, truncated card text) for
  credential-like content and local path references at display time while
  preserving raw DB text for matching and ranking.
- Exclude restricted and generated/synthesis memory by default.
- Use `memory_relevance.py` for deterministic candidate quality gates.
- Deduplicate after quality filtering and before card construction; preserve
  trace policy counts so legacy shared/global overlap stays diagnosable.
- Keep the output bounded enough for per-turn use.

### `codex_setup.py`

Owns Codex MCP config rendering, install receipts, and setup diagnostics.

Rules:

- Keep doctor output path-safe and prompt-safe.
- Distinguish MCP sidecar reachability, context construction, dry-runs, and
  actual `codex exec` prompt evidence delivery.
- For local HTTP sidecars, report listener owner/runtime mismatches with
  sanitized PID/process-name details, never raw process commands.
- For no-persona project/global memory, report global review queue counts and
  confirm-guard blocked/finding counts without file bodies or raw paths.
- Prefer sidecar health `provider_profile` evidence for enhancement provider
  smoke in doctor output; fall back to local/config plan-mode smoke without
  making a model call or exposing credential refs, tokens, smoke bodies,
  provider stderr, or generated summary text.
- Report optional wrapper command availability separately from sidecar health;
  a missing `chimera-memory` shell shim must not make a healthy HTTP MCP server
  look broken.
- Power `chimera-memory codex traces` with sanitized context/delivery history
  that distinguishes prompt construction, diagnostic smoke, generic context
  traces, and real `codex exec` delivery, including date-bounded `--since`
  diagnostics.
- Codex/no-persona MCP context tools must tolerate JSON `null` for optional
  identity fields such as `persona`, `project_id`, `previous_context`, and
  `scope`; normalize those to empty/no-persona values before calling focused
  retrieval modules.
- Codex/no-persona MCP memory tools must reject explicit or env-derived persona
  identity for reads, stats, authored writes, context/live retrieval, and
  persona-scope attempts; persona-private memory belongs on non-Codex
  persona/admin surfaces.
- The Codex/no-persona MCP surface must not register the persona-facing
  `memory_review` queue or persona-source `memory_promote_snapshot`. Use global
  review CLI/diagnostic recommendations for global-root review work.
- Codex/no-persona `memory_diagnose` must expose only the safe project/global
  subset: tools, stats, context, provider plan, worker/health, guard, and
  whereami. Persona/admin modes such as zones, traces, audit, harness, gaps, and
  consolidation must require a non-Codex surface.

### `codex_context.py`

Owns Codex Desktop/CLI prompt-context wrapping for no-persona project mode:

- calls `memory_context_pack.py` instead of duplicating retrieval/ranking
- prepends a bounded `[Automatic ChimeraMemory pre-turn evidence]` block only
  when scoped project/global evidence is returned
- strips an existing CM context prefix before rewrapping so repeated wrappers are
  idempotent
- normalizes leading real or mojibake UTF-8 BOM prefixes from Windows stdin
- supports stdin and UTF-8/UTF-8-BOM file inputs for hook-friendly prompt and
  previous-context reads
- fails closed for `auto` and `project` scopes without a resolved project id
- CLI wrappers infer no-persona project id/root from `--project-root`, `--cd`,
  or the current repo directory when safe
- `--receipt-only` emits prompt/body-free verification receipts for context and
  exec dry-runs
- powers `chimera-memory codex exec`, which runs `codex exec -` with the wrapped
  prompt on stdin for Codex CLI project work
- records safe `delivery_mode` trace metadata, and records
  `codex_prompt_delivered` only after a non-dry-run Codex subprocess returns
- summarizes child stdout/stderr in JSON receipts by default; raw output is
  explicit opt-in via `--include-output`
- can opt into `transcript_context.py` snippets with `--include-transcripts`

Rules:

- Do not add persona arguments here unless an explicit future persona mode is
  designed.
- Do not leak raw DB paths, provider stderr, auth paths, child stderr/stdout,
  or card dictionaries in wrapper receipts unless a command explicitly opts into
  raw output.
- The grounding rule must not treat pending, evidence-only, stale, or archived
  global records as current settled instructions; they are leads until
  confirmed, current, or verified.
- Do not include transcript snippets unless `transcript_context.py` proves the
  transcript session belongs to the current project workspace.
- Keep mechanical injection outside MCP setup; this helper is for hooks,
  wrappers, and harnesses.

### `hermes_setup.py`

Owns standalone Hermes Agent setup helpers (parity with `codex_setup.py`, but
narrower and safer):

- `render_hermes_template()` (output-only indexer env/command + paste-in Hermes
  `mcp_servers` block)
- `inspect_hermes_setup()` read-only doctor (Hermes home, persona session store,
  parse smoke, harness resolution)
- `install_hermes_indexer()` writes per-persona launcher scripts under
  `~/.chimera-memory/hermes/`; dry-run by default
- `build_hermes_indexer_env()` / `hermes_sessions_dir()` persona-scoped resolution

Rules:

- Never mutate Hermes's comment-rich `config.yaml` (same clobbering risk class as
  the Codex TOML installer); print the paste-in block instead.
- Persona is required and sanitized against traversal; never scan across personas.
- `doctor` is read-only and path-safe; `install` defaults to dry-run.

### `memory_retrieval_trace_analysis.py`

Owns post-hoc retrieval diagnostics:

- recall trace summarization
- bounded diagnostic categories
- strict JSON invocation envelope for an injected analysis client
- audit logging for analysis runs

Rules:

- Never send raw memory bodies to the analysis client.
- Never send raw context-delivery prompt/query text, raw local paths, process
  output, or credential-like trace payload fields to the analysis client; reuse
  observability read-side sanitizers before building provider-bound summaries.
- Do not mutate recall ranking or inject memories into prompts.
- Treat analysis output as recommendations only.
- Deterministic CM fixes should be implemented separately after validation.

### `memory_review.py`

Owns manual review workflows:

- pending review query
- review action application
- before/after metadata snapshots
- review audit events

Rules:

- Review actions may call observability audit helpers.
- Review actions should not mutate raw markdown files.
- Keep review state transitions explicit.

### `memory_auto_capture.py`

Owns the session-close auto-capture protocol lifted from OB1's auto-capture skill:

- deterministic ACT NOW extraction
- governed markdown rendering
- persona-root resolution
- safe file writing under `memory/episodes/`
- safety scan summaries without raw secret payloads

Rules:

- Auto-captured memories are generated, pending review, evidence-only, and require user confirmation.
- Auto-capture helpers may use sanitizer helpers, but must not import `memory.py`.
- The facade is responsible for indexing written files and writing audit events.

### `memory_entities.py`

Owns the local entity graph lifted from OB1:

- `memory_entities`
- `memory_file_entities`
- `memory_entity_edges`
- entity normalization and deduplication
- frontmatter-derived entity indexing
- enhancement-derived entity linking
- shared-file connection queries
- explicit entity-edge queries
- typed entity-edge upserts

Rules:

- Entity indexing is additive. Do not replace `memory_gaps`.
- Entity helpers may call observability audit helpers.
- Entity helpers must not import `memory.py`.
- LLM extraction can populate these tables later, but this module must keep a local frontmatter-only path.

### `memory_file_edges.py`

Owns typed reasoning relations between memory files lifted from OB1's `thought_edges` pattern:

- `memory_file_edges`
- relation types such as `supports`, `contradicts`, `evolved_into`, `supersedes`, and `depends_on`
- confidence and support-count accumulation
- current-only query filtering via `valid_until`
- temporal sweep helpers for expiring stale current edges
- typed edge upsert and query helpers

Rules:

- Memory-file edges are additive. Do not replace `memory_gaps` or the entity graph.
- Edge helpers may call observability audit helpers.
- Edge helpers must not import `memory.py`.
- Keep relation types explicit. Do not accept arbitrary free-form relation labels through public tools.

### `memory_pyramid.py`

Owns deterministic multi-resolution summaries for long curated or imported memory files:

- `memory_pyramid_summaries`
- chunk, section, and document summary levels
- idempotent rebuilds keyed by memory-file content hash
- query helpers for current summaries
- audit events for summary builds

Rules:

- Pyramid summaries are additive sidecar rows. Do not modify the source markdown file.
- Summary helpers may call observability audit helpers.
- Summary helpers must not import `memory.py`.
- Keep the default path deterministic and local. LLM summaries can be a later provider-backed enhancement, not the baseline.

### `memory_import_chatgpt.py`

Owns ChatGPT export ingestion scaffolding:

- `conversations.json` loading from a file, directory, or zip export
- conversation flattening
- governed markdown planning
- safe file writing under `memory/imports/chatgpt/`

Rules:

- Imported conversations are imported provenance but pending review and evidence-only by default.
- Import helpers must not import `memory.py`.
- The facade owns indexing written files, building pyramid summaries, and audit completion events.
- Keep parser behavior tolerant. ChatGPT export shape changes over time.

### `memory_import_obsidian.py`

Owns Obsidian vault ingestion scaffolding:

- markdown note loading from a vault directory or zip export
- frontmatter/body parsing for source notes
- governed markdown planning
- safe file writing under `memory/imports/obsidian/`

Rules:

- Imported Obsidian notes are imported provenance but pending review and evidence-only by default.
- Import helpers must not import `memory.py`.
- The facade owns indexing written files, building pyramid summaries, and audit completion events.
- Skip Obsidian internals such as `.obsidian/`.

### `memory_import_gmail.py`

Owns Gmail / Google Takeout mbox ingestion scaffolding:

- mbox loading from a file, directory, or zip export
- email header and body extraction
- governed markdown planning
- safe file writing under `memory/imports/gmail/`

Rules:

- Imported Gmail messages are imported provenance, pending review, restricted, and evidence-only by default.
- Import helpers must not import `memory.py`.
- The facade owns indexing written files, building pyramid summaries, and audit completion events.
- Skip attachments. The baseline importer stores text bodies only.

### `memory_import_perplexity.py`

Owns Perplexity export ingestion scaffolding:

- markdown, text, and tolerant JSON loading from a file, directory, or zip export
- conversation/message JSON flattening
- governed markdown planning
- safe file writing under `memory/imports/perplexity/`

Rules:

- Imported Perplexity documents are imported provenance but pending review and evidence-only by default.
- Import helpers must not import `memory.py`.
- The facade owns indexing written files, building pyramid summaries, and audit completion events.
- Keep parser behavior tolerant. Perplexity export shapes are less stable than Gmail mbox or ChatGPT conversations.json.

### `memory_import_grok.py`

Owns Grok export ingestion scaffolding:

- markdown/text/JSON/JSONL parsing
- conversation/message JSON flattening
- governed markdown planning
- safe file writing under `memory/imports/grok/`

Rules:

- Imported Grok documents are imported provenance but pending review and evidence-only by default.
- Import helpers must not import `memory.py`.
- The facade owns indexing written files, building pyramid summaries, and audit completion events.
- Keep parser behavior tolerant. Grok export shapes are less stable than Gmail mbox or ChatGPT conversations.json.

### `memory_import_twitter.py`

Owns X/Twitter tweet archive ingestion scaffolding:

- `data/tweets.js` / tweet JSON / JSONL parsing
- tweet metadata extraction
- governed markdown planning
- safe file writing under `memory/imports/twitter/`

Rules:

- Imported tweet/status documents are imported provenance but pending review and evidence-only by default.
- Import helpers must not import `memory.py`.
- The facade owns indexing written files, building pyramid summaries, and audit completion events.
- Direct messages are intentionally out of scope for this module. DM imports need a separate restricted importer.

### `memory_import_instagram.py`

Owns Instagram export ingestion scaffolding:

- message thread JSON flattening
- content/post JSON flattening
- governed markdown planning
- safe file writing under `memory/imports/instagram/`

Rules:

- Imported Instagram documents are imported provenance, pending review, restricted, and evidence-only by default.
- Import helpers must not import `memory.py`.
- The facade owns indexing written files, building pyramid summaries, and audit completion events.
- Keep the parser tolerant. Instagram Takeout structure changes between export versions.

### `memory_import_google_activity.py`

Owns Google Activity / Takeout ingestion scaffolding:

- MyActivity JSON parsing
- HTML/text fallback parsing
- governed markdown planning
- safe file writing under `memory/imports/google-activity/`

Rules:

- Imported Google Activity documents are imported provenance, pending review, restricted, and evidence-only by default.
- Import helpers must not import `memory.py`.
- The facade owns indexing written files, building pyramid summaries, and audit completion events.
- Keep the parser tolerant. Google Takeout product folders vary heavily by export source.

### `memory_import_atom_blogger.py`

Owns Atom / Blogger XML ingestion scaffolding:

- Atom entry parsing
- title/content/author/category/link extraction
- governed markdown planning
- safe file writing under `memory/imports/atom-blogger/`

Rules:

- Imported Atom/Blogger documents are imported provenance but pending review and evidence-only by default.
- Import helpers must not import `memory.py`.
- The facade owns indexing written files, building pyramid summaries, and audit completion events.
- Keep parsing stdlib-only. XML import should not add a dependency.

### `memory_profile_export.py`

Owns deterministic portable context exports from reviewed memory:

- USER.md / SOUL.md / HEARTBEAT.md rendering
- structured `memory-profile.json` output
- review/use-policy filtering
- audit events for preview and write runs

Rules:

- Profile export is generated output. Do not modify source markdown files.
- Export helpers may read source markdown bodies for sanitized excerpts.
- Export helpers may call observability audit helpers.
- Export helpers must not import `memory.py`.
- Pending, rejected, disputed, and restricted memories stay out by default.

### `memory_enhancement.py`

Owns the model-free sidecar contract:

- request shape
- response normalization
- untrusted content wrapping
- schema version constants

Rules:

- No OAuth or model calls here.
- Treat captured content as untrusted input.
- Validate sidecar output before queue completion or writeback.

### `memory_enhancement_provider.py`

Owns provider policy for future memory-enhancement sidecar calls:

- provider priority order
- credential-reference validation
- model defaults
- optional models.dev-backed recommended OpenAI, Anthropic, Gemini/Google,
  OpenRouter, and LM Studio defaults
- budget caps
- safe invocation envelope
- bounded failure categories
- safe provider receipts

Rules:

- No provider model calls here.
- Catalog lookups must go through `memory_model_catalog.py` and stay env-gated.
- Store Gemini internally as provider id `google`, matching models.dev.
- Store Local AI submenu choices internally as `ollama`, `lmstudio`, or
  `openai_compatible`.
- No raw OAuth token or bearer token values here.
- Credential references are names such as `oauth:openai-memory`, not credentials.
- This module may import the sidecar contract, but not queue/review/schema/facade modules.

### `memory_enhancement_provider_smoke.py`

Owns safe provider readiness smoke receipts:

- plan-only provider/model/OAuth/ref invocation shape checks
- explicit live direct provider smoke calls
- explicit live ephemeral HTTP sidecar smoke calls
- metadata-shape summaries for operator receipts

Rules:

- Live model calls must be opt-in.
- Receipts must not include credential refs, token values, raw smoke content,
  provider stderr, raw provider responses, or generated summary text.
- Keep the smoke request global/no-persona and non-mutating.
- Use `tests/test_memory_enhancement_provider_smoke.py` plus CLI coverage when
  changing this surface.

### `memory_model_catalog.py`

Owns the narrow models.dev catalog integration used by the memory-enhancement picker:

- bundled models.dev snapshot fallback
- disk cache with short refresh interval and offline fallback
- provider/model dataclasses
- recommended model filtering for cheap text structured extraction

Rules:

- No credential reads.
- No provider calls other than the public catalog fetch.
- The catalog feeds cloud and bundled recommendation lists only. Local AI model
  discovery belongs to PA or a later endpoint-probing module that queries the
  user's running endpoint.

### `memory_enhancement_runner.py`

Owns the provider-aware batch runner boundary:

- claims pending jobs
- builds provider invocation envelopes
- calls an injected `MemoryEnhancementClient`
- completes jobs with normalized metadata
- records failures as bounded categories only

Rules:

- No provider-specific SDK code here.
- No raw OAuth token resolution here.
- Host applications can inject a client that knows how to resolve scoped credentials.
- Failure storage must use categories, not raw provider stderr or exception text.

### `memory_enhancement_queue.py`

Owns enhancement job persistence:

- enqueue
- claim next
- complete/fail/skip
- job serialization

Rules:

- Queue helpers may depend on `memory_frontmatter.py`, `memory_observability.py`, `memory_entities.py`, and `memory_enhancement.py`.
- Queue helpers must not import `memory.py`.
- Completing a job does not directly promote generated metadata to instruction-grade.
- Internal job rows may preserve raw paths and request payloads for workers and
  repair/debug internals, but public enhancement receipts must collapse local
  paths to labels/fingerprints and redact wrapped content, authored payload
  bodies, and non-governance result metadata.

### `memory_frontmatter.py`

Owns markdown frontmatter parsing shared by indexing and enhancement enqueue.

This tiny module exists to avoid circular imports between `memory.py` and `memory_enhancement_queue.py`.

### `enhancement_worker.py`

Owns deterministic local enhancement workers:

- legacy dry-run queue consumer
- fake CLI-worker harness that exercises worker claim/budget/submit protocol

Rules:

- These are not the real OAuth/model adapter or headless CLI launcher.
- Keep deterministic behavior for tests.
- Real sidecar/model work should land behind explicit provider boundaries.

## Import Direction

Allowed direction:

```text
memory.py facade
  imports focused modules

memory_live_retrieval.py
  imports memory_observability.py
  imports sanitizer.py

memory_health.py
  imports embeddings.py
  imports memory_observability.py

memory_global_seed.py
  imports memory.py inside global index helper only
  imports sanitizer.py

memory_global_review.py
  imports memory_global_seed.py
  imports memory_governance.py
  imports memory_observability.py
  imports memory_schema.py
  imports sanitizer.py

memory_cli_worker_supervisor.py
  imports no CM behavior modules
  writes worker-local instruction/config files

memory_enhancement_queue.py
  imports memory_frontmatter.py
  imports memory_observability.py
  imports memory_entities.py
  imports memory_enhancement.py

memory_enhancement_provider.py
  imports memory_enhancement.py

memory_enhancement_runner.py
  imports memory_enhancement_provider.py
  imports memory_enhancement_queue.py

memory_review.py
  imports memory_observability.py

memory_auto_capture.py
  imports sanitizer.py

memory_entities.py
  imports memory_observability.py

memory_file_edges.py
  imports memory_observability.py

memory_pyramid.py
  imports memory_frontmatter.py
  imports memory_observability.py
  imports sanitizer.py

memory_import_chatgpt.py
  imports memory_auto_capture.py
  imports memory_observability.py
  imports sanitizer.py

memory_import_obsidian.py
  imports memory_auto_capture.py
  imports memory_frontmatter.py
  imports memory_observability.py
  imports sanitizer.py

memory_import_gmail.py
  imports memory_auto_capture.py
  imports memory_observability.py
  imports sanitizer.py

memory_import_perplexity.py
  imports memory_auto_capture.py
  imports memory_frontmatter.py
  imports memory_observability.py
  imports sanitizer.py

memory_import_grok.py
  imports memory_auto_capture.py
  imports memory_frontmatter.py
  imports memory_observability.py
  imports sanitizer.py

memory_import_twitter.py
  imports memory_auto_capture.py
  imports memory_observability.py
  imports sanitizer.py

memory_import_instagram.py
  imports memory_auto_capture.py
  imports memory_observability.py
  imports sanitizer.py

memory_import_google_activity.py
  imports memory_auto_capture.py
  imports memory_observability.py
  imports sanitizer.py

memory_import_atom_blogger.py
  imports memory_auto_capture.py
  imports memory_observability.py
  imports sanitizer.py

memory_profile_export.py
  imports memory_frontmatter.py
  imports memory_observability.py
  imports sanitizer.py

memory_observability.py
  imports only stdlib

memory_governance.py
  imports only stdlib

memory_schema.py
  imports only stdlib
```

Avoid:

- focused modules importing `memory.py`
- schema importing queue/review/observability behavior
- review and queue importing each other
- model/OAuth code inside the queue module
- raw credential values in provider policy or safe receipts
- raw provider exception text in queue failure storage

## Test Map

- Schema: `tests/test_memory_schema_hygiene.py`
- Governance: `tests/test_memory_governance.py`
- Observability: `tests/test_memory_observability.py`
- Health snapshots: `tests/test_memory_health.py`
- Live retrieval: `tests/test_memory_live_retrieval.py`
- Retrieval trace analysis: `tests/test_memory_retrieval_trace_analysis.py`
- Review: `tests/test_memory_review.py`
- Auto-capture: `tests/test_memory_auto_capture.py`
- Entities: `tests/test_memory_entities.py`
- Memory-file edges: `tests/test_memory_file_edges.py`
- Pyramid summaries: `tests/test_memory_pyramid.py`
- ChatGPT import: `tests/test_memory_import_chatgpt.py`
- Obsidian import: `tests/test_memory_import_obsidian.py`
- Gmail import: `tests/test_memory_import_gmail.py`
- Perplexity import: `tests/test_memory_import_perplexity.py`
- Grok import: `tests/test_memory_import_grok.py`
- X/Twitter import: `tests/test_memory_import_twitter.py`
- Instagram import: `tests/test_memory_import_instagram.py`
- Google Activity import: `tests/test_memory_import_google_activity.py`
- Atom/Blogger import: `tests/test_memory_import_atom_blogger.py`
- Portable profile export: `tests/test_memory_profile_export.py`
- Transcript embeddings: `tests/test_embeddings.py`
- Sidecar contract: `tests/test_memory_enhancement.py`
- Provider policy: `tests/test_memory_enhancement_provider.py`
- Provider runner: `tests/test_memory_enhancement_runner.py`
- Enhancement queue: `tests/test_memory_enhancement_queue.py`
- Dry-run worker: `tests/test_memory_enhancement_worker.py`

When touching `memory.py`, also run the legacy standalone scripts:

```powershell
python tests/test_persona_scope.py
python tests/test_memory_watcher.py
python tests/test_indexer.py
python tests/test_search.py
python tests/test_parser.py
```
