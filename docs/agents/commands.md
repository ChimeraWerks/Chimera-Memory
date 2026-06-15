# Agent Commands

Run commands from the repo root unless a task says otherwise.

## Environment Setup

Install editable package with dev test dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Preferred Windows local setup keeps dependencies inside the repo venv:

```powershell
.\scripts\bootstrap-cm-venv.ps1 -Dev
.\.venv\Scripts\python.exe -m chimera_memory.cli stats
```

Optional MCP extra:

```powershell
python -m pip install -e ".[mcp,dev]"
```

Optional FastEmbed CUDA extra:

```powershell
python -m pip install -e ".[gpu,dev]"
```

The repo includes `uv.lock`, but no Makefile, justfile, taskfile, or package
scripts were present at audit time. Prefer explicit `python -m ...` commands.

## Core CLI

The console script is `chimera-memory = chimera_memory.cli:main`.

```powershell
chimera-memory serve
chimera-memory serve --transport streamable-http --host 127.0.0.1 --port 8765
.\scripts\start-cm-http.ps1 -Port 8766 -Bootstrap
.\scripts\install-cm-http-autostart.ps1 -Port 8766 -RunNow
chimera-memory backfill
chimera-memory backfill --jsonl-dir <DIR> --persona <NAME> --client claude
chimera-memory backfill --jsonl-dir <DIR> --persona <NAME> --client codex
chimera-memory backfill --jsonl-dir <DIR> --persona <NAME> --client hermes
chimera-memory embed
chimera-memory embed --limit 500 --batch-size 64
chimera-memory stats
chimera-memory split-db
```

Use module form when the editable console script is unavailable:

```powershell
python -m chimera_memory.cli stats
```

## Harness Auto-Detection

`chimera_memory/harness.py` `detect_harness()` resolves the active harness so the
transcript JSONL directory and parser are chosen without per-launch config.
Precedence (each step only fills what the previous left unset; explicit env always
wins): explicit `CHIMERA_CLIENT` / `TRANSCRIPT_JSONL_DIR` (the dir shape is
recognized for `.codex/sessions`, `.claude/projects`, and
`.hermes/profiles/<persona>/sessions`) → process-injected running-harness signals
(`CLAUDECODE` → Claude Code, `CODEX_SANDBOX` → Codex; install-location vars like
`HERMES_HOME` / `CODEX_HOME` are deliberately NOT used because they persist in
every shell) → on-disk Codex sessions-dir signature → per-file JSONL content
sniffing at index time → Claude-Code default. Discovery is parser-aware:
Claude/Codex use `*.jsonl`, Hermes uses `session_*.json`. So a Codex rollout is
never silently parsed as Claude even if the label is wrong.

## Hermes Setup Helpers

Standalone Hermes is persona-scoped: a persona is required so CM reads only
`~/.hermes/profiles/<persona>/sessions`, never across personas. Hermes running
inside Claude Code writes Claude-format JSONL and is handled as `claude-code`
automatically; these helpers are for the standalone Hermes agent's native
`session_*.json` store.

```powershell
chimera-memory hermes template --persona <NAME>
chimera-memory hermes template --persona <NAME> --json
chimera-memory hermes doctor --persona <NAME>
chimera-memory hermes doctor --persona <NAME> --json
chimera-memory hermes install --persona <NAME>
chimera-memory hermes install --persona <NAME> --write
```

`template` prints (output-only) the persona-scoped indexer env/command plus a
paste-in Hermes `config.yaml` `mcp_servers` block (least-privilege
`persona_memory` surface). `doctor` is read-only: it checks the Hermes home, the
persona session store, runs a parse smoke, and confirms harness resolution.
`install` is dry-run by default and writes per-persona launcher scripts under
`~/.chimera-memory/hermes/`; it never mutates Hermes's `config.yaml`.

## Codex Setup Helpers

