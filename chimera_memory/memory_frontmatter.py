"""Markdown frontmatter parsing helpers."""

from __future__ import annotations


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    try:
        import yaml

        fm = yaml.safe_load(text[3:end].strip())
    except Exception:
        fm = {}
    # Valid YAML that is not a mapping (e.g. a top-level list or scalar) would
    # otherwise reach callers as fm.get(...) -> AttributeError and abort a whole
    # reindex on one malformed file. Coerce any non-dict body to an empty dict.
    if not isinstance(fm, dict):
        fm = {}
    return fm, text[end + 4 :].strip()
