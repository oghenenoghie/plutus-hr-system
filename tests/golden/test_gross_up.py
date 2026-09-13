"""Golden tests for the gross-up solvers (ported from hr-payroll's
solveLumpSumGrossForNetKobo/solveRegularPackageGrossUp): given a target net
figure, bisection finds the minimal gross that achieves it. Correctness
here is checked against compute_payslip itself (round-trip: the solved
gross's own net is >= target, and one kobo less falls short) rather than
independently hand-verified numbers, since the solvers are explicitly
defined as an inverse of compute_payslip.
"""

from app.compliance.versions.ng_2026_1 import NG_2026_1
from app.domain.payroll.frequency import PayFrequency
from app.domain.payroll.gross_up import (
    scale_components_to_total,
    solve_lump_sum_gross_for_net_minor,
    solve_regular_package_gross_up,
)
from app.domain.payroll.payslip import compute_payslip


def kobo(naira: int) -> int:
    return naira * 100


def _lump_sum_net(*, other_earnings_minor: int, lump_sum_minor: int) -> int:
    baseline = compute_payslip(
        basic_minor=kobo(300_000),
        housing_minor=kobo(150_000),
        transport_minor=kobo(50_000),
        other_earnings_minor=other_earnings_minor,
        annual_rent_paid_minor=0,
        periods_elapsed_this_year=1,
        frequency=PayFrequency.MONTHLY,
        cumulative_gross_before_minor=0,
        cumulative_pension_employee_before_minor=0,
        cumulative_nhf_before_minor=0,
        cumulative_paye_withheld_before_minor=0,
        rules=NG_2026_1,
    )
    with_lump_sum = compute_payslip(
        basic_minor=kobo(300_000),
        housing_minor=kobo(150_000),
        transport_minor=kobo(50_000),
        other_earnings_minor=other_earnings_minor + lump_sum_minor,
        annual_rent_paid_minor=0,
        periods_elapsed_this_year=1,
        frequency=PayFrequency.MONTHLY,
        cumulative_gross_before_minor=0,
        cumulative_pension_employee_before_minor=0,
        cumulative_nhf_before_minor=0,
        cumulative_paye_withheld_before_minor=0,
        rules=NG_2026_1,
    )
    return lump_sum_minor - (with_lump_sum.paye_minor - baseline.paye_minor)


def test_lump_sum_gross_up_hits_target_net_within_a_kobo() -> None:
    target_net = kobo(500_000)
    solved_gross = solve_lump_sum_gross_for_net_minor(
        target_net_minor=target_net,
        basic_minor=kobo(300_000),
        housing_minor=kobo(150_000),
        transport_minor=kobo(50_000),
        other_earnings_minor=0,
        annual_rent_paid_minor=0,
        periods_elapsed_this_year=1,
        frequency=PayFrequency.MONTHLY,
        cumulative_gross_before_minor=0,
        cumulative_pension_employee_before_minor=0,
        cumulative_nhf_before_minor=0,
        cumulative_paye_withheld_before_minor=0,
        rules=NG_2026_1,
    )

    achieved_net = _lump_sum_net(other_earnings_minor=0, lump_sum_minor=solved_gross)
    assert achieved_net >= target_net
    # The minimal solution: one kobo less gross must fall short of target.
    assert _lump_sum_net(other_earnings_minor=0, lump_sum_minor=solved_gross - 1) < target_net


def test_lump_sum_gross_up_crosses_the_twelve_million_naira_band_boundary() -> None:
    # Regular pay alone puts chargeable income just under the ₦12,000,000
    # band ceiling; a lump sum large enough pushes it across into the 21%
    # band, so the solver must account for the marginal rate changing
    # partway through the lump sum, not apply one flat rate throughout.
    other_earnings = kobo(11_500_000)
    target_net = kobo(2_000_000)

    solved_gross = solve_lump_sum_gross_for_net_minor(
        target_net_minor=target_net,
        basic_minor=kobo(300_000),
        housing_minor=kobo(150_000),
        transport_minor=kobo(50_000),
        other_earnings_minor=other_earnings,
        annual_rent_paid_minor=0,
        periods_elapsed_this_year=1,
        frequency=PayFrequency.MONTHLY,
        cumulative_gross_before_minor=0,
        cumulative_pension_employee_before_minor=0,
        cumulative_nhf_before_minor=0,
        cumulative_paye_withheld_before_minor=0,
        rules=NG_2026_1,
    )

    achieved_net = _lump_sum_net(other_earnings_minor=other_earnings, lump_sum_minor=solved_gross)
    assert achieved_net >= target_net
    assert (
        _lump_sum_net(other_earnings_minor=other_earnings, lump_sum_minor=solved_gross - 1)
        < target_net
    )