```powershell
chimera-memory codex doctor
chimera-memory codex doctor --json
chimera-memory codex traces
chimera-memory codex traces --real-only --json
chimera-memory codex traces --kind failed --json
chimera-memory codex traces --since 2026-06-10T21:00:00Z
chimera-memory codex template --persona <NAME>
chimera-memory codex install --persona-id <ROLE/NAME> --persona-root <PATH> --yes
chimera-memory codex install --project-id <ID> --project-root <DIR> --global-root <DIR>
"prompt text" | chimera-memory codex context --project-id <ID>
"prompt text" | chimera-memory codex context
"prompt text" | chimera-memory codex context --project-id <ID> --json
chimera-memory codex context --prompt "prompt text"
chimera-memory codex context --prompt "prompt text" --receipt-only --json
chimera-memory codex context --project-id <ID> --prompt "prompt text"
chimera-memory codex context --project-id <ID> --prompt-file <PATH>
chimera-memory codex context --project-id <ID> --prompt-file <PATH> --previous-context-file <PATH> --no-force
chimera-memory codex exec --prompt "prompt text" --dry-run --json
chimera-memory codex exec --prompt "prompt text" --dry-run --receipt-only --json
chimera-memory codex exec --project-id <ID> --prompt "prompt text" --dry-run --json
chimera-memory codex exec --project-id <ID> --prompt-file <PATH>
chimera-memory codex exec --project-id <ID> --prompt-file <PATH> --dry-run --json
chimera-memory codex exec --project-id <ID> --project-root <DIR> --prompt-file <PATH> --include-transcripts
```

`codex context` is the prompt-wrapper helper for Codex Desktop/CLI project mode.
Use stdin or `--prompt-file` for hooks so prompt text is not stored in shell
history or process argv. `--prompt` is for manual diagnostics and one-off local
commands. It emits the original prompt unchanged on miss, uses no persona
identity, and fails closed for `auto`/`project` scope unless a project id is
supplied, resolved from the environment, or inferred by the CLI wrapper from a
safe repo workspace (`--project-root`, `--cd`, or current directory). When
supplied via `--global-root` or `CHIMERA_MEMORY_GLOBAL_ROOT`, global evidence is
filtered to that active root; otherwise the wrapper uses CM's default global
root. In all three cases, stale outside-root global DB rows are not injected.
Returned memory cards include
review/authority markers such as `review=pending`, `evidence-only`,
`needs-confirmation`, `lifecycle=stale`, and `lifecycle=archived`; the wrapper's
grounding rule treats those records as unconfirmed or non-current leads, not
settled instructions. Use `--receipt-only --json` to verify injection, scope,
counts, and trace ids without printing prompt text or memory snippets.

`codex exec` uses the same context builder, then launches `codex exec -` and
writes the wrapped prompt through stdin. Use `--dry-run --json` to inspect the
command and injected prompt without starting Codex, or add `--receipt-only` to
keep the dry-run receipt prompt/body-free. For non-dry-run `--json`,
the receipt includes return code and stdout/stderr counts by default; use
`--include-output` only when raw Codex child output is intentionally needed.
Exec receipts include a body-safe `delivery_proof` object that separates prompt
construction, memory injection into the wrapped prompt, subprocess stdin
delivery, delivery-event recording, and launch failure without including prompt
text, memory bodies, raw commands, or child output. On Windows, bare `codex`
wrapper launches are normalized to a launchable shim such as `codex.cmd` or
`codex.exe` so Python subprocesses do not trip over extensionless npm shims.

