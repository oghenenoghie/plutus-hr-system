import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.candidate import Candidate
from app.models.job_posting import JobPosting
from app.models.membership import Role
from app.schemas.candidates import CandidateCreate, CandidateOut
from app.schemas.job_postings import JobPostingCreate, JobPostingOut, JobPostingUpdate
from app.services.candidates import register_candidate
from app.services.job_postings import register_job_posting

router = APIRouter(prefix="/job-postings", tags=["recruitment"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_job_posting_or_404(db: Session, job_posting_id: uuid.UUID) -> JobPosting:
    job_posting = db.get(JobPosting, job_posting_id)
    if job_posting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job posting not found")
    return job_posting


@router.post("", response_model=JobPostingOut, status_code=status.HTTP_201_CREATED)
def create_job_posting(
    body: JobPostingCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> JobPosting:
    return register_job_posting(db, org_id=claims.org_id, **body.model_dump())


@router.get("", response_model=list[JobPostingOut])
def list_job_postings(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[JobPosting]:
    return list(db.scalars(select(JobPosting)))


@router.get("/{job_posting_id}", response_model=JobPostingOut)
def get_job_posting(
    job_posting_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> JobPosting:
    return _get_job_posting_or_404(db, job_posting_id)


@router.patch("/{job_posting_id}", response_model=JobPostingOut)
def update_job_posting(
    job_posting_id: uuid.UUID,
    body: JobPostingUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> JobPosting:
    job_posting = _get_job_posting_or_404(db, job_posting_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(job_posting, field, value)
    db.add(job_posting)
    db.flush()
    return job_posting


@router.post(
    "/{job_posting_id}/candidates", response_model=CandidateOut, status_code=status.HTTP_201_CREATED
)
def create_candidate(
    job_posting_id: uuid.UUID,
    body: CandidateCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Candidate:
    _get_job_posting_or_404(db, job_posting_id)
    return register_candidate(
        db, org_id=claims.org_id, job_posting_id=job_posting_id, **body.model_dump()
    )


@router.get("/{job_posting_id}/candidates", response_model=list[CandidateOut])
def list_candidates_for_posting(
    job_posting_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> list[Candidate]:
    _get_job_posting_or_404(db, job_posting_id)
    return list(db.scalars(select(Candidate).where(Candidate.job_posting_id == job_posting_id)))
