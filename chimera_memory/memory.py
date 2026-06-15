"""Curated memory system: index, search, and manage persona memory files.

Ported from the original chimera-memory MCP server. Indexes markdown files
with YAML frontmatter, provides FTS5 + semantic search, gap detection,
and consolidation analysis.
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Optional

from .memory_enhancement_queue import (
    ENHANCEMENT_JOB_STATUSES,
    memory_enhancement_claim_next,
    memory_enhancement_complete,
    memory_enhancement_enqueue,
    memory_enhancement_enqueue_authored,
    memory_worker_budget,
    memory_worker_claim_next,
    memory_worker_has_pending_job,
    memory_worker_heartbeat,
    memory_worker_submit_result,
)
from .memory_enhancement_shadow import memory_enhancement_shadow_enqueue
from .memory_entities import (
    ENTITY_TYPES,
    MENTION_ROLES,
    apply_enhancement_entities,
    memory_entity_connections,
    memory_entity_edge_query,
    memory_entity_index,
    memory_entity_query,
    memory_file_entity_links,
    normalize_entity_name,
    upsert_memory_entity,
    upsert_memory_entity_edge,
)
from .memory_frontmatter import parse_frontmatter
from .memory_file_edges import (
    MEMORY_FILE_EDGE_RELATION_TYPES,
    memory_file_edge_query,
    memory_file_edge_temporal_sweep,
    memory_file_edge_upsert,
)
from .memory_entity_wiki import memory_entity_wiki_batch, memory_entity_wiki_generate
from .sanitizer import build_fts_query
from .memory_import_atom_blogger import memory_import_atom_blogger_export as _memory_import_atom_blogger_export
from .memory_import_chatgpt import memory_import_chatgpt_export as _memory_import_chatgpt_export
from .memory_import_gmail import memory_import_gmail_mbox as _memory_import_gmail_mbox
from .memory_import_google_activity import memory_import_google_activity_export as _memory_import_google_activity_export
from .memory_import_grok import memory_import_grok_export as _memory_import_grok_export
from .memory_import_instagram import memory_import_instagram_export as _memory_import_instagram_export
from .memory_import_obsidian import memory_import_obsidian_vault as _memory_import_obsidian_vault
from .memory_import_perplexity import memory_import_perplexity_export as _memory_import_perplexity_export
from .memory_import_twitter import memory_import_twitter_archive as _memory_import_twitter_archive
from .memory_governance import (
    INSTRUCTION_GRADE_PROVENANCE,
    LIFECYCLE_STATUSES,
    PROVENANCE_STATUSES,
    REVIEW_STATUSES,
    SENSITIVITY_TIERS,
    governance_from_frontmatter,
)
from .memory_live_retrieval import memory_live_retrieval_check
from .memory_legacy_migration import (
    memory_legacy_frontmatter_retrofit as _memory_legacy_frontmatter_retrofit,
    memory_legacy_frontmatter_review_action as _memory_legacy_frontmatter_review_action,
    memory_legacy_migration_plan,
)
from .memory_profile_export import memory_profile_export
from .memory_pyramid import memory_pyramid_summary_build, memory_pyramid_summary_query
from .memory_observability import (
    _json_object,
    _json_text,
    memory_audit_query,
    memory_recall_trace_query,
    record_memory_audit_event,
    record_memory_recall_trace,
)
from .memory_auto_capture import build_auto_capture_plan, write_auto_capture_file
from .memory_authored_writeback import (
    build_authored_memory_write_plan,
    write_authored_memory_file,
    write_authored_memory_global_file,
    write_authored_memory_project_file,
)
from .memory_review import REVIEW_ACTIONS, memory_review_action as _db_memory_review_action, memory_review_pending
from .memory_scope import (
    MEMORY_SCOPE_AUTO,
    MEMORY_SCOPE_GLOBAL,
    MEMORY_SCOPE_PROJECT,
    global_root_filter_values,
    global_memory_root,
    infer_memory_scope,
    project_memory_roots,
    scope_filter_sql,
)
from .memory_schema import init_memory_tables

_FACADE_COMPAT_EXPORTS = (
    ENHANCEMENT_JOB_STATUSES,
    memory_enhancement_claim_next,
    memory_enhancement_complete,
    memory_enhancement_enqueue,
    memory_worker_budget,
    memory_worker_claim_next,
    memory_worker_has_pending_job,
    memory_worker_heartbeat,
    memory_worker_submit_result,
    ENTITY_TYPES,
    MENTION_ROLES,
    apply_enhancement_entities,
    memory_entity_connections,
    memory_entity_edge_query,
    memory_entity_index,
    memory_entity_query,
    memory_file_entity_links,
    normalize_entity_name,
    upsert_memory_entity,
    upsert_memory_entity_edge,
    MEMORY_FILE_EDGE_RELATION_TYPES,
    memory_file_edge_query,
    memory_file_edge_temporal_sweep,
    memory_file_edge_upsert,
    memory_entity_wiki_batch,
    memory_entity_wiki_generate,
    INSTRUCTION_GRADE_PROVENANCE,
    LIFECYCLE_STATUSES,
    PROVENANCE_STATUSES,
    REVIEW_STATUSES,
    SENSITIVITY_TIERS,
    memory_live_retrieval_check,
    memory_legacy_migration_plan,
    memory_profile_export,
    memory_pyramid_summary_query,
    _json_object,
    memory_audit_query,
    memory_recall_trace_query,
    REVIEW_ACTIONS,
    memory_review_pending,
)

log = logging.getLogger(__name__)

# Config
MEMORY_DIRS = {"memory", "reading", "shared"}
PROJECT_MEMORY_DIRS = {"memory", "project"}
INDEX_EXTENSIONS = {".md"}
SKIP_DIRS = {
    ".git",
    ".obsidian",
    ".claude",
    "__pycache__",
    "node_modules",
    ".chimera",
    "auth",
    "oauth",
    "pwa-state",
    "cache",
    "diagnostics",
}

# Consolidation thresholds
IMPORTANCE_DECAY_RATE = 0.05
MIN_IMPORTANCE_ACTIVE = 3
MIN_IMPORTANCE_STALE = 1
CONSOLIDATION_AGE_DAYS = 7

# Helpers
_FINGERPRINT_WHITESPACE_RE = re.compile(r"\s+")


def normalized_content_fingerprint(text: str) -> str:
    """Return OB1-style normalized SHA256 for duplicate-content detection."""
    normalized = _FINGERPRINT_WHITESPACE_RE.sub(" ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _frontmatter_bool(value: object, default: bool = False) -> int:
    if value is None:
        return 1 if default else 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return 1
    if text in {"0", "false", "no", "off"}:
        return 0
    return 1 if default else 0


def _source_refs_from_frontmatter(value: object) -> list[dict[str, object]]:
    raw_refs = value if isinstance(value, list) else [value] if isinstance(value, Mapping) else []
    refs: list[dict[str, object]] = []
    for raw in raw_refs:
        if not isinstance(raw, Mapping):
            continue
        kind = str(raw.get("kind") or raw.get("source_kind") or "").strip().lower()
        if not kind:
            continue
        ref = {
            "kind": kind,
            "uri": str(raw.get("uri") or "").strip() or None,
            "title": str(raw.get("title") or "").strip() or None,
            "timestamp": str(raw.get("timestamp") or raw.get("source_timestamp") or "").strip() or None,
            "metadata": {
                key: value
                for key, value in raw.items()
                if key not in {"kind", "source_kind", "uri", "title", "timestamp", "source_timestamp"}
            },
        }
        refs.append(ref)
    return refs


def _sync_memory_source_refs(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    persona: str,
    source_refs: object,
) -> None:
    refs = _source_refs_from_frontmatter(source_refs)
    conn.execute("DELETE FROM memory_file_source_refs WHERE file_id = ?", (file_id,))
    for ref in refs:
        conn.execute(
            """
            INSERT INTO memory_file_source_refs (
                file_id, persona, source_kind, uri, title, source_timestamp, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                persona,
                ref["kind"],
                ref["uri"],
                ref["title"],
                ref["timestamp"],
                json.dumps(ref["metadata"], sort_keys=True),
            ),
        )


def _artifact_refs_from_frontmatter(fm: Mapping[str, object]) -> list[dict[str, object]]:
    payload = fm.get("memory_payload")
    raw_value = payload.get("artifacts") if isinstance(payload, Mapping) else fm.get("artifacts")
    raw_refs = raw_value if isinstance(raw_value, list) else [raw_value] if isinstance(raw_value, Mapping) else []
    artifacts: list[dict[str, object]] = []
    for raw in raw_refs:
        if not isinstance(raw, Mapping):
            continue
        kind = str(raw.get("kind") or raw.get("artifact_kind") or "").strip().lower()
        uri = str(raw.get("uri") or "").strip()
        if not kind or not uri:
            continue
        artifacts.append(
            {
                "kind": kind,
                "uri": uri,
                "description": str(raw.get("description") or "").strip() or None,
                "metadata": {
                    key: value
                    for key, value in raw.items()
                    if key not in {"kind", "artifact_kind", "uri", "description"}
                },
            }
        )
    return artifacts


