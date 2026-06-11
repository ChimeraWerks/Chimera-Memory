"""Runtime helpers for launching local Codex commands."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def codex_executable_for_subprocess(command: str | None = None) -> str:
    """Return a Codex executable that Python subprocess can launch on Windows."""
    selected = str(command or "").strip() or os.environ.get("CHIMERA_MEMORY_CODEX_BIN", "").strip() or "codex"
    if os.name != "nt" or _looks_like_path(selected) or Path(selected).suffix:
        return selected
    for candidate in (f"{selected}.cmd", f"{selected}.exe", f"{selected}.bat", selected):
        if shutil.which(candidate):
            return candidate
    return selected


def _looks_like_path(value: str) -> bool:
    return any(separator and separator in value for separator in (os.sep, os.altsep))
