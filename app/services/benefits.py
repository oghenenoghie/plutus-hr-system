import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.benefit import Benefit, BenefitDependent, BenefitFrequency, BenefitPlan


def create_benefit_plan(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    frequency: BenefitFrequency,
    description: str | None = None,
    default_employee_cost_minor: int | None = None,
    employer_cost_minor: int | None = None,
) -> BenefitPlan:
    if default_employee_cost_minor is not None and default_employee_cost_minor < 0:
        raise ValueError("default_employee_cost_minor must not be negative")
    if employer_cost_minor is not None and employer_cost_minor < 0:
        raise ValueError("employer_cost_minor must not be negative")

    plan = BenefitPlan(
        org_id=org_id,
        name=name,
        description=description,
        frequency=frequency,
        default_employee_cost_minor=default_employee_cost_minor,
        employer_cost_minor=employer_cost_minor,
    )
    db.add(plan)
    db.flush()
    return plan


def assign_benefit(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    effective_date: date,
    plan: BenefitPlan | None = None,
    name: str | None = None,
    frequency: BenefitFrequency | None = None,
    description: str | None = None,
    value_minor: int | None = None,
    employer_cost_minor: int | None = None,
    end_date: date | None = None,
) -> Benefit:
    """Either plan or (name, frequency) must be given. When plan is given,
    its name/frequency/costs seed the enrolment and any of name,
    frequency, value_minor, employer_cost_minor, description explicitly
    passed override just that field — the enrolment is then an
    independent copy (see BenefitPlan's docstring), never a live
    reference back to the plan.
    """
    if plan is None and (name is None or frequency is None):
        raise ValueError("either plan or both name and frequency must be given")
    if value_minor is not None and value_minor < 0:
        raise ValueError("value_minor must not be negative")
    if employer_cost_minor is not None and employer_cost_minor < 0:
        raise ValueError("employer_cost_minor must not be negative")
    if end_date is not None and end_date < effective_date:
        raise ValueError("end_date must not be before effective_date")

    resolved_name = name if name is not None else (plan.name if plan is not None else None)
    resolved_frequency = (
        frequency if frequency is not None else (plan.frequency if plan is not None else None)
    )
    resolved_description = (
        description if description is not None else (plan.description if plan is not None else None)
    )
    resolved_value_minor = (
        value_minor
        if value_minor is not None
        else (plan.default_employee_cost_minor if plan is not None else None)
    )
    resolved_employer_cost_minor = (
        employer_cost_minor
        if employer_cost_minor is not None
        else (plan.employer_cost_minor if plan is not None else None)
    )
    assert resolved_name is not None and resolved_frequency is not None  # guaranteed above

    benefit = Benefit(
        org_id=org_id,
        employee_id=employee_id,
        plan_id=plan.id if plan is not None else None,
        name=resolved_name,
        description=resolved_description,
        value_minor=resolved_value_minor,
        employer_cost_minor=resolved_employer_cost_minor,
        frequency=resolved_frequency,
        effective_date=effective_date,
        end_date=end_date,
    )
    db.add(benefit)
    db.flush()
    return benefit


def end_benefit(db: Session, benefit: Benefit, *, end_date: date) -> Benefit:
    if end_date < benefit.effective_date:
        raise ValueError("end_date must not be before effective_date")
    benefit.end_date = end_date
    db.add(benefit)
    return benefit


def add_dependent(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    full_name: str,
    relationship: str,
    date_of_birth: date | None = None,
) -> BenefitDependent:
    dependent = BenefitDependent(
        org_id=org_id,
        employee_id=employee_id,
        full_name=full_name,
        relationship=relationship,
        date_of_birth=date_of_birth,
    )
    db.add(dependent)
    db.flush()
    return dependent
