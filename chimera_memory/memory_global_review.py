"""Durable review helpers for the no-persona global memory corpus."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from typing import Any

from .memory_governance import governance_from_frontmatter
from .memory_global_seed import (
    GLOBAL_GOVERNANCE_REQUIRED_KEYS,
    _discover_root_markdown_files,
    _global_db_counts,
    _global_governance_status,
    _index_global_memory_file,
    _is_default_available,
    _path_provenance,
    _render_frontmatter_markdown,
    _resolve_cli_db_path,
    _resolve_cli_global_root,
    _root_payload,
    _should_skip_path,
    _split_frontmatter_preserving_body,
    _utc_now,
)
from .memory_display import redact_local_path_references
from .memory_observability import _json_text, record_memory_audit_event
from .sanitizer import sanitize_content, scan_for_injection
from .memory_schema import init_memory_tables

GLOBAL_FRONTMATTER_REVIEW_SCHEMA_VERSION = "chimera-memory.global-frontmatter-review.v1"
GLOBAL_REVIEW_ACTION_GUIDANCE_SCHEMA_VERSION = "chimera-memory.global-review-action-guidance.v1"
GLOBAL_AUTO_PROMOTE_SCHEMA_VERSION = "chimera-memory.global-auto-promote.v1"
GLOBAL_AUTO_PROMOTE_POLICY_SCHEMA_VERSION = "chimera-memory.global-auto-promote-policy.v1"
GLOBAL_REVIEW_ACTIONS = {
    "auto_confirm",
    "confirm",
    "edit",
    "evidence_only",
    "restrict_scope",
    "mark_stale",
    "merge",
    "reject",
    "dispute",
    "supersede",
}
GLOBAL_REVIEW_REASONS = {
    "confirm_guard_blocked",
    "missing_required_governance",
    "non_global_scope",
    "parse_error",
    "pending_review",
    "requires_user_confirmation",
    "stamp_recommended",
    "unsafe_instruction_grade",
}
_REVIEW_COMMAND_DOUBLE_QUOTE_SAFE_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-/"
)

_GLOBAL_REVIEW_UPDATES: dict[str, dict[str, object]] = {
    "auto_confirm": {
        "provenance_status": "auto_confirmed",
        "review_status": "confirmed",
        "can_use_as_instruction": True,
        "can_use_as_evidence": True,
        "requires_user_confirmation": False,
    },
    "confirm": {
        "provenance_status": "user_confirmed",
        "review_status": "confirmed",
        "can_use_as_instruction": True,
        "can_use_as_evidence": True,
        "requires_user_confirmation": False,
    },
    "evidence_only": {
        "provenance_status": "user_confirmed",
        "review_status": "evidence_only",
        "can_use_as_instruction": False,
        "can_use_as_evidence": True,
        "requires_user_confirmation": False,
    },
    "edit": {
        "review_status": "pending",
        "can_use_as_instruction": False,
        "can_use_as_evidence": True,
        "requires_user_confirmation": True,
    },
    "restrict_scope": {
        "provenance_status": "user_confirmed",
        "review_status": "restricted",
        "sensitivity_tier": "restricted",
        "can_use_as_instruction": False,
        "requires_user_confirmation": False,
    },
    "mark_stale": {
        "provenance_status": "user_confirmed",
        "status": "stale",
        "lifecycle_status": "stale",
        "review_status": "stale",
        "can_use_as_instruction": False,
        "requires_user_confirmation": False,
    },
    "merge": {
        "provenance_status": "user_confirmed",
        "lifecycle_status": "superseded",
        "review_status": "merged",
        "can_use_as_instruction": False,
        "requires_user_confirmation": False,
    },
    "reject": {
        "provenance_status": "user_confirmed",
        "lifecycle_status": "rejected",
        "review_status": "rejected",
        "can_use_as_instruction": False,
        "can_use_as_evidence": False,
        "requires_user_confirmation": False,
    },
    "dispute": {
        "provenance_status": "disputed",
        "lifecycle_status": "disputed",
        "review_status": "pending",
        "can_use_as_instruction": False,
        "requires_user_confirmation": True,
    },
    "supersede": {
        "provenance_status": "user_confirmed",
        "lifecycle_status": "superseded",
        "review_status": "stale",
        "can_use_as_instruction": False,
        "requires_user_confirmation": False,
    },
}

_GLOBAL_REVIEW_EVENT_TYPES = {
    "auto_confirm": "global_memory_auto_promoted",
    "confirm": "global_memory_confirmed",
    "edit": "global_memory_review_edit_requested",
    "evidence_only": "global_memory_evidence_only",
    "restrict_scope": "global_memory_restricted",
    "mark_stale": "global_memory_marked_stale",
    "merge": "global_memory_merged",
    "reject": "global_memory_rejected",
    "dispute": "global_memory_disputed",
    "supersede": "global_memory_superseded",
}

_GLOBAL_AUTO_PROMOTE_POLICIES: dict[str, dict[str, object]] = {
    "trusted_clean": {
        "schema_version": GLOBAL_AUTO_PROMOTE_POLICY_SCHEMA_VERSION,
        "allowed_provenance_statuses": ["imported"],
        "allowed_review_statuses": ["pending"],
        "allowed_review_reasons": ["pending_review", "requires_user_confirmation"],
        "blocked_review_reasons": [
            "confirm_guard_blocked",
            "missing_required_governance",
            "non_global_scope",
            "parse_error",
            "stamp_recommended",
            "unsafe_instruction_grade",
        ],
        "allow_missing_required_governance": False,
        "allow_restricted": False,
        "promoted_provenance_status": "auto_confirmed",
    },
    "repair_clean": {
        "schema_version": GLOBAL_AUTO_PROMOTE_POLICY_SCHEMA_VERSION,
        "allowed_provenance_statuses": ["imported"],
        "allowed_review_statuses": ["pending"],
        "allowed_review_reasons": [
            "missing_required_governance",
            "pending_review",
            "requires_user_confirmation",
            "stamp_recommended",
        ],
        "blocked_review_reasons": [
            "confirm_guard_blocked",
            "non_global_scope",
            "parse_error",
            "unsafe_instruction_grade",
        ],
        "allow_missing_required_governance": True,
        "allow_restricted": False,
        "promoted_provenance_status": "auto_confirmed",
    },
}


def memory_global_review_pending(
    *,
    target_root: str | Path | None = None,
    db_path: str | Path | None = None,
    limit: int = 50,
    reasons: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Return global-root markdown files that still require human review."""
    root, root_provenance = _resolve_cli_global_root(target_root)
    db = _resolve_cli_db_path(db_path)
    db_provenance = _path_provenance(db_path)
    reason_filters, unsupported_reasons = _normalize_review_reason_filters(reasons or [])
    if unsupported_reasons:
        return {
            "ok": False,
            "error": "unsupported global review reason filter",
            "unsupported_reasons": unsupported_reasons,
            "supported_reasons": sorted(GLOBAL_REVIEW_REASONS),
            "root": _root_payload(root, provenance=root_provenance),
            "db": _root_payload(db, provenance=db_provenance),
            "global_root_provenance": root_provenance,
        }
    if not root.exists() or not root.is_dir():
        return {
            "ok": False,
            "error": "global root does not exist or is not a directory",
            "root": _root_payload(root, provenance=root_provenance),
            "db": _root_payload(db, provenance=db_provenance),
            "global_root_provenance": root_provenance,
        }

    _db_counts, indexed_by_path = _global_db_counts(db)
    max_items = max(0, min(int(limit), 200))
    pending: list[dict[str, Any]] = []
    total_pending = 0
    matching_pending = 0
    first_matching_relative_path = ""
    first_matching_target: dict[str, Any] | None = None
    scanned_files = 0
    all_summary = _empty_review_list_summary()
    matching_summary = _empty_review_list_summary()
    returned_summary = _empty_review_list_summary()
    for relative, path in _discover_root_markdown_files(root):
        scanned_files += 1
        item = _global_file_review_item(path, relative_path=relative)
        if not item["requires_review"]:
            continue
        total_pending += 1
        item_reasons = {str(reason) for reason in item.get("review_reasons") or []}
        _accumulate_review_list_summary(all_summary, item)
        if reason_filters and not (reason_filters & item_reasons):
            continue
        matching_pending += 1
        indexed_row = indexed_by_path.get(str(path).replace("\\", "/"))
        returned_item = {
            "relative_path": relative,
            "indexed": indexed_row is not None,
            "default_available": bool(indexed_row.get("available")) if indexed_row else False,
            **item,
        }
        if not first_matching_relative_path:
            first_matching_relative_path = relative
            first_matching_target = returned_item
        _accumulate_review_list_summary(matching_summary, item)
        if len(pending) >= max_items:
            continue
        pending.append(returned_item)
        _accumulate_review_list_summary(returned_summary, returned_item)

    result = {
        "ok": True,
        "root": _root_payload(root, provenance=root_provenance),
        "db": _root_payload(db, provenance=db_provenance),
        "global_root_provenance": root_provenance,
        "pending_count": total_pending,
        "matching_count": matching_pending,
        "first_matching_relative_path": first_matching_relative_path,
        "first_matching_target": first_matching_target,
        "returned_count": len(pending),
        "truncated": matching_pending > len(pending),
        "filters": {
            "review_reasons": sorted(reason_filters),
        },
        "summary": {
            "scanned_file_count": scanned_files,
            "pending_count": total_pending,
            "matching_count": matching_pending,
            **_finalize_review_list_summary(all_summary),
        },
        "matching_summary": {
            "matching_count": matching_pending,
            **_finalize_review_list_summary(matching_summary),
        },
        "returned_summary": {
            "returned_count": len(pending),
            **_finalize_review_list_summary(returned_summary),
        },
        "files": pending,
    }
    result["recommendations"] = _global_review_recommendations(result)
    return result


