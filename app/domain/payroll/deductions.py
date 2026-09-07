from dataclasses import dataclass

from app.compliance.models import BorneBy


@dataclass(frozen=True)
class Deduction:
    label: str
    amount_minor: int
    borne_by: BorneBy


def total_employee_deductions(deductions: tuple[Deduction, ...]) -> int:
    """Sum of every line an employee actually pays. Employer-only lines
    (NSITF, ITF, employer pension) are structurally excluded by borne_by —
    never by convention (nigeria-statutory-compliance.md engine invariants)."""
    return sum(d.amount_minor for d in deductions if d.borne_by is not BorneBy.EMPLOYER)


def total_employer_costs(deductions: tuple[Deduction, ...]) -> int:
    return sum(d.amount_minor for d in deductions if d.borne_by is not BorneBy.EMPLOYEE)
