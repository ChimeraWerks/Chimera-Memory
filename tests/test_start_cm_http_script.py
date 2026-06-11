from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "start-cm-http.ps1"


def test_start_cm_http_reuse_checks_parent_venv_launcher() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "ParentExecutablePath" in text
    assert "ParentCommandLine" in text
    assert "Test-CmProcessUsesRuntime" in text
    assert "ExecutablePath, $ProcessInfo.ParentExecutablePath" in text
    assert "CommandLine, $ProcessInfo.ParentCommandLine" in text


def test_start_cm_http_only_reuses_listening_port_owner() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "Get-NetTCPConnection -State Listen" in text
    assert "Select-Object -ExpandProperty OwningProcess -Unique" in text
