# Implementation Style Playbook

Read this when:

- a change spans multiple files or modules
- a task touches architecture, imports, schema, provider boundaries, or public surfaces
- you are refactoring or deciding where new behavior belongs

Do not read this when:

- the task is a tiny docs-only edit
- you are answering a simple question after already inspecting the relevant file

## Inspect First

Read the existing module, its focused tests, the relevant docs, and nearby
sibling patterns before editing. Prefer `rg` for search. Let the current module
layout decide where new behavior belongs.

## Keep Changes Additive

Add sidecars, trace rows, fields, helper modules, diagnostics, and adapters
without replacing the retrieval core or weakening governance defaults.
Replacement work needs measured proof and explicit approval.

## Place Code By Ownership

- Facade compatibility and orchestration: `memory.py`
- DDL and migrations: `memory_schema.py`
- Trust metadata: `memory_governance.py`
- Audit and recall traces: `memory_observability.py`
- Review workflows: `memory_review.py`
- Enhancement persistence: `memory_enhancement_queue.py`
- Provider policy: `memory_enhancement_provider.py`
- Provider/client transport: dedicated model, HTTP, OAuth, or sidecar modules
- Import parsing and safe write planning: matching `memory_import_*.py`
- Frontmatter parsing shared across modules: `memory_frontmatter.py`

When a public helper must remain importable from `memory.py`, implement it in
the focused module and re-export it from the facade.

## Avoid Circular Imports

Focused modules should not import `memory.py`. Schema and governance should
stay low-level. Observability should not import review or queue. Queue should
not own provider SDK/network code.

## Prefer Declarative Shapes

Use registries, dataclasses, explicit relation enums, bounded failure
categories, and structured payloads over scattered conditionals or ad hoc
strings.

## Comment Discipline

Runtime-critical comments need why, scar, source, and test. Good places for
these comments include Windows shims, CLI arg-budget fallbacks, stream parsers,
browser-safe projections, reload-survival state, and fallback model lists.

Do not comment self-named helpers or trivial branches.

## Dependencies

Do not add dependencies casually. Keep baseline local and lightweight. If a new
dependency is unavoidable, update `pyproject.toml`, docs, lockfiles as needed,
and explain why stdlib or existing dependencies are insufficient.
