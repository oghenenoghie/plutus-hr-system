import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.membership import Role
from app.models.performance_review import PerformanceReview
from app.schemas.performance_reviews import (
    PerformanceReviewAcknowledge,
    PerformanceReviewCreate,
    PerformanceReviewOut,
    PerformanceReviewSubmit,
)
from app.services.performance_reviews import (
    acknowledge_performance_review,
    register_performance_review,
    submit_performance_review,
)

router = APIRouter(prefix="/performance-reviews", tags=["performance"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_review_or_404(db: Session, review_id: uuid.UUID) -> PerformanceReview:
    review = db.get(PerformanceReview, review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="performance review not found"
        )
    return review


def _requester_can_manage(db: Session, claims: TokenClaims, review: PerformanceReview) -> None:
    """ADMIN/PAYROLL_MANAGER can manage any review; a MANAGER only one for
    their own direct report."""
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        employee = db.get(Employee, review.employee_id)
        if manager is not None and employee is not None and employee.manager_id == manager.id:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="not authorised to manage this review"
    )


@router.post("", response_model=PerformanceReviewOut, status_code=status.HTTP_201_CREATED)
def create_performance_review(
    body: PerformanceReviewCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> PerformanceReview:
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        employee = db.get(Employee, body.employee_id)
        if manager is None or employee is None or employee.manager_id != manager.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not authorised to create a review for this employee",
            )
    try:
        return register_performance_review(db, org_id=claims.org_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/me", response_model=list[PerformanceReviewOut])
def list_my_performance_reviews(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[PerformanceReview]:
    return list(
        db.scalars(
            select(PerformanceReview)
            .where(PerformanceReview.employee_id == employee.id)
            .order_by(PerformanceReview.period_start.desc())
        )
    )


@router.get("", response_model=list[PerformanceReviewOut])
def list_performance_reviews(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[PerformanceReview]:
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return list(db.scalars(select(PerformanceReview)))

    manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
    if manager is None:
        return []
    report_ids = select(Employee.id).where(Employee.manager_id == manager.id)
    return list(
        db.scalars(select(PerformanceReview).where(PerformanceReview.employee_id.in_(report_ids)))
    )


@router.get("/{review_id}", response_model=PerformanceReviewOut)
def get_performance_review(
    review_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW_LIST),
) -> PerformanceReview:
    review = _get_review_or_404(db, review_id)
    _requester_can_manage(db, claims, review)
    return review


@router.post("/{review_id}/submit", response_model=PerformanceReviewOut)
def submit_review(
    review_id: uuid.UUID,
    body: PerformanceReviewSubmit,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> PerformanceReview:
    review = _get_review_or_404(db, review_id)
    _requester_can_manage(db, claims, review)
    try:
        submit_performance_review(db, review, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return review


@router.post("/{review_id}/acknowledge", response_model=PerformanceReviewOut)
def acknowledge_review(
    review_id: uuid.UUID,
    body: PerformanceReviewAcknowledge,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> PerformanceReview:
    review = _get_review_or_404(db, review_id)
    if review.employee_id != employee.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not authorised to acknowledge this review",
        )
    try:
        acknowledge_performance_review(db, review, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return review
