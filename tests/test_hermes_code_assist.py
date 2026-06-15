import chimera_memory.hermes_google_code_assist as code_assist
from chimera_memory.hermes_google_code_assist import FREE_TIER_ID, onboard_user


def _patch_lro(monkeypatch):
    """Make onboarding an LRO that never finishes, and count poll sleeps."""
    sleeps = {"count": 0}

    def fake_post_json(url, body, access_token, **kwargs):
        # First call returns an unfinished LRO; polls keep returning unfinished.
        return {"name": "operations/onboard-x"}

    def fake_sleep(_seconds):
        sleeps["count"] += 1

    monkeypatch.setattr(code_assist, "_post_json", fake_post_json)
    monkeypatch.setattr(code_assist.time, "sleep", fake_sleep)
    return sleeps


def test_onboard_user_aborts_polls_past_deadline(monkeypatch):
    # hermes-011: an already-expired caller deadline must abort onboarding polls
    # immediately instead of blocking for the full 12x5s budget.
    sleeps = _patch_lro(monkeypatch)
    expired = code_assist.time.monotonic() - 1.0

    onboard_user(
        "token", tier_id=FREE_TIER_ID, project_id="", deadline_monotonic=expired
    )

    assert sleeps["count"] == 0


def test_onboard_user_polls_full_budget_without_deadline(monkeypatch):
    # Backward compatible: no deadline → existing 12-attempt polling behavior.
    sleeps = _patch_lro(monkeypatch)

    onboard_user("token", tier_id=FREE_TIER_ID, project_id="", deadline_monotonic=None)

    assert sleeps["count"] == code_assist._ONBOARDING_POLL_ATTEMPTS
