import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.membership import Role


class ApprovalRequestType(str, enum.Enum):
    LEAVE_REQUEST = "leave_request"
    EXPENSE = "expense"
    BILL = "bill"


class ApprovalStepEligibilityType(str, enum.Enum):
    ROLE = "role"
    DIRECT_MANAGER = "direct_manager"
    DEPARTMENT_HEAD = "department_head"
    SPECIFIC_PERSON = "specific_person"


class ApprovalInstanceStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalDecisionType(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalWorkflowStep(Base):
    """One ordered step in an org's approval chain for one request_type.
    Zero rows for (org_id, request_type) is not an unconfigured error state
    — it's the explicit backward-compat default: the service layer falls
    back to each flow's original hardcoded role/manager gate. eligible_role
    and eligible_account_id are mutually exclusive with each other and with
    DIRECT_MANAGER/DEPARTMENT_HEAD (enforced by a schema validator plus a DB
    CHECK constraint as defense in depth). SPECIFIC_PERSON stores an
    account_id rather than an employee_id: a named approver need not have an
    Employee record at all (e.g. an ops-only Admin account), unlike
    DIRECT_MANAGER/DEPARTMENT_HEAD which are necessarily resolved through
    the Employee/Department graph at decision time.
    """

    __tablename__ = "approval_workflow_steps"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "request_type", "step_order", name="uq_approval_step_org_type_order"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    request_type: Mapped[ApprovalRequestType] = mapped_column(
        Enum(
            ApprovalRequestType,
            name="approval_request_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    eligibility_type: Mapped[ApprovalStepEligibilityType] = mapped_column(
        Enum(
            ApprovalStepEligibilityType,
            name="approval_step_eligibility_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    eligible_role: Mapped[Role | None] = mapped_column(
        Enum(
            Role,
            name="membership_role",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_type=False,
        )
    )
    eligible_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalInstance(Base):
    """Runtime tracking row, one per submitted request. request_id is a bare
    UUID rather than a foreign key — like AuditLog.entity_id, it points
    polymorphically at leave_requests/expenses/bills, three different
    tables. Created eagerly at submission time so "step 1 of N, pending" is
    visible immediately; also created defensively the first time a decision
    is attempted, for requests submitted before this feature existed.

    Mutable — current_step and status change over the instance's life —
    unlike the append-only decision trail below. Eligibility for the
    *current* step is resolved live against current config each time a
    decision is attempted, not pinned at submission: reconfiguring an org's
    workflow while a request is mid-flight can change who is eligible to
    decide its remaining steps. Acceptable since delegation/escalation are
    out of scope for this engine; not something to build around silently.
    """

    __tablename__ = "approval_instances"
    __table_args__ = (
        UniqueConstraint("request_type", "request_id", name="uq_approval_instance_request"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    request_type: Mapped[ApprovalRequestType] = mapped_column(
        Enum(
            ApprovalRequestType,
            name="approval_request_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_type=False,
        ),
        nullable=False,
    )
    request_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    requester_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL")
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[ApprovalInstanceStatus] = mapped_column(
        Enum(
            ApprovalInstanceStatus,
            name="approval_instance_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ApprovalInstanceStatus.PENDING,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    decisions: Mapped[list["ApprovalInstanceDecision"]] = relationship(
        back_populates="instance", order_by="ApprovalInstanceDecision.created_at"
    )


class ApprovalInstanceDecision(Base):
    """Append-only decision trail — same discipline as audit_logs. step_order
    is a snapshot integer, deliberately not a foreign key to
    approval_workflow_steps: steps can be edited or reordered after a
    request is already in flight, and the trail must record what was true
    when the decision was made, not what the current config says.
    decided_by_role is likewise captured at decision time, mirroring
    AuditLog.role — a later role change must not rewrite what happened.
    """

    __tablename__ = "approval_instance_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    approval_instance_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("approval_instances.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[ApprovalDecisionType] = mapped_column(
        Enum(
            ApprovalDecisionType,
            name="approval_decision_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    decided_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )
    decided_by_role: Mapped[str | None] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    instance: Mapped["ApprovalInstance"] = relationship(back_populates="decisions")
