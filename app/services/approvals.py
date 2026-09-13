import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.models.approval import (
    ApprovalDecisionType,
    ApprovalInstance,
    ApprovalInstanceDecision,
    ApprovalInstanceStatus,
    ApprovalRequestType,
    ApprovalStepEligibilityType,
    ApprovalWorkflowStep,
)
from app.models.department import Department
from app.models.employee import Employee
from app.models.membership import Role
from app.schemas.approvals import ApprovalWorkflowStepInput

# direct_manager/department_head steps have no meaning for a request type
# with no requester (bills) — rejected at config-write time.
_MANAGER_RELATIONSHIP_TYPES = frozenset(
    {ApprovalStepEligibilityType.DIRECT_MANAGER, ApprovalStepEligibilityType.DEPARTMENT_HEAD}
)


def _resolve_employee_for_account(db: Session, account_id: uuid.UUID) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.account_id == account_id))


def get_configured_steps(
    db: Session, *, org_id: uuid.UUID, request_type: ApprovalRequestType
) -> list[ApprovalWorkflowStep]:
    return list(
        db.scalars(
            select(ApprovalWorkflowStep)
            .where(
                ApprovalWorkflowStep.org_id == org_id,
                ApprovalWorkflowStep.request_type == request_type,
            )
            .order_by(ApprovalWorkflowStep.step_order)
        )
    )


def is_eligible_approver(
    db: Session,
    *,
    step: ApprovalWorkflowStep | None,
    claims: TokenClaims,
    requester_employee_id: uuid.UUID | None,
) -> bool:
    """step=None means the org has zero configured steps for this request
    type — replicate that flow's original hardcoded gate exactly: ADMIN/
    PAYROLL_MANAGER decide anything; MANAGER only their own direct report
    (only meaningful when there's a requester at all — bills have none, so
    a MANAGER is never eligible for a zero-config bill)."""
    if step is None:
        if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
            return True
        if claims.role == Role.MANAGER.value and requester_employee_id is not None:
            manager = _resolve_employee_for_account(db, claims.account_id)
            if manager is None:
                return False
            requester = db.get(Employee, requester_employee_id)
            return requester is not None and requester.manager_id == manager.id
        return False

    if step.eligibility_type == ApprovalStepEligibilityType.ROLE:
        return step.eligible_role is not None and claims.role == step.eligible_role.value

    if step.eligibility_type == ApprovalStepEligibilityType.SPECIFIC_PERSON:
        return step.eligible_account_id == claims.account_id

    # DIRECT_MANAGER / DEPARTMENT_HEAD both require a requester to resolve
    # against. replace_workflow_steps already refuses to configure these for
    # a requester-less request type (bills), so reaching here with none is a
    # config bug rather than a normal decision path — deny, don't raise.
    if requester_employee_id is None:
        return False

    requester = db.get(Employee, requester_employee_id)
    if requester is None:
        return False

    decider = _resolve_employee_for_account(db, claims.account_id)
    if decider is None:
        return False

    if step.eligibility_type == ApprovalStepEligibilityType.DIRECT_MANAGER:
        return requester.manager_id == decider.id

    if step.eligibility_type == ApprovalStepEligibilityType.DEPARTMENT_HEAD:
        if requester.department_id is None:
            return False
        department = db.get(Department, requester.department_id)
        return department is not None and department.manager_id == decider.id

    return False


def get_or_create_instance(
    db: Session,
    *,
    org_id: uuid.UUID,
    request_type: ApprovalRequestType,
    request_id: uuid.UUID,
    requester_employee_id: uuid.UUID | None,
) -> ApprovalInstance:
    """Idempotent. Called eagerly at submission time so a request's approval
    state is visible from the moment it exists, and defensively inside
    decide() for any request submitted before this feature existed."""
    instance = db.scalar(
        select(ApprovalInstance).where(
            ApprovalInstance.request_type == request_type,
            ApprovalInstance.request_id == request_id,
        )
    )
    if instance is not None:
        return instance

    instance = ApprovalInstance(
        org_id=org_id,
        request_type=request_type,
        request_id=request_id,
        requester_employee_id=requester_employee_id,
    )
    db.add(instance)
    db.flush()
    return instance


