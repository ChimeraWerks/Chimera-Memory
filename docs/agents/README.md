# Agent Docs

Start with root `AGENTS.md`. Read these files only when relevant to the task.

## Core Docs

- `README.md` - this index and routing table
- `repo-map.md` - repository layout, major files, and where work belongs
- `commands.md` - install, CLI, server, test, and validation commands
- `boundaries.md` - architecture boundaries, focused module ownership, and import direction
- `validation.md` - validation order, focused test map, and completion rules
- `security.md` - local-first, persona, credential, path, and data-safety rules

## Playbooks

| Task | Read |
|---|---|
| Architecture, refactors, module movement, or multi-file changes | `playbooks/implementation-style.md` |
| CLI, MCP, config, import/export, dashboard, or user-visible behavior | `playbooks/user-facing-completeness.md` |
| Bugs, tests, validation strategy, final review, or risk assessment | `playbooks/verification-and-review.md` |
| Auth, OAuth, secrets, filesystem paths, subprocesses, network calls, migrations, transcripts, or user data | `playbooks/security-and-boundaries.md` |

## Existing Project References

- `README.md` - public tool reference, config docs, architecture overview
- `docs/MODULE_LAYOUT.md` - detailed focused-module ownership and test map
- `docs/OB1_COMPARISON.md` - OB1 feature comparison and lift plan
- `docs/MEMORY_ENHANCEMENT_SIDECAR.md` - sidecar contract and threat model
- `docs/MEMORY_ENHANCEMENT_CLI_WORKER.md` - persistent CLI worker transport design
- `docs/MIGRATION_PIPELINE.md` - legacy memory migration workflow
- `docs/FEDERATED_MEMORY_SCOPE.md` - federated memory scope policy
- `docs/ACTIVE_HARNESS_LEASE.md` - active harness lease behavior

Do not read every document by default. Use this index and `AGENTS.md` routing to keep context focused.
