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


@contextmanager
def langfuse_attributes(
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[None]:
    """Attach trace-level attributes for all child observations."""
    client = init_langfuse()
    if client is None or not hasattr(client, "propagate_attributes"):
        yield
        return

    kwargs = {
        "user_id": user_id,
        "session_id": session_id,
        "tags": tags,
        "metadata": metadata,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    with client.propagate_attributes(**kwargs):
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
        "input": input,
        "output": output,
        "metadata": metadata,
    }
    payload.update(kwargs)
    payload = {k: v for k, v in payload.items() if v is not None}
    with client.start_as_current_observation(**payload) as observation:
        yield observation


def update_langfuse_observation(observation: Any | None = None, **kwargs: Any) -> None:
    payload = {k: v for k, v in kwargs.items() if v is not None}
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


def flush_langfuse() -> None:
    client = init_langfuse()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:  # pragma: no cover - optional dependency path
        print(f"LangFuse flush skipped: {exc}", file=sys.stderr)
