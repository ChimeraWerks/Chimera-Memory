# Chimera Memory

**Perfect recall and cognitive memory for any agent harness.** A standalone MCP server that indexes session transcripts into queryable SQLite, adds a curated memory layer with semantic search and zone-based loading, and gives you tools for everything from "what did we talk about yesterday" to "which memories are stale and should decay."

Works with Claude Code, Codex CLI, and Hermes Agent. No required dependency on any other repo.

## What It Does

Modern coding agents write detailed session logs (JSONL files) every time you use them. Chimera Memory indexes those files into a local SQLite database, embeds them for semantic search, and layers a curated memory system on top so you can write memories as markdown + YAML frontmatter and query them through the same MCP interface.

```
Agent harness writes  →  JSONL files  →  ChimeraMemory indexes  →  SQLite + embeddings  →  You query via MCP
Your memory files     →  markdown+YAML →  ChimeraMemory indexes  →  FTS5 + zones          →  You query via MCP
```

**Two layers, one interface:**

- **Transcript layer** — everything the harness has ever said, heard, or tooled. Auto-indexed. Zero effort.
- **Curated memory layer** — markdown files you deliberately write (facts, episodes, procedural lessons). Opinionated structure. Importance scoring. Zones. Decay. Graph analysis. Optional.

Use whichever layer you want. Both are exposed through the same MCP server.

## Problems It Solves

- **No native query for transcripts.** Claude Code / Codex / Hermes write JSONL session logs but offer no recall API. Without indexing, "what did we discuss last Tuesday" requires opening files manually.
- **Context loss between sessions.** Agents forget across `/clear` and across days. A queryable transcript DB plus a curated memory layer gives an agent persistent recall.
- **Curated knowledge degrades silently.** Without decay, importance scoring, or graph analysis, written memories pile up; bad knowledge doesn't get penalized; outdated facts mix with current ones.
- **No principled "what loads on session start."** Without zones and importance scoring, you load too much (token waste) or too little (forgotten context).
- **Hidden secrets in transcripts.** Raw JSONL contains tokens, API keys, webhook URLs. A naive grep can leak. Sanitization at index time keeps the DB clean.

Chimera Memory addresses each.

## Quick Start

```bash
# Clone and install (editable mode = live source updates)
git clone https://github.com/ChimeraWerks/Chimera-Memory.git
cd Chimera-Memory
pip install -e .

# Index your existing sessions
chimera-memory backfill

# Run as MCP server
chimera-memory serve
# Or run one shared local HTTP MCP server and point Codex at its URL:
chimera-memory serve --transport streamable-http --host 127.0.0.1 --port 8765
```

On Windows, prefer the repo-local venv so CM does not depend on stale global
console shims:

```powershell
.\scripts\bootstrap-cm-venv.ps1
.\.venv\Scripts\python.exe -m chimera_memory.cli stats
.\scripts\start-cm-http.ps1 -Port 8766 -Bootstrap
```

On Windows, the one-file Codex setup path is:

```powershell
.\install-codex.ps1
```

It creates or refreshes `.venv`, installs CM editable there, writes the Codex
MCP config, asks whether to import past Codex sessions, optionally reuses a
provider login, runs doctor, and tells you to restart Codex.

`pip install -e .` creates the `chimera-memory` CLI on PATH and adds the Python package via `.pth` so any edit to source flows through immediately on next process spawn. No re-install needed for code changes; only dependency changes (new `pyproject.toml` requires) need a re-run.

## Integration Patterns (Cross-Runtime)

Chimera Memory works with three agent harnesses today, each with a slightly different "front door":

### Claude Code

Spawned as an MCP server. Wire it into your `.mcp.json`:

```json
{
  "mcpServers": {
    "chimera-memory": {
      "command": "chimera-memory",
      "args": ["serve"],
      "env": {
        "TRANSCRIPT_JSONL_DIR": "~/.claude/projects/YOUR-PROJECT/",
        "CHIMERA_MEMORY_EMBEDDING_PROVIDER": "auto",
        "CHIMERA_MEMORY_EMBEDDING_CPU_RESERVE_PERCENT": "20"
      }
    }
  }
}
```

CM auto-selects an ONNX GPU execution provider when the local ONNX Runtime exposes one, then falls back to CPU. Windows DirectML appears as `DmlExecutionProvider`; NVIDIA CUDA appears as `CUDAExecutionProvider`. FastEmbed CUDA installs can also be forced with `CHIMERA_MEMORY_FASTEMBED_CUDA=true`; pin devices with `CHIMERA_MEMORY_FASTEMBED_DEVICE_IDS=0` after constraining visibility with `CUDA_VISIBLE_DEVICES` when a specific NVIDIA card must be used. CPU fallback reserves 20% of logical cores by default, enforces ONNX thread env vars before model load, and adds a small duty-cycle pause between batches so first-run embedding does not monopolize the machine. Tune with `CHIMERA_MEMORY_EMBEDDING_PROVIDER=auto|gpu|cpu`, `CHIMERA_MEMORY_EMBEDDING_CPU_RESERVE_PERCENT=20`, or `CHIMERA_MEMORY_EMBEDDING_MAX_THREADS=<N>`.

Restart Claude Code and the tools appear as `mcp__chimera-memory__*`.

### Codex Desktop and CLI

Codex Desktop reads MCP servers from `~/.codex/config.toml`:

```toml
[mcp_servers."chimera-memory"]
command = "python"
args = ["-m", "chimera_memory.cli", "serve"]
startup_timeout_sec = 30

[mcp_servers."chimera-memory".env]
TRANSCRIPT_JSONL_DIR = "~/.codex/sessions/"
CHIMERA_CLIENT = "codex"
CHIMERA_MEMORY_PROJECT_ID = "your-repo"
CHIMERA_MEMORY_PROJECT_ROOT = "C:\\path\\to\\your-repo\\.chimera-memory"
CHIMERA_MEMORY_GLOBAL_ROOT = "~/.chimera-memory/global-memory"
CHIMERA_MEMORY_MCP_SURFACE = "codex"
```

Codex can run repo-scoped with no persona. In that mode CM searches global plus
current-project memory, writes authored memories under the configured project
root, uses the configured global root for no-persona global authored memory,
intentionally leaves persona identity env unset, and defaults to the
`codex` MCP surface so exact memory search/query and scoped live-retrieval
diagnostic tools remain available.
Project discovery honors an explicit `CHIMERA_MEMORY_PROJECT_ID` with the
single configured project root, even when the root folder name would derive a
different id.
The MCP server also publishes surface-aware memory-use instructions to clients:
on the Codex surface, use `memory_context_pack` for substantial work, topic
shifts, recall questions, and prior-context-sensitive decisions, then use
`memory_search`, `memory_query`, or `memory_recall` for scoped project/global
curated memory. Codex does not receive generic transcript recall MCP tools;
bounded project transcript fallback is opt-in through the `codex exec
--include-transcripts` wrapper path. These instructions guide tool use, but
they do not mechanically inject memory into Codex turns without a Codex-side
hook, wrapper, or harness.

For wrapper or hook experiments, use `codex context` to prefix a prompt with
scoped evidence only when current project/global memory survives the context-pack
quality gate. Returned cards include review/authority markers such as
`review=pending`, `evidence-only`, `needs-confirmation`, `lifecycle=stale`, and
`lifecycle=archived`; the Codex grounding rule treats those records as
unconfirmed or non-current leads, not settled instructions. Global
evidence is filtered to `--global-root`, then `CHIMERA_MEMORY_GLOBAL_ROOT`, then
CM's default `~/.chimera-memory/global-memory` root:

```bash
echo "what should Codex remember about this repo?" | chimera-memory codex context
```

For Codex CLI, `codex exec` can be launched through CM so the wrapped prompt is
sent to Codex over stdin instead of appearing in the child process command line:

```bash
chimera-memory codex exec --prompt-file prompt.txt --model gpt-5.3-codex-spark
chimera-memory codex exec --prompt-file prompt.txt --dry-run --json
```

Add `--include-transcripts` when Codex should also use bounded transcript
snippets from prior local Codex sessions in the same project workspace. Pass
`--project-root <repo-or-.chimera-memory>` when the workspace root is not already
configured; otherwise the CLI wrapper infers no-persona project id/root from
`--cd` or the current repo directory when safe.
Transcript fallback is project-scoped through session `cwd`; it does not search
all transcript history. For non-dry-run `--json`, CM reports return code and
stdout/stderr sizes by default; pass `--include-output` only when you explicitly
want raw Codex child output in the JSON receipt. Exec receipts include a
body-safe `delivery_proof` object that separates prompt construction, memory
injection into the wrapped prompt, subprocess stdin delivery, delivery-event
recording, and launch failure without including prompt text, memory bodies, raw
commands, or child output. On Windows, bare `codex` wrapper launches are
normalized to a launchable shim such as `codex.cmd` or `codex.exe` so Python
subprocesses do not trip over extensionless npm shims.