`codex doctor` checks MCP setup, local HTTP MCP initialize identity for shared
sidecars, CM health freshness, the live sidecar runtime/provider profile, the
latest context trace, the latest returned context trace, and enhancement
provider smoke evidence without printing prompt text, memory bodies, raw env
values, raw paths, or secrets. It warns when a
reachable shared HTTP sidecar is not ChimeraMemory, when a local HTTP listener
is owned by a different Python runtime than the doctor/repo runtime, when the
health snapshot is stale, when the sidecar is not running as no-persona Codex
project+global memory, or when the global memory root is missing. Listener
runtime diagnostics report sanitized owner counts, process names, and stale
PIDs only, not raw process commands. It also
reports indexed/default-available global corpus counts separately from root
existence. When the transcript DB is readable, those corpus counts come from the
live `memory_files` table overlaid onto the latest low-cadence health snapshot,
so a fresh watcher index is visible immediately. The live corpus receipt
separates default-available evidence from confirmed instruction-grade global
files; pending or evidence-only records can be retrieved as leads without being
reported as settled instructions. When a global root is configured, doctor
counts the configured root separately and warns about indexed global rows
outside that root instead of using them to prove active global memory. If the
sidecar is wired but the configured global corpus is empty, the diagnostic
points operators toward adding/promoting global memories or starting the sidecar
with a populated global root. When no-persona project memory lacks
`CHIMERA_MEMORY_GLOBAL_ROOT`, doctor reports any indexed global DB rows as
inactive rootless rows and skips the global context smoke rather than treating
stale rows as active memory. For no-persona
project memory, doctor also checks the global review queue and reports sanitized
pending/reason counts plus confirm-guard blocked/finding counts, warning when a
pending global file would be blocked by instruction-grade confirmation. It also
reports selected enhancement provider/model, credential-ref presence, and
whether the selected provider uses user OAuth without calling a model or
printing credential refs. Doctor prefers the latest sidecar health
`provider_profile` when available and falls back to local/config plan-mode
provider smoke when no sidecar profile is recorded. Use `chimera-memory enhance
provider-smoke --live --http-sidecar --json` for explicit live provider proof. It also
relies on the Codex MCP surface failing closed when a caller supplies explicit
or env-derived persona identity; persona-scoped reads, stats, authored writes,
and persona-scope attempts are rejected instead of being treated as Codex
project/global memory. The Codex surface also excludes the persona-facing
`memory_review` queue and persona-source `memory_promote_snapshot`; no-persona
global review is handled by
`chimera-memory global review` and body-safe doctor recommendations. Codex
`memory_diagnose` exposes only the safe project/global subset: tools, stats,
context, provider plan, worker/health, guard, and whereami; persona/admin
diagnostics such as zones, traces, audit, harness, gaps, and consolidation are
rejected on the Codex surface. The whereami mode includes project identity/root
and global-root provenance so no-persona project/global wiring can be audited
without raw environment dumps. MCP display text and public trace item payloads
must render memory paths as safe relative labels or filename/fingerprint
receipts, never raw path-shaped DB values. Prompt/MCP prose fields such as
retrieval snippets and `about` text are sanitized for credential-like content
and local path references at display time, while raw DB text remains available
for matching and ranking. Public recall trace queries also sanitize
request/response payloads and item metadata on read. Context-delivery traces
(`memory_context_pack`, `memory_live_retrieval`, and
`codex_transcript_context`) omit raw query text because it can be prompt-derived.
Public audit query payloads follow the same read-side
safety rule for local path-like target ids and payload fields while preserving
non-local URIs and opaque ids, and redact sensitive
prompt, body, command, process-output, and credential-like fields as receipts.
When no project id/root is configured, direct auto-scoped memory tools fail
closed, while `memory_diagnose(mode="stats")` reports global-only corpus stats
instead of unscoped operator/admin counts.
Doctor also runs an in-memory global context smoke against configured-root
global metadata to verify whether the `codex context` wrapper would return
prompt evidence right now, without writing trace rows, printing prompt text, or
exposing memory bodies. It
reports that MCP tools are on-demand and that automatic prompt evidence
requires `codex context`, `codex exec`, or another hook/harness. Trace timestamps
show stored UTC plus local time to avoid local day-boundary confusion. The JSON
report includes a `context_delivery` receipt with generic context traces, Codex
context-builder traces, real `codex exec` delivery events, returned delivery
traces, and the no-write global smoke result, so operators can tell whether CM
is merely reachable, would return memory through the wrapper, or has actually
handed memory prompt evidence to a Codex subprocess. When recall/audit tables
exist, doctor treats only Codex-owned traces from actor `codex-context` as
Codex prompt-context readiness; newer generic, persona, MCP, or admin context
traces remain visible as generic trace metadata but do not satisfy Codex
readiness checks. `codex context` and
`codex exec --dry-run` are recorded as prompt construction, not real delivery.
For per-run proof, `codex exec --receipt-only --json` exposes
`delivery_proof.prompt_injected`, `subprocess_stdin_delivered`, and
`real_delivery_recorded` as separate booleans.
When the global context smoke returns evidence but no real delivery exists yet,
doctor's suggested proof/delivery commands include `--scope global` so they do
not depend on project-id inference from the current shell directory.
If `codex exec` fails before Codex launches, the wrapper records a sanitized
`codex_prompt_delivery_failed` audit event and doctor reports the latest failed
attempt separately from successful real delivery.
`codex doctor` also reports whether the optional `chimera-memory` wrapper command
resolves on PATH; missing or stale shims affect manual wrapper use, not HTTP MCP
sidecar reachability. Real exec delivery also includes a recency receipt so
historical delivery is not mistaken for fresh current-session evidence. On
Windows, listener-runtime details use sanitized match-source counts such as
`parent_executable=1`; this means the listener child may appear as the base
Python executable while the accepted launcher parent is the repo venv. Doctor
also reports `http_listener_source_freshness`, comparing listener start time to
selected runtime source-file mtimes, so a reachable but stale loaded sidecar is
called out with a restart recommendation.

