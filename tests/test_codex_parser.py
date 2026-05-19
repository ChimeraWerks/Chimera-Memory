import json
from pathlib import Path

from chimera_memory.parser import get_parser


def test_codex_offset_parse_uses_session_meta_id(tmp_path: Path) -> None:
    path = tmp_path / "rollout-2026-05-19T13-30-25-session-id.jsonl"
    rows = [
        {
            "timestamp": "2026-05-19T17:30:25.541Z",
            "type": "session_meta",
            "payload": {
                "id": "019e4149-f0d1-7e91-9de9-28325474cb40",
                "timestamp": "2026-05-19T17:30:25.541Z",
                "cwd": "C:/repo/personas/developer/asa",
            },
        },
        {
            "timestamp": "2026-05-19T17:31:19.273Z",
            "type": "event_msg",
            "payload": {
                "type": "agent_message",
                "phase": "final",
                "message": "Tail-read after session_meta should keep the real session id.",
            },
        },
    ]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(rows[0]) + "\n")
        offset = handle.tell()
        handle.write(json.dumps(rows[1]) + "\n")

    parser = get_parser("codex")
    parsed = list(parser.parse_file(path, start_offset=offset))

    assert len(parsed) == 1
    assert parsed[0]["session_id"] == "019e4149-f0d1-7e91-9de9-28325474cb40"
