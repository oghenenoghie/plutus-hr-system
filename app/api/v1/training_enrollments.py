import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.membership import Role
from app.models.training_enrollment import TrainingEnrollment
from app.schemas.training_enrollments import TrainingEnrollmentOut, TrainingEnrollmentUpdate

router = APIRouter(prefix="/training-enrollments", tags=["learning"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_enrollment_or_404(db: Session, enrollment_id: uuid.UUID) -> TrainingEnrollment:
    enrollment = db.get(TrainingEnrollment, enrollment_id)
    if enrollment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="enrollment not found")
    return enrollment


@router.get("/me", response_model=list[TrainingEnrollmentOut])
def list_my_enrollments(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[TrainingEnrollment]:
    return list(
        db.scalars(
            select(TrainingEnrollment)
            .where(TrainingEnrollment.employee_id == employee.id)
            .order_by(TrainingEnrollment.enrolled_date.desc())
        )
    )


@router.get("/{enrollment_id}", response_model=TrainingEnrollmentOut)
def get_enrollment(
    enrollment_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> TrainingEnrollment:
    return _get_enrollment_or_404(db, enrollment_id)


@router.patch("/{enrollment_id}", response_model=TrainingEnrollmentOut)
def update_enrollment(
    enrollment_id: uuid.UUID,
    body: TrainingEnrollmentUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> TrainingEnrollment:
    enrollment = _get_enrollment_or_404(db, enrollment_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(enrollment, field, value)
    db.add(enrollment)
    db.flush()
    return enrollment