`codex traces` is the focused delivery-history view. It reads recent
`memory_context_pack` and `codex_transcript_context` recall traces plus matching
audit events, classifies each row as prompt construction, diagnostic smoke,
generic context trace, failed `codex exec` delivery, or real `codex exec`
delivery. It supports `--real-only` to answer whether CM has actually handed
prompt evidence to a Codex subprocess, and repeatable `--kind` /
`--delivery-kind` filters for `real`, `failed`, `prompt`, `diagnostic`, or
`context` traces. Use `--since <ISO_OR_DATE>` for date-bounded checks; explicit
timezone timestamps are safest, while date-only values are interpreted as the
local day start. The report omits prompt text, memory bodies, raw trace payloads,
and raw paths. The selected trace DB is reported as a path-safe payload with
name, provenance, and fingerprint instead of an absolute path. It includes
sanitized request scope metadata and returned memory scope counts, such as
`returned_scopes=global=1`, so operators can tell whether a prompt-construction
trace returned global memory evidence without seeing the memory text. When no
real `codex exec` delivery is present, JSON and text
receipts include body-safe recommendations for receipt-only dry-run verification
and real wrapper delivery; if the latest returned prompt construction contains
only global memory, those commands use `--scope global`. If the latest relevant
wrapped exec attempt failed before launch, recommendations start with checking
the Codex executable or supplying `--codex-bin` / `CHIMERA_MEMORY_CODEX_BIN`.
Filtered views still inspect the unfiltered latest delivery attempt, so an old
failed row does not keep recommending delivery after a newer real wrapper
delivery succeeds. Doctor keeps the latest real wrapper attempt separate from
the latest real wrapper attempt that returned memory, so a newer zero-evidence
Codex turn is reported as a miss instead of being hidden behind an older
successful context delivery. If the no-write global smoke can retrieve memory
but the latest real Codex delivery returned zero cards, doctor emits a warning
that the real turn was not memory-augmented by ChimeraMemory.

Use `memory_diagnose(mode="harness")` to inspect active MCP/harness leases when
diagnosing service-mode conflicts. Same-host leases whose process IDs are no
longer alive are ignored for active-conflict warnings; real live concurrent
processes still produce warning-only diagnostics.

On the `codex` MCP surface with no persona configured, read-oriented memory
tools fail closed instead of falling back to all-memory recall. `scope=all` is
rejected, and `scope=auto` or `scope=project` requires
`CHIMERA_MEMORY_PROJECT_ID` or an explicit `project_id`; use `scope=global` for
global-only recall when project identity is not configured. MCP
`memory_context_pack`, `memory_live_retrieval_check`, and direct read tools
(`memory_search`, `memory_query`, `memory_recall`, `memory_stats`) pass the
active global root into retrieval, so outside-root global rows are not injected,
suggested, or counted as active Codex memory.

Use `--include-transcripts` only when project-scoped transcript snippets are
appropriate. CM filters transcript candidates to sessions whose `cwd` is inside
the configured project workspace. Supply `--project-root` when the workspace is
not already configured; `--cd` can also provide the Codex workspace for
`codex exec`. Transcript fallback writes `codex_transcript_context` recall
traces and `codex_transcript_context_*` audit events with sanitized item
metadata, so later diagnostics can distinguish curated-memory misses from
project transcript evidence.

Windows helper:

```powershell
.\install-codex.ps1 -PersonaId <ROLE/NAME> -PersonaRoot <PATH> -Yes
```

The helper creates or refreshes `.venv`, installs CM editable there, writes or
updates Codex MCP config, then runs `chimera-memory codex doctor` through the
venv Python.

For shared HTTP mode, `scripts/start-cm-http.ps1` defaults `-GlobalRoot` to
`~/.chimera-memory/global-memory`, creates it before startup, and exports it as
`CHIMERA_MEMORY_GLOBAL_ROOT` so the memory watcher sees global-memory files from
process start. If the port is already held by a ChimeraMemory server from a
different Python runtime, the starter refuses to silently reuse it; rerun with
`-Replace` only after confirming that stale process should be stopped. On
Windows, the listener may appear as the base Python executable when launched
through the repo venv shim; the starter accepts that process when the parent
executable or parent command line resolves to the repo `.venv` Python.

## Enhancement Helpers

