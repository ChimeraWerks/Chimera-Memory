"""Local embedding generation and vector storage/search."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import math
import os
import struct
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Generator

log = logging.getLogger(__name__)

# Embedding model config
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384
DEFAULT_CPU_RESERVE_PERCENT = 20
FASTEMBED_CUDA_ENV = "CHIMERA_MEMORY_FASTEMBED_CUDA"
FASTEMBED_DEVICE_IDS_ENV = "CHIMERA_MEMORY_FASTEMBED_DEVICE_IDS"
GPU_PROVIDER_PREFERENCE = (
    "CUDAExecutionProvider",
    "DmlExecutionProvider",
    "ROCMExecutionProvider",
    "MIGraphXExecutionProvider",
    "TensorrtExecutionProvider",
    "CoreMLExecutionProvider",
    "OpenVINOExecutionProvider",
)
TRANSCRIPT_EMBEDDABLE_TYPES = (
    "user_message",
    "assistant_message",
    "discord_inbound",
    "discord_outbound",
)

# Lazy-loaded model singleton
_model = None
_model_lock = threading.Lock()


@dataclass(frozen=True)
class EmbeddingRuntimeConfig:
    """Resolved ONNX/FastEmbed runtime choices for one model instance."""

    requested_provider: str
    provider: str
    providers: tuple[str, ...]
    available_providers: tuple[str, ...]
    cpu_count: int
    cpu_reserve_percent: int
    threads: int
    using_gpu: bool
    throttle_cpu: bool
    fastembed_cuda: bool | None
    fastembed_device_ids: tuple[int, ...]
    cuda_visible_devices: str


def _get_cache_dir():
    """Persistent cache directory for the ONNX embedding model.

    Default: ~/.chimera-memory/cache/. Override with CHIMERA_MEMORY_CACHE_DIR.
    MUST NOT live in %TEMP% — Windows auto-cleans Temp periodically and that
    wipes the cached ONNX model, causing NoSuchFile crashes on next server
    startup (Day 25 root-cause fix, 2026-04-16).
    """
    import os
    from pathlib import Path
    override = os.environ.get("CHIMERA_MEMORY_CACHE_DIR")
    if override:
        cache_dir = Path(override)
    else:
        cache_dir = Path.home() / ".chimera-memory" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir)


def _get_progress_path() -> Path:
    override = os.environ.get("CHIMERA_MEMORY_EMBEDDING_PROGRESS_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".chimera-memory" / "embedding-progress.json"


def embedding_progress_path() -> str:
    """Return the status file path used for live embedding progress."""

    return str(_get_progress_path())


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("%s=%r is not an integer; using %s", name, raw, default)
        return default
    return max(minimum, min(maximum, value))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _env_optional_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    value = raw.strip().lower()
    if value == "auto":
        return None
    if value in {"1", "true", "yes", "on", "enabled"}:
        return True
    if value in {"0", "false", "no", "off", "disabled"}:
        return False
    log.warning("%s=%r is not true, false, or auto; using auto", name, raw)
    return None


def _env_int_tuple(name: str) -> tuple[int, ...]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return ()
    values: list[int] = []
    for item in raw.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        try:
            value = int(stripped)
        except ValueError:
            log.warning("%s=%r contains a non-integer device id; ignoring", name, raw)
            return ()
        if value < 0:
            log.warning("%s=%r contains a negative device id; ignoring", name, raw)
            return ()
        values.append(value)
    return tuple(values)


def _available_onnx_providers() -> tuple[str, ...]:
    try:
        import onnxruntime as ort

        return tuple(ort.get_available_providers())
    except Exception as exc:  # pragma: no cover - exercised only with broken local installs
        log.warning("Unable to inspect ONNX Runtime providers; falling back to CPU: %s", exc)
        return ("CPUExecutionProvider",)


def _resolve_embedding_runtime_config() -> EmbeddingRuntimeConfig:
    cpu_count = os.cpu_count() or 1
    reserve_percent = _env_int(
        "CHIMERA_MEMORY_EMBEDDING_CPU_RESERVE_PERCENT",
        DEFAULT_CPU_RESERVE_PERCENT,
        minimum=0,
        maximum=95,
    )
    explicit_threads = os.environ.get("CHIMERA_MEMORY_EMBEDDING_MAX_THREADS")
    if explicit_threads and explicit_threads.strip():
        threads = _env_int(
            "CHIMERA_MEMORY_EMBEDDING_MAX_THREADS",
            max(1, math.floor(cpu_count * (100 - reserve_percent) / 100)),
            minimum=1,
            maximum=cpu_count,
        )
    else:
        threads = max(1, math.floor(cpu_count * (100 - reserve_percent) / 100))

    requested_provider = (
        os.environ.get("CHIMERA_MEMORY_EMBEDDING_PROVIDER")
        or os.environ.get("CHIMERA_MEMORY_EMBEDDING_DEVICE")
        or "auto"
    ).strip().lower()
    if requested_provider not in {"auto", "gpu", "cpu"}:
        log.warning(
            "Unknown CHIMERA_MEMORY_EMBEDDING_PROVIDER=%r; using auto",
            requested_provider,
        )
        requested_provider = "auto"

    fastembed_cuda = _env_optional_bool(FASTEMBED_CUDA_ENV)
    fastembed_device_ids = _env_int_tuple(FASTEMBED_DEVICE_IDS_ENV)
    if fastembed_device_ids and fastembed_cuda is None:
        fastembed_cuda = True

    available_providers = _available_onnx_providers()
    selected_gpu = next(
        (provider for provider in GPU_PROVIDER_PREFERENCE if provider in available_providers),
        "",
    )
    if requested_provider == "cpu":
        fastembed_cuda = False
        fastembed_device_ids = ()

    if fastembed_cuda is True:
        providers = ()
        provider = "FastEmbed CUDA"
        using_gpu = True
    elif requested_provider in {"auto", "gpu"} and selected_gpu:
        providers = (selected_gpu, "CPUExecutionProvider")
        provider = selected_gpu
        using_gpu = True
    elif requested_provider == "gpu":
        providers = ("CPUExecutionProvider",)
        provider = "cpu_fallback"
        using_gpu = False
        log.warning(
            "GPU embeddings requested, but no supported ONNX GPU provider is available. "
            "Available providers: %s",
            ", ".join(available_providers) or "none",
        )
    else:
        providers = ("CPUExecutionProvider",)
        provider = "CPUExecutionProvider"
        using_gpu = False

    return EmbeddingRuntimeConfig(
        requested_provider=requested_provider,
        provider=provider,
        providers=providers,
        available_providers=available_providers,
        cpu_count=cpu_count,
        cpu_reserve_percent=reserve_percent,
        threads=threads,
        using_gpu=using_gpu,
        throttle_cpu=_env_bool("CHIMERA_MEMORY_EMBEDDING_CPU_THROTTLE", True),
        fastembed_cuda=fastembed_cuda,
        fastembed_device_ids=fastembed_device_ids,
        cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES", ""),
    )


def embedding_runtime_status() -> dict:
    """Return the resolved embedding runtime plan without loading the model."""

    return asdict(_resolve_embedding_runtime_config())


def _configure_thread_env(config: EmbeddingRuntimeConfig) -> None:
    thread_value = str(config.threads)
    inter_threads = str(max(1, min(config.threads, config.threads // 2 or 1)))
    os.environ["OMP_NUM_THREADS"] = thread_value
    os.environ["ORT_INTRA_OP_NUM_THREADS"] = thread_value
    os.environ["ORT_INTER_OP_NUM_THREADS"] = inter_threads


def _write_embedding_progress(state: dict) -> None:
    path = _get_progress_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception:
        log.debug("failed to write embedding progress state", exc_info=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_progress_bar(current: int, total: int, *, width: int = 28) -> str:
    """Return a compact ASCII progress bar for logs and CLI output."""

    total = max(0, int(total))
    current = max(0, int(current))
    if total <= 0:
        return "[----------------------------]   0% 0/0"
    current = min(current, total)
    pct = current / total
    filled = int(round(width * pct))
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {pct * 100:5.1f}% {current:,}/{total:,}"


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _progress_message(
    current: int,
    total: int,
    *,
    started_at_monotonic: float,
    width: int = 28,
) -> str:
    elapsed = max(0.001, time.monotonic() - started_at_monotonic)
    rate = current / elapsed if current else 0.0
    remaining = (total - current) / rate if rate else 0.0
    return (
        f"{format_progress_bar(current, total, width=width)} "
        f"rate={rate:.1f}/s eta={_format_duration(remaining)}"
    )


def _sleep_for_cpu_reserve(work_seconds: float, config: EmbeddingRuntimeConfig) -> None:
    if config.using_gpu or not config.throttle_cpu or config.cpu_reserve_percent <= 0:
        return
    active_percent = max(1, 100 - config.cpu_reserve_percent)
    sleep_seconds = work_seconds * (config.cpu_reserve_percent / active_percent)
    if sleep_seconds > 0:
        time.sleep(min(sleep_seconds, 5.0))


def _get_model():
    """Lazy-load the embedding model (23MB ONNX, cached after first download).

    Uses an ONNX GPU provider when one is available, otherwise caps ONNX CPU
    threads so CM leaves a configurable CPU reserve for the rest of the system.
    Cache path is explicitly persistent (see _get_cache_dir).
    """
    global _model
    if _model is None:
        with _model_lock:
            if _model is not None:
                return _model

            _model = _load_model()
    return _model


def _load_model():
    config = _resolve_embedding_runtime_config()
    _configure_thread_env(config)
    cache_dir = _get_cache_dir()
    from fastembed import TextEmbedding

    model_kwargs: dict[str, object] = {
        "model_name": MODEL_NAME,
        "threads": config.threads,
        "cache_dir": cache_dir,
    }
    if config.fastembed_cuda is not None:
        model_kwargs["cuda"] = config.fastembed_cuda
        if config.fastembed_device_ids:
            model_kwargs["device_ids"] = list(config.fastembed_device_ids)
    else:
        model_kwargs["providers"] = list(config.providers)

    model = TextEmbedding(**model_kwargs)
    log.info(
        "Loaded embedding model: %s (%d dims, provider=%s, threads=%d/%d, "
        "cpu_reserve=%d%%, fastembed_cuda=%s, device_ids=%s, CUDA_VISIBLE_DEVICES=%s, cache=%s)",
        MODEL_NAME,
        EMBEDDING_DIM,
        config.provider,
        config.threads,
        config.cpu_count,
        config.cpu_reserve_percent,
        config.fastembed_cuda,
        list(config.fastembed_device_ids),
        config.cuda_visible_devices,
        cache_dir,
    )
    return model


def embed_text(text: str) -> list[float]:
    """Embed a single text string. Returns a list of floats."""
    model = _get_model()
    results = list(model.embed([text]))
    if not results:
        # fastembed yields one vector per non-empty input today; an empty result
        # would IndexError below and escape unwrapped through the
        # memory_context_pack MCP path. Raise a clean error so callers degrade to
        # FTS-only instead of leaking a raw exception (se-07).
        raise RuntimeError("embedding produced no output")
    return results[0].tolist()


def embed_batch(texts: list[str], batch_size: int = 64) -> Generator[list[float], None, None]:
    """Embed a batch of texts. Yields one embedding per text."""
    model = _get_model()
    for embedding in model.embed(texts, batch_size=batch_size):
        yield embedding.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors. Pure Python, no numpy."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def pack_embedding(embedding: list[float]) -> bytes:
    """Pack a float list into bytes for SQLite BLOB storage."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def unpack_embedding(blob: bytes) -> list[float]:
    """Unpack bytes back into a float list."""
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


