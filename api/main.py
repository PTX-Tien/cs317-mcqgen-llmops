"""
api/main.py — MCQGen FastAPI server (Production-grade)
"""
import asyncio, json, math, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from celery.result import AsyncResult
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator
from sqlmodel import Session, select, func

from api.tasks import celery_app, run_mcq_pipeline, warmup_system
from api.core.config import settings
from api.core.logger import setup_logging, log, CorrelationIDMiddleware
from api.core.auth import (
    pwd_context, create_token, decode_token, get_current_user,
    require_role, oauth2_scheme,
    register_user, UsernameAlreadyExistsError,
)
from api.core.database import (
    engine,
    exam_summary,
    format_exam_display_name,
    get_exam_mcqs,
    get_session,
    init_db,
    persist_generation_failure,
    persist_generation_success,
    Exam,
    Question,
    QuizAttempt,
    UserAccount,
)
from api.core.cache import (
    get_cached_task_id,
    set_cached_task_id,
    cache_health,
)
from api.core.session import (
    register_session,
    blacklist_token,
    invalidate_user_sessions,
    append_user_context,
    get_user_context,
    clear_user_context,
    session_health,
)
from api.pdf_exporter import export_exam_pdf
from src.mcqgen.math_format import normalize_mcq_math, strip_answers_for_view
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

# Redis-backed storage đảm bảo rate limit được chia sẻ qua tất cả API instances
# Fallback sang in-memory nếu Redis không khả dụng
try:
    limiter = Limiter(key_func=get_user_key, storage_uri=settings.REDIS_CACHE_URL)
except Exception:
    limiter = Limiter(key_func=get_user_key)

app = FastAPI(title="MCQGen API", version="2.0", docs_url="/docs")

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
    display_name: Optional[str] = None
    retrieval_mode: str = "auto"

class LoginResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int
    role:          str
    full_name:     str

class PracticeSubmitRequest(BaseModel):
    answers: Dict[str, str]
    duration_seconds: int = 0

class RegisterRequest(BaseModel):
    username:   str
    password:   str
    full_name:  Optional[str] = ""

GENERATION_MIN_PER_QUESTION_BY_MODE = {
    "fast": 7,
    "auto": 8,
    "quality": 10,
}
QUEUE_MIN_PER_JOB = 10
GENERATION_TASK_NAME = "api.tasks.run_mcq_pipeline"
CHAPTER_LABELS = {
    "ch02": "Chương 2: NumPy, Pandas",
    "ch03": "Chương 3: Pipeline và EDA",
    "ch04": "Chương 4: Tiền xử lý dữ liệu",
    "ch05": "Chương 5: Đánh giá mô hình",
    "ch06": "Chương 6: Học không giám sát",
    "ch07a": "Chương 7a: Hồi quy",
    "ch07b": "Chương 7b: Phân loại",
    "ch08": "Chương 8: Deep Learning và CNN",
    "ch09": "Chương 9: Tinh chỉnh tham số",
    "ch10": "Chương 10: Ensemble Models",
    "ch11": "Chương 11: Triển khai mô hình",
}

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

def estimate_queue_wait_minutes(jobs_ahead: int) -> int:
    worker_slots = max(1, settings.CELERY_GENERATION_CONCURRENCY)
    job_waves_ahead = math.ceil(max(0, jobs_ahead) / worker_slots)
    return job_waves_ahead * QUEUE_MIN_PER_JOB

def _task_name(task: Any) -> str:
    if not isinstance(task, dict):
        return ""
    request = task.get("request")
    if isinstance(request, dict):
        return str(request.get("name") or request.get("task") or "")
    return str(task.get("name") or task.get("task") or "")

def _is_own_worker(worker_name: str) -> bool:
    namespace = (settings.CELERY_WORKER_NAMESPACE or "").strip()
    if not namespace:
        return True
    return worker_name.startswith(f"{namespace}-")

def _count_generation_tasks(tasks_by_worker) -> int:
    total = 0
    for worker_name, tasks in (tasks_by_worker or {}).items():
        if not _is_own_worker(str(worker_name)):
            continue
        for task in tasks or []:
            if _task_name(task) == GENERATION_TASK_NAME:
                total += 1
    return total

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

    active_jobs = _count_generation_tasks(active)
    reserved_jobs = _count_generation_tasks(reserved)
    scheduled_jobs = _count_generation_tasks(scheduled)
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


def _sync_exam_from_celery(session: Session, exam: Exam) -> Exam:
    result = AsyncResult(exam.task_id, app=celery_app)
    if result.state == "SUCCESS":
        if exam.status == "success":
            return exam
        data = result.result or {}
        if isinstance(data, dict) and data.get("type") != "warmup":
            return persist_generation_success(session, exam.task_id, data) or exam
    if result.state == "FAILURE":
        return persist_generation_failure(session, exam.task_id, str(result.info)) or exam
    return exam


def _user_has_attempt(session: Session, exam: Exam, username: str) -> bool:
    return bool(
        session.exec(
            select(QuizAttempt)
            .where(QuizAttempt.exam_id == exam.id)
            .where(QuizAttempt.student_id == username)
        ).first()
    )


def _ensure_answer_access(session: Session, exam: Exam | None, username: str):
    if not exam:
        raise HTTPException(status_code=403, detail="Cần lưu đề trước khi xem đáp án")
    if not _user_has_attempt(session, exam, username):
        raise HTTPException(
            status_code=403,
            detail="Bạn cần nộp bài trước khi xem hoặc tải đáp án.",
        )


