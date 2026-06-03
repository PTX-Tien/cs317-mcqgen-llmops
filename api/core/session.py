"""
api/core/session.py — Redis-backed session management.

3 concerns được xử lý ở đây:
  1. Token blacklist  — logout invalidates token trước khi hết hạn
  2. Active sessions  — tracking tất cả JTI đang hoạt động của 1 user
                        → cho phép "logout everywhere" (force-expire toàn bộ)
  3. User context     — lưu lịch sử tương tác LLM per-user (conversation window)
                        → foundation để sau này xây multi-turn chat

Redis DB 3 được dùng riêng cho session, tách khỏi Celery (DB 0/1) và cache (DB 2).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import redis

from api.core.config import settings
from api.core.logger import log

_session_client: Optional[redis.Redis] = None


def _client() -> redis.Redis:
    global _session_client
    if _session_client is None:
        _session_client = redis.from_url(
            settings.REDIS_SESSION_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
        )
    return _session_client


# ── Token blacklist ───────────────────────────────────────────────────────────

def blacklist_token(jti: str, exp: datetime) -> None:
    """Đưa một JWT JTI vào blacklist cho đến khi token hết hạn tự nhiên.

    Sau khi token hết hạn, Redis tự xoá key (TTL-based) → không tốn bộ nhớ vô hạn.
    """
    remaining_seconds = max(0, int((exp - datetime.utcnow()).total_seconds()))
    if remaining_seconds <= 0:
        return  # token đã hết hạn rồi, không cần blacklist
    try:
        _client().setex(f"mcq:blacklist:{jti}", remaining_seconds, "1")
        log.info("token_blacklisted", jti=jti, ttl=remaining_seconds)
    except Exception as exc:
        log.warning("blacklist_set_failed", jti=jti, error=str(exc))


def is_token_blacklisted(jti: str) -> bool:
    """Kiểm tra xem JTI đã bị blacklist chưa.

    Fail-open: nếu Redis lỗi, cho phép đi qua (ưu tiên availability).
    """
    try:
        return bool(_client().exists(f"mcq:blacklist:{jti}"))
    except Exception as exc:
        log.warning("blacklist_check_failed", jti=jti, error=str(exc))
        return False


# ── Active session tracking ───────────────────────────────────────────────────

def register_session(username: str, jti: str) -> None:
    """Đăng ký một JWT mới vào tập active sessions của user."""
    key = f"mcq:sessions:{username}"
    try:
        client = _client()
        client.sadd(key, jti)
        # TTL của set = thời gian sống của access token + buffer nhỏ
        client.expire(key, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60 + 120)
    except Exception as exc:
        log.warning("session_register_failed", username=username, error=str(exc))


def get_active_sessions(username: str) -> list[str]:
    """Lấy danh sách JTI đang active của user."""
    try:
        return list(_client().smembers(f"mcq:sessions:{username}"))
    except Exception as exc:
        log.warning("session_list_failed", username=username, error=str(exc))
        return []


def invalidate_user_sessions(username: str) -> int:
    """Blacklist tất cả session của user (force-logout everywhere).

    Trả về số session đã invalidate.
    """
    jtis = get_active_sessions(username)
    count = 0
    try:
        client = _client()
        pipe = client.pipeline()
        blacklist_ttl = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        for jti in jtis:
            pipe.setex(f"mcq:blacklist:{jti}", blacklist_ttl, "1")
            count += 1
        pipe.delete(f"mcq:sessions:{username}")
        pipe.execute()
        log.info("sessions_invalidated", username=username, count=count)
    except Exception as exc:
        log.warning("session_invalidate_failed", username=username, error=str(exc))
    return count


# ── User conversation context ─────────────────────────────────────────────────

_CONTEXT_MAX_TURNS = 20  # Giữ tối đa 20 turns để tránh context quá dài


def get_user_context(username: str) -> list[dict]:
    """Lấy conversation context của user (dùng để build multi-turn LLM prompt)."""
    try:
        raw = _client().get(f"mcq:context:{username}")
        return json.loads(raw) if raw else []
    except Exception as exc:
        log.warning("context_get_failed", username=username, error=str(exc))
        return []


def append_user_context(username: str, role: str, content: str) -> None:
    """Thêm một turn mới vào context của user, tự cắt nếu vượt quá max turns."""
    context = get_user_context(username)
    context.append({
        "role": role,
        "content": content,
        "ts": datetime.utcnow().isoformat(),
    })
    if len(context) > _CONTEXT_MAX_TURNS:
        context = context[-_CONTEXT_MAX_TURNS:]
    _save_user_context(username, context)


def clear_user_context(username: str) -> None:
    """Xoá toàn bộ context của user (reset conversation)."""
    try:
        _client().delete(f"mcq:context:{username}")
    except Exception as exc:
        log.warning("context_clear_failed", username=username, error=str(exc))


def _save_user_context(username: str, context: list[dict]) -> None:
    try:
        _client().setex(
            f"mcq:context:{username}",
            settings.SESSION_CONTEXT_TTL,
            json.dumps(context, ensure_ascii=False, default=str),
        )
    except Exception as exc:
        log.warning("context_save_failed", username=username, error=str(exc))


def session_health() -> dict:
    """Kiểm tra trạng thái Redis session — dùng cho /health endpoint."""
    try:
        _client().ping()
        return {"status": "ok", "url": settings.REDIS_SESSION_URL}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "url": settings.REDIS_SESSION_URL}