```powershell
chimera-memory global inspect --json
chimera-memory global inspect --query "what should Codex remember?" --json
chimera-memory global inspect --global-root <DIR> --files --json
chimera-memory global seed --source <DIR> --json
chimera-memory global seed --source <DIR> --include TEAM_KNOWLEDGE.md --include "modes/**" --json
chimera-memory global seed --source <DIR> --global-root <DIR> --write --json
chimera-memory global reindex --json
chimera-memory global reindex --include TEAM_KNOWLEDGE.md --write --prune-missing --json
chimera-memory global review --json
chimera-memory global review --relative-path TEAM_KNOWLEDGE.md --json
chimera-memory global review --relative-path TEAM_KNOWLEDGE.md --action confirm --reviewer <NAME> --expect-body-sha256 <BODY_SHA256> --write --json
chimera-memory global promote --json
chimera-memory global promote --enable-auto-promotion --write --json
chimera-memory enhance provider-plan --json
chimera-memory enhance provider-smoke --expect-provider openai --expect-model gpt-5.3-codex-spark --json
chimera-memory enhance provider-smoke --live --http-sidecar --expect-provider openai --expect-model gpt-5.3-codex-spark --json
chimera-memory enhance oauth-list --json
chimera-memory enhance oauth-import --provider openai --source codex_cli --store "$env:USERPROFILE\.chimera-memory\auth.json" --json
chimera-memory enhance enqueue --file <MEMORY_PATH> --json
chimera-memory enhance authored-enqueue --persona <NAME> --payload <JSON> --json
chimera-memory enhance authored-write --personas-dir <DIR> --persona <NAME> --payload <YAML> --json
chimera-memory enhance authored-write --scope global --global-root <DIR> --payload <YAML> --write --json
chimera-memory enhance authored-write --scope project --project-id <ID> --project-root <DIR> --payload <YAML> --write --json
chimera-memory enhance dry-run --persona <NAME> --limit 10 --json
chimera-memory enhance worker-fake --persona <NAME> --limit 10 --json
chimera-memory enhance worker-doctor --runtime codex --json
chimera-memory enhance sidecar-run --endpoint http://127.0.0.1:8944/enhance --json
chimera-memory enhance serve-dry-run --port 8944
chimera-memory enhance serve-provider --port 8944
chimera-memory enhance grade-runs --input <RUN_JSONL> --json
```

`dry-run` and `serve-dry-run` are deterministic local paths. They should remain
safe without provider tokens.
`worker-doctor --json` is also a safe diagnostics path: it redacts absolute
paths and launch argv, reports only file roles/existence/worker-root containment,
and marks Codex/Claude readiness false when copied auth or credentials are
missing.
`provider-plan` is body-safe: it hides credential refs and token values, and it
now recommends the explicit OpenAI/Codex OAuth import when Codex auth is present
but CM's OAuth store has no usable OpenAI credential.
`provider-smoke` is the repeatable safe proof path for provider-backed
enhancement readiness. Without `--live`, it verifies selected provider/model,
OAuth/ref presence, and invocation shape without a model call. With `--live
--http-sidecar`, it exercises an ephemeral local HTTP sidecar plus the resolving
provider client and returns only metadata shape/counts, never the smoke body,
credential ref, token value, provider stderr, or raw provider response text.
Enhancement job JSON receipts are path/body-safe on client-facing commands:
`enqueue`, `authored-enqueue`, `dry-run`, `worker-fake`, and nested authored
write `enrichment_job` receipts redact wrapped content and authored payload
bodies while preserving job id, status, provider/model, safe path labels,
fingerprints, and governance fields.