def _sync_memory_artifacts(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    persona: str,
    frontmatter: Mapping[str, object],
) -> None:
    artifacts = _artifact_refs_from_frontmatter(frontmatter)
    conn.execute("DELETE FROM memory_file_artifacts WHERE file_id = ?", (file_id,))
    for artifact in artifacts:
        conn.execute(
            """
            INSERT INTO memory_file_artifacts (
                file_id, persona, artifact_kind, uri, description, metadata
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                persona,
                artifact["kind"],
                artifact["uri"],
                artifact["description"],
                json.dumps(artifact["metadata"], sort_keys=True),
            ),
        )


def _sync_memory_provenance_indexes(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    persona: str,
    frontmatter: Mapping[str, object],
) -> None:
    _sync_memory_source_refs(conn, file_id=file_id, persona=persona, source_refs=frontmatter.get("source_refs"))
    _sync_memory_artifacts(conn, file_id=file_id, persona=persona, frontmatter=frontmatter)


_MEMORY_PAYLOAD_INDEX_FIELDS = (
    "memory_id",
    "memory_type",
    "decisions",
    "lessons",
    "constraints",
    "next_steps",
    "failures",
    "outputs",
    "unresolved_questions",
    "entities",
    "artifacts",
)
_MEMORY_PAYLOAD_INDEX_MARKER = "zzpayloadindexv1"


def _flatten_memory_payload_value(value: object, *, depth: int = 0) -> list[str]:
    if depth > 4 or value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, child in value.items():
            child_parts = _flatten_memory_payload_value(child, depth=depth + 1)
            for child_text in child_parts:
                parts.append(f"{key}: {child_text}")
        return parts
    if isinstance(value, list):
        parts = []
        for child in value:
            parts.extend(_flatten_memory_payload_value(child, depth=depth + 1))
        return parts
    return []


def memory_payload_index_text(frontmatter: Mapping[str, object], *, max_chars: int = 6000) -> str:
    """Return authored structured payload text for retrieval indexing."""
    payload = frontmatter.get("memory_payload")
    if not isinstance(payload, Mapping):
        return ""

    parts: list[str] = []
    for field in _MEMORY_PAYLOAD_INDEX_FIELDS:
        values = _flatten_memory_payload_value(payload.get(field))
        label = field.removeprefix("memory_").replace("_", " ")
        for value in values:
            parts.append(f"{label}: {value}")

    return " ".join(parts)[:max_chars]


def _memory_payload_index_stale(conn: sqlite3.Connection, *, file_id: int, payload_text: str) -> bool:
    if not payload_text:
        return False
    row = conn.execute("SELECT content FROM memory_fts WHERE rowid = ?", (file_id,)).fetchone()
    if row is None:
        return True
    return _MEMORY_PAYLOAD_INDEX_MARKER not in str(row[0])


def normalize_for_fts(text: str) -> str:
    """Expand text for better FTS5 matching.

    Splits CamelCase and file paths into separate tokens.
    """

    def expand_camel(match):
        word = match.group(0)
        parts = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", word)
        return f"{word} {parts}" if parts != word else word

    def expand_path(match):
        path = match.group(0)
        segments = re.split(r"[/\\]", path)
        segments = [s for s in segments if s and s not in ("", "C:")]
        return f"{path} {' '.join(segments)}"

    result = re.sub(r"[A-Za-z]:[/\\][^\s,;)}\]]+", expand_path, text)
    result = re.sub(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", expand_camel, result)
    return result

# â”€â”€â”€ File Discovery â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def discover_files(personas_dir: Path) -> list[tuple[str, str, Path]]:
    """Discover indexable markdown files allowed for the current runtime.

    When TRANSCRIPT_PERSONA env var is set, only files belonging to that persona
    are indexed from the persona tree. Global/shared and current-project memory
    may also be indexed because those scopes are intentionally non-private.

    When TRANSCRIPT_PERSONA is unset and project roots or Codex no-persona mode
    are configured, skips the persona tree and indexes only global/shared/project
    memory. Otherwise it keeps the legacy multi-persona aggregation behavior.

    Returns [(persona, relative_path, full_path)].
    """
    results = []

    scope_persona = os.environ.get("TRANSCRIPT_PERSONA", "").strip()
    project_roots = project_memory_roots()
    skip_persona_tree = _skip_persona_tree_for_runtime(scope_persona, project_roots)

    if personas_dir.exists() and not skip_persona_tree:
        for persona_dir in personas_dir.iterdir():
            if not persona_dir.is_dir() or persona_dir.name.startswith("."):
                continue
            for sub in persona_dir.iterdir():
                if not sub.is_dir() or sub.name.startswith("."):
                    continue
                if scope_persona and sub.name != scope_persona:
                    continue
                for index_root_name in sorted(MEMORY_DIRS - {"shared"}):
                    index_root = sub / index_root_name
                    if index_root.exists() and index_root.is_dir():
                        _walk_for_files(index_root, sub.name, sub, results)

    # Existing ChimeraAgency shared/ is treated as the v1 global layer.
    shared_dir = personas_dir.parent / "shared"
    if shared_dir.exists():
        _walk_for_files(shared_dir, "shared", shared_dir, results)

    global_dir = global_memory_root()
    if global_dir.exists() and global_dir.resolve() != shared_dir.resolve():
        _walk_for_files(global_dir, "global", global_dir, results)

    for project_id, project_dir in project_roots:
        if project_dir.exists():
            _walk_project_memory_files(project_dir, f"project:{project_id}", results)

    return results


def _skip_persona_tree_for_runtime(
    scope_persona: str,
    project_roots: tuple[tuple[str, Path], ...],
) -> bool:
    if scope_persona:
        return False
    if project_roots:
        return True
    client = os.environ.get("CHIMERA_CLIENT", "").strip().lower()
    surface = os.environ.get("CHIMERA_MEMORY_MCP_SURFACE", "").strip().lower()
    return client == "codex" or surface == "codex"


def _walk_project_memory_files(project_dir: Path, persona: str, results: list) -> None:
    """Index only explicit project-memory subtrees from a project root.

    A repo-level .chimera-memory folder may also contain auth/cache state. V1
    only indexes named project memory subdirs to keep credentials out of scope.
    """
    for root in _project_index_roots(project_dir):
        _walk_for_files(root, persona, project_dir, results)


def _project_index_roots(project_dir: Path) -> list[Path]:
    roots = []
    for name in sorted(PROJECT_MEMORY_DIRS):
        child = project_dir / name
        if child.exists() and child.is_dir():
            roots.append(child)
    return roots or [project_dir]


def _managed_reindex_roots(personas_dir: Path) -> list[Path]:
    """Return filesystem roots this runtime is authoritative to prune."""
    roots: list[Path] = []
    scope_persona = os.environ.get("TRANSCRIPT_PERSONA", "").strip()
    project_roots = project_memory_roots()
    skip_persona_tree = _skip_persona_tree_for_runtime(scope_persona, project_roots)

    if personas_dir.exists() and not skip_persona_tree:
        for persona_dir in personas_dir.iterdir():
            if not persona_dir.is_dir() or persona_dir.name.startswith("."):
                continue
            for sub in persona_dir.iterdir():
                if not sub.is_dir() or sub.name.startswith("."):
                    continue
                if scope_persona and sub.name != scope_persona:
                    continue
                for index_root_name in sorted(MEMORY_DIRS - {"shared"}):
                    index_root = sub / index_root_name
                    if index_root.exists() and index_root.is_dir():
                        roots.append(index_root.resolve(strict=False))

    shared_dir = personas_dir.parent / "shared"
    if shared_dir.exists():
        roots.append(shared_dir.resolve(strict=False))

    global_dir = global_memory_root()
    if global_dir.exists() and global_dir.resolve(strict=False) != shared_dir.resolve(strict=False):
        roots.append(global_dir.resolve(strict=False))

    for _project_id, project_dir in project_roots:
        if project_dir.exists():
            roots.extend(root.resolve(strict=False) for root in _project_index_roots(project_dir))
    return roots


def _is_under_any_root(path_text: str, roots: list[Path]) -> bool:
    if not path_text or not roots:
        return False
    try:
        path = Path(path_text).resolve(strict=False)
    except OSError:
        return False
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def cleanup_other_personas(conn, scope_persona: str) -> dict:
    """Delete memory rows belonging to other personas.

    Used to enforce the privacy boundary on existing data when TRANSCRIPT_PERSONA
    scope changes. Removes from memory_files, memory_embeddings, memory_fts.
    The 'shared' persona is preserved.

    Returns {'memory_files': N, 'memory_embeddings': N, 'memory_fts': N} counts.
    """
    if not scope_persona:
        return {"error": "scope_persona required"}

    cur = conn.cursor()
    counts = {}

    # Find file IDs to delete (everything except scope_persona plus shared/global/project scopes)
    cur.execute(
        """
        SELECT id FROM memory_files
         WHERE memory_scope = 'persona'
           AND persona NOT IN (?, 'shared', 'global')
        """,
        (scope_persona,),
    )
    ids_to_delete = [row[0] for row in cur.fetchall()]

    if not ids_to_delete:
        return {"memory_files": 0, "memory_embeddings": 0, "memory_fts": 0}

    placeholders = ",".join("?" * len(ids_to_delete))

    cur.execute(
        f"DELETE FROM memory_embeddings WHERE file_id IN ({placeholders})",
        ids_to_delete,
    )
    counts["memory_embeddings"] = cur.rowcount

    cur.execute(
        f"DELETE FROM memory_fts WHERE rowid IN ({placeholders})",
        ids_to_delete,
    )
    counts["memory_fts"] = cur.rowcount

    cur.execute(
        f"DELETE FROM memory_files WHERE id IN ({placeholders})",
        ids_to_delete,
    )
    counts["memory_files"] = cur.rowcount

    conn.commit()
    return counts


def _skip_memory_child_path(path: Path) -> bool:
    return path.name in SKIP_DIRS or path.name.startswith(".") or path.is_symlink()


def _memory_relative_path_allowed(relative_path: Path) -> bool:
    return not any(part in SKIP_DIRS or part.startswith(".") for part in relative_path.parts)


def _walk_for_files(directory: Path, persona: str, base: Path, results: list):
    for item in directory.iterdir():
        if _skip_memory_child_path(item):
            continue
        if item.is_dir():
            _walk_for_files(item, persona, base, results)
        elif item.is_file() and item.suffix in INDEX_EXTENSIONS:
            rel = str(item.relative_to(base)).replace("\\", "/")
            results.append((persona, rel, item))


# â”€â”€â”€ Indexing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _sync_memory_file_frontmatter_columns(
    conn: sqlite3.Connection,
    *,
    file_id: int,
    frontmatter: dict,
    tags_json: str,
    content_fingerprint: str,
    idempotency_key: str | None,
    governance: dict,
    exclude_from_default_search: int,
    memory_scope: str,
    project_id: str | None,
) -> None:
    """Refresh indexed frontmatter policy columns even when file content is unchanged."""
    conn.execute("""
        UPDATE memory_files SET
            fm_type=?, fm_importance=?, fm_created=?, fm_last_accessed=?,
            fm_access_count=?, fm_status=?, fm_about=?, fm_tags=?,
            fm_entity=?, fm_relationship_temperature=?, fm_trust_level=?,
            fm_trend=?, fm_failure_count=?, idempotency_key=?, content_fingerprint=?,
            fm_provenance_status=?, fm_confidence=?, fm_lifecycle_status=?,
            fm_review_status=?, fm_sensitivity_tier=?,
            fm_can_use_as_instruction=?, fm_can_use_as_evidence=?,
            fm_requires_user_confirmation=?, fm_exclude_from_default_search=?,
            memory_scope=?, project_id=?
        WHERE id=?
    """, (
        frontmatter.get("type"), frontmatter.get("importance"), frontmatter.get("created"),
        frontmatter.get("last_accessed"), frontmatter.get("access_count", 0),
        frontmatter.get("status", "active"), frontmatter.get("about"), tags_json,
        frontmatter.get("entity"), frontmatter.get("relationship_temperature"),
        frontmatter.get("trust_level"), frontmatter.get("trend"),
        frontmatter.get("failure_count", 0), idempotency_key, content_fingerprint,
        governance["provenance_status"], governance["confidence"],
        governance["lifecycle_status"], governance["review_status"],
        governance["sensitivity_tier"], governance["can_use_as_instruction"],
        governance["can_use_as_evidence"], governance["requires_user_confirmation"],
        exclude_from_default_search, memory_scope, project_id,
        file_id,
    ))


def index_file(conn: sqlite3.Connection, persona: str, relative_path: str,
               full_path: Path, maintenance: bool = False) -> bool:
    """Index a single memory file. Returns True if new or updated.

    Args:
        maintenance: If True, don't bump access counters (anti-inflation).
    """
    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    content_fingerprint = normalized_content_fingerprint(content)
    path_str = str(full_path).replace("\\", "/")

    fm, body = parse_frontmatter(content)
    payload_text = memory_payload_index_text(fm)
    idempotency_key = str(fm.get("idempotency_key") or "").strip() or None
    if idempotency_key:
        # idempotency_key backs a UNIQUE index. If a different file already owns
        # this key (e.g. legacy scope-agnostic authored keys colliding across
        # scopes), writing it here raises IntegrityError and aborts the entire
        # reindex. Degrade this row to no key + a warning instead of crashing
        # the run (wcp-01); the owning file keeps the key.
        conflict = conn.execute(
            "SELECT 1 FROM memory_files WHERE idempotency_key = ? AND path != ? LIMIT 1",
            (idempotency_key, path_str),
        ).fetchone()
        if conflict:
            log.warning(
                "idempotency_key already owned by another memory file; indexing %s without it",
                relative_path,
            )
            idempotency_key = None
    tags_json = json.dumps(fm.get("tags", []))
    governance = governance_from_frontmatter(fm)
    exclude_from_default_search = _frontmatter_bool(fm.get("exclude_from_default_search"), False)
    memory_scope, project_id = infer_memory_scope(persona, fm, relative_path=relative_path)
    now = time.time()
    row = conn.execute(
        "SELECT id, content_hash, idempotency_key FROM memory_files WHERE path = ?", (path_str,)
    ).fetchone()

    if row and row[1] == content_hash and row[2] == idempotency_key:
        if _memory_payload_index_stale(conn, file_id=int(row[0]), payload_text=payload_text):
            conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (row[0],))
        else:
            _sync_memory_file_frontmatter_columns(
                conn,
                file_id=int(row[0]),
                frontmatter=fm,
                tags_json=tags_json,
                content_fingerprint=content_fingerprint,
                idempotency_key=idempotency_key,
                governance=governance,
                exclude_from_default_search=exclude_from_default_search,
                memory_scope=memory_scope,
                project_id=project_id,
            )
            _sync_memory_provenance_indexes(
                conn,
                file_id=int(row[0]),
                persona=persona,
                frontmatter=fm,
            )
            return False

    elif row:
        conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (row[0],))

    if row and row[1] == content_hash and row[2] == idempotency_key:
        _sync_memory_provenance_indexes(
            conn,
            file_id=int(row[0]),
            persona=persona,
            frontmatter=fm,
        )
        file_id = row[0]
        payload_index_only = True
    else:
        payload_index_only = False

    if row and not payload_index_only:
        file_id = row[0]
        conn.execute("""
            UPDATE memory_files SET
                content_hash=?, indexed_at=?,
                fm_type=?, fm_importance=?, fm_created=?, fm_last_accessed=?,
                fm_access_count=?, fm_status=?, fm_about=?, fm_tags=?,
                fm_entity=?, fm_relationship_temperature=?, fm_trust_level=?,
                fm_trend=?, fm_failure_count=?, idempotency_key=?, content_fingerprint=?,
                fm_provenance_status=?, fm_confidence=?, fm_lifecycle_status=?,
                fm_review_status=?, fm_sensitivity_tier=?,
                fm_can_use_as_instruction=?, fm_can_use_as_evidence=?,
                fm_requires_user_confirmation=?, fm_exclude_from_default_search=?,
                memory_scope=?, project_id=?
            WHERE id=?
        """, (
            content_hash, now,
            fm.get("type"), fm.get("importance"), fm.get("created"),
            fm.get("last_accessed"), fm.get("access_count", 0),
            fm.get("status", "active"), fm.get("about"), tags_json,
            fm.get("entity"), fm.get("relationship_temperature"),
            fm.get("trust_level"), fm.get("trend"),
            fm.get("failure_count", 0), idempotency_key, content_fingerprint,
            governance["provenance_status"], governance["confidence"],
            governance["lifecycle_status"], governance["review_status"],
            governance["sensitivity_tier"], governance["can_use_as_instruction"],
            governance["can_use_as_evidence"], governance["requires_user_confirmation"],
            exclude_from_default_search, memory_scope, project_id,
            file_id
        ))
    elif not row:
        cursor = conn.execute("""
            INSERT INTO memory_files (
                path, persona, relative_path, content_hash, indexed_at,
                fm_type, fm_importance, fm_created, fm_last_accessed,
                fm_access_count, fm_status, fm_about, fm_tags,
                fm_entity, fm_relationship_temperature, fm_trust_level,
                fm_trend, fm_failure_count, idempotency_key, content_fingerprint,
                fm_provenance_status, fm_confidence, fm_lifecycle_status,
                fm_review_status, fm_sensitivity_tier,
                fm_can_use_as_instruction, fm_can_use_as_evidence,
                fm_requires_user_confirmation, fm_exclude_from_default_search,
                memory_scope, project_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            path_str, persona, relative_path, content_hash, now,
            fm.get("type"), fm.get("importance"), fm.get("created"),
            fm.get("last_accessed"), fm.get("access_count", 0),
            fm.get("status", "active"), fm.get("about"), tags_json,
            fm.get("entity"), fm.get("relationship_temperature"),
            fm.get("trust_level"), fm.get("trend"),
            fm.get("failure_count", 0), idempotency_key, content_fingerprint,
            governance["provenance_status"], governance["confidence"],
            governance["lifecycle_status"], governance["review_status"],
            governance["sensitivity_tier"], governance["can_use_as_instruction"],
            governance["can_use_as_evidence"], governance["requires_user_confirmation"],
            exclude_from_default_search, memory_scope, project_id,
        ))
        file_id = cursor.lastrowid

    index_text = body if not payload_text else f"{body}\n\n{_MEMORY_PAYLOAD_INDEX_MARKER} {payload_text}"
    fts_body = normalize_for_fts(index_text)
    conn.execute("""
        INSERT INTO memory_fts (rowid, path, persona, relative_path, content, fm_type, fm_tags, fm_about)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (file_id, path_str, persona, relative_path, fts_body, fm.get("type", ""), tags_json, fm.get("about", "")))
    _sync_memory_provenance_indexes(conn, file_id=int(file_id), persona=persona, frontmatter=fm)

    return True


def full_reindex(conn: sqlite3.Connection, personas_dir: Path, embed: bool = True) -> int:
    """Full reindex of all persona memory files."""
    files = discover_files(personas_dir)
    updated = 0
    updated_ids = []
    shadow_candidates: list[tuple[str, str]] = []

    for persona, rel, full_path in files:
        if index_file(conn, persona, rel, full_path, maintenance=True):
            updated += 1
            shadow_candidates.append((persona, rel))
            row = conn.execute("SELECT id FROM memory_files WHERE path = ?",
                               (str(full_path).replace("\\", "/"),)).fetchone()
            if row:
                updated_ids.append(row[0])
    conn.commit()

    # Clean up deleted files
    indexed_paths = {str(fp).replace("\\", "/") for _, _, fp in files}
    managed_roots = _managed_reindex_roots(personas_dir)
    rows = conn.execute("SELECT id, path FROM memory_files").fetchall()
    for file_id, path in rows:
        if path not in indexed_paths and _is_under_any_root(str(path or ""), managed_roots):
            conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (file_id,))
            conn.execute("DELETE FROM memory_embeddings WHERE file_id = ?", (file_id,))
            conn.execute("DELETE FROM memory_files WHERE id = ?", (file_id,))
    conn.commit()

    if embed and updated_ids:
        embed_memory_files(conn, updated_ids)
    if embed:
        missing = conn.execute("""
            SELECT f.id FROM memory_files f
            LEFT JOIN memory_embeddings e ON e.file_id = f.id
            WHERE e.file_id IS NULL
        """).fetchall()
        missing_ids = [r[0] for r in missing if r[0] not in updated_ids]
        if missing_ids:
            embed_memory_files(conn, missing_ids)

    for persona, rel in shadow_candidates:
        memory_enhancement_shadow_enqueue(
            conn,
            file_path=rel,
            persona=persona,
            reason="full_reindex",
        )

    return updated


def embed_memory_files(conn: sqlite3.Connection, file_ids: list[int]):
    """Generate and store embeddings for memory files using fastembed."""
    if not file_ids:
        return

    from .embeddings import embed_batch, pack_embedding

    placeholders = ",".join("?" * len(file_ids))
    rows = conn.execute(f"""
        SELECT id, path, persona, relative_path, fm_type, fm_about, fm_tags
        FROM memory_files WHERE id IN ({placeholders})
    """, file_ids).fetchall()

    texts = []
    ids = []
    for r in rows:
        path = Path(r[1])
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            frontmatter, body = parse_frontmatter(content)
        except OSError:
            frontmatter = {}
            body = ""

        text_parts = [f"persona:{r[2]}", f"file:{r[3]}"]
        if r[4]:
            text_parts.append(f"type:{r[4]}")
        if r[5]:
            text_parts.append(f"about:{r[5]}")
        if r[6]:
            tags = json.loads(r[6]) if r[6] else []
            if tags:
                text_parts.append(f"tags:{','.join(str(t) for t in tags)}")
        text_parts.append(body[:2000])
        payload_text = memory_payload_index_text(frontmatter, max_chars=2000)
        if payload_text:
            text_parts.append(f"memory_payload:{payload_text}")
        texts.append(" ".join(text_parts))
        ids.append(r[0])

    if not texts:
        return

    log.info("Embedding %d memory files...", len(texts))
    now = time.time()

    for file_id, emb in zip(ids, embed_batch(texts)):
        conn.execute("""
            INSERT OR REPLACE INTO memory_embeddings (file_id, embedding, embedded_at)
            VALUES (?, ?, ?)
        """, (file_id, pack_embedding(emb), now))
    conn.commit()


# â”€â”€â”€ Search Tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_BLOCKED_RETRIEVAL_LIFECYCLE = {"disputed", "rejected", "superseded"}


def _add_default_retrieval_safety_conditions(
    conditions: list[str],
    params: list[object],
    *,
    include_restricted: bool,
    include_blocked: bool,
) -> dict[str, object]:
    conditions.append("COALESCE(f.fm_can_use_as_evidence, 1) = 1")
    if not include_restricted:
        conditions.append("COALESCE(f.fm_sensitivity_tier, 'standard') <> 'restricted'")
    if not include_blocked:
        placeholders = ",".join("?" * len(_BLOCKED_RETRIEVAL_LIFECYCLE))
        conditions.append(f"COALESCE(f.fm_lifecycle_status, 'active') NOT IN ({placeholders})")
        params.extend(sorted(_BLOCKED_RETRIEVAL_LIFECYCLE))
    return {
        "can_use_as_evidence": True,
        "include_restricted": bool(include_restricted),
        "include_blocked": bool(include_blocked),
        "blocked_lifecycle": sorted(_BLOCKED_RETRIEVAL_LIFECYCLE),
    }


def _add_active_global_root_conditions(
    conditions: list[str],
    params: list[object],
    *,
    global_root: str | Path | None,
    scope_policy: dict[str, object] | None = None,
) -> bool:
    root_filter = global_root_filter_values(global_root)
    if root_filter is None:
        return False
    conditions.append(
        "("
        "COALESCE(f.memory_scope, '') <> 'global' "
        "OR LOWER(REPLACE(COALESCE(f.path, ''), '\\', '/')) = ? "
        "OR LOWER(REPLACE(COALESCE(f.path, ''), '\\', '/')) LIKE ?"
        ")"
    )
    params.extend(root_filter)
    if scope_policy is not None:
        scope_policy["global_root_filtered"] = True
    return True


def memory_search(
    conn: sqlite3.Connection,
    query: str,
    persona: Optional[str] = None,
    limit: int = 20,
    include_synthesis: bool = False,
    include_restricted: bool = False,
    include_blocked: bool = False,
    source_kind: Optional[str] = None,
    source_uri: Optional[str] = None,
    project_id: Optional[str] = None,
    scope: str = MEMORY_SCOPE_AUTO,
    global_root: str | Path | None = None,
) -> list[dict]:
    """Full-text search across memory files."""
    from .cognitive import reinforce_on_access_batch
    from .memory_relevance import quality_filter_candidates

    query_terms = query.split()
    fts_query = build_fts_query(query_terms)
    if not fts_query:
        return []

    conditions = [
        "memory_fts MATCH ?",
        "(? OR COALESCE(f.fm_exclude_from_default_search, 0) = 0)",
    ]
    params: list[object] = [fts_query, int(bool(include_synthesis))]
    safety_policy = _add_default_retrieval_safety_conditions(
        conditions,
        params,
        include_restricted=include_restricted,
        include_blocked=include_blocked,
    )
    scope_sql, scope_params, scope_policy = scope_filter_sql(
        table_alias="f",
        persona=persona,
        project_id=project_id,
        scope=scope,
    )
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    global_root_filtered = _add_active_global_root_conditions(
        conditions,
        params,
        global_root=global_root,
        scope_policy=scope_policy,
    )
    _add_source_ref_conditions(conditions, params, source_kind=source_kind, source_uri=source_uri)
    where = " AND ".join(conditions)
    total_count = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM memory_fts
        JOIN memory_files f ON f.id = memory_fts.rowid
        WHERE {where}
        """,
        params,
    ).fetchone()[0]
    candidate_limit = min(max(limit * 10, 100), 500)
    rows = conn.execute(f"""
        SELECT f.id, f.path, f.persona, f.relative_path, f.fm_type, f.fm_importance,
               f.fm_status, snippet(memory_fts, 3, '>>>', '<<<', '...', 40) as snippet,
               f.memory_scope, f.project_id
        FROM memory_fts
        JOIN memory_files f ON f.id = memory_fts.rowid
        WHERE {where}
        ORDER BY rank LIMIT ?
    """, params + [candidate_limit]).fetchall()

    candidates = [
        {"id": r[0], "path": r[1], "persona": r[2], "relative_path": r[3], "type": r[4],
         "importance": r[5], "status": r[6], "snippet": r[7],
         "memory_scope": r[8], "project_id": r[9]}
        for r in rows
    ]
    filtered_candidates, quality_policy = quality_filter_candidates(
        candidates,
        query_terms=query_terms,
    )
    results = filtered_candidates[:limit]

    reinforce_on_access_batch(conn, [item["id"] for item in results])
    record_memory_recall_trace(
        conn,
        tool_name="memory_search",
        query_text=query,
        persona=persona,
        requested_limit=limit,
        results=results,
        result_count=total_count,
        request_payload={
            "query": query,
            "persona": persona,
            "limit": limit,
            "source_kind": source_kind,
            "source_uri_supplied": bool(source_uri),
            "project_id": project_id,
            "scope": scope,
            "include_restricted": bool(include_restricted),
            "include_blocked": bool(include_blocked),
            "global_root_filter_enabled": global_root_filtered,
        },
        response_policy={
            "ranking": "fts5_rank",
            "returned": "quality_filtered_top_limit",
            "include_synthesis": bool(include_synthesis),
            "safety_policy": safety_policy,
            "scope_policy": scope_policy,
            "candidate_pool_limit": candidate_limit,
            "quality_gate": quality_policy,
        },
    )
    return results


