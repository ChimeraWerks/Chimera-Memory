# Memory Enhancement CLI Worker

Status: Protocol, exclusion, budget, fake-worker, Codex supervisor, and
Claude Code supervisor slices implemented.

This document captures the replacement for subscription-backed HTTP enrichment
calls.

The original target was a persistent headless provider CLI session supervised
by ChimeraMemory. The shipped implementation is a persistent CM supervisor that
launches official CLI passes (`codex exec`, `claude --print`, `agy --print`)
only when the local queue already has eligible work. By default those passes
can reuse one daily provider conversation per worker, but the reuse window is
capped by `CHIMERA_MEMORY_CLI_WORKER_SESSION_MAX_TURNS` and defaults to one
pass. That conservative default prevents resumed-session context from growing
silently during memory metadata work.

- Codex starts a persisted `codex exec` session and resumes it with
  `codex exec resume`.
- Claude Code starts with a generated `--session-id` and resumes with
  `--resume`.
- Antigravity starts a print session and resumes with `--continue`.

Raise `CHIMERA_MEMORY_CLI_WORKER_SESSION_MAX_TURNS` only after reviewing
`memory_diagnose mode=cli_worker` cache-read growth. Set
`CHIMERA_MEMORY_CLI_WORKER_SESSION_MODE=bounded` to return to isolated one-shot
passes. A true always-running stdin/stdout provider process remains a future
transport mode if the CLIs expose a stable enough protocol.

The goal is to keep CM's deterministic core while letting a provider's official
CLI session own subscription authentication, token refresh, endpoint changes,
and model invocation behavior.

## Decision

For subscription-backed frontier enrichment, prefer official CLI worker
transport over raw HTTP OAuth transport once the worker protocol exists.

Transport order:

1. `dry_run`: deterministic local extraction, no model call.
2. `cli_worker`: persistent local supervisor plus daily-resumed official CLI
   sessions, preferred subscription mode today.
   - Fallback: bounded one-shot passes with
     `CHIMERA_MEMORY_CLI_WORKER_SESSION_MODE=bounded`.
   - Future extension: true always-running provider CLI process.
3. `http_oauth`: direct HTTP OAuth fallback.
4. `byok`: sanctioned API key or gateway key mode.

This only applies to provider-backed memory enhancement. It does not replace:

- transcript ingestion
- local fastembed transcript embeddings
- `memory_context_pack`
- health snapshots
- curated markdown memory files

## Why

Direct HTTP OAuth is fast and observable, but CM must maintain provider-specific
private wire behavior: endpoints, headers, request shapes, refresh edge cases,
and rate posture. That is brittle and can look programmatic in ways a provider
does not expect from a subscription account.

A persistent CLI worker has different trade-offs:

- The official CLI owns login, refresh, headers, and endpoint drift.
- The worker session JSONL is an inspectable job audit log.
- Behavior can be controlled by a dedicated `AGENTS.md` or `CLAUDE.md`.
- Traffic is closer to normal CLI use than raw HTTP impersonation.
- The worker is slower and must be supervised like a real process.

This is lower-risk and more transparent than HTTP OAuth. It is not guaranteed
terms-safe. A persistent automated CLI session is still automation, so CM must
keep conservative budgets, explicit user opt-in, and a fast disable path.

## Separation Of Responsibilities

CM remains the deterministic supervisor:

- queue ownership
- job claiming and locks
- rate and budget enforcement
- credential selection
- health and heartbeat monitoring
- audit events
- schema validation
- provenance, scope, and sensitivity validation
- database writes

The CLI worker is an LLM-backed extractor:

- claim one job
- read only the scoped job payload
- produce strict JSON
- submit the result
- maintain a heartbeat

The CLI worker must not write authoritative memory directly.

## Minimal Worker Tool Surface

The worker should not receive the normal persona tool belt.

Required tools:

- `memory_worker_claim_next`
- `memory_worker_submit_result`
- `memory_worker_heartbeat`
- `memory_worker_budget`

Optional read-only context:

- `memory_recall_readonly`

Explicitly excluded from the worker surface:

- `memory_remember`
- `memory_review` write actions
- `memory_promote_snapshot`
- federation write tools
- broad transcript recall unless a job specifically grants it

## Job Protocol

Claim request:

```json
{
  "worker_id": "codex-memory-worker-1",
  "capability": "enhancement",
  "provider": "openai",
  "max_jobs": 1
}
```

Claim response:

