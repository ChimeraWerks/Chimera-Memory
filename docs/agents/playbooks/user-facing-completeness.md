# User-Facing Completeness Playbook

Read this when:

- changing CLI commands, MCP tools, config, env vars, JSON receipts, diagnostics, import/export flows, or dashboard behavior
- changing text or behavior a user or agent harness will see
- adding setup, doctor, install, dry-run, or provider planning flows

Do not read this when:

- the change is an internal pure helper with no public behavior
- the task is only a narrow test cleanup

## Public Surface Checklist

- Does the command, MCP tool, or helper name the action clearly?
- Does the output include enough state to decide the next step?
- Are errors actionable without leaking secrets, raw paths, raw commands, or stderr?
- Does JSON output remain stable and machine-readable?
- Are dry-run and preview paths available where writes or provider calls are risky?
- Are new env vars or config keys documented?
- Are generated values labeled with provenance?

## CLI Behavior

Keep CLI helpers safe by default. `doctor`, `template`, `provider-plan`, OAuth
list/import, worker doctor, and dry-run commands should expose receipts without
printing token values or raw credential material.

When commands write files, preserve existing config when possible, make backups
where current patterns do, and offer dry-run or explicit confirmation for risky
operations.

## MCP Tool Behavior

MCP tools should return bounded, useful text or JSON. Tools that query memory
should respect persona, lifecycle, sensitivity, and review defaults. Restricted
or generated/synthesis memory should stay excluded unless the tool explicitly
allows it.

## Import And Export Behavior

Importers should tolerate source format drift, skip unsafe data by default, and
write governed markdown under the importer-specific memory directory. Imports
default to pending review and evidence-only. Sensitive imports default to
restricted.

Profile export and generated summaries must not mutate source memory files.

## Docs And Tests

For public behavior changes:

- update `README.md` or the relevant docs file
- update focused tests
- include at least one test for safe output when secrets, paths, or provider failures are involved
