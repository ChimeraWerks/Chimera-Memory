"""Deterministic local worker for memory-enhancement jobs.

This is a dry-run worker. It proves queue consumption and result handling
without calling an LLM, OAuth provider, or local model.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from .memory import (
    memory_enhancement_claim_next,
    memory_enhancement_complete,
    memory_worker_budget,
    memory_worker_claim_next,
    memory_worker_heartbeat,
    memory_worker_submit_result,
)
from .memory_enhancement import (
    ALLOWED_MEMORY_TYPES,
    UNTRUSTED_END,
    UNTRUSTED_START,
)


_DATE_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_ACTION_RE = re.compile(r"^(?:[-*]\s*\[\s*\]\s*|todo:|action:)\s*(?P<text>.+)$", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOPWORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "into",
    "not",
    "the",
    "this",
    "that",
    "with",
    "without",
}


def _wrapped_content_text(request_payload: dict[str, Any]) -> str:
    wrapped = str(request_payload.get("wrapped_content") or "")
    if UNTRUSTED_START in wrapped and UNTRUSTED_END in wrapped:
        return wrapped.split(UNTRUSTED_START, 1)[1].split(UNTRUSTED_END, 1)[0].strip()
    return wrapped.strip()


def _first_sentence(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:240]
    return ""


def _topic_candidates(text: str, existing_tags: Any) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        topic = str(value or "").strip()
        key = topic.lower()
        if not topic or key in seen or key in _STOPWORDS:
            return
        topics.append(topic[:80])
        seen.add(key)

    if isinstance(existing_tags, list):
        for tag in existing_tags:
            add(tag)
    elif isinstance(existing_tags, str):
        add(existing_tags)

    counts: dict[str, int] = {}
    for word in _WORD_RE.findall(text):
        key = word.lower()
        if key in _STOPWORDS:
            continue
        counts[key] = counts.get(key, 0) + 1
    for word, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]:
        add(word)
    return topics[:12]


def _action_items(text: str) -> list[str]:
    actions: list[str] = []
    for line in text.splitlines():
        match = _ACTION_RE.match(line.strip())
        if match:
            actions.append(match.group("text").strip()[:200])
        if len(actions) >= 10:
            break
    return actions


def derive_dry_run_metadata(job: dict[str, Any]) -> dict[str, Any]:
    """Derive deterministic metadata from a queued job payload."""
    request_payload = job.get("request_payload") or {}
    existing = request_payload.get("existing_frontmatter") or {}
    text = _wrapped_content_text(request_payload)
    existing_type = str(existing.get("type") or "").strip()
    memory_type = existing_type if existing_type in ALLOWED_MEMORY_TYPES else "semantic"

    return {
        "memory_type": memory_type,
        "summary": str(existing.get("about") or "").strip() or _first_sentence(text),
        "topics": _topic_candidates(text, existing.get("tags")),
        "people": [],
        "projects": [],
        "tools": [],
        "action_items": _action_items(text),
        "dates": _DATE_RE.findall(text)[:10],
        "confidence": 0.35,
        "sensitivity_tier": "standard",
    }


def run_memory_enhancement_dry_run(
    conn: sqlite3.Connection,
    *,
    persona: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Process pending enhancement jobs with deterministic local metadata."""
    processed: list[dict[str, Any]] = []
    for _ in range(max(0, min(limit, 100))):
        job = memory_enhancement_claim_next(conn, persona=persona)
        if job is None:
            break
        metadata = derive_dry_run_metadata(job)
        result = memory_enhancement_complete(
            conn,
            job_id=job["job_id"],
            status="succeeded",
            response_payload=metadata,
            actual_provider="dry_run",
            actual_model="deterministic-local",
        )
        if result.get("ok"):
            processed.append(result["job"])
    return processed


def run_memory_enhancement_fake_worker(
    conn: sqlite3.Connection,
    *,
    worker_id: str = "fake-memory-worker",
    persona: str | None = None,
    provider: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Exercise the CLI-worker protocol with deterministic local metadata.

    This harness never spawns a provider CLI and never makes a model call. It
    claims work through the worker protocol, derives the same deterministic
    metadata as the dry-run worker, and submits the result through the same
    validation/writeback path a real CLI worker will use.
    """
    worker_id = str(worker_id or "").strip() or "fake-memory-worker"
    provider = str(provider or "").strip()
    processed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    budget: dict[str, Any] | None = None
    budget_stopped = False
    race_lost = False

    memory_worker_heartbeat(
        conn,
        worker_id=worker_id,
        capability="enhancement",
        provider=provider,
        status="idle",
        metadata={"mode": "fake_worker"},
    )

    for _ in range(max(0, min(limit, 100))):
        budget = memory_worker_budget(
            conn,
            worker_id=worker_id,
            capability="enhancement",
            provider=provider,
        )
        if not budget.get("ok", False):
            failures.append({"status": "failed", "error": budget.get("error", "budget check failed")})
            break
        if not budget.get("allowed", False):
            budget_stopped = True
            memory_worker_heartbeat(
                conn,
                worker_id=worker_id,
                capability="enhancement",
                provider=provider,
                status="idle",
                metadata={"mode": "fake_worker", "stop_reason": budget.get("reason", "budget_denied")},
            )
            break

        claimed = memory_worker_claim_next(
            conn,
            worker_id=worker_id,
            capability="enhancement",
            persona=persona,
            provider=provider,
        )
        if not claimed.get("ok", False):
            failures.append({"status": "failed", "error": claimed.get("error", "claim failed")})
            break
        if claimed.get("race_lost"):
            race_lost = True
            continue
        job = claimed.get("job")
        if not job:
            break

        metadata = derive_dry_run_metadata(job)
        submitted = memory_worker_submit_result(
            conn,
            worker_id=worker_id,
            job_id=str(job["job_id"]),
            status="succeeded",
            result_payload=metadata,
            actual_provider="dry_run",
            actual_model="deterministic-local",
            diagnostics={"mode": "fake_worker"},
        )
        if submitted.get("ok"):
            processed.append(submitted["job"])
        else:
            failures.append(
                {
                    "job_id": job["job_id"],
                    "status": "failed",
                    "error": submitted.get("error", "submit failed"),
                }
            )
            memory_worker_heartbeat(
                conn,
                worker_id=worker_id,
                capability="enhancement",
                provider=provider,
                status="failed",
                current_job_id=str(job["job_id"]),
                metadata={"mode": "fake_worker", "error": submitted.get("error", "submit failed")},
            )
            break

    return {
        "worker_id": worker_id,
        "provider": provider,
        "mode": "fake_worker",
        "processed": processed,
        "failures": failures,
        "processed_count": len(processed),
        "failure_count": len(failures),
        "budget_stopped": budget_stopped,
        "race_lost": race_lost,
        "budget": budget,
    }