def _mcqs_for_view(mcqs: list[dict], include_answers: bool) -> list[dict]:
    normalized = [normalize_mcq_math(dict(mcq)) for mcq in mcqs if isinstance(mcq, dict)]
    if include_answers:
        return normalized
    return [strip_answers_for_view(mcq) for mcq in normalized]


def _db_result_payload(session: Session, exam: Exam, include_answers: bool = False) -> dict:
    mcqs = get_exam_mcqs(session, exam)
    summary = exam_summary(exam)
    return {
        "task_id": exam.task_id,
        "display_name": summary["exam_name"],
        "accepted": exam.accepted_questions or len(mcqs),
        "failed": exam.failed_questions,
        "failures": summary["failures"],
        "mcqs": _mcqs_for_view(mcqs, include_answers),
        "include_answers": include_answers,
        "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
        "celery_generation_concurrency": settings.CELERY_GENERATION_CONCURRENCY,
        "question_concurrency": settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
        "llm_concurrency": settings.MCQGEN_LLM_MAX_CONCURRENCY,
        "vllm_max_num_seqs": settings.VLLM_MAX_NUM_SEQS,
        "source": "db",
    }


def _result_display_name(data: object, exam: Optional[Exam] = None) -> str:
    if isinstance(data, dict):
        return format_exam_display_name(
            data.get("display_name") or data.get("output_name") or (exam.exam_name if exam else "")
        )
    return format_exam_display_name(exam.exam_name if exam else "")


def _db_terminal_status_payload(task_id: str) -> Optional[dict]:
    with Session(engine) as session:
        exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
        if not exam:
            return None
        if exam.status == "success":
            summary = exam_summary(exam)
            return {
                "task_id": task_id,
                "state": "success",
                "progress": 100,
                "display_name": summary["exam_name"],
                "accepted": exam.accepted_questions or exam.n_questions,
                "failed": exam.failed_questions,
                "failures": summary["failures"],
                "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
                "celery_generation_concurrency": settings.CELERY_GENERATION_CONCURRENCY,
                "question_concurrency": settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
                "llm_concurrency": settings.MCQGEN_LLM_MAX_CONCURRENCY,
                "vllm_max_num_seqs": settings.VLLM_MAX_NUM_SEQS,
                "source": "db",
            }
        if exam.status in {"failed", "cancelled"}:
            return {
                "task_id": task_id,
                "state": "failed",
                "error": exam.error_message or f"Job {exam.status}",
                "source": "db",
            }
    return None


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _chapter_label(chapter_id: str | None) -> str:
    return CHAPTER_LABELS.get(chapter_id or "", chapter_id or "Chưa rõ chương")


def _exam_for_practice(session: Session, task_id: str) -> Exam:
    exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    exam = _sync_exam_from_celery(session, exam)
    if exam.status != "success":
        raise HTTPException(status_code=400, detail=f"Đề thi chưa sẵn sàng: {exam.status}")
    return exam


def _practice_question(mcq: dict) -> dict:
    return {
        "question_id": mcq.get("question_id", ""),
        "question_text": mcq.get("question_text", ""),
        "question_type": mcq.get("question_type", "single_correct"),
        "options": mcq.get("options", {}),
        "topic": mcq.get("topic", ""),
        "difficulty_label": mcq.get("difficulty_label", mcq.get("difficulty", "G2")),
        "chapter_id": mcq.get("chapter_id", ""),
        "chapter_label": _chapter_label(mcq.get("chapter_id")),
    }


def _score_practice_attempt(mcqs: list[dict], answers: dict[str, str]) -> tuple[int, list[dict]]:
    n_correct = 0
    details = []
    for idx, mcq in enumerate(mcqs):
        question_id = mcq.get("question_id") or f"q{idx + 1}"
        selected = (answers.get(question_id) or answers.get(str(idx)) or "").strip().upper()
        correct_answers = [
            str(answer).strip().upper()
            for answer in (mcq.get("correct_answers") or [])
        ]
        is_correct = bool(selected) and selected in correct_answers
        if is_correct:
            n_correct += 1
        details.append({
            "question_id": question_id,
            "position": idx,
            "question_text": mcq.get("question_text", ""),
            "question_type": mcq.get("question_type", "single_correct"),
            "options": mcq.get("options", {}),
            "selected": selected,
            "correct_answers": correct_answers,
            "is_correct": is_correct,
            "correct_rationale": mcq.get("correct_rationale", ""),
            "topic": mcq.get("topic", ""),
            "chapter_id": mcq.get("chapter_id", ""),
            "chapter_label": _chapter_label(mcq.get("chapter_id")),
            "difficulty_label": mcq.get("difficulty_label", mcq.get("difficulty", "G2")),
        })
    return n_correct, details


def _attempt_summary(attempt: QuizAttempt, exam: Exam | None = None) -> dict:
    return {
        "id": attempt.id,
        "exam_id": attempt.exam_id,
        "exam_name": format_exam_display_name(exam.exam_name) if exam else "Đề thi",
        "task_id": exam.task_id if exam else None,
        "student_id": attempt.student_id,
        "score": attempt.score,
        "n_correct": attempt.n_correct,
        "n_total": attempt.n_total,
        "duration_seconds": attempt.duration_seconds,
        "submitted_at": attempt.submitted_at,
        "answers": _json_loads(attempt.answers_json, {}),
        "details": _json_loads(attempt.details_json, []),
    }


def _ratio(part: int, total: int) -> float:
    return round((part / total) * 100, 1) if total else 0.0


