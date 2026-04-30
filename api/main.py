"""
api/main.py — MCQGen FastAPI server (Production-grade)
"""
import asyncio, json, os, sys
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
from sqlmodel import Session, select

from api.tasks import celery_app, run_mcq_pipeline
from api.core.config import settings
from api.core.logger import setup_logging, log, CorrelationIDMiddleware
from api.core.auth import (
    get_users_db, pwd_context, create_token, get_current_user,
    require_role, oauth2_scheme
)
from api.core.database import init_db, get_session, Exam, Question, QuizAttempt
from api.pdf_exporter import export_exam_pdf

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

class LoginResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int
    role:          str
    full_name:     str

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
    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        reserved  = inspector.reserved() or {}
        active    = inspector.active()   or {}
        depth = sum(len(v) for v in reserved.values()) + \
                sum(len(v) for v in active.values())
    except Exception:
        depth = 0
    return {
        "pending_jobs":      depth,
        "estimated_wait_min": depth * 7,
        "status":            "busy" if depth > 0 else "idle",
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

    # Queue depth
    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        reserved  = inspector.reserved() or {}
        depth = sum(len(v) for v in reserved.values())
    except Exception:
        depth = 0

    task = run_mcq_pipeline.delay(topics, req.output_name)

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
        queue_depth=depth,
    )
    return {
        "task_id":            task.id,
        "status":             "queued",
        "queue_position":     depth + 1,
        "estimated_wait_min": depth * 7,
        "n_questions":        n_q,
        "message":            f"Generating {n_q} MCQs — position #{depth + 1}",
    }

@app.get("/status/{task_id}")
def get_status(task_id: str, user: dict = Depends(get_current_user)):
    result = AsyncResult(task_id, app=celery_app)
    if result.state == "PENDING":
        return {"task_id": task_id, "state": "pending", "progress": 0}
    elif result.state == "PROGRESS":
        meta = result.info or {}
        return {
            "task_id":          task_id,
            "state":            "running",
            "progress":         meta.get("progress", 0),
            "step":             meta.get("step", ""),
            "current_question": meta.get("current_question", 0),
            "total_questions":  meta.get("total_questions", 0),
        }
    elif result.state == "SUCCESS":
        data = result.result or {}
        return {
            "task_id":  task_id,
            "state":    "success",
            "progress": 100,
            "accepted": data.get("accepted", 0),
            "failed":   data.get("failed", 0),
        }
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

    return {"task_id": task_id, "accepted": len(mcqs), "mcqs": mcqs}

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
            elif result.state == "PROGRESS":
                meta = result.info or {}
                await websocket.send_json({
                    "state":            "running",
                    "progress":         meta.get("progress", 0),
                    "step":             meta.get("step", ""),
                    "current_question": meta.get("current_question", 0),
                    "total_questions":  meta.get("total_questions", 0),
                })
            elif result.state == "SUCCESS":
                data = result.result or {}
                await websocket.send_json({
                    "state":    "success",
                    "progress": 100,
                    "accepted": data.get("accepted", 0),
                })
                break
            elif result.state == "FAILURE":
                await websocket.send_json({"state": "failed", "error": str(result.info)})
                break
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        log.info("websocket_disconnected", task_id=task_id)
