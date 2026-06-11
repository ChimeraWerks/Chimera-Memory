"""Timestamp formatting helpers for user-facing diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo


def format_diagnostic_timestamp(value: object, *, local_tz: tzinfo | None = None) -> str:
    """Render a stored UTC timestamp with an explicit local-time companion."""
    text = str(value or "").strip()
    if not text:
        return "-"
    parsed = _parse_timestamp(text)
    if parsed is None:
        return text
    utc_dt = parsed.astimezone(timezone.utc)
    local_dt = utc_dt.astimezone(local_tz) if local_tz is not None else utc_dt.astimezone()
    return f"{_format_utc(utc_dt)} (local {_format_local(local_dt)})"


def _parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_utc(value: datetime) -> str:
    text = value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return text.replace(".000Z", "Z")


def _format_local(value: datetime) -> str:
    label = value.strftime("%Y-%m-%d %H:%M:%S")
    zone = value.tzname() or value.strftime("%z") or "local"
    return f"{label} {zone}"
