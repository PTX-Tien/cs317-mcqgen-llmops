from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from api.core.config import settings

pwd_context   = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# User store — production: thay bằng database
# Hash passwords lazy để tránh lỗi lúc import
_RAW_USERS = {
    "giaovien": {"password": "gv2026", "role": "teacher", "full_name": "Giảng viên CS116"},
    "sinhvien": {"password": "sv2026", "role": "student",  "full_name": "Sinh viên CS116"},
}

def _build_users_db():
    return {
        username: {
            "username":       username,
            "hashed_password": pwd_context.hash(info["password"]),
            "role":           info["role"],
            "full_name":      info["full_name"],
        }
        for username, info in _RAW_USERS.items()
    }

_users_cache = None
def get_users_db() -> dict:
    global _users_cache
    if _users_cache is None:
        _users_cache = _build_users_db()
    return _users_cache

# Backward compat
@property
def USERS_DB_prop():
    return get_users_db()

USERS_DB = None  # Will be initialized on first use

def create_token(data: dict, expires_delta: timedelta) -> str:
    payload = {
        **data,
        "exp": datetime.utcnow() + expires_delta,
        "iat": datetime.utcnow(),
        "iss": "mcqgen-cs116",
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
            detail=f"Token invalid: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    username = payload.get("sub")
    if not username or username not in get_users_db():
        raise HTTPException(status_code=401, detail="User not found")
    return get_users_db()[username]

def require_role(*roles: str):
    async def check(user: dict = Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user['role']}' không có quyền thực hiện hành động này"
            )
        return user
    return check
