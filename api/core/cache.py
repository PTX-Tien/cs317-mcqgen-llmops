"""
api/core/cache.py — Redis-backed cache cho MCQGen.

Chiến lược:
  DB 2: cache kết quả generation (dedup identical requests)
  Key  : mcq:gen:v1:<sha256[:16] của (topics_canonical + mode)>
  Value: task_id của generation job đã thành công trước đó
  TTL  : CACHE_TTL_GENERATION (mặc định 7 ngày)

Ngoài ra cung cấp generic cache_get / cache_set để cache kết quả DB query.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import redis

from api.core.config import settings
from api.core.logger import log

# Lazy singleton — chỉ connect khi lần đầu dùng
_cache_client: Optional[redis.Redis] = None


def _client() -> redis.Redis:
    global _cache_client
    if _cache_client is None:
        _cache_client = redis.from_url(
            settings.REDIS_CACHE_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
        )
    return _cache_client


# ── Generation dedup ─────────────────────────────────────────────────────────

def _gen_cache_key(topics: list[dict], retrieval_mode: str) -> str:
    """Canonical hash key cho một generation request.

    Topics được sort theo topic_id+difficulty để đảm bảo thứ tự không ảnh hưởng hash.
    """
    canonical = {
        "topics": sorted(
            [
                {
                    "topic_id":   t.get("topic_id", ""),
                    "chapter_id": t.get("chapter_id", ""),
                    "topic":      t.get("topic", ""),
                    "difficulty": t.get("difficulty", "G2"),
                    "n":          int(t.get("n", 1)),
                }
                for t in topics
            ],
            key=lambda x: (x["topic_id"], x["difficulty"]),
        ),
        "mode": retrieval_mode.lower(),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return f"mcq:gen:v1:{digest}"


def get_cached_task_id(topics: list[dict], retrieval_mode: str) -> Optional[str]:
    """Trả về task_id đã cached nếu cùng config đã được generate thành công trước đó."""
    key = _gen_cache_key(topics, retrieval_mode)
    try:
        value = _client().get(key)
        if value:
            log.info("cache_hit_generation", key=key, task_id=value)
        return value
    except Exception as exc:
        log.warning("cache_get_failed", key=key, error=str(exc))
        return None


def set_cached_task_id(
    topics: list[dict],
    retrieval_mode: str,
    task_id: str,
    ttl: Optional[int] = None,
) -> None:
    """Lưu task_id vào cache sau khi generation thành công."""
    key = _gen_cache_key(topics, retrieval_mode)
    ttl = ttl if ttl is not None else settings.CACHE_TTL_GENERATION
    try:
        _client().setex(key, ttl, task_id)
        log.info("cache_set_generation", key=key, task_id=task_id, ttl=ttl)
    except Exception as exc:
        log.warning("cache_set_failed", key=key, error=str(exc))


def invalidate_generation_cache(topics: list[dict], retrieval_mode: str) -> bool:
    """Xoá cache entry (VD: khi user xoá exam khỏi history)."""
    key = _gen_cache_key(topics, retrieval_mode)
    try:
        deleted = bool(_client().delete(key))
        if deleted:
            log.info("cache_invalidated", key=key)
        return deleted
    except Exception as exc:
        log.warning("cache_invalidate_failed", key=key, error=str(exc))
        return False


# ── Generic key-value cache ──────────────────────────────────────────────────

def cache_get(key: str) -> Optional[Any]:
    """Lấy giá trị từ generic cache (trả về None nếu miss hoặc lỗi Redis)."""
    try:
        raw = _client().get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as exc:
        log.warning("cache_generic_get_failed", key=key, error=str(exc))
        return None


def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Lưu giá trị vào generic cache với TTL (giây)."""
    try:
        _client().setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
    except Exception as exc:
        log.warning("cache_generic_set_failed", key=key, error=str(exc))


def cache_delete(key: str) -> None:
    """Xoá một key khỏi generic cache."""
    try:
        _client().delete(key)
    except Exception as exc:
        log.warning("cache_generic_delete_failed", key=key, error=str(exc))


def cache_health() -> dict:
    """Kiểm tra trạng thái Redis cache — dùng cho /health endpoint."""
    try:
        _client().ping()
        return {"status": "ok", "url": settings.REDIS_CACHE_URL}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "url": settings.REDIS_CACHE_URL}
