import sqlite3
from pathlib import Path

from chimera_memory.memory import index_file, init_memory_tables, memory_audit_query, memory_recall_trace_query
from chimera_memory.memory_context_pack import memory_context_pack, strip_memory_context


def _write_memory(path: Path, frontmatter: list[str], body: str) -> None:
    path.write_text(
        "\n".join(["---", *frontmatter, "---", body]),
        encoding="utf-8",
    )


def test_context_pack_skips_without_topic_shift_and_audits() -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    result = memory_context_pack(
        conn,
        current_context="memory broker context pack",
        previous_context="memory broker context pack",
        persona="asa",
    )

    assert result["ok"] is True
    assert result["retrieved"] is False
    assert result["reason"] == "no_topic_shift"
    assert result["context_block"] == ""
    assert memory_recall_trace_query(conn, tool_name="memory_context_pack") == []
    events = memory_audit_query(conn, event_type="memory_context_pack_skipped", persona="asa")
    assert len(events) == 1


def test_context_pack_returns_fenced_scoped_cards_and_trace(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    normal = tmp_path / "broker.md"
    restricted = tmp_path / "restricted.md"
    other = tmp_path / "other.md"
    synthesis = tmp_path / "synthesis.md"
    _write_memory(
        normal,
        ["type: procedural", "importance: 9", "about: Hermes-style memory broker"],
        "Hermes context broker retrieves bounded memory cards before each turn.",
    )
    _write_memory(
        restricted,
        [
            "type: semantic",
            "importance: 10",
            "sensitivity_tier: restricted",
            "about: restricted broker note",
        ],
        "Restricted Hermes context broker note should not auto-inject.",
    )
    _write_memory(
        other,
        ["type: procedural", "importance: 9", "about: Sarah broker note"],
        "Sarah-only Hermes context broker note should stay outside Asa scope.",
    )
    _write_memory(
        synthesis,
        [
            "type: semantic",
            "importance: 9",
            "exclude_from_default_search: true",
            "about: generated broker synthesis",
        ],
        "Generated synthesis about Hermes context broker should be excluded by default.",
    )
    assert index_file(conn, "asa", "memory/broker.md", normal)
    assert index_file(conn, "asa", "memory/restricted.md", restricted)
    assert index_file(conn, "sarah", "memory/other.md", other)
    assert index_file(conn, "asa", "memory/synthesis.md", synthesis)

    result = memory_context_pack(
        conn,
        current_context="Need Hermes context broker automatic memory cards now.",
        previous_context="Earlier topic was oauth setup.",
        persona="asa",
        limit=5,
        force=True,
    )

    assert result["ok"] is True
    assert result["retrieved"] is True
    assert result["returned_count"] == 1
    assert result["cards"][0]["relative_path"] == "memory/broker.md"
    assert "<chimera-memory-context" in result["context_block"]
    assert "Recalled ChimeraMemory context" in result["context_block"]
    assert "Restricted" not in result["context_block"]
    assert "Sarah-only" not in result["context_block"]
    assert "Generated synthesis" not in result["context_block"]

    traces = memory_recall_trace_query(conn, tool_name="memory_context_pack", include_items=True)
    assert len(traces) == 1
    assert traces[0]["trace_id"] == result["trace_id"]
    assert traces[0]["items"][0]["relative_path"] == "memory/broker.md"

    events = memory_audit_query(conn, event_type="memory_context_pack_returned", persona="asa")
    assert len(events) == 1
    assert events[0]["trace_id"] == result["trace_id"]


def test_context_pack_allows_restricted_and_synthesis_only_when_explicit(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    restricted = tmp_path / "restricted.md"
    synthesis = tmp_path / "synthesis.md"
    _write_memory(
        restricted,
        ["type: semantic", "sensitivity_tier: restricted", "importance: 8"],
        "Restricted broker memory can appear only when explicitly requested.",
    )
    _write_memory(
        synthesis,
        ["type: semantic", "exclude_from_default_search: true", "importance: 8"],
        "Synthesis broker memory can appear only when explicitly requested.",
    )
    assert index_file(conn, "asa", "memory/restricted.md", restricted)
    assert index_file(conn, "asa", "memory/synthesis.md", synthesis)

    default = memory_context_pack(
        conn,
        current_context="broker memory explicit request",
        persona="asa",
        force=True,
    )
    assert default["returned_count"] == 0

    included = memory_context_pack(
        conn,
        current_context="broker memory explicit request",
        persona="asa",
        force=True,
        include_restricted=True,
        include_synthesis=True,
    )
    assert {card["relative_path"] for card in included["cards"]} == {
        "memory/restricted.md",
        "memory/synthesis.md",
    }


def test_context_pack_respects_token_budget(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    init_memory_tables(conn)

    for idx in range(5):
        path = tmp_path / f"memory-{idx}.md"
        _write_memory(
            path,
            ["type: procedural", "importance: 7"],
            f"Hermes broker memory card {idx} " + ("detail " * 80),
        )
        assert index_file(conn, "asa", f"memory/card-{idx}.md", path)

    result = memory_context_pack(
        conn,
        current_context="Hermes broker memory card detail",
        persona="asa",
        force=True,
        limit=5,
        token_budget=160,
    )

    assert 1 <= result["returned_count"] < 5
    assert result["token_estimate"] <= 160


def test_strip_memory_context_removes_supported_fences() -> None:
    text = (
        "hello\n"
        "<chimera-memory-context trace_id=\"x\">secret</chimera-memory-context>\n"
        "<memory-context>legacy</memory-context>\n"
        "<supermemory-context>provider</supermemory-context>\n"
        "world"
    )

    assert strip_memory_context(text) == "hello\n\n\n\nworld"
