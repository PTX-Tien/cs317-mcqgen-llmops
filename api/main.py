"""
api/main.py — MCQGen FastAPI server (Production-grade)
"""
import asyncio, json, math, os, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import List, Optional
from datetime import timedelta
from celery.result import AsyncResult
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator
from sqlmodel import Session, select

from api.tasks import celery_app, run_mcq_pipeline, warmup_system
from api.core.config import settings
from api.core.logger import setup_logging, log, CorrelationIDMiddleware
from api.core.auth import (
    get_users_db, pwd_context, create_token, get_current_user,
    require_role, oauth2_scheme
)
from api.core.database import init_db, get_session, Exam, Question, QuizAttempt
from api.pdf_exporter import export_exam_pdf
from monitoring.langfuse_tracing import (
    flush_langfuse,
    langfuse_attributes,
    langfuse_observation,
    update_langfuse_observation,
)

# ── Setup ────────────────────────────────────────────────────────
setup_logging()
init_db()

# Rate limiter — theo user_id nếu có token, fallback IP
def get_user_key(request: Request) -> str:
    try:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            from api.core.auth import decode_token
            payload = decode_token(auth[7:])
            return payload.get("sub", get_remote_address(request))
    except Exception:
        pass
    return get_remote_address(request)

limiter = Limiter(key_func=get_user_key)
app     = FastAPI(title="MCQGen API", version="2.0", docs_url="/docs")

# ── Middleware ────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(
    app,
    endpoint="/metrics",
    include_in_schema=False,
)

# ── Schemas ───────────────────────────────────────────────────────
class TopicConfig(BaseModel):
    topic_id:   str
    chapter_id: str
    topic:      str
    difficulty: str = "G2"
    n:          int = 3

class GenerateRequest(BaseModel):
    topics:      List[TopicConfig]
    output_name: str = "exam"
    retrieval_mode: str = "auto"

class LoginResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int
    role:          str
    full_name:     str

GENERATION_MIN_PER_QUESTION_BY_MODE = {
    "fast": 7,
    "auto": 8,
    "quality": 10,
}
QUEUE_MIN_PER_JOB = 10

def estimate_generation_minutes(n_questions: int, retrieval_mode: str = "auto") -> int:
    minutes_per_question = GENERATION_MIN_PER_QUESTION_BY_MODE.get(retrieval_mode, 8)
    effective_concurrency = max(
        1,
        min(
            settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
            settings.MCQGEN_LLM_MAX_CONCURRENCY,
            settings.VLLM_MAX_NUM_SEQS,
        ),
    )
    runtime = max(1, math.ceil((n_questions * minutes_per_question) / effective_concurrency))
    return runtime

def _count_inspected_tasks(tasks_by_worker) -> int:
    return sum(len(tasks) for tasks in (tasks_by_worker or {}).values())

def get_queue_snapshot() -> dict:
    """Return Celery queue load before submitting a new task."""
    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        scheduled = inspector.scheduled() or {}
    except Exception as exc:
        log.warning("queue_inspect_failed", error=str(exc))
        return {
            "active_jobs": 0,
            "reserved_jobs": 0,
            "scheduled_jobs": 0,
            "queued_jobs": 0,
            "total_jobs": 0,
            "inspect_ok": False,
        }

    active_jobs = _count_inspected_tasks(active)
    reserved_jobs = _count_inspected_tasks(reserved)
    scheduled_jobs = _count_inspected_tasks(scheduled)
    queued_jobs = reserved_jobs + scheduled_jobs
    total_jobs = active_jobs + queued_jobs
    return {
        "active_jobs": active_jobs,
        "reserved_jobs": reserved_jobs,
        "scheduled_jobs": scheduled_jobs,
        "queued_jobs": queued_jobs,
        "total_jobs": total_jobs,
        "inspect_ok": True,
    }

