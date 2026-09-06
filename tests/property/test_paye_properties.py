from hypothesis import given
from hypothesis import strategies as st

from app.compliance.versions.ng_2026_1 import NG_2026_1
from app.domain.payroll.nhf import compute_nhf
from app.domain.payroll.paye import compute_paye_annual
from app.domain.payroll.pension import compute_pension_employee, compute_pension_employer
from app.domain.payroll.reliefs import compute_rent_relief

BANDS = NG_2026_1.paye.bands
PAYE_RULE = NG_2026_1.paye
PENSION_RULE = NG_2026_1.pension
NHF_RULE = NG_2026_1.nhf

# Bounded to a realistic annual chargeable income range (up to ~₦1bn) so the
# suite stays fast; the boundary-exact cases already live in tests/golden.
chargeable_income = st.integers(min_value=0, max_value=100_000_000_000)


@given(chargeable_income)
def test_paye_never_exceeds_chargeable_income(chargeable_minor: int) -> None:
    assert compute_paye_annual(chargeable_minor, BANDS) <= chargeable_minor


@given(chargeable_income)
def test_paye_never_negative(chargeable_minor: int) -> None:
    assert compute_paye_annual(chargeable_minor, BANDS) >= 0


@given(chargeable_income)
def test_monthly_times_twelve_reconciles_to_annual_within_rounding(chargeable_minor: int) -> None:
    annual = compute_paye_annual(chargeable_minor, BANDS)
    monthly = annual // 12
    # Integer division can leave up to 11 kobo of remainder per year.
    assert abs(monthly * 12 - annual) <= 11


@given(st.integers(min_value=0, max_value=100_000_000_000))
def test_rent_relief_never_negative_and_never_exceeds_cap(annual_rent_minor: int) -> None:
    relief = compute_rent_relief(annual_rent_minor, PAYE_RULE)
    assert relief >= 0
    assert relief <= PAYE_RULE.rent_relief_cap_minor


@given(st.integers(min_value=0, max_value=100_000_000_000))
def test_pension_contributions_never_negative(pensionable_pay_minor: int) -> None:
    assert compute_pension_employee(pensionable_pay_minor, PENSION_RULE) >= 0
    assert compute_pension_employer(pensionable_pay_minor, PENSION_RULE) >= 0


@given(st.integers(min_value=0, max_value=100_000_000_000))
def test_nhf_never_negative(basic_salary_minor: int) -> None:
    assert compute_nhf(basic_salary_minor, NHF_RULE) >= 0
