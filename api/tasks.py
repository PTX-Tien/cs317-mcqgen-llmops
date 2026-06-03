"""
tasks.py — Celery tasks cho MCQ generation pipeline
"""
import sys, json, asyncio, os
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from celery import Celery
from dotenv import load_dotenv
from sqlmodel import Session
from api.core.config import settings
from api.core.database import (
    engine,
    format_exam_display_name,
    get_user_question_history,
    persist_generation_failure,
    persist_generation_success,
)
from api.core.load_tracking import (
    finish_generation,
    mark_generation_running,
    touch_generation,
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
    session_id = trace_payload.get("session_id") or f"exam:{task_id}"
    runtime_snapshot = mark_generation_running(task_id)
    trace_payload.update(
        {
            "runtime_concurrent_users": runtime_snapshot.concurrent_users,
            "runtime_concurrent_traces": runtime_snapshot.concurrent_traces,
            "runtime_active_sessions": runtime_snapshot.active_sessions,
            "runtime_traffic_mode": runtime_snapshot.traffic_mode,
            "runtime_concurrency_bucket": runtime_snapshot.concurrency_bucket,
        }
    )
    if trace_payload.get("user_id") and "previous_questions" not in trace_payload:
        try:
            with Session(engine) as session:
                trace_payload["previous_questions"] = get_user_question_history(
                    session,
                    str(trace_payload["user_id"]),
                    limit=settings.MCQGEN_DEDUP_HISTORY_LIMIT,
                )
        except Exception as exc:
            print(f"[DEDUP_HISTORY_WARN] user={trace_payload.get('user_id')} error={exc!r}")
            trace_payload["previous_questions"] = []
    total_questions = sum(int(t.get("n", 1)) for t in topics)
    trace_metadata = {
        **trace_payload,
        "task_id": task_id,
        "session_id": session_id,
        "use_case": trace_payload.get("use_case") or "generate_exam",
        "output_name": output_name,
        "retrieval_mode": retrieval_mode,
        "n_questions": total_questions,
        "topic_count": len(topics),
        "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
        "resource_capacity_jobs": settings.MCQGEN_RESOURCE_MAX_RUNNING_JOBS,
        "celery_generation_concurrency": settings.CELERY_GENERATION_CONCURRENCY,
        "question_concurrency_per_job": settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
        "llm_concurrency_per_job": settings.MCQGEN_LLM_MAX_CONCURRENCY,
        "vllm_max_num_seqs": settings.VLLM_MAX_NUM_SEQS,
        "total_llm_slots": (
            settings.VLLM_MAX_NUM_SEQS
            if str(settings.MCQGEN_DYNAMIC_CONCURRENCY).strip().lower() in {"1", "true", "yes", "on"}
            else settings.CELERY_GENERATION_CONCURRENCY * settings.MCQGEN_MAX_CONCURRENT_QUESTIONS
        ),
        "global_slot_guard": settings.MCQGEN_GLOBAL_SLOT_GUARD,
        "global_llm_slots": settings.MCQGEN_GLOBAL_LLM_SLOTS,
        "celery_queue_high": settings.CELERY_QUEUE_HIGH,
        "celery_worker_namespace": settings.CELERY_WORKER_NAMESPACE,
    }

    def publish_progress(progress: int, step: str, **meta):
        touch_generation(task_id)
        payload = {
            "step": step,
            "progress": progress,
            "current_question": meta.pop("current_question", 0),
            "total_questions": meta.pop("total_questions", total_questions),
        }
        payload.update(meta)
        self.update_state(state="PROGRESS", meta=payload)

    resource_progress = {
        key: trace_metadata.get(key)
        for key in (
            "resource_status",
            "resource_message",
            "resource_queue_reason",
            "resource_capacity_jobs",
            "allocated_question_slots_at_start",
            "expected_question_slots_when_running",
            "resource_slots_total",
            "dynamic_concurrency",
            "runtime_concurrent_traces",
            "runtime_concurrent_users",
        )
        if trace_metadata.get(key) is not None
    }

    publish_progress(1, "Worker đã nhận job", current_question=0, **resource_progress)

    async def _run():
        publish_progress(5, "Đang nạp pipeline/RAG", current_question=0, **resource_progress)
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
            session_id=session_id,
            tags=trace_payload.get("langfuse_tags") or ["app:mcqgen", "usecase:generate_exam"],
            metadata=trace_metadata,
            trace_name="mcqgen.generate_exam",
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
                failures = result.get("failures", []) if isinstance(result, dict) else []
                failure_stage_counts = Counter(
                    failure.get("stage", "unknown")
                    for failure in failures
                    if isinstance(failure, dict)
                )
                acceptance_rate = accepted / max(accepted + failed, 1)
                update_langfuse_observation(
                    lf_span,
                    output={
                        "accepted": accepted,
                        "failed": failed,
                        "acceptance_rate": acceptance_rate,
                        "failure_stage_counts": dict(failure_stage_counts),
                        "output_file": result.get("output_file") if isinstance(result, dict) else None,
                    },
                    metadata={
                        **trace_metadata,
                        "accepted": accepted,
                        "failed": failed,
                        "acceptance_rate": acceptance_rate,
                        "failure_stage_counts": dict(failure_stage_counts),
                    },
                )
                score_langfuse_trace("accepted_questions", float(accepted))
                score_langfuse_trace("failed_questions", float(failed))
                score_langfuse_trace("acceptance_rate", float(acceptance_rate))
                for stage, count in failure_stage_counts.items():
                    score_langfuse_trace(f"reject_stage.{stage}", float(count))
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
        finish_generation(task_id)
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

    tracing = {
        "provider": "langfuse",
        "enabled": os.getenv("ENABLE_LANGFUSE", "0") == "1",
        "base_url": os.getenv("LANGFUSE_BASE_URL"),
    }
    if tracing["enabled"]:
        publish_progress(85, "Đang kiểm tra Langfuse")
        from urllib.request import urlopen

        base_url = (os.getenv("LANGFUSE_BASE_URL") or "http://localhost:8083").rstrip("/")
        health_url = f"{base_url}/api/public/health"
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
