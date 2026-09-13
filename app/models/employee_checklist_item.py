import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChecklistType(str, enum.Enum):
    ONBOARDING = "onboarding"
    OFFBOARDING = "offboarding"


class ChecklistItemStatus(str, enum.Enum):
    PENDING = "pending"
    DONE = "done"


class EmployeeChecklistItem(Base):
    """One task on an employee's onboarding or offboarding checklist (equipment
    issued, IT access granted/revoked, exit interview held, ...) — a plain
    HR-defined task list, not a workflow engine: items are created and
    completed individually, with no ordering or dependency between them.
    Mutable (not append-only): a title or due_date can be corrected, and
    completing an item is itself the meaningful state transition being
    tracked, same as DisciplinaryCase.
    """

    __tablename__ = "employee_checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    checklist_type: Mapped[ChecklistType] = mapped_column(
        Enum(ChecklistType, name="checklist_type", values_callable=lambda m: [x.value for x in m]),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ChecklistItemStatus] = mapped_column(
        Enum(
            ChecklistItemStatus,
            name="checklist_item_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=ChecklistItemStatus.PENDING,
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