`chimera-memory codex doctor` reports MCP reachability, performs a local HTTP
MCP initialize identity check for shared sidecars, reports the latest CM health
snapshot plus freshness, the live sidecar runtime/provider profile when
available, enhancement provider smoke evidence, the latest context trace, and
the latest returned context trace. It warns when a
shared HTTP sidecar is reachable but is not ChimeraMemory, when a local HTTP
listener is owned by a different Python runtime than the doctor/repo runtime,
when the health snapshot is stale, when the sidecar is not running as
no-persona Codex project+global memory, or when the global memory root is
missing. Listener runtime diagnostics report only sanitized owner counts,
process names, and stale PIDs, not raw process commands. It also
reports the selected enhancement provider/model, credential-ref presence, and
OAuth-use boolean without making a model call or printing credential refs.
Doctor prefers the latest sidecar health `provider_profile` when present and
falls back to a local/config plan-mode smoke when no sidecar profile has been
recorded. Run `chimera-memory enhance provider-smoke --live --http-sidecar
--json` when live provider proof is needed. It also reports how many indexed global memory files
are available to default
retrieval, so an empty global corpus is visible without being treated as a setup
failure. When the
transcript DB is readable, `codex doctor` overlays live global corpus counts on
the latest health snapshot so a low-cadence snapshot cannot report stale empty
counts after the watcher has indexed global files. Those live counts separate
default-available evidence from confirmed instruction-grade global files, so
pending/review-gated memory is not mistaken for settled operating rules. If the
corpus is genuinely empty, the diagnostic points to adding/promoting global
memories or starting the sidecar with a populated global root. For no-persona
project memory, missing `CHIMERA_MEMORY_GLOBAL_ROOT` fails closed: existing
global DB rows are reported only as indexed rows without an active root, and the
global context smoke is skipped instead of using them to prove active global
memory. Doctor also checks the global review queue and reports sanitized
pending/reason counts plus confirm-guard blocked/finding counts, warning when a
pending global file would be blocked by instruction-grade confirmation. It also
runs an in-memory global context
smoke against indexed global metadata to verify whether the `codex context`
wrapper would return prompt evidence right now, without writing trace rows,
printing prompt text, or exposing memory bodies. It states the boundary plainly:
MCP tools are on-demand, while mechanical prompt evidence requires
`codex context`, `codex exec`, or another hook/harness. It also reports whether
the optional `chimera-memory` wrapper command resolves on PATH, because a
healthy HTTP MCP sidecar can still coexist with a missing or stale shell shim.
The JSON report includes a `context_delivery` receipt with generic context
traces, Codex context-builder traces, real `codex exec` post-run delivery
events, returned delivery traces, and the no-write global smoke result, so
diagnostics can separate "CM is healthy" from "Codex actually received memory
prompt evidence." `codex context` and `codex exec --dry-run` are prompt
construction evidence, not real delivery. For per-run proof,
`codex exec --receipt-only --json` exposes `delivery_proof.prompt_injected`,
`subprocess_stdin_delivered`, and `real_delivery_recorded` as separate
booleans. When the global context smoke returns
evidence but no real delivery exists yet, doctor recommends proof and delivery
commands with `--scope global` so they do not depend on project-id inference
from the current shell directory. If `codex exec` fails before Codex
launches, CM records a sanitized `codex_prompt_delivery_failed` event so doctor
and traces can report a current failed delivery attempt separately from both
prompt construction and successful real delivery. Real exec delivery also gets a
recency receipt so an old successful wrapper run is not mistaken for fresh
prompt evidence in the current work session. If the no-write global smoke can
retrieve memory but the latest real Codex delivery returned zero cards, doctor
warns that the real turn was not memory-augmented by ChimeraMemory. Use
`chimera-memory codex traces`
for a recent sanitized trace list that classifies each context row as prompt
construction, diagnostic smoke, generic context trace, failed `codex exec`
delivery, or real `codex exec` delivery without printing prompt text, memory
bodies, raw trace payloads, or raw paths. The selected trace DB is reported as a
path-safe payload with name, provenance, and fingerprint instead of an absolute
path. Trace receipts include sanitized request scope metadata and returned memory
scope counts, such as `returned_scopes=global=1`; when the latest returned prompt
construction contains only global memory, no-real-delivery recommendations use
`--scope global`. Use `--kind failed`, `--kind real`, `--kind prompt`,
`--kind diagnostic`, or `--kind context` to inspect one delivery state directly.
Filtered views still inspect the unfiltered latest delivery attempt, so an old
failed row does not keep recommending delivery after a newer real wrapper
delivery succeeds.

On the Codex MCP surface, no-persona project/global mode rejects explicit
`persona` arguments and env-derived `TRANSCRIPT_PERSONA` identity for memory
reads, stats, context packs, live retrieval, authored writes, and persona
scope attempts. Use a non-Codex persona MCP surface for persona-private memory.
The Codex surface does not register the persona-facing `memory_review` queue or
persona-source `memory_promote_snapshot`; use `chimera-memory global review` for
no-persona global-root review.
Codex `memory_diagnose` is also limited to safe project/global diagnostics:
tools, stats, context, provider plan, worker/health, guard, and whereami.
Persona/admin diagnose modes such as zones, traces, audit, harness, gaps, and
consolidation are rejected on the Codex surface.

Hooks should prefer stdin or `--prompt-file <PATH>` instead of putting prompt
text in argv. Use `--previous-context-file <PATH>` with `--no-force` when the
hook tracks a prior turn/topic and wants topic-shift gating. The command emits
the original prompt unchanged on a miss. It supports only `auto`, `project`, and
`global` scopes; `auto` and `project` fail closed unless `--project-id`,
`CHIMERA_MEMORY_PROJECT_ID`, or a configured project root resolves a project id.
The CLI wrapper can also infer no-persona project id/root from `--project-root`,
`--cd`, or the current repo directory when safe. It intentionally has no persona
mode. Use `--receipt-only --json` to verify scope, counts, and trace ids without
printing prompt text or memory snippets.

If the `chimera-memory` shim on PATH is unavailable or stale, use
`--command "python -m chimera_memory.cli"` with `codex template` or
`codex install`; the generated config will split that into a Codex-safe command
plus args.

Check the wiring without exposing raw environment values:

```bash
chimera-memory codex doctor
```

The doctor verifies that the Codex MCP config exists, the `chimera-memory`
server entry is present, the command resolves, `serve` is passed, and the Codex
parser is selected with `CHIMERA_CLIENT=codex`.
It also shows whether runtime fields are explicit or derived, and summarizes the
latest CM health snapshot and live runtime profile when a transcript database is
available.

Write or update the Codex MCP config directly:

```bash
chimera-memory codex install --project-id Chimera-Memory --project-root "$PWD/.chimera-memory"
```

The installer preserves other MCP servers, writes a backup before changing an
existing config, asks whether to import historical Codex sessions, and stores
that choice as `CHIMERA_MEMORY_IMPORT_HISTORY`.
It can also set a provider preference and explicitly reuse an existing login:

```bash
chimera-memory codex install --project-id Chimera-Memory --provider openai --reuse-provider-login
```

Provider reuse is never implicit. When requested, the installer imports into
CM's local auth store and prints only a safe receipt.

Generate a safe config template without reading or modifying your live Codex
config:

```bash
chimera-memory codex template --project-id Chimera-Memory --project-root "$PWD/.chimera-memory"
```

Add persona identity fields only when you want persona-scoped Codex indexing:

```bash
chimera-memory codex template \
  --persona asa \
  --persona-id developer/asa \
  --persona-name asa \
  --persona-root "$CHIMERA_AGENCY_ROOT/personas/developer/asa" \
  --personas-dir "$CHIMERA_AGENCY_ROOT/personas" \
  --shared-root "$CHIMERA_AGENCY_ROOT/shared"
```

Persona profiles can also include `--project-id` and `--project-root` when the
same Codex session should recall persona, current-project, and global memory.

The template command prints JSON only. The install and doctor commands target
`~/.codex/config.toml` by default and still accept a legacy `mcp_servers.json`
path via `--config`. They do not include secrets or OAuth tokens.

### Hermes Agent

Hermes supports two integration modes simultaneously:

1. **As an MCP server** (same as Claude Code / Codex). Lives in `<HERMES_HOME>/config.yaml` under `mcp_servers.chimera-memory`.
2. **As a native memory provider** via plugin filesystem symlink at `<HERMES_HOME>/plugins/chimera_memory` plus `memory.provider: chimera_memory` in `config.yaml`. This is Hermes's first-class memory backend — used during agent turns for live recall, replacing or supplementing Honcho.

The plugin path uses a filesystem **symlink** to the source repo, so source edits flow through. Different mechanism from Claude Code's pip-install pattern (Hermes scans a directory, Claude Code spawns a CLI), same outcome.

