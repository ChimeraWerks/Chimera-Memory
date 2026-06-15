---
id: chimera-memory-mcp-cli-and-service-surfaces
title: MCP, CLI, And Service Surfaces
scope: repo
kind: system
status: active
trust: high
created: 2026-06-09
updated: 2026-06-11
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - README.md
  - pyproject.toml
  - docs/agents/commands.md
  - docs/agents/token-efficient-usage.md
  - chimera_memory/cli.py
  - chimera_memory/diagnostic_time.py
  - chimera_memory/server.py
  - chimera_memory/memory_display.py
  - chimera_memory/memory_observability.py
  - chimera_memory/memory_health.py
  - chimera_memory/memory_active_harness.py
  - chimera_memory/memory_enhancement_provider_smoke.py
  - chimera_memory/mcp_surface.py
  - chimera_memory/memory_live_retrieval.py
  - chimera_memory/codex_setup.py
  - chimera_memory/codex_context.py
  - chimera_memory/memory_global_seed.py
  - chimera_memory/memory_global_review.py
  - scripts/start-cm-http.ps1
  - scripts/install-cm-http-autostart.ps1
  - tests/test_server_startup.py
  - tests/test_memory_observability.py
  - tests/test_memory_active_harness.py
  - tests/test_memory_global_seed.py
  - tests/test_memory_global_review.py
  - tests/test_codex_desktop_project_mode.py
  - tests/test_codex_setup.py
  - tests/test_memory_health.py
  - tests/test_memory_enhancement_provider_smoke.py
  - tests/test_codex_context.py
  - tests/test_memory_live_retrieval.py
  - tests/test_codex_desktop_project_mode.py
  - tests/test_whereami.py
---

# MCP, CLI, And Service Surfaces

## CLI

The main console command is `chimera-memory`.

Important command families:

- `serve`: run MCP stdio, SSE, or streamable HTTP transport.
- `backfill`: index transcript JSONL.
- `embed`: generate transcript embeddings.
- `stats`: show transcript database stats.
- `split-db`: split a shared DB into per-persona DBs.
- `codex doctor|template|install`: inspect and manage Codex MCP setup.
- `codex context`: prefix a Codex prompt with scoped project/global evidence
  when a hook, wrapper, or harness wants mechanical pre-turn context.
- `codex exec`: build the same scoped context, then launch `codex exec -` with
  the wrapped prompt on stdin for Codex CLI project work.
  `--include-transcripts` adds bounded snippets from prior sessions whose `cwd`
  is inside the current project workspace; `--project-root`, `--cd`, env, or a
  safe current repo directory supplies that workspace boundary.
- `codex traces`: inspect recent sanitized Codex context/delivery traces and
  classify prompt construction, diagnostic smoke, generic context traces, and
  real `codex exec` delivery.
- `enhance ...`: provider plans, OAuth import/list, enqueue, dry-run, fake
  worker, worker doctor, sidecar run, sidecar serve, and grade-runs.

Use module form when the console shim is stale:

```powershell
python -m chimera_memory.cli stats
```

## MCP Server

`chimera_memory/server.py` owns MCP registration. `chimera_memory/mcp_surface.py`
filters tools by configured surface:

- `full`: legacy/admin full surface.
- `persona`: persona memory belt plus transcript recall tools.
- `codex`: Codex Desktop project surface with the project/global memory belt,
  exact `memory_search`, `memory_query`, scoped `memory_stats`,
  `memory_whereami`, and scoped read-only `memory_live_retrieval_check`; it does
  not register generic transcript recall tools.
- `persona_memory`: only the memory belt.
- `worker`: enhancement worker-only tools.