def _build_ranked_stats(stats: dict[str, dict]) -> list[dict]:
    rows = []
    for key, item in stats.items():
        rows.append({
            "key": key,
            "label": item["label"],
            "wrong": item["wrong"],
            "total": item["total"],
            "wrong_rate": _ratio(item["wrong"], item["total"]),
        })
    return sorted(rows, key=lambda row: (row["wrong"], row["wrong_rate"]), reverse=True)

# ── Auth endpoints ────────────────────────────────────────────────
@app.post("/auth/register", status_code=201)
def register(req: RegisterRequest):
    """Đăng ký tài khoản user mới (public endpoint, không cần auth)."""
    try:
        user_info = register_user(
            username=req.username,
            password=req.password,
            full_name=req.full_name or "",
        )
        log.info("register_success", username=user_info["username"])
        return {"message": "Đăng ký thành công", "username": user_info["username"]}
    except UsernameAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/auth/login", response_model=LoginResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    from api.core.auth import _get_user_from_db
    user = _get_user_from_db(form_data.username)
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

    # Đăng ký session để hỗ trợ logout & force-logout
    try:
        jti = decode_token(access_token).get("jti")
        if jti:
            register_session(user["username"], jti)
    except Exception:
        pass

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

@app.post("/auth/logout")
def logout(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Logout: blacklist token hiện tại để nó không dùng được nữa dù chưa hết hạn."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header[7:]
            payload = decode_token(token)
            jti = payload.get("jti")
            exp_ts = payload.get("exp")
            if jti and exp_ts:
                exp_dt = datetime.utcfromtimestamp(exp_ts)
                blacklist_token(jti, exp_dt)
        except Exception:
            pass  # token invalid hoặc Redis lỗi → vẫn return 200
    log.info("logout", username=user["username"])
    return {"message": "Đăng xuất thành công"}

@app.post("/auth/logout-all")
def logout_all(user: dict = Depends(get_current_user)):
    """Logout tất cả sessions của user (force logout on all devices)."""
    count = invalidate_user_sessions(user["username"])
    log.info("logout_all", username=user["username"], sessions_revoked=count)
    return {"message": f"Đã đăng xuất {count} session", "sessions_revoked": count}

# ── Health ────────────────────────────────────────────────────────
@app.get("/health")
def health():
    cache_status  = cache_health()
    session_status = session_health()
    all_ok = cache_status["status"] == "ok" and session_status["status"] == "ok"
    return {
        "status":  "ok" if all_ok else "degraded",
        "version": "2.0",
        "service": "MCQGen API",
        "components": {
            "cache":   cache_status,
            "session": session_status,
        },
        "concurrency": {
            "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
            "celery_generation_concurrency": settings.CELERY_GENERATION_CONCURRENCY,
            "question_concurrency_per_job": settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
            "llm_concurrency_per_job": settings.MCQGEN_LLM_MAX_CONCURRENCY,
            "vllm_max_num_seqs": settings.VLLM_MAX_NUM_SEQS,
            "total_llm_slots": (
                settings.CELERY_GENERATION_CONCURRENCY
                * settings.MCQGEN_MAX_CONCURRENT_QUESTIONS
            ),
            "autotune": settings.MCQGEN_CONCURRENCY_AUTOTUNE,
            "celery_queue_high": settings.CELERY_QUEUE_HIGH,
            "celery_queue_low": settings.CELERY_QUEUE_LOW,
            "celery_worker_namespace": settings.CELERY_WORKER_NAMESPACE,
        },
    }

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
        "estimated_wait_min": estimate_queue_wait_minutes(depth),
        "status":             "busy" if depth > 0 else "idle",
        "inspect_ok":         queue["inspect_ok"],
        "celery_queue_high": settings.CELERY_QUEUE_HIGH,
        "celery_queue_low": settings.CELERY_QUEUE_LOW,
        "celery_worker_namespace": settings.CELERY_WORKER_NAMESPACE,
        "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
        "celery_generation_concurrency": settings.CELERY_GENERATION_CONCURRENCY,
        "generation_concurrency": settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
        "llm_concurrency": settings.MCQGEN_LLM_MAX_CONCURRENCY,
        "vllm_max_num_seqs": settings.VLLM_MAX_NUM_SEQS,
        "total_llm_slots": (
            settings.CELERY_GENERATION_CONCURRENCY
            * settings.MCQGEN_MAX_CONCURRENT_QUESTIONS
        ),
    }

@app.post("/admin/warmup")
def admin_warmup(user: dict = Depends(require_role("admin"))):
    task = warmup_system.delay()
    log.info("warmup_submitted", task_id=task.id, user=user["username"])
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Warming RAG retriever and vLLM inside Celery worker",
    }