`global inspect` is read-only and reports configured global-root existence,
markdown file counts, indexed/default-available DB counts, unindexed root
markdown, indexed rows whose files are missing, target-root DB counts, and
path-safe counts/details for indexed global rows outside the inspected root.
Database counts distinguish default-available evidence from confirmed
instruction-grade files. The receipt also includes an `authority` summary for
filesystem frontmatter: evidence-enabled files, trusted instruction-grade files,
pending-review files, evidence-only reviews, and files requiring user
confirmation. It also runs a read-only memory guard scan over
global-root markdown and reports sanitized finding counts and relative paths
without echoing unsafe samples. Files with missing or unrecognized frontmatter
are reported as imported, pending, evidence-enabled, instruction-disabled, and
requiring confirmation. When review-gated global files are present, inspect
also includes body-safe `recommendations` from the global review queue, such as
listing the queue, inspecting the first target, previewing confirmation, writing
confirmation after review, running automated promotion, or marking the file
evidence-only.
When inspect sees indexed global rows outside the configured root, it says those
rows are excluded from active retrieval and recommends path-safe `--files`
inspection plus a dry-run active-root reindex preview instead of implying
automatic pruning or immediate write-mode repair.
Pass `--query <TEXT>` to run a read-only global context-pack smoke against an
in-memory copy of the selected DB. The `query_smoke` receipt reports returned,
raw, filtered, duplicate-filtered, and token counts plus safe card metadata
such as relative path, governance labels, score, and query-match profile. Misses
also include body-safe diagnostics that distinguish no scoped candidates,
quality-gate filtering, dedupe, and packing-stage gaps, plus matching
body-safe recommendations. When the quality gate filters candidates, diagnostics
also include safe candidate profiles with relative labels, governance flags,
scores, and query-term coverage so operators can decide whether to use more
specific terms or improve global `about`/`tags` metadata. Query-match profiles
may show matched term labels, but those labels are sanitized before JSON or text
display so credential-shaped prompt terms are not echoed. It
does not persist recall traces or audit rows and does not include memory bodies,
snippets, card text, prompts, raw DB paths, or raw root paths.
`global seed` is
dry-run-first and no-persona: it copies only markdown files from an explicit
source directory into the configured global memory root when `--write` is set,
skips hidden/cache/auth-style folders, and indexes copied files as
`memory_scope=global` unless `--no-index` is passed. Write mode first fails
closed on unresolved target conflicts unless `--overwrite` is supplied, then
runs the memory guard over selected files and fails closed on credential,
injection, or hidden-content findings; use `--no-guard` only for an intentional
compatibility import. Write mode also stamps missing or ambiguous global
governance frontmatter before indexing, making imported global files
evidence-only and pending review unless they already carry explicit confirmed
instruction-grade provenance; use `--no-stamp-governance` only for an
intentional compatibility import. Write mode also fails closed when a broad seed
would copy mixed shared/persona-style paths such as `roster/**`,
`relationships/**`, `image-feedback/**`, or `persona-*` files. Use repeatable
`--include` and `--exclude` relative globs to select only reviewed global files
from mixed source trees; broad globs such as `**/*.md` do not bypass the
mixed-source guard unless the include pattern names the mixed path itself. Use
`--allow-mixed-source` only for an intentional compatibility import where those
paths have already been reviewed as global-safe. These operator CLI helpers use
`CHIMERA_MEMORY_GLOBAL_ROOT` when set and otherwise fall back to
`~/.chimera-memory/global-memory`, matching Codex no-persona setup even when the
current shell did not inherit the sidecar environment. Inspect, seed, reindex,
and review receipts represent root and DB locations as names, provenance
labels, and short fingerprints rather than raw absolute paths; human inspect,
seed, reindex, and review output uses the same safe labels.
`global reindex` is the DB repair path for files already present in one global
root. It is dry-run by default, indexes only that root on `--write`, honors the
same include/exclude filters, and prunes stale global rows under that root only
when `--prune-missing` is also supplied. Reindex write mode uses the same memory
guard and safe governance stamp before indexing unless `--no-guard` or
`--no-stamp-governance` is supplied. Reindex receipts include safe root and DB
payloads plus the selected-file `authority` summary so dry runs show whether
selected files are evidence, trusted instruction-grade, pending, or confirmation-gated before
indexing/stamping. Stale-row pruning uses the resolved row path under the
selected root as the live authority for filter matching and receipt-relative
paths, so a drifted DB `relative_path` cannot hide a missing row from filtered
prune repair. Prune candidate receipts expose only `relative_path`, `name`, and
a short `path_fingerprint`, not the absolute stale row path. Inspect, files, and
query-smoke receipts collapse path-shaped stored DB `relative_path` values to
filename-only labels before returning them. Write-mode pruning
also removes file-owned side-table rows such as source refs, artifacts, entity
links, file edges, embeddings, FTS rows, and summaries, while preserving
trace/review/job history with `file_id` cleared. Write-mode seed/reindex
receipts are
non-OK when governance stamping reports errors, indexing reports errors, or
files are skipped from indexing, even if some filesystem writes already
completed. Files whose governance stamp fails are not indexed in that run.
For imported, non-`user_confirmed`/`auto_confirmed`, or originally non-global files, the
governance stamp forces `can_use_as_instruction: false` and
`requires_user_confirmation: true` even when legacy frontmatter claimed
otherwise; explicit global `user_confirmed` review or explicitly enabled
trusted automation that writes `auto_confirmed` provenance can clear the
confirmation gate.
`global promote` is the no-human promotion path. It is dry-run by default and
uses named automated trust policies such as `trusted_clean`; write mode requires
`--enable-auto-promotion` or `CHIMERA_MEMORY_GLOBAL_AUTO_PROMOTE=true`. Eligible
files are written, reindexed, and audited as `global_memory_auto_promoted`.
Generated, restricted, excluded, malformed, wrong-scope, missing-governance
under the strict policy, or guard-blocked files are skipped with body-safe
policy reasons instead of becoming instruction-grade memory.
`global review` lists pending global-root markdown plus files that need
governance repair, such as missing required policy keys, wrong memory scope,
parse errors, or unsafe instruction-grade state. Returned items include
sanitized `review_reasons`, reason-count summaries, governance flags, and
confirm-action guard preview counts, not memory bodies. Missing or unrecognized
frontmatter is treated as pending/untrusted evidence instead of default
instruction authority. Human-readable listings also include returned
root-relative review targets with per-file reasons,
indexed state, confirm-guard blocked counts, and body-safe recommendations for
listing the queue, inspecting the first matching target without body text,
previewing confirmation, writing confirmation after review, automated
promotion, marking a
file evidence-only, or previewing remediation actions. Queue
recommendations use the same guard-derived action guidance as action previews:
they include write commands only when the selected action can be written without
guard blockage, and fall back to preview-only remediation commands when
default-retrievable review actions would be blocked. Queue-level write
recommendations use a `<BODY_SHA256>` placeholder until target inspection or
preview supplies the real reviewed body hash. Each returned file also
carries `action_guidance`: a body-safe matrix showing which review actions can
be written without guard blockage, whether an action would keep the file
default-retrievable, and whether it promotes instruction use. Text output
summarizes this as `actions=...` on each review target. Use repeatable
`--reason <REASON>` to focus the listing on files
with a specific review blocker such as `pending_review`,
`missing_required_governance`, `non_global_scope`, or `confirm_guard_blocked`;
filtered receipts keep all-pending `summary` counts separate from
`matching_summary` and `returned_summary` counts. `confirm_guard_blocked`
surfaces files whose sanitized confirm-action preview would be blocked by the
memory guard, including otherwise confirmed instruction-grade files with unsafe
body content. Even when `--limit 0` returns no file rows, the receipt keeps the
path-safe `first_matching_relative_path` plus a body-safe
`first_matching_target` summary with review reasons, guard counts, indexed
state, and action guidance. This lets diagnostics such as Codex doctor emit
concrete inspect/confirm/evidence-only/remediation recommendations without
returning memory bodies or falling back to placeholder commands. With
`--relative-path` and
no `--action`, it inspects one target body-safely: the receipt includes
frontmatter keys, review reasons, indexed/default availability, guard status,
body hash, body length, and recommendations, but not memory body text. With
`--relative-path` and
`--action`, it previews a durable frontmatter review change; with
`--write --reviewer <NAME>`, it updates the markdown, reindexes the same file as
`memory_scope=global`, writes a review action row, and records an audit event.
Preview `preview_frontmatter` output keeps the reviewed frontmatter shape but
sanitizes string values for local paths and credential-like content; write-mode
frontmatter remains the canonical reviewed markdown.
Inspection and preview recommendations include `--expect-body-sha256 <HASH>`
when CM knows the reviewed body hash. Write-mode review actions require that
argument and fail closed before mutation when it is missing, invalid, or no
longer matches the reviewed body.
Malformed-frontmatter files can be remediated by review actions: the original
source text is preserved as markdown body under repaired review frontmatter and
reported through `source_parse_error`, not echoed in output. Review listings and
Codex doctor use the same preserved-body path for confirm-guard previews, so
unsafe malformed sources are counted without leaking their contents.
If the post-write index/review-audit step fails, CM attempts to restore the
original markdown and reports a `restore` receipt so the file and DB do not
silently drift.
`confirm` is the explicit manual path that promotes a global file to
instruction-grade use; `global promote` is the explicitly enabled automated
path that records `auto_confirmed` provenance. `evidence_only`,
`restrict_scope`, `reject`, and the other review actions are durable reviewed
decisions that keep the file out of instruction use.
Review actions are root-relative only and
preserve the markdown body. Review action receipts use the relative target plus
hashes and do not return the absolute target file path. Root-relative targets
with a leading slash, backslash, Windows drive or stream separator, `..`, or
control characters are rejected instead of normalized into a different file.
Targets under hidden, cache, auth, or other skipped corpus directories are also
rejected case-insensitively, matching global discovery/seeding boundaries.
Review action previews and
write failures include body-safe
recommendations derived from the same action-guidance matrix: clean previews
name the exact write command, while guard-blocked previews tell the operator not
to write that action and suggest remediation previews such as `reject`,
`restrict_scope`, `dispute`, or `supersede`. Human-readable review action output
reports sanitized review-guard required, blocked-file, and finding counts,
including failed writes. Write-mode review runs the memory guard before any
action that would leave the post-review file available to default global
retrieval; unsafe files can still be rejected, disputed, superseded, or
restricted out of default retrieval. Review availability uses the same
`exclude_from_default_search` key as retrieval/indexing.
Recommendation commands keep simple targets double-quoted for readability, but
shell-active names such as paths containing `$`, spaces, parentheses, or quotes
are emitted with PowerShell-safe single-quote escaping.
Write-mode `global seed`, `global reindex`, and `global review` record compact
audit events with counts or action metadata, root provenance, root fingerprints,
and affected relative paths, but not memory bodies or raw absolute roots.