def memory_query(
    conn: sqlite3.Connection, persona: Optional[str] = None,
    fm_type: Optional[str] = None, min_importance: Optional[int] = None,
    max_importance: Optional[int] = None, status: Optional[str] = None,
    tag: Optional[str] = None, about: Optional[str] = None,
    sort_by: str = "importance", sort_order: str = "DESC", limit: int = 50,
    include_synthesis: bool = False,
    include_restricted: bool = False,
    include_blocked: bool = False,
    source_kind: Optional[str] = None,
    source_uri: Optional[str] = None,
    project_id: Optional[str] = None,
    scope: str = MEMORY_SCOPE_AUTO,
    global_root: str | Path | None = None,
) -> list[dict]:
    """Structured query against frontmatter fields."""
    conditions, params = [], []

    scope_sql, scope_params, scope_policy = scope_filter_sql(
        table_alias="f",
        persona=persona,
        project_id=project_id,
        scope=scope,
    )
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    global_root_filtered = _add_active_global_root_conditions(
        conditions,
        params,
        global_root=global_root,
        scope_policy=scope_policy,
    )
    if fm_type:
        conditions.append("f.fm_type = ?")
        params.append(fm_type)
    if min_importance is not None:
        conditions.append("f.fm_importance >= ?")
        params.append(min_importance)
    if max_importance is not None:
        conditions.append("f.fm_importance <= ?")
        params.append(max_importance)
    if status:
        conditions.append("f.fm_status = ?")
        params.append(status)
    if tag:
        conditions.append("f.fm_tags LIKE ?")
        params.append(f"%{tag}%")
    if about:
        conditions.append("f.fm_about LIKE ?")
        params.append(f"%{about}%")
    if not include_synthesis:
        conditions.append("COALESCE(f.fm_exclude_from_default_search, 0) = 0")
    safety_policy = _add_default_retrieval_safety_conditions(
        conditions,
        params,
        include_restricted=include_restricted,
        include_blocked=include_blocked,
    )
    _add_source_ref_conditions(conditions, params, source_kind=source_kind, source_uri=source_uri)

    where = " AND ".join(conditions) if conditions else "1=1"
    valid_sorts = {
        "importance": "fm_importance", "created": "fm_created",
        "last_accessed": "fm_last_accessed", "access_count": "fm_access_count",
        "trust_level": "fm_trust_level", "relationship_temperature": "fm_relationship_temperature",
    }
    sort_col = valid_sorts.get(sort_by, "fm_importance")
    order = "ASC" if sort_order.upper() == "ASC" else "DESC"

    total_count = conn.execute(
        f"SELECT COUNT(*) FROM memory_files f WHERE {where}",
        params,
    ).fetchone()[0]

    rows = conn.execute(f"""
        SELECT id, path, persona, relative_path, fm_type, fm_importance,
               fm_created, fm_last_accessed, fm_access_count, fm_status,
               fm_about, fm_tags, fm_entity, fm_relationship_temperature,
               fm_trust_level, fm_trend, fm_failure_count,
               fm_provenance_status, fm_confidence, fm_lifecycle_status,
               fm_review_status, fm_sensitivity_tier,
               fm_can_use_as_instruction, fm_can_use_as_evidence,
               fm_requires_user_confirmation, fm_exclude_from_default_search,
               memory_scope, project_id
        FROM memory_files f WHERE {where}
        ORDER BY {sort_col} {order} NULLS LAST LIMIT ?
    """, params + [limit]).fetchall()

    results = [
        {"id": r[0], "path": r[1], "persona": r[2], "relative_path": r[3], "type": r[4],
         "importance": r[5], "created": r[6], "last_accessed": r[7],
         "access_count": r[8], "status": r[9], "about": r[10],
         "tags": json.loads(r[11]) if r[11] else [], "entity": r[12],
         "relationship_temperature": r[13], "trust_level": r[14],
         "trend": r[15], "failure_count": r[16],
         "provenance_status": r[17], "confidence": r[18],
         "lifecycle_status": r[19], "review_status": r[20],
         "sensitivity_tier": r[21], "can_use_as_instruction": bool(r[22]),
         "can_use_as_evidence": bool(r[23]),
         "requires_user_confirmation": bool(r[24]),
         "exclude_from_default_search": bool(r[25]),
         "memory_scope": r[26], "project_id": r[27]}
        for r in rows
    ]
    record_memory_recall_trace(
        conn,
        tool_name="memory_query",
        query_text=_memory_query_trace_text(
            persona=persona,
            fm_type=fm_type,
            min_importance=min_importance,
            max_importance=max_importance,
            status=status,
            tag=tag,
            about=about,
            source_kind=source_kind,
            source_uri_supplied=bool(source_uri),
            project_id=project_id,
            scope=scope,
        ),
        persona=persona,
        requested_limit=limit,
        results=results,
        result_count=total_count,
        request_payload={
            "persona": persona,
            "type": fm_type,
            "min_importance": min_importance,
            "max_importance": max_importance,
            "status": status,
            "tag": tag,
            "about": about,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "limit": limit,
            "source_kind": source_kind,
            "source_uri_supplied": bool(source_uri),
            "project_id": project_id,
            "scope": scope,
            "include_restricted": bool(include_restricted),
            "include_blocked": bool(include_blocked),
            "global_root_filter_enabled": global_root_filtered,
        },
        response_policy={
            "ranking": "frontmatter_sort",
            "sort_column": sort_col,
            "sort_order": order,
            "returned": "limited_results",
            "include_synthesis": bool(include_synthesis),
            "safety_policy": safety_policy,
            "scope_policy": scope_policy,
        },
    )
    return results


