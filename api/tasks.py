"""
tasks.py — Celery tasks cho MCQ generation pipeline
"""
import sys, json, asyncio, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from celery import Celery
from dotenv import load_dotenv
from sqlmodel import Session
from api.core.config import settings
from api.core.database import (
    engine,
    format_exam_display_name,
    persist_generation_failure,
    persist_generation_success,
)
from monitoring.langfuse_tracing import (
    flush_langfuse,
    langfuse_attributes,
    langfuse_observation,
    score_langfuse_trace,
    update_langfuse_observation,
)

load_dotenv()

celery_app = Celery("mcqgen", broker=settings.CELERY_BROKER, backend=settings.CELERY_BACKEND)
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Tracking & TTL
    task_track_started=True,
    result_expires=settings.TASK_RESULT_TTL,

    # Task routing — user-facing tasks → high-priority queue
    task_routes={
        "api.tasks.run_mcq_pipeline": {"queue": settings.CELERY_QUEUE_HIGH},
        "api.tasks.warmup_system":    {"queue": settings.CELERY_QUEUE_LOW},
    },

    # Time limits — tránh worker bị treo vô thời hạn
    # soft limit: gửi SoftTimeLimitExceeded exception cho task
    # hard limit: SIGKILL nếu task vẫn chạy sau đó
    task_soft_time_limit=30 * 60,   # 30 phút — cảnh báo
    task_time_limit=35 * 60,        # 35 phút — force kill

    # Worker prefetch — mỗi worker chỉ nhận 1 task (tránh worker chậm giữ nhiều task)
    worker_prefetch_multiplier=1,

    # Acknowledge sau khi task chạy xong (không phải khi nhận) → tránh mất task khi worker crash
    task_acks_late=True,

    # Cho phép worker tự huỷ task trùng
    task_reject_on_worker_lost=True,
)


def _persist_success(task_id: str, result: dict):
    try:
        with Session(engine) as session:
            persist_generation_success(session, task_id, result)
    except Exception as exc:
        print(f"[DB_PERSIST_ERROR] task_id={task_id} status=success error={exc!r}")


def _persist_failure(task_id: str, error: Exception):
    try:
        with Session(engine) as session:
            persist_generation_failure(session, task_id, str(error))
    except Exception as exc:
        print(f"[DB_PERSIST_ERROR] task_id={task_id} status=failed error={exc!r}")

@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,       # 60s trước khi retry lần 1
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,           # exponential backoff: 60s, 120s
    retry_backoff_max=300,        # tối đa 5 phút giữa các retry
    retry_jitter=True,            # thêm jitter tránh thundering herd
)
def run_mcq_pipeline(
    self,
    topics: list,
    output_name: str = "exam",
    retrieval_mode: str = "auto",
    trace_payload: dict | None = None,
):
    """Celery task: chạy MCQ pipeline async, update progress."""
    trace_payload = trace_payload or {}
    task_id = trace_payload.get("task_id") or self.request.id
    total_questions = sum(int(t.get("n", 1)) for t in topics)
    trace_metadata = {
        **trace_payload,
        "task_id": task_id,
        "output_name": output_name,
        "retrieval_mode": retrieval_mode,
        "n_questions": total_questions,
        "topic_count": len(topics),
    }

    def publish_progress(progress: int, step: str, **meta):
        payload = {
            "step": step,
            "progress": progress,
            "current_question": meta.pop("current_question", 0),
            "total_questions": meta.pop("total_questions", total_questions),
        }
        payload.update(meta)
        self.update_state(state="PROGRESS", meta=payload)

    publish_progress(1, "Worker đã nhận job", current_question=0)

    async def _run():
        publish_progress(5, "Đang nạp pipeline/RAG", current_question=0)
        from src.mcqgen.pipeline_mcq import run_pipeline_with_topics

        return await run_pipeline_with_topics(
            topics=topics,
            output_name=output_name,
            progress_callback=publish_progress,
            retrieval_mode=retrieval_mode,
            trace_payload=trace_metadata,
        )

    try:
        with langfuse_attributes(
            user_id=trace_payload.get("user_id"),
            session_id=task_id,
            tags=["mcqgen", "celery", "generation"],
            metadata=trace_metadata,
        ):
            with langfuse_observation(
                "celery.run_mcq_pipeline",
                as_type="span",
                input={"topics": topics, "output_name": output_name},
                metadata=trace_metadata,
            ) as lf_span:
                result = asyncio.run(_run())
                if isinstance(result, dict):
                    result.setdefault("output_name", output_name)
                    result["display_name"] = format_exam_display_name(
                        result.get("display_name") or trace_payload.get("exam_name") or output_name
                    )
                accepted = int(result.get("accepted", 0)) if isinstance(result, dict) else 0
                failed = int(result.get("failed", 0)) if isinstance(result, dict) else 0
                update_langfuse_observation(
                    lf_span,
                    output={
                        "accepted": accepted,
                        "failed": failed,
                        "output_file": result.get("output_file") if isinstance(result, dict) else None,
                    },
                    metadata={**trace_metadata, "accepted": accepted, "failed": failed},
                )
                score_langfuse_trace("accepted_questions", float(accepted))
                score_langfuse_trace("failed_questions", float(failed))
                if isinstance(result, dict):
                    _persist_success(task_id, result)
                    # Cache task_id để dedup các request giống nhau trong tương lai
                    if accepted > 0:
                        try:
                            from api.core.cache import set_cached_task_id
                            set_cached_task_id(topics, retrieval_mode, task_id)
                        except Exception as cache_exc:
                            print(f"[CACHE_SET_WARN] {cache_exc!r}")
    except Exception as exc:
        score_langfuse_trace("job_failed", 1.0, comment=str(exc))
        _persist_failure(task_id, exc)
        raise
    finally:
        flush_langfuse()

    publish_progress(100, "done", current_question=total_questions)
    return result


@celery_app.task(bind=True)
def warmup_system(self):
    """Warm RAG and vLLM inside the Celery worker process."""
    def publish_progress(progress: int, step: str, **meta):
        payload = {"step": step, "progress": progress}
        payload.update(meta)
        self.update_state(state="PROGRESS", meta=payload)

    publish_progress(5, "Worker đã nhận warmup job")

    publish_progress(20, "Đang warm RAG retriever")
    from src.mcqgen.advanced_retrieval import warmup_retriever
    rag_info = warmup_retriever()

    publish_progress(65, "Đang warm vLLM")

    async def _warm_vllm():
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=os.getenv("VLLM_URL", "http://localhost:8000/v1"),
            api_key="x",
        )
        response = await client.chat.completions.create(
            model=os.getenv("VLLM_MODEL", "mcqgen"),
            messages=[{"role": "user", "content": "Trả lời ngắn: OK"}],
            temperature=0.0,
            max_tokens=8,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        return response.choices[0].message.content.strip()

    vllm_reply = asyncio.run(_warm_vllm())

    tracing = {"enabled": os.getenv("ENABLE_TRACING", "0") == "1"}
    if tracing["enabled"]:
        publish_progress(85, "Đang kiểm tra Phoenix")
        from urllib.request import urlopen

        health_url = os.getenv("PHOENIX_HEALTH_URL", "http://localhost:6006/healthz")
        with urlopen(health_url, timeout=2.0) as response:
            tracing["healthy"] = response.status < 400
            tracing["health_status"] = response.status
    else:
        tracing["healthy"] = None

    publish_progress(100, "warmup_done")
    return {
        "type": "warmup",
        "ready": True,
        "rag": rag_info,
        "vllm": {"reply": vllm_reply},
        "tracing": tracing,
    }