The MCP server publishes surface-aware client-visible instructions. Full and
persona surfaces can advertise transcript recall tools such as
`semantic_search`; the Codex surface advertises only scoped project/global
curated-memory tools and explicitly says transcript fallback is outside MCP via
`chimera-memory codex exec --include-transcripts` or Codex context/trace wrapper
flows. These instructions are live guidance, not a prompt-injection harness:
clients still need a hook, wrapper, or external harness for mechanical pre-turn
insertion.
MCP text, public trace-query item payloads, and public audit-query payloads
render memory paths through display-safe labels: safe relative paths stay
visible, path-shaped or absolute DB values collapse to filename labels, and
trace/audit items include fingerprints instead of raw local filesystem paths.
Prompt/MCP prose fields such as context-pack card snippets, direct retrieval
snippets, and `about` text pass through display-time secret sanitization and
local-path redaction; raw DB text remains available internally for matching and
ranking.
Public recall trace queries also sanitize request/response payloads and item
metadata on read. Context-delivery traces (`memory_context_pack`,
`memory_live_retrieval`, and `codex_transcript_context`) omit raw query text
because it can be prompt-derived.
Non-local URIs and opaque ids remain visible so diagnostics do not lose useful
external references. Public audit-query payloads additionally return redaction
receipts for sensitive prompt, body, command, process output, and
credential-like fields while keeping ordinary status and typed error fields
readable.

## Recommended Tool Routing

For transcript recall on full/persona surfaces with legacy Discord-shaped rows,
prefer compact progressive disclosure:

1. `discord_recall_index`
2. `discord_detail`
3. `discord_recall` only when direct full-content recall is needed

For curated memory, prefer `memory_stats`, `memory_context_pack`,
`memory_recall`, `memory_search`, and `memory_query` according to the task.
Use `memory_live_retrieval_check` when a caller needs a dry-run, non-injecting
view of the topic-shift recall decision. It follows default retrieval
governance, including excluding generated synthesis rows unless
`include_synthesis=true` is explicitly requested.
`memory_stats` follows the same live scope and default governance filters as
direct retrieval, so Codex project mode should not expose persona-private corpus
counts.

For diagnostics, start with `memory_diagnose` modes before inspecting raw DBs or
logs. `memory_diagnose(mode="context")` gives a body-safe prompt-context status
view with the latest context trace, latest returned context trace, and the
on-demand MCP versus wrapper/harness boundary.
`memory_diagnose(mode="gaps")` depends on the declared runtime `networkx`
package for graph analysis.

Codex/no-persona context tools accept JSON `null` for optional identity and
routing fields such as `persona`, `project_id`, `previous_context`, and
`scope`; the server normalizes those values to empty/no-persona defaults before
calling focused retrieval modules. This keeps no-persona Codex clients from
failing validation when they represent omitted optional fields as null.

## Streamable HTTP And Startup Workers

`chimera-memory serve --transport streamable-http --host 127.0.0.1 --port 8765`
is implemented for one shared local server process.

Server diagnostics filter only the benign Windows asyncio proactor
connection-reset record produced by local client disconnects. Other asyncio
errors still reach normal logs.

Active-harness lease diagnostics are warning-only. Same-host leases whose
process IDs are no longer live are ignored for active conflict counts, which
keeps restarted/crashed local MCP processes from producing false "another
harness is using this persona DB" warnings while preserving warnings for real
live concurrent processes.

Startup maintenance defaults to post-ready behavior: the server waits for the
first MCP `tools/list`, then starts indexing, file watching, transcript
embedding, health, and enhancement workers in the background when it owns the
startup maintenance lease. Worker MCP surface disables nested maintenance.
The Windows shared HTTP starter defaults to no-persona Codex project mode,
creates the repo project root plus `~/.chimera-memory/global-memory`, exports
`CHIMERA_MEMORY_GLOBAL_ROOT`, and starts the watcher after those roots exist.
For existing listeners, it only inspects listening socket owners and accepts
the Windows venv-launcher shape where the socket owner is base `python.exe` but
the parent executable or command line is the repo `.venv` Python; mismatched
ChimeraMemory owners are still refused unless `-Replace` is explicit.
The memory file watcher schedules persona, shared, global, and every configured
project root when a persona/admin profile permits persona-tree indexing. In
no-persona Codex/project mode it skips persona-tree watches and keeps shared,
global, and explicit project roots. The handler also fails closed for persona
paths when the persona tree was intentionally skipped, so an unexpected event
cannot index private persona files. Multiple `CHIMERA_MEMORY_PROJECT_ROOTS`
entries are watched independently, so live edits in one project root do not
mask another project or global memory root.

## Codex Setup

