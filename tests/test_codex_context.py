import io
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import chimera_memory.cli as cli_module
import chimera_memory.codex_runtime as codex_runtime
from chimera_memory.cli import _codex_executable_for_subprocess, main
from chimera_memory.codex_context import (
    CODEX_MEMORY_CONTEXT_MARKER,
    CODEX_MEMORY_GROUNDING_RULE,
    build_codex_prompt_context,
)
from chimera_memory.db import TranscriptDB
from chimera_memory.memory import index_file, init_memory_tables, memory_audit_query, memory_recall_trace_query
from chimera_memory.transcript_context import format_transcript_context_block, project_transcript_context


def _write_memory(path: Path, frontmatter: list[str], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(["---", *frontmatter, "---", body]), encoding="utf-8")


def _seed_codex_context_db(db_path: Path, tmp_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
        project = tmp_path / "project.md"
        private = tmp_path / "private.md"
        weak = tmp_path / "weak.md"
        _write_memory(
            project,
            [
                "type: procedural",
                "importance: 8",
                "memory_scope: project",
                "project_id: Chimera-Memory",
                "about: Codex Desktop automatic injection supervisor project setup",
            ],
            "Project memory says Codex Desktop automatic injection needs a hook or wrapper.",
        )
        _write_memory(
            private,
            ["type: procedural", "importance: 10", "about: private Codex Desktop automatic injection supervisor"],
            "Persona-private Codex Desktop automatic injection details must not appear in project mode.",
        )
        _write_memory(
            weak,
            ["type: semantic", "importance: 10", "about: broad shared memory context"],
            "Shared context mentions stopping working without durable setup details.",
        )
        assert index_file(conn, "project:Chimera-Memory", "memory/project-context.md", project)
        assert index_file(conn, "asa", "memory/private-context.md", private)
        assert index_file(conn, "shared", "global/weak.md", weak)
        conn.commit()
    finally:
        conn.close()


def _seed_transcript_context_db(db_path: Path, tmp_path: Path) -> dict[str, Path]:
    db = TranscriptDB(db_path)
    repo = tmp_path / "repo"
    other_repo = tmp_path / "repo-other"
    repo.mkdir()
    other_repo.mkdir()
    db.upsert_session(
        {
            "session_id": "project-session",
            "title": "Project Thread",
            "cwd": str(repo),
            "started_at": "2026-06-10T10:00:00Z",
            "ended_at": "2026-06-10T10:05:00Z",
            "exchange_count": 2,
        }
    )
    db.upsert_session(
        {
            "session_id": "other-session",
            "title": "Other Thread",
            "cwd": str(other_repo),
            "started_at": "2026-06-10T10:00:00Z",
            "ended_at": "2026-06-10T10:05:00Z",
            "exchange_count": 1,
        }
    )
    db.insert_entries(
        [
            {
                "session_id": "project-session",
                "entry_type": "assistant_message",
                "timestamp": "2026-06-10T10:01:00Z",
                "content": "Codex transcript fallback says memory-aware exec uses stdin context.",
                "source": "cli",
                "author": "assistant",
            },
            {
                "session_id": "other-session",
                "entry_type": "assistant_message",
                "timestamp": "2026-06-10T10:02:00Z",
                "content": "Codex transcript fallback says unrelated neighboring repo secret.",
                "source": "cli",
                "author": "assistant",
            },
        ]
    )
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
    finally:
        conn.close()
    return {"repo": repo, "other_repo": other_repo, "memory_root": repo / ".chimera-memory"}


def test_codex_exec_windows_subprocess_prefers_launchable_shim(monkeypatch) -> None:
    def fake_which(command: str) -> str | None:
        return "C:/Users/test/AppData/Roaming/npm/codex.cmd" if command == "codex.cmd" else None

    monkeypatch.setattr(codex_runtime.os, "name", "nt", raising=False)
    monkeypatch.setattr(codex_runtime.shutil, "which", fake_which)

    assert _codex_executable_for_subprocess("codex") == "codex.cmd"
    assert _codex_executable_for_subprocess("codex-test") == "codex-test"
    assert _codex_executable_for_subprocess("C:\\Tools\\codex") == "C:\\Tools\\codex"


def test_codex_prompt_context_prepends_project_memory_and_excludes_private(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        result = build_codex_prompt_context(
            conn,
            prompt="Need Codex Desktop automatic injection supervisor setup.",
            project_id="Chimera-Memory",
        )
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["injected"] is True
    assert result["returned_count"] == 1
    assert CODEX_MEMORY_CONTEXT_MARKER in result["prompt"]
    assert "memory/project-context.md" in result["prompt"]
    assert "memory/private-context.md" not in result["prompt"]
    assert "global/weak.md" not in result["prompt"]
    assert result["prompt"].endswith("Need Codex Desktop automatic injection supervisor setup.")


def test_codex_prompt_context_leaves_prompt_unchanged_on_miss(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        result = build_codex_prompt_context(
            conn,
            prompt="Need unrelated quantum umbrella details.",
            project_id="Chimera-Memory",
        )
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["injected"] is False
    assert result["prompt"] == "Need unrelated quantum umbrella details."
    assert result["context_block"] == ""


def test_codex_prompt_context_rejects_all_scope(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = build_codex_prompt_context(
        conn,
        prompt="Need Codex memory.",
        scope="all",
    )

    assert result["ok"] is False
    assert "scope must be auto, project, or global" in result["error"]


def test_codex_prompt_context_requires_project_for_auto_scope(monkeypatch) -> None:
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = build_codex_prompt_context(
        conn,
        prompt="Need Codex memory.",
    )

    assert result["ok"] is False
    assert "project_id or CHIMERA_MEMORY_PROJECT_ID is required" in result["error"]


def test_codex_prompt_context_uses_project_id_env(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "Chimera-Memory")
    conn = sqlite3.connect(db_path)
    try:
        result = build_codex_prompt_context(
            conn,
            prompt="Need Codex Desktop automatic injection supervisor setup.",
        )
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["injected"] is True
    assert result["project_id"] == "Chimera-Memory"
    assert "memory/project-context.md" in result["prompt"]


def test_codex_prompt_context_replaces_existing_prefix(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    original_prompt = "Need Codex Desktop automatic injection supervisor setup."
    already_prefixed = (
        f"{CODEX_MEMORY_CONTEXT_MARKER}\n"
        "<chimera-memory-context trace_id=\"stale\">stale context</chimera-memory-context>\n\n"
        f"{CODEX_MEMORY_GROUNDING_RULE}\n\n"
        f"{original_prompt}"
    )
    conn = sqlite3.connect(db_path)
    try:
        result = build_codex_prompt_context(
            conn,
            prompt=already_prefixed,
            project_id="Chimera-Memory",
        )
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["injected"] is True
    assert result["prompt"].count(CODEX_MEMORY_CONTEXT_MARKER) == 1
    assert "stale context" not in result["prompt"]
    assert result["prompt"].endswith(original_prompt)


def test_codex_prompt_context_strips_leading_bom_prefixes(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        real_bom = build_codex_prompt_context(
            conn,
            prompt="\ufeffNeed Codex Desktop automatic injection supervisor setup.",
            project_id="Chimera-Memory",
        )
        mojibake_bom = build_codex_prompt_context(
            conn,
            prompt="\u00ef\u00bb\u00bfNeed Codex Desktop automatic injection supervisor setup.",
            project_id="Chimera-Memory",
        )
    finally:
        conn.close()

    assert real_bom["ok"] is True
    assert mojibake_bom["ok"] is True
    assert "\ufeff" not in real_bom["prompt"]
    assert "\u00ef\u00bb\u00bf" not in mojibake_bom["prompt"]
    assert real_bom["prompt"].endswith("Need Codex Desktop automatic injection supervisor setup.")
    assert mojibake_bom["prompt"].endswith("Need Codex Desktop automatic injection supervisor setup.")


def test_codex_prompt_context_can_include_project_scoped_transcript_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "memory.db"
    paths = _seed_transcript_context_db(db_path, tmp_path)
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "Chimera-Memory")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(paths["memory_root"]))
    conn = sqlite3.connect(db_path)
    try:
        result = build_codex_prompt_context(
            conn,
            prompt="Need Codex transcript fallback memory-aware exec stdin context.",
            project_id="Chimera-Memory",
            include_transcripts=True,
            transcript_limit=3,
        )
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["injected"] is True
    assert result["returned_count"] == 0
    assert result["transcript_returned_count"] == 1
    assert "<chimera-transcript-context" in result["prompt"]
    assert "memory-aware exec uses stdin context" in result["prompt"]
    assert "neighboring repo secret" not in result["prompt"]
    assert str(paths["repo"]) not in result["prompt"]
    assert result["transcript_trace_id"]
    assert result["transcript_event_id"]

    trace_conn = sqlite3.connect(db_path)
    try:
        traces = memory_recall_trace_query(trace_conn, tool_name="codex_transcript_context", include_items=True)
        assert traces[0]["trace_id"] == result["transcript_trace_id"]
        assert traces[0]["returned_count"] == 1
        assert traces[0]["response_policy"]["source_policy"] == "session_cwd_under_project_root"
        assert traces[0]["response_policy"]["raw_paths_in_trace"] is False
        assert traces[0]["items"][0]["relative_path"] == "transcript/project-session"
        assert traces[0]["items"][0]["path"] == ""
        assert "Codex transcript fallback says memory-aware exec uses stdin context" not in json.dumps(traces[0])

        events = memory_audit_query(trace_conn, event_type="codex_transcript_context_returned")
        assert events[0]["trace_id"] == result["transcript_trace_id"]
        assert events[0]["actor"] == "codex-context"
    finally:
        trace_conn.close()


def test_project_transcript_context_preserves_connection_row_factory(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    paths = _seed_transcript_context_db(db_path, tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.row_factory is None
        result = project_transcript_context(
            conn,
            query="memory-aware exec stdin context",
            project_root=str(paths["repo"]),
            actor="test",
        )
        assert result["returned_count"] == 1
        assert result["trace_id"]
        assert conn.row_factory is None
    finally:
        conn.close()


def test_project_transcript_context_limit_zero_returns_no_snippets_and_traces(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    paths = _seed_transcript_context_db(db_path, tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        result = project_transcript_context(
            conn,
            query="memory-aware exec stdin context",
            project_root=str(paths["repo"]),
            limit=0,
            actor="test",
        )
        assert result["reason"] == "limit_zero"
        assert result["returned_count"] == 0
        assert result["snippets"] == []
        traces = memory_recall_trace_query(conn, tool_name="codex_transcript_context")
        assert traces[0]["trace_id"] == result["trace_id"]
        assert traces[0]["returned_count"] == 0
        events = memory_audit_query(conn, event_type="codex_transcript_context_skipped")
        assert events[0]["trace_id"] == result["trace_id"]
    finally:
        conn.close()


def test_format_transcript_context_block_counts_included_snippets() -> None:
    result = {
        "snippets": [
            {
                "timestamp": "2026-06-10T10:00:00Z",
                "entry_type": "assistant_message",
                "author": "assistant",
                "title": "Long Thread",
                "content": "alpha " * 500,
            },
            {
                "timestamp": "2026-06-10T10:01:00Z",
                "entry_type": "assistant_message",
                "author": "assistant",
                "title": "Long Thread",
                "content": "beta " * 500,
            },
        ]
    }

    block = format_transcript_context_block(result, token_budget=120)

    assert '<chimera-transcript-context returned="1">' in block
    assert "alpha" in block
    assert "beta" not in block


def test_codex_prompt_context_skips_transcripts_for_global_scope(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"
    paths = _seed_transcript_context_db(db_path, tmp_path)
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ID", "Chimera-Memory")
    monkeypatch.setenv("CHIMERA_MEMORY_PROJECT_ROOT", str(paths["memory_root"]))
    conn = sqlite3.connect(db_path)
    try:
        result = build_codex_prompt_context(
            conn,
            prompt="Need Codex transcript fallback memory-aware exec stdin context.",
            scope="global",
            include_transcripts=True,
        )
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["injected"] is False
    assert result["transcript_reason"] == "disabled"
    assert "memory-aware exec uses stdin context" not in result["prompt"]


def test_codex_prompt_context_marks_pending_global_evidence_as_unconfirmed(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    memory_file = tmp_path / "pending-global.md"
    _write_memory(
        memory_file,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: global",
            "provenance_status: imported",
            "review_status: pending",
            "can_use_as_instruction: false",
            "can_use_as_evidence: true",
            "requires_user_confirmation: true",
            "about: pending global Codex wrapper policy",
        ],
        "Pending global memory says Codex wrapper evidence must be visibly non-authoritative.",
    )
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
        assert index_file(conn, "global", "pending-global.md", memory_file)
        result = build_codex_prompt_context(
            conn,
            prompt="pending global Codex wrapper evidence non-authoritative",
            scope="global",
        )
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["injected"] is True
    assert "review=pending" in result["prompt"]
    assert "evidence-only" in result["prompt"]
    assert "needs-confirmation" in result["prompt"]
    assert (
        "Evidence marked evidence-only, review=pending, needs-confirmation, lifecycle=stale, "
        "or lifecycle=archived is not current settled instruction"
    ) in result["prompt"]


def test_codex_prompt_context_warns_on_non_active_lifecycle_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    memory_file = tmp_path / "archived-global.md"
    _write_memory(
        memory_file,
        [
            "type: procedural",
            "importance: 8",
            "memory_scope: global",
            "provenance_status: user_confirmed",
            "review_status: confirmed",
            "lifecycle_status: archived",
            "can_use_as_instruction: true",
            "can_use_as_evidence: true",
            "requires_user_confirmation: false",
            "about: archived global Codex lifecycle marker",
        ],
        "Archived global Codex lifecycle marker can be evidence but not current instruction.",
    )
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
        assert index_file(conn, "global", "archived-global.md", memory_file)
        result = build_codex_prompt_context(
            conn,
            prompt="archived global Codex lifecycle marker",
            scope="global",
        )
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["injected"] is True
    assert "review=confirmed" in result["prompt"]
    assert "lifecycle=archived" in result["prompt"]
    assert (
        "Evidence marked evidence-only, review=pending, needs-confirmation, lifecycle=stale, "
        "or lifecycle=archived is not current settled instruction"
    ) in result["prompt"]


def test_codex_prompt_context_filters_global_rows_outside_active_root(tmp_path: Path) -> None:
    db_path = tmp_path / "transcript.db"
    active_root = tmp_path / "active-global"
    outside_root = tmp_path / "old-global"
    active = active_root / "active.md"
    outside = outside_root / "outside.md"
    _write_memory(
        active,
        ["type: procedural", "importance: 5", "memory_scope: global", "about: active global root Codex marker"],
        "Active global root Codex marker should be injected.",
    )
    _write_memory(
        outside,
        ["type: procedural", "importance: 10", "memory_scope: global", "about: outside global root Codex marker"],
        "Outside global root Codex marker must not be injected.",
    )
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
        assert index_file(conn, "global", "active.md", active)
        assert index_file(conn, "global", "outside.md", outside)

        result = build_codex_prompt_context(
            conn,
            prompt="global root Codex marker",
            scope="global",
            global_root=str(active_root),
            force=True,
        )
        traces = memory_recall_trace_query(conn, tool_name="memory_context_pack")
    finally:
        conn.close()

    assert result["ok"] is True
    assert result["injected"] is True
    assert result["returned_count"] == 1
    assert "Active global root Codex marker" in result["prompt"]
    assert "Outside global root Codex marker" not in result["prompt"]
    assert traces[0]["request_payload"]["global_root_filter_enabled"] is True
    assert str(active_root) not in json.dumps(traces)


def test_cli_codex_context_uses_default_global_root_filter(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    db_path = tmp_path / "transcript.db"
    default_global_root = tmp_path / ".chimera-memory" / "global-memory"
    outside_root = tmp_path / "old-global"
    active = default_global_root / "active.md"
    outside = outside_root / "outside.md"
    _write_memory(
        active,
        ["type: procedural", "importance: 5", "memory_scope: global", "about: default wrapper global root marker"],
        "Default wrapper global root marker should be injected.",
    )
    _write_memory(
        outside,
        ["type: procedural", "importance: 10", "memory_scope: global", "about: outside default wrapper root marker"],
        "Outside default wrapper root marker must not be injected.",
    )
    conn = sqlite3.connect(db_path)
    try:
        init_memory_tables(conn)
        assert index_file(conn, "global", "active.md", active)
        assert index_file(conn, "global", "outside.md", outside)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.delenv("CHIMERA_MEMORY_GLOBAL_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "context",
            "Need default wrapper global root marker evidence.",
            "--db",
            str(db_path),
            "--scope",
            "global",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "Default wrapper global root marker should be injected." in output
    assert "Outside default wrapper root marker" not in output
    conn = sqlite3.connect(db_path)
    try:
        traces = memory_recall_trace_query(conn, tool_name="memory_context_pack")
    finally:
        conn.close()
    assert traces[0]["request_payload"]["global_root_filter_enabled"] is True
    assert str(default_global_root) not in json.dumps(traces)


def test_cli_codex_context_outputs_prefixed_prompt(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "context",
            "Need Codex Desktop automatic injection supervisor setup.",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert CODEX_MEMORY_CONTEXT_MARKER in output
    assert "memory/project-context.md" in output
    assert output.rstrip().endswith("Need Codex Desktop automatic injection supervisor setup.")


def test_cli_codex_context_json_reads_stdin_without_db_path(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("Need Codex Desktop automatic injection supervisor setup."))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "context",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--json",
        ],
    )

    main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ok"] is True
    assert payload["injected"] is True
    assert payload["returned_count"] == 1
    assert str(db_path) not in output


def test_cli_codex_context_accepts_explicit_prompt_option(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "context",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt",
            "Need Codex Desktop automatic injection supervisor setup.",
            "--json",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["injected"] is True
    assert payload["prompt"].rstrip().endswith("Need Codex Desktop automatic injection supervisor setup.")


def test_cli_codex_context_receipt_only_omits_prompt_and_memory_body(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "context",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt",
            "Need Codex Desktop automatic injection supervisor setup.",
            "--receipt-only",
            "--json",
        ],
    )

    main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ok"] is True
    assert payload["injected"] is True
    assert payload["returned_count"] == 1
    assert payload["prompt_included"] is False
    assert payload["evidence_body_included"] is False
    assert "prompt" not in payload
    assert "Need Codex Desktop automatic injection supervisor setup" not in output
    assert "Project memory says Codex Desktop automatic injection" not in output
    assert CODEX_MEMORY_CONTEXT_MARKER not in output


def test_cli_codex_context_reads_prompt_file_over_positional_text(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(
        "Need Codex Desktop automatic injection supervisor setup.",
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "context",
            "ignored positional prompt",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt-file",
            str(prompt_file),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert CODEX_MEMORY_CONTEXT_MARKER in output
    assert "ignored positional prompt" not in output
    assert output.rstrip().endswith("Need Codex Desktop automatic injection supervisor setup.")


def test_cli_codex_context_reads_previous_context_file_for_shift_gate(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    prompt_file = tmp_path / "prompt.txt"
    previous_file = tmp_path / "previous.txt"
    prompt_file.write_text("Need Codex Desktop automatic injection supervisor setup.", encoding="utf-8")
    previous_file.write_text("Need Codex Desktop automatic injection supervisor setup.", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "context",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt-file",
            str(prompt_file),
            "--previous-context-file",
            str(previous_file),
            "--no-force",
            "--json",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["retrieved"] is False
    assert payload["injected"] is False
    assert payload["prompt"] == "Need Codex Desktop automatic injection supervisor setup."


def test_cli_codex_context_infers_project_id_from_current_repo(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = tmp_path / "Chimera-Memory"
    repo.mkdir()
    (repo / ".git").mkdir()
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "context",
            "--db",
            str(db_path),
            "--prompt",
            "Need Codex Desktop automatic injection supervisor setup.",
            "--json",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["project_id"] == "Chimera-Memory"
    assert payload["project_root"] == str(repo)
    assert payload["injected"] is True
    assert "memory/project-context.md" in payload["prompt"]


def test_cli_codex_context_block_only_can_print_transcript_context(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    db_path = tmp_path / "memory.db"
    paths = _seed_transcript_context_db(db_path, tmp_path)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Need Codex transcript fallback memory-aware exec stdin context.", encoding="utf-8")
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "context",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--project-root",
            str(paths["memory_root"]),
            "--prompt-file",
            str(prompt_file),
            "--include-transcripts",
            "--block-only",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "<chimera-transcript-context" in output
    assert "memory-aware exec uses stdin context" in output
    assert "neighboring repo secret" not in output
    assert CODEX_MEMORY_CONTEXT_MARKER not in output


def test_cli_codex_exec_dry_run_builds_stdin_command_receipt(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Need Codex Desktop automatic injection supervisor setup.", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "exec",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt-file",
            str(prompt_file),
            "--codex-bin",
            "codex-test",
            "--model",
            "gpt-test",
            "--cd",
            str(tmp_path),
            "--json-events",
            "--dry-run",
            "--json",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["delivery_mode"] == "exec_dry_run"
    assert payload["injected"] is True
    assert payload["transcript_returned_count"] == 0
    assert payload["transcript_reason"] == "disabled"
    assert payload["transcript_trace_id"] == ""
    assert payload["command_preview"] == [
        "codex-test",
        "exec",
        "--model",
        "gpt-test",
        "--cd",
        str(tmp_path),
        "--json",
        "-",
    ]
    assert CODEX_MEMORY_CONTEXT_MARKER in payload["prompt"]
    assert "Need Codex Desktop automatic injection supervisor setup." not in payload["command_preview"]
    conn = sqlite3.connect(db_path)
    try:
        traces = memory_recall_trace_query(conn, tool_name="memory_context_pack")
        assert traces[0]["response_policy"]["delivery_mode"] == "exec_dry_run"
        assert memory_audit_query(conn, event_type="codex_prompt_delivered") == []
    finally:
        conn.close()


def test_cli_codex_exec_dry_run_infers_project_id_from_cd(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = tmp_path / "Chimera-Memory"
    repo.mkdir()
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("CHIMERA_MEMORY_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "exec",
            "--db",
            str(db_path),
            "--prompt",
            "Need Codex Desktop automatic injection supervisor setup.",
            "--codex-bin",
            "codex-test",
            "--cd",
            str(repo),
            "--dry-run",
            "--json",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["project_id"] == "Chimera-Memory"
    assert payload["injected"] is True
    assert payload["command_preview"] == ["codex-test", "exec", "--cd", str(repo), "-"]


def test_cli_codex_exec_accepts_explicit_prompt_option(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "exec",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt",
            "Need Codex Desktop automatic injection supervisor setup.",
            "--codex-bin",
            "codex-test",
            "--dry-run",
            "--json",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["command_preview"] == ["codex-test", "exec", "-"]
    assert payload["prompt"].rstrip().endswith("Need Codex Desktop automatic injection supervisor setup.")


def test_cli_codex_exec_dry_run_receipt_only_omits_prompt_and_memory_body(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "exec",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt",
            "Need Codex Desktop automatic injection supervisor setup.",
            "--codex-bin",
            "codex-test",
            "--dry-run",
            "--receipt-only",
            "--json",
        ],
    )

    main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["command_preview"] == ["codex-test", "exec", "-"]
    assert payload["prompt_included"] is False
    assert payload["evidence_body_included"] is False
    assert payload["delivery_proof"] == {
        "schema_version": "chimera-memory.codex-exec-delivery-proof.v1",
        "prompt_constructed": True,
        "prompt_injected": True,
        "delivery_mode": "exec_dry_run",
        "transport": "stdin",
        "dry_run": True,
        "subprocess_attempted": False,
        "subprocess_started": False,
        "subprocess_stdin_delivered": False,
        "delivery_failed": False,
        "delivery_event_count": 0,
        "delivery_event_recorded_count": 0,
        "delivery_failure_event_recorded_count": 0,
        "real_delivery_recorded": False,
        "returncode": None,
        "raw_prompt_included": False,
        "raw_output_included": False,
    }
    assert "prompt" not in payload
    assert "Need Codex Desktop automatic injection supervisor setup" not in output
    assert "Project memory says Codex Desktop automatic injection" not in output
    assert CODEX_MEMORY_CONTEXT_MARKER not in output


def test_cli_codex_exec_receipt_includes_transcript_trace_id(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    db_path = tmp_path / "memory.db"
    paths = _seed_transcript_context_db(db_path, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "exec",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--project-root",
            str(paths["memory_root"]),
            "--prompt",
            "Need Codex transcript fallback memory-aware exec stdin context.",
            "--include-transcripts",
            "--codex-bin",
            "codex-test",
            "--dry-run",
            "--json",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["transcript_returned_count"] == 1
    assert payload["transcript_trace_id"]
    assert payload["transcript_event_id"]


def test_cli_codex_exec_runs_codex_with_wrapped_prompt_on_stdin(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Need Codex Desktop automatic injection supervisor setup.", encoding="utf-8")
    calls = []

    def fake_run(command, *, input, text, cwd, capture_output):
        calls.append(
            {
                "command": command,
                "input": input,
                "text": text,
                "cwd": cwd,
                "capture_output": capture_output,
            }
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="codex ok\n",
            stderr="raw stderr C:/Users/test/.codex/auth.json TEST_ONLY_SECRET",
        )

    monkeypatch.setattr("chimera_memory.cli.subprocess.run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "exec",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt-file",
            str(prompt_file),
            "--codex-bin",
            "codex-test",
            "--skip-git-repo-check",
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 0
    assert len(calls) == 1
    assert calls[0]["command"] == ["codex-test", "exec", "--skip-git-repo-check", "-"]
    assert calls[0]["text"] is True
    assert calls[0]["capture_output"] is True
    assert calls[0]["cwd"] is None
    assert CODEX_MEMORY_CONTEXT_MARKER in calls[0]["input"]
    assert calls[0]["input"].endswith("Need Codex Desktop automatic injection supervisor setup.")
    payload = json.loads(capsys.readouterr().out)
    assert payload["returncode"] == 0
    assert payload["delivery_mode"] == "exec"
    assert len(payload["delivery_events"]) == 1
    assert payload["delivery_events"][0]["delivery_mode"] == "exec"
    assert payload["delivery_proof"] == {
        "schema_version": "chimera-memory.codex-exec-delivery-proof.v1",
        "prompt_constructed": True,
        "prompt_injected": True,
        "delivery_mode": "exec",
        "transport": "stdin",
        "dry_run": False,
        "subprocess_attempted": True,
        "subprocess_started": True,
        "subprocess_stdin_delivered": True,
        "delivery_failed": False,
        "delivery_event_count": 1,
        "delivery_event_recorded_count": 1,
        "delivery_failure_event_recorded_count": 0,
        "real_delivery_recorded": True,
        "returncode": 0,
        "raw_prompt_included": False,
        "raw_output_included": False,
    }
    assert "stdout" not in payload
    assert "stderr" not in payload
    assert payload["output"] == {
        "raw_output_included": False,
        "stderr": {"char_count": 58, "line_count": 1, "present": True},
        "stdout": {"char_count": 9, "line_count": 1, "present": True},
    }
    assert "TEST_ONLY_SECRET" not in json.dumps(payload)
    assert ".codex/auth.json" not in json.dumps(payload)
    conn = sqlite3.connect(db_path)
    try:
        events = memory_audit_query(conn, event_type="codex_prompt_delivered")
        assert len(events) == 1
        assert events[0]["actor"] == "codex-context"
        assert events[0]["payload"]["delivery_mode"] == "exec"
        assert events[0]["payload"]["transport"] == "stdin"
        assert events[0]["payload"]["raw_prompt_in_payload"] is False
        assert "Need Codex Desktop" not in json.dumps(events[0])
        traces = memory_recall_trace_query(conn, tool_name="memory_context_pack")
        assert traces[0]["response_policy"]["delivery_mode"] == "exec"
    finally:
        conn.close()


def test_cli_codex_exec_launch_failure_records_sanitized_failed_delivery(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("raw launch failure C:/Users/test/.codex/auth.json TEST_ONLY_SECRET")

    monkeypatch.setattr("chimera_memory.cli.subprocess.run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "exec",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt",
            "Need Codex Desktop automatic injection supervisor setup.",
            "--codex-bin",
            "missing-codex-test",
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 127
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["error"] == "codex exec launch failed"
    assert payload["exception"] == "FileNotFoundError"
    assert payload["returncode"] == 127
    assert payload["delivery_events"][0]["delivery_failed"] is True
    assert payload["delivery_proof"] == {
        "schema_version": "chimera-memory.codex-exec-delivery-proof.v1",
        "prompt_constructed": True,
        "prompt_injected": True,
        "delivery_mode": "exec",
        "transport": "stdin",
        "dry_run": False,
        "subprocess_attempted": True,
        "subprocess_started": False,
        "subprocess_stdin_delivered": False,
        "delivery_failed": True,
        "delivery_event_count": 1,
        "delivery_event_recorded_count": 1,
        "delivery_failure_event_recorded_count": 1,
        "real_delivery_recorded": False,
        "returncode": 127,
        "raw_prompt_included": False,
        "raw_output_included": False,
    }
    assert payload["output"] == {
        "raw_output_included": False,
        "stderr": {"char_count": 0, "line_count": 0, "present": False},
        "stdout": {"char_count": 0, "line_count": 0, "present": False},
    }
    assert "TEST_ONLY_SECRET" not in output
    assert ".codex/auth.json" not in output
    assert "raw launch failure" not in output
    conn = sqlite3.connect(db_path)
    try:
        events = memory_audit_query(conn, event_type="codex_prompt_delivery_failed")
        assert len(events) == 1
        assert events[0]["actor"] == "codex-context"
        assert events[0]["payload"]["delivery_mode"] == "exec"
        assert events[0]["payload"]["exception"] == "FileNotFoundError"
        assert events[0]["payload"]["raw_prompt_in_payload"] is False
        assert events[0]["payload"]["raw_command_in_payload"] is False
        assert events[0]["payload"]["raw_output_in_payload"] is False
        assert "TEST_ONLY_SECRET" not in json.dumps(events[0])
        traces = memory_recall_trace_query(conn, tool_name="memory_context_pack")
        assert traces[0]["response_policy"]["delivery_mode"] == "exec"
    finally:
        conn.close()


def test_cli_codex_exec_can_include_raw_output_when_explicitly_requested(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    db_path = tmp_path / "memory.db"
    _seed_codex_context_db(db_path, tmp_path)

    def fake_run(command, *, input, text, cwd, capture_output):
        return subprocess.CompletedProcess(command, 0, stdout="codex ok\n", stderr="codex warning\n")

    monkeypatch.setattr("chimera_memory.cli.subprocess.run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chimera-memory",
            "codex",
            "exec",
            "--db",
            str(db_path),
            "--project-id",
            "Chimera-Memory",
            "--prompt",
            "Need Codex Desktop automatic injection supervisor setup.",
            "--codex-bin",
            "codex-test",
            "--json",
            "--include-output",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stdout"] == "codex ok\n"
    assert payload["stderr"] == "codex warning\n"
    assert payload["output"]["raw_output_included"] is True


def test_read_cli_text_arg_shares_stdin_across_reads(monkeypatch) -> None:
    # cli-09: two CLI text args pointing at '-' must both see stdin content,
    # not '' on the second read after the stream drains.
    cli_module._read_stdin_once.cache_clear()
    monkeypatch.setattr(sys, "stdin", io.StringIO("piped prompt text"))

    first = cli_module._read_cli_text_arg(file_path="-", inline_text="", default_stdin=True)
    second = cli_module._read_cli_text_arg(file_path="-", inline_text="", default_stdin=False)

    assert first == "piped prompt text"
    assert second == "piped prompt text"
    cli_module._read_stdin_once.cache_clear()


def test_embed_rejects_negative_limit(monkeypatch) -> None:
    # cli-08: a negative --limit must error at parse time, not silently clamp to
    # 0 and print a misleading "already have embeddings" success line.
    monkeypatch.setattr(sys, "argv", ["chimera-memory", "embed", "--limit", "-1"])

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 2