```json
{
  "job_id": 123,
  "schema_version": "chimera-memory.worker.enhance.v1",
  "source_ref": {
    "kind": "memory_file",
    "id": "developer/asa/procedural/example.md"
  },
  "content": {
    "format": "markdown",
    "text": "untrusted captured content"
  },
  "policy": {
    "max_topics": 12,
    "max_people": 20,
    "allow_action_items": true,
    "allow_sensitivity_hint": true
  },
  "output_schema": "strict-json"
}
```

Submit request:

```json
{
  "worker_id": "codex-memory-worker-1",
  "job_id": 123,
  "status": "succeeded",
  "actual_provider": "openai",
  "actual_model": "gpt-5.4",
  "result": {
    "topics": [],
    "people": [],
    "action_items": [],
    "sensitivity_hint": "normal",
    "summary": ""
  },
  "diagnostics": {
    "tokens_in": 0,
    "tokens_out": 0,
    "latency_ms": 0
  }
}
```

CM validates `result` before any writeback.

## Worker Files And Ingestion Exclusion

The worker needs its own instructions and operational state, but that state must
not become ordinary persona memory.

Day-one rule:

- worker files live under a dedicated worker directory
- worker JSONL is excluded from transcript ingestion
- worker operational notes are not semantic-indexed
- worker notes are not returned by default recall
- worker output is auditable by job id and file path

Do not index worker memory as a normal scoped persona memory until a concrete
use case exists and a loop-proof promotion path is designed.

Required exclusion guards:

- path-level blocklist for worker JSONL directories
- worker session id blocklist where available
- audit event marking for skipped worker transcript files

## Supervision

The worker supervisor owns:

- spawn and restart
- heartbeat timeout
- daily or size-based session rotation
- shutdown at CM exit
- queue lease cleanup if the worker dies
- stderr/stdout capture without secret leakage
- provider-specific launch commands
- local queue and budget checks before provider launch

The supervisor should not scrape free-form conversational output as the primary
result channel. Results should come through the worker MCP submit tool.

Idle polling must stay deterministic and local. The supervisor checks the
SQLite queue before launching Codex, Claude Code, or Antigravity; if no matching
pending job exists, it writes an idle heartbeat and sleeps without starting a
provider CLI. Provider-backed CLI sessions are for processing known work, not
for discovering whether work exists.

The supervisor records each provider-backed pass in
`memory_cli_worker_pass_events`: runtime, worker id, provider, session mode,
session id/day, resumed flag, return code, log paths, claimed/succeeded/failed
job counts, token usage, cache creation/read tokens, latency, and model.
Inspect with `memory_diagnose mode=cli_worker`.

Auto-enqueue excludes persona `MEMORY.md` index files and debounces repeated
same-fingerprint file updates. Index maintenance should not burn provider
tokens, and one save burst should not create multiple enhancement jobs for the
same content.

Codex supervisor status:

- opt-in with `CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE=cli_worker`
- launches `codex exec` worker passes and resumes one daily Codex session by
  default
- resolves the Codex executable with `shutil.which("codex")` or the Windows
  npm shim unless `CHIMERA_MEMORY_CODEX_BIN` is set
- passes `gpt-5.3-codex-spark` by default; override with
  `CHIMERA_MEMORY_CODEX_WORKER_MODEL`
- sets reasoning effort with `CHIMERA_MEMORY_CODEX_WORKER_EFFORT` or the
  shared `CHIMERA_MEMORY_CLI_WORKER_EFFORT`; default is `medium`
- copies the existing Codex auth file into the isolated worker `CODEX_HOME`
  unless `CHIMERA_MEMORY_CODEX_WORKER_AUTH_PATH` points somewhere else
- creates worker-local `AGENTS.md`
- creates worker-local Codex `config.toml` and legacy `mcp_servers.json` with
  worker-only CM tools
- uses `--dangerously-bypass-approvals-and-sandbox` by default because current
  `codex exec` cancels worker MCP tool calls without it
- set `CHIMERA_MEMORY_CODEX_WORKER_BYPASS_APPROVALS_AND_SANDBOX=false` to
  return to read-only sandbox mode when Codex supports non-interactive MCP
  approvals cleanly
- sets nested CM maintenance workers off in the child MCP server to prevent
  recursion
- defaults worker state under `CHIMERA_MEMORY_STATE_ROOT/workers/codex-memory-worker`

Codex bypass mode is accepted only inside the worker containment envelope:
isolated `CODEX_HOME`, daily worker session or bounded one-shot session,
worker-only MCP surface, temporary worker root, CM-side schema validation,
budget governor, shadow writes, and no direct authoritative memory writes.

