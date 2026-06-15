"""Global memory corpus seeding helpers."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from collections.abc import Mapping
from datetime import datetime, timezone
import fnmatch
import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

from .memory_governance import INSTRUCTION_GRADE_PROVENANCE, governance_from_frontmatter
from .memory_display import safe_filename_label, safe_memory_relative_path_display, safe_memory_text_display
from .sanitizer import scan_for_injection


INDEX_EXTENSIONS = {".md"}
DEFAULT_CLI_GLOBAL_ROOT = "~/.chimera-memory/global-memory"
GLOBAL_GOVERNANCE_STAMP_SCHEMA_VERSION = "chimera-memory.global-governance-stamp.v1"
GLOBAL_GOVERNANCE_REQUIRED_KEYS = {
    "memory_scope",
    "provenance_status",
    "lifecycle_status",
    "review_status",
    "sensitivity_tier",
    "can_use_as_instruction",
    "can_use_as_evidence",
    "requires_user_confirmation",
}
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".obsidian",
    ".claude",
    ".chimera",
    "__pycache__",
    "node_modules",
    "auth",
    "oauth",
    "pwa-state",
    "cache",
    "diagnostics",
}
MIXED_SOURCE_SEGMENTS = {
    "image-feedback",
    "image-feedbacks",
    "imagefeedback",
    "persona",
    "personas",
    "private",
    "relationship",
    "relationships",
    "roster",
    "rosters",
}
MIXED_SOURCE_PREFIXES = (
    "persona-",
    "persona_",
    "private-",
    "private_",
    "relationship-",
    "relationship_",
)


@dataclass(frozen=True)
class GlobalSeedCandidate:
    source_path: Path
    target_path: Path
    relative_path: str
    action: str
    reason: str = ""


class _NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: object) -> bool:
        return True


def inspect_global_memory_corpus(
    *,
    target_root: str | Path | None = None,
    db_path: str | Path | None = None,
    include_files: bool = False,
    query: str = "",
    query_limit: int = 5,
    query_token_budget: int = 800,
) -> dict[str, Any]:
    """Inspect filesystem and DB proof for the configured global memory corpus."""
    root, root_provenance = _resolve_cli_global_root(target_root)
    db = _resolve_cli_db_path(db_path)
    db_provenance = _path_provenance(db_path)
    root_files = _discover_root_markdown_files(root) if root.exists() and root.is_dir() else []
    governance_statuses = [
        _global_file_governance_status(path, relative_path=relative)
        for relative, path in root_files
    ]
    guard_status = _plan_global_file_guard(root_files, enabled=True)
    db_counts, indexed_by_path = _global_db_counts(db)
    # Windows stores memory_files.path unresolved while discovery resolve()s, so
    # compare on a normcased/normpath canonical form; otherwise casing or
    # 8.3-vs-long drift in the configured root misreports indexed files (gsr-08).
    indexed_by_canonical = {
        os.path.normcase(os.path.normpath(key)): value for key, value in indexed_by_path.items()
    }
    root_indexed = 0
    root_available = 0
    root_instruction_grade = 0
    root_missing = 0
    root_unindexed: list[str] = []
    indexed_missing: list[str] = []
    indexed_outside_root: list[dict[str, Any]] = []

    root_relatives = {relative for relative, _path in root_files}
    for relative, path in root_files:
        indexed_row = indexed_by_canonical.get(os.path.normcase(os.path.normpath(str(path))))
        indexed = indexed_row is not None
        if indexed:
            root_indexed += 1
            if indexed_row and indexed_row.get("available"):
                root_available += 1
            if indexed_row and indexed_row.get("instruction_grade_available"):
                root_instruction_grade += 1
        else:
            root_unindexed.append(relative)
    for path_text, row in indexed_by_path.items():
        path = Path(path_text)
        try:
            relative = str(path.resolve(strict=False).relative_to(root)).replace("\\", "/")
        except ValueError:
            indexed_outside_root.append(_outside_root_row_payload(path, row))
            continue
        if relative not in root_relatives:
            root_missing += 1
            indexed_missing.append(relative)
    db_counts = {
        **db_counts,
        "target_root_indexed_file_count": root_indexed,
        "target_root_available_file_count": root_available,
        "target_root_instruction_grade_file_count": root_instruction_grade,
        "outside_target_root_indexed_file_count": len(indexed_outside_root),
        "outside_target_root_available_file_count": sum(1 for row in indexed_outside_root if row.get("available")),
        "outside_target_root_instruction_grade_file_count": sum(
            1 for row in indexed_outside_root if row.get("instruction_grade_available")
        ),
    }

    receipt: dict[str, Any] = {
        "ok": True,
        "root": _root_payload(root, provenance=root_provenance),
        "db": _root_payload(db, provenance=db_provenance),
        "global_root_provenance": root_provenance,
        "global_root_exists": root.exists() and root.is_dir(),
        "db_exists": db.exists(),
        "filesystem": {
            "markdown_file_count": len(root_files),
            "indexed_markdown_file_count": root_indexed,
            "unindexed_markdown_file_count": len(root_unindexed),
            "indexed_missing_file_count": root_missing,
        },
        "governance": _global_governance_counts(governance_statuses),
        "authority": _global_authority_counts(governance_statuses),
        "guard": guard_status,
        "database": db_counts,
    }
    if str(query or "").strip():
        receipt["query_smoke"] = _global_query_smoke(
            db,
            root=root,
            query=query,
            limit=query_limit,
            token_budget=query_token_budget,
        )
    receipt["recommendations"] = _global_inspect_recommendations(receipt, root=root, db_path=db)
    if include_files:
        receipt["files"] = [
            {
                "relative_path": relative,
                "indexed": os.path.normcase(os.path.normpath(str(path))) in indexed_by_canonical,
                "governance": governance_statuses[index],
            }
            for index, (relative, path) in enumerate(root_files)
        ]
        receipt["indexed_missing_files"] = sorted(indexed_missing)
        receipt["indexed_outside_root_files"] = sorted(
            indexed_outside_root,
            key=lambda row: (str(row.get("relative_path") or ""), str(row.get("name") or "")),
        )
        receipt["unindexed_files"] = sorted(root_unindexed)
    return receipt


def _global_query_smoke(
    db_path: Path,
    *,
    root: Path,
    query: str,
    limit: int,
    token_budget: int,
) -> dict[str, Any]:
    """Run a read-only global retrieval smoke against an in-memory DB copy."""
    query_text = str(query or "").strip()
    base: dict[str, Any] = {
        "schema_version": "chimera-memory.global-query-smoke.v1",
        "status": "skipped",
        "reason": "",
        "scope": "global",
        "trace_written": False,
        "body_included": False,
        "prompt_included": False,
        "query": {
            "supplied": bool(query_text),
            "char_count": len(query_text),
            "source": "user_supplied" if query_text else "",
        },
        "policy": {
            "global_root_filter_enabled": True,
            "include_restricted": False,
            "include_synthesis": False,
            "force": True,
        },
        "returned_count": 0,
        "result_count": 0,
        "raw_result_count": 0,
        "filtered_count": 0,
        "duplicate_filtered_count": 0,
        "token_estimate": 0,
        "diagnostics": {
            "schema_version": "chimera-memory.global-query-smoke-diagnostics.v1",
            "candidate_stage": "not_run",
            "likely_reason": "not_run",
            "raw_candidate_count": 0,
            "quality_filtered_count": 0,
            "post_quality_candidate_count": 0,
            "duplicate_filtered_count": 0,
            "returned_count": 0,
        },
        "cards": [],
    }
    if not query_text:
        return {**base, "reason": "empty_query"}
    if not db_path.exists():
        return {**base, "reason": "db_missing"}

    source_conn: sqlite3.Connection | None = None
    conn: sqlite3.Connection | None = None
    try:
        source_conn = sqlite3.connect(str(db_path))
        conn = sqlite3.connect(":memory:")
        source_conn.backup(conn)
        from .memory_context_pack import memory_context_pack

        result = memory_context_pack(
            conn,
            current_context=query_text,
            previous_context="",
            persona=None,
            project_id=None,
            scope="global",
            global_root=root,
            limit=max(1, min(int(limit), 20)),
            token_budget=max(120, min(int(token_budget), 4000)),
            force=True,
            include_restricted=False,
            include_synthesis=False,
            actor="global-inspect",
            delivery_mode="diagnostic_smoke",
        )
        candidate_profiles = _global_query_smoke_candidate_profiles(
            conn,
            result,
            root=root,
            limit=max(1, min(int(limit), 20)),
        )
    except (sqlite3.Error, OSError, ValueError) as exc:
        return {**base, "status": "unavailable", "reason": exc.__class__.__name__}
    finally:
        if conn is not None:
            conn.close()
        if source_conn is not None:
            source_conn.close()

    cards = result.get("cards") if isinstance(result.get("cards"), list) else []
    returned_count = int(result.get("returned_count") or 0)
    diagnostics = _global_query_smoke_diagnostics(
        result,
        returned_count=returned_count,
        candidate_profiles=candidate_profiles,
    )
    return {
        **base,
        "status": "ok" if returned_count > 0 else "miss",
        "reason": "" if returned_count > 0 else str(diagnostics.get("likely_reason") or "no_matching_global_context"),
        "retrieved": bool(result.get("retrieved")),
        "returned_count": returned_count,
        "result_count": int(result.get("result_count") or 0),
        "raw_result_count": int(result.get("raw_result_count") or 0),
        "filtered_count": int(result.get("filtered_count") or 0),
        "duplicate_filtered_count": int(result.get("duplicate_filtered_count") or 0),
        "token_estimate": int(result.get("token_estimate") or 0),
        "diagnostics": diagnostics,
        "cards": [_global_query_smoke_card(card) for card in cards],
    }


def _global_query_smoke_diagnostics(
    result: Mapping[str, Any] | None,
    *,
    returned_count: int,
    candidate_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_count = int((result or {}).get("raw_result_count") or 0)
    quality_filtered = int((result or {}).get("filtered_count") or 0)
    post_quality_count = int((result or {}).get("result_count") or 0)
    duplicate_filtered = int((result or {}).get("duplicate_filtered_count") or 0)
    if returned_count > 0:
        stage = "returned"
        likely_reason = "returned"
    elif raw_count <= 0:
        stage = "candidate_generation"
        likely_reason = "no_global_candidates_after_scope_filters"
    elif post_quality_count <= 0 and quality_filtered >= raw_count:
        stage = "quality_gate"
        likely_reason = "quality_gate_filtered_all_candidates"
    elif post_quality_count <= 0 and duplicate_filtered > 0:
        stage = "dedupe"
        likely_reason = "duplicate_filter_removed_all_candidates"
    elif post_quality_count > 0:
        stage = "packing"
        likely_reason = "candidates_available_but_not_returned"
    else:
        stage = "unknown"
        likely_reason = "no_matching_global_context"
    diagnostics: dict[str, Any] = {
        "schema_version": "chimera-memory.global-query-smoke-diagnostics.v1",
        "candidate_stage": stage,
        "likely_reason": likely_reason,
        "raw_candidate_count": raw_count,
        "quality_filtered_count": quality_filtered,
        "post_quality_candidate_count": post_quality_count,
        "duplicate_filtered_count": duplicate_filtered,
        "returned_count": int(returned_count),
    }
    if candidate_profiles:
        diagnostics["candidate_profiles"] = candidate_profiles
    return diagnostics


def _global_query_smoke_card(card: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "relative_path": _safe_relative_path_label(
            card.get("relative_path"),
            fallback_path=card.get("path"),
        ),
        "memory_scope": str(card.get("memory_scope") or ""),
        "project_id": str(card.get("project_id") or ""),
        "review_status": str(card.get("review_status") or ""),
        "lifecycle_status": str(card.get("lifecycle_status") or ""),
        "sensitivity_tier": str(card.get("sensitivity_tier") or ""),
        "requires_user_confirmation": bool(card.get("requires_user_confirmation")),
        "can_use_as_instruction": bool(card.get("can_use_as_instruction")),
        "score": card.get("ranking_score"),
        "importance": card.get("importance"),
        "query_match_profile": _safe_query_match_profile(card.get("query_match_profile")),
    }


def _global_query_smoke_candidate_profiles(
    conn: sqlite3.Connection,
    result: Mapping[str, Any],
    *,
    root: Path,
    limit: int,
) -> list[dict[str, Any]]:
    plan = result.get("plan") if isinstance(result.get("plan"), Mapping) else {}
    query_terms = [str(term) for term in (plan.get("query_terms") or []) if str(term).strip()]
    query_text = str(plan.get("query_text") or "").strip()
    if not query_terms and not query_text:
        return []
    try:
        from .memory_context_pack import _combine_candidates, _fts_candidates, _semantic_candidates
        from .memory_relevance import passes_quality_gate, query_match_profile

        candidate_limit = max(int(limit) * 4, 20)
        fts, _fts_policy = _fts_candidates(
            conn,
            query_terms,
            persona=None,
            project_id=None,
            scope="global",
            include_restricted=False,
            include_synthesis=False,
            global_root=root,
            limit=candidate_limit,
        )
        semantic, _semantic_policy = _semantic_candidates(
            conn,
            query_text,
            persona=None,
            project_id=None,
            scope="global",
            include_restricted=False,
            include_synthesis=False,
            global_root=root,
            limit=candidate_limit,
        )
        raw_candidates = _combine_candidates(fts, semantic, limit=candidate_limit)
    except (sqlite3.Error, OSError, ValueError):
        return []

    profiles: list[dict[str, Any]] = []
    for candidate in raw_candidates[:10]:
        profile = query_match_profile(candidate, query_terms)
        passed = passes_quality_gate(candidate, profile)
        item = _global_query_smoke_candidate_profile(candidate)
        item["quality_gate_passed"] = bool(passed)
        item["query_match_profile"] = _safe_query_match_profile(profile)
        if not passed:
            item["quality_gate_reason"] = "insufficient_query_term_coverage"
        profiles.append(item)
    return profiles


def _global_query_smoke_candidate_profile(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "relative_path": _safe_relative_path_label(
            candidate.get("relative_path"),
            fallback_path=candidate.get("path"),
        ),
        "memory_scope": str(candidate.get("memory_scope") or ""),
        "review_status": str(candidate.get("review_status") or ""),
        "lifecycle_status": str(candidate.get("lifecycle_status") or ""),
        "sensitivity_tier": str(candidate.get("sensitivity_tier") or ""),
        "requires_user_confirmation": bool(candidate.get("requires_user_confirmation")),
        "can_use_as_instruction": bool(candidate.get("can_use_as_instruction")),
        "score": candidate.get("ranking_score"),
        "importance": candidate.get("importance"),
    }


def _safe_query_match_profile(profile: object) -> dict[str, Any]:
    if not isinstance(profile, Mapping):
        return {}
    return {
        "enabled": bool(profile.get("enabled")),
        "query_term_count": _safe_int(profile.get("query_term_count")),
        "gate_term_count": _safe_int(profile.get("gate_term_count")),
        "match_count": _safe_int(profile.get("match_count")),
        "specific_match_count": _safe_int(profile.get("specific_match_count")),
        "coverage": _safe_float(profile.get("coverage")),
        "matched_terms": [
            term
            for term in (_safe_query_term_label(value) for value in (profile.get("matched_terms") or []))
            if term
        ][:12],
    }


def _safe_query_term_label(value: object) -> str:
    text = " ".join(safe_memory_text_display(value).split())
    if len(text) <= 120:
        return text
    return text[:117].rstrip() + "..."


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _global_inspect_recommendations(
    receipt: Mapping[str, Any],
    *,
    root: Path,
    db_path: Path,
) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    filesystem = receipt.get("filesystem") if isinstance(receipt.get("filesystem"), Mapping) else {}
    authority = receipt.get("authority") if isinstance(receipt.get("authority"), Mapping) else {}
    database = receipt.get("database") if isinstance(receipt.get("database"), Mapping) else {}
    if not bool(receipt.get("global_root_exists")):
        return [
            {
                "code": "create_or_seed_global_root",
                "message": "Create or seed the configured global memory root before expecting global memory retrieval.",
                "command": "chimera-memory global seed --source <DIR> --json",
            }
        ]
    if int(filesystem.get("markdown_file_count") or 0) <= 0:
        recommendations.append(
            {
                "code": "seed_global_memory",
                "message": "The global memory root has no markdown files; seed reviewed global markdown before expecting retrieval.",
                "command": "chimera-memory global seed --source <DIR> --json",
            }
        )
    if int(filesystem.get("unindexed_markdown_file_count") or 0) > 0:
        _append_global_recommendation(
            recommendations,
            {
                "code": "preview_global_reindex",
                "message": "Preview a global reindex so root markdown files can become available to retrieval.",
                "command": "chimera-memory global reindex --json",
            }
        )
    outside_indexed_count = int(database.get("outside_target_root_indexed_file_count") or 0)
    outside_available_count = int(database.get("outside_target_root_available_file_count") or 0)
    if outside_indexed_count > 0:
        _append_global_recommendation(
            recommendations,
            {
                "code": "inspect_outside_root_global_rows",
                "message": (
                    f"Indexed global DB rows exist outside the configured global root ({outside_indexed_count}); "
                    "active retrieval excludes them, so inspect the path-safe file list before changing roots or pruning data."
                ),
                "command": "chimera-memory global inspect --files --json",
            }
        )
    if outside_available_count > 0:
        _append_global_recommendation(
            recommendations,
            {
                "code": "reindex_active_global_root",
                "message": (
                    "Preview a refresh of the configured global root so active-root counts and governance can be checked; "
                    "outside-root rows require deliberate old-root inspection or DB maintenance before removal."
                ),
                "command": "chimera-memory global reindex --json",
            }
        )
    query_smoke = receipt.get("query_smoke") if isinstance(receipt.get("query_smoke"), Mapping) else {}
    for recommendation in _global_query_smoke_recommendations(query_smoke):
        _append_global_recommendation(recommendations, recommendation)
    if int(authority.get("pending_review_file_count") or 0) > 0 or int(authority.get("requires_user_confirmation_file_count") or 0) > 0:
        try:
            from .memory_global_review import memory_global_review_pending

            review = memory_global_review_pending(target_root=root, db_path=db_path, limit=0)
        except Exception as exc:
            _append_global_recommendation(
                recommendations,
                {
                    "code": "global_review_unavailable",
                    "message": f"Global review recommendations could not be built ({exc.__class__.__name__}); list the queue manually.",
                    "command": "chimera-memory global review --json",
                }
            )
        else:
            if review.get("ok") and isinstance(review.get("recommendations"), list):
                for item in review["recommendations"]:
                    if isinstance(item, dict):
                        _append_global_recommendation(recommendations, item)
            else:
                _append_global_recommendation(
                    recommendations,
                    {
                        "code": "list_global_review_queue",
                        "message": "List pending global memory review targets before treating global memory as instruction-grade.",
                        "command": "chimera-memory global review --json",
                    }
                )
    return recommendations


def _append_global_recommendation(recommendations: list[dict[str, str]], item: Mapping[str, object]) -> None:
    code = str(item.get("code") or "").strip()
    if code and any(str(existing.get("code") or "") == code for existing in recommendations):
        return
    recommendations.append(
        {
            "code": code,
            "message": str(item.get("message") or ""),
            "command": str(item.get("command") or ""),
        }
    )


def _global_query_smoke_recommendations(query_smoke: Mapping[str, Any]) -> list[dict[str, str]]:
    if not query_smoke:
        return []
    status = str(query_smoke.get("status") or "")
    if status == "ok":
        return []
    reason = str(query_smoke.get("reason") or "")
    diagnostics = query_smoke.get("diagnostics") if isinstance(query_smoke.get("diagnostics"), Mapping) else {}
    likely_reason = str(diagnostics.get("likely_reason") or reason)
    if reason == "db_missing":
        return [
            {
                "code": "global_query_db_missing",
                "message": "The query smoke could not run because the selected memory DB is missing; preview a reindex of the active global root before writing the DB.",
                "command": "chimera-memory global reindex --json",
            }
        ]
    if likely_reason == "no_global_candidates_after_scope_filters":
        return [
            {
                "code": "global_query_no_scoped_candidates",
                "message": "The query smoke found no scoped global candidates; inspect the active root and reindex if expected files are missing from the DB.",
                "command": "chimera-memory global inspect --files --json",
            }
        ]
    if likely_reason == "quality_gate_filtered_all_candidates":
        return [
            {
                "code": "global_query_quality_gate_filtered",
                "message": "Global candidates existed but the relevance quality gate filtered them; retry with more specific task terms or inspect global file metadata for stronger about/tags.",
                "command": "chimera-memory global inspect --query <TEXT> --json",
            }
        ]
    if likely_reason == "duplicate_filter_removed_all_candidates":
        return [
            {
                "code": "global_query_dedupe_removed_candidates",
                "message": "Global candidates were removed as duplicates; inspect global files for overlapping relative paths or identical content fingerprints.",
                "command": "chimera-memory global inspect --files --json",
            }
        ]
    if likely_reason == "candidates_available_but_not_returned":
        return [
            {
                "code": "global_query_packing_gap",
                "message": "Global candidates survived filtering but were not packed into the smoke result; retry with a larger query token budget or lower limit noise.",
                "command": "chimera-memory global inspect --query <TEXT> --query-token-budget 1600 --json",
            }
        ]
    return []


def seed_global_memory_corpus(
    source_root: str | Path,
    *,
    target_root: str | Path | None = None,
    db_path: str | Path | None = None,
    write: bool = False,
    overwrite: bool = False,
    index: bool = True,
    stamp_governance: bool = True,
    guard: bool = True,
    allow_mixed_source: bool = False,
    include_patterns: list[str] | tuple[str, ...] | None = None,
    exclude_patterns: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Plan or copy markdown files into the configured global memory root."""
    source = Path(source_root).expanduser().resolve()
    target, target_provenance = _resolve_cli_global_root(target_root)
    validation = _validate_roots(
        source,
        target,
        source_provenance="user_supplied",
        target_provenance=target_provenance,
    )
    if validation is not None:
        return validation

    include = _normalize_patterns(include_patterns or [])
    exclude = _normalize_patterns(exclude_patterns or [])
    candidates = _discover_seed_candidates(source, target, overwrite=overwrite, include_patterns=include, exclude_patterns=exclude)
    mixed_source_guard = _plan_mixed_source_guard(
        candidates,
        include_patterns=include,
        allow_mixed_source=allow_mixed_source,
    )
    governance_stamp_preview = _plan_global_governance_stamps(
        candidates,
        source_root=source,
        target_root=target,
        operation="global_seed",
        enabled=stamp_governance,
    )
    guard_preview = _plan_global_seed_guard(
        candidates,
        enabled=guard,
    )
    receipt: dict[str, Any] = {
        "ok": True,
        "write": bool(write),
        "indexed": False,
        "source": _root_payload(source, provenance="user_supplied"),
        "target": _root_payload(target, provenance=target_provenance),
        "source_provenance": "user_supplied",
        "target_provenance": target_provenance,
        "filters": {
            "include_patterns": include,
            "exclude_patterns": exclude,
            "allow_mixed_source": bool(allow_mixed_source),
        },
        "counts": _candidate_counts(candidates),
        "mixed_source_guard": mixed_source_guard,
        "guard": guard_preview,
        "governance_stamp": governance_stamp_preview,
        "files": [_candidate_payload(candidate) for candidate in candidates],
    }
    if not write:
        return receipt
    if mixed_source_guard["blocked_count"]:
        receipt["ok"] = False
        receipt["written_count"] = 0
        receipt["error"] = "global memory mixed-source guard blocked selected files"
        return receipt
    if guard_preview["blocked_count"]:
        receipt["ok"] = False
        receipt["error"] = "global memory guard blocked selected files"
        return receipt
    if int(receipt["counts"].get("conflict") or 0):
        receipt["written_count"] = 0
        _mark_global_write_errors(receipt, operation="global memory seed")
        return receipt

    target.mkdir(parents=True, exist_ok=True)
    written: list[GlobalSeedCandidate] = []
    stamp_failed_relative_paths: set[str] = set()
    stamp_result = _empty_stamp_result(enabled=stamp_governance)
    # Back up overwritten files and track new copies so a failure during the
    # copy/stamp/index steps leaves NO half-applied state on disk (gsr-05): new
    # files are removed and overwritten ones restored from backup. The backup
    # dir lives only for the duration of the write so success discards it.
    with tempfile.TemporaryDirectory(prefix="chimera-global-seed-bak-") as backup_dir:
        backups: dict[Path, Path] = {}
        try:
            for candidate in candidates:
                if candidate.action in {"copy", "overwrite"}:
                    candidate.target_path.parent.mkdir(parents=True, exist_ok=True)
                    if candidate.action == "overwrite" and candidate.target_path.exists():
                        backup_path = Path(backup_dir) / f"{len(backups)}-{candidate.target_path.name}"
                        shutil.copy2(candidate.target_path, backup_path)
                        backups[candidate.target_path] = backup_path
                    shutil.copy2(candidate.source_path, candidate.target_path)
                    written.append(candidate)
                if candidate.action in {"copy", "overwrite", "unchanged"}:
                    stamped = _stamp_global_governance_file(
                        candidate.target_path,
                        relative_path=candidate.relative_path,
                        source_root=source,
                        root=target,
                        operation="global_seed",
                        result=stamp_result,
                        enabled=stamp_governance,
                    )
                    if not stamped:
                        stamp_failed_relative_paths.add(candidate.relative_path)

            receipt["written_count"] = len(written)
            receipt["governance_stamp"].update(stamp_result)
            _mark_global_write_errors(receipt, operation="global memory seed")
            if index:
                receipt["index"] = _index_seeded_global_files(
                    target,
                    candidates,
                    db_path=db_path,
                    skip_relative_paths=stamp_failed_relative_paths,
                    audit_payload=_global_seed_audit_payload(
                        source=source,
                        target=target,
                        source_provenance="user_supplied",
                        target_provenance=target_provenance,
                        filters=receipt["filters"],
                        counts=receipt["counts"],
                        mixed_source_guard=receipt["mixed_source_guard"],
                        guard=receipt["guard"],
                        governance_stamp=receipt["governance_stamp"],
                        written=written,
                    ),
                )
                receipt["indexed"] = True
                _mark_global_write_errors(receipt, operation="global memory seed")
        except Exception as exc:  # noqa: BLE001 - any write/index failure rolls back
            receipt["rolled_back"] = _rollback_seed_writes(written, backups)
            receipt["written_count"] = 0
            receipt["ok"] = False
            receipt["error"] = f"global memory seed failed and was rolled back ({type(exc).__name__})"
            return receipt
    return receipt


