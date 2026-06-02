"""Optional LangFuse tracing helpers for MCQGen.

The application must keep running when LangFuse is not installed or not
configured. All helpers below are no-ops unless ENABLE_LANGFUSE=1 and
LangFuse credentials are present.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator

_CLIENT: Any | None = None
_IMPORT_ERROR_REPORTED = False

TRUE_VALUES = {"1", "true", "yes", "on"}
PROPAGATED_METADATA_KEYS = {
    "task_id",
    "session_id",
    "output_name",
    "retrieval_mode",
    "n_questions",
    "topic_count",
    "user_role",
    "role",
    "use_case",
    "load_scenario",
    "concurrency_at_submit",
    "active_jobs_at_submit",
    "queued_jobs_at_submit",
    "queue_depth_at_submit",
    "target_concurrent_users",
    "celery_generation_concurrency",
    "question_concurrency_per_job",
    "llm_concurrency_per_job",
    "vllm_max_num_seqs",
    "total_llm_slots",
    "celery_queue_high",
    "celery_worker_namespace",
}


def _env_enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in TRUE_VALUES


def langfuse_enabled() -> bool:
    if not _env_enabled("ENABLE_LANGFUSE"):
        return False
    if os.getenv("LANGFUSE_TRACING_ENABLED", "true").strip().lower() == "false":
        return False
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def init_langfuse() -> Any | None:
    """Return a configured LangFuse client or None when tracing is disabled."""
    global _CLIENT, _IMPORT_ERROR_REPORTED
    if _CLIENT is not None:
        return _CLIENT
    if not langfuse_enabled():
        return None

    base_url = (
        os.getenv("LANGFUSE_BASE_URL")
        or os.getenv("LANGFUSE_HOST")
        or "http://localhost:3000"
    )
    os.environ.setdefault("LANGFUSE_BASE_URL", base_url)
    os.environ.setdefault("LANGFUSE_HOST", base_url)

    try:
        from langfuse import get_client

        _CLIENT = get_client()
        return _CLIENT
    except Exception as exc:  # pragma: no cover - optional dependency path
        if not _IMPORT_ERROR_REPORTED:
            print(f"LangFuse tracing disabled: {exc}", file=sys.stderr)
            _IMPORT_ERROR_REPORTED = True
        return None


def truncate_for_langfuse(value: Any, limit: int | None = None) -> Any:
    """Limit large prompt/context payloads before sending them to LangFuse."""
    if value is None:
        return None
    if limit is None:
        try:
            limit = int(os.getenv("LANGFUSE_MAX_IO_CHARS", "12000"))
        except ValueError:
            limit = 12000
    if not isinstance(value, str):
        return value
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return f"{value[:limit]}\n... [truncated {omitted} chars]"


def sanitize_for_langfuse(value: Any, limit: int | None = None, depth: int = 0) -> Any:
    """Recursively trim large payloads before sending them to LangFuse."""
    if depth > 4:
        return truncate_for_langfuse(str(value), limit)
    if isinstance(value, str):
        return truncate_for_langfuse(value, limit)
    if isinstance(value, dict):
        return {
            str(k): sanitize_for_langfuse(v, limit, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        items = list(value)
        trimmed = [sanitize_for_langfuse(v, limit, depth + 1) for v in items[:20]]
        if len(items) > 20:
            trimmed.append(f"... [truncated {len(items) - 20} items]")
        return trimmed
    return value


def usage_details_from_response(response: Any) -> dict[str, int] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None

    def read(name: str) -> int | None:
        if isinstance(usage, dict):
            value = usage.get(name)
        else:
            value = getattr(usage, name, None)
        return int(value) if value is not None else None

    prompt_tokens = read("prompt_tokens")
    completion_tokens = read("completion_tokens")
    total_tokens = read("total_tokens")
    details: dict[str, int] = {}
    if prompt_tokens is not None:
        details["input"] = prompt_tokens
    if completion_tokens is not None:
        details["output"] = completion_tokens
    if total_tokens is not None:
        details["total"] = total_tokens
    return details or None


def _to_propagated_attr(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) > 200:
        text = text[:200]
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        return None
    return text


def _propagated_metadata(metadata: dict[str, Any] | None) -> dict[str, str] | None:
    if not metadata:
        return None
    safe: dict[str, str] = {}
    for key in PROPAGATED_METADATA_KEYS:
        value = _to_propagated_attr(metadata.get(key))
        if value is not None:
            safe[key] = value
    return safe or None


@contextmanager
def langfuse_attributes(
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    trace_name: str | None = None,
) -> Iterator[None]:
    """Attach trace-level attributes for all child observations."""
    client = init_langfuse()
    if client is None:
        yield
        return

    kwargs = {
        "user_id": _to_propagated_attr(user_id),
        "session_id": _to_propagated_attr(session_id),
        "tags": tags,
        "metadata": _propagated_metadata(metadata),
        "trace_name": _to_propagated_attr(trace_name),
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        from langfuse import propagate_attributes

        with propagate_attributes(**kwargs):
            yield
    except Exception as exc:  # pragma: no cover - optional dependency path
        print(f"LangFuse attributes propagation skipped: {exc}", file=sys.stderr)
        yield


@contextmanager
def langfuse_observation(
    name: str,
    *,
    as_type: str = "span",
    input: Any | None = None,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Iterator[Any | None]:
    """Create a LangFuse observation when enabled, otherwise yield None."""
    client = init_langfuse()
    if client is None or not hasattr(client, "start_as_current_observation"):
        yield None
        return

    payload = {
        "name": name,
        "as_type": as_type,
        "input": sanitize_for_langfuse(input),
        "output": sanitize_for_langfuse(output),
        "metadata": sanitize_for_langfuse(metadata),
    }
    payload.update(kwargs)
    payload = {k: v for k, v in payload.items() if v is not None}
    with client.start_as_current_observation(**payload) as observation:
        yield observation


def update_langfuse_observation(observation: Any | None = None, **kwargs: Any) -> None:
    payload = {k: sanitize_for_langfuse(v) for k, v in kwargs.items() if v is not None}
    if not payload:
        return

    try:
        if observation is not None and hasattr(observation, "update"):
            observation.update(**payload)
            return
        client = init_langfuse()
        if client is not None and hasattr(client, "update_current_span"):
            client.update_current_span(**payload)
    except Exception as exc:  # pragma: no cover - optional dependency path
        print(f"LangFuse observation update skipped: {exc}", file=sys.stderr)


def score_langfuse_trace(name: str, value: float, comment: str | None = None) -> None:
    client = init_langfuse()
    if client is None:
        return
    try:
        client.score_current_trace(name=name, value=value, comment=comment)
    except Exception as exc:  # pragma: no cover - optional dependency path
        print(f"LangFuse score skipped: {exc}", file=sys.stderr)


def score_langfuse_observation(
    observation: Any | None,
    name: str,
    value: float,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        payload = {
            "name": name,
            "value": float(value),
            "comment": comment,
            "metadata": sanitize_for_langfuse(metadata),
            "data_type": "NUMERIC",
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        if observation is not None and hasattr(observation, "score"):
            observation.score(**payload)
            return
        client = init_langfuse()
        if client is not None and hasattr(client, "score_current_span"):
            client.score_current_span(**payload)
    except Exception as exc:  # pragma: no cover - optional dependency path
        print(f"LangFuse observation score skipped: {exc}", file=sys.stderr)


def flush_langfuse() -> None:
    client = init_langfuse()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:  # pragma: no cover - optional dependency path
        print(f"LangFuse flush skipped: {exc}", file=sys.stderr)
