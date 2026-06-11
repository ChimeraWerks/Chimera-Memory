---
id: chimera-memory-enhancement-workers-and-provider-boundaries
title: Enhancement Workers And Provider Boundaries
scope: repo
kind: system
status: active
trust: high
created: 2026-06-09
updated: 2026-06-11
sources:
  - raw/sources/chimera-memory-source-pointers-2026-06-09.md
  - docs/MEMORY_ENHANCEMENT_SIDECAR.md
  - docs/MEMORY_ENHANCEMENT_CLI_WORKER.md
  - docs/agents/security.md
  - chimera_memory/memory_enhancement_http_client.py
  - chimera_memory/memory_enhancement_sidecar.py
  - chimera_memory/memory_enhancement.py
  - chimera_memory/memory_enhancement_queue.py
  - chimera_memory/memory_enhancement_provider.py
  - chimera_memory/memory_enhancement_provider_smoke.py
  - chimera_memory/memory_health.py
  - chimera_memory/memory_enhancement_oauth_import.py
  - chimera_memory/memory_cli_worker_supervisor.py
  - scripts/start-cm-http.ps1
  - scripts/install-cm-http-autostart.ps1
  - tests/test_memory_cli_worker_supervisor.py
  - tests/test_cli_enhance.py
  - tests/test_memory_enhancement.py
  - tests/test_memory_enhancement_queue.py
  - tests/test_memory_enhancement_provider.py
  - tests/test_memory_enhancement_provider_smoke.py
  - tests/test_memory_enhancement_oauth_import.py
  - tests/test_memory_enhancement_http_client.py
  - tests/test_memory_enhancement_sidecar.py
---

# Enhancement Workers And Provider Boundaries

## Decision

Memory enhancement is optional sidecar/worker work. CM remains the deterministic
owner of queue, locks, budgets, provenance, scope, schema validation, review
state, and database writes.

## Modes

- `dry_run`: deterministic local extraction, no model calls, default no-provider
  floor.
- `provider`: direct provider-backed batch runner through injected or resolving
  clients.
- `cli_worker`: official CLI worker passes for Codex, Claude Code, or
  Antigravity; explicit opt-in.
- `http_oauth` / BYOK style paths: fallback or sanctioned API/gateway modes,
  depending on provider setup.

## Credential Boundary

Credential references are names, not tokens. Accepted forms include
`oauth:...`, `secret:...`, and env-var references. Provider policy and queue
failures must not store raw tokens, raw provider responses, raw provider stderr,
or raw exception text.

Live Codex/ChatGPT OAuth is not consumed automatically. Detection may report
that Codex OAuth is importable, but provider-backed OpenAI enhancement only
becomes available after an explicit CM OAuth import or credential ref. The
`provider-plan` receipt labels this as `import_openai_codex_oauth` without
printing token material. The shared HTTP sidecar startup uses the user-global CM
state/auth store by default and accepts explicit provider/OAuth-store arguments
so scheduled restarts do not silently fall back to a repo-local empty store.

`provider-smoke` is the repeatable readiness proof after provider setup. In
plan mode it reports selected provider/model, OAuth/ref presence, budget, and
invocation shape without a model call. With `--live --http-sidecar`, it starts
an ephemeral local HTTP sidecar and calls the resolving provider client; the
receipt keeps the smoke global/no-persona and non-mutating and returns only
metadata shape/counts plus governance booleans, not credential refs, token
values, raw smoke content, generated summary text, provider stderr, or raw
provider response bodies.

Health snapshots record a safe provider profile alongside runtime health:
selected provider/model plus credential-ref and user-OAuth booleans, but not
credential refs or tokens. `codex doctor` treats that sidecar-recorded profile
as stronger evidence than a local/config plan-mode fallback when both are
available.

HTTP sidecar transport follows the same bounded-error rule. Auth failures return
the safe `auth_error` category, unauthorized small request bodies are drained
before the 401 response so Windows clients receive the JSON error rather than a
raw socket abort, and client-side OS/network failures collapse to sanitized
unavailable/timeout messages.

Queue rows may preserve raw source paths and wrapped request content for workers
and repair/debug internals. Client-facing enhancement receipts are a separate
safe boundary: CLI `enqueue`, `authored-enqueue`, `dry-run`, `worker-fake`, and
nested authored-write `enrichment_job` JSON collapse local paths to safe labels
plus fingerprints and redact wrapped content, authored payload bodies, and
content-derived metadata fields that are not needed for status or governance.

## Worker Surface

Enhancement workers use only worker tools:

- `memory_worker_claim_next`
- `memory_worker_submit_result`
- `memory_worker_heartbeat`
- `memory_worker_budget`

Optional read-only context must be explicitly granted. Workers must not receive
normal persona write tools or broad transcript recall by default.

`chimera-memory enhance worker-doctor` is a path-safe readiness surface. Its
live receipt redacts absolute local paths and raw launch argv, exposes only file
roles/existence/worker-root containment, reports a safe command profile, and
requires copied Codex auth or Claude credentials before `ok=true`.

## Output Validation

Captured content is untrusted data. Sidecar output must be strict JSON, schema
validated, sensitivity checked, and persisted as generated, pending review,
evidence-only metadata unless later review promotes it.

Provider-backed retrieval trace analysis uses sanitized trace summaries only:
raw context-derived query text, raw prompt payload fields, local paths, process
output, and credential-like values are omitted, redacted, or path-labeled before
the request is handed to an analysis client.

Authored-memory sensitivity checks scan authored payload content, source refs,
model audit refs, and optional enrichment output. They do not scan the request
contract or closed topic enum, because those are control data and include
allowed sensitive-topic labels such as OAuth or credential handling.

## Budget And Loop Prevention

Provider-backed work must check budget before claiming work. Worker logs and
worker JSONL must be excluded from normal transcript ingestion to prevent
self-referential enhancement loops. Nested CM maintenance workers are disabled
inside worker-local MCP config.