# Schema for embedding storage
EMBEDDING_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcript_embeddings (
    transcript_id INTEGER PRIMARY KEY,
    embedding BLOB NOT NULL,
    FOREIGN KEY (transcript_id) REFERENCES transcript(id) ON DELETE CASCADE
);
"""


def init_embedding_table(conn: sqlite3.Connection):
    """Create the embeddings table if it doesn't exist."""
    conn.execute(EMBEDDING_SCHEMA)
    conn.commit()


def store_embeddings(conn: sqlite3.Connection, entries: list[tuple[int, list[float]]]):
    """Batch store embeddings. entries = [(transcript_id, embedding_vector), ...]"""
    data = [(tid, pack_embedding(emb)) for tid, emb in entries]
    conn.executemany(
        "INSERT OR IGNORE INTO transcript_embeddings (transcript_id, embedding) VALUES (?, ?)",
        data,
    )
    conn.commit()


def vector_search(conn: sqlite3.Connection, query_embedding: list[float],
                   limit: int = 50, entry_types: list[str] | None = None) -> list[tuple[int, float]]:
    """Search for similar entries by cosine similarity.

    Returns list of (transcript_id, similarity_score) sorted by similarity descending.
    This is a brute-force scan — fine for <1M entries. For larger scale, use sqlite-vec.
    """
    # Build query with optional type filter
    if entry_types:
        placeholders = ",".join("?" * len(entry_types))
        sql = f"""
            SELECT e.transcript_id, e.embedding
            FROM transcript_embeddings e
            JOIN transcript t ON t.id = e.transcript_id
            WHERE t.entry_type IN ({placeholders})
        """
        rows = conn.execute(sql, entry_types).fetchall()
    else:
        rows = conn.execute(
            "SELECT transcript_id, embedding FROM transcript_embeddings"
        ).fetchall()

    # Compute similarities
    results = []
    for row in rows:
        tid = row[0]
        stored_emb = unpack_embedding(row[1])
        sim = cosine_similarity(query_embedding, stored_emb)
        results.append((tid, sim))

    # Sort by similarity descending, return top N
    results.sort(key=lambda x: -x[1])
    return results[:limit]


