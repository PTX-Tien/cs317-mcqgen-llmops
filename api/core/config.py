import os
from dotenv import load_dotenv
load_dotenv()

def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default

class Settings:
    # Auth
    JWT_SECRET:  str = os.getenv("JWT_SECRET", "change-this")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    REFRESH_TOKEN_EXPIRE_DAYS:   int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/mcqgen.db")

    # vLLM
    VLLM_URL:   str = os.getenv("VLLM_URL", "http://localhost:8000/v1")
    VLLM_MODEL: str = os.getenv("VLLM_MODEL", "mcqgen")
    VLLM_MAX_NUM_SEQS: int = _env_int("VLLM_MAX_NUM_SEQS", 4)

    # Redis — broker/backend dùng DB 0/1, cache DB 2, session DB 3
    REDIS_BASE_URL: str = os.getenv("REDIS_BASE_URL", "redis://localhost:6379")
    CELERY_BROKER:  str = os.getenv("CELERY_BROKER",  "redis://localhost:6379/0")
    CELERY_BACKEND: str = os.getenv("CELERY_BACKEND", "redis://localhost:6379/1")
    REDIS_CACHE_URL:   str = os.getenv("REDIS_CACHE_URL",   "redis://localhost:6379/2")
    REDIS_SESSION_URL: str = os.getenv("REDIS_SESSION_URL", "redis://localhost:6379/3")
    TASK_RESULT_TTL: int = int(os.getenv("TASK_RESULT_TTL_SECONDS", "86400"))

    # Admin account (auto-created on first startup)
    ADMIN_USERNAME:   str = os.getenv("ADMIN_USERNAME",   "admin")
    ADMIN_PASSWORD:   str = os.getenv("ADMIN_PASSWORD",   "admin2026")
    ADMIN_FULL_NAME:  str = os.getenv("ADMIN_FULL_NAME",  "Administrator")

    # Rate limit
    RATE_LIMIT_ADMIN: str = os.getenv("RATE_LIMIT_ADMIN", os.getenv("RATE_LIMIT_TEACHER", "50/hour"))
    RATE_LIMIT_USER:  str = os.getenv("RATE_LIMIT_USER",  os.getenv("RATE_LIMIT_STUDENT", "20/hour"))
    # Backward-compat aliases
    RATE_LIMIT_TEACHER: str = os.getenv("RATE_LIMIT_TEACHER", "50/hour")
    RATE_LIMIT_STUDENT: str = os.getenv("RATE_LIMIT_STUDENT", "20/hour")

    # Pipeline concurrency
    MCQGEN_TARGET_CONCURRENT_USERS: int = _env_int("MCQGEN_TARGET_CONCURRENT_USERS", 3)
    CELERY_GENERATION_CONCURRENCY: int = _env_int(
        "CELERY_GENERATION_CONCURRENCY",
        MCQGEN_TARGET_CONCURRENT_USERS,
    )
    MCQGEN_MAX_CONCURRENT_QUESTIONS: int = _env_int("MCQGEN_MAX_CONCURRENT_QUESTIONS", 4)
    MCQGEN_LLM_MAX_CONCURRENCY: int = _env_int(
        "MCQGEN_LLM_MAX_CONCURRENCY",
        MCQGEN_MAX_CONCURRENT_QUESTIONS,
    )
    MCQGEN_CONCURRENCY_AUTOTUNE: str = os.getenv("MCQGEN_CONCURRENCY_AUTOTUNE", "1")

    # Celery queues
    CELERY_WORKER_NAMESPACE: str = os.getenv("CELERY_WORKER_NAMESPACE") or os.getenv("USER", "mcqgen")
    CELERY_QUEUE_NAMESPACE: str = os.getenv("CELERY_QUEUE_NAMESPACE") or CELERY_WORKER_NAMESPACE
    CELERY_QUEUE_HIGH: str = os.getenv("CELERY_QUEUE_HIGH", f"mcq.{CELERY_QUEUE_NAMESPACE}.high")
    CELERY_QUEUE_LOW:  str = os.getenv("CELERY_QUEUE_LOW",  f"mcq.{CELERY_QUEUE_NAMESPACE}.low")

    # Cache TTLs (seconds)
    CACHE_TTL_GENERATION: int = _env_int("CACHE_TTL_GENERATION", 7 * 86400)   # 7 ngày
    CACHE_TTL_DB_QUERY:   int = _env_int("CACHE_TTL_DB_QUERY",   300)          # 5 phút

    # Session TTLs (seconds)
    SESSION_CONTEXT_TTL: int = _env_int("SESSION_CONTEXT_TTL", 7 * 86400)     # 7 ngày

settings = Settings()
