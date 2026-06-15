from chimera_memory.memory_display import redact_local_path_references, safe_memory_text_display


def test_redacts_unc_path():
    # mfr-08: UNC paths (the Windows style most likely on this platform) must be
    # redacted, not echoed raw through MCP-facing prose.
    redacted = redact_local_path_references(r"see \\server\share\secret.txt for details")
    assert r"\\server\share" not in redacted
    assert "local-path:" in redacted


def test_redacts_relative_backslash_path():
    redacted = redact_local_path_references(r"open ..\..\notes\plan.md now")
    assert r"..\..\notes" not in redacted
    assert "local-path:" in redacted


def test_drive_letter_path_still_redacted():
    redacted = redact_local_path_references(r"at C:\Users\charl\x.md")
    assert r"C:\Users\charl" not in redacted
    assert "local-path:" in redacted


def test_clean_prose_unchanged():
    text = "no paths here, just prose about memory"
    assert redact_local_path_references(text) == text


def test_safe_memory_text_display_redacts_unc():
    assert r"\\server\share" not in safe_memory_text_display(r"note: \\server\share\creds.txt")