def _memory_query_trace_text(
    *,
    persona: Optional[str],
    fm_type: Optional[str],
    min_importance: Optional[int],
    max_importance: Optional[int],
    status: Optional[str],
    tag: Optional[str],
    about: Optional[str],
    source_kind: Optional[str],
    source_uri_supplied: bool,
    project_id: Optional[str],
    scope: str,
) -> str:
    parts = ["structured memory query"]
    for label, value in (
        ("persona", persona),
        ("type", fm_type),
        ("min_importance", min_importance),
        ("max_importance", max_importance),
        ("status", status),
        ("tag", tag),
        ("about", about),
        ("source_kind", source_kind),
        ("project_id", project_id),
        ("scope", scope),
    ):
        if value is not None and str(value).strip():
            parts.append(f"{label}={str(value).strip()[:80]}")
    if source_uri_supplied:
        parts.append("source_uri_supplied=true")
    return " ".join(parts)


def _add_source_ref_conditions(
    conditions: list[str],
    params: list[object],
    *,
    source_kind: Optional[str],
    source_uri: Optional[str],
) -> None:
    if not source_kind and not source_uri:
        return
    sub_conditions = ["sr.file_id = f.id"]
    if source_kind:
        sub_conditions.append("sr.source_kind = ?")
        params.append(source_kind.strip().lower())
    if source_uri:
        sub_conditions.append("sr.uri = ?")
        params.append(source_uri)
    conditions.append(
        "EXISTS (SELECT 1 FROM memory_file_source_refs sr WHERE "
        + " AND ".join(sub_conditions)
        + ")"
    )


