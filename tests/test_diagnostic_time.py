from datetime import timezone, timedelta

from chimera_memory.diagnostic_time import format_diagnostic_timestamp


def test_format_diagnostic_timestamp_includes_utc_and_local_time() -> None:
    eastern = timezone(timedelta(hours=-4), "EDT")

    rendered = format_diagnostic_timestamp("2026-06-11T01:28:41.402Z", local_tz=eastern)

    assert rendered == "2026-06-11T01:28:41.402Z (local 2026-06-10 21:28:41 EDT)"


def test_format_diagnostic_timestamp_leaves_unparseable_values_unchanged() -> None:
    assert format_diagnostic_timestamp("not-a-time") == "not-a-time"