def memory_global_auto_promote(
    *,
    target_root: str | Path | None = None,
    db_path: str | Path | None = None,
    policy: str = "",
    limit: int = 50,
    write: bool = False,
    enabled: bool | None = None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Promote eligible global memories through an automated trust policy."""
    policy_id = _normalize_auto_promote_policy(policy)
    if policy_id not in _GLOBAL_AUTO_PROMOTE_POLICIES:
        return {
            "ok": False,
            "schema_version": GLOBAL_AUTO_PROMOTE_SCHEMA_VERSION,
            "error": "unsupported global auto-promotion policy",
            "policy": policy_id,
            "supported_policies": sorted(_GLOBAL_AUTO_PROMOTE_POLICIES),
        }
    policy_profile = _global_auto_promote_policy_profile(policy_id)
    enabled_value = _global_auto_promote_enabled() if enabled is None else bool(enabled)
    root, root_provenance = _resolve_cli_global_root(target_root)
    db = _resolve_cli_db_path(db_path)
    db_provenance = _path_provenance(db_path)
    result: dict[str, Any] = {
        "ok": True,
        "schema_version": GLOBAL_AUTO_PROMOTE_SCHEMA_VERSION,
        "write": bool(write),
        "enabled": enabled_value,
        "policy": policy_profile,
        "root": _root_payload(root, provenance=root_provenance),
        "db": _root_payload(db, provenance=db_provenance),
        "global_root_provenance": root_provenance,
        "body_included": False,
        "prompt_included": False,
        "counts": {
            "scanned_count": 0,
            "eligible_count": 0,
            "promoted_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
        },
        "files": [],
    }

    pending = memory_global_review_pending(
        target_root=root,
        db_path=db,
        limit=max(0, min(int(limit), 200)),
    )
    result["review_queue"] = _global_auto_promote_queue_summary(pending)
    if not pending.get("ok"):
        result["ok"] = False
        result["error"] = pending.get("error") or "global review queue unavailable"
        return result
    if write and not enabled_value:
        result["ok"] = False
        result["error"] = "global auto-promotion write requires explicit enablement"
        result["recommendations"] = _global_auto_promote_enablement_recommendations(policy_id)
        return result

    # The duplicate-body guard below counts body hashes only over the returned
    # window. If the pending queue is truncated, those counts are incomplete and a
    # file with a duplicate outside the window could be wrongly promoted. Fail
    # closed for write mode; surface the flag everywhere (gsr-04).
    result["truncated"] = bool(pending.get("truncated"))
    if write and pending.get("truncated"):
        result["ok"] = False
        result["error"] = (
            "global review queue is truncated; the duplicate-body guard cannot be "
            "computed over the full pending set. Raise --limit or promote in batches."
        )
        return result

    files = pending.get("files") if isinstance(pending.get("files"), list) else []
    target_receipts: dict[str, dict[str, Any]] = {}
    body_hash_counts: dict[str, int] = {}
    for item in files:
        if not isinstance(item, Mapping):
            continue
        relative_path = str(item.get("relative_path") or "")
        if not relative_path:
            continue
        target = memory_global_review_target(
            relative_path=relative_path,
            target_root=root,
            db_path=db,
        )
        target_receipts[relative_path] = target
        body_hash = str(target.get("body_sha256") or "") if target.get("ok") else ""
        if body_hash:
            body_hash_counts[body_hash] = int(body_hash_counts.get(body_hash) or 0) + 1

    for item in files:
        if not isinstance(item, Mapping):
            continue
        result["counts"]["scanned_count"] += 1
        relative_path = str(item.get("relative_path") or "")
        target = target_receipts.get(relative_path, {})
        body_hash = str(target.get("body_sha256") or "") if target.get("ok") else ""
        decision = _global_auto_promote_decision(
            item,
            policy=policy_profile,
            duplicate_body=bool(body_hash and int(body_hash_counts.get(body_hash) or 0) > 1),
        )
        file_result: dict[str, Any] = {
            "relative_path": relative_path,
            "decision": decision["decision"],
            "eligible": bool(decision["eligible"]),
            "policy_reasons": list(decision["policy_reasons"]),
            "review_reasons": list(item.get("review_reasons") or []),
            "confirm_guard_blocked": int((item.get("confirm_guard") or {}).get("blocked_count") or 0),
            "body_included": False,
        }
        if not decision["eligible"]:
            result["counts"]["skipped_count"] += 1
            result["files"].append(file_result)
            continue
        result["counts"]["eligible_count"] += 1
        if not write:
            result["files"].append(file_result)
            continue

        if not target.get("ok"):
            result["counts"]["failed_count"] += 1
            result["files"].append(
                {
                    **file_result,
                    "decision": "failed",
                    "eligible": False,
                    "error": target.get("error") or "global review target unavailable",
                }
            )
            continue
        action_result = memory_global_review_action(
            relative_path=relative_path,
            action="auto_confirm",
            reviewer=f"automation:{policy_id}",
            notes=f"Automated global promotion policy: {policy_id}",
            expected_body_sha256=str(target.get("body_sha256") or ""),
            target_root=root,
            db_path=db,
            write=True,
            reviewed_at=reviewed_at,
        )
        if action_result.get("ok"):
            result["counts"]["promoted_count"] += 1
            result["files"].append(
                {
                    **file_result,
                    "decision": "promoted",
                    "action_id": action_result.get("action_id", ""),
                    "indexed": bool(action_result.get("indexed")),
                    "after": action_result.get("after") or {},
                }
            )
            continue
        result["counts"]["failed_count"] += 1
        result["files"].append(
            {
                **file_result,
                "decision": "failed",
                "error": action_result.get("error") or "global auto-promotion action failed",
                "guard": action_result.get("guard") or {},
            }
        )

    result["recommendations"] = _global_auto_promote_recommendations(result)
    if write and int(result["counts"]["failed_count"] or 0) > 0:
        result["ok"] = False
        result["error"] = "one or more global auto-promotions failed"
    return result


def memory_global_review_target(
    *,
    relative_path: str,
    target_root: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a body-safe inspection receipt for one global review target."""
    root, root_provenance = _resolve_cli_global_root(target_root)
    db = _resolve_cli_db_path(db_path)
    db_provenance = _path_provenance(db_path)
    resolved = _resolve_global_memory_file(root, relative_path=relative_path)
    if not resolved["ok"]:
        resolved["root"] = _root_payload(root, provenance=root_provenance)
        resolved["db"] = _root_payload(db, provenance=db_provenance)
        resolved["global_root_provenance"] = root_provenance
        return resolved
    target = resolved["path"]
    relative_text = resolved["relative_path"]
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "ok": False,
            "error": "global memory file could not be read",
            "relative_path": relative_text,
            "exception": exc.__class__.__name__,
            "root": _root_payload(root, provenance=root_provenance),
            "db": _root_payload(db, provenance=db_provenance),
            "global_root_provenance": root_provenance,
        }

    split = _split_frontmatter_preserving_body(content)
    frontmatter = dict(split.get("frontmatter") or {}) if split.get("ok") else {}
    body = str(split.get("body") if split.get("ok") else content)
    item = _global_file_review_item(target, relative_path=relative_text)
    _db_counts, indexed_by_path = _global_db_counts(db)
    indexed_row = indexed_by_path.get(str(target).replace("\\", "/"))
    result: dict[str, Any] = {
        "ok": True,
        "schema_version": "chimera-memory.global-review-target.v1",
        "root": _root_payload(root, provenance=root_provenance),
        "db": _root_payload(db, provenance=db_provenance),
        "global_root_provenance": root_provenance,
        "relative_path": relative_text,
        "indexed": indexed_row is not None,
        "default_available": bool(indexed_row.get("available")) if indexed_row else False,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "body_char_count": len(body),
        "frontmatter_key_count": len(frontmatter),
        "frontmatter_keys": sorted(str(key) for key in frontmatter),
        "had_frontmatter": bool(split.get("had_frontmatter")),
        "source_parse_error": str(split.get("error") or ""),
        "requires_review": bool(item.get("requires_review")),
        "review_reasons": list(item.get("review_reasons") or []),
        "missing_required_keys": list(item.get("missing_required_keys") or []),
        "review_status": item.get("review_status", ""),
        "provenance_status": item.get("provenance_status", ""),
        "requires_user_confirmation": bool(item.get("requires_user_confirmation")),
        "can_use_as_instruction": bool(item.get("can_use_as_instruction")),
        "can_use_as_evidence": bool(item.get("can_use_as_evidence")),
        "unsafe_instruction_grade": bool(item.get("unsafe_instruction_grade")),
        "stamp_recommended": bool(item.get("stamp_recommended")),
        "confirm_guard": item.get("confirm_guard") or {},
        "action_guidance": item.get("action_guidance") or {},
        "body_included": False,
    }
    result["recommendations"] = _global_review_target_recommendations(result)
    return result


