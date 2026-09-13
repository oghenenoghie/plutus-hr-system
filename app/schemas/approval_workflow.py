import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.approval_workflow import ApprovalRequestStatus, StepDecision
from app.models.membership import Role


class ApprovalTemplateCreate(BaseModel):
    entity_type: str
    name: str
    approver_roles: list[Role]


class ApprovalTemplateUpdate(BaseModel):
    is_active: bool


class ApprovalStepOut(BaseModel):
    id: uuid.UUID
    sequence: int
    approver_role: Role

    model_config = {"from_attributes": True}


class ApprovalTemplateOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    entity_type: str
    name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalRequestCreate(BaseModel):
    entity_type: str
    entity_id: uuid.UUID


class ApprovalDecisionRequest(BaseModel):
    decision: StepDecision
    comments: str | None = None


class ApprovalStepDecisionOut(BaseModel):
    id: uuid.UUID
    step_sequence: int
    decision: StepDecision
    decided_by: uuid.UUID | None
    comments: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalRequestOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    template_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    current_step: int
    status: ApprovalRequestStatus
    created_at: datetime

    model_config = {"from_attributes": True}
