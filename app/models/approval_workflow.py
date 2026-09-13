import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.approval_workflow import ApprovalRequestStatus, StepDecision
from app.models.base import Base
from app.models.membership import Role

__all__ = [
    "ApprovalRequest",
    "ApprovalRequestStatus",
    "ApprovalStepDecision",
    "ApprovalWorkflowStep",
    "ApprovalWorkflowTemplate",
    "StepDecision",
]


class ApprovalWorkflowTemplate(Base):
    """An org-defined chain of approval steps for one kind of entity
    (entity_type is a free-text tag, e.g. "expense" — this module doesn't
    know or care what the underlying entities are, it just tracks approval
    state against an (entity_type, entity_id) pair a caller supplies). At
    most one is_active template per (org_id, entity_type) — enforced by
    register_template — so starting a new approval never has to guess
    which template applies.
    """

    __tablename__ = "approval_workflow_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalWorkflowStep(Base):
    """One 1-based position in a template's chain and which role must
    decide it. approver_role is intentionally a Role, not a specific
    account — the same shape require_roles() already uses everywhere else
    in this codebase, so a step just says "any ADMIN" rather than naming
    one person."""

    __tablename__ = "approval_workflow_steps"
    __table_args__ = (
        UniqueConstraint("template_id", "sequence", name="uq_workflow_step_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("approval_workflow_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[Role] = mapped_column(
        Enum(
            Role, name="approval_step_approver_role", values_callable=lambda m: [x.value for x in m]
        ),
        nullable=False,
    )


class ApprovalRequest(Base):
    """One in-flight (or decided) run of a template against one real
    entity. At most one per (entity_type, entity_id) — see
    uq_approval_request_entity — this module models a single approval run
    per entity, not resubmission after rejection.
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_approval_request_entity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("approval_workflow_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[ApprovalRequestStatus] = mapped_column(
        Enum(
            ApprovalRequestStatus,
            name="approval_request_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=ApprovalRequestStatus.PENDING,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalStepDecision(Base):
    """Append-only log of every decision made on an ApprovalRequest — who
    decided which step, when, and how. Never edited or deleted (see
    forbid_update_delete); ApprovalRequest.current_step/status are the
    live, derived view, this is the permanent record of how it got there.
    """

    __tablename__ = "approval_step_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False
    )
    step_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[StepDecision] = mapped_column(
        Enum(
            StepDecision,
            name="approval_step_decision",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )
    comments: Mapped[str | None] = mapped_column(String(1000))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