def count_unembedded_transcript_entries(conn: sqlite3.Connection) -> int:
    """Count transcript entries that are eligible for embedding and missing one."""
    init_embedding_table(conn)
    placeholders = ",".join("?" * len(TRANSCRIPT_EMBEDDABLE_TYPES))
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM transcript t
            LEFT JOIN transcript_embeddings e ON e.transcript_id = t.id
            WHERE e.transcript_id IS NULL
              AND t.content IS NOT NULL
              AND t.content != ''
              AND t.entry_type IN ({placeholders})
            """,
            TRANSCRIPT_EMBEDDABLE_TYPES,
        ).fetchone()[0]
    )


def embed_transcript_entries(db, conn: sqlite3.Connection, batch_size: int = 100,
                              progress_callback: Callable[[int, int], None] | None = None,
                              limit: int | None = None,
                              progress_label: str = "transcript embeddings",
                              log_progress: bool = True):
    """Embed all transcript entries that don't have embeddings yet.

    Only embeds entries with content (skips tool_result, system, etc.).

    Args:
        db: TranscriptDB instance
        conn: SQLite connection
        batch_size: Number of entries to embed per batch
        progress_callback: Called with (entries_done, total_entries) after each batch
        limit: Optional maximum entries to embed in this run
    """
    init_embedding_table(conn)
    placeholders = ",".join("?" * len(TRANSCRIPT_EMBEDDABLE_TYPES))
    params: list[object] = list(TRANSCRIPT_EMBEDDABLE_TYPES)
    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT ?"
        params.append(max(0, int(limit)))

    # Find entries needing embeddings
    rows = conn.execute(f"""
        SELECT t.id, t.content
        FROM transcript t
        LEFT JOIN transcript_embeddings e ON e.transcript_id = t.id
        WHERE e.transcript_id IS NULL
          AND t.content IS NOT NULL
          AND t.content != ''
          AND t.entry_type IN ({placeholders})
        ORDER BY t.id ASC
        {limit_sql}
    """, params).fetchall()

    if not rows:
        return 0

    runtime_config = _resolve_embedding_runtime_config()
    started_at = time.monotonic()
    started_at_iso = _utc_now_iso()
    _write_embedding_progress(
        {
            "status": "running",
            "label": progress_label,
            "current": 0,
            "total": len(rows),
            "started_at": started_at_iso,
            "updated_at": started_at_iso,
            "runtime": asdict(runtime_config),
        }
    )
    if log_progress:
        log.info(
            "Embedding %d transcript entries with %s",
            len(rows),
            _progress_message(0, len(rows), started_at_monotonic=started_at),
        )

    # Process in batches
    total = 0
    for i in range(0, len(rows), batch_size):
        batch_started_at = time.monotonic()
        batch = rows[i:i + batch_size]
        ids = [r[0] for r in batch]
        texts = [r[1] for r in batch]

        embeddings = list(embed_batch(texts, batch_size=batch_size))
        entries = list(zip(ids, embeddings))
        store_embeddings(conn, entries)
        total += len(entries)

        if progress_callback:
            progress_callback(total, len(rows))
        progress = _progress_message(total, len(rows), started_at_monotonic=started_at)
        if log_progress:
            log.info("Embedding progress %s", progress)
        _write_embedding_progress(
            {
                "status": "running",
                "label": progress_label,
                "current": total,
                "total": len(rows),
                "started_at": started_at_iso,
                "updated_at": _utc_now_iso(),
                "progress": progress,
                "runtime": asdict(runtime_config),
            }
        )
        _sleep_for_cpu_reserve(time.monotonic() - batch_started_at, runtime_config)

    complete_state = {
        "status": "complete",
        "label": progress_label,
        "current": total,
        "total": len(rows),
        "started_at": started_at_iso,
        "updated_at": _utc_now_iso(),
        "progress": _progress_message(total, len(rows), started_at_monotonic=started_at),
        "runtime": asdict(runtime_config),
    }
    _write_embedding_progress(complete_state)
    if log_progress:
        log.info("Embedding complete: %s", complete_state["progress"])
    return total
