import json

from chimera_memory.memory_enhancement_provider_smoke import (
    DEFAULT_PROVIDER_SMOKE_CONTENT,
    memory_enhancement_provider_smoke,
)


class FakeProviderClient:
    def __init__(self) -> None:
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return {
            "memory_type": "procedural",
            "summary": "Provider smoke returned metadata.",
            "topics": ["oauth", "sidecar"],
            "entities": [{"name": "Chimera Memory", "type": "tool", "confidence": 0.8}],
            "action_items": ["keep diagnostics safe"],
            "confidence": 0.8,
            "sensitivity_tier": "standard",
        }


def _openai_env(tmp_path):
    return {
        "CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_ORDER": "openai,dry_run",
        "CHIMERA_MEMORY_ENHANCEMENT_OPENAI_CREDENTIAL_REF": "oauth:openai-memory",
        "CHIMERA_MEMORY_OAUTH_STORE": str(tmp_path / "auth.json"),
    }


def test_provider_smoke_plan_receipt_hides_credential_and_body(tmp_path) -> None:
    result = memory_enhancement_provider_smoke(env=_openai_env(tmp_path))
    payload = json.dumps(result)

    assert result["ok"] is True
    assert result["status"] == "planned"
    assert result["live"] is False
    assert result["provider"]["selected_provider"] == "openai"
    assert result["provider"]["selected_model"] == "gpt-5.3-codex-spark"
    assert result["invocation"]["credential_ref_present"] is True
    assert result["invocation"]["uses_user_oauth"] is True
    assert "oauth:openai-memory" not in payload
    assert DEFAULT_PROVIDER_SMOKE_CONTENT not in payload


def test_provider_smoke_expectation_mismatch_does_not_invoke_live_client(tmp_path) -> None:
    client = FakeProviderClient()

    result = memory_enhancement_provider_smoke(
        env=_openai_env(tmp_path),
        live=True,
        expected_model="not-spark",
        client=client,
    )

    assert result["ok"] is False
    assert result["status"] == "expectation_failed"
    assert result["error"]["code"] == "model_mismatch"
    assert result["expectations"]["matched"] is False
    assert client.invocations == []


def test_provider_smoke_live_direct_returns_safe_metadata_summary(tmp_path) -> None:
    client = FakeProviderClient()

    result = memory_enhancement_provider_smoke(
        env=_openai_env(tmp_path),
        live=True,
        expected_provider="openai",
        expected_model="gpt-5.3-codex-spark",
        client=client,
    )
    payload = json.dumps(result)

    assert result["ok"] is True
    assert result["status"] == "succeeded"
    assert result["transport"] == "direct"
    assert result["sidecar"]["contract_exercised"] is False
    assert len(client.invocations) == 1
    assert result["metadata"]["summary_present"] is True
    assert result["metadata"]["review_status"] == "pending"
    assert result["metadata"]["can_use_as_instruction"] is False
    assert result["metadata"]["topics_count"] == 2
    assert "Provider smoke returned metadata." not in payload
    assert DEFAULT_PROVIDER_SMOKE_CONTENT not in payload
    assert "oauth:openai-memory" not in payload


def test_provider_smoke_live_http_sidecar_exercises_contract(tmp_path) -> None:
    client = FakeProviderClient()

    result = memory_enhancement_provider_smoke(
        env=_openai_env(tmp_path),
        live=True,
        http_sidecar=True,
        client=client,
    )
    payload = json.dumps(result)

    assert result["ok"] is True
    assert result["status"] == "succeeded"
    assert result["transport"] == "http_sidecar"
    assert result["sidecar"] == {
        "contract_exercised": True,
        "endpoint": "local_ephemeral",
    }
    assert len(client.invocations) == 1
    assert result["metadata"]["summary_present"] is True
    assert result["metadata"]["can_use_as_instruction"] is False
    assert DEFAULT_PROVIDER_SMOKE_CONTENT not in payload
    assert "oauth:openai-memory" not in payload