# ── Auth endpoints ────────────────────────────────────────────────
@app.post("/auth/login", response_model=LoginResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = get_users_db().get(form_data.username)
    if not user or not pwd_context.verify(form_data.password, user["hashed_password"]):
        log.warning("login_failed", username=form_data.username)
        raise HTTPException(status_code=401, detail="Sai username hoặc password")

    access_token = create_token(
        {"sub": user["username"], "role": user["role"]},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_token(
        {"sub": user["username"], "type": "refresh"},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    log.info("login_success", username=user["username"], role=user["role"])
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        role=user["role"],
        full_name=user["full_name"],
    )

@app.get("/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "role": user["role"], "full_name": user["full_name"]}

# ── Health ────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0", "service": "MCQGen API"}

@app.get("/queue/status")
def queue_status(user: dict = Depends(get_current_user)):
    queue = get_queue_snapshot()
    depth = queue["total_jobs"]
    return {
        "pending_jobs":       depth,
        "active_jobs":        queue["active_jobs"],
        "queued_jobs":        queue["queued_jobs"],
        "reserved_jobs":      queue["reserved_jobs"],
        "scheduled_jobs":     queue["scheduled_jobs"],
        "estimated_wait_min": depth * QUEUE_MIN_PER_JOB,
        "status":             "busy" if depth > 0 else "idle",
        "inspect_ok":         queue["inspect_ok"],
        "generation_concurrency": settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
        "llm_concurrency": settings.MCQGEN_LLM_MAX_CONCURRENCY,
        "vllm_max_num_seqs": settings.VLLM_MAX_NUM_SEQS,
    }

@app.post("/admin/warmup")
def admin_warmup(user: dict = Depends(require_role("teacher"))):
    task = warmup_system.delay()
    log.info("warmup_submitted", task_id=task.id, user=user["username"])
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Warming RAG retriever and vLLM inside Celery worker",
    }

# ── Generation ────────────────────────────────────────────────────
@app.post("/generate")
@limiter.limit(settings.RATE_LIMIT_TEACHER)
def generate(
    request: Request,
    req: GenerateRequest,
    user: dict = Depends(require_role("teacher")),
    session: Session = Depends(get_session),
):
    topics = [t.model_dump() for t in req.topics]
    n_q    = sum(t["n"] for t in topics)
    retrieval_mode = req.retrieval_mode.lower()
    if retrieval_mode not in {"fast", "auto", "quality"}:
        raise HTTPException(status_code=422, detail="retrieval_mode must be fast, auto, or quality")

    task_id = str(uuid.uuid4())
    trace_payload = {
        "task_id": task_id,
        "user_id": user["username"],
        "role": user.get("role"),
        "exam_name": req.output_name,
        "n_questions": n_q,
        "topic_count": len(topics),
        "retrieval_mode": retrieval_mode,
        "topics": topics,
    }

    with langfuse_attributes(
        user_id=user["username"],
        session_id=task_id,
        tags=["mcqgen", "api", "generate"],
        metadata=trace_payload,
    ):
        with langfuse_observation(
            "api.generate.submit",
            as_type="span",
            input={
                "output_name": req.output_name,
                "retrieval_mode": retrieval_mode,
                "topics": topics,
            },
            metadata=trace_payload,
        ) as lf_span:
            queue = get_queue_snapshot()
            jobs_ahead = queue["total_jobs"]

            estimated_runtime_min = estimate_generation_minutes(n_q, retrieval_mode)
            queue_wait_min = jobs_ahead * QUEUE_MIN_PER_JOB
            estimated_total_min = estimated_runtime_min + queue_wait_min
            task = run_mcq_pipeline.apply_async(
                args=[topics, req.output_name, retrieval_mode, trace_payload],
                task_id=task_id,
            )

            update_langfuse_observation(
                lf_span,
                output={
                    "task_id": task.id,
                    "queue_position": jobs_ahead + 1,
                    "active_jobs": queue["active_jobs"],
                    "queued_jobs": queue["queued_jobs"],
                    "estimated_total_min": estimated_total_min,
                },
                metadata={
                    **trace_payload,
                    "queue_depth": jobs_ahead,
                    "active_jobs": queue["active_jobs"],
                    "queued_jobs": queue["queued_jobs"],
                },
            )
            flush_langfuse()

            # Save to DB
            exam = Exam(
                task_id=task.id,
                created_by=user["username"],
                exam_name=req.output_name,
                n_questions=n_q,
                status="pending",
            )
            session.add(exam)
            session.commit()

    log.info("job_submitted",
        task_id=task.id,
        user=user["username"],
        n_questions=n_q,
        retrieval_mode=retrieval_mode,
        queue_depth=jobs_ahead,
        active_jobs=queue["active_jobs"],
        queued_jobs=queue["queued_jobs"],
    )
    return {
        "task_id":            task.id,
        "status":             "queued",
        "queue_position":     jobs_ahead + 1,
        "jobs_ahead":         jobs_ahead,
        "active_jobs":        queue["active_jobs"],
        "queued_jobs":        queue["queued_jobs"],
        "estimated_wait_min": estimated_total_min,
        "estimated_total_min": estimated_total_min,
        "estimated_runtime_min": estimated_runtime_min,
        "queue_wait_min":     queue_wait_min,
        "n_questions":        n_q,
        "retrieval_mode":     retrieval_mode,
        "generation_concurrency": settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
        "llm_concurrency":    settings.MCQGEN_LLM_MAX_CONCURRENCY,
        "vllm_max_num_seqs":  settings.VLLM_MAX_NUM_SEQS,
        "message":            f"Generating {n_q} MCQs — estimated ~{estimated_total_min} min",
    }

@app.get("/status/{task_id}")
def get_status(task_id: str, user: dict = Depends(get_current_user)):
    result = AsyncResult(task_id, app=celery_app)
    if result.state == "PENDING":
        return {"task_id": task_id, "state": "pending", "progress": 0}
    elif result.state == "STARTED":
        return {
            "task_id": task_id,
            "state": "running",
            "progress": 1,
            "step": "Worker đã nhận job",
            "current_question": 0,
            "total_questions": 0,
        }
    elif result.state == "PROGRESS":
        meta = result.info or {}
        return {
            "task_id":          task_id,
            "state":            "running",
            "progress":         meta.get("progress", 0),
            "step":             meta.get("step", ""),
            "current_question": meta.get("current_question", 0),
            "total_questions":  meta.get("total_questions", 0),
            "question_concurrency": meta.get("question_concurrency", settings.MCQGEN_MAX_CONCURRENT_QUESTIONS),
            "llm_concurrency":      meta.get("llm_concurrency", settings.MCQGEN_LLM_MAX_CONCURRENCY),
            "vllm_max_num_seqs":    settings.VLLM_MAX_NUM_SEQS,
        }
    elif result.state == "SUCCESS":
        data = result.result or {}
        payload = {
            "task_id":  task_id,
            "state":    "success",
            "progress": 100,
            "accepted": data.get("accepted", 0),
            "failed":   data.get("failed", 0),
            "question_concurrency": data.get("question_concurrency", settings.MCQGEN_MAX_CONCURRENT_QUESTIONS),
            "llm_concurrency":      data.get("llm_concurrency", settings.MCQGEN_LLM_MAX_CONCURRENCY),
            "vllm_max_num_seqs":    settings.VLLM_MAX_NUM_SEQS,
        }
        if data.get("type") == "warmup":
            payload.update({
                "type": "warmup",
                "ready": data.get("ready", False),
                "details": data,
            })
        return payload
    elif result.state == "FAILURE":
        return {"task_id": task_id, "state": "failed", "error": str(result.info)}
    return {"task_id": task_id, "state": result.state}

@app.get("/results/{task_id}")
def get_results(
    task_id: str,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    result = AsyncResult(task_id, app=celery_app)
    if result.state != "SUCCESS":
        raise HTTPException(400, f"Job not done: {result.state}")
    data = result.result or {}
    mcqs = data.get("mcqs", [])

    # Save questions to DB
    exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
    if exam and exam.status == "pending":
        for mcq in mcqs:
            q = Question(
                exam_id=exam.id,
                question_id=mcq.get("question_id", ""),
                question_text=mcq.get("question_text", ""),
                options_json=json.dumps(mcq.get("options", {}), ensure_ascii=False),
                correct_answers_json=json.dumps(mcq.get("correct_answers", []), ensure_ascii=False),
                topic=mcq.get("topic", ""),
                difficulty=mcq.get("difficulty_label", "G2"),
                quality_score=mcq.get("evaluation", {}).get("quality_score", 0),
                rag_strategy=mcq.get("rag_strategy", ""),
                chapter_id=mcq.get("chapter_id", ""),
            )
            session.add(q)
        exam.status = "success"
        exam.n_questions = len(mcqs)
        from datetime import datetime
        exam.completed_at = datetime.utcnow()
        exam.quality_avg = sum(m.get("evaluation",{}).get("quality_score",0) for m in mcqs) / len(mcqs) if mcqs else 0
        session.commit()

    return {
        "task_id": task_id,
        "accepted": len(mcqs),
        "mcqs": mcqs,
        "question_concurrency": data.get("question_concurrency", settings.MCQGEN_MAX_CONCURRENT_QUESTIONS),
        "llm_concurrency": data.get("llm_concurrency", settings.MCQGEN_LLM_MAX_CONCURRENCY),
        "vllm_max_num_seqs": settings.VLLM_MAX_NUM_SEQS,
    }

@app.delete("/cancel/{task_id}")
def cancel_job(task_id: str, user: dict = Depends(get_current_user)):
    result = AsyncResult(task_id, app=celery_app)
    if result.state in ("PENDING", "PROGRESS"):
        result.revoke(terminate=True, signal="SIGTERM")
        log.info("job_cancelled", task_id=task_id, user=user["username"])
        return {"task_id": task_id, "cancelled": True}
    return {"task_id": task_id, "cancelled": False, "reason": f"Job already {result.state}"}

# ── History ───────────────────────────────────────────────────────
@app.get("/history")
def get_history(
    user: dict = Depends(require_role("teacher")),
    session: Session = Depends(get_session),
):
    exams = session.exec(
        select(Exam).where(Exam.created_by == user["username"])
        .order_by(Exam.created_at.desc()).limit(20)
    ).all()
    return {"exams": [e.model_dump() for e in exams]}

# ── Export PDF ────────────────────────────────────────────────────
@app.get("/export/pdf/{task_id}")
def export_pdf(
    task_id: str,
    include_answers: bool = False,
    user: dict = Depends(get_current_user),
):
    result = AsyncResult(task_id, app=celery_app)
    if result.state != "SUCCESS":
        raise HTTPException(400, f"Job not done: {result.state}")
    data = result.result or {}
    mcqs = data.get("mcqs", [])
    if not mcqs:
        raise HTTPException(404, "No MCQs found")

    pdf_bytes = export_exam_pdf(
        mcqs,
        exam_name=data.get("output_name", "ĐỀ KIỂM TRA CS116").upper(),
        include_answer_key=include_answers,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=exam_{task_id[:8]}.pdf"}
    )

# ── WebSocket progress ────────────────────────────────────────────
@app.websocket("/ws/{task_id}")
async def ws_progress(websocket: WebSocket, task_id: str):
    await websocket.accept()
    try:
        while True:
            result = AsyncResult(task_id, app=celery_app)
            if result.state == "PENDING":
                await websocket.send_json({"state": "pending", "progress": 0})
            elif result.state == "STARTED":
                await websocket.send_json({
                    "state":            "running",
                    "progress":         1,
                    "step":             "Worker đã nhận job",
                    "current_question": 0,
                    "total_questions":  0,
                })
            elif result.state == "PROGRESS":
                meta = result.info or {}
                await websocket.send_json({
                    "state":            "running",
                    "progress":         meta.get("progress", 0),
                    "step":             meta.get("step", ""),
                    "current_question": meta.get("current_question", 0),
                    "total_questions":  meta.get("total_questions", 0),
                    "question_concurrency": meta.get("question_concurrency", settings.MCQGEN_MAX_CONCURRENT_QUESTIONS),
                    "llm_concurrency":      meta.get("llm_concurrency", settings.MCQGEN_LLM_MAX_CONCURRENCY),
                    "vllm_max_num_seqs":    settings.VLLM_MAX_NUM_SEQS,
                })
            elif result.state == "SUCCESS":
                data = result.result or {}
                await websocket.send_json({
                    "state":    "success",
                    "progress": 100,
                    "accepted": data.get("accepted", 0),
                    "question_concurrency": data.get("question_concurrency", settings.MCQGEN_MAX_CONCURRENT_QUESTIONS),
                    "llm_concurrency":      data.get("llm_concurrency", settings.MCQGEN_LLM_MAX_CONCURRENCY),
                    "vllm_max_num_seqs":    settings.VLLM_MAX_NUM_SEQS,
                })
                break
            elif result.state == "FAILURE":
                await websocket.send_json({"state": "failed", "error": str(result.info)})
                break
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        log.info("websocket_disconnected", task_id=task_id)