def memory_source_ref_query(
    conn: sqlite3.Connection,
    persona: Optional[str] = None,
    source_kind: Optional[str] = None,
    uri: Optional[str] = None,
    limit: int = 50,
    *,
    project_id: Optional[str] = None,
    scope: str = MEMORY_SCOPE_AUTO,
    include_synthesis: bool = False,
    include_restricted: bool = False,
    include_blocked: bool = False,
    global_root: str | Path | None = None,
) -> list[dict]:
    """Query indexed memory source references without reading memory bodies."""
    conditions, params = [], []
    scope_sql, scope_params, scope_policy = scope_filter_sql(
        table_alias="f",
        persona=persona,
        project_id=project_id,
        scope=scope,
    )
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    _add_active_global_root_conditions(
        conditions,
        params,
        global_root=global_root,
        scope_policy=scope_policy,
    )
    if not include_synthesis:
        conditions.append("COALESCE(f.fm_exclude_from_default_search, 0) = 0")
    _add_default_retrieval_safety_conditions(
        conditions,
        params,
        include_restricted=include_restricted,
        include_blocked=include_blocked,
    )
    if source_kind:
        conditions.append("r.source_kind = ?")
        params.append(source_kind.strip().lower())
    if uri:
        conditions.append("r.uri = ?")
        params.append(uri)
    where = " AND ".join(conditions) if conditions else "1=1"
    rows = conn.execute(
        f"""
        SELECT r.persona, f.relative_path, f.fm_type, f.fm_importance,
               r.source_kind, r.uri, r.title, r.source_timestamp, r.metadata,
               f.memory_scope, f.project_id
        FROM memory_file_source_refs r
        JOIN memory_files f ON f.id = r.file_id
        WHERE {where}
        ORDER BY f.fm_importance DESC NULLS LAST, f.relative_path ASC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    return [
        {
            "persona": r[0],
            "relative_path": r[1],
            "type": r[2],
            "importance": r[3],
            "source_kind": r[4],
            "uri": r[5],
            "title": r[6],
            "timestamp": r[7],
            "metadata": json.loads(r[8]) if r[8] else {},
            "memory_scope": r[9],
            "project_id": r[10],
        }
        for r in rows
    ]


def memory_artifact_query(
    conn: sqlite3.Connection,
    persona: Optional[str] = None,
    artifact_kind: Optional[str] = None,
    uri: Optional[str] = None,
    limit: int = 50,
    *,
    project_id: Optional[str] = None,
    scope: str = MEMORY_SCOPE_AUTO,
    include_synthesis: bool = False,
    include_restricted: bool = False,
    include_blocked: bool = False,
    global_root: str | Path | None = None,
) -> list[dict]:
    """Query indexed artifact references without reading memory bodies."""
    conditions, params = [], []
    scope_sql, scope_params, scope_policy = scope_filter_sql(
        table_alias="f",
        persona=persona,
        project_id=project_id,
        scope=scope,
    )
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    _add_active_global_root_conditions(
        conditions,
        params,
        global_root=global_root,
        scope_policy=scope_policy,
    )
    if not include_synthesis:
        conditions.append("COALESCE(f.fm_exclude_from_default_search, 0) = 0")
    safety_policy = _add_default_retrieval_safety_conditions(
        conditions,
        params,
        include_restricted=include_restricted,
        include_blocked=include_blocked,
    )
    if artifact_kind:
        conditions.append("a.artifact_kind = ?")
        params.append(artifact_kind.strip().lower())
    if uri:
        conditions.append("a.uri = ?")
        params.append(uri)
    where = " AND ".join(conditions) if conditions else "1=1"
    rows = conn.execute(
        f"""
        SELECT a.persona, f.relative_path, f.fm_type, f.fm_importance,
               a.artifact_kind, a.uri, a.description, a.metadata,
               f.memory_scope, f.project_id
        FROM memory_file_artifacts a
        JOIN memory_files f ON f.id = a.file_id
        WHERE {where}
        ORDER BY f.fm_importance DESC NULLS LAST, f.relative_path ASC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    return [
        {
            "persona": r[0],
            "relative_path": r[1],
            "type": r[2],
            "importance": r[3],
            "artifact_kind": r[4],
            "uri": r[5],
            "description": r[6],
            "metadata": json.loads(r[7]) if r[7] else {},
            "memory_scope": r[8],
            "project_id": r[9],
        }
        for r in rows
    ]


def memory_recall(
    conn: sqlite3.Connection,
    concept: str,
    persona: Optional[str] = None,
    limit: int = 10,
    include_synthesis: bool = False,
    project_id: Optional[str] = None,
    scope: str = MEMORY_SCOPE_AUTO,
    min_similarity: float = 0.15,
    include_restricted: bool = False,
    include_blocked: bool = False,
    global_root: str | Path | None = None,
) -> list[dict]:
    """Semantic recall: find memories most similar to a concept."""
    from .embeddings import embed_text, unpack_embedding, cosine_similarity
    from .memory_live_retrieval import extract_live_retrieval_terms
    from .memory_relevance import quality_filter_candidates

    query_emb = embed_text(concept)
    try:
        selected_min_similarity = float(min_similarity)
    except (TypeError, ValueError):
        selected_min_similarity = 0.15
    enable_fts_rescue = selected_min_similarity <= 0.15
    try:
        selected_limit = max(0, int(limit))
    except (TypeError, ValueError):
        selected_limit = 10

    scope_sql, scope_params, scope_policy = scope_filter_sql(
        table_alias="f",
        persona=persona,
        project_id=project_id,
        scope=scope,
    )
    conditions = ["(? OR COALESCE(f.fm_exclude_from_default_search, 0) = 0)"]
    params: list[object] = [int(bool(include_synthesis))]
    safety_policy = _add_default_retrieval_safety_conditions(
        conditions,
        params,
        include_restricted=include_restricted,
        include_blocked=include_blocked,
    )
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    global_root_filtered = _add_active_global_root_conditions(
        conditions,
        params,
        global_root=global_root,
        scope_policy=scope_policy,
    )
    where = " AND ".join(conditions)
    rows = conn.execute(f"""
        SELECT f.id, f.path, f.persona, f.relative_path, f.fm_type,
               f.fm_importance, f.fm_status, f.fm_about, f.fm_tags, e.embedding,
               f.memory_scope, f.project_id, substr(memory_fts.content, 1, 2000) AS match_text,
               f.content_fingerprint
        FROM memory_files f
        JOIN memory_embeddings e ON e.file_id = f.id
        LEFT JOIN memory_fts ON memory_fts.rowid = f.id
        WHERE {where}
    """, params).fetchall()

    query_terms = extract_live_retrieval_terms(concept, limit=8)
    scored: list[tuple[float, dict]] = []
    semantic_scores: dict[int, float] = {}
    for r in rows:
        emb = unpack_embedding(r[9])
        sim = cosine_similarity(query_emb, emb)
        file_id = int(r[0])
        semantic_scores[file_id] = sim
        if sim < selected_min_similarity:
            continue
        scored.append((sim, {
            "id": r[0],
            "path": r[1],
            "persona": r[2],
            "relative_path": r[3],
            "type": r[4],
            "importance": r[5],
            "status": r[6],
            "about": r[7],
            "tags": r[8],
            "similarity": round(sim, 4),
            "semantic_score": sim,
            "fts_score": 0.0,
            "snippet": "",
            # Populate match_text from the already-selected body column so the
            # deterministic quality gate sees body tokens for purely-semantic
            # candidates (mirrors the FTS-rescue path) instead of near-empty
            # tokens that lean entirely on semantic_score thresholds (mfr-07).
            "match_text": r[12] or "",
            "memory_scope": r[10],
            "project_id": r[11],
            "content_fingerprint": r[13],
            "recall_source": "semantic",
        }))

    scored.sort(key=lambda x: -x[0])
    semantic_candidates = [item for _sim, item in scored]
    if selected_min_similarity <= 0:
        similarity_filtered_count = 0
    else:
        similarity_filtered_count = len(rows) - len(semantic_candidates)

    fts_candidates: list[dict] = []
    fts_policy: dict[str, object] = {"enabled": False, "reason": "empty_query", "raw_candidate_count": 0}
    fts_query = build_fts_query(query_terms)
    if not enable_fts_rescue:
        fts_policy = {
            "enabled": False,
            "reason": "min_similarity_above_default",
            "raw_candidate_count": 0,
            "query_term_count": len(query_terms),
        }
    elif fts_query:
        fts_limit = max(selected_limit * 4, 20)
        fts_rows = conn.execute(f"""
            SELECT f.id, f.path, f.persona, f.relative_path, f.fm_type,
                   f.fm_importance, f.fm_status, f.fm_about, f.fm_tags,
                   f.memory_scope, f.project_id,
                   snippet(memory_fts, 3, '>>>', '<<<', '...', 32) AS snippet,
                   substr(memory_fts.content, 1, 2000) AS match_text,
                   rank, f.content_fingerprint
            FROM memory_fts
            JOIN memory_files f ON f.id = memory_fts.rowid
            WHERE memory_fts MATCH ? AND {where}
            ORDER BY rank
            LIMIT ?
        """, [fts_query, *params, fts_limit]).fetchall()
        for index, r in enumerate(fts_rows):
            file_id = int(r[0])
            sim = semantic_scores.get(file_id)
            fts_candidates.append({
                "id": r[0],
                "path": r[1],
                "persona": r[2],
                "relative_path": r[3],
                "type": r[4],
                "importance": r[5],
                "status": r[6],
                "about": r[7],
                "tags": r[8],
                "similarity": round(sim, 4) if sim is not None else None,
                "semantic_score": max(0.0, sim or 0.0),
                "fts_score": 1.0 / (index + 1),
                "snippet": r[11] or "",
                "match_text": r[12] or "",
                "memory_scope": r[9],
                "project_id": r[10],
                "content_fingerprint": r[14],
                "recall_source": "fts_rescue",
                "requires_strict_term_coverage": True,
            })
        fts_policy = {
            "enabled": True,
            "raw_candidate_count": len(fts_rows),
            "query_term_count": len(query_terms),
        }

    combined_by_id: dict[int, dict] = {}
    for candidate in [*semantic_candidates, *fts_candidates]:
        file_id = int(candidate["id"])
        existing = combined_by_id.get(file_id)
        if existing is None:
            combined_by_id[file_id] = dict(candidate)
            continue
        existing["semantic_score"] = max(float(existing.get("semantic_score") or 0.0), float(candidate.get("semantic_score") or 0.0))
        existing["fts_score"] = max(float(existing.get("fts_score") or 0.0), float(candidate.get("fts_score") or 0.0))
        if candidate.get("similarity") is not None:
            existing["similarity"] = candidate.get("similarity")
        if candidate.get("snippet") and not existing.get("snippet"):
            existing["snippet"] = candidate.get("snippet")
        if candidate.get("match_text") and not existing.get("match_text"):
            existing["match_text"] = candidate.get("match_text")
        existing["recall_source"] = "hybrid"
        existing["requires_strict_term_coverage"] = bool(
            existing.get("requires_strict_term_coverage") or candidate.get("requires_strict_term_coverage")
        )

    ranked_candidates = []
    for item in combined_by_id.values():
        importance_score = max(0.0, min(1.0, float(item.get("importance") or 0) / 10.0))
        ranking_score = (
            0.65 * float(item.get("semantic_score") or 0.0)
            + 0.30 * float(item.get("fts_score") or 0.0)
            + 0.05 * importance_score
        )
        item["ranking_score"] = round(max(0.0, ranking_score), 4)
        ranked_candidates.append(item)
    ranked_candidates.sort(
        key=lambda item: (
            float(item.get("ranking_score") or 0.0),
            float(item.get("semantic_score") or 0.0),
            float(item.get("importance") or 0.0),
        ),
        reverse=True,
    )

    if selected_min_similarity <= 0:
        filtered_candidates = ranked_candidates
        quality_policy = {
            "enabled": False,
            "reason": "min_similarity_disabled",
            "raw_candidate_count": len(ranked_candidates),
            "filtered_count": 0,
            "returned_candidate_count": len(ranked_candidates),
        }
    else:
        filtered_candidates, quality_policy = quality_filter_candidates(
            ranked_candidates,
            query_terms=query_terms,
        )

    # Collapse content-duplicate files (different ids, identical body) the way
    # context_pack does, keeping the highest-ranked copy. Without this, shared and
    # global overlap surfaced the same memory twice (mfr-04).
    deduped_candidates: list[dict] = []
    seen_fingerprints: set[str] = set()
    for item in filtered_candidates:
        fingerprint = str(item.get("content_fingerprint") or "").strip()
        if fingerprint:
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
        deduped_candidates.append(item)
    top = deduped_candidates[:selected_limit]

    from .cognitive import reinforce_on_access_batch
    reinforce_on_access_batch(conn, [item["id"] for item in top])

    results = [
        {
            "id": item["id"],
            "path": item["path"],
            "persona": item["persona"],
            "relative_path": item["relative_path"],
            "type": item["type"],
            "importance": item["importance"],
            "status": item["status"],
            "about": item["about"],
            # FTS-only candidates never receive a semantic score; coalesce None
            # to 0.0 so the MCP formatter's f"{similarity:.3f}" cannot crash.
            "similarity": float(item.get("similarity") or 0.0),
            "ranking_score": item.get("ranking_score"),
            "memory_scope": item["memory_scope"],
            "project_id": item["project_id"],
            "metadata": {
                "recall_source": item.get("recall_source"),
                "fts_score": item.get("fts_score"),
            },
        }
        for item in top
    ]
    quality_filtered_count = int(quality_policy.get("filtered_count") or 0)
    filtered_count = max(0, len(rows) - len(results))
    record_memory_recall_trace(
        conn,
        tool_name="memory_recall",
        query_text=concept,
        persona=persona,
        requested_limit=limit,
        results=results,
        result_count=len(filtered_candidates),
        request_payload={
            "concept": concept,
            "persona": persona,
            "limit": limit,
            "project_id": project_id,
            "scope": scope,
            "min_similarity": selected_min_similarity,
            "raw_candidate_count": len(rows),
            "semantic_candidate_count": len(semantic_candidates),
            "fts_candidate_count": len(fts_candidates),
            "combined_candidate_count": len(ranked_candidates),
            "include_restricted": bool(include_restricted),
            "include_blocked": bool(include_blocked),
            "global_root_filter_enabled": global_root_filtered,
        },
        response_policy={
            "ranking": "hybrid_semantic_fts_rescue",
            "returned": "top_limit",
            "include_synthesis": bool(include_synthesis),
            "scope_policy": scope_policy,
            "safety_policy": safety_policy,
            "min_similarity": selected_min_similarity,
            "raw_candidate_count": len(rows),
            "similarity_filtered_count": similarity_filtered_count,
            "semantic_candidate_count": len(semantic_candidates),
            "fts_rescue": fts_policy,
            "combined_candidate_count": len(ranked_candidates),
            "quality_gate": quality_policy,
            "quality_filtered_count": quality_filtered_count,
            "filtered_count": filtered_count,
        },
    )
    return results


def memory_stats(
    conn: sqlite3.Connection,
    persona: Optional[str] = None,
    *,
    project_id: Optional[str] = None,
    scope: str = MEMORY_SCOPE_AUTO,
    include_synthesis: bool = False,
    include_restricted: bool = False,
    include_blocked: bool = False,
    global_root: str | Path | None = None,
) -> dict:
    """Get memory corpus statistics."""
    conditions, params = [], []
    scope_sql, scope_params, scope_policy = scope_filter_sql(
        table_alias="f",
        persona=persona,
        project_id=project_id,
        scope=scope,
    )
    if scope_sql:
        conditions.append(scope_sql)
        params.extend(scope_params)
    _add_active_global_root_conditions(
        conditions,
        params,
        global_root=global_root,
        scope_policy=scope_policy,
    )
    if not include_synthesis:
        conditions.append("COALESCE(f.fm_exclude_from_default_search, 0) = 0")
    safety_policy = _add_default_retrieval_safety_conditions(
        conditions,
        params,
        include_restricted=include_restricted,
        include_blocked=include_blocked,
    )
    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    total = conn.execute(f"SELECT COUNT(*) FROM memory_files f {where}", params).fetchone()[0]
    by_type = conn.execute(
        f"""
        SELECT f.fm_type, COUNT(*) FROM memory_files f {where}
        GROUP BY f.fm_type ORDER BY COUNT(*) DESC
        """,
        params,
    ).fetchall()
    by_status = conn.execute(
        f"""
        SELECT f.fm_status, COUNT(*) FROM memory_files f {where}
        GROUP BY f.fm_status ORDER BY COUNT(*) DESC
        """,
        params,
    ).fetchall()
    by_persona = conn.execute(
        f"""
        SELECT f.persona, COUNT(*) FROM memory_files f {where}
        GROUP BY f.persona ORDER BY COUNT(*) DESC
        """,
        params,
    ).fetchall()

    return {
        "total_files": total,
        "by_type": {r[0] or "unknown": r[1] for r in by_type},
        "by_status": {r[0] or "unknown": r[1] for r in by_status},
        "by_persona": {r[0]: r[1] for r in by_persona},
        "scope_policy": scope_policy,
        "safety_policy": safety_policy,
    }


def memory_content_duplicate_groups(
    conn: sqlite3.Connection,
    *,
    persona: Optional[str] = None,
    limit: int = 20,
    min_count: int = 2,
) -> list[dict]:
    """Find normalized-content duplicate groups without merging provenance."""
    conditions = ["content_fingerprint IS NOT NULL", "content_fingerprint <> ''"]
    params: list[object] = []
    if persona:
        conditions.append("persona = ?")
        params.append(persona)
    where = " AND ".join(conditions)
    group_rows = conn.execute(
        f"""
        SELECT content_fingerprint, COUNT(*) AS duplicate_count
        FROM memory_files
        WHERE {where}
        GROUP BY content_fingerprint
        HAVING COUNT(*) >= ?
        ORDER BY duplicate_count DESC, content_fingerprint ASC
        LIMIT ?
        """,
        [*params, max(2, int(min_count)), max(0, min(int(limit), 200))],
    ).fetchall()
    groups: list[dict] = []
    for fingerprint, duplicate_count in group_rows:
        file_conditions = ["content_fingerprint = ?"]
        file_params: list[object] = [fingerprint]
        if persona:
            file_conditions.append("persona = ?")
            file_params.append(persona)
        file_where = " AND ".join(file_conditions)
        file_rows = conn.execute(
            f"""
            SELECT id, path, persona, relative_path, fm_type, fm_about,
                   fm_review_status, fm_provenance_status, indexed_at
            FROM memory_files
            WHERE {file_where}
            ORDER BY persona ASC, relative_path ASC, path ASC
            """,
            file_params,
        ).fetchall()
        groups.append(
            {
                "content_fingerprint": fingerprint,
                "duplicate_count": duplicate_count,
                "files": [
                    {
                        "id": row[0],
                        "path": row[1],
                        "persona": row[2],
                        "relative_path": row[3],
                        "type": row[4],
                        "about": row[5],
                        "review_status": row[6],
                        "provenance_status": row[7],
                        "indexed_at": row[8],
                    }
                    for row in file_rows
                ],
            }
        )
    return groups


def _find_memory_file_for_review_route(conn: sqlite3.Connection, file_path: str):
    path = file_path.replace("\\", "/").strip()
    return conn.execute(
        """
        SELECT id, path, persona, relative_path
        FROM memory_files
        WHERE path = ? OR relative_path = ? OR path LIKE ?
        ORDER BY CASE
            WHEN path = ? THEN 0
            WHEN relative_path = ? THEN 1
            ELSE 2
        END
        LIMIT 1
        """,
        (path, path, f"%{path}%", path, path),
    ).fetchone()


def _persona_dir_from_indexed_file(full_path: Path, relative_path: str) -> Path | None:
    try:
        relative_parts = Path(relative_path).parts
    except (TypeError, ValueError):
        return None
    persona_root = full_path
    for _part in relative_parts:
        persona_root = persona_root.parent
    return persona_root.parent


def _is_frontmatter_migrated_memory(full_path: Path) -> bool:
    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    frontmatter, _body = parse_frontmatter(content)
    return isinstance(frontmatter.get("memory_payload"), Mapping) and isinstance(
        frontmatter.get("legacy_migration"), Mapping
    )


def memory_review_action(
    conn: sqlite3.Connection,
    *,
    file_path: str,
    action: str,
    reviewer: str = "user",
    notes: str = "",
) -> dict:
    """Apply a review action, routing migrated memories through durable frontmatter."""
    row = _find_memory_file_for_review_route(conn, file_path)
    if row is not None:
        full_path = Path(row[1])
        if full_path.exists() and _is_frontmatter_migrated_memory(full_path):
            personas_dir = _persona_dir_from_indexed_file(full_path, str(row[3]))
            if personas_dir is not None:
                result = memory_legacy_frontmatter_review_action(
                    conn,
                    personas_dir,
                    persona=str(row[2]),
                    relative_path=str(row[3]),
                    action=action,
                    reviewer=reviewer,
                    notes=notes,
                    write=True,
                )
                if result.get("ok"):
                    action_id = str(uuid.uuid4())
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
                            reviewer or "user",
                            row[2],
                            result.get("file_id") or row[0],
                            str(full_path).replace("\\", "/"),
                            _json_text(result.get("before", {})),
                            _json_text(result.get("after", {})),
                            notes or "",
                        ),
                    )
                    record_memory_audit_event(
                        conn,
                        {
                            "confirm": "memory_confirmed",
                            "edit": "memory_review_edit_requested",
                            "evidence_only": "memory_evidence_only",
                            "restrict_scope": "memory_restricted",
                            "mark_stale": "memory_marked_stale",
                            "merge": "memory_merged",
                            "reject": "memory_rejected",
                            "dispute": "memory_disputed",
                            "supersede": "memory_superseded",
                        }.get(action, "memory_review_action"),
                        persona=str(row[2]),
                        target_kind="memory_file",
                        target_id=str(result.get("file_id") or row[0]),
                        payload={
                            "action_id": action_id,
                            "path": str(full_path).replace("\\", "/"),
                            "notes": notes or "",
                            "durable_frontmatter": True,
                        },
                        actor=reviewer or "user",
                        commit=False,
                    )
                    conn.commit()
                    result["action_id"] = action_id
                    result["durable_frontmatter"] = True
                    return result
                if result.get("error") == "unsupported review action":
                    raise ValueError(f"unsupported review action: {action}")
                return result

    return _db_memory_review_action(
        conn,
        file_path=file_path,
        action=action,
        reviewer=reviewer,
        notes=notes,
    )