No-persona Codex project mode is first-class. It sets `CHIMERA_CLIENT=codex`,
project identity/root, `CHIMERA_MEMORY_GLOBAL_ROOT`, and
`CHIMERA_MEMORY_MCP_SURFACE=codex`, while leaving persona identity unset. It
must not crawl private persona trees. The Codex MCP guard also rejects explicit
`persona` arguments and env-derived `TRANSCRIPT_PERSONA` identity for memory
reads, stats, context packs, live retrieval, authored writes, and persona
scope attempts, so a caller cannot opt the no-persona surface into
persona-private scope. The Codex surface does not register the persona-facing
`memory_review` queue or persona-source `memory_promote_snapshot`; global-root
review remains a CLI/diagnostic flow through `chimera-memory global review`.
Codex `memory_diagnose` is restricted to safe
project/global diagnostics: tools, stats, context, provider plan, worker/health,
guard, and whereami. Persona/admin modes such as zones, traces, audit, harness,
gaps, and consolidation are rejected on the Codex surface.
The whereami diagnostic reports project identity/root and `CHIMERA_MEMORY_GLOBAL_ROOT`
provenance alongside persona/transcript runtime fields, so a no-persona Codex
session can prove global memory wiring without dumping raw process env.
In no-project Codex mode, direct auto-scoped memory tools still fail closed;
`memory_diagnose(mode="stats")` is the exception that reports global-only
corpus stats rather than unscoped operator/admin totals.
The explicit `CHIMERA_MEMORY_PROJECT_ID` is used as the single-project indexing
identity; folder-derived ids are fallback only.

`chimera-memory codex doctor` checks setup without printing secrets, raw env
values, prompt text, or memory bodies. In addition to MCP config/reachability,
it performs a local HTTP MCP initialize identity check for shared sidecars. It
also reads the latest CM health snapshot and path-safe runtime profile stored
with health snapshots, reports snapshot freshness, then warns when a reachable
shared HTTP sidecar is not ChimeraMemory, a local HTTP listener is owned by a
different Python runtime than the doctor/repo runtime, the health snapshot is
stale, the sidecar is not running as no-persona Codex project+global memory, or
the global root is missing. Listener runtime diagnostics report sanitized owner
counts, process names, and stale PIDs only, never raw process commands. The
runtime profile also includes indexed and default-available
global corpus counts, so an empty global root is visible without being marked as
a setup failure. Because the health snapshot is low-cadence, `codex doctor`
overlays live `memory_files` global corpus counts when the transcript DB is
readable; runtime mode still comes from the path-safe snapshot, while corpus
availability reflects current indexed rows. An empty global corpus diagnostic
includes the fix path: add/promote global memories or start the sidecar with a
populated global root. Corpus diagnostics separate default-available global
evidence from confirmed instruction-grade global files, so pending or
evidence-only records are reported as retrievable leads rather than settled
instructions. For no-persona project memory, missing
`CHIMERA_MEMORY_GLOBAL_ROOT` is a fail-closed diagnostic boundary: live indexed
global rows are reported as rootless inactive rows, and the global context smoke
is skipped instead of using stale all-global rows to validate active memory.
Doctor also checks the global review queue and reports sanitized pending/reason
counts plus confirm-guard blocked/finding counts, warning when a pending global
file would be blocked by instruction-grade confirmation. It also reports safe
enhancement provider smoke evidence: first from the latest sidecar health
`provider_profile` when available, otherwise from local/config plan-mode
provider smoke. The receipt includes selected provider/model, credential-ref
presence, and whether the selected provider uses user OAuth without making a
model call or printing credential refs; explicit live provider proof remains
`chimera-memory enhance provider-smoke --live --http-sidecar --json`. It runs an in-memory global context smoke
against indexed global metadata to verify whether the `codex context` wrapper
would return prompt evidence right now, without writing trace rows, prompt text,
or memory bodies to the live DB/report. It reports the latest context trace and
the latest returned context trace so operators can distinguish "MCP is
reachable" from "CM actually supplied prompt evidence." It also records the
boundary that MCP tools are on-demand; mechanical prompt evidence requires
`codex context`, `codex exec`,
or another hook/harness. It also reports whether the optional `chimera-memory`
wrapper command resolves on PATH, keeping missing/stale shell shims separate
from HTTP MCP sidecar health. Context trace timestamps preserve stored UTC and
append local time so local-day boundaries are explicit. The JSON report includes
a `context_delivery` receipt that separates generic context traces, Codex
context-builder traces, real `codex exec` post-run delivery events, returned
delivery traces, and the no-write global smoke result, so the diagnostic does
not overread sidecar reachability, context construction, dry-runs, or an
in-memory smoke as actual Codex prompt delivery. When the recall/audit tables
exist, only traces with Codex-owned `codex-context` audit events satisfy Codex
context-readiness checks; newer generic MCP, persona, or admin context traces
remain visible as generic trace metadata but do not make doctor report Codex
prompt context as ready. When the global context smoke
returns evidence but real delivery is still absent, doctor recommends
proof/delivery commands with `--scope global` so the path does not rely on
project-id inference from cwd. Real exec delivery includes a
recency receipt so a historical successful wrapper run is not mistaken for
fresh current-session prompt evidence. On Windows, HTTP listener runtime
diagnostics also report sanitized match-source counts such as
`parent_executable=1`, so a repo-venv parent launcher with a base-Python listener
child can be distinguished from a stale unrelated Python owner without exposing
raw executable paths or command lines. `codex doctor` also compares the listener
start time to selected ChimeraMemory runtime source-file mtimes and reports
`http_listener_source_freshness`; this catches the live failure mode where an
HTTP sidecar is reachable but still running code loaded before the current
runtime modules changed.