def test_zero_or_negative_target_net_needs_no_gross_up() -> None:
    assert (
        solve_lump_sum_gross_for_net_minor(
            target_net_minor=0,
            basic_minor=kobo(300_000),
            housing_minor=kobo(150_000),
            transport_minor=kobo(50_000),
            other_earnings_minor=0,
            annual_rent_paid_minor=0,
            periods_elapsed_this_year=1,
            frequency=PayFrequency.MONTHLY,
            cumulative_gross_before_minor=0,
            cumulative_pension_employee_before_minor=0,
            cumulative_nhf_before_minor=0,
            cumulative_paye_withheld_before_minor=0,
            rules=NG_2026_1,
        )
        == 0
    )


def test_scale_components_to_total_preserves_ratio_and_exact_sum() -> None:
    basic, housing, transport = scale_components_to_total(
        basic_minor=kobo(300_000),
        housing_minor=kobo(150_000),
        transport_minor=kobo(50_000),
        new_total_minor=kobo(1_000_000),
    )
    assert basic + housing + transport == kobo(1_000_000)
    # Original ratio is 6:3:1 (500,000 total) -> scaled to 1,000,000 should
    # land close to 600,000:300,000:100,000, up to integer-division rounding.
    assert abs(basic - kobo(600_000)) <= 1
    assert abs(housing - kobo(300_000)) <= 1
    assert abs(transport - kobo(100_000)) <= 1


def test_regular_package_gross_up_hits_target_net_and_preserves_ratio() -> None:
    target_net = kobo(700_000)
    result = solve_regular_package_gross_up(
        target_net_minor=target_net,
        current_basic_minor=kobo(300_000),
        current_housing_minor=kobo(150_000),
        current_transport_minor=kobo(50_000),
        other_earnings_minor=0,
        annual_rent_paid_minor=0,
        periods_elapsed_this_year=1,
        frequency=PayFrequency.MONTHLY,
        cumulative_gross_before_minor=0,
        cumulative_pension_employee_before_minor=0,
        cumulative_nhf_before_minor=0,
        cumulative_paye_withheld_before_minor=0,
        rules=NG_2026_1,
    )

    assert result.computation.net_pay_minor >= target_net
    # Same 6:3:1 ratio as the input package, preserved by construction.
    total = result.basic_minor + result.housing_minor + result.transport_minor
    assert abs(result.basic_minor / total - 0.6) < 0.01
    assert abs(result.housing_minor / total - 0.3) < 0.01
    assert abs(result.transport_minor / total - 0.1) < 0.01

    # One kobo less gross-package total falls short of the target net.
    basic, housing, transport = scale_components_to_total(
        basic_minor=kobo(300_000),
        housing_minor=kobo(150_000),
        transport_minor=kobo(50_000),
        new_total_minor=result.basic_minor + result.housing_minor + result.transport_minor - 1,
    )
    shy_computation = compute_payslip(
        basic_minor=basic,
        housing_minor=housing,
        transport_minor=transport,
        other_earnings_minor=0,
        annual_rent_paid_minor=0,
        periods_elapsed_this_year=1,
        frequency=PayFrequency.MONTHLY,
        cumulative_gross_before_minor=0,
        cumulative_pension_employee_before_minor=0,
        cumulative_nhf_before_minor=0,
        cumulative_paye_withheld_before_minor=0,
        rules=NG_2026_1,
    )
    assert shy_computation.net_pay_minor < target_net
