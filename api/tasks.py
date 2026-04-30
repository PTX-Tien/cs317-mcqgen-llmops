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
    from pipeline_mcq import run_pipeline_with_topics

    self.update_state(state="PROGRESS", meta={
        "step": "🔍 Khởi tạo retrieval engine", "progress": 5
    })

    async def _run():
        return await run_pipeline_with_topics(
            topics=topics,
            output_name=output_name,
            progress_callback=lambda p, s: self.update_state(
                state="PROGRESS",
                meta={"step": s, "progress": p}
            )
        )

    result = asyncio.run(_run())

    self.update_state(state="PROGRESS", meta={"step": "done", "progress": 100})
    return result
