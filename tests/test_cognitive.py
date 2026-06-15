from datetime import datetime, timezone

from chimera_memory.cognitive import _days_since, compute_zone_score


def test_days_since_handles_utc_z_and_naive_dates() -> None:
    # se-04: the stored fm_last_accessed is UTC '...Z'; _days_since must parse it
    # against a tz-aware UTC now without a naive/aware subtraction crash, and
    # normalize a naive author date to UTC.
    now = datetime(2026, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert abs(_days_since("2026-06-14T00:00:00Z", None, now) - 1.0) < 0.01
    assert abs(_days_since(None, "2026-06-14", now) - 1.0) < 0.01


def test_zone_score_biases_by_review_status() -> None:
    base = compute_zone_score(importance=7, access_count=2, days_since_access=10, failure_count=0)
    confirmed = compute_zone_score(
        importance=7,
        access_count=2,
        days_since_access=10,
        failure_count=0,
        review_status="confirmed",
    )
    evidence_only = compute_zone_score(
        importance=7,
        access_count=2,
        days_since_access=10,
        failure_count=0,
        review_status="evidence_only",
    )
    pending = compute_zone_score(
        importance=7,
        access_count=2,
        days_since_access=10,
        failure_count=0,
        review_status="pending",
    )

    assert confirmed == min(1.0, round(base + 0.15, 4))
    assert evidence_only == round(base + 0.05, 4)
    assert pending == round(base - 0.08, 4)