`chimera-memory codex traces` is the focused context-delivery history view. It
reads recent `memory_context_pack` and `codex_transcript_context` recall traces
plus matching audit events, supports `--real-only`, repeatable `--kind` /
`--delivery-kind` filters, and `--since`, and reports only sanitized trace ids,
timestamps, counts, delivery kind, delivery mode, and context/delivery event
types. Supported kind aliases are `real`, `failed`, `prompt`, `diagnostic`, and
`context`. Explicit timezone timestamps are safest for `--since`; date-only
values are interpreted as the local day start. It omits
prompt text, memory bodies, raw trace payloads, and raw paths. The selected
trace DB is reported as a path-safe payload with name, provenance, and
fingerprint instead of an absolute path. Trace receipts now include body-safe
recommendations when the selected window has context
construction but no real `codex exec` delivery, including receipt-only dry-run
verification and real wrapper-delivery commands. They also include sanitized
request scope metadata and returned memory scope counts; when the latest
returned prompt construction contains only global memory, no-real-delivery
recommendations use `--scope global`. If a wrapped `codex exec` attempt fails
before Codex launches, CM records a sanitized
`codex_prompt_delivery_failed` event, classifies that trace as
`exec_delivery_failed`, and recommends verifying the Codex executable or using
`--codex-bin` / `CHIMERA_MEMORY_CODEX_BIN` when that failure is still the latest
relevant wrapper-delivery state. Doctor keeps the latest real wrapper attempt
separate from the latest real wrapper attempt that returned memory, so a newer
zero-evidence Codex turn is reported as a miss instead of being hidden behind an
older successful context delivery. If the no-write global smoke retrieves
memory while that latest real delivery returned zero cards, doctor escalates the
state to warning because the real turn was not memory-augmented by
ChimeraMemory.

