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

    # Redis
    CELERY_BROKER:  str = os.getenv("CELERY_BROKER", "redis://localhost:6379/0")
    CELERY_BACKEND: str = os.getenv("CELERY_BACKEND", "redis://localhost:6379/0")
    TASK_RESULT_TTL: int = int(os.getenv("TASK_RESULT_TTL_SECONDS", "86400"))

    # Rate limit
    RATE_LIMIT_TEACHER: str = os.getenv("RATE_LIMIT_TEACHER", "10/hour")
    RATE_LIMIT_STUDENT: str = os.getenv("RATE_LIMIT_STUDENT", "30/hour")

    # Pipeline concurrency
    MCQGEN_MAX_CONCURRENT_QUESTIONS: int = _env_int("MCQGEN_MAX_CONCURRENT_QUESTIONS", 4)
    MCQGEN_LLM_MAX_CONCURRENCY: int = _env_int(
        "MCQGEN_LLM_MAX_CONCURRENCY",
        MCQGEN_MAX_CONCURRENT_QUESTIONS,
    )

settings = Settings()
