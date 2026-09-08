from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.approval import ApprovalRequestType, ApprovalWorkflowStep
from app.models.membership import Role
from app.schemas.approvals import ApprovalWorkflowStepInput, ApprovalWorkflowStepOut
from app.services.approvals import get_configured_steps, replace_workflow_steps

router = APIRouter(prefix="/approval-workflow-steps", tags=["approval-workflows"])

_MANAGE = require_roles(Role.ADMIN)


@router.get("/{request_type}", response_model=list[ApprovalWorkflowStepOut])
def list_workflow_steps(
    request_type: ApprovalRequestType,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[ApprovalWorkflowStep]:
    return get_configured_steps(db, org_id=claims.org_id, request_type=request_type)


@router.put("/{request_type}", response_model=list[ApprovalWorkflowStepOut])
def replace_workflow_steps_endpoint(
    request_type: ApprovalRequestType,
    body: list[ApprovalWorkflowStepInput],
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[ApprovalWorkflowStep]:
    try:
        return replace_workflow_steps(
            db, org_id=claims.org_id, request_type=request_type, steps=body
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
