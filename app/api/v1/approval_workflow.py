import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.approval_workflow import (
    ApprovalRequest,
    ApprovalStepDecision,
    ApprovalWorkflowTemplate,
)
from app.models.membership import Role
from app.schemas.approval_workflow import (
    ApprovalDecisionRequest,
    ApprovalRequestCreate,
    ApprovalRequestOut,
    ApprovalStepDecisionOut,
    ApprovalTemplateCreate,
    ApprovalTemplateOut,
    ApprovalTemplateUpdate,
)
from app.services.approval_workflow import (
    current_step_for,
    decide_step,
    register_template,
    start_approval,
)

router = APIRouter(prefix="/approval-workflows", tags=["approval-workflows"])

_MANAGE_TEMPLATES = require_roles(Role.ADMIN)
_START = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_template_or_404(db: Session, template_id: uuid.UUID) -> ApprovalWorkflowTemplate:
    template = db.get(ApprovalWorkflowTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="template not found")
    return template


def _get_request_or_404(db: Session, request_id: uuid.UUID) -> ApprovalRequest:
    request = db.get(ApprovalRequest, request_id)
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="approval request not found"
        )
    return request


@router.post("/templates", response_model=ApprovalTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: ApprovalTemplateCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE_TEMPLATES),
) -> ApprovalWorkflowTemplate:
    try:
        return register_template(db, org_id=claims.org_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/templates", response_model=list[ApprovalTemplateOut])
def list_templates(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE_TEMPLATES)
) -> list[ApprovalWorkflowTemplate]:
    return list(db.scalars(select(ApprovalWorkflowTemplate)))


@router.patch("/templates/{template_id}", response_model=ApprovalTemplateOut)
def update_template(
    template_id: uuid.UUID,
    body: ApprovalTemplateUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE_TEMPLATES),
) -> ApprovalWorkflowTemplate:
    template = _get_template_or_404(db, template_id)
    template.is_active = body.is_active
    db.add(template)
    db.flush()
    return template


@router.post("/requests", response_model=ApprovalRequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    body: ApprovalRequestCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_START),
) -> ApprovalRequest:
    try:
        return start_approval(db, org_id=claims.org_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/requests/{request_id}", response_model=ApprovalRequestOut)
def get_request(
    request_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(get_current_claims),
) -> ApprovalRequest:
    return _get_request_or_404(db, request_id)


@router.get("/requests/{request_id}/decisions", response_model=list[ApprovalStepDecisionOut])
def list_decisions(
    request_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(get_current_claims),
) -> list[ApprovalStepDecision]:
    _get_request_or_404(db, request_id)
    return list(
        db.scalars(
            select(ApprovalStepDecision)
            .where(ApprovalStepDecision.approval_request_id == request_id)
            .order_by(ApprovalStepDecision.created_at)
        )
    )


@router.post("/requests/{request_id}/decide", response_model=ApprovalRequestOut)
def decide(
    request_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> ApprovalRequest:
    request = _get_request_or_404(db, request_id)
    step = current_step_for(db, request)
    if claims.role != step.approver_role.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"this step requires a {step.approver_role.value}",
        )
    try:
        decide_step(
            db,
            request,
            decision=body.decision,
            decided_by=claims.account_id,
            comments=body.comments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return request
