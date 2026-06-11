"""Deterministic relevance gates for scoped memory recall."""

from __future__ import annotations

import re
from typing import Any


_CONTEXT_BLOCK_RE = re.compile(
    r"<\s*(?:chimera-memory-context|chimera-transcript-context|memory-context|supermemory-context)(?:\s+[^>]*)?>"
    r"[\s\S]*?"
    r"</\s*(?:chimera-memory-context|chimera-transcript-context|memory-context|supermemory-context)\s*>",
    re.IGNORECASE,
)
_CONTEXT_TAG_RE = re.compile(
    r"</?\s*(?:chimera-memory-context|chimera-transcript-context|memory-context|supermemory-context)(?:\s+[^>]*)?>",
    re.IGNORECASE,
)
_HIGHLIGHT_RE = re.compile(r">>>|<<<")
_MATCH_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}")
_BROAD_CONTEXT_TERMS = {
    "context",
    "contexts",
    "global",
    "memory",
    "memories",
    "project",
    "projects",
    "session",
    "sessions",
    "stop",
    "stopped",
    "stops",
    "turn",
    "turns",
    "work",
    "working",
}
_STRONG_SEMANTIC_SCORE = 0.78
_VERY_STRONG_SEMANTIC_SCORE = 0.86


def clean_relevance_text(value: object, *, max_chars: int = 2000) -> str:
    """Normalize text for deterministic relevance matching."""
    text = str(value or "")
    text = _CONTEXT_BLOCK_RE.sub("", text)
    text = _CONTEXT_TAG_RE.sub("", text)
    text = _HIGHLIGHT_RE.sub("", text)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _normalize_match_term(value: object) -> str:
    return str(value or "").strip("-_").lower()


def _dedupe_terms(terms: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = _normalize_match_term(term)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _candidate_match_tokens(item: dict[str, Any]) -> set[str]:
    text = " ".join(
        str(value or "")
        for value in (
            item.get("relative_path"),
            item.get("type"),
            item.get("tags"),
            item.get("about"),
            item.get("snippet"),
            item.get("match_text"),
            item.get("memory_scope"),
            item.get("project_id"),
        )
    )
    tokens: set[str] = set()
    for match in _MATCH_TERM_RE.finditer(clean_relevance_text(text)):
        token = _normalize_match_term(match.group(0))
        if not token:
            continue
        tokens.add(token)
        for part in re.split(r"[-_]+", token):
            normalized = _normalize_match_term(part)
            if normalized:
                tokens.add(normalized)
    return tokens


def _token_matches_term(term: str, tokens: set[str]) -> bool:
    if term in tokens:
        return True
    if len(term) < 5:
        return False
    prefix = term[:5]
    return any(token.startswith(prefix) or term.startswith(token[:5]) for token in tokens if len(token) >= 5)


def query_match_profile(item: dict[str, Any], query_terms: list[str]) -> dict[str, Any]:
    """Return deterministic query-term coverage metadata for a memory candidate."""
    terms = _dedupe_terms(query_terms)
    specific_terms = [term for term in terms if term not in _BROAD_CONTEXT_TERMS]
    gate_terms = specific_terms or terms
    if not gate_terms:
        return {
            "enabled": False,
            "query_term_count": 0,
            "gate_term_count": 0,
            "match_count": 0,
            "specific_match_count": 0,
            "coverage": 0.0,
            "matched_terms": [],
        }

    tokens = _candidate_match_tokens(item)
    matched_terms = [term for term in terms if _token_matches_term(term, tokens)]
    gate_matches = [term for term in gate_terms if _token_matches_term(term, tokens)]
    coverage = len(gate_matches) / len(gate_terms)
    return {
        "enabled": True,
        "query_term_count": len(terms),
        "gate_term_count": len(gate_terms),
        "match_count": len(matched_terms),
        "specific_match_count": len(gate_matches),
        "coverage": round(coverage, 4),
        "matched_terms": matched_terms[:12],
    }


def passes_quality_gate(item: dict[str, Any], profile: dict[str, Any]) -> bool:
    """Return whether a scoped candidate is strong enough to surface."""
    if not profile.get("enabled"):
        return True
    gate_term_count = _safe_int(profile.get("gate_term_count"))
    specific_match_count = _safe_int(profile.get("specific_match_count"))
    match_count = _safe_int(profile.get("match_count"))
    coverage = _safe_float(profile.get("coverage"))
    semantic_score = _safe_float(item.get("semantic_score"))
    min_matches = 1 if gate_term_count <= 2 else 2
    if item.get("requires_strict_term_coverage"):
        if specific_match_count >= min_matches:
            return True
        if specific_match_count >= 1 and coverage >= 0.50:
            return True
        return semantic_score >= _VERY_STRONG_SEMANTIC_SCORE and coverage >= 0.50

    if specific_match_count >= min_matches:
        return True
    if specific_match_count >= 1 and coverage >= 0.50:
        return True
    if semantic_score >= _STRONG_SEMANTIC_SCORE and (specific_match_count >= 1 or match_count >= 2):
        return True
    return semantic_score >= _VERY_STRONG_SEMANTIC_SCORE


def quality_filter_candidates(
    candidates: list[dict[str, Any]],
    *,
    query_terms: list[str],
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    """Filter weak broad-term matches while preserving traceable policy metadata."""
    filtered: list[dict[str, Any]] = []
    ignored = 0
    for item in candidates:
        candidate = dict(item)
        profile = query_match_profile(candidate, query_terms)
        candidate["query_match_profile"] = profile
        if passes_quality_gate(candidate, profile):
            filtered.append(candidate)
            continue
        ignored += 1

    return filtered, {
        "enabled": True,
        "raw_candidate_count": len(candidates),
        "filtered_count": ignored,
        "returned_candidate_count": len(filtered),
        "broad_terms": sorted(_BROAD_CONTEXT_TERMS),
        "strong_semantic_score": _STRONG_SEMANTIC_SCORE,
        "very_strong_semantic_score": _VERY_STRONG_SEMANTIC_SCORE,
    }