def memory_gaps(conn: sqlite3.Connection, persona: Optional[str] = None) -> dict:
    """Detect knowledge gaps using graph analysis."""
    try:
        import networkx as nx
    except ImportError:
        return {"error": "networkx not installed. pip install networkx"}

    where = "WHERE persona = ?" if persona else ""
    params = [persona] if persona else []

    rows = conn.execute(f"""
        SELECT id, path, persona, relative_path, fm_type, fm_importance, fm_tags, fm_about
        FROM memory_files {where}
    """, params).fetchall()

    if not rows:
        return {"error": "No files found", "gaps": [], "clusters": [], "bridges": []}

    G = nx.Graph()
    file_concepts = {}

    for r in rows:
        file_id, rel_path = r[0], r[3]
        fm_type = r[4] or "unknown"
        tags = json.loads(r[6]) if r[6] else []
        about = str(r[7]) if r[7] else ""

        concepts = set()
        for tag in tags:
            concepts.add(str(tag).lower())
        if about:
            concepts.add(about.lower())
        concepts.add(fm_type.lower())
        stem = Path(rel_path).stem.replace("-", " ").replace("_", " ").lower()
        for word in stem.split():
            if len(word) > 3:
                concepts.add(word)

        file_concepts[file_id] = concepts
        G.add_node(file_id, path=rel_path, persona=r[2], type=fm_type,
                    importance=r[5], concepts=list(concepts))

    file_ids = list(file_concepts.keys())
    for i in range(len(file_ids)):
        for j in range(i + 1, len(file_ids)):
            shared = file_concepts[file_ids[i]] & file_concepts[file_ids[j]]
            if shared:
                G.add_edge(file_ids[i], file_ids[j], weight=len(shared))

    components = list(nx.connected_components(G))
    clusters = []
    for comp in sorted(components, key=len, reverse=True)[:5]:
        files_in = [{"path": G.nodes[n]["path"], "type": G.nodes[n]["type"]} for n in comp]
        all_concepts = set()
        for n in comp:
            all_concepts.update(G.nodes[n].get("concepts", []))
        clusters.append({"size": len(comp), "files": files_in[:10], "top_concepts": sorted(all_concepts)[:15]})

    isolated = [{"path": G.nodes[n]["path"], "type": G.nodes[n]["type"]} for n in nx.isolates(G)]

    return {
        "total_nodes": len(G.nodes), "total_edges": len(G.edges),
        "connected_components": len(components),
        "clusters": clusters, "isolated_files": isolated[:20],
    }


def consolidation_report(conn: sqlite3.Connection, persona: Optional[str] = None) -> dict:
    """Dry-run analysis of what consolidation would do. Does NOT modify anything."""
    where = "WHERE persona = ?" if persona else ""
    params = [persona] if persona else []
    now = datetime.now()

    rows = conn.execute(f"""
        SELECT id, path, persona, relative_path, fm_type, fm_importance,
               fm_created, fm_last_accessed, fm_access_count, fm_status
        FROM memory_files {where}
    """, params).fetchall()

    stale_candidates = []
    archive_candidates = []

    for r in rows:
        importance = r[5]
        if importance is None:
            continue

        last_accessed = r[7]
        days_since = 30  # default
        if last_accessed:
            try:
                days_since = (now - datetime.fromisoformat(str(last_accessed))).days
            except (ValueError, TypeError):
                pass
        elif r[6]:
            try:
                days_since = (now - datetime.fromisoformat(str(r[6]))).days
            except (ValueError, TypeError):
                pass

        decayed = max(0, importance - IMPORTANCE_DECAY_RATE * days_since)
        status = r[9] or "active"

        if status == "active" and decayed < MIN_IMPORTANCE_ACTIVE:
            stale_candidates.append({"path": r[3], "persona": r[2],
                                     "importance": importance, "decayed": round(decayed, 2), "type": r[4]})

        if status in ("active", "stale") and decayed < MIN_IMPORTANCE_STALE:
            archive_candidates.append({"path": r[3], "persona": r[2],
                                       "importance": importance, "decayed": round(decayed, 2), "type": r[4]})

    return {
        "total_analyzed": len(rows),
        "stale_candidates": stale_candidates,
        "archive_candidates": archive_candidates,
        "summary": {
            "would_mark_stale": len(stale_candidates),
            "would_archive": len(archive_candidates),
        }
    }


