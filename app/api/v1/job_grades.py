import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.job_grade import JobGrade
from app.models.membership import Role
from app.schemas.job_grades import JobGradeCreate, JobGradeOut, JobGradeUpdate
from app.services.job_grades import register_job_grade

router = APIRouter(prefix="/job-grades", tags=["job-grades"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_job_grade_or_404(db: Session, job_grade_id: uuid.UUID) -> JobGrade:
    job_grade = db.get(JobGrade, job_grade_id)
    if job_grade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job grade not found")
    return job_grade


@router.post("", response_model=JobGradeOut, status_code=status.HTTP_201_CREATED)
def create_job_grade(
    body: JobGradeCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> JobGrade:
    try:
        return register_job_grade(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a job grade with this name already exists",
        ) from exc


@router.get("", response_model=list[JobGradeOut])
def list_job_grades(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[JobGrade]:
    return list(db.scalars(select(JobGrade)))


@router.get("/{job_grade_id}", response_model=JobGradeOut)
def get_job_grade(
    job_grade_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> JobGrade:
    return _get_job_grade_or_404(db, job_grade_id)


@router.patch("/{job_grade_id}", response_model=JobGradeOut)
def update_job_grade(
    job_grade_id: uuid.UUID,
    body: JobGradeUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> JobGrade:
    job_grade = _get_job_grade_or_404(db, job_grade_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(job_grade, field, value)
    db.add(job_grade)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a job grade with this name already exists",
        ) from exc
    return job_grade
