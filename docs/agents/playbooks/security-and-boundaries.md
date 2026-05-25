# Security And Boundaries Playbook

Read this when:

- touching auth, OAuth, API keys, credential stores, provider clients, sidecars, subprocesses, filesystem writes, imports, migrations, transcripts, user data, browser/client output, or persona scoping
- adding a shell command, worker command, network call, or path projection

Do not read this when:

- the task is a purely local algorithm change with no user data, paths, auth, subprocess, network, or public output
- the task is docs-only and does not alter safety guidance

## First Questions

- What data could cross a trust boundary?
- Which persona, project, or root owns the data?
- Could output expose a raw path, command, stderr, token, refresh token, credential ref, or private transcript?
- Is generated content being treated as instruction instead of evidence?
- Is the path write constrained to the expected memory root?
- Is the network/provider call optional, budgeted, and explicit?

## Required Patterns

- Use credential references, never token values, in plans and receipts.
- Use bounded failure categories instead of raw exception text.
- Use safe projections for browser, MCP, JSON, and diagnostic output.
- Sanitize imported or captured content before indexing excerpts or returning it.
- Keep dry-run paths deterministic and token-free.
- Keep provider calls behind injected clients, sidecars, or dedicated transport modules.
- Keep migrations additive and idempotent.

## Filesystem Writes

Before writing user data, ensure the target resolves under the intended root.
Reject traversal and ambiguous relative paths. Importers should write under
their source-specific memory/import directory. Authored writeback should stay
under the selected persona root.

## Subprocesses

Generated worker homes and MCP config must isolate worker surfaces. Disable
nested CM enhancement, embedding, and health workers in generated worker config.
Do not scrape free-form stdout for trusted results; use the worker submit tool
protocol.

## Tests To Look For

Add or update tests that prove:

- token and credential values are not printed or stored in receipts
- unsafe paths are rejected
- restricted/generated memories remain filtered by default
- provider failures are categorized safely
- schema migrations are idempotent
- worker configs avoid recursive process trees
