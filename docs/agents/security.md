# Security And Data Safety

## Local-First Boundary

CM's default path is local SQLite, local files, and local embeddings. Do not add
cloud persistence, hosted vector stores, or cloud LLM requirements to the
baseline path. Optional provider-backed enhancement must remain behind explicit
configuration, credential references, budgets, and sidecar/runner boundaries.

## Persona Boundary

Persona scoping is a privacy boundary. Preserve:

- `TRANSCRIPT_PERSONA`
- `CHIMERA_PERSONA_ID`
- `CHIMERA_PERSONA_NAME`
- `CHIMERA_PERSONA_ROOT`
- `CHIMERA_PERSONAS_DIR`
- `CHIMERA_SHARED_ROOT`
- per-persona DB path helpers
- cross-persona folder restrictions

Do not add fallback behavior that silently crosses persona roots or merges
restricted memories into default retrieval.

## Sensitive Files

Never commit or echo:

- runtime DBs or WAL files
- session transcripts or JSONL logs
- `.env`
- OAuth stores, refresh tokens, bearer tokens, API keys, local auth files
- generated provider worker homes or credentials
- raw provider stderr or exception text that may contain secrets

Ignored local state includes `.chimera-memory/`, `.venv/`, `*.db`, `*.db-wal`,
`*.db-shm`, `.env`, build outputs, caches, and IDE files.

## Browser And Client Surfaces

Anything returned to MCP clients, dashboards, browser surfaces, JSON receipts,
or diagnostics must be safe:

- hide raw local paths unless explicitly intended for trusted CLI output
- hide raw commands when they may reveal user paths or tokens
- hide credential refs when they reveal store names or user-specific secrets
- hide tokens and raw provider errors
- summarize failures with bounded categories and next actions

Prefer structured safe receipts over free-form stderr or exception strings.

## Provider And OAuth Boundaries

- Store credential references such as `oauth:openai-memory`, not token values.
- Provider policy must not resolve raw tokens.
- Queue failures must store bounded categories, not raw provider output.
- Runner code uses injected clients. Provider-specific network code belongs in dedicated clients/sidecars.
- Local deterministic/dry-run enhancement paths must require no provider token.
- Budget checks should happen before claiming provider-backed queue jobs.

## Filesystem And Imports

Importers and authored writeback must plan and write only under the allowed
persona memory root or the importer-specific safe subdirectory. Restricted
sources such as Gmail, Instagram, and Google Activity default to restricted,
pending review, and evidence-only.

When handling archive exports:

- tolerate source shape drift
- skip attachments unless explicitly designed otherwise
- sanitize content before indexing or returning excerpts
- prevent path traversal
- keep source markdown/body content as evidence, not instruction

## Subprocess And CLI Workers

CLI-worker supervisor code may spawn provider CLIs only when explicitly enabled
by env/config. Generated worker config must disable nested CM enhancement,
embedding, and health workers to avoid recursive process trees.

Worker output must return through `memory_worker_submit_result`, not free-form
stdout scraping. Worker prompts should be bounded to one pass and worker tool
surfaces should stay narrow.

## Migrations And Schema

SQLite migrations must be additive and idempotent. Do not delete or mutate user
data without an explicit migration plan, tests, and rollback story. Legacy
migration helpers must keep dry-run/plan behavior and hard stops.

## Generated Metadata

Generated metadata, generated memories, auto-capture output, sidecar output,
and imported memories start as review-gated evidence. Do not promote generated
metadata to instruction-grade without human review or explicitly trusted
provenance.
