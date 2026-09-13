import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.quiz_grading import grade_quiz
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_question import QuizQuestion
from app.models.training_enrollment import TrainingEnrollment, TrainingEnrollmentStatus
from app.models.training_quiz import TrainingQuiz


def create_quiz(
    db: Session, *, org_id: uuid.UUID, course_id: uuid.UUID, title: str, passing_score: int = 70
) -> TrainingQuiz:
    if not 0 <= passing_score <= 100:
        raise ValueError("passing_score must be between 0 and 100")
    quiz = TrainingQuiz(
        org_id=org_id, course_id=course_id, title=title, passing_score=passing_score
    )
    db.add(quiz)
    db.flush()
    return quiz


def add_quiz_question(
    db: Session,
    quiz: TrainingQuiz,
    *,
    question_text: str,
    options: list[str],
    correct_option_index: int,
) -> QuizQuestion:
    if len(options) < 2:
        raise ValueError("a question needs at least two options")
    if not 0 <= correct_option_index < len(options):
        raise ValueError("correct_option_index is out of range for options")

    question = QuizQuestion(
        org_id=quiz.org_id,
        quiz_id=quiz.id,
        question_text=question_text,
        options=options,
        correct_option_index=correct_option_index,
    )
    db.add(question)
    db.flush()
    return question


def submit_quiz_attempt(
    db: Session,
    quiz: TrainingQuiz,
    *,
    employee_id: uuid.UUID,
    enrollment: TrainingEnrollment,
    answers: list[int],
) -> QuizAttempt:
    if enrollment.employee_id != employee_id:
        raise ValueError("this enrollment does not belong to this employee")

    questions = list(
        db.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_id == quiz.id)
            .order_by(QuizQuestion.created_at)
        )
    )
    correct_indices = [q.correct_option_index for q in questions]
    score, passed = grade_quiz(correct_indices, answers, passing_score=quiz.passing_score)

    attempt = QuizAttempt(
        org_id=quiz.org_id,
        quiz_id=quiz.id,
        employee_id=employee_id,
        enrollment_id=enrollment.id,
        answers=answers,
        score=score,
        passed=passed,
    )
    db.add(attempt)

    if passed:
        enrollment.status = TrainingEnrollmentStatus.COMPLETED
        enrollment.completed_date = datetime.now(UTC).date()
        enrollment.score = score
        db.add(enrollment)

    db.flush()
    return attempt
