from sqlmodel import SQLModel, Field, Session, create_engine
from datetime import datetime
from typing import Optional
from api.core.config import settings
import uuid, json

engine = create_engine(settings.DATABASE_URL, echo=False)

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

class Question(SQLModel, table=True):
    id:              str = Field(default_factory=lambda: str(uuid.uuid4())[:8], primary_key=True)
    exam_id:         str = Field(index=True)
    question_id:     str = Field(index=True)
    question_text:   str
    options_json:    str  # JSON string
    correct_answers_json: str
    topic:           str
    difficulty:      str = "G2"
    quality_score:   float = 0.0
    rag_strategy:    str = ""
    chapter_id:      str = ""
    prompt_version:  str = "v1.0"

class QuizAttempt(SQLModel, table=True):
    id:           str = Field(default_factory=lambda: str(uuid.uuid4())[:8], primary_key=True)
    student_id:   str = Field(index=True)
    exam_id:      str = Field(index=True)
    answers_json: str  # JSON
    score:        float
    n_correct:    int
    n_total:      int
    submitted_at: datetime = Field(default_factory=datetime.utcnow)

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
