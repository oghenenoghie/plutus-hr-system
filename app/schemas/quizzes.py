import uuid
from datetime import datetime

from pydantic import BaseModel


class QuizCreate(BaseModel):
    title: str
    passing_score: int = 70


class QuizOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    course_id: uuid.UUID
    title: str
    passing_score: int
    created_at: datetime

    model_config = {"from_attributes": True}


class QuizQuestionCreate(BaseModel):
    question_text: str
    options: list[str]
    correct_option_index: int


class QuizQuestionOut(BaseModel):
    """Admin-facing view — includes the answer key. Never served to an
    employee about to take the quiz; see QuizQuestionForAttemptOut."""

    id: uuid.UUID
    quiz_id: uuid.UUID
    question_text: str
    options: list[str]
    correct_option_index: int
    created_at: datetime

    model_config = {"from_attributes": True}


class QuizQuestionForAttemptOut(BaseModel):
    """What an employee sees before answering — no correct_option_index,
    so taking the quiz can't leak the answer key."""

    id: uuid.UUID
    question_text: str
    options: list[str]

    model_config = {"from_attributes": True}


class QuizAttemptSubmit(BaseModel):
    answers: list[int]


class QuizAttemptOut(BaseModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    employee_id: uuid.UUID
    enrollment_id: uuid.UUID
    answers: list[int]
    score: int
    passed: bool
    created_at: datetime

    model_config = {"from_attributes": True}
