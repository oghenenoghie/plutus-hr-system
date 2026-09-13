import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.approval_workflow import advance
from app.models.approval_workflow import (
    ApprovalRequest,
    ApprovalRequestStatus,
    ApprovalStepDecision,
    ApprovalWorkflowStep,
    ApprovalWorkflowTemplate,
    StepDecision,
)
from app.models.membership import Role


def register_template(
    db: Session, *, org_id: uuid.UUID, entity_type: str, name: str, approver_roles: list[Role]
) -> ApprovalWorkflowTemplate:
    if not approver_roles:
        raise ValueError("a template needs at least one step")
    existing_active = db.scalar(
        select(ApprovalWorkflowTemplate).where(
            ApprovalWorkflowTemplate.org_id == org_id,
            ApprovalWorkflowTemplate.entity_type == entity_type,
            ApprovalWorkflowTemplate.is_active.is_(True),
        )
    )
    if existing_active is not None:
        raise ValueError(
            f"an active template already exists for entity_type {entity_type!r} "
            "— deactivate it first"
        )

    template = ApprovalWorkflowTemplate(org_id=org_id, entity_type=entity_type, name=name)
    db.add(template)
    db.flush()
    db.add_all(
        ApprovalWorkflowStep(
            org_id=org_id, template_id=template.id, sequence=sequence, approver_role=role
        )
        for sequence, role in enumerate(approver_roles, start=1)
    )
    db.flush()
    return template


def _steps_for(db: Session, template_id: uuid.UUID) -> list[ApprovalWorkflowStep]:
    return list(
        db.scalars(
            select(ApprovalWorkflowStep)
            .where(ApprovalWorkflowStep.template_id == template_id)
            .order_by(ApprovalWorkflowStep.sequence)
        )
    )


def start_approval(
    db: Session, *, org_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
) -> ApprovalRequest:
    template = db.scalar(
        select(ApprovalWorkflowTemplate).where(
            ApprovalWorkflowTemplate.org_id == org_id,
            ApprovalWorkflowTemplate.entity_type == entity_type,
            ApprovalWorkflowTemplate.is_active.is_(True),
        )
    )
    if template is None:
        raise ValueError(f"no active approval workflow template for entity_type {entity_type!r}")

    existing = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.entity_type == entity_type, ApprovalRequest.entity_id == entity_id
        )
    )
    if existing is not None:
        raise ValueError("an approval request already exists for this entity")

    request = ApprovalRequest(
        org_id=org_id, template_id=template.id, entity_type=entity_type, entity_id=entity_id
    )
    db.add(request)
    db.flush()
    return request


def current_step_for(db: Session, request: ApprovalRequest) -> ApprovalWorkflowStep:
    steps = _steps_for(db, request.template_id)
    return next(step for step in steps if step.sequence == request.current_step)


def decide_step(
    db: Session,
    request: ApprovalRequest,
    *,
    decision: StepDecision,
    decided_by: uuid.UUID | None,
    comments: str | None = None,
) -> ApprovalRequest:
    if request.status != ApprovalRequestStatus.PENDING:
        raise ValueError(f"approval request is already {request.status.value}")

    steps = _steps_for(db, request.template_id)
    db.add(
        ApprovalStepDecision(
            org_id=request.org_id,
            approval_request_id=request.id,
            step_sequence=request.current_step,
            decision=decision,
            decided_by=decided_by,
            comments=comments,
        )
    )
    next_step, new_status = advance(request.current_step, len(steps), decision)
    request.current_step = next_step
    request.status = new_status
    db.add(request)
    db.flush()
    return request
