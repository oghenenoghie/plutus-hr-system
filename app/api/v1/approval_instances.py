import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_tenant_db
from app.core.security import TokenClaims
from app.models.approval import ApprovalInstance, ApprovalRequestType
from app.models.membership import Role
from app.schemas.approvals import ApprovalInstanceOut
from app.services.approvals import get_instance_with_decisions

router = APIRouter(prefix="/approval-instances", tags=["approval-workflows"])


@router.get("/{request_type}/{request_id}", response_model=ApprovalInstanceOut | None)
def get_approval_instance(
    request_type: ApprovalRequestType,
    request_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> ApprovalInstance | None:
    # Mirrors each flow's own list-endpoint viewer set: ADMIN/PAYROLL_MANAGER
    # always; MANAGER too, except for bills (which have no manager-relevant
    # requester concept at all).
    allowed = {Role.ADMIN.value, Role.PAYROLL_MANAGER.value}
    if request_type != ApprovalRequestType.BILL:
        allowed.add(Role.MANAGER.value)
    if claims.role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not authorised to view this history"
        )
    return get_instance_with_decisions(db, request_type=request_type, request_id=request_id)
