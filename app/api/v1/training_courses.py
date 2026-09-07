import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.training_course import TrainingCourse
from app.models.training_enrollment import TrainingEnrollment
from app.schemas.training_courses import (
    TrainingCourseCreate,
    TrainingCourseOut,
    TrainingCourseUpdate,
)
from app.schemas.training_enrollments import TrainingEnrollmentCreate, TrainingEnrollmentOut
from app.services.training_courses import register_training_course
from app.services.training_enrollments import register_training_enrollment

router = APIRouter(prefix="/training-courses", tags=["learning"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER, Role.EMPLOYEE)
_VIEW_ENROLLMENTS = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_course_or_404(db: Session, course_id: uuid.UUID) -> TrainingCourse:
    course = db.get(TrainingCourse, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="training course not found"
        )
    return course


@router.post("", response_model=TrainingCourseOut, status_code=status.HTTP_201_CREATED)
def create_training_course(
    body: TrainingCourseCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> TrainingCourse:
    try:
        return register_training_course(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a training course with this title already exists",
        ) from exc


@router.get("", response_model=list[TrainingCourseOut])
def list_training_courses(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[TrainingCourse]:
    return list(db.scalars(select(TrainingCourse)))


@router.get("/{course_id}", response_model=TrainingCourseOut)
def get_training_course(
    course_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> TrainingCourse:
    return _get_course_or_404(db, course_id)


@router.patch("/{course_id}", response_model=TrainingCourseOut)
def update_training_course(
    course_id: uuid.UUID,
    body: TrainingCourseUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> TrainingCourse:
    course = _get_course_or_404(db, course_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    db.add(course)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a training course with this title already exists",
        ) from exc
    return course


@router.post(
    "/{course_id}/enrollments",
    response_model=TrainingEnrollmentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_enrollment(
    course_id: uuid.UUID,
    body: TrainingEnrollmentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> TrainingEnrollment:
    _get_course_or_404(db, course_id)
    return register_training_enrollment(
        db, org_id=claims.org_id, course_id=course_id, **body.model_dump()
    )


@router.get("/{course_id}/enrollments", response_model=list[TrainingEnrollmentOut])
def list_enrollments_for_course(
    course_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_ENROLLMENTS),
) -> list[TrainingEnrollment]:
    _get_course_or_404(db, course_id)
    return list(
        db.scalars(select(TrainingEnrollment).where(TrainingEnrollment.course_id == course_id))
    )
