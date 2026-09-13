import enum
import uuid
from dataclasses import dataclass
from datetime import date


class BenefitFrequency(str, enum.Enum):
    ONE_TIME = "one_time"
    MONTHLY = "monthly"
    ANNUAL = "annual"


@dataclass(frozen=True)
class BenefitCandidate:
    """Pure-data mirror of app.models.benefit.Benefit's fields this module
    needs — kept ORM-free like every other app/domain/payroll module; the
    service layer maps the real model into this before calling in.
    """

    id: uuid.UUID
    value_minor: int | None
    frequency: BenefitFrequency
    effective_date: date
    end_date: date | None


@dataclass(frozen=True)
class BenefitDeduction:
    benefit_id: uuid.UUID
    value_minor: int


def is_benefit_active_this_period(
    benefit: BenefitCandidate, *, period_start: date, period_end: date
) -> bool:
    """Whether a benefit recurs in this specific pay period. ONE_TIME only
    ever matches the single period containing its effective_date; ANNUAL
    matches the period whose end falls in the same calendar month as
    effective_date (its 'anniversary month'); MONTHLY matches every period
    it's active for, regardless of the pay frequency's actual cadence —
    same simplification the rest of this codebase makes elsewhere for
    lack of a time-clock/attendance granularity to do better.
    """
    if benefit.value_minor is None or benefit.value_minor <= 0:
        return False
    if benefit.effective_date > period_end:
        return False
    if benefit.end_date is not None and benefit.end_date < period_start:
        return False

    if benefit.frequency == BenefitFrequency.ONE_TIME:
        return period_start <= benefit.effective_date <= period_end
    if benefit.frequency == BenefitFrequency.ANNUAL:
        return benefit.effective_date.month == period_end.month
    return True  # MONTHLY


def select_benefit_deductions(
    benefits: list[BenefitCandidate], *, available_net_minor: int
) -> tuple[list[BenefitDeduction], int]:
    """Applies each benefit's value_minor against available_net_minor in
    effective_date order (earliest-enrolled first), skipping — never
    partially deducting — any benefit whose value would push the running
    total past what's available. Same 'skip whole enrollment if it can't
    be covered' rule hr-payroll uses for benefits and union dues.
    """
    applied: list[BenefitDeduction] = []
    remaining = available_net_minor
    for benefit in sorted(benefits, key=lambda b: b.effective_date):
        value = benefit.value_minor or 0
        if value <= remaining:
            applied.append(BenefitDeduction(benefit_id=benefit.id, value_minor=value))
            remaining -= value
    return applied, available_net_minor - remaining
