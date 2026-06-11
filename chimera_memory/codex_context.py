"""Codex prompt context helpers for non-persona project mode."""

from __future__ import annotations

import sqlite3
from typing import Any

from .memory_context_pack import memory_context_pack, strip_memory_context
from .memory_scope import (
    MEMORY_SCOPE_AUTO,
    MEMORY_SCOPE_GLOBAL,
    MEMORY_SCOPE_PROJECT,
    current_project_id,
    safe_project_id,
)
from .transcript_context import format_transcript_context_block, project_transcript_context


CODEX_MEMORY_CONTEXT_MARKER = "[Automatic ChimeraMemory pre-turn evidence]"
CODEX_MEMORY_GROUNDING_RULE = (
    "[Grounding rule: for canonical, agreed, default, decided, baseline, reference, historical, "
    "or ownership claims, use confirmed/instruction-grade evidence when relevant. Evidence marked "
    "evidence-only, review=pending, needs-confirmation, lifecycle=stale, or lifecycle=archived is "
    "not current settled instruction; treat it as a lead, verify before relying on it, and say it "
    "needs confirmation if it is the only matching record. If an exact artifact, path, or date is "
    "required, read the referenced memory before answering. If the evidence does not contain a matching record, say CM did not provide one "
    "before asserting ground truth.]"
)
CODEX_CONTEXT_ALLOWED_SCOPES = frozenset((MEMORY_SCOPE_AUTO, MEMORY_SCOPE_PROJECT, MEMORY_SCOPE_GLOBAL))
CODEX_CONTEXT_DELIVERY_MODES = frozenset(
    ("context_only", "exec_dry_run", "exec", "diagnostic_smoke", "unknown")
)
_MOJIBAKE_UTF8_BOM = "\u00ef\u00bb\u00bf"


def normalize_codex_delivery_mode(value: object) -> str:
    mode = str(value or "").strip().lower().replace("-", "_")
    return mode if mode in CODEX_CONTEXT_DELIVERY_MODES else "unknown"


def _strip_prompt_bom(text: str) -> str:
    cleaned = str(text or "")
    changed = True
    while changed:
        changed = False
        for prefix in ("\ufeff", _MOJIBAKE_UTF8_BOM):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :]
                changed = True
    return cleaned


def strip_codex_prompt_context(text: str) -> str:
    """Remove a leading Codex CM evidence prefix before building a fresh prompt."""
    raw_text = _strip_prompt_bom(str(text or ""))
    cleaned = raw_text.lstrip()
    if not cleaned.startswith(CODEX_MEMORY_CONTEXT_MARKER):
        return raw_text

    cleaned = cleaned[len(CODEX_MEMORY_CONTEXT_MARKER) :].lstrip()
    cleaned = strip_memory_context(cleaned).lstrip()
    if cleaned.startswith(CODEX_MEMORY_GROUNDING_RULE):
        cleaned = cleaned[len(CODEX_MEMORY_GROUNDING_RULE) :].lstrip()
    return cleaned


def build_codex_prompt_context(
    conn: sqlite3.Connection,
    *,
    prompt: str,
    previous_context: str = "",
    project_id: str | None = None,
    project_root: str | None = None,
    global_root: str | None = None,
    scope: str = MEMORY_SCOPE_AUTO,
    limit: int = 5,
    token_budget: int = 800,
    shift_threshold: float = 0.55,
    force: bool = True,
    include_transcripts: bool = False,
    transcript_limit: int = 3,
    transcript_token_budget: int = 500,
    delivery_mode: str = "context_only",
) -> dict[str, Any]:
    """Return a Codex prompt with scoped CM evidence prepended when available.

    This helper intentionally omits persona parameters. Codex Desktop/CLI
    project mode should use only global plus current-project evidence.
    """
    selected_scope = str(scope or MEMORY_SCOPE_AUTO).strip().lower()
    selected_delivery_mode = normalize_codex_delivery_mode(delivery_mode)
    if selected_scope not in CODEX_CONTEXT_ALLOWED_SCOPES:
        return {
            "ok": False,
            "error": "scope must be auto, project, or global for Codex project context",
            "allowed_scopes": sorted(CODEX_CONTEXT_ALLOWED_SCOPES),
        }

    prompt_text = strip_codex_prompt_context(str(prompt or ""))
    selected_project_id = safe_project_id(project_id) or current_project_id()
    if selected_scope in (MEMORY_SCOPE_AUTO, MEMORY_SCOPE_PROJECT) and not selected_project_id:
        return {
            "ok": False,
            "error": "project_id or CHIMERA_MEMORY_PROJECT_ID is required for Codex auto/project context",
            "scope": selected_scope,
            "project_id": "",
        }
    if selected_scope == MEMORY_SCOPE_GLOBAL:
        selected_project_id = None

    result = memory_context_pack(
        conn,
        current_context=prompt_text,
        previous_context=previous_context,
        persona=None,
        project_id=selected_project_id,
        scope=selected_scope,
        limit=limit,
        token_budget=token_budget,
        shift_threshold=shift_threshold,
        force=force,
        include_restricted=False,
        include_synthesis=False,
        global_root=global_root,
        actor="codex-context",
        delivery_mode=selected_delivery_mode,
    )
    context_block = str(result.get("context_block") or "").strip()
    transcript_result: dict[str, Any] = {
        "ok": True,
        "reason": "disabled",
        "returned_count": 0,
        "raw_candidate_count": 0,
        "trace_id": "",
        "event_id": "",
        "snippets": [],
    }
    transcript_block = ""
    if include_transcripts and selected_scope in (MEMORY_SCOPE_AUTO, MEMORY_SCOPE_PROJECT):
        transcript_result = project_transcript_context(
            conn,
            query=prompt_text,
            project_id=selected_project_id,
            project_root=project_root,
            limit=transcript_limit,
            actor="codex-context",
            delivery_mode=selected_delivery_mode,
        )
        transcript_block = format_transcript_context_block(
            transcript_result,
            token_budget=transcript_token_budget,
        ).strip()

    evidence_blocks = [block for block in (context_block, transcript_block) if block]
    injected = bool(evidence_blocks)
    evidence_block = "\n\n".join(evidence_blocks)
    if injected:
        prefixed_prompt = (
            f"{CODEX_MEMORY_CONTEXT_MARKER}\n"
            + evidence_block
            + f"\n\n{CODEX_MEMORY_GROUNDING_RULE}\n\n{prompt_text}"
        )
    else:
        prefixed_prompt = prompt_text
    return {
        "ok": True,
        "injected": injected,
        "prompt": prefixed_prompt,
        "evidence_block": evidence_block,
        "context_block": context_block,
        "transcript_block": transcript_block,
        "trace_id": result.get("trace_id", ""),
        "retrieved": result.get("retrieved", False),
        "returned_count": result.get("returned_count", 0),
        "transcript_returned_count": transcript_result.get("returned_count", 0),
        "transcript_raw_candidate_count": transcript_result.get("raw_candidate_count", 0),
        "transcript_reason": transcript_result.get("reason", ""),
        "transcript_trace_id": transcript_result.get("trace_id", ""),
        "transcript_event_id": transcript_result.get("event_id", ""),
        "result_count": result.get("result_count", 0),
        "raw_result_count": result.get("raw_result_count", 0),
        "filtered_count": result.get("filtered_count", 0),
        "token_estimate": result.get("token_estimate", 0),
        "scope": selected_scope,
        "project_id": selected_project_id or "",
        "project_root": str(project_root or ""),
        "delivery_mode": selected_delivery_mode,
    }
