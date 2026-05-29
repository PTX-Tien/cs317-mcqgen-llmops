"""
tasks.py — Celery tasks cho MCQ generation pipeline
"""
import sys, json, asyncio, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = "redis://localhost:6379/0"
celery_app = Celery("mcqgen", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=3600,
)

@celery_app.task(bind=True)
def run_mcq_pipeline(self, topics: list, output_name: str = "exam", retrieval_mode: str = "auto"):
    """Celery task: chạy MCQ pipeline async, update progress."""
    total_questions = sum(int(t.get("n", 1)) for t in topics)

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
        )

    result = asyncio.run(_run())

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