def memory_global_review_action(
    *,
    relative_path: str,
    action: str,
    reviewer: str = "",
    notes: str = "",
    expected_body_sha256: str = "",
    target_root: str | Path | None = None,
    db_path: str | Path | None = None,
    write: bool = False,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Preview or apply a durable frontmatter review action to one global file."""
    action = str(action or "").strip()
    if action not in GLOBAL_REVIEW_ACTIONS:
        return {
            "ok": False,
            "error": "unsupported review action",
            "action": action,
            "supported_actions": sorted(GLOBAL_REVIEW_ACTIONS),
        }
    reviewer = str(reviewer or "").strip()
    if write and not reviewer:
        return {"ok": False, "error": "reviewer required for write-mode global review"}

    root, root_provenance = _resolve_cli_global_root(target_root)
    db = _resolve_cli_db_path(db_path)
    db_provenance = _path_provenance(db_path)
    resolved = _resolve_global_memory_file(root, relative_path=relative_path)
    if not resolved["ok"]:
        resolved["root"] = _root_payload(root, provenance=root_provenance)
        resolved["db"] = _root_payload(db, provenance=db_provenance)
        resolved["global_root_provenance"] = root_provenance
        return resolved
    target = resolved["path"]
    relative_text = resolved["relative_path"]

    try:
        original = target.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "ok": False,
            "error": "global memory file could not be read",
            "relative_path": relative_text,
            "exception": exc.__class__.__name__,
            "root": _root_payload(root, provenance=root_provenance),
            "db": _root_payload(db, provenance=db_provenance),
            "global_root_provenance": root_provenance,
        }
    split = _split_frontmatter_preserving_body(original)
    source_parse_error = str(split.get("error") or "")
    if split.get("ok"):
        frontmatter = dict(split.get("frontmatter") or {})
        body = str(split.get("body") or "")
    else:
        frontmatter = {}
        body = original
    body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    hash_precondition = _review_body_hash_precondition(
        expected_body_sha256,
        actual_body_sha256=body_sha256,
    )
    if not hash_precondition["ok"]:
        return {
            "ok": False,
            "error": hash_precondition["error"],
            "schema_version": GLOBAL_FRONTMATTER_REVIEW_SCHEMA_VERSION,
            "root": _root_payload(root, provenance=root_provenance),
            "db": _root_payload(db, provenance=db_provenance),
            "global_root_provenance": root_provenance,
            "relative_path": relative_text,
            "action": action,
            "written": False,
            "indexed": False,
            "body_included": False,
            "body_sha256": body_sha256,
            "hash_precondition": hash_precondition,
        }
    before = _source_review_snapshot(frontmatter, parse_error=source_parse_error)
    reviewed = _reviewed_frontmatter(
        frontmatter,
        action=action,
        reviewer=reviewer or "user",
        notes=notes,
        relative_path=relative_text,
        reviewed_at=reviewed_at or _utc_now(),
    )
    if source_parse_error:
        reviewed["global_review"]["previous_review_status"] = before["review_status"]
    updated = _render_frontmatter_markdown(reviewed, body)
    verify = _split_frontmatter_preserving_body(updated)
    if not verify.get("ok"):
        return {"ok": False, "error": "rendered review frontmatter is invalid", "relative_path": relative_text}
    if str(verify.get("body") or "") != body:
        return {
            "ok": False,
            "error": "body preservation guard failed",
            "relative_path": relative_text,
            "body_sha256_before": body_sha256,
            "body_sha256_after": hashlib.sha256(str(verify.get("body") or "").encode("utf-8")).hexdigest(),
        }

    result: dict[str, Any] = {
        "ok": True,
        "schema_version": GLOBAL_FRONTMATTER_REVIEW_SCHEMA_VERSION,
        "root": _root_payload(root, provenance=root_provenance),
        "db": _root_payload(db, provenance=db_provenance),
        "global_root_provenance": root_provenance,
        "relative_path": relative_text,
        "action": action,
        "reviewer": reviewer or "user",
        "written": False,
        "indexed": False,
        "body_preserved": True,
        "source_parse_error": source_parse_error,
        "body_sha256": body_sha256,
        "hash_precondition": hash_precondition,
        "before": before,
        "after": _review_snapshot(reviewed),
        "content_sha256_before": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "content_sha256_after": hashlib.sha256(updated.encode("utf-8")).hexdigest(),
        "frontmatter_keys_added": sorted(set(reviewed) - set(frontmatter)),
        "frontmatter_keys_updated": sorted(
            key for key in set(reviewed).intersection(frontmatter) if reviewed[key] != frontmatter[key]
        ),
    }
    result["guard"] = _review_guard(updated, relative_path=relative_text, reviewed_frontmatter=reviewed)
    result["action_guidance"] = _global_review_action_guidance(
        frontmatter,
        body=body,
        relative_path=relative_text,
        parse_error=source_parse_error,
    )
    result["selected_action_guidance"] = _selected_review_action_guidance(
        result["action_guidance"],
        action=action,
    )
    if not write:
        result["preview_frontmatter"] = _display_safe_review_frontmatter(reviewed)
        result["recommendations"] = _global_review_action_recommendations(result)
        return result
    if not bool(hash_precondition.get("checked")):
        result["body_included"] = False
        result["recommendations"] = _global_review_missing_hash_recommendations(result)
        return {
            **result,
            "ok": False,
            "error": "expected body sha256 required for write-mode global review",
        }
    if result["guard"]["blocked_count"]:
        result["recommendations"] = _global_review_action_recommendations(result)
        return {
            **result,
            "ok": False,
            "error": "global memory guard blocked review action",
        }

    try:
        target.write_text(updated, encoding="utf-8", newline="\n")
    except OSError as exc:
        return {
            **result,
            "ok": False,
            "error": "global memory file could not be written",
            "exception": exc.__class__.__name__,
        }
    result["written"] = True
    try:
        index_result = _index_reviewed_global_file(
            db,
            root=root,
            root_provenance=root_provenance,
            db_provenance=db_provenance,
            relative_path=relative_text,
            path=target,
            action=action,
            reviewer=reviewer,
            notes=notes,
            before=before,
            after=result["after"],
        )
    except Exception as exc:
        index_result = {
            "ok": False,
            "error": "global memory review index step failed",
            "indexed": False,
            "exception": exc.__class__.__name__,
        }
    result["index"] = index_result
    result["indexed"] = bool(index_result.get("indexed"))
    result["action_id"] = index_result.get("action_id", "")
    if not index_result.get("ok"):
        restore_result = _restore_original_review_file(target, original)
        result["restore"] = restore_result
        if restore_result.get("ok"):
            result["written"] = False
        result["ok"] = False
        result["error"] = index_result.get("error") or "global memory review indexed failed"
    result["recommendations"] = _global_review_action_recommendations(result)
    return result


def _global_file_review_item(path: Path, *, relative_path: str) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "parse_error": exc.__class__.__name__,
            "requires_review": True,
            "review_reasons": [
                "parse_error",
                "missing_required_governance",
                "stamp_recommended",
            ],
            "missing_required_keys": sorted(GLOBAL_GOVERNANCE_REQUIRED_KEYS),
            "unsafe_instruction_grade": False,
            "stamp_recommended": True,
            "review_status": "pending",
            "provenance_status": "imported",
            "lifecycle_status": "active",
            "sensitivity_tier": "standard",
            "exclude_from_default_search": False,
            "requires_user_confirmation": True,
            "can_use_as_instruction": False,
            "can_use_as_evidence": True,
            "confirm_guard": _unavailable_confirm_guard_preview(reason="read_error"),
            "action_guidance": _unavailable_action_guidance(reason="read_error"),
        }
    split = _split_frontmatter_preserving_body(content)
    frontmatter = dict(split.get("frontmatter") or {})
    body = str(split.get("body") or "")
    parse_error = str(split.get("error") or "")
    snapshot = _source_review_snapshot(frontmatter, parse_error=parse_error)
    governance_status = _global_governance_status(frontmatter, parse_error=parse_error)
    review_reasons = _global_review_reasons(
        snapshot=snapshot,
        governance_status=governance_status,
        frontmatter=frontmatter,
    )
    confirm_guard = _confirm_guard_preview(
        frontmatter,
        body=body,
        relative_path=relative_path,
        parse_error=parse_error,
    )
    if int(confirm_guard.get("blocked_count") or 0) > 0:
        review_reasons.append("confirm_guard_blocked")
    action_guidance = _global_review_action_guidance(
        frontmatter,
        body=body,
        relative_path=relative_path,
        parse_error=parse_error,
    )
    return {
        "parse_error": parse_error,
        "requires_review": bool(review_reasons),
        "review_reasons": review_reasons,
        "missing_required_keys": list(governance_status.get("missing_required_keys") or []),
        "unsafe_instruction_grade": bool(governance_status.get("unsafe_instruction_grade")),
        "stamp_recommended": bool(governance_status.get("stamp_recommended")),
        "review_status": snapshot["review_status"],
        "provenance_status": snapshot["provenance_status"],
        "lifecycle_status": snapshot["lifecycle_status"],
        "sensitivity_tier": snapshot["sensitivity_tier"],
        "exclude_from_default_search": bool(frontmatter.get("exclude_from_default_search")),
        "requires_user_confirmation": snapshot["requires_user_confirmation"],
        "can_use_as_instruction": snapshot["can_use_as_instruction"],
        "can_use_as_evidence": snapshot["can_use_as_evidence"],
        "confirm_guard": confirm_guard,
        "action_guidance": action_guidance,
    }


def _global_review_action_guidance(
    frontmatter: Mapping[str, Any],
    *,
    body: str,
    relative_path: str,
    parse_error: str,
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for action in (
        "confirm",
        "evidence_only",
        "restrict_scope",
        "reject",
        "dispute",
        "supersede",
    ):
        reviewed = _reviewed_frontmatter(
            frontmatter,
            action=action,
            reviewer="preview",
            notes="",
            relative_path=relative_path,
            reviewed_at="preview",
        )
        updated = _render_frontmatter_markdown(reviewed, body)
        guard = _review_guard(updated, relative_path=relative_path, reviewed_frontmatter=reviewed)
        blocked_count = int(guard.get("blocked_count") or 0)
        finding_count = int(guard.get("finding_count") or 0)
        post_review_default_available = bool(guard.get("required"))
        can_write_without_guard_block = blocked_count <= 0
        actions.append(
            {
                "action": action,
                "can_write_without_guard_block": can_write_without_guard_block,
                "post_review_default_available": post_review_default_available,
                "promotes_instruction": action == "confirm",
                "blocked_count": blocked_count,
                "finding_count": finding_count,
                "guidance": _review_action_guidance_text(
                    action,
                    can_write_without_guard_block=can_write_without_guard_block,
                    post_review_default_available=post_review_default_available,
                    parse_error=bool(parse_error),
                ),
            }
        )

    actions_by_name = {str(item.get("action")): item for item in actions}
    default_available_blocked = any(
        not bool(actions_by_name.get(action, {}).get("can_write_without_guard_block"))
        for action in ("confirm", "evidence_only")
    )
    if default_available_blocked:
        recommended = [
            action
            for action in ("reject", "restrict_scope", "dispute", "supersede")
            if bool(actions_by_name.get(action, {}).get("can_write_without_guard_block"))
        ]
    else:
        recommended = [
            action
            for action in ("confirm", "evidence_only")
            if bool(actions_by_name.get(action, {}).get("can_write_without_guard_block"))
        ]
    return {
        "schema_version": GLOBAL_REVIEW_ACTION_GUIDANCE_SCHEMA_VERSION,
        "recommended_next_actions": recommended,
        "actions": actions,
    }


def _review_action_guidance_text(
    action: str,
    *,
    can_write_without_guard_block: bool,
    post_review_default_available: bool,
    parse_error: bool,
) -> str:
    if not can_write_without_guard_block:
        return "write would be blocked by the memory guard because the post-review file remains default-retrievable"
    if action == "auto_confirm":
        return "promotes to instruction-grade only through explicit automated policy gates and clean preview"
    if action == "confirm":
        return "promotes to instruction-grade only after human review and clean preview"
    if action == "evidence_only":
        return "keeps the file retrievable as evidence but not instruction-grade"
    if post_review_default_available:
        return "keeps the file default-retrievable"
    if parse_error:
        return "repairs malformed frontmatter while preserving source text as body"
    return "keeps the file out of default retrieval or instruction use"


def _unavailable_action_guidance(*, reason: str) -> dict[str, Any]:
    return {
        "schema_version": GLOBAL_REVIEW_ACTION_GUIDANCE_SCHEMA_VERSION,
        "reason": reason,
        "recommended_next_actions": [],
        "actions": [],
    }


def _selected_review_action_guidance(guidance: Mapping[str, Any], *, action: str) -> dict[str, Any]:
    actions = guidance.get("actions") if isinstance(guidance.get("actions"), list) else []
    for item in actions:
        if isinstance(item, Mapping) and str(item.get("action") or "") == action:
            return dict(item)
    return {
        "action": action,
        "can_write_without_guard_block": False,
        "post_review_default_available": False,
        "promotes_instruction": action == "confirm",
        "blocked_count": 0,
        "finding_count": 0,
        "guidance": "action guidance unavailable",
    }


def _global_review_action_recommendations(result: Mapping[str, Any]) -> list[dict[str, str]]:
    relative_path = str(result.get("relative_path") or "").replace("\\", "/").strip()
    target = _review_command_target(relative_path)
    body_hash_arg = _review_body_hash_command_arg(result.get("body_sha256"))
    action = str(result.get("action") or "").strip()
    selected = (
        result.get("selected_action_guidance")
        if isinstance(result.get("selected_action_guidance"), Mapping)
        else {}
    )
    guard = result.get("guard") if isinstance(result.get("guard"), Mapping) else {}
    blocked_count = int(guard.get("blocked_count") or selected.get("blocked_count") or 0)
    recommended_actions = _recommended_review_actions(result, current_action=action)

    if bool(result.get("written")) and bool(result.get("ok", True)):
        return [
            {
                "code": "review_queue_after_write",
                "message": "Review the remaining global memory queue after this action is written and indexed.",
                "command": "chimera-memory global review --json",
            }
        ]

    if blocked_count > 0:
        recommendations: list[dict[str, str]] = [
            {
                "code": "do_not_write_guard_blocked_action",
                "message": "Do not write this review action: the memory guard would block it because the post-review file remains default-retrievable.",
                "command": "",
            }
        ]
        for recommended_action in recommended_actions:
            recommendations.append(
                {
                    "code": f"preview_{recommended_action}_remediation",
                    "message": f"Preview `{recommended_action}` as a remediation action before writing any global review change.",
                    "command": f"chimera-memory global review --relative-path {target} --action {recommended_action} --reviewer <NAME>{body_hash_arg} --json",
                }
            )
        return recommendations

    if action:
        return [
            {
                "code": "write_clean_review_action",
                "message": "The preview is guard-clean; after human review, write this action with an explicit reviewer.",
                "command": f"chimera-memory global review --relative-path {target} --action {action} --reviewer <NAME>{body_hash_arg} --write --json",
            }
        ]
    return []


def _global_review_missing_hash_recommendations(result: Mapping[str, Any]) -> list[dict[str, str]]:
    relative_path = str(result.get("relative_path") or "").replace("\\", "/").strip()
    target = _review_command_target(relative_path)
    action = str(result.get("action") or "").strip()
    recommendations = [
        {
            "code": "inspect_global_review_target_for_body_hash",
            "message": "Inspect this global review target to get the current body hash before write mode.",
            "command": f"chimera-memory global review --relative-path {target} --json",
        }
    ]
    if action:
        recommendations.append(
            {
                "code": "preview_global_review_action_for_body_hash",
                "message": "Preview the same review action to verify guard status and copy the body-hash-protected write command.",
                "command": f"chimera-memory global review --relative-path {target} --action {action} --reviewer <NAME> --json",
            }
        )
    return recommendations


def _recommended_review_actions(result: Mapping[str, Any], *, current_action: str) -> list[str]:
    guidance = result.get("action_guidance") if isinstance(result.get("action_guidance"), Mapping) else {}
    actions = guidance.get("actions") if isinstance(guidance.get("actions"), list) else []
    can_write: set[str] = {
        str(item.get("action") or "")
        for item in actions
        if isinstance(item, Mapping) and bool(item.get("can_write_without_guard_block"))
    }
    recommended = [
        str(action)
        for action in (guidance.get("recommended_next_actions") or [])
        if str(action) and str(action) != current_action and str(action) in can_write
    ]
    if recommended:
        return recommended
    return [
        action
        for action in ("reject", "restrict_scope", "dispute", "supersede")
        if action != current_action and action in can_write
    ]


def _global_review_recommendations(result: Mapping[str, Any]) -> list[dict[str, str]]:
    pending_count = int(result.get("pending_count") or 0)
    matching_count = int(result.get("matching_count") or pending_count)
    if pending_count <= 0:
        return []

    recommendations: list[dict[str, str]] = [
        {
            "code": "list_global_review_queue",
            "message": "List pending global memory review targets before treating global memory as instruction-grade.",
            "command": "chimera-memory global review --json",
        }
    ]
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    if int(summary.get("confirm_guard_blocked_count") or 0) > 0:
        recommendations.append(
            {
                "code": "inspect_confirm_guard_blockers",
                "message": "Inspect global files whose confirm-action preview is blocked by the memory guard before editing, rejecting, or leaving them evidence-only.",
                "command": "chimera-memory global review --reason confirm_guard_blocked --json",
            }
        )

    files = result.get("files") if isinstance(result.get("files"), list) else []
    first_relative_path = str(result.get("first_matching_relative_path") or "").replace("\\", "/").strip()
    for item in files:
        if isinstance(item, Mapping):
            returned_relative_path = str(item.get("relative_path") or "").replace("\\", "/").strip()
            if returned_relative_path:
                first_relative_path = returned_relative_path
                break

    target = _review_command_target(first_relative_path)
    if first_relative_path:
        recommendations.append(
            {
                "code": "inspect_global_review_target",
                "message": "Inspect the first matching global review target without exposing its memory body before choosing a review action.",
                "command": f"chimera-memory global review --relative-path {target} --json",
            }
        )
    first_target = result.get("first_matching_target")
    first_item = next((item for item in files if isinstance(item, Mapping) and item.get("relative_path")), {})
    if not first_item and isinstance(first_target, Mapping):
        first_item = first_target
    recommendations.extend(_global_review_queue_action_recommendations(first_item, target=target))
    if matching_count < pending_count:
        recommendations.append(
            {
                "code": "clear_unfiltered_queue",
                "message": "Run the unfiltered queue after handling the active filter so other pending global files are not missed.",
                "command": "chimera-memory global review --json",
            }
        )
    return recommendations


def _global_review_target_recommendations(result: Mapping[str, Any]) -> list[dict[str, str]]:
    relative_path = str(result.get("relative_path") or "").strip()
    if not relative_path:
        return []
    target = _review_command_target(relative_path)
    body_hash_arg = _review_body_hash_command_arg(result.get("body_sha256"))
    recommendations: list[dict[str, str]] = [
        {
            "code": "preview_confirm_after_human_review",
            "message": "After reading and approving this global file, preview a confirm action before writing instruction-grade governance.",
            "command": f"chimera-memory global review --relative-path {target} --action confirm --reviewer <NAME>{body_hash_arg} --json",
        },
        {
            "code": "preview_evidence_only_after_human_review",
            "message": "If this global file is useful context but should not instruct agents, preview an evidence-only review action.",
            "command": f"chimera-memory global review --relative-path {target} --action evidence_only --reviewer <NAME>{body_hash_arg} --json",
        },
    ]
    confirm_guard = result.get("confirm_guard") if isinstance(result.get("confirm_guard"), Mapping) else {}
    if int(confirm_guard.get("blocked_count") or 0) > 0:
        recommendations.insert(
            0,
            {
                "code": "inspect_confirm_guard_blocker",
                "message": "The confirm-action preview is blocked by the memory guard; remediate before promoting this file.",
                "command": f"chimera-memory global review --relative-path {target} --action reject --reviewer <NAME>{body_hash_arg} --json",
            },
        )
    if not bool(result.get("requires_review")):
        recommendations.append(
            {
                "code": "list_global_review_queue",
                "message": "This file does not currently require review; list the queue to find remaining global review targets.",
                "command": "chimera-memory global review --json",
            }
        )
    return recommendations


def _global_review_queue_action_recommendations(
    item: Mapping[str, Any],
    *,
    target: str,
) -> list[dict[str, str]]:
    guidance = item.get("action_guidance") if isinstance(item.get("action_guidance"), Mapping) else {}
    action_rows = guidance.get("actions") if isinstance(guidance.get("actions"), list) else []
    by_action = {
        str(row.get("action") or ""): row
        for row in action_rows
        if isinstance(row, Mapping) and str(row.get("action") or "")
    }
    confirm_clean = bool(by_action.get("confirm", {}).get("can_write_without_guard_block"))
    evidence_clean = bool(by_action.get("evidence_only", {}).get("can_write_without_guard_block"))
    recommendations: list[dict[str, str]] = [
        {
            "code": "preview_confirm_after_human_review",
            "message": "After reading and approving a global file, preview a confirm action before writing instruction-grade governance.",
            "command": f"chimera-memory global review --relative-path {target} --action confirm --reviewer <NAME> --json",
        }
    ]
    if confirm_clean:
        recommendations.append(
            {
                "code": "write_confirm_after_human_review",
                "message": "Only after human review and a clean preview, write the confirm action to promote that global file to instruction-grade memory.",
                "command": f"chimera-memory global review --relative-path {target} --action confirm --reviewer <NAME> --expect-body-sha256 <BODY_SHA256> --write --json",
            }
        )
    if evidence_clean:
        recommendations.append(
            {
                "code": "keep_as_evidence_only",
                "message": "If a global file is useful context but should not instruct agents, mark it evidence-only after review.",
                "command": f"chimera-memory global review --relative-path {target} --action evidence_only --reviewer <NAME> --expect-body-sha256 <BODY_SHA256> --write --json",
            }
        )
    if confirm_clean or evidence_clean:
        return recommendations

    for action in (
        str(action)
        for action in (guidance.get("recommended_next_actions") or [])
        if str(action)
    ):
        row = by_action.get(action) or {}
        if not bool(row.get("can_write_without_guard_block")):
            continue
        recommendations.append(
            {
                "code": f"preview_{action}_remediation",
                "message": f"Preview `{action}` as a remediation action because default-retrievable review actions would be blocked.",
                "command": f"chimera-memory global review --relative-path {target} --action {action} --reviewer <NAME> --json",
            }
        )
    return recommendations


def _review_body_hash_precondition(value: object, *, actual_body_sha256: str) -> dict[str, object]:
    expected = str(value or "").strip().lower()
    if not expected:
        return {
            "ok": True,
            "checked": False,
            "kind": "body_sha256",
            "matched": False,
            "expected_present": False,
        }
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        return {
            "ok": False,
            "error": "invalid expected body sha256",
            "checked": True,
            "kind": "body_sha256",
            "matched": False,
            "expected_present": True,
        }
    matched = expected == actual_body_sha256
    return {
        "ok": matched,
        "error": "" if matched else "global review body hash precondition failed",
        "checked": True,
        "kind": "body_sha256",
        "matched": matched,
        "expected_present": True,
        "expected_sha256": expected,
        "actual_sha256": actual_body_sha256,
    }


def _review_body_hash_command_arg(value: object) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        return ""
    return f" --expect-body-sha256 {text}"


def _review_command_target(relative_path: str) -> str:
    text = str(relative_path or "").strip()
    if not text:
        return "<RELATIVE_PATH>"
    if all(char in _REVIEW_COMMAND_DOUBLE_QUOTE_SAFE_CHARS for char in text):
        return '"' + text + '"'
    return "'" + text.replace("'", "''") + "'"


def _empty_review_list_summary() -> dict[str, Any]:
    return {
        "reason_counts": {},
        "confirm_guard_required_count": 0,
        "confirm_guard_blocked_count": 0,
        "confirm_guard_finding_count": 0,
        "confirm_guard_blocked_relative_paths": [],
    }


def _accumulate_review_list_summary(summary: dict[str, Any], item: Mapping[str, Any]) -> None:
    reason_counts = summary["reason_counts"]
    for reason in {str(reason) for reason in (item.get("review_reasons") or [])}:
        reason_counts[reason] = int(reason_counts.get(reason) or 0) + 1
    confirm_guard = item.get("confirm_guard") if isinstance(item.get("confirm_guard"), Mapping) else {}
    if confirm_guard.get("required"):
        summary["confirm_guard_required_count"] += 1
    summary["confirm_guard_blocked_count"] += int(confirm_guard.get("blocked_count") or 0)
    summary["confirm_guard_finding_count"] += int(confirm_guard.get("finding_count") or 0)
    summary["confirm_guard_blocked_relative_paths"].extend(
        str(relative_path) for relative_path in (confirm_guard.get("blocked_relative_paths") or [])
    )


def _finalize_review_list_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    reason_counts = summary.get("reason_counts") if isinstance(summary.get("reason_counts"), Mapping) else {}
    return {
        "reason_counts": dict(sorted((str(key), int(value or 0)) for key, value in reason_counts.items())),
        "confirm_guard_required_count": int(summary.get("confirm_guard_required_count") or 0),
        "confirm_guard_blocked_count": int(summary.get("confirm_guard_blocked_count") or 0),
        "confirm_guard_finding_count": int(summary.get("confirm_guard_finding_count") or 0),
        "confirm_guard_blocked_relative_paths": sorted(
            {str(path) for path in (summary.get("confirm_guard_blocked_relative_paths") or [])}
        ),
    }


def _global_review_reasons(
    *,
    snapshot: Mapping[str, Any],
    governance_status: Mapping[str, Any],
    frontmatter: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if governance_status.get("parse_error"):
        reasons.append("parse_error")
    if governance_status.get("missing_required_keys"):
        reasons.append("missing_required_governance")
    memory_scope = str(frontmatter.get("memory_scope") or "").strip().lower()
    if memory_scope and memory_scope != "global":
        reasons.append("non_global_scope")
    if bool(snapshot.get("requires_user_confirmation")):
        reasons.append("requires_user_confirmation")
    if str(snapshot.get("review_status") or "").strip() == "pending":
        reasons.append("pending_review")
    if governance_status.get("unsafe_instruction_grade"):
        reasons.append("unsafe_instruction_grade")
    if governance_status.get("stamp_recommended") and not reasons:
        reasons.append("stamp_recommended")
    return reasons


def _normalize_auto_promote_policy(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text:
        return text
    configured = os.environ.get("CHIMERA_MEMORY_GLOBAL_AUTO_PROMOTE_POLICY", "").strip()
    return configured.lower().replace("-", "_") if configured else "trusted_clean"


def _global_auto_promote_enabled() -> bool:
    value = os.environ.get("CHIMERA_MEMORY_GLOBAL_AUTO_PROMOTE", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _global_auto_promote_policy_profile(policy_id: str) -> dict[str, Any]:
    profile = dict(_GLOBAL_AUTO_PROMOTE_POLICIES[policy_id])
    profile["id"] = policy_id
    return profile


def _global_auto_promote_decision(
    item: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    duplicate_body: bool = False,
) -> dict[str, Any]:
    reasons: list[str] = []
    review_reasons = {str(reason) for reason in (item.get("review_reasons") or [])}
    blocked_reasons = {str(reason) for reason in (policy.get("blocked_review_reasons") or [])}
    blocked_matches = sorted(review_reasons & blocked_reasons)
    if blocked_matches:
        reasons.extend(f"blocked_review_reason:{reason}" for reason in blocked_matches)
    allowed_reasons = {str(reason) for reason in (policy.get("allowed_review_reasons") or [])}
    unsupported_reasons = sorted(review_reasons - allowed_reasons - blocked_reasons)
    if unsupported_reasons:
        reasons.extend(f"unsupported_review_reason:{reason}" for reason in unsupported_reasons)
    if item.get("missing_required_keys") and not bool(policy.get("allow_missing_required_governance")):
        reasons.append("missing_required_governance")
    provenance = str(item.get("provenance_status") or "")
    if provenance not in {str(value) for value in (policy.get("allowed_provenance_statuses") or [])}:
        reasons.append(f"weak_provenance:{provenance or 'missing'}")
    review_status = str(item.get("review_status") or "")
    if review_status not in {str(value) for value in (policy.get("allowed_review_statuses") or [])}:
        reasons.append(f"unsupported_review_status:{review_status or 'missing'}")
    if str(item.get("lifecycle_status") or "active") != "active":
        reasons.append(f"non_active_lifecycle:{item.get('lifecycle_status') or 'missing'}")
    sensitivity = str(item.get("sensitivity_tier") or "standard")
    if sensitivity != "standard" and not bool(policy.get("allow_restricted")):
        reasons.append(f"non_standard_sensitivity:{sensitivity}")
    if bool(item.get("exclude_from_default_search")):
        reasons.append("excluded_from_default_search")
    if duplicate_body:
        reasons.append("duplicate_body_hash")
    if not bool(item.get("can_use_as_evidence")):
        reasons.append("not_evidence_enabled")
    confirm_guard = item.get("confirm_guard") if isinstance(item.get("confirm_guard"), Mapping) else {}
    if int(confirm_guard.get("blocked_count") or 0) > 0:
        reasons.append("confirm_guard_blocked")
    if bool(item.get("unsafe_instruction_grade")):
        reasons.append("unsafe_instruction_grade")
    eligible = not reasons
    return {
        "eligible": eligible,
        "decision": "eligible" if eligible else "skipped",
        "policy_reasons": sorted(set(reasons)) if reasons else ["policy_passed"],
    }


def _global_auto_promote_queue_summary(pending: Mapping[str, Any]) -> dict[str, Any]:
    if not pending.get("ok"):
        return {
            "ok": False,
            "error": pending.get("error") or "unavailable",
        }
    summary = pending.get("summary") if isinstance(pending.get("summary"), Mapping) else {}
    return {
        "ok": True,
        "pending_count": int(pending.get("pending_count") or 0),
        "returned_count": int(pending.get("returned_count") or 0),
        "truncated": bool(pending.get("truncated")),
        "reason_counts": dict(summary.get("reason_counts") or {}),
        "confirm_guard_blocked_count": int(summary.get("confirm_guard_blocked_count") or 0),
        "confirm_guard_finding_count": int(summary.get("confirm_guard_finding_count") or 0),
    }


def _global_auto_promote_enablement_recommendations(policy_id: str) -> list[dict[str, str]]:
    return [
        {
            "code": "preview_global_auto_promotion",
            "message": "Preview automated global promotion before enabling write mode.",
            "command": f"chimera-memory global promote --policy {policy_id} --json",
        },
        {
            "code": "enable_global_auto_promotion",
            "message": "Enable automated global promotion explicitly for write mode; no per-file human approval is required.",
            "command": f"chimera-memory global promote --policy {policy_id} --enable-auto-promotion --write --json",
        },
    ]


def _global_auto_promote_recommendations(result: Mapping[str, Any]) -> list[dict[str, str]]:
    policy = result.get("policy") if isinstance(result.get("policy"), Mapping) else {}
    policy_id = str(policy.get("id") or "trusted_clean")
    counts = result.get("counts") if isinstance(result.get("counts"), Mapping) else {}
    if not bool(result.get("write")) and int(counts.get("eligible_count") or 0) > 0:
        return _global_auto_promote_enablement_recommendations(policy_id)
    if bool(result.get("write")):
        return [
            {
                "code": "inspect_global_corpus_after_auto_promotion",
                "message": "Inspect active global memory counts after automated promotion.",
                "command": "chimera-memory global inspect --json",
            },
            {
                "code": "prove_codex_global_context",
                "message": "Run a real global Codex exec receipt after automated promotion changes instruction-grade availability.",
                "command": "chimera-memory codex exec --scope global --prompt-file <PROMPT_FILE> --receipt-only --json",
            },
        ]
    return [
        {
            "code": "no_eligible_global_auto_promotion_targets",
            "message": "No files matched the automated promotion policy; inspect skipped policy reasons before changing policy.",
            "command": "chimera-memory global promote --json",
        }
    ]


def _normalize_review_reason_filters(values: list[str] | tuple[str, ...]) -> tuple[set[str], list[str]]:
    filters: set[str] = set()
    unsupported: list[str] = []
    for value in values:
        text = str(value or "").strip().lower().replace("-", "_")
        if not text:
            continue
        if text not in GLOBAL_REVIEW_REASONS:
            unsupported.append(text)
            continue
        filters.add(text)
    return filters, sorted(set(unsupported))


def _resolve_global_memory_file(root: Path, *, relative_path: str) -> dict[str, Any]:
    if not root.exists() or not root.is_dir():
        return {"ok": False, "error": "global root does not exist or is not a directory"}
    raw_text = str(relative_path or "").strip()
    if raw_text.startswith(("/", "\\")):
        relative_text = raw_text.replace("\\", "/")
        return {"ok": False, "error": "relative_path escapes global root", "relative_path": relative_text}
    relative_text = raw_text.replace("\\", "/").strip()
    if not relative_text:
        return {"ok": False, "error": "relative_path required"}
    if any(ord(char) < 32 for char in relative_text):
        return {"ok": False, "error": "relative_path contains control characters", "relative_path": relative_text}
    windows_relative = PureWindowsPath(relative_text)
    if windows_relative.drive or windows_relative.root or ":" in relative_text:
        return {"ok": False, "error": "relative_path contains drive or stream separator", "relative_path": relative_text}
    relative = Path(relative_text)
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        return {"ok": False, "error": "relative_path escapes global root", "relative_path": relative_text}

    root_resolved = root.resolve()
    candidate = root_resolved / relative
    if candidate.is_symlink() or _should_skip_path(root_resolved, candidate):
        return {
            "ok": False,
            "error": "global review target is not in discoverable global corpus",
            "relative_path": relative_text,
        }
    target = candidate.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError:
        return {"ok": False, "error": "relative_path escapes global root", "relative_path": relative_text}
    if target.suffix.lower() != ".md":
        return {"ok": False, "error": "global review target must be a markdown file", "relative_path": relative_text}
    if not target.exists() or not target.is_file():
        return {"ok": False, "error": "global memory file not found", "relative_path": relative_text}
    return {"ok": True, "path": target, "relative_path": relative_text}


def _restore_original_review_file(path: Path, original: str) -> dict[str, Any]:
    try:
        path.write_text(original, encoding="utf-8", newline="")
    except OSError as exc:
        return {
            "ok": False,
            "error": "global memory file could not be restored after index failure",
            "exception": exc.__class__.__name__,
        }
    return {
        "ok": True,
        "content_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
    }


def _display_safe_review_frontmatter(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _display_safe_review_frontmatter(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_display_safe_review_frontmatter(item) for item in value]
    if isinstance(value, tuple):
        return [_display_safe_review_frontmatter(item) for item in value]
    if isinstance(value, str):
        return redact_local_path_references(sanitize_content(value) or "")
    return value


def _reviewed_frontmatter(
    frontmatter: Mapping[str, Any],
    *,
    action: str,
    reviewer: str,
    notes: str,
    relative_path: str,
    reviewed_at: str,
) -> dict[str, Any]:
    reviewed = dict(frontmatter)
    reviewed["memory_scope"] = "global"
    reviewed.setdefault("provenance_status", "imported")
    reviewed.setdefault("lifecycle_status", str(reviewed.get("status") or "active"))
    reviewed.setdefault("sensitivity_tier", "standard")
    reviewed.setdefault("can_use_as_evidence", True)
    reviewed.update(_GLOBAL_REVIEW_UPDATES[action])
    review_metadata: dict[str, Any] = {
        "schema_version": GLOBAL_FRONTMATTER_REVIEW_SCHEMA_VERSION,
        "action": action,
        "relative_path": relative_path,
        "reviewed_at": reviewed_at,
        "reviewed_by": reviewer,
        "previous_review_status": _review_snapshot(frontmatter).get("review_status"),
    }
    if notes:
        review_metadata["review_notes"] = notes
    reviewed["global_review"] = review_metadata
    return reviewed


def _review_snapshot(frontmatter: Mapping[str, Any]) -> dict[str, Any]:
    governance = governance_from_frontmatter(dict(frontmatter))
    return {
        "memory_scope": str(frontmatter.get("memory_scope") or ""),
        "provenance_status": governance["provenance_status"],
        "confidence": governance["confidence"],
        "lifecycle_status": governance["lifecycle_status"],
        "review_status": governance["review_status"],
        "sensitivity_tier": governance["sensitivity_tier"],
        "can_use_as_instruction": bool(governance["can_use_as_instruction"]),
        "can_use_as_evidence": bool(governance["can_use_as_evidence"]),
        "requires_user_confirmation": bool(governance["requires_user_confirmation"]),
    }


def _source_review_snapshot(frontmatter: Mapping[str, Any], *, parse_error: str) -> dict[str, Any]:
    if not parse_error and frontmatter:
        return _review_snapshot(frontmatter)
    return {
        "memory_scope": str(frontmatter.get("memory_scope") or ""),
        "provenance_status": "imported",
        "confidence": 0.0,
        "lifecycle_status": "active",
        "review_status": "pending",
        "sensitivity_tier": "standard",
        "can_use_as_instruction": False,
        "can_use_as_evidence": True,
        "requires_user_confirmation": True,
    }


def _review_guard(content: str, *, relative_path: str, reviewed_frontmatter: Mapping[str, Any]) -> dict[str, Any]:
    default_available = _review_leaves_default_available(reviewed_frontmatter)
    receipt: dict[str, Any] = {
        "enabled": True,
        "required": default_available,
        "reason": "post_review_default_available" if default_available else "post_review_not_default_available",
        "candidate_count": 1 if default_available else 0,
        "blocked_count": 0,
        "finding_count": 0,
        "blocked_relative_paths": [],
        "findings": [],
    }
    if not default_available:
        return receipt

    findings = [
        {
            "type": str(finding.get("type") or "unknown"),
            "match_count": int(finding.get("match_count") or 1),
        }
        for finding in scan_for_injection(content)
    ]
    if findings:
        receipt["blocked_count"] = 1
        receipt["finding_count"] = len(findings)
        receipt["blocked_relative_paths"] = [relative_path]
        receipt["findings"] = [{"relative_path": relative_path, "findings": findings}]
    return receipt


def _confirm_guard_preview(
    frontmatter: Mapping[str, Any],
    *,
    body: str,
    relative_path: str,
    parse_error: str,
) -> dict[str, Any]:
    reviewed = _reviewed_frontmatter(
        frontmatter,
        action="confirm",
        reviewer="preview",
        notes="",
        relative_path=relative_path,
        reviewed_at="preview",
    )
    updated = _render_frontmatter_markdown(reviewed, body)
    receipt = _review_guard(updated, relative_path=relative_path, reviewed_frontmatter=reviewed)
    receipt["action"] = "confirm"
    if parse_error:
        receipt["source_parse_error"] = parse_error
        receipt["reason"] = f"{receipt.get('reason', 'post_review_default_available')}_from_parse_error_source"
    return receipt


def _unavailable_confirm_guard_preview(*, reason: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "action": "confirm",
        "required": False,
        "reason": reason,
        "candidate_count": 0,
        "blocked_count": 0,
        "finding_count": 0,
        "blocked_relative_paths": [],
        "findings": [],
    }


def _review_leaves_default_available(frontmatter: Mapping[str, Any]) -> bool:
    governance = governance_from_frontmatter(dict(frontmatter))
    return _is_default_available(
        exclude_default=frontmatter.get("exclude_from_default_search"),
        can_evidence=governance["can_use_as_evidence"],
        sensitivity=governance["sensitivity_tier"],
        lifecycle=governance["lifecycle_status"],
    )


def _index_reviewed_global_file(
    db: Path,
    *,
    root: Path,
    root_provenance: str,
    db_provenance: str,
    relative_path: str,
    path: Path,
    action: str,
    reviewer: str,
    notes: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    action_id = str(uuid.uuid4())
    conn = sqlite3.connect(str(db))
    try:
        init_memory_tables(conn)
        changed, file_id = _index_global_memory_file(conn, relative_path=relative_path, path=path)
        if file_id is None:
            conn.rollback()
            return {"ok": False, "error": "reviewed global memory file was not indexed", "indexed": False}
        conn.execute(
            """
            INSERT INTO memory_review_actions (
                action_id, action, reviewer, persona, file_id, path,
                before_metadata, after_metadata, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                action,
                reviewer,
                "global",
                file_id,
                str(path).replace("\\", "/"),
                _json_text(before),
                _json_text(after),
                notes or "",
            ),
        )
        record_memory_audit_event(
            conn,
            _GLOBAL_REVIEW_EVENT_TYPES[action],
            persona="global",
            target_kind="global_memory_file",
            target_id=str(file_id),
            payload={
                "action_id": action_id,
                "relative_path": relative_path,
                "root": _root_payload(root, provenance=root_provenance),
                "notes_present": bool(notes),
            },
            actor=reviewer,
            commit=False,
        )
        conn.commit()
    except Exception as exc:  # pragma: no cover - defensive CLI receipt boundary
        conn.rollback()
        return {
            "ok": False,
            "error": "global memory review index failed",
            "exception": exc.__class__.__name__,
            "indexed": False,
        }
    finally:
        conn.close()
    return {
        "ok": True,
        "db": _root_payload(db, provenance=db_provenance),
        "indexed": True,
        "changed": bool(changed),
        "action_id": action_id,
    }
