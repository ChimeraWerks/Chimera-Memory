# Codex Desktop Scope And Code Audit

Status: Codex Desktop no-persona project-mode wiring landed locally on
2026-05-25; broad refactor is planned, not yet applied.

## Scope Change

CM remains a local-first AI memory layer with the same priority model:

```text
global -> persona -> repo/project -> narrower task context
```

The practical retrieval rule is still explicit and bounded:

- Persona sessions use `persona + current project + global`.
- Codex Desktop no-persona sessions use `current project + global`.
- Operator/admin calls may opt into `scope=all`.

No-persona Codex Desktop is now a first-class profile. It does not set
`TRANSCRIPT_PERSONA`. It sets:

- `CHIMERA_CLIENT=codex`
- `CHIMERA_MEMORY_PROJECT_ID=<safe repo id>`
- `CHIMERA_MEMORY_PROJECT_ROOT=<repo>/.chimera-memory`
- `CHIMERA_MEMORY_GLOBAL_ROOT=~/.chimera-memory/global-memory`
- `TRANSCRIPT_JSONL_DIR=~/.codex/sessions/`
- `CHIMERA_MEMORY_MCP_SURFACE=codex`

In no-persona project mode, CM must not crawl private persona trees. Authored
memory writes land under the project memory root with frontmatter:

```yaml
memory_scope: project
project_id: <repo id>
```

## Implemented Slice

The first slice makes repo-scoped Codex Desktop usable without a persona:

- `chimera-memory codex template` no longer requires `--persona`.
- `chimera-memory codex install` accepts `--project-id` and `--project-root`.
- Project-profile Codex install/template/starter flows set a CM-local global
  root and real installs create it before the watcher starts.
- `install-codex.ps1` defaults to project mode unless `-PersonaId` is provided.
- `chimera-memory codex doctor` treats missing persona identity as OK when
  project identity is complete.
- Persona Codex profiles can also carry explicit project env for
  persona + project + global recall.
- No-persona Codex installs default to the `codex` MCP surface, which keeps
  exact `memory_search`, `memory_query`, and scoped read-only
  `memory_live_retrieval_check` available.
- Codex templates also emit the matching `CHIMERA_MEMORY_MCP_SURFACE` value so
  copy/paste setup and installer setup agree.
- Codex setup can split `--command "python -m chimera_memory.cli"` into
  `command: python` plus `args: ["-m", "chimera_memory.cli", "serve"]`, and a
  bare Python executable command is normalized the same way.
- The `codex` MCP surface exposes the project/global memory belt, exact
  `memory_search`, structured `memory_query`, scoped read-only
  `memory_live_retrieval_check`, `memory_stats`, and `memory_whereami`, while
  hiding generic transcript recall, persona review/promotion, and
  operator/admin tools.
- `memory_diagnose(mode="whereami")` reports project identity/root and global
  root provenance alongside persona and transcript runtime fields.
- Health snapshots include a path-safe runtime profile, and `codex doctor`
  warns when a reachable HTTP sidecar is not actually running as no-persona
  Codex project+global memory.
- `memory_remember` and `memory_authored_writeback` can write project memory
  when no persona is active.
- Project-only indexing skips persona trees while still indexing global/shared
  and current-project memory.
- Explicit `CHIMERA_MEMORY_PROJECT_ID` pairs correctly with a single explicit
  `CHIMERA_MEMORY_PROJECT_ROOT` for discovery, indexing, writes, and queries,
  even when the root folder's derived id differs.
- `memory_stats` and provenance metadata lookups are now scoped and governed by
  the same default safety filters as direct retrieval, so Codex project mode
  does not expose persona-private counts or hidden memory metadata.

## Audit Results

Baseline runtime health before the scope slice:

- `python -m compileall -q chimera_memory tests` passed.
- `python -m pytest` passed with 425 tests.

Focused validation after the scope slice:

- `python -m py_compile chimera_memory/memory.py chimera_memory/server.py chimera_memory/mcp_surface.py chimera_memory/codex_setup.py chimera_memory/cli.py chimera_memory/memory_scope.py chimera_memory/memory_authored_writeback.py chimera_memory/config.py` passed.
- `python -m ruff check` on touched runtime/test files passed.
- `python -m pytest tests/test_codex_desktop_project_mode.py tests/test_persona_tool_surface.py tests/test_codex_setup.py tests/test_memory_authored_writeback.py tests/test_memory_scope.py` passed with 47 tests.
- `python -m pytest` passed with 439 tests.
- Temp Codex checks passed: project template emitted `codex` surface, install
  dry-run did not write a config file, temp install wrote only the temp Codex
  config, generated `python -m chimera_memory.cli serve` launch args, and
  `codex doctor` reported `ok`.
