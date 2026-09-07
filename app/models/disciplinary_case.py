import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DisciplinaryCaseCategory(str, enum.Enum):
    MISCONDUCT = "misconduct"
    ATTENDANCE = "attendance"
    POLICY_VIOLATION = "policy_violation"
    HARASSMENT = "harassment"
    OTHER = "other"


class DisciplinaryCaseStatus(str, enum.Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class DisciplinaryCaseAction(str, enum.Enum):
    NONE = "none"
    VERBAL_WARNING = "verbal_warning"
    WRITTEN_WARNING = "written_warning"
    SUSPENSION = "suspension"
    TERMINATION = "termination"


class DisciplinaryCase(Base):
    """An employee-relations case: a reported incident tracked through to
    resolution. reported_by_id is nullable (SET NULL) since the reporter
    leaving shouldn't erase the case itself. Not exposed to self-service —
    unlike Performance Reviews, an employee never sees their own case
    through the API; only ADMIN/PAYROLL_MANAGER/MANAGER can. Resolving a
    case (setting action_taken/resolution_notes/resolution_date) is
    restricted to ADMIN/PAYROLL_MANAGER — a MANAGER can open and view a
    case for their own report but the disciplinary outcome itself is an
    HR/admin decision.
    """

    __tablename__ = "disciplinary_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    reported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL")
    )

    category: Mapped[DisciplinaryCaseCategory] = mapped_column(
        Enum(
            DisciplinaryCaseCategory,
            name="disciplinary_case_category",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DisciplinaryCaseStatus] = mapped_column(
        Enum(
            DisciplinaryCaseStatus,
            name="disciplinary_case_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=DisciplinaryCaseStatus.OPEN,
    )
    incident_date: Mapped[date] = mapped_column(Date, nullable=False)
    action_taken: Mapped[DisciplinaryCaseAction | None] = mapped_column(
        Enum(
            DisciplinaryCaseAction,
            name="disciplinary_case_action",
            values_callable=lambda m: [x.value for x in m],
        ),
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolution_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
