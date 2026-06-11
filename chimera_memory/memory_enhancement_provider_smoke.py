"""Safe provider and sidecar smoke checks for memory enhancement."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from typing import Any

from .memory_enhancement import build_memory_enhancement_request, normalize_memory_enhancement_response
from .memory_enhancement_http_client import MemoryEnhancementHttpClient
from .memory_enhancement_provider import (
    build_enhancement_invocation,
    classify_enhancement_failure,
    resolve_enhancement_provider_plan,
    safe_provider_receipt,
)
from .memory_enhancement_sidecar import create_provider_sidecar_server

PROVIDER_SMOKE_SCHEMA_VERSION = "chimera-memory.provider-smoke.v1"
DEFAULT_PROVIDER_SMOKE_CONTENT = (
    "Chimera Memory provider smoke. Extract concise metadata for this diagnostic text only."
)


def memory_enhancement_provider_smoke(
    *,
    env: Mapping[str, str] | None = None,
    live: bool = False,
    http_sidecar: bool = False,
    expected_provider: str = "",
    expected_model: str = "",
    timeout_seconds: int = 30,
    client: Any | None = None,
) -> dict[str, Any]:
    """Return a safe provider smoke receipt.

    Plan mode proves provider resolution and invocation shape without a model
    call. Live mode is explicit because it may use networked user credentials.
    """
    started = time.perf_counter()
    env_map = os.environ if env is None else env
    plan = resolve_enhancement_provider_plan(env_map)
    provider = safe_provider_receipt(plan, env_map)
    selected = plan.selected
    request = build_memory_enhancement_request(
        content=DEFAULT_PROVIDER_SMOKE_CONTENT,
        persona="global",
        source_path="provider-smoke.md",
        existing_frontmatter={"type": "note", "tags": ["diagnostic", "sidecar"], "importance": 3},
        request_id="chimera-memory-provider-smoke",
    )
    invocation = build_enhancement_invocation(request, plan)
    invocation["request_id"] = "chimera-memory-provider-smoke"
    invocation.setdefault("budget", {})["timeout_seconds"] = _safe_timeout(timeout_seconds)

    receipt: dict[str, Any] = {
        "ok": True,
        "schema_version": PROVIDER_SMOKE_SCHEMA_VERSION,
        "status": "planned",
        "live": bool(live),
        "transport": "http_sidecar" if http_sidecar else "direct",
        "duration_ms": 0,
        "provider": provider,
        "expectations": {
            "provider": _clean_expected(expected_provider),
            "model": _clean_expected(expected_model),
            "matched": True,
        },
        "invocation": _safe_invocation_summary(invocation),
        "metadata": {},
        "body_included": False,
    }

    mismatch = _expectation_mismatch(
        selected_provider=selected.provider_id,
        selected_model=selected.model,
        expected_provider=expected_provider,
        expected_model=expected_model,
    )
    if mismatch:
        receipt.update(
            {
                "ok": False,
                "status": "expectation_failed",
                "error": {"code": mismatch, "message": ""},
            }
        )
        receipt["expectations"]["matched"] = False
        receipt["duration_ms"] = _elapsed_ms(started)
        return receipt

    if not live:
        receipt["duration_ms"] = _elapsed_ms(started)
        return receipt

    try:
        if http_sidecar:
            metadata = _invoke_ephemeral_provider_sidecar(
                invocation,
                client=client,
                timeout_seconds=_safe_timeout(timeout_seconds),
            )
            receipt["sidecar"] = {
                "contract_exercised": True,
                "endpoint": "local_ephemeral",
            }
        else:
            metadata = _invoke_provider_direct(invocation, client=client)
            receipt["sidecar"] = {
                "contract_exercised": False,
                "endpoint": "",
            }
        normalized = normalize_memory_enhancement_response(
            metadata,
            sensitivity_context=invocation.get("request") if isinstance(invocation.get("request"), Mapping) else {},
        )
    except Exception as exc:
        receipt.update(
            {
                "ok": False,
                "status": "failed",
                "error": {
                    "code": classify_enhancement_failure(str(exc)),
                    "message": "",
                },
            }
        )
    else:
        receipt.update(
            {
                "status": "succeeded",
                "metadata": _safe_metadata_summary(normalized),
            }
        )
    receipt["duration_ms"] = _elapsed_ms(started)
    return receipt


def _invoke_provider_direct(invocation: Mapping[str, Any], *, client: Any | None) -> Mapping[str, Any]:
    active_client = client
    if active_client is None:
        from .memory_enhancement_provider_sidecar import ResolvingMemoryEnhancementProviderClient

        active_client = ResolvingMemoryEnhancementProviderClient()
    result = active_client.invoke(invocation)
    return result if isinstance(result, Mapping) else {}


def _invoke_ephemeral_provider_sidecar(
    invocation: Mapping[str, Any],
    *,
    client: Any | None,
    timeout_seconds: int,
) -> Mapping[str, Any]:
    active_client = client
    if active_client is None:
        from .memory_enhancement_provider_sidecar import ResolvingMemoryEnhancementProviderClient

        active_client = ResolvingMemoryEnhancementProviderClient()
    server = create_provider_sidecar_server("127.0.0.1", 0, client=active_client)
    thread = threading.Thread(target=server.serve_forever, name="cm-provider-smoke-sidecar", daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        endpoint = f"http://{host}:{port}/enhance"
        return MemoryEnhancementHttpClient(endpoint, timeout_seconds=timeout_seconds).invoke(invocation)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _safe_invocation_summary(invocation: Mapping[str, Any]) -> dict[str, Any]:
    provider = invocation.get("provider") if isinstance(invocation.get("provider"), Mapping) else {}
    budget = invocation.get("budget") if isinstance(invocation.get("budget"), Mapping) else {}
    request = invocation.get("request") if isinstance(invocation.get("request"), Mapping) else {}
    return {
        "request_id": str(invocation.get("request_id") or ""),
        "provider_id": str(provider.get("provider_id") or ""),
        "model": str(provider.get("model") or ""),
        "credential_ref_present": bool(provider.get("credential_ref")),
        "uses_user_oauth": bool(provider.get("uses_user_oauth")),
        "requires_network": bool(provider.get("requires_network")),
        "timeout_seconds": _safe_timeout(budget.get("timeout_seconds")),
        "task": str(request.get("task") or ""),
        "persona": str(request.get("persona") or ""),
        "body_included": False,
    }


def _safe_metadata_summary(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "keys": sorted(str(key) for key in metadata),
        "summary_present": bool(str(metadata.get("summary") or "").strip()),
        "memory_type": _enum_text(metadata.get("memory_type")),
        "review_status": _enum_text(metadata.get("review_status")),
        "provenance_status": _enum_text(metadata.get("provenance_status")),
        "sensitivity_tier": _enum_text(metadata.get("sensitivity_tier")),
        "can_use_as_instruction": bool(metadata.get("can_use_as_instruction")),
        "can_use_as_evidence": bool(metadata.get("can_use_as_evidence")),
        "requires_user_confirmation": bool(metadata.get("requires_user_confirmation")),
        "topics_count": _list_count(metadata.get("topics")),
        "entities_count": _list_count(metadata.get("entities")),
        "action_items_count": _list_count(metadata.get("action_items")),
        "body_included": False,
    }


def _expectation_mismatch(
    *,
    selected_provider: str,
    selected_model: str,
    expected_provider: str,
    expected_model: str,
) -> str:
    provider = _clean_expected(expected_provider)
    model = _clean_expected(expected_model)
    if provider and provider != selected_provider:
        return "provider_mismatch"
    if model and model != selected_model:
        return "model_mismatch"
    return ""


def _clean_expected(value: object) -> str:
    return str(value or "").strip()


def _safe_timeout(value: object) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = 30
    return max(1, min(300, timeout))


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _enum_text(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text.replace("_", "").replace("-", "").isalnum() else ""


def _list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0
