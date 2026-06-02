import os
import uuid
import json
import re
from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Session, create_engine, select
from sqlalchemy import event

from api.core.config import settings
from src.mcqgen.math_format import normalize_mcq_math

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

# SQLite WAL mode: cho phép concurrent reads từ nhiều API instances
# không block nhau khi writer đang ghi
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")   # faster writes, safe với WAL
        cursor.execute("PRAGMA busy_timeout=30000")   # 30s wait thay vì lỗi ngay
        cursor.close()

class UserAccount(SQLModel, table=True):
    username:         str      = Field(primary_key=True)
    hashed_password:  str
    role:             str      = "user"     # "admin" | "user"
    full_name:        str      = ""
    created_at:       datetime = Field(default_factory=datetime.utcnow)
    is_active:        bool     = True


class Exam(SQLModel, table=True):
    id:            str = Field(default_factory=lambda: str(uuid.uuid4())[:8], primary_key=True)
    task_id:       str = Field(unique=True, index=True)
    created_by:    str
    exam_name:     str
    n_questions:   int = 0
    status:        str = "pending"
    created_at:    datetime = Field(default_factory=datetime.utcnow)
    completed_at:  Optional[datetime] = None
    quality_avg:   Optional[float] = None
    prompt_version: str = "v1.0"
    requested_questions: int = 0
    accepted_questions:  int = 0
    failed_questions:    int = 0
    output_file:     Optional[str] = None
    error_message:   Optional[str] = None
    failure_info_json: str = "[]"

class Question(SQLModel, table=True):
    id:              str = Field(default_factory=lambda: str(uuid.uuid4())[:8], primary_key=True)
    exam_id:         str = Field(index=True)
    question_id:     str = Field(index=True)
    position:        int = 0
    question_text:   str
    question_type:   str = "single_correct"
    options_json:    str  # JSON string
    correct_answers_json: str
    correct_rationale: str = ""
    topic:           str
    difficulty:      str = "G2"
    quality_score:   float = 0.0
    evaluation_json: str = "{}"
    rag_strategy:    str = ""
    chapter_id:      str = ""
    prompt_version:  str = "v1.0"
    raw_mcq_json:    Optional[str] = None

class QuizAttempt(SQLModel, table=True):
    id:           str = Field(default_factory=lambda: str(uuid.uuid4())[:8], primary_key=True)
    student_id:   str = Field(index=True)
    exam_id:      str = Field(index=True)
    answers_json: str  # JSON
    score:        float
    n_correct:    int
    n_total:      int
    duration_seconds: int = 0
    details_json: str = "[]"
    submitted_at: datetime = Field(default_factory=datetime.utcnow)

def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Optional[str], default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def format_exam_display_name(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw:
        return "Đề thi"

    normalized = re.sub(r"[-\s]+", "_", raw).strip("_").lower()
    match = re.fullmatch(r"de_so_(\d+)", normalized)
    if match:
        return f"Đề số {int(match.group(1))}"

    if normalized in {"de", "de_thi", "exam"}:
        return "Đề thi"

    return raw


def _migrate_sqlite_schema():
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    migrations = {
        "exam": {
            "requested_questions": "INTEGER NOT NULL DEFAULT 0",
            "accepted_questions": "INTEGER NOT NULL DEFAULT 0",
            "failed_questions": "INTEGER NOT NULL DEFAULT 0",
            "output_file": "TEXT",
            "error_message": "TEXT",
            "failure_info_json": "TEXT NOT NULL DEFAULT '[]'",
        },
        "question": {
            "position": "INTEGER NOT NULL DEFAULT 0",
            "question_type": "TEXT NOT NULL DEFAULT 'single_correct'",
            "correct_rationale": "TEXT NOT NULL DEFAULT ''",
            "evaluation_json": "TEXT NOT NULL DEFAULT '{}'",
            "raw_mcq_json": "TEXT",
        },
        "quizattempt": {
            "duration_seconds": "INTEGER NOT NULL DEFAULT 0",
            "details_json": "TEXT NOT NULL DEFAULT '[]'",
        },
    }

    with engine.begin() as conn:
        for table_name, columns in migrations.items():
            existing = {
                row[1]
                for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").all()
            }
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                    )
        conn.exec_driver_sql(
            "UPDATE exam SET requested_questions = n_questions "
            "WHERE requested_questions = 0"
        )
        for exam_id, exam_name in conn.exec_driver_sql("SELECT id, exam_name FROM exam").all():
            display_name = format_exam_display_name(exam_name)
            if display_name != exam_name:
                conn.exec_driver_sql(
                    "UPDATE exam SET exam_name = ? WHERE id = ?",
                    (display_name, exam_id),
                )