`chimera-memory codex context` is a no-persona prompt-wrapper helper. It calls
`memory_context_pack`, emits the original prompt unchanged on miss, strips any
existing CM prefix before rewrapping, supports stdin/UTF-8 file input for hooks,
supports `--prompt` for manual diagnostics, and supports only `auto`, `project`,
and `global` scopes. `auto` and `project` require a resolved project id so Codex
project mode does not silently fall back to all-memory recall. The CLI wrapper
can infer no-persona project id/root from `--project-root`, `--cd`, or the
current repo directory when safe; the focused context builder remains fail-closed
without a project id or configured environment. Wrapper global evidence uses an
explicit `--global-root`, then `CHIMERA_MEMORY_GLOBAL_ROOT`, then CM's default
global root, so the CLI path applies the same active-root boundary even when the
caller does not pass a root flag. Context-pack card labels expose root-relative
paths or synthetic scoped IDs, not raw filesystem paths, even when a legacy DB
row lacks a stored relative path.
Context cards include review/authority markers, and the Codex grounding rule
treats `review=pending`, `evidence-only`, `needs-confirmation`,
`lifecycle=stale`, and `lifecycle=archived` records as unconfirmed or
non-current leads rather than settled instructions. `--receipt-only --json`
emits a prompt/body-free verification receipt with scope, counts, and trace ids.
`chimera-memory codex exec` is the CLI launcher form of the same boundary: it
passes the wrapped prompt to `codex exec -` over stdin so memory context does not
need to be copied into the Codex child argv. Non-dry-run JSON receipts summarize
child stdout/stderr by presence, character count, and line count by default;
raw output is included only when `--include-output` is explicitly set.
Dry-run exec can use `--receipt-only` for the same prompt/body-free verification
receipt.
`codex exec` records a safe `codex_prompt_delivered` audit event after the
Codex subprocess returns. If the child process cannot be launched, it records a
safe `codex_prompt_delivery_failed` audit event without raw prompts, commands,
output, or local exception text. `codex context` and `codex exec --dry-run` tag
recall traces as context construction instead of real delivery.
Transcript snippets are opt-in and project-scoped by session `cwd`; they are a
fallback evidence source, not a replacement for curated memory. Transcript
fallback runs write `codex_transcript_context` recall traces and
`codex_transcript_context_*` audit events with sanitized item metadata.

On the `codex` MCP surface with no persona configured, read-oriented memory
tools fail closed instead of falling back to all-memory recall. `scope=all` is
rejected, and `scope=auto` or `scope=project` requires a configured
`CHIMERA_MEMORY_PROJECT_ID` or explicit `project_id`; `scope=global` remains the
global-only retrieval path.

`chimera-memory codex doctor` treats the configured global root as the active
no-persona global corpus for diagnostics. Live DB counts are split into
configured-root and outside-root global rows; outside-root rows are reported by
count only and do not make the configured corpus or no-write global context
smoke look healthy. MCP `memory_context_pack` and the Codex wrapper pass the
active global root into retrieval so outside-root global rows are not injected
as prompt evidence. MCP `memory_live_retrieval_check` and direct MCP read tools
(`memory_search`, `memory_query`, `memory_recall`, `memory_stats`) use the same
active-root filter, so stale outside-root global rows are not suggested,
returned, or counted as active Codex memory.

