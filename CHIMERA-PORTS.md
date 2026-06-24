<!-- Generated from the chimera-ports registry on 2026-06-20. Do not hand-edit; edit the registry and re-run `ports caddyfile`. -->
# Dev ports & Caddy hosts — chimera-memory

| App | Role | Port | Caddy host | Bind | Entry |
| --- | --- | --- | --- | --- | --- |
| chimera-memory | mcp | 20020 | [http://chimera-memory-mcp.chimera.localhost](http://chimera-memory-mcp.chimera.localhost) | 127.0.0.1 | `chimera_memory.cli serve` |

## Rule

Read this port from an environment variable or config (e.g. PORT), defaulting to the registry value; never hard-code it. Before binding a new port, run `ports claim`.

## Hard-coded references to migrate

_none found_

Browser → the Caddy host. Direct → http://localhost:20020. Source of truth → chimera-ports registry (block 20000-24999).