def init_db():
    SQLModel.metadata.create_all(engine)
    _migrate_sqlite_schema()
    _ensure_admin_account()


def _ensure_admin_account():
    """Tạo admin account nếu chưa có — chạy mỗi lần startup."""
    from passlib.context import CryptContext
    _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin2026")
    admin_fullname = os.getenv("ADMIN_FULL_NAME", "Administrator")

    with Session(engine) as s:
        existing = s.get(UserAccount, admin_username)
        if existing is None:
            s.add(UserAccount(
                username=admin_username,
                hashed_password=_pwd.hash(admin_password),
                role="admin",
                full_name=admin_fullname,
                is_active=True,
            ))
            s.commit()
        elif existing.role != "admin":
            # Đảm bảo account admin luôn có đúng role
            existing.role = "admin"
            s.add(existing)
            s.commit()


def question_from_mcq(exam_id: str, mcq: dict, position: int = 0) -> Question:
    mcq = normalize_mcq_math(dict(mcq))
    evaluation = mcq.get("evaluation", {}) if isinstance(mcq, dict) else {}
    return Question(
        exam_id=exam_id,
        question_id=mcq.get("question_id", ""),
        position=position,
        question_text=mcq.get("question_text", ""),
        question_type=mcq.get("question_type", "single_correct"),
        options_json=_json_dumps(mcq.get("options", {})),
        correct_answers_json=_json_dumps(mcq.get("correct_answers", [])),
        correct_rationale=mcq.get("correct_rationale", ""),
        topic=mcq.get("topic", ""),
        difficulty=mcq.get("difficulty_label", mcq.get("difficulty", "G2")),
        quality_score=evaluation.get("quality_score", 0) if isinstance(evaluation, dict) else 0,
        evaluation_json=_json_dumps(evaluation),
        rag_strategy=mcq.get("rag_strategy", ""),
        chapter_id=mcq.get("chapter_id", ""),
        prompt_version=mcq.get("prompt_version", "v1.0"),
        raw_mcq_json=_json_dumps(mcq),
    )


def question_to_mcq(question: Question) -> dict:
    raw = _json_loads(question.raw_mcq_json, None)
    if isinstance(raw, dict):
        mcq = raw
    else:
        mcq = {
            "question_id": question.question_id,
            "question_text": question.question_text,
            "question_type": question.question_type or "single_correct",
            "options": _json_loads(question.options_json, {}),
            "correct_answers": _json_loads(question.correct_answers_json, []),
            "correct_rationale": question.correct_rationale,
            "topic": question.topic,
            "difficulty_label": question.difficulty,
            "evaluation": _json_loads(question.evaluation_json, {
                "overall_valid": True,
                "quality_score": question.quality_score,
                "fail_reasons": [],
            }),
            "rag_strategy": question.rag_strategy,
            "chapter_id": question.chapter_id,
            "prompt_version": question.prompt_version,
        }

    mcq.setdefault("question_id", question.question_id)
    mcq.setdefault("question_text", question.question_text)
    mcq.setdefault("question_type", question.question_type or "single_correct")
    mcq.setdefault("options", _json_loads(question.options_json, {}))
    mcq.setdefault("correct_answers", _json_loads(question.correct_answers_json, []))
    mcq.setdefault("topic", question.topic)
    mcq.setdefault("difficulty_label", question.difficulty)
    mcq.setdefault("evaluation", _json_loads(question.evaluation_json, {}))
    mcq.setdefault("rag_strategy", question.rag_strategy)
    mcq.setdefault("chapter_id", question.chapter_id)
    return normalize_mcq_math(mcq)


