import json

import httpx

from chimera_memory.hermes_gemini_cloudcode_adapter import _gemini_http_error, _iter_sse_events
from chimera_memory.memory_enhancement_provider_sidecar import _google_cloudcode_model_retryable


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def iter_text(self):
        yield from self._chunks


def test_iter_sse_events_flushes_final_line_without_newline():
    # hermes-005: a stream closed right after the last `data: {...}` with no
    # trailing newline / [DONE] must still yield that closing chunk.
    parsed = list(_iter_sse_events(_FakeStream(['data: {"finishReason": "STOP"}'])))
    assert parsed == [{"finishReason": "STOP"}]


def test_iter_sse_events_skips_done_sentinel_without_newline():
    # A trailing [DONE] with no newline must not be parsed as JSON.
    parsed = list(_iter_sse_events(_FakeStream(["data: [DONE]"])))
    assert parsed == []


def _response_404(message: str, status: str = "") -> httpx.Response:
    err = {"message": message}
    if status:
        err["status"] = status
    return httpx.Response(404, content=json.dumps({"error": err}).encode())


def test_gemini_http_error_model_404_stays_retryable():
    # hermes-008: a 404 naming a model keeps code_assist_http_404 so the sidecar
    # fans out across model candidates.
    err = _gemini_http_error(_response_404("Model gemini-x not found", status="NOT_FOUND"))
    assert err.code == "code_assist_http_404"
    assert _google_cloudcode_model_retryable(f"code={err.code}") is True


def test_gemini_http_error_generic_404_fails_fast():
    # hermes-008: a generic 404 ("Not Found", misconfigured base_url) must fail
    # fast — a distinct code the sidecar substring-match won't treat as retryable.
    err = _gemini_http_error(_response_404("Not Found"))
    assert err.code == "code_assist_endpoint_404"
    assert _google_cloudcode_model_retryable(f"code={err.code}") is False