### Via PersonifyAgents Installer (Automated)

PA bundles three handlers that wire Chimera Memory into any of the three runtimes deterministically:

```bash
# Wire CM as a Hermes memory provider (plugin symlink + config.yaml mutation)
personifyagents install apply \
  --runtime hermes \
  --feature chimera_memory.hermes_provider \
  --hermes-home /path/to/hermes-home \
  --chimera-memory-repo <repo-root> \
  --mode symlink \
  --yes

# Wire CM as an MCP server in any runtime's config
personifyagents install apply \
  --runtime claude_code \
  --feature chimera_memory.mcp_server \
  --runtime-home /path/to/claude-project \
  --yes

# Install a transcript backfill helper script (calls chimera-memory backfill on schedule)
personifyagents install apply \
  --runtime hermes \
  --feature chimera_memory.transcript_backfill_helper \
  --persona <persona-name> \
  --yes
```

Each PA apply writes a backup, a receipt, and updates the install-state ledger ... fully audited and reversible. PA assumes `chimera-memory` is already on PATH (it doesn't pip-install the binary itself; that's a separate concern).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Your Machine                            │
│                                                              │
│  Agent harness  ──writes──►  JSONL Session Files             │
│                                 │                            │
│  Your Memory   ──writes──►  Markdown + YAML files            │
│                                 │                            │
│                         ┌───────▼────────┐                   │
│                         │   Indexer      │  watchdog +       │
│                         │                │  poll safety      │
│                         └───────┬────────┘                   │
│                                 │                            │
│                         ┌───────▼────────┐                   │
│                         │   Sanitizer    │  secret +         │
│                         │                │  injection scan   │
│                         └───────┬────────┘                   │
│                                 │                            │
│                         ┌───────▼────────┐                   │
│                         │  SQLite + FTS5 │  WAL mode         │
│                         │  + embeddings  │  bge-small-en     │
│                         └───────┬────────┘                   │
│                                 │                            │
│                         ┌───────▼────────┐                   │
│                         │ Cognitive Layer│  decay, surprise, │
│                         │                │  zones, gaps      │
│                         └───────┬────────┘                   │
│                                 │                            │
│                  ┌──────────────┴──────────────┐             │
│                  │                             │             │
│             MCP Server                         CLI           │
│        (local memory tools)                (setup + query)   │
└─────────────────────────────────────────────────────────────┘
```

## MCP Tools

### Transcript Layer (everything the harness wrote)

Claude Code, Codex Desktop/CLI, and Hermes Agent are first-class transcript
sources with native parsers. The active harness is auto-identified (see Harness
Detection below), so Claude `~/.claude/projects` logs, Codex `~/.codex/sessions`
rollouts, and Hermes `~/.hermes/profiles/<persona>/sessions/session_*.json` files
are each discovered and parsed correctly without per-launch wiring. Two Hermes
modes are supported: Hermes running *inside* Claude Code writes Claude-format
JSONL (indexed via the Claude parser, auto-detected as `claude-code`), and the
standalone Hermes agent writes per-persona `session_*.json` files (indexed via the
native Hermes parser when `CHIMERA_CLIENT=hermes` and a persona are set). Hermes
also integrates as an MCP server and memory provider.

The `discord_*` tools below are legacy compatibility helpers for Discord-shaped
transcript rows and older imports; they are not required for Codex Desktop/CLI
operation and do not imply that a Discord runtime is active.

#### Harness Detection

ChimeraMemory identifies the active harness so indexing finds the right session
directory and parser. Precedence (each step only fills what the previous left
unset; explicit overrides always win):

1. Explicit `CHIMERA_CLIENT` (`claude`/`codex`/`hermes`) / `TRANSCRIPT_JSONL_DIR`
   (the dir shape is recognized: `.codex/sessions`, `.claude/projects`,
   `.hermes/profiles/<persona>/sessions`).
2. Process-injected "currently running" env signals (`CLAUDECODE` → Claude Code,
   `CODEX_SANDBOX` → Codex). Install-location vars like `HERMES_HOME`/`CODEX_HOME`
   are deliberately **not** used — they persist in every shell and would mislabel.
3. On-disk session-directory signature (a Codex `~/.codex/sessions` tree).
4. Per-file JSONL content sniffing at index time, so a Codex rollout is never
   silently parsed as Claude (and vice-versa) even if the label is wrong.
5. Default: Claude Code (historical behavior).

Discovery is parser-aware: Claude/Codex use `*.jsonl`, Hermes uses
`session_*.json`. Standalone Hermes is **persona-scoped** — set `CHIMERA_CLIENT=hermes`
plus a persona (`CHIMERA_PERSONA_NAME`/`TRANSCRIPT_PERSONA`) so CM reads only that
persona's `~/.hermes/profiles/<persona>/sessions`, never across personas.

| Tool | What it does |
|------|-------------|
| `discord_recall_index` | Compact search index (~100 tokens/result). **Use this first.** Returns ID, timestamp, author, 80-char preview. |
| `discord_detail` | Fetch full content for specific entry IDs from the index. Used after `discord_recall_index`. |
| `discord_recall` | Direct full-content search. Heavier than the index flow. Use when you need everything at once. |
| `semantic_search` | Hybrid FTS5 + vector search via Reciprocal Rank Fusion. Finds "car" when you search "vehicle." |
| `session_list` | Browse sessions with dates, durations, dispositions, persona filters. |
| `transcript_stats` | Entry count, session count, DB size, last entry timestamp, breakdowns by type and source. |
| `transcript_backfill` | Index all historical JSONL files. Safe to re-run (skips unchanged via MD5). |
| `embed_transcripts` | Generate embeddings for entries that don't have them. Useful for manual catch-up; `serve` also runs a bounded local embedding worker by default. |

**Recommended legacy Discord-row recall workflow** (3-10x token savings vs direct recall):
1. `discord_recall_index(search="topic")` — scan previews
2. Pick relevant IDs
3. `discord_detail(ids=[...])` — get full content only for those

For current Codex Desktop/CLI work, prefer scoped curated-memory tools
(`memory_context_pack`, `memory_search`, `memory_query`, `memory_recall`) and
`semantic_search` / `session_list` for transcript history when exposed by the
selected MCP surface.

### Curated Memory Layer (markdown files you write)

| Tool | What it does |
|------|-------------|
| `memory_stats` | Scoped corpus overview. Excludes synthesis, restricted, blocked-lifecycle, and non-evidence rows by default. |
| `memory_context_pack` | Hermes-style turn broker. Builds a fenced, token-capped pack of 3-7 scoped memory cards for harness pre-turn injection. |
| `memory_search` | FTS5 full-text search across scoped memory files. Excludes restricted, blocked-lifecycle, and non-evidence rows by default. Records sanitized recall traces with total-before-limit counts. |
| `memory_recall` | Semantic similarity search via embeddings. Use for fuzzy/conceptual queries. Filters low-similarity, low-coverage, restricted, blocked, and non-evidence noise by default; lower `min_similarity` only for diagnostics. |
| `memory_query` | Structured filter by type, importance, status, tags, about field. Excludes restricted, blocked-lifecycle, and non-evidence rows by default. Records sanitized recall traces with total-before-limit counts. |
| `memory_source_refs` / `memory_artifacts` | Provenance metadata lookups. Full-surface tools; scoped and evidence-safe by default, with explicit restricted/blocked/synthesis opt-ins. MCP text redacts local path-shaped URIs to a filename plus fingerprint; lower-level query APIs keep stored URI values for internal review/debug use. |
| `memory_guard` | Scan text for credentials, injection patterns, invisible unicode before persisting. |
| `memory_gaps` | Graph analysis. Finds disconnected memory clusters and isolated files. |
| `memory_entity_index` | Build the local entity graph from indexed memory frontmatter and tags. Enhancement results can add links too. |
| `memory_entity_query` | Query entities, shared-file connections, or explicit typed entity edges. |
| `memory_edge_upsert` | Create or reinforce a typed reasoning edge between two memory files. |
| `memory_edge_query` | Query memory-to-memory reasoning edges such as supports or supersedes. |
| `memory_edge_temporal_sweep` | Expire current memory edges whose validity inputs are stale. |
| `memory_pyramid_summary_build` | Build deterministic chunk, section, and document summaries for an indexed memory file. |
| `memory_pyramid_summary_query` | Query multi-resolution summaries for long imported memories. |
| `memory_import_chatgpt_export` | Plan or write governed memories from a ChatGPT `conversations.json` export, with optional pyramid summaries. |
| `memory_import_obsidian_vault` | Plan or write governed memories from an Obsidian markdown vault directory or zip export. |
| `memory_import_gmail_mbox` | Plan or write restricted, evidence-only memories from Gmail / Google Takeout mbox exports. |
| `memory_import_perplexity_export` | Plan or write governed memories from Perplexity markdown, text, or JSON exports. |
| `memory_import_grok_export` | Plan or write governed memories from Grok markdown, text, JSON, or JSONL exports. |
| `memory_import_twitter_archive` | Plan or write governed tweet/status memories from X/Twitter archive exports. |
| `memory_import_instagram_export` | Plan or write restricted, evidence-only memories from Instagram export files. |
| `memory_import_google_activity_export` | Plan or write restricted, evidence-only memories from Google Activity / Takeout exports. |
| `memory_import_atom_blogger_export` | Plan or write governed memories from Atom / Blogger XML exports. |
| `memory_profile_export` | Plan or write portable USER.md / SOUL.md / HEARTBEAT.md / JSON context artifacts from reviewed memory. |
| `memory_reindex` | Force re-scan after bulk file changes. |
| `memory_mark_failure` | Flag a memory that led to wrong advice. Penalizes its zone score. |
| `memory_consolidation_report` | Dry-run analysis: what would be decayed, staled, or archived. |

### Governance and Enhancement

| Tool | What it does |
|------|-------------|
| `memory_recall_trace_query` | Inspect recent recall traces and optional returned items. Returned item paths are display-safe labels plus fingerprints, not raw local filesystem paths. Useful for tuning retrieval quality. |
| `memory_audit_query` | Inspect memory audit events such as recall, review, and enhancement operations. Returned target IDs and path-like payload fields are display-safe labels/fingerprints for local paths while preserving non-local URIs and opaque IDs. Sensitive prompt/body/command/process-output/credential-like payload fields are returned as redaction receipts. |
| `memory_live_retrieval_check` | Dry-run scoped proactive recall on topic shifts, quality-filtered for weak broad matches, silent on miss and logged for tuning. Codex project mode exposes this read-only checker. |
| `memory_review_pending` | List generated or restricted memories that need review before instructional use. |
| `memory_review_action` | Confirm, restrict, reject, stale, merge, dispute, or supersede a memory review item. |
| `memory_auto_capture_session_close` | Plan or write an evidence-only session-close memory with ACT NOW items. |
| `memory_enhancement_provider_plan` | Show the selected enhancement provider and budget caps without exposing credential refs. |
| `memory_enhancement_enqueue` | Queue an indexed memory file for metadata enrichment. |
| `memory_enhancement_dry_run` | Process queued enhancement jobs with deterministic local metadata. No model call required. |
| `memory_worker_claim_next` | Worker-surface tool. Atomically claim one pending enhancement job and return a strict JSON worker payload. |
| `memory_worker_submit_result` | Worker-surface tool. Submit strict JSON output for a claimed job; CM validates before writeback. |
| `memory_worker_heartbeat` | Worker-surface tool. Record liveness for a supervised memory worker. |
| `memory_worker_budget` | Worker-surface tool. Return shared provider-governor budget status before work is claimed. |

### Cognitive Analytics

| Tool | What it does |
|------|-------------|
| `memory_zones` | Assigns every memory to CORE/ACTIVE/PASSIVE/ARCHIVE tier based on importance, frequency, recency, and failures. Drives "what loads automatically." |
| `memory_decay_report` | Per-type exponential decay rates. Procedural decays slowest (load-bearing), opinions fastest. |
| `memory_surprise` | Novelty scoring via nearest-neighbor embedding distance. High surprise = unique. Low = redundant. |

## Memory Enhancement (Optional Sidecar)

The memory enhancement system extracts structured metadata (topics, entities, action items) from your curated memory files using a configurable LLM provider. Output lives in a separate database table for inspection ... it does **not** edit memory files, change agent behavior, or get treated as instructions until you explicitly promote it.

Worker protocol note: CM also exposes a restricted `worker` MCP surface with
`memory_worker_claim_next`, `memory_worker_submit_result`,
`memory_worker_heartbeat`, and `memory_worker_budget`. This is the deterministic
protocol layer for supervised CLI enhancement workers. `chimera-memory enhance
worker-fake` exercises the same claim/budget/submit protocol with deterministic
local metadata for tests and operator smoke checks.

CLI worker supervision is available as an explicit opt-in by setting
`CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE=cli_worker`. Codex launches bounded
`codex exec` worker passes with a worker-local `AGENTS.md`; Claude Code
launches bounded `claude --print` worker passes with a worker-local
`CLAUDE.md`; Antigravity CLI launches bounded `agy --print` worker passes with
worker-local `AGENTS.md` and `GEMINI.md`. All use worker-only MCP config and
are disabled by default; dry-run remains the no-provider floor. Codex worker
passes use bypass mode by default because current `codex exec` cancels worker
MCP calls otherwise; set
`CHIMERA_MEMORY_CODEX_WORKER_BYPASS_APPROVALS_AND_SANDBOX=false` to disable it
when Codex supports non-interactive MCP approvals cleanly.

The CLI supervisor checks the local enhancement queue and provider budget before
launching any provider CLI. Empty queues produce an idle heartbeat only; they do
not launch Codex, Claude Code, or Antigravity just to poll for work.

Run `chimera-memory enhance worker-doctor --runtime codex --init` or
`--runtime claude --init` or `--runtime agy --init` to create and inspect the
generated worker files without launching the provider CLI.
Doctor JSON is path-safe and argv-redacted: it reports file roles, existence,
worker-root containment, credential presence, and a command profile instead of
absolute local paths or raw launch commands. Codex worker readiness requires the
worker-local copied `auth.json`; Claude readiness requires worker-local copied
credentials.

### What It Does

When a memory file is written or updated AND enhancement auto-enqueue is enabled for that persona (via `CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE=true` plus the persona-allowlist env var), the indexer enqueues it for enhancement. Legacy shadow mode (`CHIMERA_MEMORY_ENHANCEMENT_SHADOW_MODE=true`) still enables the same queue for comparison-only pilots. A sidecar worker pulls jobs, sends them to the configured provider, and stores extracted metadata as generated, pending-review evidence. Inspect the per-job outcome via `memory_enhancement_shadow_report` (status, type inference, sensitivity escalation, topic/entity overlap with frontmatter tags). The separate `memory_review_pending` / `memory_review_action` tools govern memory files themselves, not enhancement output.

### Provider Support

Configurable provider order:

- **OpenAI** (`gpt-5.4` and similar)
- **Anthropic** (Claude OAuth via Hermes-pattern device-code flow)
- **Google** (Code Assist via OAuth PKCE + loopback HTTP server)
- **Local** (Kobold, LM Studio, Ollama, OpenAI-compatible endpoints)
- **Dry run** (deterministic local fallback ... no model call required)

OAuth flows mirror Hermes's call patterns at the wire level: dynamic Claude Code version detection (queries `claude --version` with a fallback constant), exact UA strings (`claude-cli/{version} (external, cli)`), Content-Type that matches the actual request body shape, full beta-set headers.

### Stage Gates

The enhancement system is staged for safety. Each stage explicitly does not unlock the next:

| Stage | What's enabled | What's NOT enabled |
|-------|---------------|--------------------|
| Stage 0 (manual smoke) | Operator manually triggers enhancement via CLI (`chimera-memory enhance enqueue --file X`) for development inspection | Auto-enqueue on memory writes, file edits, behavior changes |
| Stage 1 (DB metadata only) | Writes extracted metadata to a dedicated DB table for inspection | Memory file edits, persona behavior changes, instruction-grade use |
| Stage 2 (writeback) | Gated on rename normalization + single-slot variance follow-ups | Default-on behavior |
| Stage 3 (default-on) | Gated on type-aware summary contract + per-type budget rules | — |

Set `CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE=true` and `CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE_PERSONAS=<persona>` to enable production auto-enqueue for a specific persona's writes. Set `CHIMERA_MEMORY_ENHANCEMENT_SHADOW_MODE=true` and `CHIMERA_MEMORY_ENHANCEMENT_SHADOW_PERSONAS=<persona>` only when intentionally running comparison-only shadow pilots.

### Credential Governance

When the enhancement system uses cloud providers, six clauses govern credential handling:

1. **Credential discovery can be automatic; credential consumption must be configured and auditable.** Auto-detect of existing credentials is fine; unattended use is allowed only after a credential reference, OAuth import, or provider affinity is explicitly configured and recorded.
2. **Pilot/local: reuse is acceptable after explicit configuration + provenance.** Borrowed credentials need recorded `credential_source=...` metadata; they do not need a runtime prompt once configured.
3. **Daemon/default-on: purpose-specific credential unless ToS + scopes are clean.** Long-running automation uses its own credential, not a borrowed one.
4. **Silent implicit import dies.** Do not copy or consume newly discovered credentials without an explicit config/import step; already configured refs may run unattended.
5. **Local provenance is forensic, not isolating.** Recording the credential source helps debugging but doesn't isolate ... provider-side logs still collapse under one auth identity.
6. **Borrowed auth must be revocable without damaging the source tool, or it stays pilot-only.** Test for graduation: can you kill the borrowed-auth consumer without breaking the source?

### Sensitivity-Tier Governance

Enhancement output is scored on a sensitivity scale (`standard` / `restricted` / `confidential`) via a deterministic gate. Patterns include:

- **Literal prefixes:** `sk-ant-`, `MTQ`, Discord webhook URLs, `ghp_`/`gho_`/`ghs_`/`ghr_`, `AKIA`, `ASIA`
- **Keywords:** oauth, refresh-token, access-token, api-key, secret, password, bearer, webhook, private-key, credential
- **Dual-scan:** both model output AND original sidecar request context get scanned

Restricted memories are flagged `can_use_as_instruction: false` and require explicit review via `memory_review_action` before they're allowed to influence agent behavior.

## Memory File Format

Markdown + YAML frontmatter:

```markdown
---
type: procedural        # episodic | semantic | procedural | entity | reflection | social
importance: 8           # 1-10
created: 2026-04-06
last_accessed: 2026-04-06
access_count: 0
tags: [topic, topic]
status: active
---

