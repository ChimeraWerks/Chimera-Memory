"""Display-safe labels for memory paths.

Storage keeps raw file paths for indexing and repair, but prompt/MCP display
must not echo path-shaped DB text back to users.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PureWindowsPath

from .sanitizer import sanitize_content


_LOCAL_PATH_FRAGMENT_RE = re.compile(
    r"file://[^\s\"'<>]+"
    r"|(?<![\w])(?:[A-Za-z]:[^\s\"'<>]+)"
    r"|(?:(?<=^)|(?<=[\s=\(\[\{]))/(?!/)[^\s\"'<>]+"
)


def is_safe_relative_path_text(value: object) -> bool:
    text = str(value or "").replace("\\", "/").strip()
    if not text or text.startswith(("/", "\\")):
        return False
    if any(ord(char) < 32 for char in text):
        return False
    windows = PureWindowsPath(text)
    if windows.drive or windows.root or ":" in text:
        return False
    path = Path(text)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def safe_filename_label(value: object, *, default: str = "unsafe-relative-path") -> str:
    text = str(value or "").replace("\\", "/").strip()
    name = PureWindowsPath(text).name or Path(text).name
    name = "".join(char for char in name if ord(char) >= 32).strip()
    if ":" in name:
        name = name.split(":", 1)[0]
    name = name.replace("/", "_").replace("\\", "_").strip()
    if not name or name in {".", ".."}:
        return default
    return name


def safe_memory_relative_path_display(
    value: object,
    *,
    fallback_path: object = "",
    default: str = "unsafe-relative-path",
) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return ""
    if is_safe_relative_path_text(text):
        return text
    return safe_filename_label(fallback_path or text, default=default)


def local_path_fingerprint(value: object, *, length: int = 12) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[: max(1, int(length))]


def looks_like_local_path_reference(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower.startswith("file://"):
        return True
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        return True
    if text.startswith("\\\\"):
        return True
    if text.startswith("/") and not lower.startswith(("http://", "https://")):
        return True
    return "\\" in text


def safe_local_path_reference_display(value: object, *, default: str = "local-reference") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not looks_like_local_path_reference(text):
        return text
    name = safe_filename_label(text, default=default)
    fingerprint = local_path_fingerprint(text)
    suffix = f" (fingerprint={fingerprint})" if fingerprint else ""
    return f"local-path:{name}{suffix}"


def redact_local_path_references(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""

    def replace(match: re.Match[str]) -> str:
        return safe_local_path_reference_display(match.group(0))

    return _LOCAL_PATH_FRAGMENT_RE.sub(replace, text)


def safe_memory_text_display(value: object) -> str:
    """Render prompt/MCP prose without secrets or local path references."""
    return redact_local_path_references(sanitize_content(str(value or "")) or "")
