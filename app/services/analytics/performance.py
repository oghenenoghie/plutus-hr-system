"""Performance and learning analytics. Ratings are integers with no scale
fixed by the application, so they are shown as recorded: never rescaled,
and never generated for reviews that don't have one. Definitions:
docs/analytics-metrics.md §6.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.performance_review import PerformanceReview, PerformanceReviewStatus
from app.models.training_enrollment import TrainingEnrollment, TrainingEnrollmentStatus
from app.schemas.analytics import Metric, PerformanceOut, Unit
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.common import (
    NO_DEPARTMENT,
    average,
    breakdown,
    build_meta,
    department_names,
    employee_conditions,
    metric,
    percent,
    row,
    series,
    trend,
)
from app.services.analytics.filters import AnalyticsFilters, month_keys

HREF = "/analytics/performance"

_COMPLETE = PerformanceReview.status.in_(
    (PerformanceReviewStatus.SUBMITTED, PerformanceReviewStatus.ACKNOWLEDGED)
)
_REVIEW_LABELS = {
    PerformanceReviewStatus.DRAFT: "Draft",
    PerformanceReviewStatus.SUBMITTED: "Submitted",
    PerformanceReviewStatus.ACKNOWLEDGED: "Acknowledged",
}
_TRAINING_LABELS = {
    TrainingEnrollmentStatus.ENROLLED: "Enrolled",
    TrainingEnrollmentStatus.IN_PROGRESS: "In progress",
    TrainingEnrollmentStatus.COMPLETED: "Completed",
    TrainingEnrollmentStatus.FAILED: "Failed",
}


def _reviews(filters: AnalyticsFilters, org_id: uuid.UUID, *columns: Any) -> Any:
    return (
        select(*columns)
        .select_from(PerformanceReview)
        .join(Employee, PerformanceReview.employee_id == Employee.id)
        .where(
            PerformanceReview.org_id == org_id,
            PerformanceReview.period_end.between(filters.date_from, filters.date_to),
            *employee_conditions(filters),
        )
    )


def _enrollments(filters: AnalyticsFilters, org_id: uuid.UUID, *columns: Any) -> Any:
    return (
        select(*columns)
        .select_from(TrainingEnrollment)
        .join(Employee, TrainingEnrollment.employee_id == Employee.id)
        .where(
            TrainingEnrollment.org_id == org_id,
            TrainingEnrollment.enrolled_date.between(filters.date_from, filters.date_to),
            *employee_conditions(filters),
        )
    )


def _period(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> dict[str, int]:
    reviews, complete, rated = db.execute(
        _reviews(
            filters,
            org_id,
            func.count(),
            func.count().filter(_COMPLETE),
            func.count(PerformanceReview.rating).filter(_COMPLETE),
        )
    ).one()
    enrollments, completed = db.execute(
        _enrollments(
            filters,
            org_id,
            func.count(),
            func.count().filter(TrainingEnrollment.status == TrainingEnrollmentStatus.COMPLETED),
        )
    ).one()
    return {
        "reviews": reviews,
        "complete": complete,
        "rated": rated,
        "enrollments": enrollments,
        "training_completed": completed,
    }


def performance(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> PerformanceOut:
    org_id = access.org_id
    months = month_keys(filters.date_from, filters.date_to)
    now = _period(db, org_id, filters)
    previous_filters = filters.comparison()
    before = _period(db, org_id, previous_filters) if previous_filters else {}
    compare = previous_filters is not None

    def rate(figures: dict[str, int], numerator: str, denominator: str) -> float | None:
        return percent(figures[numerator], figures[denominator]) if figures else None

    kpis: list[Metric] = [
        metric(
            key="reviews",
            label="Reviews in the period",
            unit=Unit.COUNT,
            value=now["reviews"],
            previous=before.get("reviews"),
            compare=compare,
            definition="Performance reviews whose review period ends in the range.",
            href=HREF,
            dataset="reviews",
        ),
        metric(
            key="review_completion",
            label="Review completion rate",
            unit=Unit.PERCENT,
            value=rate(now, "complete", "reviews"),
            previous=rate(before, "complete", "reviews"),
            compare=compare,
            higher_is_better=True,
            definition="Submitted or acknowledged reviews ÷ all reviews whose period ends in the "
            "range × 100.",
            href=HREF,
            dataset="reviews",
        ),
        metric(
            key="rated_reviews",
            label="Completed reviews with a rating",
            unit=Unit.COUNT,
            value=now["rated"],
            previous=before.get("rated"),
            compare=compare,
            definition="Submitted or acknowledged reviews that carry a rating.",
            href=HREF,
            dataset="reviews",
        ),
        metric(
            key="enrollments",
            label="Training enrolments",
            unit=Unit.COUNT,
            value=now["enrollments"],
            previous=before.get("enrollments"),
            compare=compare,
            definition="Course enrolments whose enrolment date falls in the period.",
            href=HREF,
        ),
        metric(
            key="training_completion",
            label="Training completion rate",
            unit=Unit.PERCENT,
            value=rate(now, "training_completed", "enrollments"),
            previous=rate(before, "training_completed", "enrollments"),
            compare=compare,
            higher_is_better=True,
            definition="Completed ÷ all enrolments made in the period × 100.",
            href=HREF,
        ),
    ]

    month = func.to_char(PerformanceReview.period_end, "YYYY-MM")
    monthly = {
        key: percent(complete, total)
        for key, total, complete in db.execute(
            _reviews(filters, org_id, month, func.count(), func.count().filter(_COMPLETE)).group_by(
                month
            )
        ).tuples()
    }
    by_status = [
        row(status.value, _REVIEW_LABELS[status], count, count=count)
        for status, count in db.execute(
            _reviews(filters, org_id, PerformanceReview.status, func.count()).group_by(
                PerformanceReview.status
            )
        ).tuples()
    ]
    ratings = [
        row(str(rating), str(rating), count, count=count)
        for rating, count in db.execute(
            _reviews(filters, org_id, PerformanceReview.rating, func.count())
            .where(_COMPLETE, PerformanceReview.rating.is_not(None))
            .group_by(PerformanceReview.rating)
            .order_by(PerformanceReview.rating)
        ).tuples()
    ]
    names = department_names(db, org_id)
    # Every caller is protected here: a department's average of one or two
    # ratings would be those people's ratings.
    by_department = [
        row(
            dept or "none",
            names.get(dept, NO_DEPARTMENT) if dept else NO_DEPARTMENT,
            average(int(total), count),
            count=count,
            protect=True,
        )
        for dept, total, count in db.execute(
            _reviews(
                filters,
                org_id,
                Employee.department_id,
                func.sum(PerformanceReview.rating),
                func.count(PerformanceReview.rating),
            )
            .where(_COMPLETE, PerformanceReview.rating.is_not(None))
            .group_by(Employee.department_id)
        ).tuples()
    ]
    training = [
        row(status.value, _TRAINING_LABELS[status], count, count=count)
        for status, count in db.execute(
            _enrollments(filters, org_id, TrainingEnrollment.status, func.count()).group_by(
                TrainingEnrollment.status
            )
        ).tuples()
    ]

    return PerformanceOut(
        meta=build_meta(
            "performance",
            filters,
            access,
            notes=[
                "Ratings are shown as recorded; the application doesn't fix a rating scale.",
                "A department average of fewer than 3 ratings is hidden.",
            ],
        ),
        kpis=kpis,
        completion_trend=trend(
            key="completion",
            title="Review completion rate",
            unit=Unit.PERCENT,
            series_list=[series("completion", "Completion rate", months, monthly, missing=None)],
            definition="Submitted or acknowledged ÷ all reviews, by the month the review "
            "period ends. A month with no reviews has no rate.",
            dataset="reviews",
        ),
        reviews_by_status=breakdown(
            key="reviews_by_status",
            title="Reviews by status",
            unit=Unit.COUNT,
            rows=by_status,
            definition="Reviews whose period ends in the range, by status.",
            dataset="reviews",
        ),
        rating_distribution=breakdown(
            key="rating_distribution",
            title="Rating distribution",
            unit=Unit.COUNT,
            rows=ratings,
            definition="Completed reviews by the rating given. Reviews without a rating are "
            "left out, not counted as zero.",
            sort=False,
        ),
        rating_by_department=breakdown(
            key="rating_by_department",
            title="Average rating by department",
            unit=Unit.RATING,
            rows=by_department,
            definition="Mean rating of completed, rated reviews, by each employee's current "
            "department; the count is rated reviews. Fewer than 3 is hidden.",
        ),
        training_by_status=breakdown(
            key="training_by_status",
            title="Training enrolments by status",
            unit=Unit.COUNT,
            rows=training,
            definition="Enrolments made in the period, by their status today.",
        ),
    )
