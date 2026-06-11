"""Local live-retrieval planning helpers."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .memory_observability import record_memory_audit_event, record_memory_recall_trace
from .memory_relevance import clean_relevance_text, quality_filter_candidates
from .memory_scope import MEMORY_SCOPE_AUTO, global_root_filter_values, scope_filter_sql
from .sanitizer import build_fts_query

LIVE_RETRIEVAL_SCHEMA_VERSION = "chimera-memory.live-retrieval.v1"

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been",
    "but", "can", "could", "did", "does", "done", "for", "from", "had",
    "has", "have", "how", "into", "just", "like", "more", "need", "not",
    "now", "our", "out", "over", "should", "that", "the", "then", "this",
    "through", "use", "was", "what", "when", "where", "which", "with",
    "would", "you", "your",
}
_BLOCKED_LIFECYCLE = {"disputed", "rejected"}


def _clamp_limit(value: object, *, default: int = 5, maximum: int = 50) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, maximum))


def extract_live_retrieval_terms(text: str, *, limit: int = 10) -> list[str]:
    """Extract stable keyword cues from live context."""
    counts: dict[str, int] = {}
    order: list[str] = []
    clean_text = clean_relevance_text(text)
    for match in _WORD_RE.finditer(clean_text):
        term = match.group(0).strip("-_").lower()
        if len(term) < 3 or term in _STOPWORDS:
            continue
        if term not in counts:
            order.append(term)
            counts[term] = 0
        counts[term] += 1
    first_pos = {term: index for index, term in enumerate(order)}
    order.sort(key=lambda item: (-counts[item], first_pos[item]))
    return order[: max(0, limit)]


def build_live_retrieval_plan(
    *,
    current_context: str,
    previous_context: str = "",
    shift_threshold: float = 0.55,
    min_terms: int = 2,
    force: bool = False,
) -> dict:
    """Decide whether a context shift should trigger recall."""
    current_terms = extract_live_retrieval_terms(current_context)
    previous_terms = extract_live_retrieval_terms(previous_context)
    current_set = set(current_terms)
    previous_set = set(previous_terms)
    if not current_set:
        shift_score = 0.0
    elif not previous_set:
        shift_score = 1.0
    else:
        shift_score = 1.0 - (len(current_set & previous_set) / len(current_set | previous_set))
    should_retrieve = force or (len(current_terms) >= min_terms and shift_score >= shift_threshold)
    return {
        "schema_version": LIVE_RETRIEVAL_SCHEMA_VERSION,
        "current_terms": current_terms,
        "previous_terms": previous_terms,
        "query_terms": current_terms[:8],
        "query_text": " ".join(current_terms[:8]),
        "shift_score": round(shift_score, 4),
        "shift_threshold": shift_threshold,
        "should_retrieve": should_retrieve,
        "force": force,
    }


def memory_live_retrieval_check(
    conn: sqlite3.Connection,
    *,
    current_context: str,
    previous_context: str = "",
    persona: str | None = None,
    project_id: str | None = None,
    scope: str = MEMORY_SCOPE_AUTO,
    limit: int = 5,
    shift_threshold: float = 0.55,
    force: bool = False,
    include_restricted: bool = False,
    include_synthesis: bool = False,
    global_root: str | Path | None = None,
    actor: str = "system",
) -> dict:
    """Run a local proactive recall check and return suggestions without injecting them."""
    plan = build_live_retrieval_plan(
        current_context=current_context,
        previous_context=previous_context,
        shift_threshold=shift_threshold,
        force=force,
    )
    scope_sql, scope_params, scope_policy = scope_filter_sql(
        persona=persona,
        project_id=project_id,
        table_alias="f",
        scope=scope,
    )
    if not plan["should_retrieve"]:
        record_memory_audit_event(
            conn,
            "memory_live_retrieval_skipped",
            persona=persona,
            target_kind="memory_live_retrieval",
            target_id="skipped",
            payload={**plan, "scope_policy": scope_policy},
            actor=actor,
        )
        return {
            "ok": True,
            "retrieved": False,
            "reason": "no_topic_shift",
            "plan": plan,
            "scope_policy": scope_policy,
            "results": [],
        }

    fts_query = build_fts_query(plan["query_terms"])
    if not fts_query:
        record_memory_audit_event(
            conn,
            "memory_live_retrieval_skipped",
            persona=persona,
            target_kind="memory_live_retrieval",
            target_id="empty_query",
            payload={**plan, "scope_policy": scope_policy},
            actor=actor,
        )
        return {
            "ok": True,
            "retrieved": False,
            "reason": "empty_query",
            "plan": plan,
            "scope_policy": scope_policy,
            "results": [],
        }

    selected_limit = _clamp_limit(limit)
    candidate_limit = 0 if selected_limit <= 0 else min(100, max(selected_limit * 4, selected_limit))
    conditions = ["memory_fts MATCH ?", "COALESCE(f.fm_can_use_as_evidence, 1) = 1"]
    params: list[object] = [fts_query]
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    if not include_restricted:
        conditions.append("COALESCE(f.fm_sensitivity_tier, 'standard') <> 'restricted'")
    if not include_synthesis:
        conditions.append("COALESCE(f.fm_exclude_from_default_search, 0) = 0")
    root_filter = global_root_filter_values(global_root)
    if root_filter is not None:
        conditions.append(
            "("
            "COALESCE(f.memory_scope, '') <> 'global' "
            "OR LOWER(REPLACE(COALESCE(f.path, ''), '\\', '/')) = ? "
            "OR LOWER(REPLACE(COALESCE(f.path, ''), '\\', '/')) LIKE ?"
            ")"
        )
        params.extend(root_filter)
        scope_policy["global_root_filtered"] = True
    placeholders = ",".join("?" * len(_BLOCKED_LIFECYCLE))
    conditions.append(f"COALESCE(f.fm_lifecycle_status, 'active') NOT IN ({placeholders})")
    params.extend(sorted(_BLOCKED_LIFECYCLE))
    rows = conn.execute(
        f"""
        SELECT f.id, f.path, f.persona, f.relative_path, f.fm_type,
               f.fm_importance, f.fm_status, f.fm_about,
               f.memory_scope, f.project_id,
               snippet(memory_fts, 3, '>>>', '<<<', '...', 32) AS snippet,
               rank
        FROM memory_fts
        JOIN memory_files f ON f.id = memory_fts.rowid
        WHERE {' AND '.join(conditions)}
        ORDER BY rank
        LIMIT ?
        """,
        params + [candidate_limit],
    ).fetchall()
    raw_results = [
        {
            "id": row[0],
            "path": row[1],
            "persona": row[2],
            "relative_path": row[3],
            "type": row[4],
            "importance": row[5],
            "status": row[6],
            "about": row[7],
            "memory_scope": row[8],
            "project_id": row[9],
            "snippet": row[10],
            "ranking_score": row[11],
        }
        for row in rows
    ]
    filtered_results, quality_policy = quality_filter_candidates(
        raw_results,
        query_terms=plan["query_terms"],
    )
    results = filtered_results[:selected_limit]
    trace_id = record_memory_recall_trace(
        conn,
        tool_name="memory_live_retrieval",
        query_text=plan["query_text"],
        persona=persona,
        requested_limit=limit,
        results=results,
        result_count=len(filtered_results),
        request_payload={
            "current_context_chars": len(current_context or ""),
            "previous_context_chars": len(previous_context or ""),
            "plan": plan,
            "include_restricted": include_restricted,
            "include_synthesis": include_synthesis,
            "global_root_filter_enabled": root_filter is not None,
            "scope_policy": scope_policy,
            "raw_result_count": len(raw_results),
        },
        response_policy={
            "mode": "proactive_dry_run",
            "ranking": "fts5_rank",
            "quality_gate": quality_policy,
            "silent_on_miss": True,
            "injects_into_prompt": False,
            "scope_policy": scope_policy,
        },
    )
    event_type = "memory_live_retrieval_suggested" if results else "memory_live_retrieval_miss"
    record_memory_audit_event(
        conn,
        event_type,
        persona=persona,
        target_kind="memory_live_retrieval",
        target_id=trace_id,
        trace_id=trace_id,
        payload={
            "result_count": len(filtered_results),
            "raw_result_count": len(raw_results),
            "filtered_count": quality_policy["filtered_count"],
            "returned_count": len(results),
            "plan": plan,
            "quality_gate": quality_policy,
        },
        actor=actor,
    )
    return {
        "ok": True,
        "retrieved": True,
        "trace_id": trace_id,
        "plan": plan,
        "scope_policy": scope_policy,
        "raw_result_count": len(raw_results),
        "filtered_count": quality_policy["filtered_count"],
        "quality_gate": quality_policy,
        "results": results,
    }
