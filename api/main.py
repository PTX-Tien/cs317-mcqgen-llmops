"""
main.py — FastAPI server cho MCQGen system
Chạy: uvicorn api.main:app --host 0.0.0.0 --port 7860 --reload
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from celery.result import AsyncResult
from api.tasks import celery_app, run_mcq_pipeline

app = FastAPI(title="MCQGen API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# ── Schema ─────────────────────────────────────────────────────────
class TopicConfig(BaseModel):
    topic_id: str
    chapter_id: str
    topic: str
    difficulty: str = "G2"
    n: int = 3

class GenerateRequest(BaseModel):
    topics: List[TopicConfig]
    output_name: str = "exam"

# ── Endpoints ──────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "MCQGen API"}

@app.post("/generate")
def generate(req: GenerateRequest):
    """Submit MCQ generation job → trả về task_id ngay."""
    topics = [t.model_dump() for t in req.topics]
    task = run_mcq_pipeline.delay(topics, req.output_name)
    return {
        "task_id": task.id,
        "status": "queued",
        "message": f"Generating {sum(t['n'] for t in topics)} MCQs"
    }

@app.get("/status/{task_id}")
def get_status(task_id: str):
    """Poll trạng thái job."""
    result = AsyncResult(task_id, app=celery_app)
    if result.state == "PENDING":
        return {"task_id": task_id, "state": "pending", "progress": 0}
    elif result.state == "PROGRESS":
        meta = result.info or {}
        return {
            "task_id": task_id,
            "state": "running",
            "progress": meta.get("progress", 0),
            "step": meta.get("step", "")
        }
    elif result.state == "SUCCESS":
        data = result.result or {}
        return {
            "task_id": task_id,
            "state": "success",
            "progress": 100,
            "accepted": data.get("accepted", 0),
            "failed": data.get("failed", 0),
        }
    elif result.state == "FAILURE":
        return {"task_id": task_id, "state": "failed", "error": str(result.info)}
    return {"task_id": task_id, "state": result.state}

@app.get("/results/{task_id}")
def get_results(task_id: str):
    """Lấy MCQs sau khi job SUCCESS."""
    result = AsyncResult(task_id, app=celery_app)
    if result.state != "SUCCESS":
        raise HTTPException(400, f"Job not done yet: {result.state}")
    data = result.result or {}
    return {
        "task_id": task_id,
        "accepted": data.get("accepted", 0),
        "mcqs": data.get("mcqs", []),
    }

@app.get("/")
def root():
    return {
        "service": "MCQGen API",
        "endpoints": {
            "POST /generate": "Submit job",
            "GET /status/{task_id}": "Poll status",
            "GET /results/{task_id}": "Get MCQs",
            "GET /health": "Health check",
        }
    }
