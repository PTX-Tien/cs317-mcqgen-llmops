"""
tasks.py — Celery tasks cho MCQ generation pipeline
"""
import sys, json, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from celery import Celery

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
def run_mcq_pipeline(self, topics: list, output_name: str = "exam"):
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
        from pipeline_mcq import run_pipeline_with_topics

        return await run_pipeline_with_topics(
            topics=topics,
            output_name=output_name,
            progress_callback=publish_progress,
        )

    result = asyncio.run(_run())

    publish_progress(100, "done", current_question=total_questions)
    return result