def mark_failure(conn: sqlite3.Connection, file_path: str) -> bool:
    """Increment failure_count for a memory file. Returns True if found."""
    path_str = file_path.replace("\\", "/")
    row = conn.execute("SELECT id, fm_failure_count FROM memory_files WHERE path LIKE ?",
                        (f"%{path_str}%",)).fetchone()
    if not row:
        return False
    new_count = (row[1] or 0) + 1
    conn.execute("UPDATE memory_files SET fm_failure_count = ? WHERE id = ?", (new_count, row[0]))
    conn.commit()
    return True


def memory_auto_capture_session_close(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    persona: str,
    title: str = "",
    summary: str = "",
    session_text: str = "",
    act_now_text: str = "",
    source_session_id: str = "",
    write: bool = False,
    actor: str = "agent",
) -> dict:
    """Plan or write a governed session-close capture memory."""
    plan = build_auto_capture_plan(
        persona=persona,
        title=title,
        summary=summary,
        session_text=session_text,
        act_now_text=act_now_text,
        source_session_id=source_session_id,
    )
    if not plan.get("ok"):
        return plan

    audit_payload = {
        "schema_version": plan["schema_version"],
        "capture_id": plan["capture_id"],
        "relative_path": plan["relative_path"],
        "action_item_count": len(plan.get("action_items", [])),
        "guard_findings": plan.get("guard_findings", []),
        "write": bool(write),
    }

    if not write:
        record_memory_audit_event(
            conn,
            "memory_auto_capture_planned",
            persona=persona,
            target_kind="auto_capture",
            target_id=plan["capture_id"],
            payload=audit_payload,
            actor=actor,
        )
        preview = {key: value for key, value in plan.items() if key != "body"}
        preview["body_preview"] = plan["body"][:1200]
        # Surface blocking_findings at the top level so a caller can warn that the
        # write would be rejected by the safety scan, rather than reporting a clean
        # preview that then fails on persist (wcp-06).
        blocking = plan.get("blocking_findings") or []
        return {
            "ok": True,
            "written": False,
            "plan": preview,
            "blocking_findings": blocking,
            "safety_blocked": bool(blocking),
        }

    write_result = write_auto_capture_file(personas_dir, plan)
    if not write_result.get("ok"):
        return write_result

    full_path = Path(write_result["path"])
    relative_path = write_result["relative_path"]
    indexed = index_file(conn, persona, relative_path, full_path)
    row = conn.execute(
        "SELECT id FROM memory_files WHERE path = ?",
        (str(full_path).replace("\\", "/"),),
    ).fetchone()
    file_id = row[0] if row else None
    audit_payload.update(
        {
            "relative_path": relative_path,
            "path": str(full_path).replace("\\", "/"),
            "indexed": indexed,
            "file_id": file_id,
        }
    )
    record_memory_audit_event(
        conn,
        "memory_auto_capture_written",
        persona=persona,
        target_kind="memory_file",
        target_id=str(file_id or relative_path),
        payload=audit_payload,
        actor=actor,
        commit=False,
    )
    conn.commit()
    shadow_result = memory_enhancement_shadow_enqueue(
        conn,
        file_path=relative_path,
        persona=persona,
        reason="auto_capture_write",
    )
    return {
        "ok": True,
        "written": True,
        "path": str(full_path),
        "relative_path": relative_path,
        "file_id": file_id,
        "indexed": indexed,
        "capture_id": plan["capture_id"],
        "action_items": plan.get("action_items", []),
        "guard_findings": plan.get("guard_findings", []),
        "shadow_enhancement": shadow_result,
    }


def memory_authored_writeback(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    persona: str,
    payload: dict,
    relative_path: str = "",
    write: bool = False,
    enqueue: bool = True,
    requested_provider: str = "",
    requested_model: str = "",
    memory_scope: str = "persona",
    project_id: str = "",
    global_root: Path | None = None,
    project_root: Path | None = None,
    actor: str = "agent",
) -> dict:
    """Plan or write a structured authored memory and queue narrow enrichment."""
    plan = build_authored_memory_write_plan(
        payload=payload,
        persona=persona,
        relative_path=relative_path,
        memory_scope=memory_scope,
        project_id=project_id,
    )
    if not plan.get("ok"):
        return plan

    audit_payload = {
        "schema_version": plan["schema_version"],
        "relative_path": plan["relative_path"],
        "structured_field_count": plan["request_payload"]["contract"]["structured_field_count"],
        "guard_findings": plan.get("guard_findings", []),
        "write": bool(write),
        "enqueue": bool(enqueue),
        "memory_scope": plan.get("memory_scope"),
        "project_id": plan.get("project_id"),
    }
    if not write:
        record_memory_audit_event(
            conn,
            "memory_authored_writeback_planned",
            persona=persona,
            target_kind="authored_memory_writeback",
            target_id=plan["relative_path"],
            payload=audit_payload,
            actor=actor,
        )
        preview = {key: value for key, value in plan.items() if key != "body"}
        preview["body_preview"] = plan["body"][:1200]
        # Surface blocking_findings at the top level so a caller can warn that the
        # write would be rejected by the safety scan, rather than reporting a clean
        # preview that then fails on persist (wcp-06).
        blocking = plan.get("blocking_findings") or []
        return {
            "ok": True,
            "written": False,
            "plan": preview,
            "blocking_findings": blocking,
            "safety_blocked": bool(blocking),
        }

    if plan.get("memory_scope") == MEMORY_SCOPE_PROJECT:
        if project_root is None:
            return {"ok": False, "error": "project root required"}
        write_result = write_authored_memory_project_file(project_root, plan)
    elif plan.get("memory_scope") == MEMORY_SCOPE_GLOBAL:
        write_result = write_authored_memory_global_file(global_root or global_memory_root(), plan)
    else:
        write_result = write_authored_memory_file(personas_dir, plan)
    if not write_result.get("ok"):
        return write_result

    full_path = Path(write_result["path"])
    relative = write_result["relative_path"]
    indexed = index_file(conn, persona, relative, full_path)
    row = conn.execute(
        "SELECT id FROM memory_files WHERE path = ?",
        (str(full_path).replace("\\", "/"),),
    ).fetchone()
    file_id = row[0] if row else None
    queue_result = {"ok": True, "enqueued": False, "job": None}
    if enqueue:
        queue_result = memory_enhancement_enqueue_authored(
            conn,
            persona=persona,
            memory_payload=payload,
            provenance=plan.get("request_payload", {}).get("provenance") or {},
            source_ref=relative,
            file_id=file_id,
            requested_provider=requested_provider,
            requested_model=requested_model,
        )
    audit_payload.update(
        {
            "relative_path": relative,
            "path": str(full_path).replace("\\", "/"),
            "indexed": indexed,
            "file_id": file_id,
            "enrichment_job_id": (queue_result.get("job") or {}).get("job_id"),
        }
    )
    record_memory_audit_event(
        conn,
        "memory_authored_writeback_written",
        persona=persona,
        target_kind="memory_file",
        target_id=str(file_id or relative),
        payload=audit_payload,
        actor=actor,
        commit=False,
    )
    conn.commit()
    return {
        "ok": True,
        "written": True,
        "path": str(full_path),
        "relative_path": relative,
        "file_id": file_id,
        "indexed": indexed,
        "enrichment_job": queue_result,
        "guard_findings": plan.get("guard_findings", []),
    }


def memory_promote_snapshot(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    persona: str,
    source_file_path: str,
    destination_scope: str = "project",
    project_id: str = "",
    target_relative_path: str = "",
    write: bool = False,
    approved_by: str = "",
    actor: str = "agent",
) -> dict:
    """Preview or write a private memory snapshot into project/global scope."""
    from .memory_promotion import memory_promote_snapshot as _memory_promote_snapshot

    return _memory_promote_snapshot(
        conn,
        personas_dir,
        persona=persona,
        source_file_path=source_file_path,
        destination_scope=destination_scope,
        project_id=project_id,
        target_relative_path=target_relative_path,
        write=write,
        approved_by=approved_by,
        actor=actor,
        index_file_func=index_file,
        record_audit_event_func=record_memory_audit_event,
    )


def memory_legacy_frontmatter_retrofit(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    persona: str,
    relative_path: str,
    memory_payload: dict,
    write: bool = False,
    overwrite_payload: bool = False,
    actor: str = "agent",
) -> dict:
    """Preview or write a body-preserving legacy memory frontmatter retrofit."""
    result = _memory_legacy_frontmatter_retrofit(
        personas_dir,
        persona=persona,
        relative_path=relative_path,
        memory_payload=memory_payload,
        write=write,
        overwrite_payload=overwrite_payload,
        actor=actor,
    )
    if not result.get("ok"):
        return result

    audit_payload = {
        "schema_version": result["schema_version"],
        "relative_path": result["relative_path"],
        "write": bool(write),
        "body_preserved": bool(result.get("body_preserved")),
        "body_sha256": result.get("body_sha256"),
        "review_status": result.get("review_status"),
        "provenance_status": result.get("provenance_status"),
    }
    if not write:
        record_memory_audit_event(
            conn,
            "memory_legacy_frontmatter_retrofit_planned",
            persona=persona,
            target_kind="memory_file",
            target_id=result["relative_path"],
            payload=audit_payload,
            actor=actor,
        )
        return result

    full_path = Path(result["path"])
    indexed = index_file(conn, persona, result["relative_path"], full_path)
    row = conn.execute(
        "SELECT id FROM memory_files WHERE path = ?",
        (str(full_path).replace("\\", "/"),),
    ).fetchone()
    file_id = row[0] if row else None
    audit_payload.update(
        {
            "path": str(full_path).replace("\\", "/"),
            "indexed": indexed,
            "file_id": file_id,
        }
    )
    record_memory_audit_event(
        conn,
        "memory_legacy_frontmatter_retrofit_written",
        persona=persona,
        target_kind="memory_file",
        target_id=str(file_id or result["relative_path"]),
        payload=audit_payload,
        actor=actor,
        commit=False,
    )
    conn.commit()
    result.update({"indexed": indexed, "file_id": file_id})
    return result


def memory_legacy_frontmatter_review_action(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    persona: str,
    relative_path: str,
    action: str,
    reviewer: str = "user",
    notes: str = "",
    write: bool = False,
) -> dict:
    """Preview or write a durable frontmatter review action for a migrated memory."""
    result = _memory_legacy_frontmatter_review_action(
        personas_dir,
        persona=persona,
        relative_path=relative_path,
        action=action,
        reviewer=reviewer,
        notes=notes,
        write=write,
    )
    if not result.get("ok"):
        return result

    audit_payload = {
        "schema_version": result["schema_version"],
        "relative_path": result["relative_path"],
        "action": result["action"],
        "write": bool(write),
        "body_preserved": bool(result.get("body_preserved")),
        "body_sha256": result.get("body_sha256"),
        "before": result.get("before", {}),
        "after": result.get("after", {}),
    }
    if not write:
        record_memory_audit_event(
            conn,
            "memory_legacy_frontmatter_review_planned",
            persona=persona,
            target_kind="memory_file",
            target_id=result["relative_path"],
            payload=audit_payload,
            actor=reviewer or "user",
        )
        return result

    full_path = Path(result["path"])
    indexed = index_file(conn, persona, result["relative_path"], full_path)
    row = conn.execute(
        "SELECT id FROM memory_files WHERE path = ?",
        (str(full_path).replace("\\", "/"),),
    ).fetchone()
    file_id = row[0] if row else None
    audit_payload.update(
        {
            "path": str(full_path).replace("\\", "/"),
            "indexed": indexed,
            "file_id": file_id,
        }
    )
    record_memory_audit_event(
        conn,
        "memory_legacy_frontmatter_review_written",
        persona=persona,
        target_kind="memory_file",
        target_id=str(file_id or result["relative_path"]),
        payload=audit_payload,
        actor=reviewer or "user",
        commit=False,
    )
    conn.commit()
    result.update({"indexed": indexed, "file_id": file_id})
    return result