`chimera-memory global inspect` is the read-only receipt for the no-persona
global corpus: it reports configured global-root existence, markdown file
counts, indexed/default-available DB counts, unindexed root markdown, indexed
rows whose files are missing, target-root DB counts, and path-safe
counts/details for indexed global rows outside the inspected root. Its
filesystem-frontmatter `authority` summary distinguishes evidence-enabled,
trusted instruction-grade, pending-review, evidence-only, and
confirmation-gated files before or after DB indexing. It also runs a read-only
memory guard scan over global-root markdown and reports sanitized finding counts
and relative paths without echoing unsafe samples. Missing or unrecognized
frontmatter is classified as imported, pending, evidence-enabled,
instruction-disabled, and confirmation-required.
With `--query <TEXT>`, `global inspect` also runs a read-only global
context-pack smoke against an in-memory copy of the selected DB. The
`query_smoke` receipt reports retrieval counts, token estimate, root-filter
policy, and safe card metadata such as relative path, governance labels, score,
and query-match profile. Miss receipts also include body-safe diagnostics that
distinguish no scoped candidates, quality-gate filtering, dedupe, and
packing-stage gaps, plus matching body-safe recommendations. It does not
persist recall traces or audit rows and does not include memory bodies,
snippets, card text, prompts, raw DB paths, or raw root paths.
`chimera-memory global seed` is the
write-capable seeding path. It is dry-run-first, takes an explicit source
directory, targets the configured or user-supplied global root, copies only
markdown files on `--write`, skips hidden/cache/auth-style directories, and
indexes copied files as `memory_scope=global` unless indexing is disabled. It
accepts repeatable include/exclude relative globs so mixed shared/global sources
can seed only reviewed global files while leaving roster, relationship,
image-feedback, or other persona-specific shared files untouched. Broad
write-mode seed runs fail closed when selected paths look mixed-source unless
the operator narrows the source with targeted includes/excludes that name those
mixed paths, or passes `--allow-mixed-source` for an intentional reviewed
compatibility import. Broad include globs such as `**/*.md` do not count as
explicit review of mixed-source paths. These
commands are intended for reviewed shared/global corpora and must not implicitly
read or write persona-private memory roots. The global CLI helpers use
`CHIMERA_MEMORY_GLOBAL_ROOT` when present and otherwise fall back to
`~/.chimera-memory/global-memory`, matching Codex no-persona setup even when the
interactive shell did not inherit the shared sidecar environment. Write-mode
global seed first fails closed on unresolved target conflicts unless
`--overwrite` is supplied, then runs the memory guard over selected files and
fails closed on credential, injection, or hidden-content findings without
echoing unsafe samples. It then stamps missing or ambiguous governance before
indexing so imported global files are evidence-only and pending review unless
they already carry explicit confirmed instruction-grade provenance. The
governance stamp forces non-`user_confirmed` files and files whose original
frontmatter was not already `memory_scope: global` to
`can_use_as_instruction: false` and `requires_user_confirmation: true` even when
legacy frontmatter claimed otherwise. Inspect, seed, reindex, and review
receipts represent root and DB locations as names, provenance labels, and short
fingerprints rather than raw absolute paths; human inspect, seed, reindex, and
review output uses the same safe labels.
`chimera-memory global inspect` is read-only but now carries body-safe
recommendations from the global review queue when review-gated global files are
present, letting the corpus/authority receipt point directly to inspect,
confirm-preview, confirm-write, evidence-only, or remediation commands without
exposing memory bodies. When inspect sees indexed global rows outside the
configured root, it states that active retrieval excludes those rows and
recommends path-safe `--files` inspection plus a dry-run active-root reindex
preview instead of suggesting automatic outside-root pruning or immediate
write-mode repair.
`chimera-memory global reindex` is the DB repair path for files already present
under one global root. It is dry-run by default, indexes only that root on
`--write`, honors the same include/exclude filters, and prunes stale global rows
under that root only when `--prune-missing` is also supplied. Reindex write mode
uses the same memory guard and safe governance stamp before indexing unless
`--no-guard` or `--no-stamp-governance` is supplied. Reindex receipts include
safe root and DB payloads plus the selected-file filesystem-frontmatter
`authority` summary so dry runs show whether selected files are evidence,
trusted instruction-grade, pending, or confirmation-gated before
indexing/stamping. For stale DB rows under the
selected root, reindex uses the row's resolved path as the live authority for
root-relative filter matching and receipts, not a drifted stored
`relative_path`. Prune candidate receipts expose only `relative_path`, `name`,
and a short `path_fingerprint`, not the absolute stale row path. Inspect,
outside-root row, query-smoke card, and query-smoke candidate-profile receipts
collapse path-shaped stored DB `relative_path` values to filename-only labels
before returning them. Query-smoke misses caused by the deterministic quality
gate include safe candidate profiles with governance flags, ranking score, and
query-term coverage, but still omit memory bodies, snippets, prompts, raw root
paths, and raw DB paths. Query-match profiles may expose matched term labels;
those labels are secret-sanitized and local-path-redacted before JSON or text
display so credential-shaped prompt terms are not echoed.
Write-mode
pruning removes file-owned side-table rows for pruned file ids and clears
nullable historical file references on trace, review, and enhancement job rows,
so cleanup does not depend on SQLite foreign-key pragmas being enabled.
Write-mode
global seed/reindex operations record compact audit events with counts, filters, guard
counts, governance-stamp counts, root provenance, root fingerprints, and affected
relative paths, while avoiding memory bodies and raw absolute roots. Write-mode
seed/reindex receipts return non-OK when governance stamping or indexing reports
per-file errors, or when files are skipped from indexing, even if some
filesystem writes or earlier files completed. Files whose governance stamp fails
are not indexed in that run, preserving the evidence-only global import
boundary.
The shared HTTP starter uses the repo-local venv as the intended runtime and now
refuses to silently accept an existing ChimeraMemory listener on the configured
port when that listener was launched from another Python runtime; operators must
confirm replacement with `-Replace`.
`chimera-memory codex exec` receipts now expose a body-safe `delivery_proof`
object. The proof keeps prompt construction, wrapped-prompt memory injection,
subprocess stdin delivery, delivery-event recording, and launch failure as
separate booleans, without storing prompt text, memory bodies, raw commands, or
child output. Dry-run receipts can therefore prove `prompt_injected=true` while
still reporting `subprocess_stdin_delivered=false` and
`real_delivery_recorded=false`. On Windows, bare `codex` wrapper launches are
normalized to launchable shims such as `codex.cmd` or `codex.exe`, avoiding the
extensionless npm shim that can fail before prompt delivery under Python
subprocesses. `codex traces` recommendations also consult the unfiltered latest
delivery attempt, so filtered failed views do not keep recommending delivery
after a newer real wrapper run succeeds.
`chimera-memory global promote` is the no-human global-root promotion path. It
is dry-run by default and evaluates pending global files through named
automation policies such as `trusted_clean`; write mode requires explicit
enablement through `--enable-auto-promotion` or
`CHIMERA_MEMORY_GLOBAL_AUTO_PROMOTE=true`. Passing files are written with
`auto_confirmed` provenance, reindexed, recorded in `memory_review_actions`, and
audited as `global_memory_auto_promoted`. Generated, restricted, excluded,
malformed, wrong-scope, duplicate-body, missing-governance under the strict
policy, or guard-blocked files are skipped with body-safe policy reasons.

