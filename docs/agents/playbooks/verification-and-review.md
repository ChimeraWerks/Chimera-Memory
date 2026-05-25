# Verification And Review Playbook

Read this when:

- fixing a bug
- selecting tests
- reviewing a diff
- preparing the final response
- deciding whether a change is safe to call complete

Do not read this when:

- you are only mapping the repo and have not made or proposed a change
- a task explicitly asks for brainstorming without implementation

## Bug Fix Flow

1. Reproduce or understand the failing path from tests, code, or a concrete scenario.
2. Add or update the focused test that proves the scar.
3. Make the smallest code change that addresses the failure.
4. Run the focused test.
5. Broaden validation when the touched code is shared.

## Review Stance

Lead with bugs, regressions, data loss risks, privacy boundary leaks, missing
tests, and public-surface hazards. File and line references matter more than a
large summary.

High-risk issues in this repo include:

- cross-persona retrieval
- generated metadata promoted to instruction-grade
- raw credentials or local paths reaching browser/client surfaces
- non-idempotent schema migrations
- provider errors or stderr stored raw
- focused modules importing `memory.py`
- queue/provider/review modules collapsing into each other
- retrieval core replacements without receipts

## Validation Selection

- Docs-only: route/link/orphan checks plus `git diff`.
- Pure helper: focused unit test and compile if imports changed.
- Public CLI/MCP/config: focused tests plus docs check.
- Schema: schema hygiene tests plus affected feature tests.
- Core retrieval/index/parser: legacy standalone tests plus focused pytest.
- Provider/OAuth/network: safe-output tests, failure-category tests, budget/governor tests, and no-token-leak checks.

## Final Response

Include:

- what changed
- key files
- validation run and result
- assumptions
- risks, skipped checks, or follow-up work

Never bury failing validation in a cheerful summary.