Claude Code supervisor status:

- opt-in with `CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE=cli_worker` and
  `CHIMERA_MEMORY_CLI_WORKER_RUNTIME=claude`
- launches `claude --print --output-format stream-json` worker passes and
  can resume a daily Claude Code session when the session turn cap permits it
- passes an explicit memory-enhancement model; default is the Anthropic
  memory-enhancement Haiku tier
- rejects Opus model selection unless
  `CHIMERA_MEMORY_CLAUDE_WORKER_ALLOW_OPUS=true` is explicitly set
- sets reasoning effort with `CHIMERA_MEMORY_CLAUDE_WORKER_EFFORT` or the
  shared `CHIMERA_MEMORY_CLI_WORKER_EFFORT`; default is `medium`, and
  `xhigh`/`max` are downgraded unless Opus is explicitly allowed
- sets `CLAUDE_CONFIG_DIR` to a worker-local config directory so global
  `~/.claude/CLAUDE.md`, installed plugins, and user settings are not loaded
  into memory enhancement jobs
- copies the existing Claude Code credentials file into the isolated worker
  config directory unless `CHIMERA_MEMORY_CLAUDE_WORKER_CREDENTIALS_PATH` points
  somewhere else
- creates worker-local `CLAUDE.md`
- creates worker-local `.mcp.json` with worker-only CM tools
- launches with slash commands disabled, local settings only, strict MCP config,
  and the four worker MCP tools allowlisted
- sets nested CM maintenance workers off in the child MCP server to prevent
  recursion
- defaults worker state under `CHIMERA_MEMORY_STATE_ROOT/workers/claude-memory-worker`

Antigravity CLI supervisor status:

- opt-in with `CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE=cli_worker` and
  `CHIMERA_MEMORY_CLI_WORKER_RUNTIME=agy`
- launches `agy --print` worker passes and resumes one daily Antigravity
  conversation by default
- creates worker-local `AGENTS.md` and `GEMINI.md`
- creates worker-local Antigravity CLI `mcp_config.json` with worker-only CM
  tools
- sets nested CM maintenance workers off in the child MCP server to prevent
  recursion
- defaults worker state under `CHIMERA_MEMORY_STATE_ROOT/workers/agy-memory-worker`
- uses `CHIMERA_MEMORY_AGY_BIN` or local Antigravity install detection because
  `agy` may be a shell alias rather than a PATH executable

## Budget And Rate Posture

Subscription-backed workers must be conservative by default:

- concurrency `1`
- low per-minute cap
- daily job or token cap
- jitter between jobs
- pause on auth warning
- pause on rate limit
- reserve quota for human interactive use

BYOK and gateway-key modes may use higher caps because they are sanctioned paid
API traffic.

## Risks

- Worker prompt drift can produce invalid JSON.
- Worker context can accumulate irrelevant state.
- CLI upgrades can change behavior.
- Persistent automation is lower-risk than raw HTTP OAuth but not terms-proof.
- If worker JSONL enters normal CM ingestion, CM can create a self-referential
  enhancement loop.
- Too much tool access turns the worker into a self-writing memory agent.

Mitigations:

- strict schema validation
- no direct memory writes
- isolated worker tool surface
- transcript ingestion exclusion
- budget governor
- heartbeat and health checks
- deterministic dry-run fallback

## Implementation Slices

1. Add worker protocol tables and MCP tools. Shipped.
2. Add result schema validation and writeback gate. Shipped at the protocol boundary.
3. Add worker JSONL/path exclusion to transcript ingestion. Shipped with env-driven glob and session-id filters.
4. Add provider budget governor shared by HTTP and CLI transports. Shipped.
5. Add fake worker harness for tests. Shipped via `chimera-memory enhance worker-fake`.
6. Add Codex headless worker supervisor. Shipped as an explicit opt-in `codex exec` supervisor with daily session reuse.
7. Add Claude Code headless worker supervisor. Shipped as an explicit opt-in `claude --print` supervisor with daily session reuse.
8. Make `cli_worker` the default subscription-backed enhancement transport. Shipped for explicit OpenAI/Anthropic provider-worker setup.
9. Keep `http_oauth` as fallback and `dry_run` as the no-provider floor. Shipped: Google/other provider-backed setup keeps direct provider mode, dry-run remains default.
10. Add CLI-worker readiness doctor. Shipped as `chimera-memory enhance worker-doctor`, with optional `--init` to generate worker files without launching provider CLIs. Receipts are path-safe/argv-redacted and require copied Codex auth or Claude credentials before reporting ready.