def _rollback_seed_writes(
    written: list[GlobalSeedCandidate], backups: dict[Path, Path]
) -> dict[str, int]:
    """Undo seed copies/overwrites after a failed write/index step (gsr-05).

    New files (action 'copy') are removed; overwritten files are restored from
    their pre-seed backup. Source files are untouched, so a rolled-back run can be
    safely retried.
    """
    restored = 0
    removed = 0
    for candidate in written:
        target = candidate.target_path
        try:
            if candidate.action == "overwrite" and target in backups:
                shutil.copy2(backups[target], target)
                restored += 1
            elif candidate.action == "copy":
                target.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return {"restored_overwrites": restored, "removed_new_files": removed}


def reindex_global_memory_corpus(
    *,
    target_root: str | Path | None = None,
    db_path: str | Path | None = None,
    write: bool = False,
    prune_missing: bool = False,
    stamp_governance: bool = True,
    guard: bool = True,
    include_patterns: list[str] | tuple[str, ...] | None = None,
    exclude_patterns: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Plan or update DB indexes for markdown files under one global memory root."""
    root, root_provenance = _resolve_cli_global_root(target_root)
    db = _resolve_cli_db_path(db_path)
    db_provenance = _path_provenance(db_path)
    if not root.exists() or not root.is_dir():
        return {
            "ok": False,
            "error": "global root does not exist or is not a directory",
            "root": _root_payload(root, provenance=root_provenance),
            "db": _root_payload(db, provenance=db_provenance),
            "global_root_provenance": root_provenance,
        }

    include = _normalize_patterns(include_patterns or [])
    exclude = _normalize_patterns(exclude_patterns or [])
    root_files = _discover_root_markdown_files(root)
    selected_files: list[tuple[str, Path]] = []
    skipped_files: list[dict[str, str]] = []
    for relative, path in root_files:
        if include and not _matches_any(relative, include):
            skipped_files.append({"relative_path": relative, "reason": "not included"})
            continue
        if exclude and _matches_any(relative, exclude):
            skipped_files.append({"relative_path": relative, "reason": "excluded"})
            continue
        selected_files.append((relative, path))
    guard_preview = _plan_global_file_guard(selected_files, enabled=guard)
    governance_stamp_preview = _plan_global_reindex_governance_stamps(
        selected_files,
        root=root,
        operation="global_reindex",
        enabled=stamp_governance,
    )
    authority_preview = _global_authority_counts(
        [_global_file_governance_status(path, relative_path=relative) for relative, path in selected_files]
    )

    existing_rows = _global_indexed_rows_under_root(db, root)
    prune_candidates = [
        row for row in existing_rows
        if not row["exists"] and _selected_by_filters(row["relative_path"], include, exclude)
    ]
    receipt: dict[str, Any] = {
        "ok": True,
        "write": bool(write),
        "root": _root_payload(root, provenance=root_provenance),
        "db": _root_payload(db, provenance=db_provenance),
        "global_root_provenance": root_provenance,
        "filters": {
            "include_patterns": include,
            "exclude_patterns": exclude,
        },
        "counts": {
            "markdown_file_count": len(root_files),
            "selected_file_count": len(selected_files),
            "skipped_file_count": len(skipped_files),
            "existing_indexed_under_root_count": len(existing_rows),
            "prune_candidate_count": len(prune_candidates),
        },
        "guard": guard_preview,
        "authority": authority_preview,
        "governance_stamp": governance_stamp_preview,
        "files": [{"relative_path": relative, "action": "index"} for relative, _path in selected_files],
        "skipped_files": skipped_files,
        "prune_candidates": [
            _prune_candidate_payload(row)
            for row in prune_candidates
        ],
    }
    if not write:
        return receipt
    if guard_preview["blocked_count"]:
        receipt["ok"] = False
        receipt["error"] = "global memory guard blocked selected files"
        return receipt

    from .memory import init_memory_tables

    conn = sqlite3.connect(str(db))
    indexed = 0
    changed = 0
    pruned = 0
    errors: list[dict[str, str]] = []
    skipped_due_to_stamp: list[str] = []
    stamp_result = _empty_stamp_result(enabled=stamp_governance)
    try:
        init_memory_tables(conn)
        for relative, path in selected_files:
            try:
                stamped = _stamp_global_governance_file(
                    path,
                    relative_path=relative,
                    source_root=None,
                    root=root,
                    operation="global_reindex",
                    result=stamp_result,
                    enabled=stamp_governance,
                )
                if not stamped:
                    skipped_due_to_stamp.append(relative)
                    continue
                changed_file, _file_id = _index_global_memory_file(conn, relative_path=relative, path=path)
                if changed_file:
                    changed += 1
                indexed += 1
            except Exception as exc:  # pragma: no cover - defensive boundary for CLI receipts
                errors.append({"relative_path": relative, "error": exc.__class__.__name__})
        if prune_missing and prune_candidates:
            pruned = _delete_memory_file_rows(conn, [int(row["id"]) for row in prune_candidates])
        _record_global_corpus_audit(
            conn,
            "global_reindex_written",
            payload=_global_reindex_audit_payload(
                root=root,
                root_provenance=root_provenance,
                filters=receipt["filters"],
                counts=receipt["counts"],
                selected_files=selected_files,
                guard=receipt["guard"],
                governance_stamp={**receipt["governance_stamp"], **stamp_result},
                index={
                    "indexed_count": indexed,
                    "changed_count": changed,
                    "error_count": len(errors),
                    "skipped_count": len(skipped_due_to_stamp),
                },
                prune={
                    "enabled": bool(prune_missing),
                    "pruned_count": pruned,
                },
            ),
        )
        conn.commit()
    finally:
        conn.close()
    receipt["index"] = {
        "indexed_count": indexed,
        "changed_count": changed,
        "error_count": len(errors),
        "errors": errors,
        "skipped_count": len(skipped_due_to_stamp),
        "skipped_relative_paths": _relative_paths(skipped_due_to_stamp),
    }
    receipt["governance_stamp"].update(stamp_result)
    receipt["prune"] = {
        "enabled": bool(prune_missing),
        "pruned_count": pruned,
    }
    _mark_global_write_errors(receipt, operation="global memory reindex")
    return receipt


def cli_global_memory_root(value: str | Path | None = None) -> Path:
    """Resolve the operator CLI global root without requiring sidecar env inheritance."""
    root, _provenance = _resolve_cli_global_root(value)
    return root


def _resolve_cli_global_root(value: str | Path | None = None) -> tuple[Path, str]:
    if value:
        return Path(value).expanduser().resolve(), "user_supplied"
    configured = os.environ.get("CHIMERA_MEMORY_GLOBAL_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(), "live"
    return Path(DEFAULT_CLI_GLOBAL_ROOT).expanduser().resolve(), "fallback"


def _resolve_cli_db_path(value: str | Path | None = None) -> Path:
    if value:
        # Expand env vars too (e.g. %USERPROFILE% on Windows), matching every
        # other DB-path resolution; expanduser-only made env-var paths resolve to
        # a literal non-existent path so the global review-queue doctor check
        # falsely reported the queue unavailable (codex-setup-5).
        return Path(os.path.expandvars(os.path.expanduser(str(value))))
    return Path.home() / ".chimera-memory" / "transcript.db"


def _path_provenance(value: str | Path | None = None) -> str:
    return "user_supplied" if value else "fallback"


def _path_within_root(resolved: Path, root_resolved: Path) -> bool:
    # rglob follows symlinked DIRECTORIES, so a file reached through one can sit
    # outside the root even though it is not itself a symlink. Require the resolved
    # path to stay under the resolved root (gsr-03).
    return resolved == root_resolved or root_resolved in resolved.parents


def _discover_root_markdown_files(root: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    root_resolved = root.resolve(strict=False)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve(strict=False)
        if not _path_within_root(resolved, root_resolved):
            continue
        if _should_skip_path(root, path):
            continue
        if path.suffix.lower() not in INDEX_EXTENSIONS:
            continue
        files.append((str(path.relative_to(root)).replace("\\", "/"), resolved))
    return sorted(files, key=lambda item: item[0])


def _file_is_present_or_uncertain(path: Path) -> bool:
    """Conservative presence check used to gate pruning.

    Returns True if the file exists OR if we cannot confidently confirm it is
    genuinely gone. Only a listable parent directory that does not contain the
    file counts as a real absence; a missing/inaccessible parent (network blip,
    permission hiccup) is transient and must NOT trigger a prune (gsr-11).
    """
    try:
        if path.exists():
            return True
        parent = path.parent
        if not parent.exists() or not parent.is_dir():
            return True  # parent gone/inaccessible -> cannot confirm absence
        try:
            next(parent.iterdir(), None)  # parent is listable
        except OSError:
            return True  # parent not listable -> transient, keep
        return False  # parent listable and file absent -> genuinely removed
    except OSError:
        return True  # any FS error -> conservative keep


def _global_indexed_rows_under_root(db_path: Path, root: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(conn, "memory_files"):
            return []
        rows = conn.execute(
            """
            SELECT id, path, relative_path
            FROM memory_files
            WHERE COALESCE(memory_scope, '') = 'global'
            """
        ).fetchall()
    finally:
        conn.close()
    result: list[dict[str, Any]] = []
    for file_id, path_text, _stored_relative_path in rows:
        path = Path(str(path_text or ""))
        try:
            resolved = path.resolve(strict=False)
            root_relative = str(resolved.relative_to(root)).replace("\\", "/")
        except (OSError, ValueError):
            continue
        # The resolved path under the selected root is live authority; the DB
        # relative_path can drift across imports, migrations, or manual repair.
        result.append(
            {
                "id": int(file_id),
                "path": str(resolved),
                "relative_path": root_relative,
                # Conservative: only confidently-absent files are prune
                # candidates; transiently-missing ones are kept (gsr-11).
                "exists": _file_is_present_or_uncertain(resolved),
            }
        )
    return sorted(result, key=lambda row: str(row["relative_path"]))


def _selected_by_filters(relative_path: str, include_patterns: list[str], exclude_patterns: list[str]) -> bool:
    if include_patterns and not _matches_any(relative_path, include_patterns):
        return False
    if exclude_patterns and _matches_any(relative_path, exclude_patterns):
        return False
    return True


def _delete_memory_file_rows(conn: sqlite3.Connection, file_ids: list[int]) -> int:
    if not file_ids:
        return 0
    placeholders = ",".join("?" for _ in file_ids)
    if _table_exists(conn, "memory_fts"):
        conn.execute(f"DELETE FROM memory_fts WHERE rowid IN ({placeholders})", file_ids)
    for table in (
        "memory_embeddings",
        "memory_file_source_refs",
        "memory_file_artifacts",
        "memory_file_entities",
        "memory_pyramid_summaries",
    ):
        if _table_exists(conn, table):
            conn.execute(f"DELETE FROM {table} WHERE file_id IN ({placeholders})", file_ids)
    if _table_exists(conn, "memory_file_edges"):
        conn.execute(
            f"DELETE FROM memory_file_edges WHERE source_file_id IN ({placeholders}) OR target_file_id IN ({placeholders})",
            [*file_ids, *file_ids],
        )
    for table in ("memory_recall_items", "memory_review_actions", "memory_enhancement_jobs"):
        if _table_exists(conn, table):
            conn.execute(f"UPDATE {table} SET file_id = NULL WHERE file_id IN ({placeholders})", file_ids)
    cursor = conn.execute(f"DELETE FROM memory_files WHERE id IN ({placeholders})", file_ids)
    return int(cursor.rowcount or 0)


def _global_seed_audit_payload(
    *,
    source: Path,
    target: Path,
    source_provenance: str,
    target_provenance: str,
    filters: dict[str, list[str]],
    counts: dict[str, int],
    mixed_source_guard: dict[str, Any],
    guard: dict[str, Any],
    governance_stamp: dict[str, Any],
    written: list[GlobalSeedCandidate],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "global_seed",
        "source": _root_payload(source, provenance=source_provenance),
        "target": _root_payload(target, provenance=target_provenance),
        "filters": filters,
        "counts": counts,
        "mixed_source_guard": _mixed_source_audit_payload(mixed_source_guard),
        "guard": _guard_audit_payload(guard),
        "governance_stamp": _stamp_audit_payload(governance_stamp),
        "written_count": len(written),
        "written_relative_paths": _relative_paths([candidate.relative_path for candidate in written]),
    }


def _global_reindex_audit_payload(
    *,
    root: Path,
    root_provenance: str,
    filters: dict[str, list[str]],
    counts: dict[str, int],
    selected_files: list[tuple[str, Path]],
    guard: dict[str, Any],
    governance_stamp: dict[str, Any],
    index: dict[str, int],
    prune: dict[str, int | bool],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "global_reindex",
        "target": _root_payload(root, provenance=root_provenance),
        "filters": filters,
        "counts": counts,
        "guard": _guard_audit_payload(guard),
        "governance_stamp": _stamp_audit_payload(governance_stamp),
        "selected_relative_paths": _relative_paths([relative for relative, _path in selected_files]),
        "index": index,
        "prune": prune,
    }


def _mark_global_write_errors(receipt: dict[str, Any], *, operation: str) -> None:
    index_result = receipt.get("index") if isinstance(receipt.get("index"), dict) else {}
    governance_stamp = receipt.get("governance_stamp") if isinstance(receipt.get("governance_stamp"), dict) else {}
    counts = receipt.get("counts") if isinstance(receipt.get("counts"), dict) else {}
    conflicts = int(counts.get("conflict") or 0)
    index_errors = int(index_result.get("error_count") or 0)
    index_skipped = int(index_result.get("skipped_count") or 0)
    stamp_errors = int(governance_stamp.get("error_count") or 0)
    if not conflicts and not index_errors and not index_skipped and not stamp_errors:
        return
    parts: list[str] = []
    if conflicts:
        parts.append(f"conflict_count={conflicts}")
    if stamp_errors:
        parts.append(f"governance_stamp_error_count={stamp_errors}")
    if index_errors:
        parts.append(f"index_error_count={index_errors}")
    if index_skipped:
        parts.append(f"index_skipped_count={index_skipped}")
    receipt["ok"] = False
    receipt["error"] = f"{operation} completed with errors: {', '.join(parts)}"


def _root_payload(path: Path, *, provenance: str) -> dict[str, str]:
    text = str(path)
    return {
        "name": path.name,
        "provenance": provenance,
        "fingerprint": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    }


def _relative_paths(paths: list[str], *, limit: int = 50) -> list[str]:
    return sorted(str(path).replace("\\", "/") for path in paths)[:limit]


def _safe_relative_path_label(value: object, *, fallback_path: object = "") -> str:
    return safe_memory_relative_path_display(value, fallback_path=fallback_path) or safe_filename_label(fallback_path)


def _outside_root_row_payload(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": path.name,
        "relative_path": _safe_relative_path_label(row.get("relative_path"), fallback_path=path),
        "path_fingerprint": hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16],
        "available": bool(row.get("available")),
    }


def _prune_candidate_payload(row: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(row.get("path") or ""))
    return {
        "name": path.name,
        "relative_path": _safe_relative_path_label(row.get("relative_path"), fallback_path=path),
        "path_fingerprint": hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16],
    }


def _record_global_corpus_audit(conn: sqlite3.Connection, event_type: str, *, payload: dict[str, Any]) -> None:
    from .memory_observability import record_memory_audit_event

    record_memory_audit_event(
        conn,
        event_type,
        persona=None,
        target_kind="global_corpus",
        target_id=str(payload.get("target", {}).get("fingerprint") or ""),
        payload=payload,
        actor="cli",
        commit=False,
    )


def _global_db_counts(db_path: Path) -> tuple[dict[str, int | bool], dict[str, dict[str, Any]]]:
    counts: dict[str, int | bool] = {
        "initialized": False,
        "global_indexed_file_count": 0,
        "global_available_file_count": 0,
        "global_instruction_grade_file_count": 0,
    }
    indexed: dict[str, dict[str, Any]] = {}
    if not db_path.exists():
        return counts, indexed
    conn = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(conn, "memory_files"):
            return counts, indexed
        counts["initialized"] = True
        rows = conn.execute(
            """
            SELECT path, relative_path,
                   COALESCE(fm_exclude_from_default_search, 0),
                   COALESCE(fm_can_use_as_evidence, 1),
                   COALESCE(fm_sensitivity_tier, 'standard'),
                   COALESCE(fm_lifecycle_status, 'active'),
                   COALESCE(fm_can_use_as_instruction, 1),
                   COALESCE(fm_review_status, 'confirmed'),
                   COALESCE(fm_provenance_status, 'imported')
            FROM memory_files
            WHERE COALESCE(memory_scope, '') = 'global'
            """
        ).fetchall()
    finally:
        conn.close()
    available = 0
    instruction_grade = 0
    for (
        path,
        relative_path,
        exclude_default,
        can_evidence,
        sensitivity,
        lifecycle,
        can_instruction,
        review_status,
        provenance_status,
    ) in rows:
        is_available = _is_default_available(
            exclude_default=exclude_default,
            can_evidence=can_evidence,
            sensitivity=sensitivity,
            lifecycle=lifecycle,
        )
        is_instruction_grade = _is_instruction_grade_available(
            available=is_available,
            can_instruction=can_instruction,
            review_status=review_status,
            provenance_status=provenance_status,
        )
        if is_available:
            available += 1
        if is_instruction_grade:
            instruction_grade += 1
        indexed[str(path or "").replace("\\", "/")] = {
            "relative_path": str(relative_path or ""),
            "available": is_available,
            "instruction_grade_available": is_instruction_grade,
        }
    counts["global_indexed_file_count"] = len(rows)
    counts["global_available_file_count"] = available
    counts["global_instruction_grade_file_count"] = instruction_grade
    return counts, indexed


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _is_default_available(
    *,
    exclude_default: object,
    can_evidence: object,
    sensitivity: object,
    lifecycle: object,
) -> bool:
    return (
        int(exclude_default or 0) == 0
        and int(can_evidence if can_evidence is not None else 1) == 1
        and str(sensitivity or "standard") != "restricted"
        and str(lifecycle or "active") not in {"disputed", "rejected", "superseded"}
    )


def _is_instruction_grade_available(
    *,
    available: bool,
    can_instruction: object,
    review_status: object,
    provenance_status: object,
) -> bool:
    return (
        bool(available)
        and int(can_instruction if can_instruction is not None else 1) == 1
        and str(review_status or "confirmed").strip() == "confirmed"
        and str(provenance_status or "imported").strip() in INSTRUCTION_GRADE_PROVENANCE
    )


def _validate_roots(
    source: Path,
    target: Path,
    *,
    source_provenance: str = "user_supplied",
    target_provenance: str = "target",
) -> dict[str, Any] | None:
    if not source.exists() or not source.is_dir():
        return {
            "ok": False,
            "error": "source root does not exist or is not a directory",
            "source": _root_payload(source, provenance=source_provenance),
            "target": _root_payload(target, provenance=target_provenance),
        }
    try:
        source.relative_to(target)
    except ValueError:
        source_inside_target = False
    else:
        source_inside_target = True
    try:
        target.relative_to(source)
    except ValueError:
        target_inside_source = False
    else:
        target_inside_source = True
    if source == target or source_inside_target or target_inside_source:
        return {
            "ok": False,
            "error": "source and target roots must be separate directories",
            "source": _root_payload(source, provenance=source_provenance),
            "target": _root_payload(target, provenance=target_provenance),
        }
    return None


def _normalize_patterns(patterns: list[str] | tuple[str, ...]) -> list[str]:
    normalized = []
    for pattern in patterns:
        text = str(pattern or "").strip().replace("\\", "/").lstrip("/")
        if text:
            normalized.append(text)
    return normalized


def _discover_seed_candidates(
    source: Path,
    target: Path,
    *,
    overwrite: bool,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> list[GlobalSeedCandidate]:
    candidates: list[GlobalSeedCandidate] = []
    source_resolved = source.resolve(strict=False)
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            candidates.append(_candidate(source, target, path, "skip", "symlink"))
            continue
        if not _path_within_root(path.resolve(strict=False), source_resolved):
            # Reached through a symlinked directory -> outside the source (gsr-03).
            candidates.append(_candidate(source, target, path, "skip", "outside source root"))
            continue
        if _should_skip_path(source, path):
            candidates.append(_candidate(source, target, path, "skip", "skipped directory"))
            continue
        if path.suffix.lower() not in INDEX_EXTENSIONS:
            candidates.append(_candidate(source, target, path, "skip", "unsupported extension"))
            continue
        current = _candidate(source, target, path, "copy")
        if include_patterns and not _matches_any(current.relative_path, include_patterns):
            candidates.append(GlobalSeedCandidate(path, current.target_path, current.relative_path, "skip", "not included"))
            continue
        if exclude_patterns and _matches_any(current.relative_path, exclude_patterns):
            candidates.append(GlobalSeedCandidate(path, current.target_path, current.relative_path, "skip", "excluded"))
            continue
        if current.target_path.exists():
            if _same_bytes(path, current.target_path) or _same_global_seed_payload(path, current.target_path):
                current = GlobalSeedCandidate(path, current.target_path, current.relative_path, "unchanged")
            elif overwrite:
                current = GlobalSeedCandidate(path, current.target_path, current.relative_path, "overwrite")
            else:
                current = GlobalSeedCandidate(path, current.target_path, current.relative_path, "conflict", "target exists")
        candidates.append(current)
    return candidates


def _matches_any(relative_path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(relative_path, pattern) for pattern in patterns)


def _candidate(source: Path, target: Path, path: Path, action: str, reason: str = "") -> GlobalSeedCandidate:
    rel = path.relative_to(source)
    relative_text = str(rel).replace("\\", "/")
    return GlobalSeedCandidate(path, target / rel, relative_text, action, reason)


def _should_skip_path(source: Path, path: Path) -> bool:
    rel = path.relative_to(source)
    return any(part.lower() in SKIP_DIRS or part.startswith(".") for part in rel.parts)


def _same_bytes(first: Path, second: Path) -> bool:
    try:
        return first.read_bytes() == second.read_bytes()
    except OSError:
        return False


def _same_global_seed_payload(source: Path, target: Path) -> bool:
    try:
        source_text = source.read_text(encoding="utf-8", errors="replace")
        target_text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    source_split = _split_frontmatter_preserving_body(source_text)
    target_split = _split_frontmatter_preserving_body(target_text)
    if not source_split.get("ok") or not target_split.get("ok"):
        return False
    if _normalize_newlines(str(source_split.get("body") or "")) != _normalize_newlines(str(target_split.get("body") or "")):
        return False

    source_fm = dict(source_split.get("frontmatter") or {})
    target_fm = dict(target_split.get("frontmatter") or {})
    if _is_trusted_instruction_frontmatter(source_fm) and not _is_trusted_instruction_frontmatter(target_fm):
        return False
    if _global_governance_status(target_fm).get("stamp_recommended"):
        return False
    return _seed_comparable_frontmatter(source_fm) == _seed_comparable_frontmatter(target_fm)


def _seed_comparable_frontmatter(frontmatter: Mapping[str, Any]) -> dict[str, Any]:
    ignored = set(GLOBAL_GOVERNANCE_REQUIRED_KEYS) | {"global_governance_stamp"}
    return {key: value for key, value in dict(frontmatter).items() if key not in ignored}


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _candidate_counts(candidates: list[GlobalSeedCandidate]) -> dict[str, int]:
    counts = {
        "discovered": len(candidates),
        "copy": 0,
        "overwrite": 0,
        "unchanged": 0,
        "conflict": 0,
        "skip": 0,
    }
    for candidate in candidates:
        counts[candidate.action] = counts.get(candidate.action, 0) + 1
    counts["writable"] = counts["copy"] + counts["overwrite"]
    return counts


def _candidate_payload(candidate: GlobalSeedCandidate) -> dict[str, str]:
    payload = {
        "relative_path": candidate.relative_path,
        "action": candidate.action,
    }
    if candidate.reason:
        payload["reason"] = candidate.reason
    return payload


def _plan_global_seed_guard(
    candidates: list[GlobalSeedCandidate],
    *,
    enabled: bool,
) -> dict[str, Any]:
    selected: list[tuple[str, Path]] = []
    for candidate in candidates:
        if candidate.action in {"copy", "overwrite"}:
            selected.append((candidate.relative_path, candidate.source_path))
        elif candidate.action == "unchanged" and candidate.target_path.exists():
            selected.append((candidate.relative_path, candidate.target_path))
    return _plan_global_file_guard(selected, enabled=enabled)


def _plan_mixed_source_guard(
    candidates: list[GlobalSeedCandidate],
    *,
    include_patterns: list[str],
    allow_mixed_source: bool,
) -> dict[str, Any]:
    selected = [
        candidate
        for candidate in candidates
        if candidate.action in {"copy", "overwrite", "unchanged"}
    ]
    findings = [
        finding
        for candidate in selected
        for finding in _mixed_source_findings(candidate.relative_path)
    ]
    explicit_include = bool(include_patterns)
    blocked = [
        finding
        for finding in findings
        if not allow_mixed_source
        and not _mixed_source_finding_explicitly_included(
            str(finding.get("relative_path") or ""),
            include_patterns,
        )
    ]
    return {
        "enabled": True,
        "allow_mixed_source": bool(allow_mixed_source),
        "explicit_include": explicit_include,
        "candidate_count": len(selected),
        "finding_count": len(findings),
        "blocked_count": len(blocked),
        "blocked_relative_paths": _relative_paths([str(item["relative_path"]) for item in blocked]),
        "findings": findings[:50],
        "policy": (
            "explicit_include_or_allow_required"
            if blocked
            else "allowed"
        ),
    }


def _mixed_source_finding_explicitly_included(relative_path: str, include_patterns: list[str]) -> bool:
    path_text = str(relative_path or "").replace("\\", "/")
    for pattern in include_patterns:
        pattern_text = str(pattern or "").replace("\\", "/").strip()
        if not pattern_text or not _matches_any(path_text, [pattern_text]):
            continue
        if _include_pattern_mentions_mixed_source(pattern_text):
            return True
    return False


def _include_pattern_mentions_mixed_source(pattern: str) -> bool:
    for part in str(pattern or "").replace("\\", "/").split("/"):
        normalized = part.strip().lower().replace("_", "-")
        stem = Path(part).stem.strip().lower().replace("_", "-")
        if normalized in MIXED_SOURCE_SEGMENTS or stem in MIXED_SOURCE_SEGMENTS:
            return True
        if any(normalized.startswith(prefix.replace("_", "-")) for prefix in MIXED_SOURCE_PREFIXES):
            return True
    return False


def _mixed_source_findings(relative_path: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    parts = str(relative_path or "").replace("\\", "/").split("/")
    for part in parts:
        normalized = part.strip().lower().replace("_", "-")
        stem = Path(part).stem.strip().lower().replace("_", "-")
        if normalized in MIXED_SOURCE_SEGMENTS or stem in MIXED_SOURCE_SEGMENTS:
            findings.append(
                {
                    "relative_path": relative_path,
                    "matched_part": part,
                    "reason": "mixed shared/persona path segment",
                }
            )
            continue
        if any(normalized.startswith(prefix.replace("_", "-")) for prefix in MIXED_SOURCE_PREFIXES):
            findings.append(
                {
                    "relative_path": relative_path,
                    "matched_part": part,
                    "reason": "persona/private filename prefix",
                }
            )
    return findings


def _plan_global_file_guard(
    selected_files: list[tuple[str, Path]],
    *,
    enabled: bool,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "enabled": bool(enabled),
        "candidate_count": len(selected_files),
        "blocked_count": 0,
        "finding_count": 0,
        "blocked_relative_paths": [],
        "findings": [],
    }
    if not enabled:
        return receipt
    for relative, path in selected_files:
        item = _scan_global_guard_file(path, relative_path=relative)
        if item["findings"]:
            receipt["blocked_count"] += 1
            receipt["blocked_relative_paths"].append(relative)
            receipt["finding_count"] += len(item["findings"])
            receipt["findings"].append(item)
    receipt["blocked_relative_paths"] = _relative_paths(receipt["blocked_relative_paths"])
    return receipt


def _scan_global_guard_file(path: Path, *, relative_path: str) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "relative_path": relative_path,
            "findings": [
                {
                    "type": "read_error",
                    "match_count": 1,
                    "error": exc.__class__.__name__,
                }
            ],
        }
    findings = [
        {
            "type": str(finding.get("type") or "unknown"),
            "match_count": int(finding.get("match_count") or 1),
        }
        for finding in scan_for_injection(content)
    ]
    return {"relative_path": relative_path, "findings": findings}


def _plan_global_governance_stamps(
    candidates: list[GlobalSeedCandidate],
    *,
    source_root: Path,
    target_root: Path,
    operation: str,
    enabled: bool,
) -> dict[str, Any]:
    eligible = [
        candidate for candidate in candidates
        if candidate.action in {"copy", "overwrite", "unchanged"}
    ]
    result = _empty_stamp_preview(enabled=enabled, candidate_count=len(eligible))
    if not enabled:
        return result
    for candidate in eligible:
        path = candidate.target_path if candidate.action == "unchanged" and candidate.target_path.exists() else candidate.source_path
        status = _global_file_governance_status(path, relative_path=candidate.relative_path)
        if status["stamp_recommended"]:
            result["would_change_count"] += 1
            result["would_change_relative_paths"].append(candidate.relative_path)
        if status["parse_error"]:
            result["parse_error_count"] += 1
    result["would_change_relative_paths"] = _relative_paths(result["would_change_relative_paths"])
    result["operation"] = operation
    result["target"] = _root_payload(target_root, provenance="target")
    result["source"] = _root_payload(source_root, provenance="user_supplied")
    return result


def _plan_global_reindex_governance_stamps(
    selected_files: list[tuple[str, Path]],
    *,
    root: Path,
    operation: str,
    enabled: bool,
) -> dict[str, Any]:
    result = _empty_stamp_preview(enabled=enabled, candidate_count=len(selected_files))
    if not enabled:
        return result
    for relative, path in selected_files:
        status = _global_file_governance_status(path, relative_path=relative)
        if status["stamp_recommended"]:
            result["would_change_count"] += 1
            result["would_change_relative_paths"].append(relative)
        if status["parse_error"]:
            result["parse_error_count"] += 1
    result["would_change_relative_paths"] = _relative_paths(result["would_change_relative_paths"])
    result["operation"] = operation
    result["target"] = _root_payload(root, provenance="target")
    return result


def _empty_stamp_preview(*, enabled: bool, candidate_count: int) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "schema_version": GLOBAL_GOVERNANCE_STAMP_SCHEMA_VERSION,
        "candidate_count": candidate_count,
        "would_change_count": 0,
        "parse_error_count": 0,
        "would_change_relative_paths": [],
    }


def _empty_stamp_result(*, enabled: bool) -> dict[str, Any]:
    return {
        "changed_count": 0,
        "unchanged_count": 0,
        "error_count": 0,
        "changed_relative_paths": [],
        "errors": [],
        "enabled": bool(enabled),
    }


def _stamp_global_governance_file(
    path: Path,
    *,
    relative_path: str,
    source_root: Path | None,
    root: Path,
    operation: str,
    result: dict[str, Any],
    enabled: bool,
) -> bool:
    if not enabled:
        return True
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        stamped = _stamp_global_governance_content(
            content,
            relative_path=relative_path,
            source_root=source_root,
            root=root,
            operation=operation,
        )
        if stamped["changed"]:
            path.write_text(str(stamped["content"]), encoding="utf-8", newline="\n")
            result["changed_count"] += 1
            result["changed_relative_paths"].append(relative_path)
        else:
            result["unchanged_count"] += 1
    except OSError as exc:
        result["error_count"] += 1
        result["errors"].append({"relative_path": relative_path, "error": exc.__class__.__name__})
        result["changed_relative_paths"] = _relative_paths(result["changed_relative_paths"])
        return False
    result["changed_relative_paths"] = _relative_paths(result["changed_relative_paths"])
    return True


def _stamp_global_governance_content(
    content: str,
    *,
    relative_path: str,
    source_root: Path | None,
    root: Path,
    operation: str,
) -> dict[str, Any]:
    split = _split_frontmatter_preserving_body(content)
    frontmatter = dict(split.get("frontmatter") or {})
    body = str(split.get("body") if split.get("ok") else content)
    status = _global_governance_status(frontmatter, parse_error=str(split.get("error") or ""))
    if not status["stamp_recommended"]:
        return {"changed": False, "content": content, "status": status}

    stamped = dict(frontmatter)
    trusted_instruction = _is_trusted_instruction_frontmatter(stamped)
    stamped["memory_scope"] = "global"
    stamped.setdefault("provenance_status", "imported")
    stamped.setdefault("lifecycle_status", str(stamped.get("status") or "active"))
    stamped.setdefault("review_status", "pending")
    stamped.setdefault("sensitivity_tier", "standard")
    stamped.setdefault("can_use_as_evidence", True)
    if trusted_instruction:
        stamped.setdefault("requires_user_confirmation", False)
    else:
        stamped["can_use_as_instruction"] = False
        stamped["requires_user_confirmation"] = True
    stamped["global_governance_stamp"] = {
        "schema_version": GLOBAL_GOVERNANCE_STAMP_SCHEMA_VERSION,
        "operation": operation,
        "policy": "global_imports_are_evidence_only_until_reviewed",
        "relative_path": relative_path,
        "stamped_at": _utc_now(),
        "target": _root_payload(root, provenance="global_root"),
    }
    if source_root is not None:
        stamped["global_governance_stamp"]["source"] = _root_payload(
            source_root,
            provenance="user_supplied",
        )
    return {
        "changed": True,
        "content": _render_frontmatter_markdown(stamped, body),
        "status": status,
    }


def _global_file_governance_status(path: Path, *, relative_path: str) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "relative_path": relative_path,
            "parse_error": exc.__class__.__name__,
            "missing_required_keys": sorted(GLOBAL_GOVERNANCE_REQUIRED_KEYS),
            "provenance_status": "imported",
            "review_status": "pending",
            "sensitivity_tier": "standard",
            "can_use_as_instruction": False,
            "can_use_as_evidence": True,
            "requires_user_confirmation": True,
            "trusted_instruction_grade": False,
            "unsafe_instruction_grade": False,
            "stamp_recommended": True,
        }
    split = _split_frontmatter_preserving_body(content)
    frontmatter = dict(split.get("frontmatter") or {})
    return {
        "relative_path": relative_path,
        **_global_governance_status(frontmatter, parse_error=str(split.get("error") or "")),
    }


def _global_governance_status(frontmatter: Mapping[str, Any], *, parse_error: str = "") -> dict[str, Any]:
    missing = sorted(key for key in GLOBAL_GOVERNANCE_REQUIRED_KEYS if key not in frontmatter)
    memory_scope = str(frontmatter.get("memory_scope") or "").strip().lower()
    if parse_error or not frontmatter:
        return {
            "parse_error": parse_error,
            "missing_required_keys": missing,
            "provenance_status": "imported",
            "review_status": "pending",
            "sensitivity_tier": "standard",
            "can_use_as_instruction": False,
            "can_use_as_evidence": True,
            "requires_user_confirmation": True,
            "trusted_instruction_grade": False,
            "unsafe_instruction_grade": False,
            "stamp_recommended": True,
        }

    governance = governance_from_frontmatter(dict(frontmatter))
    raw_instruction_requested = _optional_bool(frontmatter.get("can_use_as_instruction")) is True
    instruction_grade = bool(governance["can_use_as_instruction"])
    trusted_instruction = _is_trusted_instruction_frontmatter(frontmatter)
    unsafe_instruction = raw_instruction_requested and not trusted_instruction
    stamp_recommended = bool(parse_error or missing or memory_scope != "global" or unsafe_instruction)
    return {
        "parse_error": parse_error,
        "missing_required_keys": missing,
        "provenance_status": governance["provenance_status"],
        "review_status": governance["review_status"],
        "sensitivity_tier": governance["sensitivity_tier"],
        "can_use_as_instruction": instruction_grade,
        "can_use_as_evidence": bool(governance["can_use_as_evidence"]),
        "requires_user_confirmation": bool(governance["requires_user_confirmation"]),
        "trusted_instruction_grade": trusted_instruction,
        "unsafe_instruction_grade": unsafe_instruction,
        "stamp_recommended": stamp_recommended,
    }


def _global_governance_counts(statuses: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "file_count": len(statuses),
        "parse_error_count": sum(1 for status in statuses if status.get("parse_error")),
        "missing_required_governance_count": sum(1 for status in statuses if status.get("missing_required_keys")),
        "instruction_grade_file_count": sum(1 for status in statuses if status.get("can_use_as_instruction")),
        "unsafe_instruction_grade_file_count": sum(1 for status in statuses if status.get("unsafe_instruction_grade")),
        "stamp_recommended_file_count": sum(1 for status in statuses if status.get("stamp_recommended")),
    }


def _global_authority_counts(statuses: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "file_count": len(statuses),
        "evidence_enabled_file_count": sum(1 for status in statuses if status.get("can_use_as_evidence")),
        "non_evidence_file_count": sum(1 for status in statuses if not status.get("can_use_as_evidence")),
        "instruction_enabled_file_count": sum(1 for status in statuses if status.get("can_use_as_instruction")),
        "trusted_instruction_grade_file_count": sum(
            1 for status in statuses if status.get("trusted_instruction_grade")
        ),
        "pending_review_file_count": sum(
            1 for status in statuses if str(status.get("review_status") or "") == "pending"
        ),
        "evidence_only_review_file_count": sum(
            1 for status in statuses if str(status.get("review_status") or "") == "evidence_only"
        ),
        "requires_user_confirmation_file_count": sum(
            1 for status in statuses if status.get("requires_user_confirmation")
        ),
        "unsafe_instruction_grade_file_count": sum(
            1 for status in statuses if status.get("unsafe_instruction_grade")
        ),
    }


def _is_trusted_instruction_frontmatter(frontmatter: Mapping[str, Any]) -> bool:
    memory_scope = str(frontmatter.get("memory_scope") or "").strip().lower()
    provenance = str(frontmatter.get("provenance_status") or "").strip()
    review = str(frontmatter.get("review_status") or "").strip()
    instruction = _optional_bool(frontmatter.get("can_use_as_instruction"))
    return (
        memory_scope == "global"
        and provenance in INSTRUCTION_GRADE_PROVENANCE
        and review == "confirmed"
        and instruction is True
    )


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _split_frontmatter_preserving_body(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {"ok": True, "frontmatter": {}, "body": text, "had_frontmatter": False}

    if text.startswith("---\r\n"):
        newline = "\r\n"
    elif text.startswith("---\n"):
        newline = "\n"
    else:
        return {"ok": True, "frontmatter": {}, "body": text, "had_frontmatter": False}

    marker = f"{newline}---"
    end = text.find(marker, len(f"---{newline}"))
    if end == -1:
        return {
            "ok": False,
            "frontmatter": {},
            "body": text,
            "had_frontmatter": False,
            "error": "frontmatter_closing_marker_missing",
        }
    frontmatter_text = text[len(f"---{newline}") : end]
    body_start = end + len(marker)
    if text.startswith(newline, body_start):
        body_start += len(newline)
    body = text[body_start:]
    try:
        parsed = yaml.safe_load(frontmatter_text.strip()) or {}
    except yaml.YAMLError:
        return {
            "ok": False,
            "frontmatter": {},
            "body": text,
            "had_frontmatter": False,
            "error": "frontmatter_yaml_invalid",
        }
    if not isinstance(parsed, Mapping):
        return {
            "ok": False,
            "frontmatter": {},
            "body": text,
            "had_frontmatter": False,
            "error": "frontmatter_not_mapping",
        }
    return {"ok": True, "frontmatter": dict(parsed), "body": body, "had_frontmatter": True}


def _render_frontmatter_markdown(frontmatter: Mapping[str, Any], body: str) -> str:
    # allow_unicode keeps accented/non-Latin frontmatter values literal; files are
    # written as UTF-8, and escaping them churned content hashes and hurt
    # readability on every stamp/review touch (gsr-07).
    dumped = yaml.dump(
        dict(frontmatter),
        Dumper=_NoAliasSafeDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{dumped}\n---\n{body}"


def _stamp_audit_payload(stamp: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(stamp.get("enabled")),
        "schema_version": stamp.get("schema_version") or GLOBAL_GOVERNANCE_STAMP_SCHEMA_VERSION,
        "candidate_count": int(stamp.get("candidate_count") or 0),
        "would_change_count": int(stamp.get("would_change_count") or 0),
        "changed_count": int(stamp.get("changed_count") or 0),
        "error_count": int(stamp.get("error_count") or 0),
        "would_change_relative_paths": _relative_paths(list(stamp.get("would_change_relative_paths") or [])),
        "changed_relative_paths": _relative_paths(list(stamp.get("changed_relative_paths") or [])),
    }


def _guard_audit_payload(guard: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(guard.get("enabled")),
        "candidate_count": int(guard.get("candidate_count") or 0),
        "blocked_count": int(guard.get("blocked_count") or 0),
        "finding_count": int(guard.get("finding_count") or 0),
        "blocked_relative_paths": _relative_paths(list(guard.get("blocked_relative_paths") or [])),
    }


def _mixed_source_audit_payload(guard: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(guard.get("enabled")),
        "allow_mixed_source": bool(guard.get("allow_mixed_source")),
        "explicit_include": bool(guard.get("explicit_include")),
        "candidate_count": int(guard.get("candidate_count") or 0),
        "finding_count": int(guard.get("finding_count") or 0),
        "blocked_count": int(guard.get("blocked_count") or 0),
        "blocked_relative_paths": _relative_paths(list(guard.get("blocked_relative_paths") or [])),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _index_seeded_global_files(
    target: Path,
    candidates: list[GlobalSeedCandidate],
    *,
    db_path: str | Path | None,
    skip_relative_paths: set[str] | None = None,
    audit_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .memory import init_memory_tables
    from .server import get_default_db_path

    db_provenance = "user_supplied" if db_path else "fallback"
    path = Path(db_path).expanduser() if db_path else get_default_db_path()
    conn = sqlite3.connect(str(path))
    indexed = 0
    changed = 0
    skip_set = {str(relative).replace("\\", "/") for relative in (skip_relative_paths or set())}
    skipped_relative_paths = _relative_paths(list(skip_set))
    errors: list[dict[str, str]] = []
    try:
        init_memory_tables(conn)
        for candidate in candidates:
            if candidate.action not in {"copy", "overwrite", "unchanged"}:
                continue
            if candidate.relative_path in skip_set:
                continue
            if not candidate.target_path.exists():
                continue
            try:
                changed_file, _file_id = _index_global_memory_file(
                    conn,
                    relative_path=candidate.relative_path,
                    path=candidate.target_path,
                )
                if changed_file:
                    changed += 1
                indexed += 1
            except Exception as exc:  # pragma: no cover - defensive boundary for CLI receipts
                errors.append({"relative_path": candidate.relative_path, "error": exc.__class__.__name__})
        if audit_payload is not None:
            audit_payload = dict(audit_payload)
            audit_payload["index"] = {
                "indexed_count": indexed,
                "changed_count": changed,
                "error_count": len(errors),
                "skipped_count": len(skip_set),
            }
            _record_global_corpus_audit(conn, "global_seed_written", payload=audit_payload)
        conn.commit()
    finally:
        conn.close()
    return {
        "db": _root_payload(path, provenance=db_provenance),
        "target": _root_payload(target, provenance="global_root"),
        "indexed_count": indexed,
        "changed_count": changed,
        "error_count": len(errors),
        "errors": errors,
        "skipped_count": len(skip_set),
        "skipped_relative_paths": skipped_relative_paths,
    }


def _index_global_memory_file(conn: sqlite3.Connection, *, relative_path: str, path: Path) -> tuple[bool, int | None]:
    from .memory import index_file

    changed = index_file(conn, "global", relative_path, path, maintenance=True)
    row = conn.execute(
        "SELECT id FROM memory_files WHERE path = ?",
        (str(path).replace("\\", "/"),),
    ).fetchone()
    return bool(changed), int(row[0]) if row is not None else None
