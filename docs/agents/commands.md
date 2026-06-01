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
chimera-memory embed
chimera-memory embed --limit 500 --batch-size 64
chimera-memory stats
chimera-memory split-db
```

Use module form when the editable console script is unavailable:

```powershell
python -m chimera_memory.cli stats
```

## Codex Setup Helpers

```powershell
chimera-memory codex doctor
chimera-memory codex doctor --json
chimera-memory codex template --persona <NAME>
chimera-memory codex install --persona-id <ROLE/NAME> --persona-root <PATH> --yes
```

Windows helper:

```powershell
.\install-codex.ps1 -PersonaId <ROLE/NAME> -PersonaRoot <PATH> -Yes
```

The helper creates or refreshes `.venv`, installs CM editable there, writes or
updates Codex MCP config, then runs `chimera-memory codex doctor` through the
venv Python.

## Enhancement Helpers

```powershell
chimera-memory enhance provider-plan --json
chimera-memory enhance oauth-list --json
chimera-memory enhance oauth-import --provider openai --source codex_cli --json
chimera-memory enhance enqueue --file <MEMORY_PATH> --json
chimera-memory enhance authored-enqueue --persona <NAME> --payload <JSON> --json
chimera-memory enhance authored-write --personas-dir <DIR> --persona <NAME> --payload <YAML> --json
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

## Testing

Full suite:

```powershell
python -m pytest
```

Focused test:

```powershell
python -m pytest tests/test_memory_enhancement_queue.py
```

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
- `CHIMERA_MEMORY_EMBEDDING_PROVIDER`
- `CHIMERA_MEMORY_FASTEMBED_CUDA`
- `CHIMERA_MEMORY_FASTEMBED_DEVICE_IDS`
- `CHIMERA_MEMORY_EMBEDDING_CPU_RESERVE_PERCENT`
- `CHIMERA_MEMORY_EMBEDDING_MAX_THREADS`
- `CHIMERA_MEMORY_EMBEDDING_PROGRESS_PATH`
- `CHIMERA_MEMORY_ENHANCEMENT_USE_MODELS_DEV_CATALOG`

Config is generated under `~/.chimera-memory/config.yaml`. Runtime DBs and auth
stores belong under user runtime directories, not in this repo.

## Git and Vendor Sync

Before finalizing code changes:

```powershell
git diff
git status --short
```

When runtime CM changes need PersonifyAgents sync and `../PersonifyAgents`
exists, follow the workflow in `AGENTS.md` after this repo is committed and
pushed.
