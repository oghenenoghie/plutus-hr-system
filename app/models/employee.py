import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.payroll.frequency import PayFrequency
from app.models.base import Base


class EmploymentType(str, enum.Enum):
    PERMANENT = "permanent"
    FIXED_TERM = "fixed_term"
    PART_TIME = "part_time"
    INTERN = "intern"
    CONSULTANT = "consultant"


class LifecycleState(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


def _str_enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda members: [m.value for m in members])


class Employee(Base):
    """The record payroll hangs off. Pay components are stored separately
    (basic/housing/transport), never a derived split of gross — real
    Nigerian pay structures vary (nigeria-statutory-compliance.md §2
    caveat). Department/Branch are deliberately not modelled yet: the
    reference is explicit that locations are first-class, not free text,
    and that's a bigger piece of work than this phase needs — a plain
    state_of_residence field covers what PAYE routing (§9) requires today.
    """

    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("org_id", "employee_number", name="uq_employee_org_number"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    employee_number: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(32))
    nationality: Mapped[str | None] = mapped_column(String(64))
    marital_status: Mapped[str | None] = mapped_column(String(32))

    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    residential_address: Mapped[str | None] = mapped_column(String(500))
    next_of_kin_name: Mapped[str | None] = mapped_column(String(255))
    next_of_kin_phone: Mapped[str | None] = mapped_column(String(32))

    tin: Mapped[str | None] = mapped_column(String(64))
    pfa_name: Mapped[str | None] = mapped_column(String(255))
    rsa_pin: Mapped[str | None] = mapped_column(String(64))
    nhf_number: Mapped[str | None] = mapped_column(String(64))
    state_of_residence: Mapped[str] = mapped_column(String(64), nullable=False)

    job_title: Mapped[str | None] = mapped_column(String(255))
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL")
    )
    employment_type: Mapped[EmploymentType] = mapped_column(
        _str_enum(EmploymentType, "employment_type"), nullable=False
    )
    date_of_joining: Mapped[date] = mapped_column(Date, nullable=False)
    lifecycle_state: Mapped[LifecycleState] = mapped_column(
        _str_enum(LifecycleState, "employee_lifecycle_state"),
        nullable=False,
        default=LifecycleState.ACTIVE,
    )

    basic_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    housing_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transport_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    other_earnings_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    annual_rent_paid_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pay_frequency: Mapped[PayFrequency] = mapped_column(
        _str_enum(PayFrequency, "employee_pay_frequency"),
        nullable=False,
        default=PayFrequency.MONTHLY,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
