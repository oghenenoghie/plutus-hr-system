import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.training_course_attachment import TrainingCourseAttachment
from app.schemas.training_course_attachments import (
    TrainingCourseAttachmentCreate,
    TrainingCourseAttachmentOut,
)
from app.services.training_course_attachments import add_course_attachment

router = APIRouter(prefix="/training-courses", tags=["learning"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT)
_VIEW_LIST = require_roles(
    Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT, Role.MANAGER, Role.EMPLOYEE, Role.AUDITOR
)


@router.post(
    "/{course_id}/attachments",
    response_model=TrainingCourseAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_course_attachment(
    course_id: uuid.UUID,
    body: TrainingCourseAttachmentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> TrainingCourseAttachment:
    return add_course_attachment(db, org_id=claims.org_id, course_id=course_id, **body.model_dump())


@router.get("/{course_id}/attachments", response_model=list[TrainingCourseAttachmentOut])
def list_course_attachments(
    course_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> list[TrainingCourseAttachment]:
    return list(
        db.scalars(
            select(TrainingCourseAttachment).where(TrainingCourseAttachment.course_id == course_id)
        )
    )
