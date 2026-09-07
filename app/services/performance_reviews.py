import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.performance_review import PerformanceReview, PerformanceReviewStatus


def register_performance_review(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    reviewer_id: uuid.UUID | None = None,
    period_start: date,
    period_end: date,
    goals: str | None = None,
) -> PerformanceReview:
    if period_end < period_start:
        raise ValueError("period_end must not be before period_start")

    review = PerformanceReview(
        org_id=org_id,
        employee_id=employee_id,
        reviewer_id=reviewer_id,
        period_start=period_start,
        period_end=period_end,
        goals=goals,
    )
    db.add(review)
    db.flush()
    return review


def submit_performance_review(
    db: Session,
    review: PerformanceReview,
    *,
    rating: int | None = None,
    manager_comments: str | None = None,
) -> PerformanceReview:
    if review.status != PerformanceReviewStatus.DRAFT:
        raise ValueError(f"performance review is {review.status.value}, not draft")

    review.rating = rating
    review.manager_comments = manager_comments
    review.status = PerformanceReviewStatus.SUBMITTED
    review.submitted_date = datetime.now(UTC).date()
    db.add(review)
    return review


def acknowledge_performance_review(
    db: Session, review: PerformanceReview, *, employee_comments: str | None = None
) -> PerformanceReview:
    if review.status != PerformanceReviewStatus.SUBMITTED:
        raise ValueError(f"performance review is {review.status.value}, not submitted")

    review.employee_comments = employee_comments
    review.status = PerformanceReviewStatus.ACKNOWLEDGED
    review.acknowledged_date = datetime.now(UTC).date()
    db.add(review)
    return review
