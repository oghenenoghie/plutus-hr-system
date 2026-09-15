import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.membership import Role
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_question import QuizQuestion
from app.models.training_enrollment import TrainingEnrollment
from app.models.training_quiz import TrainingQuiz
from app.schemas.quizzes import (
    QuizAttemptOut,
    QuizAttemptSubmit,
    QuizCreate,
    QuizOut,
    QuizQuestionCreate,
    QuizQuestionForAttemptOut,
    QuizQuestionOut,
)
from app.services.quizzes import add_quiz_question, create_quiz, submit_quiz_attempt

router = APIRouter(tags=["learning"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT, Role.MANAGER, Role.EMPLOYEE, Role.AUDITOR)


def _get_quiz_or_404(db: Session, quiz_id: uuid.UUID) -> TrainingQuiz:
    quiz = db.get(TrainingQuiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quiz not found")
    return quiz


@router.post(
    "/training-courses/{course_id}/quizzes",
    response_model=QuizOut,
    status_code=status.HTTP_201_CREATED,
)
def create_course_quiz(
    course_id: uuid.UUID,
    body: QuizCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> TrainingQuiz:
    try:
        return create_quiz(db, org_id=claims.org_id, course_id=course_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/training-courses/{course_id}/quizzes", response_model=list[QuizOut])
def list_course_quizzes(
    course_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> list[TrainingQuiz]:
    return list(db.scalars(select(TrainingQuiz).where(TrainingQuiz.course_id == course_id)))


@router.post(
    "/quizzes/{quiz_id}/questions",
    response_model=QuizQuestionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_quiz_question(
    quiz_id: uuid.UUID,
    body: QuizQuestionCreate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> QuizQuestion:
    quiz = _get_quiz_or_404(db, quiz_id)
    try:
        return add_quiz_question(db, quiz, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/quizzes/{quiz_id}/questions", response_model=list[QuizQuestionOut])
def list_quiz_questions(
    quiz_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[QuizQuestion]:
    return list(
        db.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.created_at)
        )
    )


@router.get(
    "/quizzes/{quiz_id}/questions/for-attempt", response_model=list[QuizQuestionForAttemptOut]
)
def list_quiz_questions_for_attempt(
    quiz_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _employee: Employee = Depends(get_current_employee),
) -> list[QuizQuestion]:
    """The answer-key-free view an employee sees before answering."""
    return list(
        db.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.created_at)
        )
    )


@router.post(
    "/quizzes/{quiz_id}/attempts",
    response_model=QuizAttemptOut,
    status_code=status.HTTP_201_CREATED,
)
def create_quiz_attempt(
    quiz_id: uuid.UUID,
    body: QuizAttemptSubmit,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> QuizAttempt:
    quiz = _get_quiz_or_404(db, quiz_id)
    enrollment = db.scalar(
        select(TrainingEnrollment).where(
            TrainingEnrollment.course_id == quiz.course_id,
            TrainingEnrollment.employee_id == employee.id,
        )
    )
    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="employee is not enrolled in this quiz's course",
        )
    try:
        return submit_quiz_attempt(
            db, quiz, employee_id=employee.id, enrollment=enrollment, answers=body.answers
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/quizzes/{quiz_id}/attempts", response_model=list[QuizAttemptOut])
def list_quiz_attempts(
    quiz_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[QuizAttempt]:
    return list(
        db.scalars(
            select(QuizAttempt)
            .where(QuizAttempt.quiz_id == quiz_id)
            .order_by(QuizAttempt.created_at)
        )
    )