def decide(
    db: Session,
    *,
    claims: TokenClaims,
    request_type: ApprovalRequestType,
    request_id: uuid.UUID,
    requester_employee_id: uuid.UUID | None,
    approve: bool,
    comment: str | None = None,
) -> tuple[ApprovalInstance, bool]:
    """Records one decision at the instance's current step. Returns
    (instance, is_final): is_final tells the caller whether to now flip the
    underlying leave/expense/bill row's own status (only the step that
    actually finalizes approval does), or leave it pending and just advance
    current_step. A reject at any step is immediately terminal — no partial
    or parallel semantics.

    Eligibility for the current step is resolved live against current
    config, not pinned at submission: reconfiguring an org's workflow while
    a request is mid-flight can change who's eligible to decide its
    remaining steps. Acceptable since delegation/escalation are out of
    scope for this engine.
    """
    instance = get_or_create_instance(
        db,
        org_id=claims.org_id,
        request_type=request_type,
        request_id=request_id,
        requester_employee_id=requester_employee_id,
    )
    if instance.status != ApprovalInstanceStatus.PENDING:
        raise ValueError(f"approval instance is {instance.status.value}, not pending")

    steps = get_configured_steps(db, org_id=claims.org_id, request_type=request_type)
    current_step = (
        next((s for s in steps if s.step_order == instance.current_step), None) if steps else None
    )

    if not is_eligible_approver(
        db, step=current_step, claims=claims, requester_employee_id=requester_employee_id
    ):
        raise PermissionError("not authorised to decide this request at its current step")

    db.add(
        ApprovalInstanceDecision(
            org_id=claims.org_id,
            approval_instance_id=instance.id,
            step_order=instance.current_step,
            decision=ApprovalDecisionType.APPROVE if approve else ApprovalDecisionType.REJECT,
            decided_by_account_id=claims.account_id,
            decided_by_role=claims.role,
            comment=comment,
        )
    )

    if not approve:
        instance.status = ApprovalInstanceStatus.REJECTED
        instance.decided_at = datetime.now(UTC)
        db.add(instance)
        db.flush()
        return instance, True

    total_steps = len(steps) if steps else 1
    if instance.current_step >= total_steps:
        instance.status = ApprovalInstanceStatus.APPROVED
        instance.decided_at = datetime.now(UTC)
        db.add(instance)
        db.flush()
        return instance, True

    instance.current_step += 1
    db.add(instance)
    db.flush()
    return instance, False


def replace_workflow_steps(
    db: Session,
    *,
    org_id: uuid.UUID,
    request_type: ApprovalRequestType,
    steps: list[ApprovalWorkflowStepInput],
) -> list[ApprovalWorkflowStep]:
    """Delete-and-recreate the entire ordered list for (org, request_type) in
    one transaction. step_order is assigned 1..N from array position, never
    caller-supplied, so there's no gap/duplicate to validate."""
    for step in steps:
        if step.eligibility_type in _MANAGER_RELATIONSHIP_TYPES and request_type == (
            ApprovalRequestType.BILL
        ):
            raise ValueError(
                "bills have no requester; direct_manager/department_head steps aren't valid here"
            )
        if step.eligibility_type == ApprovalStepEligibilityType.ROLE and step.eligible_role == (
            Role.EMPLOYEE
        ):
            raise ValueError("employee cannot be configured as an approval-step role")

    db.execute(
        delete(ApprovalWorkflowStep).where(
            ApprovalWorkflowStep.org_id == org_id,
            ApprovalWorkflowStep.request_type == request_type,
        )
    )
    created: list[ApprovalWorkflowStep] = []
    for step_order, step in enumerate(steps, start=1):
        row = ApprovalWorkflowStep(
            org_id=org_id,
            request_type=request_type,
            step_order=step_order,
            eligibility_type=step.eligibility_type,
            eligible_role=step.eligible_role,
            eligible_account_id=step.eligible_account_id,
        )
        db.add(row)
        created.append(row)
    db.flush()
    return created


def get_instance_with_decisions(
    db: Session, *, request_type: ApprovalRequestType, request_id: uuid.UUID
) -> ApprovalInstance | None:
    return db.scalar(
        select(ApprovalInstance).where(
            ApprovalInstance.request_type == request_type,
            ApprovalInstance.request_id == request_id,
        )
    )
