"""JSONL indexer: import log, backfill, and file watching."""

import hashlib
import fnmatch
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable

from .db import TranscriptDB
from .parser import get_parser
from .sanitizer import sanitize_content

log = logging.getLogger(__name__)

BATCH_SIZE = 500
TRANSCRIPT_EXCLUDE_GLOBS_ENV = "CHIMERA_MEMORY_TRANSCRIPT_EXCLUDE_GLOBS"
TRANSCRIPT_EXCLUDE_SESSION_IDS_ENV = "CHIMERA_MEMORY_TRANSCRIPT_EXCLUDE_SESSION_IDS"


def get_file_hash(filepath: Path) -> str:
    """Compute MD5 hash of a file (chunked for large files)."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _split_filter_env(value: str | None) -> list[str]:
    return [part.strip() for part in re.split(r"[;,\n]+", str(value or "")) if part.strip()]


def _normalize_filter_pattern(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").lower().rstrip("/")


class Indexer:
    """Indexes JSONL session files into the transcript database."""

    def __init__(
        self,
        db: TranscriptDB,
        jsonl_dir: str | Path,
        persona: str | None = None,
        parser_format: str | None = None,
        recursive: bool | None = None,
    ):
        self.db = db
        self.jsonl_dir = Path(jsonl_dir).expanduser()
        self.persona = persona
        explicit_format = parser_format or os.environ.get("CHIMERA_CLIENT")
        if explicit_format:
            self.parser = get_parser(explicit_format)
            self._format_forced = True
        else:
            # No explicit client: resolve the active harness so a Codex/Hermes
            # launch is not silently parsed as Claude. Detection never raises.
            try:
                from .harness import detect_harness

                detected = detect_harness().client
            except Exception:  # pragma: no cover - detection must never break indexing
                detected = None
            self.parser = get_parser(detected or ".jsonl")
            self._format_forced = False
        self.recursive = self.parser.recursive if recursive is None else recursive
        persona_root = os.environ.get("CHIMERA_PERSONA_ROOT")
        self.persona_root = self._normalize_path(persona_root) if persona_root else None
        # No-persona Codex project mode: when a project root is configured, scope
        # Codex session indexing to sessions whose cwd is under it instead of
        # ingesting the whole ~/.codex/sessions tree across unrelated projects.
        self.project_roots = self._collect_project_roots()
        self.exclude_globs = [_normalize_filter_pattern(pattern) for pattern in _split_filter_env(os.environ.get(TRANSCRIPT_EXCLUDE_GLOBS_ENV))]
        self.exclude_session_ids = set(_split_filter_env(os.environ.get(TRANSCRIPT_EXCLUDE_SESSION_IDS_ENV)))
        self._stop_event = threading.Event()
        self._watcher_thread = None
        self._poll_thread = None

    @staticmethod
    def _normalize_path(value: str | Path | None) -> str | None:
        if not value:
            return None
        try:
            return str(Path(value).expanduser().resolve()).replace("\\", "/").lower().rstrip("/")
        except (OSError, RuntimeError):
            return str(value).replace("\\", "/").lower().rstrip("/")

    @staticmethod
    def _collect_project_roots() -> list[str]:
        raw: list[str] = list(_split_filter_env(os.environ.get("CHIMERA_MEMORY_PROJECT_ROOTS")))
        single = os.environ.get("CHIMERA_MEMORY_PROJECT_ROOT", "").strip()
        if single:
            raw.append(single)
        roots: list[str] = []
        for value in raw:
            norm = Indexer._normalize_path(value)
            if norm and norm not in roots:
                roots.append(norm)
        return roots

    def _cwd_under_any_root(self, cwd: str | None, roots: list[str]) -> bool:
        if not cwd:
            return False
        return any(cwd == root or cwd.startswith(root + "/") for root in roots)

    def _should_index_file(self, path: Path) -> bool:
        normalized_path = self._normalize_path(path) or str(path).replace("\\", "/").lower()
        for pattern in self.exclude_globs:
            if not pattern:
                continue
            if (
                fnmatch.fnmatch(normalized_path, pattern)
                or fnmatch.fnmatch(path.name.lower(), pattern)
                or pattern in normalized_path
            ):
                log.info("Skipping %s: matched transcript exclude glob", path)
                return False
        if self.exclude_session_ids:
            metadata = self.parser.extract_session_metadata(path)
            session_id = str(metadata.get("session_id") or "").strip()
            if session_id in self.exclude_session_ids:
                log.info("Skipping %s: matched transcript exclude session id", path)
                return False
        if self.parser.format_name != "codex":
            return True
        if self.persona_root:
            metadata = self.parser.extract_session_metadata(path)
            cwd = self._normalize_path(metadata.get("cwd"))
            return cwd == self.persona_root
        if self.project_roots:
            metadata = self.parser.extract_session_metadata(path)
            cwd = self._normalize_path(metadata.get("cwd"))
            return self._cwd_under_any_root(cwd, self.project_roots)
        return True

    def _session_files(self) -> list[Path]:
        globber = self.jsonl_dir.rglob if self.recursive else self.jsonl_dir.glob
        # Parser-aware glob: Claude/Codex use *.jsonl, Hermes uses session_*.json.
        pattern = getattr(self.parser, "session_glob", "*.jsonl")
        return sorted(
            (path for path in globber(pattern) if self._should_index_file(path)),
            key=lambda p: p.stat().st_mtime,
        )

    def backfill(self, progress_callback: Callable[[int, int], None] | None = None):
        """Index all historical JSONL files. Skips unchanged files via import log.

        Args:
            progress_callback: Called with (files_processed, total_files)
        """
        jsonl_files = self._session_files()
        total = len(jsonl_files)

        if total == 0:
            log.info("No JSONL files found in %s", self.jsonl_dir)
            return

        log.info("Backfilling %d JSONL files from %s", total, self.jsonl_dir)

        with self.db.bulk_connection() as conn:
            # Disable FTS triggers for bulk performance
            self.db.disable_fts_triggers(conn)

            try:
                for i, path in enumerate(jsonl_files):
                    self._index_file(path, conn, is_backfill=True)
                    if progress_callback:
                        progress_callback(i + 1, total)
            finally:
                # Always rebuild FTS and re-create triggers, even if a file mid
                # batch raised. The trigger DROP above is committed by per-batch
                # commits, so skipping the rebuild on error would leave triggers
                # dropped and every later insert silently absent from FTS search.
                log.info("Rebuilding FTS index...")
                self.db.rebuild_fts(conn)

        log.info("Backfill complete: %d files processed", total)

    def mark_existing_files_seen(self) -> int:
        """Record current JSONL offsets without importing historical content.

        This is used when a user opts out of importing past conversations during
        setup. The watcher can still tail new bytes appended after startup.
        """
        jsonl_files = self._session_files()
        if not jsonl_files:
            log.info("No JSONL files found in %s", self.jsonl_dir)
            return 0

        with self.db.connection() as conn:
            for path in jsonl_files:
                file_path_str = str(path.resolve())
                file_hash = get_file_hash(path)
                file_size = path.stat().st_size
                self.db.execute_with_retry(
                    conn,
                    """INSERT INTO import_log (file_path, file_hash, file_size, last_position, entries_imported, updated_at)
                       VALUES (?, ?, ?, ?, 0, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                       ON CONFLICT(file_path) DO UPDATE SET
                           file_hash = excluded.file_hash,
                           file_size = excluded.file_size,
                           last_position = excluded.last_position,
                           updated_at = excluded.updated_at""",
                    (file_path_str, file_hash, file_size, file_size),
                )
            conn.commit()

        log.info("Marked %d JSONL files as seen without historical import", len(jsonl_files))
        return len(jsonl_files)

    def index_file(self, path: Path):
        """Index a single JSONL file (for real-time use, with FTS triggers active)."""
        with self.db.connection() as conn:
            self._index_file(path, conn, is_backfill=False)
            conn.commit()

    def _parser_for_file(self, path: Path):
        """Pick the parser for a single file, preferring its content signature.

        Codex and Claude both use .jsonl, so a coarse client label can be wrong
        (e.g. a Codex sessions dir indexed with the Claude default). Content is
        authoritative over the label: a Codex rollout parsed as Claude yields
        zero entries and silently advances import_log, permanently dropping that
        session. Sniffing is bounded (a few lines) and only overrides when the
        file's format is unambiguous and differs from the active parser.
        """
        # Content sniffing only disambiguates the two .jsonl formats (Claude vs
        # Codex). Whole-file formats like Hermes session_*.json keep the active
        # parser selected by client/session-dir.
        if path.suffix.lower() != ".jsonl":
            return self.parser
        try:
            from .harness import sniff_jsonl_format

            fmt = sniff_jsonl_format(path)
        except Exception:  # pragma: no cover - sniff must never break indexing
            fmt = None
        if fmt and fmt != self.parser.format_name:
            from .parser import get_parser

            log.info(
                "Parsing %s as %s by content signature (active parser is %s)",
                path.name,
                fmt,
                self.parser.format_name,
            )
            return get_parser(fmt)
        return self.parser

    def _index_file(self, path: Path, conn, is_backfill: bool = False):
        """Core file indexing logic with import log check."""
        if not self._should_index_file(path):
            log.debug("Skipping %s: session cwd does not match persona root", path)
            return

        parser = self._parser_for_file(path)

        file_path_str = str(path.resolve())
        file_hash = get_file_hash(path)
        file_size = path.stat().st_size

        # Check import log
        row = conn.execute(
            "SELECT file_hash, last_position FROM import_log WHERE file_path = ?",
            (file_path_str,),
        ).fetchone()

        if row:
            if row["file_hash"] == file_hash:
                # File unchanged, skip
                return
            # File changed (grew). Read from last position for tail-read,
            # or from 0 for backfill (full re-parse).
            start_offset = 0 if is_backfill else (row["last_position"] or 0)
        else:
            start_offset = 0

        # Extract session metadata
        session_meta = parser.extract_session_metadata(path)
        session_meta["persona"] = self.persona
        self.db.upsert_session(session_meta, conn)

        # Parse entries
        entries = []
        final_pos = start_offset
        entries_seen = 0
        parser_iter = parser.parse_file(path, start_offset=start_offset)
        while True:
            try:
                entry = next(parser_iter)
            except StopIteration as exc:
                final_pos = exc.value if isinstance(exc.value, int) else file_size
                break

            # Sanitize content before indexing
            if entry.get("content"):
                entry["content"] = sanitize_content(entry["content"])

            # Add persona
            entry["persona"] = self.persona

            entries.append(entry)
            entries_seen += 1

            # Batch insert
            if len(entries) >= BATCH_SIZE:
                self.db.insert_entries(entries, conn)
                conn.commit()
                entries = []

        # Insert remaining
        if entries:
            self.db.insert_entries(entries, conn)
            conn.commit()

        # Update import log
        self.db.execute_with_retry(
            conn,
            """INSERT INTO import_log (file_path, file_hash, file_size, last_position, entries_imported, updated_at)
               VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               ON CONFLICT(file_path) DO UPDATE SET
                   file_hash = excluded.file_hash,
                   file_size = excluded.file_size,
                   last_position = excluded.last_position,
                   entries_imported = import_log.entries_imported + excluded.entries_imported,
                   updated_at = excluded.updated_at""",
            (file_path_str, file_hash, file_size, final_pos, entries_seen),
        )
        conn.commit()

        log.info("Indexed %s: %d entries (offset %d -> %d)", path.name, entries_seen, start_offset, final_pos)

    def _watch_matches(self, path: Path) -> bool:
        pattern = getattr(self.parser, "session_glob", "*.jsonl")
        return fnmatch.fnmatch(path.name.lower(), pattern.lower())

    def tail_file(self, path: Path):
        """Tail-read new content from an active session file."""
        # Whole-file formats (e.g. Hermes session_*.json) are rewritten in place,
        # so the size may not grow; route them through hash-based reindexing.
        if path.suffix.lower() != ".jsonl":
            self.index_file(path)
            return

        file_path_str = str(path.resolve())

        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT last_position FROM import_log WHERE file_path = ?",
                (file_path_str,),
            ).fetchone()

        current_size = path.stat().st_size
        last_pos = row["last_position"] if row else 0

        if current_size <= last_pos:
            return  # No new data

        with self.db.connection() as conn:
            self._index_file(path, conn, is_backfill=False)

    def start_watching(self, poll_interval: float = 30.0):
        """Start file watching with watchdog + periodic poll safety net."""
        self._stop_event.clear()

        # A prior backfill that was hard-killed (SIGKILL/power loss) can leave the
        # FTS triggers dropped; restore them before we start tailing so new rows
        # are searchable. Cheap no-op when healthy.
        try:
            with self.db.connection() as conn:
                if self.db.ensure_fts_triggers(conn):
                    conn.commit()
                    log.warning("FTS triggers were missing (interrupted import?); rebuilt FTS index")
        except Exception:
            log.exception("FTS trigger consistency check failed")

        # Try watchdog first
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class _Handler(FileSystemEventHandler):
                def __init__(self, indexer):
                    self.indexer = indexer

                def on_modified(self, event):
                    if event.is_directory:
                        return
                    path = Path(event.src_path)
                    if self.indexer._watch_matches(path):
                        try:
                            self.indexer.tail_file(path)
                        except Exception:
                            log.exception("Error tailing %s", path)

                def on_created(self, event):
                    if event.is_directory:
                        return
                    path = Path(event.src_path)
                    if self.indexer._watch_matches(path):
                        try:
                            self.indexer.index_file(path)
                        except Exception:
                            log.exception("Error indexing new file %s", path)

            observer = Observer()
            observer.schedule(_Handler(self), str(self.jsonl_dir), recursive=self.recursive)
            observer.start()
            log.info("Watchdog file watcher started on %s", self.jsonl_dir)

        except ImportError:
            log.warning("watchdog not installed, using poll-only mode")
            observer = None

        # Periodic poll safety net (catches anything watchdog missed)
        def _poll_loop():
            while not self._stop_event.is_set():
                self._stop_event.wait(poll_interval)
                if self._stop_event.is_set():
                    break
                try:
                    self._poll_for_changes()
                except Exception:
                    log.exception("Error in poll loop")

        self._poll_thread = threading.Thread(target=_poll_loop, daemon=True, name="transcript-poll")
        self._poll_thread.start()

        return observer

    def stop_watching(self):
        """Stop the file watcher and poll thread."""
        self._stop_event.set()

    def _poll_for_changes(self):
        """Check all JSONL files for changes not caught by watchdog."""
        for path in self._session_files():
            file_path_str = str(path.resolve())
            current_size = path.stat().st_size

            with self.db.connection() as conn:
                row = conn.execute(
                    "SELECT file_size FROM import_log WHERE file_path = ?",
                    (file_path_str,),
                ).fetchone()

            last_size = row["file_size"] if row else 0
            if current_size > last_size:
                self.tail_file(path)


def _parse_single_entry(obj: dict, session_id: str, timestamp: str):
    """Parse a single JSONL object into transcript entries (for tail-read use)."""
    # Import here to avoid circular dependency
    from .parser import _parse_user_entry, _parse_assistant_entry, _parse_system_entry, _parse_queue_operation, _make_entry

    obj_type = obj.get("type", "")

    if obj_type == "user":
        yield from _parse_user_entry(obj, session_id, timestamp)
    elif obj_type == "assistant":
        yield from _parse_assistant_entry(obj, session_id, timestamp)
    elif obj_type == "system":
        yield from _parse_system_entry(obj, session_id, timestamp)
    elif obj_type == "queue-operation":
        yield from _parse_queue_operation(obj, session_id, timestamp)
    elif obj_type == "attachment":
        yield _make_entry(
            session_id=session_id,
            entry_type="attachment",
            timestamp=timestamp,
            content=json.dumps(obj.get("attachment", {})),
            source="cli",
            metadata={"uuid": obj.get("uuid")},
        )
