import os
from dotenv import load_dotenv
load_dotenv()

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

    # Redis
    CELERY_BROKER:  str = os.getenv("CELERY_BROKER", "redis://localhost:6379/0")
    CELERY_BACKEND: str = os.getenv("CELERY_BACKEND", "redis://localhost:6379/0")
    TASK_RESULT_TTL: int = int(os.getenv("TASK_RESULT_TTL_SECONDS", "86400"))

    # Rate limit
    RATE_LIMIT_TEACHER: str = os.getenv("RATE_LIMIT_TEACHER", "10/hour")
    RATE_LIMIT_STUDENT: str = os.getenv("RATE_LIMIT_STUDENT", "30/hour")

settings = Settings()