# ── Generation ────────────────────────────────────────────────────
@app.post("/generate")
@limiter.limit(settings.RATE_LIMIT_USER)
def generate(
    request: Request,
    req: GenerateRequest,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    topics = [t.model_dump() for t in req.topics]
    n_q    = sum(t["n"] for t in topics)
    retrieval_mode = req.retrieval_mode.lower()
    display_name = format_exam_display_name(req.display_name or req.output_name)
    if retrieval_mode not in {"fast", "auto", "quality"}:
        raise HTTPException(status_code=422, detail="retrieval_mode must be fast, auto, or quality")

    existing_exam = next(
        (
            exam
            for exam in session.exec(
                select(Exam).where(Exam.created_by == user["username"])
            ).all()
            if format_exam_display_name(exam.exam_name).casefold() == display_name.casefold()
        ),
        None,
    )
    if existing_exam:
        raise HTTPException(
            status_code=409,
            detail=f'Tên đề thi "{display_name}" đã tồn tại trong lịch sử. Vui lòng chọn tên khác hoặc xoá đề cũ trước.',
        )

    # ── Cache dedup: kiểm tra xem config này đã được generate thành công chưa ──
    cached_task_id = get_cached_task_id(topics, retrieval_mode)
    if cached_task_id:
        cached_exam = session.exec(select(Exam).where(Exam.task_id == cached_task_id)).first()
        if cached_exam and cached_exam.status == "success":
            log.info(
                "generation_cache_hit",
                cached_task_id=cached_task_id,
                user=user["username"],
                n_questions=n_q,
            )
            summary = exam_summary(cached_exam)
            return {
                "task_id":              cached_task_id,
                "status":               "success",
                "source":               "cache",
                "display_name":         summary["exam_name"],
                "accepted":             cached_exam.accepted_questions or cached_exam.n_questions,
                "failed":               cached_exam.failed_questions,
                "n_questions":          cached_exam.n_questions,
                "retrieval_mode":       retrieval_mode,
                "message":              "Kết quả được lấy từ cache (cùng cấu hình đã generate trước đó)",
            }

    task_id = str(uuid.uuid4())
    session_id = f"exam:{task_id}"
    trace_payload = {
        "task_id": task_id,
        "session_id": session_id,
        "use_case": "exam_generation",
        "user_id": user["username"],
        "user_role": user.get("role"),
        "role": user.get("role"),
        "exam_name": display_name,
        "output_name": req.output_name,
        "n_questions": n_q,
        "topic_count": len(topics),
        "retrieval_mode": retrieval_mode,
        "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
        "celery_generation_concurrency": settings.CELERY_GENERATION_CONCURRENCY,
        "question_concurrency_per_job": settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
        "llm_concurrency_per_job": settings.MCQGEN_LLM_MAX_CONCURRENCY,
        "vllm_max_num_seqs": settings.VLLM_MAX_NUM_SEQS,
        "total_llm_slots": (
            settings.CELERY_GENERATION_CONCURRENCY
            * settings.MCQGEN_MAX_CONCURRENT_QUESTIONS
        ),
        "celery_queue_high": settings.CELERY_QUEUE_HIGH,
        "celery_worker_namespace": settings.CELERY_WORKER_NAMESPACE,
        "topics": topics,
    }

    with langfuse_attributes(
        user_id=user["username"],
        session_id=session_id,
        tags=["mcqgen", "api", "generate", "exam"],
        metadata=trace_payload,
        trace_name="mcqgen.generate_exam",
    ):
        with langfuse_observation(
            "api.generate.submit",
            as_type="span",
            input={
                "output_name": req.output_name,
                "display_name": display_name,
                "retrieval_mode": retrieval_mode,
                "topics": topics,
            },
            metadata=trace_payload,
        ) as lf_span:
            queue = get_queue_snapshot()
            jobs_ahead = queue["total_jobs"]
            concurrency_at_submit = jobs_ahead + 1
            trace_payload.update(
                {
                    "active_jobs_at_submit": queue["active_jobs"],
                    "queued_jobs_at_submit": queue["queued_jobs"],
                    "queue_depth_at_submit": jobs_ahead,
                    "concurrency_at_submit": concurrency_at_submit,
                    "load_scenario": (
                        "single_user"
                        if concurrency_at_submit <= 1
                        else "concurrent_users"
                    ),
                }
            )

            estimated_runtime_min = estimate_generation_minutes(n_q, retrieval_mode)
            queue_wait_min = estimate_queue_wait_minutes(jobs_ahead)
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
                    "concurrency_at_submit": concurrency_at_submit,
                    "load_scenario": trace_payload["load_scenario"],
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
                exam_name=display_name,
                n_questions=n_q,
                requested_questions=n_q,
                status="pending",
            )
            session.add(exam)
            session.commit()

    # Lưu context: user vừa tạo một đề thi (dùng cho future multi-turn interactions)
    try:
        append_user_context(
            user["username"],
            "user",
            f"Tạo đề thi '{display_name}' với {n_q} câu, mode={retrieval_mode}",
        )
    except Exception:
        pass

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
        "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
        "celery_generation_concurrency": settings.CELERY_GENERATION_CONCURRENCY,
        "generation_concurrency": settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
        "llm_concurrency":    settings.MCQGEN_LLM_MAX_CONCURRENCY,
        "vllm_max_num_seqs":  settings.VLLM_MAX_NUM_SEQS,
        "total_llm_slots": (
            settings.CELERY_GENERATION_CONCURRENCY
            * settings.MCQGEN_MAX_CONCURRENT_QUESTIONS
        ),
        "message":            f"Generating {n_q} MCQs — estimated ~{estimated_total_min} min",
    }