Natural language content. How you'd actually think about it.
```

The frontmatter drives everything — importance feeds zone scoring, access_count tracks reinforcement, tags enable graph analysis, failure_count penalizes bad knowledge.

## Zone-Based Loading

```
CORE     (≥0.70)   load automatically on session start
ACTIVE   (≥0.55)   load when tags match current task
PASSIVE  (≥0.30)   loaded only on direct query
ARCHIVE  (<0.30)   never auto-loaded, still queryable
```

**Scoring formula:**
```
score = confidence·0.25 + frequency·0.20 + recency·0.15
      + context_match·0.20 + spec_alignment·0.15
      - failure_penalty·0.25
```

Access reinforcement happens automatically on every `memory_search` or `memory_recall` hit. Frequency grows naturally through use. Failure marks (`memory_mark_failure`) penalize bad memories so they fall down the zones over time.

## How It Works

### JSONL Parsing

Each agent harness stores sessions as JSONL — one JSON object per line. Each object is a user message, assistant response, tool call, system event, attachment, or platform-specific event (e.g. Discord). The parser classifies each entry:

| Entry Type | What It Captures | Indexed Content |
|-----------|-----------------|-----------------|
| `discord_inbound` | Messages received from Discord | Full message text |
| `discord_outbound` | Messages sent to Discord | Full message text |
| `user_message` | CLI user input | Full text |
| `assistant_message` | Agent responses | Full text (no thinking blocks) |
| `tool_call` | Tool invocations (Read, Bash, etc.) | Metadata only |
| `tool_result` | Tool output | Metadata only |
| `system` | System events, notifications | Metadata only |
| `attachment` | File attachments | Path and metadata |

**Design choice:** Conversation content gets full-text indexed and embedded. Tool I/O gets metadata only. This keeps the DB lean and search results relevant — you won't get 50 `tool_result` hits when you search for "umbrella."

### Content Sanitization

Every entry passes through a sanitizer that detects and redacts:

- API keys (`sk-ant-*`, `sk-*`, `ghp_*`, AWS keys)
- Bot tokens (Discord, Slack)
- Webhook URLs
- Bearer tokens
- Passwords and secrets in env-var format
- Private keys
- Invisible unicode (injection vector)

Redacted content is replaced with `<REDACTED:type>` markers. The original never touches disk.

### Embeddings

Semantic search uses `bge-small-en-v1.5` via [fastembed](https://github.com/qdrant/fastembed) — a 23MB ONNX model that runs locally, no API calls. First run downloads the model (~80MB including runtime). Subsequent runs are offline.

Embeddings are only generated for conversation content (user messages, assistant messages, Discord messages). Tool results and system entries are skipped — they'd just add noise.

`chimera-memory serve` starts maintenance after the first MCP `tools/list` response by default, so MCP readiness is not gated on transcript catch-up, embedding model load, or health checks. Set `CHIMERA_MEMORY_STARTUP_BOOTSTRAP=background` for the older immediate background launch, `sync` for blocking startup, or `false` to disable startup maintenance.

Codex command-based MCP starts one stdio server per active thread/session. To avoid many CM Python processes while multitasking, run a single local HTTP MCP server:

```powershell
chimera-memory serve --transport streamable-http --host 127.0.0.1 --port 8765
```

For a Windows per-user service-style launch from this repo's `.venv`, use:

```powershell
.\scripts\start-cm-http.ps1 -Port 8766 -Bootstrap
.\scripts\install-cm-http-autostart.ps1 -Port 8766 -RunNow
```

The starter defaults to no-persona Codex project mode for this repo and creates
both `<repo>/.chimera-memory` and `~/.chimera-memory/global-memory` before the
watcher starts. Override with `-ProjectId`, `-ProjectRoot`, or `-GlobalRoot`
when hosting another repo/global-memory root. If the port is already occupied by
a ChimeraMemory server from a different Python runtime, the starter now refuses
to silently accept it; rerun with `-Replace` only after confirming the stale
process should be stopped.

Then configure Codex to use the shared URL instead of a `command`/`args` server:

```toml
[mcp_servers."chimera-memory"]
url = "http://127.0.0.1:8765/mcp"
startup_timeout_sec = 30
```

That leaves one CM server process for indexing, embeddings, health, and enhancement workers. Codex may still keep per-thread client-side helper processes, but they will not each spawn a full CM runtime.

`chimera-memory serve` starts a bounded local transcript-embedding worker by default once startup maintenance begins. It polls for unembedded conversation rows and processes a capped batch so new transcripts do not leave `semantic_search` stuck in keyword-only fallback. Tune with:

- `CHIMERA_MEMORY_TRANSCRIPT_EMBEDDING_WORKER=false` to disable the worker.
- `CHIMERA_MEMORY_STARTUP_BOOTSTRAP_DELAY_SECONDS=0.25` for the small post-readiness delay before maintenance starts.
- `CHIMERA_MEMORY_TRANSCRIPT_EMBED_INTERVAL_SECONDS=60` for the polling interval.
- `CHIMERA_MEMORY_TRANSCRIPT_EMBED_BATCH_SIZE=64` for fastembed batch size.
- `CHIMERA_MEMORY_TRANSCRIPT_EMBED_BATCH_LIMIT=1000` for the maximum rows per worker tick.
- `CHIMERA_MEMORY_EMBEDDING_PROVIDER=auto|gpu|cpu` to prefer GPU ONNX providers when installed.
- `CHIMERA_MEMORY_FASTEMBED_CUDA=true|false|auto` to force FastEmbed's CUDA path when `fastembed-gpu` is installed.
- `CHIMERA_MEMORY_FASTEMBED_DEVICE_IDS=0` to pin the visible CUDA device used by FastEmbed.
- `CHIMERA_MEMORY_EMBEDDING_CPU_RESERVE_PERCENT=20` to leave CPU headroom on fallback.
- `CHIMERA_MEMORY_EMBEDDING_PROGRESS_PATH=...` to move the live progress JSON file.

Each embedding run logs a realtime progress bar and writes live status to `~/.chimera-memory/embedding-progress.json`. Use `embed_transcripts` or `chimera-memory embed` for one-time historical catch-up if a DB has a large backlog from before the worker existed.

### Health Snapshots

`chimera-memory serve` also starts a low-cadence health worker by default. Every five minutes it records a `cm_health_snapshot` audit event and logs the overall status. The snapshot checks embedding backlog/staleness, enhancement queue age, provider drift, session rollup mismatches, duplicate message capture, worker startup state, latest success timestamps, a path-safe runtime profile for Codex/sidecar diagnostics, and a safe provider profile. The runtime profile includes global-memory root presence plus indexed/default-available global corpus counts, but not raw paths. The provider profile records selected provider/model plus credential-ref and user-OAuth booleans, but not credential refs or tokens. `codex doctor` uses the latest snapshot for runtime shape/provider evidence and overlays live DB global corpus counts when available so newly indexed global files are not hidden until the next snapshot.

Use `memory_diagnose(mode="health")` for a live health read. Tune with:

- `CHIMERA_MEMORY_HEALTH_WORKER=false` to disable the worker.
- `CHIMERA_MEMORY_HEALTH_INTERVAL_SECONDS=300` for the snapshot interval.

### Enhancement Worker

`chimera-memory serve` drains the enhancement queue by default with the deterministic local dry-run worker. That keeps shadow-enqueued memory metadata jobs from rotting while avoiding network calls, provider spend, or credential use. Provider-backed execution is explicit opt-in:

- `CHIMERA_MEMORY_ENHANCEMENT_WORKER=false` disables the worker.
- `CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE=true` queues changed memory files for enhancement.
- `CHIMERA_MEMORY_ENHANCEMENT_AUTO_ENQUEUE_PERSONAS=<persona>` allowlists personas for auto-enqueue.
- `CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE=dry_run` is the default.
- `CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE=cli_worker` uses a supervised Codex/Claude/Antigravity CLI worker.
- `CHIMERA_MEMORY_CLI_WORKER_RUNTIME=codex|claude|agy` selects the CLI runtime for `cli_worker`.
- `CHIMERA_MEMORY_CLI_WORKER_EFFORT=medium` sets the default reasoning effort for CLI workers that expose effort controls.
- `CHIMERA_MEMORY_CLI_WORKER_SESSION_MAX_TURNS=1` caps resumed CLI worker context before starting fresh again.
- `CHIMERA_MEMORY_CODEX_WORKER_MODEL=gpt-5.3-codex-spark` is the Codex worker default.
- `CHIMERA_MEMORY_CODEX_WORKER_EFFORT=low|medium|high|xhigh` overrides Codex worker effort.
- `CHIMERA_MEMORY_CLAUDE_WORKER_EFFORT=low|medium|high|xhigh|max` overrides Claude worker effort.
- `CHIMERA_MEMORY_CLAUDE_WORKER_MODEL=...` defaults to the memory-enhancement Haiku tier; Opus is rejected unless `CHIMERA_MEMORY_CLAUDE_WORKER_ALLOW_OPUS=true`.
- `CHIMERA_MEMORY_CODEX_BIN=...` overrides automatic Codex executable detection.
- `CHIMERA_MEMORY_CODEX_WORKER_AUTH_PATH=...` overrides the Codex auth file copied into the isolated worker home.
- `CHIMERA_MEMORY_CODEX_WORKER_BYPASS_APPROVALS_AND_SANDBOX=true` is the Codex worker default for non-interactive MCP calls.
- `chimera-memory enhance worker-doctor --runtime codex --init --json` verifies the copied worker auth and Spark command profile without printing raw paths or argv.
- `CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE=provider` remains the direct HTTP/provider fallback.
- `CHIMERA_MEMORY_ENHANCEMENT_WORKER_INTERVAL_SECONDS=60` controls polling.
- `CHIMERA_MEMORY_ENHANCEMENT_WORKER_LIMIT=10` controls jobs per tick.
- `CHIMERA_MEMORY_ENHANCEMENT_PER_MINUTE_CALL_CAP=30` caps shared provider calls per minute.
- `CHIMERA_MEMORY_ENHANCEMENT_DAILY_SOFT_CALL_CAP=5000` caps shared provider calls per day.
- `CHIMERA_MEMORY_ENHANCEMENT_MONTHLY_HARD_CALL_CAP=100000` caps shared provider calls per 30-day window.

Provider-backed transports share a SQLite usage ledger. The runner checks the
governor before claiming a job, so exhausted budgets leave work pending instead
of stranded in `running`. `dry_run` and local deterministic work do not consume
provider budget. Memory index files named `MEMORY.md` are excluded from
auto-enqueue, and same-fingerprint file updates are debounced so repeated
watcher events do not create duplicate provider jobs.

Provider login/import is exposed through safe CLI receipts:

```bash
chimera-memory enhance oauth-import --provider openai --source codex_cli --store "$HOME/.chimera-memory/auth.json"
chimera-memory enhance oauth-list
chimera-memory enhance provider-plan
chimera-memory enhance provider-smoke --expect-provider openai --expect-model gpt-5.3-codex-spark
chimera-memory enhance provider-smoke --live --http-sidecar --expect-provider openai --expect-model gpt-5.3-codex-spark --json
```

Credential values are never printed. `oauth-import` copies an existing provider
login into CM's local auth store after you invoke it explicitly; `oauth-list`
reports provider, transport, active status, and hashed refs only.
When OpenAI/Codex OAuth is visible but has not been imported into CM,
`provider-plan` returns a body-safe recommendation to run the explicit import
instead of reporting only `credential_missing`.
`provider-smoke` is the safe repeatable proof path: plan mode checks selected
provider/model, OAuth/ref presence, and invocation shape without a model call;
`--live --http-sidecar` exercises an ephemeral local enhancement sidecar and
the resolving provider client, returning only metadata shape/counts.
Enhancement CLI job receipts are also client-safe: queued job storage may keep
the raw local path and wrapped request body for workers, but `enqueue`,
`authored-enqueue`, `dry-run`, `worker-fake`, and nested authored-write
`enrichment_job` JSON receipts collapse paths to safe labels/fingerprints and
redact wrapped content, authored payload bodies, and content-derived metadata
fields not needed for status/governance.

### Hybrid Search (semantic_search)

`semantic_search` combines FTS5 keyword matching with vector similarity via Reciprocal Rank Fusion. Results are re-ranked by recency, session affinity, and content richness. Finds both exact matches and semantically similar content.

If embeddings aren't built yet, it falls back to keyword-only search automatically.

### Import Log (Incremental Indexing)

Every JSONL file is tracked with an MD5 hash. On restart or re-run:
- **Unchanged files** are skipped instantly
- **Modified files** (grew since last read) are re-indexed from the last position
- **New files** are indexed from scratch
- **Session rollups** are repaired from transcript rows so old zero-exchange or orphaned sessions become browseable automatically.

First backfill of 31 sessions (55MB JSONL): **~2 seconds.** Re-run: **~0.3 seconds.**

### Transcript Exclusions

Worker and supervisor logs can be excluded before parsing so they do not enter
normal transcript recall or semantic search. This is required for future
persistent CLI memory workers, whose own JSONL audit trail must not create a
self-referential enhancement loop.

- `CHIMERA_MEMORY_TRANSCRIPT_EXCLUDE_GLOBS` skips matching JSONL paths. Separate multiple patterns with `;`, `,`, or newlines.
- `CHIMERA_MEMORY_TRANSCRIPT_EXCLUDE_SESSION_IDS` skips JSONL files whose extracted session id matches one of the listed IDs.

Example:

```bash
CHIMERA_MEMORY_TRANSCRIPT_EXCLUDE_GLOBS="*/memory-workers/*.jsonl"
CHIMERA_MEMORY_TRANSCRIPT_EXCLUDE_SESSION_IDS="codex-memory-worker-1"
```

### Identity Cascade

Per-persona launches can now provide a minimal identity and let CM derive the rest. If `CHIMERA_PERSONA_ID=role/name` is set, CM derives `CHIMERA_PERSONA_NAME`, `TRANSCRIPT_PERSONA`, and the per-persona transcript DB path when explicit env/config values are absent. If `CHIMERA_PERSONA_ROOT` is also set, CM derives `CHIMERA_PERSONAS_DIR` and `CHIMERA_SHARED_ROOT`.

Historical transcript import is explicit setup state. `CHIMERA_MEMORY_IMPORT_HISTORY=true` keeps the startup backfill behavior; `false` marks existing JSONL files as already seen and only tails new content after CM starts.

Explicit env values still win. The cascade only fills blanks.

### Concurrency

- **WAL mode** — readers never block writers, writers never block readers
- **Retry with backoff** — automatic retry on `SQLITE_BUSY`
- **Tail-read pattern** — reads JSONL files the harness is actively writing to, without locking

## Performance

Tested on a real 31-session corpus:

| Metric | Result |
|--------|--------|
| Backfill (31 files, 55MB) | ~2s |
| Re-backfill (skip unchanged) | ~0.3s |
| Entries indexed | 19,500+ |
| Embeddings (5,600 entries) | ~4 min first time, then incremental |
| DB size | ~32 MB (with embeddings) |
| Chronological query | <10ms |
| FTS5 search | <15ms |
| Semantic search (hybrid) | ~50ms |
| DB integrity | ✓ |

SQLite handles databases up to 281 TB. At projected 12-month scale (~700K entries, ~3GB raw), indexed queries remain under 1ms.

## CLI Reference

```bash
chimera-memory serve              # Run MCP server (stdio)
chimera-memory serve --transport streamable-http --port 8765
chimera-memory backfill           # Index all historical sessions
chimera-memory backfill --jsonl-dir <DIR> --persona <NAME> --client claude|codex
chimera-memory embed              # Generate transcript embeddings with a live progress bar
chimera-memory embed --limit 500 --batch-size 64
chimera-memory stats              # Show database statistics
chimera-memory split-db           # Split a shared transcript DB into per-persona DBs
chimera-memory global inspect --json
chimera-memory global inspect --query "what should Codex remember?" --json
chimera-memory global inspect --global-root <DIR> --files --json
chimera-memory global seed --source <DIR> --json
chimera-memory global seed --source <DIR> --include TEAM_KNOWLEDGE.md --include "modes/**" --json
chimera-memory global seed --source <DIR> --global-root <DIR> --write --json
chimera-memory global seed --source <DIR> --allow-mixed-source --write --json
chimera-memory global reindex --json
chimera-memory global reindex --include TEAM_KNOWLEDGE.md --write --prune-missing --json
chimera-memory global review --json
chimera-memory global review --reason pending_review --json
chimera-memory global review --relative-path TEAM_KNOWLEDGE.md --json
chimera-memory global review --relative-path TEAM_KNOWLEDGE.md --action confirm --reviewer <NAME> --expect-body-sha256 <BODY_SHA256> --write --json
chimera-memory global promote --json
chimera-memory global promote --enable-auto-promotion --write --json
chimera-memory codex doctor       # Diagnose Codex MCP setup without printing env values
chimera-memory codex traces       # Inspect recent Codex context/delivery traces
chimera-memory codex traces --real-only --json
chimera-memory codex traces --kind failed --json
chimera-memory codex traces --since 2026-06-10T21:00:00Z
chimera-memory codex install      # Write/update Codex MCP setup with backup and import choice
chimera-memory codex install --project-id <ID> --project-root <DIR>
chimera-memory codex template --project-id <ID> --project-root <DIR>
chimera-memory codex context --prompt "prompt text"
chimera-memory codex context --prompt "prompt text" --receipt-only --json
chimera-memory codex context --project-id <ID> --prompt "prompt text"
chimera-memory codex context --project-id <ID> --prompt-file <PATH>
chimera-memory codex exec --prompt "prompt text" --dry-run --json
chimera-memory codex exec --prompt "prompt text" --dry-run --receipt-only --json
chimera-memory codex exec --project-id <ID> --prompt "prompt text" --dry-run --json
chimera-memory codex exec --project-id <ID> --prompt-file <PATH>
chimera-memory codex exec --project-id <ID> --project-root <DIR> --prompt-file <PATH> --include-transcripts
chimera-memory enhance provider-plan --json
chimera-memory enhance oauth-import --provider openai --source codex_cli
chimera-memory enhance oauth-list --json
chimera-memory enhance enqueue --file <MEMORY_PATH>
chimera-memory enhance dry-run --persona <NAME>
chimera-memory enhance sidecar-run --endpoint http://127.0.0.1:8944/enhance
chimera-memory enhance serve-dry-run --port 8944
```

`backfill` accepts `--client claude|codex` to use the right parser for the JSONL flavor (Claude Code and Codex CLI write structurally different JSONL).

`split-db` is for splitting a multi-persona DB after the fact, useful if you started with one shared DB and want per-persona isolation.

`global inspect` is a read-only corpus receipt: it reports configured
global-root existence, markdown file counts, indexed/default-available DB
counts, unindexed root markdown, indexed rows whose files are missing,
target-root DB counts, and path-safe counts/details for indexed global rows
outside the inspected root. Database counts distinguish default-available
evidence from confirmed instruction-grade files. The receipt also includes an
`authority` summary for filesystem frontmatter: evidence-enabled files, trusted
instruction-grade files, pending-review files, evidence-only reviews, and files
requiring user confirmation. It also runs a read-only memory
guard scan over global-root markdown and reports sanitized finding counts and
relative paths without echoing unsafe samples. Files with missing or
unrecognized frontmatter are reported as imported, pending, evidence-enabled,
instruction-disabled, and requiring confirmation. When review-gated global
files are present, inspect also includes body-safe `recommendations` from the
global review queue, such as listing the queue, inspecting the first target,
previewing confirmation, writing confirmation after review, running automated
promotion, or marking
the file evidence-only.
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
body-safe recommendations. It
does not persist recall traces or audit rows and does not include memory bodies,
snippets, card text, prompts, raw DB paths, or raw root paths.
`global seed` is the dry-run-first write path for no-persona/global memory. It
copies only markdown files from an explicit source directory into the configured
global memory root when `--write` is set, skips hidden/cache/auth-style folders,
and indexes copied files as `memory_scope=global` unless `--no-index` is passed.
Write mode first fails closed on unresolved target conflicts unless
`--overwrite` is supplied, then runs the memory guard over selected files and
fails closed on credential, injection, or hidden-content findings; use
`--no-guard` only for an intentional compatibility import. Write mode also
stamps missing or ambiguous global governance frontmatter before indexing,
making imported global files evidence-only and pending review unless they
already carry explicit confirmed instruction-grade provenance; use
`--no-stamp-governance` only for an intentional compatibility import. Write mode
also fails closed when a broad seed would copy mixed shared/persona-style paths
such as `roster/**`, `relationships/**`, `image-feedback/**`, or
`persona-*` files. Use repeatable `--include` and `--exclude` relative globs to
select only reviewed global files from mixed source trees; broad globs such as
`**/*.md` do not bypass the mixed-source guard unless the include pattern names
the mixed path itself. Use `--allow-mixed-source` only for an intentional
compatibility import where those paths have already been reviewed as
global-safe. These operator CLI helpers use
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
indexing/stamping. Stale-row pruning derives filter matching and receipt
relative paths from each row's resolved path under the selected root, not a
drifted stored DB `relative_path`. Inspect, files, and query-smoke receipts
collapse path-shaped stored DB `relative_path` values to filename-only labels
before returning them. Prune candidate receipts expose only `relative_path`,
`name`, and a short `path_fingerprint`, not the absolute stale row path.
Write-mode pruning also removes file-owned side-table rows such as
source refs, artifacts, entity links, file edges, embeddings, FTS rows, and
summaries, while preserving trace/review/job history with `file_id` cleared.
Write-mode seed/reindex receipts are
non-OK when governance stamping reports errors, indexing reports errors, or
files are skipped from indexing, even if some filesystem writes already
completed. Files whose governance stamp fails are not indexed in that run.
`global promote` is the no-human global promotion path. It is dry-run by
default and evaluates pending global files through named automated trust
policies such as `trusted_clean`. Write mode requires explicit enablement via
`--enable-auto-promotion` or `CHIMERA_MEMORY_GLOBAL_AUTO_PROMOTE=true`; eligible
files are written with `provenance_status: auto_confirmed`, reindexed, audited
as `global_memory_auto_promoted`, and left instruction-grade only after clean
policy, guard, path, body-hash, and rollback checks. Generated, restricted,
excluded, malformed, wrong-scope, missing-governance under the strict policy,
or guard-blocked files are skipped with body-safe policy reasons instead of
being promoted.

`global review` lists pending global-root markdown plus files that need
governance repair, such as missing required policy keys, wrong memory scope,
parse errors, or unsafe instruction-grade state. Returned items include
sanitized `review_reasons`, reason-count summaries, governance flags, and
confirm-action guard preview counts, not memory bodies. Missing or unrecognized
frontmatter is treated as pending/untrusted evidence instead of default
instruction authority. Human-readable listings also include returned
root-relative review targets with per-file reasons,
indexed state, confirm-guard blocked counts, and action-guidance-aware
recommendations. Queue recommendations include a concrete body-safe inspection
command for the first matching target, and include write commands only when the
target action can be written without guard blockage; otherwise they suggest
preview-only remediation actions. Queue-level write recommendations use a
`<BODY_SHA256>` placeholder until target inspection or preview supplies the real
reviewed body hash. Use repeatable
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
returning memory bodies or falling back to placeholder commands; automation can
use `global promote` for the no-human path. With
`--relative-path` and
no `--action`, it inspects one target body-safely: the receipt includes
frontmatter keys, review reasons, indexed/default availability, guard status,
body hash, body length, and recommendations, but not memory body text. With
`--relative-path` and
`--action`, it previews a durable frontmatter review change; with
`--write --reviewer <NAME>`, it updates the markdown, reindexes the same file as
`memory_scope=global`, writes a review action row, and records an audit event.
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
`confirm` is the explicit review path that promotes a global file to
instruction-grade use; `global promote` is the explicitly enabled automated
path that records `auto_confirmed` provenance instead of human provenance.
`evidence_only`, `restrict_scope`, `reject`, and the other review actions are
durable reviewed decisions that keep the file out of instruction use.
Review actions are root-relative only and
preserve the markdown body. Review action receipts use the relative target plus
hashes and do not return the absolute target file path. Targets with leading
separators, Windows drive or stream separators, `..`, control characters,
non-markdown extensions, or missing files fail closed instead of being
normalized into another target. Targets under hidden, cache, auth, or other
skipped corpus directories are rejected case-insensitively, matching global
discovery/seeding boundaries.
Human-readable review action output reports
sanitized review-guard required, blocked-file, and finding counts, including
failed writes. Write-mode review runs the memory guard before any action that
would leave the post-review file available to default global retrieval; unsafe
files can still be rejected, disputed, superseded, or restricted out of default
retrieval.
Write-mode `global seed`, `global reindex`, and `global review` record compact
audit events with counts or action metadata, root provenance, root fingerprints,
and affected relative paths, but not memory bodies or raw absolute roots.

`enhance` commands exercise the memory-enhancement sidecar pipeline without
requiring a model call. `provider-plan` shows the selected provider and budget
caps with credential refs hidden; when Codex OAuth exists but CM has not been
explicitly authorized to use it, the receipt recommends the safe `oauth-import`
command. `provider-smoke` verifies provider/model/OAuth invocation shape without
calling a model unless `--live` is passed; `--live --http-sidecar` routes the
diagnostic through an ephemeral local sidecar contract and returns only safe
metadata shape/counts. `enqueue` queues an indexed memory file for metadata
enrichment.
`dry-run` consumes queued jobs with deterministic local metadata and keeps
generated output review-gated: evidence-only, pending review, not
instruction-grade. `serve-dry-run` exposes the same deterministic behavior over
CM's HTTP sidecar contract for local integration tests. `sidecar-run` processes
queued jobs through a sidecar endpoint.

Set `CHIMERA_MEMORY_ENHANCEMENT_USE_MODELS_DEV_CATALOG=true` to let
provider-plan use CM's bundled/offline-first models.dev catalog for recommended
OpenAI, Anthropic, Gemini/Google, OpenRouter, and LM Studio model defaults.
Explicit `CHIMERA_MEMORY_ENHANCEMENT_*_MODEL` values still win. The intended
user setup flow is OpenAI, Anthropic, Gemini, OpenRouter, or Local AI. Local AI
then maps to Ollama, LM Studio, or a custom OpenAI-compatible endpoint.

## Configuration

A config file is auto-generated on first run at `~/.chimera-memory/config.yaml`. Every option is commented with plain-English explanations.

Priority: **environment variables > config file > defaults**.

| Setting | Env Variable | Default |
|---------|--------------|---------|
| Database path | `TRANSCRIPT_DB_PATH` | Persona DB if a persona is set, else `~/.chimera-memory/transcript.db` |
| JSONL directory | `TRANSCRIPT_JSONL_DIR` | Detected per harness (Claude `~/.claude/projects/<cwd>`, Codex `~/.codex/sessions`) |
| Memory root | `MEMORY_ROOT` | Auto-detected |
| Persona name | `TRANSCRIPT_PERSONA` | — |
| Project memory id | `CHIMERA_MEMORY_PROJECT_ID` | Derived from project root |
| Project memory root | `CHIMERA_MEMORY_PROJECT_ROOT` | — |
| Client/parser | `CHIMERA_CLIENT` | Detected harness (env signals → session-dir signature → JSONL content), else `claude-code` |
| Retention (days) | `TRANSCRIPT_RETENTION_DAYS` | 90 |
| Max DB size (MB) | `TRANSCRIPT_MAX_DB_SIZE_MB` | 1024 |
| Embedding provider | `CHIMERA_MEMORY_EMBEDDING_PROVIDER` | `auto` |
| Embedding CPU reserve | `CHIMERA_MEMORY_EMBEDDING_CPU_RESERVE_PERCENT` | `20` |
| Embedding max threads | `CHIMERA_MEMORY_EMBEDDING_MAX_THREADS` | CPU count minus reserve |

## Database Schema

```sql
-- Session metadata
sessions (session_id, persona, title, git_branch, cwd,
          started_at, ended_at, exchange_count, disposition)