`chimera-memory global review` is the durable global-root review path. Without a
target it lists pending global-root markdown plus files that need governance
repair, such as missing policy keys, parse errors, wrong memory scope, or unsafe
instruction-grade state; returned items expose sanitized review reasons,
reason-count summaries, governance flags, and confirm-action guard preview
counts, not memory bodies. Human-readable listings include returned
root-relative review targets with per-file reasons, indexed state,
confirm-guard blocked counts, and body-safe recommendations for listing the
queue, previewing confirmation, automated promotion, writing confirmation after
review, or marking a file evidence-only. Missing or unrecognized source frontmatter is
listed as pending/untrusted evidence instead of default instruction authority.
Queue recommendations are action-guidance-aware:
they include a concrete body-safe inspection command for the first matching
target, include write commands only when the target action can be written
without guard blockage, and otherwise suggest preview-only remediation actions.
Queue-level write recommendations use a `<BODY_SHA256>` placeholder until
target inspection or preview supplies the real reviewed body hash.
Each
returned file also includes
`action_guidance`, a guard-derived matrix that labels whether review actions can
be written without guard blockage, whether they leave the file
default-retrievable, and whether they promote instruction use. Text listings
summarize this as `actions=...` on each returned review target. Repeatable
`--reason <REASON>` filters focus the
listing on blockers such as
`pending_review`, `missing_required_governance`, `non_global_scope`, or the
virtual `confirm_guard_blocked` reason. `confirm_guard_blocked` surfaces files
whose sanitized confirm-action preview would be blocked by the memory guard,
including otherwise confirmed instruction-grade files with unsafe body content.
Filtered receipts keep all-pending `summary` counts separate from
`matching_summary` and `returned_summary` counts. Even when `--limit 0` returns
no file rows, receipts keep the path-safe `first_matching_relative_path` plus a
body-safe `first_matching_target` summary with review reasons, guard counts,
indexed state, and action guidance. Codex doctor can therefore recommend
concrete inspect/confirm/evidence-only/remediation commands instead of
placeholder commands without returning memory bodies. With a
target and no action, the CLI returns a body-safe inspection receipt for that
one global file: review reasons, frontmatter keys, indexed/default availability,
guard status, body hash, body length, and recommendations are exposed without
memory body text. With a
target/action it previews the frontmatter transition; with `--write --reviewer`,
it preserves the markdown body, updates global review governance in frontmatter,
reindexes the file immediately as `memory_scope=global`, writes a
`memory_review_actions` row, and records a path-safe `global_memory_*` audit
event. Preview-mode `preview_frontmatter` is a display-safe view of the
reviewed frontmatter: string values are passed through secret sanitization and
local-path redaction, while write-mode still persists the canonical reviewed
frontmatter. Target inspection and preview recommendations include
`--expect-body-sha256 <HASH>` when CM knows the reviewed body hash. Write-mode
review actions require that argument and fail closed before mutation when it is
missing, invalid, or no longer matches the reviewed body.
Review targets are root-relative markdown paths; leading separators,
Windows drive or stream separators, `..`, control characters, non-markdown
extensions, and missing files fail closed instead of being normalized into
another file. Review action receipts use the relative target plus hashes and do
not return the absolute target file path. Targets under hidden, cache, auth, or
other skipped corpus directories are rejected case-insensitively, matching
discovery/seeding boundaries. Malformed-frontmatter sources are
treated as pending/untrusted; review
actions preserve the original source text as body under repaired frontmatter and
report `source_parse_error` without echoing the source text. Review listings and
Codex doctor use the same preserved-body path when previewing confirm-guard
outcomes, so unsafe malformed sources are counted without exposing body text.
`confirm` is the manual review action that promotes to `user_confirmed`
instruction-grade memory; `global promote` is the automated action that promotes
to `auto_confirmed` instruction-grade memory after policy gates pass. Other
settled review actions are durable reviewed decisions that keep global memory
out of instruction use. Write-mode review runs the
memory guard before outcomes that would leave the post-review file
default-retrievable, blocking unsafe promotion while still allowing remediation
outcomes such as reject, dispute, supersede, or restrict-scope. Target/action
previews and failed writes return the same body-safe recommendation shape as
queue listings: guard-clean previews include the exact write command, while
guard-blocked previews explicitly avoid a write recommendation and suggest
remediation previews. If the
post-write index/review-audit step fails, CM attempts to restore the original
markdown and reports the restore receipt so DB and markdown do not silently
diverge. Human-readable
review action output reports sanitized review-guard required, blocked-file, and
finding counts, including failed writes, without exposing memory bodies, guard
patterns, or samples.
Default-retrieval review checks use the same `exclude_from_default_search` key
as indexing and context retrieval.

