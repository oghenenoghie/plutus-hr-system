import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator

from app.models.approval import (
    ApprovalDecisionType,
    ApprovalInstanceStatus,
    ApprovalRequestType,
    ApprovalStepEligibilityType,
)
from app.models.membership import Role


class ApprovalWorkflowStepInput(BaseModel):
    eligibility_type: ApprovalStepEligibilityType
    eligible_role: Role | None = None
    eligible_account_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_eligibility_fields(self) -> "ApprovalWorkflowStepInput":
        """Mirrors the DB CHECK constraint on approval_workflow_steps —
        enforced here too so a bad payload gets a clean 422 instead of an
        IntegrityError."""
        if self.eligibility_type == ApprovalStepEligibilityType.ROLE:
            if self.eligible_role is None or self.eligible_account_id is not None:
                raise ValueError("a 'role' step requires eligible_role and no eligible_account_id")
        elif self.eligibility_type in (
            ApprovalStepEligibilityType.DIRECT_MANAGER,
            ApprovalStepEligibilityType.DEPARTMENT_HEAD,
        ):
            if self.eligible_role is not None or self.eligible_account_id is not None:
                raise ValueError(
                    "direct_manager/department_head steps take no eligible_role or eligible_account_id"
                )
        elif self.eligibility_type == ApprovalStepEligibilityType.SPECIFIC_PERSON and (
            self.eligible_account_id is None or self.eligible_role is not None
        ):
            raise ValueError("a 'specific_person' step requires eligible_account_id and no eligible_role")
        return self


class ApprovalWorkflowStepOut(ApprovalWorkflowStepInput):
    id: uuid.UUID
    request_type: ApprovalRequestType
    step_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalInstanceDecisionOut(BaseModel):
    id: uuid.UUID
    step_order: int
    decision: ApprovalDecisionType
    decided_by_account_id: uuid.UUID | None
    decided_by_role: str | None
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalInstanceOut(BaseModel):
    id: uuid.UUID
    request_type: ApprovalRequestType
    request_id: uuid.UUID
    current_step: int
    status: ApprovalInstanceStatus
    created_at: datetime
    decided_at: datetime | None
    decisions: list[ApprovalInstanceDecisionOut]

    model_config = {"from_attributes": True}


class DecisionBody(BaseModel):
    comment: str | None = None