-- Transcript entries (full-text indexed)
transcript (session_id, entry_type, timestamp, content, persona,
            source, channel, chat_id, message_id, author, ...)

-- Transcript embeddings (separate table to keep base schema lean)
transcript_embeddings (transcript_id, embedding_blob, model)

-- Curated memory files
memory_files (id, path, relative_path, persona, fm_type, fm_importance,
              fm_status, fm_tags, fm_last_accessed, fm_access_count,
              fm_failure_count, ...)

-- Memory embeddings
memory_embeddings (file_id, embedding_blob, model)

-- Incremental indexing
import_log (file_path, file_hash, file_size, last_position, entries_imported)

-- Full-text search
transcript_fts (content)
memory_fts (content)
```

## Roadmap

### Phase 1 ✅ — Foundation
- [x] JSONL parser with content extraction and entry classification
- [x] SQLite schema (sessions, transcript, import_log)
- [x] FTS5 full-text search with Porter stemming
- [x] Content sanitization (secret/token redaction, injection detection)
- [x] Incremental indexing with MD5 hashes
- [x] WAL mode + retry with backoff
- [x] File watcher (watchdog + poll safety net)
- [x] MCP tools: recall, stats, backfill
- [x] CLI: serve, backfill, stats

### Phase 2 ✅ — Search & Session Intelligence
- [x] Progressive disclosure (`discord_recall_index` + `discord_detail`)
- [x] Session browser (`session_list`)
- [x] Retention consolidation
- [x] Auto-generated config file
- [x] Precomputed session summaries (zero LLM, deterministic)

### Phase 3 ✅ — Semantic Layer
- [x] Local embeddings (bge-small-en-v1.5 via fastembed, ~80MB, offline)
- [x] Hybrid search (FTS5 + vector via Reciprocal Rank Fusion)
- [x] Multi-signal re-ranking (recency, session affinity, content richness)
- [x] Pluggable parser interface (BaseParser ABC)

### Phase 4 ✅ — Cognitive Layer
- [x] Curated memory layer (markdown + YAML frontmatter, separate from transcripts)
- [x] Algorithmic memory decay (per-type exponential salience)
- [x] Surprise scoring (novelty via nearest-neighbor embeddings, no LLM)
- [x] Zone-based loading (CORE / ACTIVE / PASSIVE / ARCHIVE)
- [x] Access reinforcement (auto-boost on search/recall hits)
- [x] Failure marking (penalize memories that led to wrong advice)
- [x] Graph analysis (disconnected clusters, isolated files)
- [x] Memory guard (pre-write credential + injection scan)

### Phase 5 ✅ — Cross-Runtime
- [x] Codex CLI parser (separate from Claude Code parser)
- [x] Hermes Agent integration (memory provider plugin + MCP server)
- [x] PersonifyAgents installer handlers (deterministic per-runtime wiring)
- [x] `split-db` CLI for per-persona DB isolation

### Phase 6 ✅ — Memory Enhancement + Provider Layer
- [x] Provider sidecar (OpenAI / Anthropic / Google / local backends)
- [x] OAuth lifecycle ownership in CM (relocation from PA, slices 1-6)
- [x] Anthropic OAuth via Hermes-pattern device-code flow (dynamic CC-version detection, exact UA, full beta set)
- [x] Google OAuth via PKCE + loopback HTTP server (mirrors Hermes pattern)
- [x] OpenAI Codex OAuth import + transport
- [x] Multi-account credential pool with hot-swap + exhaustion failover
- [x] Memory enhancement queue + shadow mode (Stage 1 approved Day 61 for sarah-persona allowlist; activates on runtime restart)
- [x] Sensitivity-tier deterministic gate (literal-prefix + keyword patterns + dual-scan)
- [x] Memory review queue (`memory_review_pending` / `memory_review_action`)
- [x] Entity graph + reasoning edges (typed connections, temporal sweep)
- [x] Pyramid summaries for long imported memories
- [x] Import pipelines: ChatGPT / Obsidian / Gmail / Perplexity / Grok / Twitter / Instagram / Google Activity / Atom-Blogger

### Phase 7 — Open Follow-ups
- [x] GitHub Actions CI workflow for CM
- [x] Streamable HTTP MCP transport for local/shared Codex sidecar use
- [ ] Stage 2 enhancement writeback (gated on rename normalization + single-slot variance work)
- [ ] Type-aware summary contract (per-type budget rules + sentence-aware truncation)
- [ ] Claim extraction + contradiction detection
- [ ] Runtime context-aware zone scoring (currently uses neutral baseline)
- [ ] Encryption at rest
- [ ] Export (markdown / JSON / CSV)
- [ ] Conversation branch detection (harness rewinds)
- [ ] Resident service-mode owner process per persona DB

## Compatibility

- **Python:** 3.10+
- **SQLite:** 3.35+ (ships with Python)
- **OS:** Windows, macOS, Linux, WSL
- **Harnesses:** Claude Code, Codex CLI, Hermes Agent (any version writing JSONL session files)
- **Dependencies:** `fastembed`, `watchdog`, `mcp`, `networkx` (for graph analysis), `pyyaml`

## Using Without the Curated Memory Layer

If you only want transcript search (no curated memory files), just skip the memory tools. The transcript layer works independently — no setup required beyond `backfill`. The curated memory layer is opt-in.

Set `MEMORY_ROOT=/dev/null` (or simply leave it unset) to tell the indexer there's no memory directory to watch.

## Related

- [PersonifyAgents](https://github.com/nexu-io/personifyagents) — Person-shaped agent platform built on top of ChimeraMemory. Uses the curated memory layer heavily. Provides the deterministic installer handlers that wire CM into any runtime.
- [ChimeraPersonas](https://github.com/ChimeraWerks/ChimeraPersonas) — Earlier opinionated persona system using ChimeraMemory's curated layer. PA is the successor.

## License

MIT
