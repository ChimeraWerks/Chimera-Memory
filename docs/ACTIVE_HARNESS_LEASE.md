# Active Harness Lease

Status: Day 63 warning-only slice.

ChimeraMemory records which MCP/runtime process has opened a persona memory DB. This is not a lock. It is an early warning layer for the "two live harnesses write the same persona DB" risk.

## Behavior

- On first curated-memory DB access, the MCP server records a row in `memory_active_harness_leases`.
- The server refreshes its lease at most once per minute while memory tools keep using the DB.
- Leases expire after 30 minutes without refresh.
- A second live process using the same persona and DB path produces a warning, but CM does not block either process.

## Diagnostic Surface

Use:

```text
memory_diagnose(mode="harness")
```

The report includes active leases, current lease metadata, and warning text if another active harness is present.

## Non-Goals

- No hard locks.
- No process killing.
- No service-mode ownership.
- No cross-persona merge behavior.

Those are bigger architecture decisions. This slice only collects evidence and warns.