def memory_import_chatgpt_export(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    export_path: str,
    persona: str,
    limit: int = 50,
    write: bool = False,
    force: bool = False,
    build_pyramid: bool = True,
    actor: str = "agent",
) -> dict:
    """Plan or write governed memories from a ChatGPT conversations export."""
    return _memory_import_chatgpt_export(
        conn,
        personas_dir,
        export_path=export_path,
        persona=persona,
        index_file_func=index_file,
        pyramid_summary_builder=memory_pyramid_summary_build,
        limit=limit,
        write=write,
        force=force,
        build_pyramid=build_pyramid,
        actor=actor,
    )


def memory_import_obsidian_vault(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    vault_path: str,
    persona: str,
    limit: int = 200,
    write: bool = False,
    force: bool = False,
    build_pyramid: bool = True,
    actor: str = "agent",
) -> dict:
    """Plan or write governed memories from an Obsidian vault."""
    return _memory_import_obsidian_vault(
        conn,
        personas_dir,
        vault_path=vault_path,
        persona=persona,
        index_file_func=index_file,
        pyramid_summary_builder=memory_pyramid_summary_build,
        limit=limit,
        write=write,
        force=force,
        build_pyramid=build_pyramid,
        actor=actor,
    )


def memory_import_gmail_mbox(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    import_path: str,
    persona: str,
    limit: int = 200,
    write: bool = False,
    force: bool = False,
    build_pyramid: bool = True,
    actor: str = "agent",
) -> dict:
    """Plan or write governed memories from Gmail mbox exports."""
    return _memory_import_gmail_mbox(
        conn,
        personas_dir,
        import_path=import_path,
        persona=persona,
        index_file_func=index_file,
        pyramid_summary_builder=memory_pyramid_summary_build,
        limit=limit,
        write=write,
        force=force,
        build_pyramid=build_pyramid,
        actor=actor,
    )


def memory_import_perplexity_export(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    import_path: str,
    persona: str,
    limit: int = 200,
    write: bool = False,
    force: bool = False,
    build_pyramid: bool = True,
    actor: str = "agent",
) -> dict:
    """Plan or write governed memories from Perplexity exports."""
    return _memory_import_perplexity_export(
        conn,
        personas_dir,
        import_path=import_path,
        persona=persona,
        index_file_func=index_file,
        pyramid_summary_builder=memory_pyramid_summary_build,
        limit=limit,
        write=write,
        force=force,
        build_pyramid=build_pyramid,
        actor=actor,
    )


def memory_import_grok_export(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    import_path: str,
    persona: str,
    limit: int = 200,
    write: bool = False,
    force: bool = False,
    build_pyramid: bool = True,
    actor: str = "agent",
) -> dict:
    """Plan or write governed memories from Grok exports."""
    return _memory_import_grok_export(
        conn,
        personas_dir,
        import_path=import_path,
        persona=persona,
        index_file_func=index_file,
        pyramid_summary_builder=memory_pyramid_summary_build,
        limit=limit,
        write=write,
        force=force,
        build_pyramid=build_pyramid,
        actor=actor,
    )


def memory_import_twitter_archive(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    import_path: str,
    persona: str,
    limit: int = 200,
    write: bool = False,
    force: bool = False,
    build_pyramid: bool = True,
    actor: str = "agent",
) -> dict:
    """Plan or write governed memories from X/Twitter tweet archives."""
    return _memory_import_twitter_archive(
        conn,
        personas_dir,
        import_path=import_path,
        persona=persona,
        index_file_func=index_file,
        pyramid_summary_builder=memory_pyramid_summary_build,
        limit=limit,
        write=write,
        force=force,
        build_pyramid=build_pyramid,
        actor=actor,
    )


def memory_import_instagram_export(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    import_path: str,
    persona: str,
    limit: int = 200,
    write: bool = False,
    force: bool = False,
    build_pyramid: bool = True,
    actor: str = "agent",
) -> dict:
    """Plan or write governed memories from Instagram exports."""
    return _memory_import_instagram_export(
        conn,
        personas_dir,
        import_path=import_path,
        persona=persona,
        index_file_func=index_file,
        pyramid_summary_builder=memory_pyramid_summary_build,
        limit=limit,
        write=write,
        force=force,
        build_pyramid=build_pyramid,
        actor=actor,
    )


def memory_import_google_activity_export(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    import_path: str,
    persona: str,
    limit: int = 200,
    write: bool = False,
    force: bool = False,
    build_pyramid: bool = True,
    actor: str = "agent",
) -> dict:
    """Plan or write governed memories from Google Activity exports."""
    return _memory_import_google_activity_export(
        conn,
        personas_dir,
        import_path=import_path,
        persona=persona,
        index_file_func=index_file,
        pyramid_summary_builder=memory_pyramid_summary_build,
        limit=limit,
        write=write,
        force=force,
        build_pyramid=build_pyramid,
        actor=actor,
    )


def memory_import_atom_blogger_export(
    conn: sqlite3.Connection,
    personas_dir: Path,
    *,
    import_path: str,
    persona: str,
    limit: int = 200,
    write: bool = False,
    force: bool = False,
    build_pyramid: bool = True,
    actor: str = "agent",
) -> dict:
    """Plan or write governed memories from Atom/Blogger exports."""
    return _memory_import_atom_blogger_export(
        conn,
        personas_dir,
        import_path=import_path,
        persona=persona,
        index_file_func=index_file,
        pyramid_summary_builder=memory_pyramid_summary_build,
        limit=limit,
        write=write,
        force=force,
        build_pyramid=build_pyramid,
        actor=actor,
    )


# â”€â”€â”€ Live File Watcher â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def start_memory_watcher(db, personas_dir: Path):
    """Watch persona memory dirs for .md changes and incrementally reindex.

    Returns the watchdog Observer (caller can stop it) or None if watchdog
    is unavailable. The watcher opens its own SQLite connections per event,
    so it is safe to run alongside the cached memory_conn in the main thread.
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        log.warning("watchdog not installed, memory file watcher disabled")
        return None

    personas_dir = Path(personas_dir)
    shared_dir = personas_dir.parent / "shared"
    global_dir = global_memory_root()
    project_roots = project_memory_roots()

    try:
        personas_root = personas_dir.resolve()
    except OSError:
        personas_root = personas_dir
    try:
        shared_root = shared_dir.resolve()
    except OSError:
        shared_root = shared_dir
    try:
        global_root = global_dir.resolve()
    except OSError:
        global_root = global_dir
    resolved_project_roots: list[tuple[str, Path, Path]] = []
    for project_id, project_dir in project_roots:
        try:
            project_root = project_dir.resolve()
        except OSError:
            project_root = project_dir
        resolved_project_roots.append((project_id, project_dir, project_root))

    import os as _os
    _scope_persona = _os.environ.get("TRANSCRIPT_PERSONA", "").strip()
    skip_persona_tree = _skip_persona_tree_for_runtime(_scope_persona, project_roots)

    def _resolve(path: Path) -> tuple[str, str] | None:
        """Map an absolute path to (persona, relative_path) or None.

        Respects TRANSCRIPT_PERSONA env var: returns None for files belonging
        to other personas. Shared content is always allowed through.
        """
        if path.suffix not in INDEX_EXTENSIONS:
            return None
        if path.is_symlink():
            return None
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        # shared/** â†’ persona="shared", rel relative to shared_root
        try:
            rel = resolved.relative_to(shared_root)
            if not _memory_relative_path_allowed(rel):
                return None
            return ("shared", str(rel).replace("\\", "/"))
        except ValueError:
            pass

        if global_root is not None and global_dir.exists():
            try:
                rel = resolved.relative_to(global_root)
                if not _memory_relative_path_allowed(rel):
                    return None
                return ("global", str(rel).replace("\\", "/"))
            except ValueError:
                pass

        for project_id, project_dir, project_root in resolved_project_roots:
            if not project_dir.exists():
                continue
            try:
                rel = resolved.relative_to(project_root)
            except ValueError:
                continue
            if not _memory_relative_path_allowed(rel):
                return None
            parts = rel.parts
            if parts and parts[0] in PROJECT_MEMORY_DIRS:
                return (f"project:{project_id}", str(rel).replace("\\", "/"))
            if not any((project_root / name).exists() for name in PROJECT_MEMORY_DIRS):
                return (f"project:{project_id}", str(rel).replace("\\", "/"))

        if skip_persona_tree:
            return None

        # personas/<persona>/<sub>/** â†’ persona=<sub>, rel relative to <sub>
        try:
            rel_full = resolved.relative_to(personas_root)
        except ValueError:
            return None
        parts = rel_full.parts
        if not _memory_relative_path_allowed(rel_full):
            return None
        if len(parts) < 3:
            return None
        # Privacy boundary: skip files belonging to other personas
        if _scope_persona and parts[1] != _scope_persona:
            return None
        if parts[2] not in (MEMORY_DIRS - {"shared"}):
            return None
        sub_root = personas_root / parts[0] / parts[1]
        try:
            rel = resolved.relative_to(sub_root)
        except ValueError:
            return None
        if not _memory_relative_path_allowed(rel):
            return None
        return (parts[1], str(rel).replace("\\", "/"))

    def _upsert(path: Path):
        resolved = _resolve(path)
        if not resolved:
            return
        persona, rel = resolved
        try:
            with db.connection() as conn:
                init_memory_tables(conn)
                changed = index_file(conn, persona, rel, path, maintenance=True)
                if changed:
                    row = conn.execute(
                        "SELECT id FROM memory_files WHERE path = ?",
                        (str(path).replace("\\", "/"),),
                    ).fetchone()
                    if row:
                        try:
                            embed_memory_files(conn, [row[0]])
                        except Exception:
                            log.exception("Embedding failed for %s", path)
                conn.commit()
                if changed:
                    memory_enhancement_shadow_enqueue(
                        conn,
                        file_path=rel,
                        persona=persona,
                        reason="file_watcher",
                    )
        except Exception:
            log.exception("Error reindexing memory file %s", path)

    def _delete(path: Path):
        if path.suffix not in INDEX_EXTENSIONS:
            return
        path_str = str(path).replace("\\", "/")
        try:
            with db.connection() as conn:
                init_memory_tables(conn)
                row = conn.execute(
                    "SELECT id FROM memory_files WHERE path = ?", (path_str,)
                ).fetchone()
                if not row:
                    return
                file_id = row[0]
                conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (file_id,))
                conn.execute("DELETE FROM memory_embeddings WHERE file_id = ?", (file_id,))
                conn.execute("DELETE FROM memory_files WHERE id = ?", (file_id,))
                conn.commit()
        except Exception:
            log.exception("Error removing memory file from index %s", path)

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if not event.is_directory:
                _upsert(Path(event.src_path))

        def on_created(self, event):
            if not event.is_directory:
                _upsert(Path(event.src_path))

        def on_deleted(self, event):
            if not event.is_directory:
                _delete(Path(event.src_path))

        def on_moved(self, event):
            if event.is_directory:
                return
            _delete(Path(event.src_path))
            _upsert(Path(event.dest_path))

    observer = Observer()
    handler = _Handler()
    scheduled = []
    if personas_dir.exists() and not skip_persona_tree:
        observer.schedule(handler, str(personas_dir), recursive=True)
        scheduled.append(str(personas_dir))
    if shared_dir.exists():
        observer.schedule(handler, str(shared_dir), recursive=True)
        scheduled.append(str(shared_dir))
    if global_dir.exists() and global_dir.resolve() != shared_dir.resolve():
        observer.schedule(handler, str(global_dir), recursive=True)
        scheduled.append(str(global_dir))
    for project_id, project_dir, _project_root in resolved_project_roots:
        if project_dir.exists() and project_id:
            observer.schedule(handler, str(project_dir), recursive=True)
            scheduled.append(str(project_dir))

    if not scheduled:
        log.warning("start_memory_watcher: no directories to watch")
        return None

    observer.daemon = True
    observer.start()
    log.info("Memory file watcher started on %s", ", ".join(scheduled))
    return observer