@app.get("/status/{task_id}")
def get_status(
    task_id: str,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    result = AsyncResult(task_id, app=celery_app)
    exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
    if result.state == "PENDING":
        if exam and exam.status in {"success", "failed", "cancelled"}:
            payload = _db_terminal_status_payload(task_id)
            if payload:
                return payload
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
            "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
            "celery_generation_concurrency": settings.CELERY_GENERATION_CONCURRENCY,
            "question_concurrency": meta.get("question_concurrency", settings.MCQGEN_MAX_CONCURRENT_QUESTIONS),
            "llm_concurrency":      meta.get("llm_concurrency", settings.MCQGEN_LLM_MAX_CONCURRENCY),
            "vllm_max_num_seqs":    settings.VLLM_MAX_NUM_SEQS,
        }
    elif result.state == "SUCCESS":
        data = result.result or {}
        if exam and exam.status != "success" and isinstance(data, dict) and data.get("type") != "warmup":
            exam = persist_generation_success(session, task_id, data) or exam
        payload = {
            "task_id":  task_id,
            "state":    "success",
            "progress": 100,
            "display_name": _result_display_name(data, exam),
            "accepted": data.get("accepted", 0),
            "failed":   data.get("failed", 0),
            "failures": data.get("failures", []),
            "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
            "celery_generation_concurrency": data.get("celery_generation_concurrency", settings.CELERY_GENERATION_CONCURRENCY),
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
        if exam:
            persist_generation_failure(session, task_id, str(result.info))
        return {"task_id": task_id, "state": "failed", "error": str(result.info)}
    return {"task_id": task_id, "state": result.state}

@app.get("/results/{task_id}")
def get_results(
    task_id: str,
    include_answers: bool = False,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
    result = AsyncResult(task_id, app=celery_app)
    if result.state == "SUCCESS":
        data = result.result or {}
        if isinstance(data, dict) and data.get("type") == "warmup":
            raise HTTPException(400, "Warmup task has no exam results")
        if exam and exam.status != "success" and isinstance(data, dict):
            exam = persist_generation_success(session, task_id, data) or exam
        if include_answers:
            _ensure_answer_access(session, exam, user["username"])
        mcqs = data.get("mcqs", []) if isinstance(data, dict) else []
        return {
            "task_id": task_id,
            "display_name": _result_display_name(data, exam),
            "accepted": data.get("accepted", len(mcqs)) if isinstance(data, dict) else len(mcqs),
            "failed": data.get("failed", 0) if isinstance(data, dict) else 0,
            "failures": data.get("failures", []) if isinstance(data, dict) else [],
            "mcqs": _mcqs_for_view(mcqs, include_answers),
            "include_answers": include_answers,
            "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
            "celery_generation_concurrency": data.get("celery_generation_concurrency", settings.CELERY_GENERATION_CONCURRENCY) if isinstance(data, dict) else settings.CELERY_GENERATION_CONCURRENCY,
            "question_concurrency": data.get("question_concurrency", settings.MCQGEN_MAX_CONCURRENT_QUESTIONS) if isinstance(data, dict) else settings.MCQGEN_MAX_CONCURRENT_QUESTIONS,
            "llm_concurrency": data.get("llm_concurrency", settings.MCQGEN_LLM_MAX_CONCURRENCY) if isinstance(data, dict) else settings.MCQGEN_LLM_MAX_CONCURRENCY,
            "vllm_max_num_seqs": settings.VLLM_MAX_NUM_SEQS,
            "source": "celery",
        }

    if exam and exam.status == "success":
        if include_answers:
            _ensure_answer_access(session, exam, user["username"])
        return _db_result_payload(session, exam, include_answers=include_answers)
    if exam and exam.status in {"failed", "cancelled"}:
        raise HTTPException(400, exam.error_message or f"Job {exam.status}")
    raise HTTPException(400, f"Job not done: {result.state}")


# ── Practice / quiz taking ───────────────────────────────────────
@app.get("/practice/{task_id}")
def get_practice_exam(
    task_id: str,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    exam = _exam_for_practice(session, task_id)
    mcqs = get_exam_mcqs(session, exam)
    return {
        "task_id": task_id,
        "exam_id": exam.id,
        "exam_name": format_exam_display_name(exam.exam_name),
        "n_questions": len(mcqs),
        "questions": [_practice_question(mcq) for mcq in mcqs],
    }


@app.post("/practice/{task_id}/submit")
def submit_practice_exam(
    task_id: str,
    req: PracticeSubmitRequest,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    exam = _exam_for_practice(session, task_id)
    mcqs = get_exam_mcqs(session, exam)
    if not mcqs:
        raise HTTPException(status_code=404, detail="Đề thi chưa có câu hỏi")

    answers = {
        str(question_id): str(answer).strip().upper()
        for question_id, answer in req.answers.items()
        if str(answer).strip()
    }
    n_correct, details = _score_practice_attempt(mcqs, answers)
    score = round((n_correct / len(mcqs)) * 10, 2)

    attempt = QuizAttempt(
        student_id=user["username"],
        exam_id=exam.id,
        answers_json=json.dumps(answers, ensure_ascii=False),
        score=score,
        n_correct=n_correct,
        n_total=len(mcqs),
        duration_seconds=max(0, int(req.duration_seconds or 0)),
        details_json=json.dumps(details, ensure_ascii=False),
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    return {
        "attempt": _attempt_summary(attempt, exam),
        "exam_name": format_exam_display_name(exam.exam_name),
        "task_id": task_id,
        "score": score,
        "n_correct": n_correct,
        "n_total": len(mcqs),
        "details": details,
    }


@app.get("/practice/{task_id}/attempts")
def get_practice_attempts(
    task_id: str,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    exam = _exam_for_practice(session, task_id)
    attempts = session.exec(
        select(QuizAttempt)
        .where(QuizAttempt.exam_id == exam.id)
        .where(QuizAttempt.student_id == user["username"])
        .order_by(QuizAttempt.submitted_at.desc())
    ).all()
    return {
        "task_id": task_id,
        "exam_name": format_exam_display_name(exam.exam_name),
        "attempts": [_attempt_summary(attempt, exam) for attempt in attempts],
    }


@app.get("/analytics/study-summary")
def get_study_summary(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    attempts = session.exec(
        select(QuizAttempt)
        .where(QuizAttempt.student_id == user["username"])
        .order_by(QuizAttempt.submitted_at.desc())
    ).all()

    chapter_stats: dict[str, dict] = {}
    topic_stats: dict[str, dict] = {}
    difficulty_stats: dict[str, dict] = {}
    recent_attempts = []
    total_questions = 0
    total_correct = 0

    for attempt in attempts:
        exam = session.get(Exam, attempt.exam_id)
        recent_attempts.append(_attempt_summary(attempt, exam))
        total_questions += attempt.n_total
        total_correct += attempt.n_correct

        for detail in _json_loads(attempt.details_json, []):
            if not isinstance(detail, dict):
                continue
            chapter_id = detail.get("chapter_id") or "unknown"
            chapter_label = detail.get("chapter_label") or _chapter_label(chapter_id)
            topic = detail.get("topic") or "Chưa rõ topic"
            difficulty = detail.get("difficulty_label") or "Chưa rõ độ khó"
            is_correct = bool(detail.get("is_correct"))

            for stats, key, label in (
                (chapter_stats, chapter_id, chapter_label),
                (topic_stats, topic, topic),
                (difficulty_stats, difficulty, difficulty),
            ):
                item = stats.setdefault(key, {"label": label, "wrong": 0, "total": 0})
                item["total"] += 1
                if not is_correct:
                    item["wrong"] += 1

    wrong_questions = total_questions - total_correct
    average_score = (
        round(sum(attempt.score for attempt in attempts) / len(attempts), 2)
        if attempts else 0.0
    )
    top_chapters = _build_ranked_stats(chapter_stats)
    top_topics = _build_ranked_stats(topic_stats)
    top_difficulties = _build_ranked_stats(difficulty_stats)

    recommendations = []
    if top_chapters and top_chapters[0]["wrong"] > 0:
        recommendations.append(f"Ôn lại {top_chapters[0]['label']} vì đây là chương có nhiều câu sai nhất.")
    if top_topics and top_topics[0]["wrong"] > 0:
        recommendations.append(f"Luyện thêm topic {top_topics[0]['label']} để giảm lỗi lặp lại.")
    if top_difficulties and top_difficulties[0]["wrong"] > 0:
        recommendations.append(f"Tập trung thêm nhóm độ khó {top_difficulties[0]['label']}.")
    if not recommendations:
        recommendations.append("Chưa đủ dữ liệu sai để đưa ra gợi ý cải thiện.")

    return {
        "total_attempts": len(attempts),
        "total_questions": total_questions,
        "total_correct": total_correct,
        "total_wrong": wrong_questions,
        "average_score": average_score,
        "accuracy_rate": _ratio(total_correct, total_questions),
        "wrong_rate": _ratio(wrong_questions, total_questions),
        "top_wrong_chapters": top_chapters[:5],
        "top_wrong_topics": top_topics[:5],
        "top_wrong_difficulties": top_difficulties[:5],
        "recommendations": recommendations,
        "recent_attempts": recent_attempts[:5],
    }


@app.delete("/cancel/{task_id}")
def cancel_job(
    task_id: str,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    result = AsyncResult(task_id, app=celery_app)
    if result.state in ("PENDING", "STARTED", "PROGRESS", "RETRY"):
        result.revoke(terminate=True, signal="SIGTERM")
        exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
        if exam:
            exam.status = "cancelled"
            exam.completed_at = datetime.utcnow()
            exam.error_message = "User cancelled job"
            session.add(exam)
            session.commit()
        log.info("job_cancelled", task_id=task_id, user=user["username"])
        return {"task_id": task_id, "cancelled": True}
    return {"task_id": task_id, "cancelled": False, "reason": f"Job already {result.state}"}

# ── History ───────────────────────────────────────────────────────
@app.get("/history")
def get_history(
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    exams = session.exec(
        select(Exam).where(Exam.created_by == user["username"])
        .order_by(Exam.created_at.desc()).limit(20)
    ).all()
    synced = [_sync_exam_from_celery(session, exam) for exam in exams]
    rows = []
    for exam in synced:
        summary = exam_summary(exam)
        summary["has_attempt"] = _user_has_attempt(session, exam, user["username"])
        rows.append(summary)
    return {"exams": rows}


@app.delete("/history/{task_id}")
def delete_history_item(
    task_id: str,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # User chỉ xoá được exam của chính mình; admin xoá được của bất kỳ ai
    query = select(Exam).where(Exam.task_id == task_id)
    if user["role"] != "admin":
        query = query.where(Exam.created_by == user["username"])
    exam = session.exec(query).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    result = AsyncResult(task_id, app=celery_app)
    if exam.status in {"pending", "running"} and result.state in {"PENDING", "STARTED", "PROGRESS", "RETRY"}:
        result.revoke(terminate=True, signal="SIGTERM")

    for attempt in session.exec(select(QuizAttempt).where(QuizAttempt.exam_id == exam.id)).all():
        session.delete(attempt)
    for question in session.exec(select(Question).where(Question.exam_id == exam.id)).all():
        session.delete(question)
    session.delete(exam)
    session.commit()
    log.info("history_deleted", task_id=task_id, user=user["username"])
    return {"task_id": task_id, "deleted": True}

# ── Export PDF ────────────────────────────────────────────────────
@app.get("/export/pdf/{task_id}")
def export_pdf(
    task_id: str,
    include_answers: bool = False,
    user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    result = AsyncResult(task_id, app=celery_app)
    exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
    exam_name = "ĐỀ KIỂM TRA CS116"
    mcqs = []

    if result.state == "SUCCESS":
        data = result.result or {}
        if isinstance(data, dict) and data.get("type") == "warmup":
            raise HTTPException(400, "Warmup task has no exam PDF")
        if exam and exam.status != "success" and isinstance(data, dict):
            persist_generation_success(session, task_id, data)
        mcqs = data.get("mcqs", []) if isinstance(data, dict) else []
        if isinstance(data, dict):
            exam_name = format_exam_display_name(
                data.get("display_name") or data.get("output_name", exam_name)
            )
    elif exam and exam.status == "success":
        mcqs = get_exam_mcqs(session, exam)
        exam_name = format_exam_display_name(exam.exam_name)
    else:
        raise HTTPException(400, f"Job not done: {result.state}")

    if not mcqs:
        raise HTTPException(404, "No MCQs found")

    if include_answers:
        _ensure_answer_access(session, exam, user["username"])

    pdf_bytes = export_exam_pdf(
        _mcqs_for_view(mcqs, include_answers=include_answers),
        exam_name=exam_name.upper(),
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
                db_payload = _db_terminal_status_payload(task_id)
                if db_payload:
                    await websocket.send_json(db_payload)
                    break
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
                    "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
                    "celery_generation_concurrency": settings.CELERY_GENERATION_CONCURRENCY,
                    "question_concurrency": meta.get("question_concurrency", settings.MCQGEN_MAX_CONCURRENT_QUESTIONS),
                    "llm_concurrency":      meta.get("llm_concurrency", settings.MCQGEN_LLM_MAX_CONCURRENCY),
                    "vllm_max_num_seqs":    settings.VLLM_MAX_NUM_SEQS,
                })
            elif result.state == "SUCCESS":
                data = result.result or {}
                if isinstance(data, dict) and data.get("type") != "warmup":
                    with Session(engine) as session:
                        exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
                        if exam and exam.status != "success":
                            persist_generation_success(session, task_id, data)
                await websocket.send_json({
                    "state":    "success",
                    "progress": 100,
                    "display_name": _result_display_name(data),
                    "accepted": data.get("accepted", 0),
                    "failed":   data.get("failed", 0),
                    "failures": data.get("failures", []),
                    "target_concurrent_users": settings.MCQGEN_TARGET_CONCURRENT_USERS,
                    "celery_generation_concurrency": data.get("celery_generation_concurrency", settings.CELERY_GENERATION_CONCURRENCY),
                    "question_concurrency": data.get("question_concurrency", settings.MCQGEN_MAX_CONCURRENT_QUESTIONS),
                    "llm_concurrency":      data.get("llm_concurrency", settings.MCQGEN_LLM_MAX_CONCURRENCY),
                    "vllm_max_num_seqs":    settings.VLLM_MAX_NUM_SEQS,
                })
                break
            elif result.state == "FAILURE":
                with Session(engine) as session:
                    persist_generation_failure(session, task_id, str(result.info))
                await websocket.send_json({"state": "failed", "error": str(result.info)})
                break
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        log.info("websocket_disconnected", task_id=task_id)


# ── Session context ───────────────────────────────────────────────
@app.get("/session/context")
def get_my_context(user: dict = Depends(get_current_user)):
    """Lấy lịch sử interaction context của user hiện tại."""
    context = get_user_context(user["username"])
    return {"username": user["username"], "context": context, "count": len(context)}


@app.delete("/session/context")
def clear_my_context(user: dict = Depends(get_current_user)):
    """Xoá toàn bộ conversation context của user."""
    clear_user_context(user["username"])
    log.info("context_cleared", username=user["username"])
    return {"message": "Context đã được xoá"}


# ── Admin: User Management ────────────────────────────────────────
def _user_stats(session: Session, username: str) -> dict:
    """Tổng hợp thống kê sử dụng của một user."""
    exam_count = session.exec(
        select(func.count(Exam.id)).where(Exam.created_by == username)
    ).one() or 0

    success_exams = session.exec(
        select(func.count(Exam.id))
        .where(Exam.created_by == username)
        .where(Exam.status == "success")
    ).one() or 0

    attempt_count = session.exec(
        select(func.count(QuizAttempt.id)).where(QuizAttempt.student_id == username)
    ).one() or 0

    avg_score_row = session.exec(
        select(func.avg(QuizAttempt.score)).where(QuizAttempt.student_id == username)
    ).one()
    avg_score = round(float(avg_score_row), 2) if avg_score_row else None

    last_exam = session.exec(
        select(Exam.created_at)
        .where(Exam.created_by == username)
        .order_by(Exam.created_at.desc())
        .limit(1)
    ).first()

    last_attempt = session.exec(
        select(QuizAttempt.submitted_at)
        .where(QuizAttempt.student_id == username)
        .order_by(QuizAttempt.submitted_at.desc())
        .limit(1)
    ).first()

    last_active = None
    candidates = [ts for ts in [last_exam, last_attempt] if ts is not None]
    if candidates:
        last_active = max(candidates).isoformat()

    return {
        "exam_count":    exam_count,
        "success_exams": success_exams,
        "attempt_count": attempt_count,
        "avg_score":     avg_score,
        "last_active":   last_active,
    }


@app.get("/admin/users")
def admin_list_users(
    admin: dict = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    """Danh sách tất cả users với thống kê sử dụng."""
    users = session.exec(
        select(UserAccount).order_by(UserAccount.created_at.desc())
    ).all()
    result = []
    for u in users:
        stats = _user_stats(session, u.username)
        result.append({
            "username":    u.username,
            "full_name":   u.full_name,
            "role":        u.role,
            "created_at":  u.created_at.isoformat() if u.created_at else None,
            "is_active":   u.is_active,
            **stats,
        })
    return {"users": result, "total": len(result)}


@app.patch("/admin/users/{username}/status")
def admin_toggle_user_status(
    username: str,
    admin: dict = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    """Kích hoạt / vô hiệu hoá tài khoản user."""
    user = session.get(UserAccount, username)
    if not user:
        raise HTTPException(status_code=404, detail="User không tồn tại")
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Không thể vô hiệu hoá tài khoản admin")
    user.is_active = not user.is_active
    session.add(user)
    session.commit()
    action = "activated" if user.is_active else "deactivated"
    log.info(f"admin_user_{action}", target=username, by=admin["username"])
    return {
        "username":  user.username,
        "is_active": user.is_active,
        "message":   f"Tài khoản đã {'kích hoạt' if user.is_active else 'vô hiệu hoá'}",
    }


@app.delete("/admin/users/{username}")
def admin_delete_user(
    username: str,
    admin: dict = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    """Xoá user và toàn bộ data của họ (exams, attempts)."""
    user = session.get(UserAccount, username)
    if not user:
        raise HTTPException(status_code=404, detail="User không tồn tại")
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Không thể xoá tài khoản admin")

    # Xoá quiz attempts
    for attempt in session.exec(select(QuizAttempt).where(QuizAttempt.student_id == username)).all():
        session.delete(attempt)

    # Xoá questions + exams của user
    exams = session.exec(select(Exam).where(Exam.created_by == username)).all()
    for exam in exams:
        for q in session.exec(select(Question).where(Question.exam_id == exam.id)).all():
            session.delete(q)
        session.delete(exam)

    session.delete(user)
    session.commit()

    # Invalidate sessions của user
    try:
        invalidate_user_sessions(username)
    except Exception:
        pass

    log.info("admin_user_deleted", target=username, by=admin["username"])
    return {"username": username, "deleted": True}


@app.get("/admin/global-stats")
def admin_global_stats(
    admin: dict = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    """Thống kê tổng thể toàn hệ thống cho admin dashboard."""
    total_users      = session.exec(select(func.count(UserAccount.username))).one() or 0
    active_users     = session.exec(select(func.count(UserAccount.username)).where(UserAccount.is_active == True)).one() or 0
    total_exams      = session.exec(select(func.count(Exam.id))).one() or 0
    success_exams    = session.exec(select(func.count(Exam.id)).where(Exam.status == "success")).one() or 0
    total_questions  = session.exec(select(func.count(Question.id))).one() or 0
    total_attempts   = session.exec(select(func.count(QuizAttempt.id))).one() or 0
    avg_quality_row  = session.exec(select(func.avg(Exam.quality_avg)).where(Exam.status == "success")).one()
    avg_quality      = round(float(avg_quality_row), 3) if avg_quality_row else 0.0
    queue            = get_queue_snapshot()

    return {
        "total_users":     total_users,
        "active_users":    active_users,
        "total_exams":     total_exams,
        "success_exams":   success_exams,
        "total_questions": total_questions,
        "total_attempts":  total_attempts,
        "avg_quality":     avg_quality,
        "queue":           queue,
    }


@app.get("/admin/users/{username}")
def admin_get_user_detail(
    username: str,
    admin: dict = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    """Chi tiết một user: thông tin tài khoản + lịch sử đề thi + các lần làm bài."""
    user = session.get(UserAccount, username)
    if not user:
        raise HTTPException(status_code=404, detail="User không tồn tại")

    stats = _user_stats(session, username)

    # 10 đề thi gần nhất của user
    recent_exams = session.exec(
        select(Exam)
        .where(Exam.created_by == username)
        .order_by(Exam.created_at.desc())
        .limit(10)
    ).all()

    # 10 lần làm bài gần nhất
    recent_attempts = session.exec(
        select(QuizAttempt)
        .where(QuizAttempt.student_id == username)
        .order_by(QuizAttempt.submitted_at.desc())
        .limit(10)
    ).all()

    return {
        "username":   user.username,
        "full_name":  user.full_name,
        "role":       user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "is_active":  user.is_active,
        **stats,
        "recent_exams": [
            {
                "task_id":    e.task_id,
                "exam_name":  format_exam_display_name(e.exam_name),
                "status":     e.status,
                "n_questions": e.n_questions,
                "quality_avg": e.quality_avg,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in recent_exams
        ],
        "recent_attempts": [
            {
                "id":          a.id,
                "exam_id":     a.exam_id,
                "score":       a.score,
                "n_correct":   a.n_correct,
                "n_total":     a.n_total,
                "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            }
            for a in recent_attempts
        ],
    }


class ResetPasswordRequest(BaseModel):
    new_password: str


@app.post("/admin/users/{username}/reset-password")
def admin_reset_password(
    username: str,
    req: ResetPasswordRequest,
    admin: dict = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    """Admin đặt lại mật khẩu cho user."""
    if len(req.new_password) < 6:
        raise HTTPException(status_code=422, detail="Mật khẩu phải có ít nhất 6 ký tự")
    user = session.get(UserAccount, username)
    if not user:
        raise HTTPException(status_code=404, detail="User không tồn tại")
    user.hashed_password = pwd_context.hash(req.new_password)
    session.add(user)
    session.commit()
    # Invalidate tất cả session cũ của user
    try:
        invalidate_user_sessions(username)
    except Exception:
        pass
    log.info("admin_password_reset", target=username, by=admin["username"])
    return {"message": f"Đã đặt lại mật khẩu cho {username}"}
