"""
Redis-backed active load tracking for generation jobs.

This is intentionally global state, not process memory. FastAPI and Celery run in
separate processes, and Redis lets us tag Langfuse traces with concurrency at the
moment a generation request starts.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import redis

from api.core.config import settings
from api.core.logger import log

_client_instance: Optional[redis.Redis] = None


def _client() -> redis.Redis:
    global _client_instance
    if _client_instance is None:
        _client_instance = redis.from_url(
            settings.REDIS_CACHE_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
        )
    return _client_instance


def _namespace() -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", settings.CELERY_QUEUE_NAMESPACE or "mcqgen")


def _active_key() -> str:
    return f"mcq:load:{_namespace()}:active"


def _job_key(task_id: str) -> str:
    return f"mcq:load:{_namespace()}:job:{task_id}"


def _now() -> float:
    return time.time()


def _ttl() -> int:
    return max(60, settings.MCQGEN_LOAD_TRACKING_TTL_SECONDS)


def concurrency_bucket(n: int) -> str:
    if n <= 1:
        return "1"
    if n <= 5:
        return "2-5"
    if n <= 10:
        return "6-10"
    if n <= 20:
        return "11-20"
    if n <= 50:
        return "21-50"
    return "50+"


def traffic_mode(concurrent_users: int) -> str:
    return "single-user" if concurrent_users <= 1 else "multi-user"


def _safe_tag_value(value: Any, default: str = "unknown") -> str:
    text = str(value or default).strip().lower()
    text = re.sub(r"[^a-z0-9_.:-]+", "-", text)
    text = text.strip("-")
    return text[:80] or default


@dataclass
class LoadSnapshot:
    concurrent_users: int = 1
    concurrent_traces: int = 1
    active_sessions: int = 1
    traffic_mode: str = "single-user"
    concurrency_bucket: str = "1"


def _cleanup_stale(client: redis.Redis) -> None:
    cutoff = _now() - _ttl()
    try:
        stale_ids = client.zrangebyscore(_active_key(), 0, cutoff)
        if stale_ids:
            pipe = client.pipeline()
            for task_id in stale_ids:
                pipe.delete(_job_key(task_id))
            pipe.zremrangebyscore(_active_key(), 0, cutoff)
            pipe.execute()
    except Exception as exc:
        log.warning("load_tracking_cleanup_failed", error=str(exc))


def _snapshot_from_records(records: list[dict[str, Any]]) -> LoadSnapshot:
    users = {str(r.get("user_id")) for r in records if r.get("user_id")}
    sessions = {str(r.get("session_id")) for r in records if r.get("session_id")}
    concurrent_users = max(1, len(users))
    concurrent_traces = max(1, len(records))
    active_sessions = max(1, len(sessions))
    bucket = concurrency_bucket(concurrent_users)
    return LoadSnapshot(
        concurrent_users=concurrent_users,
        concurrent_traces=concurrent_traces,
        active_sessions=active_sessions,
        traffic_mode=traffic_mode(concurrent_users),
        concurrency_bucket=bucket,
    )


def _read_records(client: redis.Redis, statuses: set[str] | None = None) -> list[dict[str, Any]]:
    task_ids = client.zrangebyscore(_active_key(), _now() - _ttl(), _now() + _ttl())
    if not task_ids:
        return []

    pipe = client.pipeline()
    for task_id in task_ids:
        pipe.get(_job_key(task_id))
    raw_records = pipe.execute()

    records: list[dict[str, Any]] = []
    missing_ids: list[str] = []
    for task_id, raw in zip(task_ids, raw_records):
        if not raw:
            missing_ids.append(task_id)
            continue
        try:
            record = json.loads(raw)
            if isinstance(record, dict):
                if statuses is None or str(record.get("status", "queued")) in statuses:
                    records.append(record)
        except json.JSONDecodeError:
            missing_ids.append(task_id)

    if missing_ids:
        client.zrem(_active_key(), *missing_ids)
    return records


def get_active_load_snapshot(statuses: set[str] | None = None) -> LoadSnapshot:
    try:
        client = _client()
        _cleanup_stale(client)
        records = _read_records(client, statuses=statuses)
        if not records:
            return LoadSnapshot()
        return _snapshot_from_records(records)
    except Exception as exc:
        log.warning("load_tracking_snapshot_failed", error=str(exc))
        return LoadSnapshot()


def register_generation_start(
    *,
    task_id: str,
    user_id: str,
    session_id: str,
    use_case: str,
    output_name: str,
) -> LoadSnapshot:
    record = {
        "task_id": task_id,
        "user_id": user_id,
        "session_id": session_id,
        "use_case": use_case,
        "output_name": output_name,
        "started_at": _now(),
        "server_instance": settings.SERVER_INSTANCE,
        "status": "queued",
    }
    try:
        client = _client()
        ttl = _ttl()
        pipe = client.pipeline()
        pipe.setex(_job_key(task_id), ttl, json.dumps(record, ensure_ascii=False))
        pipe.zadd(_active_key(), {task_id: _now()})
        pipe.expire(_active_key(), ttl)
        pipe.execute()
    except Exception as exc:
        log.warning("load_tracking_register_failed", task_id=task_id, error=str(exc))
    return get_active_load_snapshot()


def mark_generation_running(task_id: str) -> LoadSnapshot:
    try:
        client = _client()
        raw = client.get(_job_key(task_id))
        record = json.loads(raw) if raw else {"task_id": task_id}
        if not isinstance(record, dict):
            record = {"task_id": task_id}
        record["status"] = "running"
        record["running_at"] = _now()
        record.setdefault("server_instance", settings.SERVER_INSTANCE)
        ttl = _ttl()
        pipe = client.pipeline()
        pipe.setex(_job_key(task_id), ttl, json.dumps(record, ensure_ascii=False))
        pipe.zadd(_active_key(), {task_id: _now()})
        pipe.expire(_active_key(), ttl)
        pipe.execute()
    except Exception as exc:
        log.warning("load_tracking_mark_running_failed", task_id=task_id, error=str(exc))
    return get_active_load_snapshot(statuses={"running"})


def touch_generation(task_id: str) -> None:
    try:
        client = _client()
        if client.exists(_job_key(task_id)):
            pipe = client.pipeline()
            pipe.expire(_job_key(task_id), _ttl())
            pipe.zadd(_active_key(), {task_id: _now()})
            pipe.expire(_active_key(), _ttl())
            pipe.execute()
    except Exception as exc:
        log.warning("load_tracking_touch_failed", task_id=task_id, error=str(exc))


def finish_generation(task_id: str) -> None:
    try:
        client = _client()
        pipe = client.pipeline()
        pipe.delete(_job_key(task_id))
        pipe.zrem(_active_key(), task_id)
        pipe.execute()
    except Exception as exc:
        log.warning("load_tracking_finish_failed", task_id=task_id, error=str(exc))


def load_metadata(snapshot: LoadSnapshot, *, target_concurrency: int | None = None) -> dict[str, Any]:
    return {
        "concurrent_users_at_start": snapshot.concurrent_users,
        "concurrent_traces_at_start": snapshot.concurrent_traces,
        "active_sessions_at_start": snapshot.active_sessions,
        "traffic_mode": snapshot.traffic_mode,
        "concurrency_bucket": snapshot.concurrency_bucket,
        "load_test_id": settings.LOAD_TEST_ID or None,
        "target_concurrency": target_concurrency or settings.MCQGEN_TARGET_CONCURRENT_USERS,
        "server_instance": settings.SERVER_INSTANCE,
        "request_source": settings.REQUEST_SOURCE,
    }


def load_tags(
    *,
    use_case: str,
    snapshot: LoadSnapshot,
    run_type: str | None = None,
) -> list[str]:
    tags = [
        "app:mcqgen",
        f"env:{_safe_tag_value(settings.APP_ENV)}",
        f"usecase:{_safe_tag_value(use_case)}",
        f"traffic:{snapshot.traffic_mode}",
        f"ccu:{snapshot.concurrency_bucket}",
        f"run:{_safe_tag_value(run_type or settings.TRACE_RUN_TYPE)}",
    ]
    if settings.LOAD_TEST_ID:
        tags.append(f"loadtest:{_safe_tag_value(settings.LOAD_TEST_ID)}")
    return tags