def get_exam_mcqs(session: Session, exam: Exam) -> list[dict]:
    questions = session.exec(
        select(Question)
        .where(Question.exam_id == exam.id)
        .order_by(Question.position, Question.question_id)
    ).all()
    return [question_to_mcq(question) for question in questions]


def get_user_question_history(
    session: Session,
    username: str,
    limit: int = 500,
) -> list[dict]:
    """Return recent successful questions for per-user duplicate prevention."""
    exams = session.exec(
        select(Exam)
        .where(Exam.created_by == username)
        .where(Exam.status == "success")
        .order_by(Exam.completed_at.desc(), Exam.created_at.desc())
    ).all()

    history: list[dict] = []
    for exam in exams:
        questions = session.exec(
            select(Question)
            .where(Question.exam_id == exam.id)
            .order_by(Question.position, Question.question_id)
        ).all()
        for question in questions:
            history.append(
                {
                    "question_id": question.question_id,
                    "question_text": question.question_text,
                    "topic": question.topic,
                    "chapter_id": question.chapter_id,
                    "exam_id": exam.id,
                    "exam_name": format_exam_display_name(exam.exam_name),
                    "created_at": exam.created_at.isoformat(),
                }
            )
            if len(history) >= limit:
                return history
    return history


def persist_generation_success(session: Session, task_id: str, result: dict) -> Optional[Exam]:
    exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
    if not exam:
        return None

    mcqs = result.get("mcqs", []) if isinstance(result, dict) else []
    failures = result.get("failures", []) if isinstance(result, dict) else []
    accepted = int(result.get("accepted", len(mcqs))) if isinstance(result, dict) else len(mcqs)
    failed = int(result.get("failed", len(failures))) if isinstance(result, dict) else len(failures)

    for question in session.exec(select(Question).where(Question.exam_id == exam.id)).all():
        session.delete(question)

    for idx, mcq in enumerate(mcqs):
        session.add(question_from_mcq(exam.id, mcq, position=idx))

    exam.status = "success"
    if isinstance(result, dict):
        exam.exam_name = format_exam_display_name(
            result.get("display_name") or result.get("exam_name") or exam.exam_name
        )
    else:
        exam.exam_name = format_exam_display_name(exam.exam_name)
    exam.n_questions = len(mcqs)
    exam.accepted_questions = accepted
    exam.failed_questions = failed
    if exam.requested_questions == 0:
        exam.requested_questions = accepted + failed
    exam.completed_at = datetime.utcnow()
    exam.output_file = result.get("output_file") if isinstance(result, dict) else None
    exam.error_message = None
    exam.failure_info_json = _json_dumps(failures)
    exam.quality_avg = (
        sum(
            m.get("evaluation", {}).get("quality_score", 0)
            for m in mcqs
            if isinstance(m, dict) and isinstance(m.get("evaluation", {}), dict)
        ) / len(mcqs)
        if mcqs else 0
    )
    session.add(exam)
    session.commit()
    session.refresh(exam)
    return exam


def persist_generation_failure(
    session: Session,
    task_id: str,
    error_message: str,
    failures: Optional[list[dict]] = None,
) -> Optional[Exam]:
    exam = session.exec(select(Exam).where(Exam.task_id == task_id)).first()
    if not exam:
        return None

    exam.status = "failed"
    exam.completed_at = datetime.utcnow()
    exam.error_message = error_message
    exam.failure_info_json = _json_dumps(failures or [])
    session.add(exam)
    session.commit()
    session.refresh(exam)
    return exam


def exam_summary(exam: Exam) -> dict:
    return {
        "id": exam.id,
        "task_id": exam.task_id,
        "created_by": exam.created_by,
        "exam_name": format_exam_display_name(exam.exam_name),
        "n_questions": exam.n_questions,
        "requested_questions": exam.requested_questions,
        "accepted_questions": exam.accepted_questions,
        "failed_questions": exam.failed_questions,
        "status": exam.status,
        "created_at": exam.created_at,
        "completed_at": exam.completed_at,
        "quality_avg": exam.quality_avg,
        "prompt_version": exam.prompt_version,
        "output_file": exam.output_file,
        "error_message": exam.error_message,
        "failures": _json_loads(exam.failure_info_json, []),
    }

def get_session():
    with Session(engine) as session:
        yield session