## Harness Detection

`chimera_memory/harness.py` `detect_harness()` chooses the transcript JSONL dir
and parser for the active harness. Precedence (explicit env always wins; each
later step only fills unset fields): explicit `CHIMERA_CLIENT` /
`TRANSCRIPT_JSONL_DIR` (dir shapes recognized for `.codex/sessions`,
`.claude/projects`, `.hermes/profiles/<persona>/sessions`) > process-injected
running signals (`CLAUDECODE` -> Claude Code, `CODEX_SANDBOX` -> Codex; install
vars `HERMES_HOME`/`CODEX_HOME` are deliberately ignored) > on-disk Codex
sessions signature > per-file JSONL content sniff > Claude-Code default.
Discovery is parser-aware via `BaseParser.session_glob` (`*.jsonl` for
Claude/Codex, `session_*.json` for Hermes), and per-file content sniffing means a
Codex rollout is never silently parsed as Claude. The persona transcript DB path
resolves identically across the MCP query tools, the maintenance lock, and the
five startup workers via `server._resolve_transcript_db_path()`.

## Hermes Setup

`chimera-memory hermes {template|doctor|install} --persona <NAME>` configures
standalone-Hermes transcript indexing (owned by `hermes_setup.py`). Standalone
Hermes is persona-scoped: CM reads only `~/.hermes/profiles/<persona>/sessions`.
`template` is output-only (indexer env + paste-in `mcp_servers` block,
least-privilege `persona_memory` surface); `doctor` is read-only and path-safe;
`install` writes per-persona launcher scripts under `~/.chimera-memory/hermes/`
(dry-run by default) and never mutates Hermes's `config.yaml`. Hermes running
inside Claude Code (Claude-format JSONL under `~/.claude/projects`) is handled as
`claude-code` with no setup. The PersonifyAgents installer is deprecated.

## Service-Mode Boundary

Local streamable HTTP exists. A broader resident service architecture with a
single owner process per persona DB remains an open architecture decision.
