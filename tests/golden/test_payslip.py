"""Golden test for the per-period payslip orchestration, independently
hand-verified against the band table (see the commit introducing this file
for the full derivation) and cross-checked against a real pay run in
tests/integration/test_payroll_core.py.
"""

from app.compliance.versions.ng_2026_1 import NG_2026_1
from app.domain.payroll.frequency import PayFrequency
from app.domain.payroll.payslip import compute_payslip


def kobo(naira: int) -> int:
    return naira * 100


def test_three_months_cumulative_payslip_matches_hand_verified_figures() -> None:
    cumulative_gross = cumulative_pension_ee = cumulative_nhf = cumulative_paye = 0
    expected_paye_naira = [0, 5_750, 62_875]
    expected_net_naira = [452_500, 446_750, 389_625]

    for period, (paye_expected, net_expected) in enumerate(
        zip(expected_paye_naira, expected_net_naira, strict=True), start=1
    ):
        result = compute_payslip(
            basic_minor=kobo(300_000),
            housing_minor=kobo(150_000),
            transport_minor=kobo(50_000),
            other_earnings_minor=0,
            annual_rent_paid_minor=kobo(2_000_000),
            periods_elapsed_this_year=period,
            frequency=PayFrequency.MONTHLY,
            cumulative_gross_before_minor=cumulative_gross,
            cumulative_pension_employee_before_minor=cumulative_pension_ee,
            cumulative_nhf_before_minor=cumulative_nhf,
            cumulative_paye_withheld_before_minor=cumulative_paye,
            rules=NG_2026_1,
        )

        assert result.paye_minor == kobo(paye_expected)
        assert result.net_pay_minor == kobo(net_expected)

        cumulative_gross += result.gross_minor
        cumulative_pension_ee += result.pension_employee_minor
        cumulative_nhf += result.nhf_minor
        cumulative_paye += result.paye_minor


def test_payslip_gross_is_not_coincidentally_equal_to_pensionable_pay() -> None:
    """Guards against the exact coincidence the reference warns about: a
    real payslip's gross can exceed pensionable pay when there are earnings
    outside basic/housing/transport."""
    result = compute_payslip(
        basic_minor=kobo(300_000),
        housing_minor=kobo(150_000),
        transport_minor=kobo(50_000),
        other_earnings_minor=kobo(100_000),
        annual_rent_paid_minor=0,
        periods_elapsed_this_year=1,
        frequency=PayFrequency.MONTHLY,
        cumulative_gross_before_minor=0,
        cumulative_pension_employee_before_minor=0,
        cumulative_nhf_before_minor=0,
        cumulative_paye_withheld_before_minor=0,
        rules=NG_2026_1,
    )
    assert result.gross_minor == kobo(600_000)
    assert result.pensionable_pay_minor == kobo(500_000)
    assert result.gross_minor != result.pensionable_pay_minor
