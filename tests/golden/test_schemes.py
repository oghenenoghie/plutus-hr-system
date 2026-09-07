"""Golden tests for pension, NHF, NSITF, ITF and WHT — each applied to its
own base, with employer-side costs kept structurally out of the employee
deduction total, per
.claude/skills/plutus-payroll-python/references/nigeria-statutory-compliance.md §12.
"""

from app.compliance.models import BorneBy
from app.compliance.versions.ng_2026_1 import NG_2026_1
from app.domain.payroll.deductions import Deduction, total_employee_deductions, total_employer_costs
from app.domain.payroll.itf import compute_itf
from app.domain.payroll.nhf import compute_nhf
from app.domain.payroll.nsitf import compute_nsitf
from app.domain.payroll.pension import (
    compute_pension_employee,
    compute_pension_employer,
    compute_pensionable_pay,
)
from app.domain.payroll.wht import compute_wht

RULES = NG_2026_1


def kobo(naira: int) -> int:
    return naira * 100


def test_pension_applies_to_basic_housing_transport_only() -> None:
    pensionable = compute_pensionable_pay(
        basic_minor=kobo(300_000), housing_minor=kobo(150_000), transport_minor=kobo(50_000)
    )
    assert pensionable == kobo(500_000)
    assert compute_pension_employee(pensionable, RULES.pension) == kobo(40_000)  # 8%
    assert compute_pension_employer(pensionable, RULES.pension) == kobo(50_000)  # 10%


def test_nhf_applies_to_basic_only_not_gross() -> None:
    # A calculator that mistakenly used gross instead of basic would give
    # 2.5% of 500,000 = 12,500, not 7,500.
    basic_only = kobo(300_000)
    assert compute_nhf(basic_only, RULES.nhf) == kobo(7_500)  # 2.5% of 300,000


def test_nsitf_uses_caller_supplied_base_excluding_bonuses() -> None:
    # Total monthly payroll of 2,000,000 excluding pension/bonus/overtime/
    # 13th-month, per §6 — never the PAYE gross figure.
    base_excluding_bonuses = kobo(2_000_000)
    assert compute_nsitf(base_excluding_bonuses, RULES.nsitf) == kobo(20_000)  # 1%


def test_itf_only_charged_when_employer_qualifies() -> None:
    annual_payroll = kobo(60_000_000)
    assert compute_itf(annual_payroll, RULES.itf, qualifies=False) == 0
    assert compute_itf(annual_payroll, RULES.itf, qualifies=True) == kobo(600_000)  # 1%


def test_wht_resolved_by_category_not_a_flat_rate() -> None:
    payment = kobo(1_000_000)
    assert compute_wht(payment, "goods", RULES.wht) == kobo(50_000)  # 5%
    assert compute_wht(payment, "services", RULES.wht) == kobo(100_000)  # 10%


def test_employer_side_costs_never_land_in_employee_deduction_total() -> None:
    pensionable = compute_pensionable_pay(kobo(300_000), kobo(150_000), kobo(50_000))
    deductions = (
        Deduction("paye", kobo(50_000), BorneBy.EMPLOYEE),
        Deduction(
            "pension_employee",
            compute_pension_employee(pensionable, RULES.pension),
            BorneBy.EMPLOYEE,
        ),
        Deduction("nhf", compute_nhf(kobo(300_000), RULES.nhf), BorneBy.EMPLOYEE),
        Deduction(
            "pension_employer",
            compute_pension_employer(pensionable, RULES.pension),
            BorneBy.EMPLOYER,
        ),
        Deduction("nsitf", compute_nsitf(kobo(2_000_000), RULES.nsitf), BorneBy.EMPLOYER),
        Deduction(
            "itf", compute_itf(kobo(60_000_000), RULES.itf, qualifies=True), BorneBy.EMPLOYER
        ),
    )

    employee_total = total_employee_deductions(deductions)
    employer_total = total_employer_costs(deductions)

    assert employee_total == kobo(50_000) + kobo(40_000) + kobo(7_500)
    assert employer_total == kobo(50_000) + kobo(20_000) + kobo(600_000)

    # Structural proof, not a value coincidence: the employee total is
    # exactly the grand total minus every EMPLOYER-borne line — no
    # employer-only line contributes to it.
    grand_total = sum(d.amount_minor for d in deductions)
    employer_only_sum = sum(d.amount_minor for d in deductions if d.borne_by is BorneBy.EMPLOYER)
    assert employee_total == grand_total - employer_only_sum
    assert employer_total == employer_only_sum