- MCP stdio startup smoke passed with temp home/config, no `TRANSCRIPT_PERSONA`,
  project env, `python -m chimera_memory.cli serve`, and
  `CHIMERA_MEMORY_MCP_SURFACE=codex`. It listed the required project tools and
  `memory_diagnose(mode="whereami")` resolved project id/root and the global
  root.
- Live Codex Desktop config was updated after the temp gate passed:
  the user Codex config now uses project profile `Chimera-Memory`, a
  repo-local `.chimera-memory` project root, `CHIMERA_MEMORY_MCP_SURFACE=codex`,
  and `python -m chimera_memory.cli serve`. A timestamped user-config backup
  was created.
  Live `codex doctor` should report `ok` after Codex Desktop is restarted.
- `git diff --check` passed; Git only reported line-ending normalization
  warnings for touched files.

Formatting and lint status:

- `python -m ruff format --check .` reports 131 files would be reformatted.
- `python -m ruff check . --statistics --exit-zero` reports 13 existing
  findings: 6 unused imports, 4 unused locals, 2 placeholder-free f-strings,
  and 1 non-top import.
- The edited focused files pass Ruff when checked directly.
- A stricter refactor scan found 696 findings across complexity, argument
  count, import ordering, Python 3.12 typing upgrades, and simplification rules.

Largest structural hotspots from AST/line audit:

| File | Size | Main issue |
|---|---:|---|
| `chimera_memory/server.py` | 3834 lines | `create_server` is 2914 lines and mixes tool registration, formatting, startup, workers, and diagnostics. |
| `chimera_memory/memory.py` | 2373 lines | Facade still carries indexing, watchers, query helpers, and compatibility exports. |
| `chimera_memory/memory_cli_worker_supervisor.py` | 1816 lines | Worker state, stats, passes, setup inspection, and formatting are coupled. |
| `chimera_memory/memory_enhancement_oauth.py` | 1533 lines | Store normalization, HTTP helpers, provider details, and credential pooling are dense. |
| `chimera_memory/memory_enhancement.py` | 1348 lines | Enhancement normalization and authored payload contracts should be split by concern. |
| `chimera_memory/cli.py` | 835 lines | `main` and `_run_enhance` are large dispatch functions. |
| `chimera_memory/codex_setup.py` | 827 lines | Installer, template builder, doctor, auth import, and runtime derivation now share one module. |

## Notable Risks

- Do not remove apparently-unused imports from `memory.py` in a blind lint pass.
  Many are compatibility re-exports through the historical facade.
- `server.py` should be split by behavior before deeper cleanup. The current
  single function makes review and tool-surface changes more error-prone.
- `start_memory_watcher` now schedules every configured project root and has
  event-level coverage that files from each root index under the matching
  `project:<id>` while persona paths are rejected in no-persona Codex/project
  mode.
- On this machine, the first `chimera-memory` executable on PATH is a stale
  Hermes venv shim that cannot import `chimera_memory.cli`. Project-mode Codex
  setup should use `python -m chimera_memory.cli` until that external shim is
  repaired or removed.
- Full-repo formatting is warranted, but it should be its own mechanical change
  after this behavior slice is stable.
- The comment standard is stricter than ordinary cleanup. Add operational
  comments only when they include why, scar, source, and test.

## Refactor Plan

1. Stabilize no-persona Codex Desktop:
   keep the current tests green, run the full suite, and verify a live Codex
   doctor receipt after install.

2. Project watcher coverage is fixed:
   multiple configured project roots are scheduled, watcher events from each
   root index under the matching project id, and no-persona Codex/project mode
   rejects persona-path events at the handler boundary.

3. Mechanical formatting pass:
   run `ruff format` in one standalone change. Do not mix this with behavior.

4. Safe lint cleanup:
   run `ruff check --fix` only for non-facade modules first. Handle
   `memory.py` exports manually with compatibility tests.

5. Split `server.py`:
   move tool registration into small modules or declarative registries by
   surface area: transcript recall, curated memory, review/import, enhancement
   worker, diagnostics, startup. Keep user-facing formatting near each tool.

6. Split `cli.py`:
   move subcommand registration and handlers into command modules. Start with
   `codex` and `enhance`, because they are already large and testable.

7. Split setup/runtime derivation:
   extract reusable profile derivation from `codex_setup.py` so future desktop,
   persona, and project install paths share one source of truth.

8. Tighten public docs:
   keep `README.md` as the user-facing reference, keep `docs/agents/` as the
   routing layer, and keep `docs/FEDERATED_MEMORY_SCOPE.md` as the scope policy.

## Agent Rules For Cleanup

- Prefer behavior-preserving slices with focused tests.
- Keep project, persona, and global scope labels explicit in code and docs.
- Do not make generated or imported memory instruction-grade without review.
- Do not leak raw paths, commands, secrets, stderr, or local auth details to
  browser/client surfaces.
- Use declarative registries where a surface is currently condition-heavy.
- Keep `memory.py` as compatibility facade; new behavior belongs in focused
  modules unless public compatibility requires a wrapper.
