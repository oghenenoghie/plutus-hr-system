import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.payroll.benefits import BenefitFrequency
from app.models.base import Base

__all__ = ["Benefit", "BenefitDependent", "BenefitFrequency", "BenefitPlan"]


class BenefitPlan(Base):
    """A shared template an org offers — 'Standard Health Cover', 'Gym
    Membership' — as opposed to Benefit, which is one employee's
    enrolment. Assigning a benefit from a plan (Benefit.plan_id) copies
    the plan's cost figures in as that enrolment's starting values rather
    than referencing the plan live, so a later change to the plan's price
    never silently reprices an employee already enrolled — same
    effective-dated-copy reasoning as compensation history elsewhere in
    this codebase. employer_cost_minor is informational only (surfaced on
    the enrolment for reporting); it is never deducted from anyone and
    never taxed as a benefit-in-kind — see Benefit's own docstring on why
    that stays out of scope.
    """

    __tablename__ = "benefit_plans"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_benefit_plan_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    frequency: Mapped[BenefitFrequency] = mapped_column(
        Enum(
            BenefitFrequency,
            name="benefit_frequency",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    # Default employee-side deduction for a new enrolment from this plan —
    # copied into Benefit.value_minor at assignment, then independent.
    default_employee_cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    employer_cost_minor: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Benefit(Base):
    """A non-statutory perk assigned to an employee (health insurance, meal
    allowance, gym membership, ...). value_minor is nullable because not
    every benefit is monetary (e.g. gym access); when it is, an active
    benefit is automatically deducted from net pay by the next pay run
    (see app.domain.payroll.benefits and process_employee_payslip) as a
    plain post-tax recovery of what the employer already covers for it.
    Deliberately never taxed or valued as a benefit-in-kind:
    nigeria-statutory-compliance.md gives no figure for that (NHIS/NHIA is
    'scheme-defined', §5, and nothing else in the reference addresses
    benefit-in-kind treatment) — encoding one would be inventing a
    statutory rule, which the engine's guardrail forbids. A net-pay
    deduction needs no such rule since it never touches gross or taxable
    income.
    """

    __tablename__ = "benefits"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    # Which catalogue plan this enrolment came from, if any — SET NULL
    # (never CASCADE) so a plan can be retired without deleting anyone's
    # active enrolment; a null plan_id is a fully ad hoc benefit, exactly
    # today's behaviour.
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("benefit_plans.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    value_minor: Mapped[int | None] = mapped_column(BigInteger)
    # Informational employer cost for this specific enrolment (copied from
    # the plan, or set directly for an ad hoc benefit) — never deducted,
    # never taxed; see BenefitPlan's docstring.
    employer_cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    frequency: Mapped[BenefitFrequency] = mapped_column(
        Enum(
            BenefitFrequency,
            name="benefit_frequency",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BenefitDependent(Base):
    """A family member declared against an employee for benefits purposes
    (health-scheme enrolment and cost calculation) — attached to the
    employee, not to any one Benefit enrolment, since the same dependents
    apply whichever health/insurance plan the employee is on."""

    __tablename__ = "benefit_dependents"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    relationship: Mapped[str] = mapped_column(String(64), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