`authored-write` defaults to persona scope for compatibility. Use
`--scope global` for no-persona global authored memory, or `--scope project`
for no-persona project memory. Global/project writes use the same structured
payload validation and review/provenance fields as persona writes.

## Testing

Full suite:

```powershell
python -m pytest
```

Focused test:

```powershell
python -m pytest tests/test_memory_enhancement_queue.py
```

## Operational Logs

The shared HTTP MCP server filters the benign Windows asyncio proactor
connection-reset record that can happen when a local client disconnects during
restart or request teardown. Other asyncio errors still log normally.

The shared MCP memory watcher monitors shared, global, and all configured
project memory roots. It also monitors the persona tree only when a persona is
explicitly scoped or the runtime is an unscoped legacy/admin aggregation run.
No-persona Codex/project runtimes skip persona-tree watches, and the watcher
handler rejects persona paths in that mode even if an unexpected event reaches
it. Use `CHIMERA_MEMORY_PROJECT_ROOTS` when one server should watch multiple
project memory roots.

Legacy standalone tests for indexing/search/parser/memory core:

```powershell
python tests/test_persona_scope.py
python tests/test_memory_watcher.py
python tests/test_indexer.py
python tests/test_search.py
python tests/test_parser.py
```

Compile touched runtime modules when refactoring imports:

```powershell
python -m py_compile chimera_memory/<module>.py
```

## Runtime Configuration

Common env/config keys:

- `TRANSCRIPT_DB_PATH`
- `TRANSCRIPT_JSONL_DIR`
- `MEMORY_ROOT`
- `TRANSCRIPT_PERSONA`
- `CHIMERA_CLIENT`
- `CHIMERA_PERSONA_ID`
- `CHIMERA_PERSONA_NAME`
- `CHIMERA_PERSONA_ROOT`
- `CHIMERA_PERSONAS_DIR`
- `CHIMERA_SHARED_ROOT`
- `CHIMERA_MEMORY_PERSONA_DB_ROOT`
- `CHIMERA_MEMORY_PROJECT_ROOTS` (multi-root watch + Codex cwd-scoped indexing)
- `CHIMERA_MEMORY_PREWARM_EMBEDDINGS` (override embedding model prewarm)
- `CHIMERA_MEMORY_PROFILE_EXPORT_ROOT` (allowed root for profile export writes)
- `CHIMERA_MEMORY_ENHANCEMENT_MAX_CALLS` / `CHIMERA_MEMORY_ENHANCEMENT_MAX_CALLS_WINDOW_SECONDS`
  (provider cost-cap burst count + rolling window)
- `CHIMERA_MEMORY_EMBEDDING_PROVIDER`
- `CHIMERA_MEMORY_FASTEMBED_CUDA`
- `CHIMERA_MEMORY_FASTEMBED_DEVICE_IDS`
- `CHIMERA_MEMORY_EMBEDDING_CPU_RESERVE_PERCENT`
- `CHIMERA_MEMORY_EMBEDDING_MAX_THREADS`
- `CHIMERA_MEMORY_EMBEDDING_PROGRESS_PATH`
- `CHIMERA_MEMORY_ENHANCEMENT_USE_MODELS_DEV_CATALOG`

Config is generated under `~/.chimera-memory/config.yaml`. Runtime DBs and auth
stores belong under user runtime directories, not in this repo.

## Git

Before finalizing code changes:

```powershell
git diff
git status --short
```
