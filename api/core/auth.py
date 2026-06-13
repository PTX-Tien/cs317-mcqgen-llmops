"""
api/core/auth.py — Authentication & Authorization

Roles:
  - "admin" : 1 account, quản lý/giám sát toàn bộ hệ thống
  - "user"  : đăng ký tự do, mỗi user có data hoàn toàn isolated

User store: SQLite (UserAccount model trong database.py)
  → persistent, không mất khi restart Redis, không cần Docker
"""
import uuid
from datetime import datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select

from api.core.config import settings

pwd_context   = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ── Helpers truy cập DB ───────────────────────────────────────────────────────

def _get_engine():
    from api.core.database import engine
    return engine


def _get_user_from_db(username: str, include_inactive: bool = False) -> dict | None:
    """Lấy user từ SQLite. Mặc định trả về None nếu không tồn tại hoặc bị inactive."""
    from api.core.database import UserAccount
    with Session(_get_engine()) as s:
        user = s.get(UserAccount, username)
        if user is None:
            return None
        if not include_inactive and not user.is_active:
            return None
        return {
            "username":        user.username,
            "hashed_password": user.hashed_password,
            "role":            user.role,
            "full_name":       user.full_name,
            "is_active":       user.is_active,
        }


def get_user(username: str) -> dict | None:
    """Public interface để lấy user info (không có hashed_password)."""
    user = _get_user_from_db(username)
    if user is None:
        return None
    return {k: v for k, v in user.items() if k != "hashed_password"}


# ── Registration ──────────────────────────────────────────────────────────────

class UsernameAlreadyExistsError(Exception):
    pass


def register_user(username: str, password: str, full_name: str = "") -> dict:
    """Đăng ký user mới. Raise UsernameAlreadyExistsError nếu username đã tồn tại."""
    from api.core.database import UserAccount
    if len(username.strip()) < 3:
        raise ValueError("Username phải có ít nhất 3 ký tự")
    if len(password) < 6:
        raise ValueError("Password phải có ít nhất 6 ký tự")

    with Session(_get_engine()) as s:
        existing = s.get(UserAccount, username)
        if existing is not None:
            raise UsernameAlreadyExistsError(f"Username '{username}' đã tồn tại")
        new_user = UserAccount(
            username=username.strip(),
            hashed_password=pwd_context.hash(password),
            role="user",
            full_name=full_name.strip() or username.strip(),
            is_active=True,
        )
        s.add(new_user)
        s.commit()
        s.refresh(new_user)
        return {
            "username":  new_user.username,
            "role":      new_user.role,
            "full_name": new_user.full_name,
        }


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_token(data: dict, expires_delta: timedelta) -> str:
    """Tạo JWT với JTI (JWT ID) để hỗ trợ token blacklisting khi logout."""
    now = datetime.utcnow()
    payload = {
        **data,
        "jti": str(uuid.uuid4()),
        "exp": now + expires_delta,
        "iat": now,
        "iss": "mcqgen",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": True},
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token không hợp lệ: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependencies ──────────────────────────────────────────────────────

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    payload = decode_token(token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Token không hợp lệ")

    # Kiểm tra token blacklist (logout) — fail-open nếu Redis không available
    jti = payload.get("jti")
    if jti:
        try:
            from api.core.session import is_token_blacklisted
            if is_token_blacklisted(jti):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token đã bị thu hồi. Vui lòng đăng nhập lại.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            raise
        except Exception:
            pass  # Redis không available → fail-open

    user = _get_user_from_db(username)
    if user is None:
        raise HTTPException(status_code=401, detail="Tài khoản không tồn tại hoặc đã bị khoá")

    return {
        "username":  user["username"],
        "role":      user["role"],
        "full_name": user["full_name"],
        "jti":       jti,
    }


def require_role(*roles: str):
    """FastAPI dependency: chỉ cho phép user có role trong danh sách."""
    async def _check(user: dict = Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Không có quyền thực hiện hành động này (yêu cầu role: {', '.join(roles)})",
            )
        return user
    return _check
