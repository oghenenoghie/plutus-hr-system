from collections.abc import Callable
from dataclasses import dataclass

from app.compliance.models import RuleVersion
from app.domain.payroll.frequency import PayFrequency
from app.domain.payroll.payslip import PayslipComputation, compute_payslip

# Bisection, not an analytic inverse — PAYE here is "tax on full
# year-to-date income minus tax already withheld," a lookup into
# progressive bands with no closed form to invert. What makes bisection
# valid is that net-of-deductions is monotonically non-decreasing in gross:
# every marginal PAYE band rate, plus pension and NHF, sum to well under
# 100%, so an extra naira of gross never reduces net. 128 iterations halves
# the search bracket enough to land within a kobo for any realistic salary.
_MAX_ITERATIONS = 128
_TOLERANCE_MINOR = 1


def _bisect_minimal_input_for_target_output(
    *, target_minor: int, upper_bound_seed_minor: int, output_for_input: Callable[[int], int]
) -> int:
    if target_minor <= 0:
        return 0

    lo, hi = 0, max(upper_bound_seed_minor, 1)
    for _ in range(_MAX_ITERATIONS):
        if output_for_input(hi) >= target_minor:
            break
        hi *= 2
    else:
        raise ValueError("could not bracket a gross-up solution within the iteration limit")

    for _ in range(_MAX_ITERATIONS):
        if hi - lo <= _TOLERANCE_MINOR:
            break
        mid = (lo + hi) // 2
        if output_for_input(mid) >= target_minor:
            hi = mid
        else:
            lo = mid
    return hi


def solve_lump_sum_gross_for_net_minor(
    *,
    target_net_minor: int,
    basic_minor: int,
    housing_minor: int,
    transport_minor: int,
    other_earnings_minor: int,
    annual_rent_paid_minor: int,
    periods_elapsed_this_year: int,
    frequency: PayFrequency,
    cumulative_gross_before_minor: int,
    cumulative_pension_employee_before_minor: int,
    cumulative_nhf_before_minor: int,
    cumulative_paye_withheld_before_minor: int,
    rules: RuleVersion,
) -> int:
    """The minimal one-off lump-sum gross (bonus, arrears, 13th month, ...)
    whose OWN net contribution — the lump sum minus the incremental PAYE it
    alone causes on top of this period's regular pay — is at least
    target_net_minor. Isolated to the lump sum's own effect rather than the
    whole payslip's net, since other_earnings_minor never changes pension
    or NHF (both are computed off basic/housing/transport only).
    """

    def _payslip(other_earnings: int) -> PayslipComputation:
        return compute_payslip(
            basic_minor=basic_minor,
            housing_minor=housing_minor,
            transport_minor=transport_minor,
            other_earnings_minor=other_earnings,
            annual_rent_paid_minor=annual_rent_paid_minor,
            periods_elapsed_this_year=periods_elapsed_this_year,
            frequency=frequency,
            cumulative_gross_before_minor=cumulative_gross_before_minor,
            cumulative_pension_employee_before_minor=cumulative_pension_employee_before_minor,
            cumulative_nhf_before_minor=cumulative_nhf_before_minor,
            cumulative_paye_withheld_before_minor=cumulative_paye_withheld_before_minor,
            rules=rules,
        )

    baseline_paye_minor = _payslip(other_earnings_minor).paye_minor

    def net_of_lump_sum(lump_sum_minor: int) -> int:
        with_lump_sum = _payslip(other_earnings_minor + lump_sum_minor)
        incremental_paye_minor = with_lump_sum.paye_minor - baseline_paye_minor
        return lump_sum_minor - incremental_paye_minor

    return _bisect_minimal_input_for_target_output(
        target_minor=target_net_minor,
        upper_bound_seed_minor=target_net_minor,
        output_for_input=net_of_lump_sum,
    )


def scale_components_to_total(
    *, basic_minor: int, housing_minor: int, transport_minor: int, new_total_minor: int
) -> tuple[int, int, int]:
    """Redistributes new_total_minor across basic/housing/transport
    preserving their current ratio — a raise or gross-up is spread
    proportionally rather than dumped into one component, which would
    otherwise distort the pensionable-pay base (basic+housing+transport)
    out of proportion to the employee's actual package shape. Transport
    absorbs the rounding remainder so the three always sum to exactly
    new_total_minor.
    """
    current_total = basic_minor + housing_minor + transport_minor
    if current_total <= 0:
        raise ValueError("cannot scale a package whose current total is zero or negative")
    new_basic = (basic_minor * new_total_minor) // current_total
    new_housing = (housing_minor * new_total_minor) // current_total
    new_transport = new_total_minor - new_basic - new_housing
    return new_basic, new_housing, new_transport


@dataclass(frozen=True)
class RegularPackageGrossUpResult:
    basic_minor: int
    housing_minor: int
    transport_minor: int
    computation: PayslipComputation


def solve_regular_package_gross_up(
    *,
    target_net_minor: int,
    current_basic_minor: int,
    current_housing_minor: int,
    current_transport_minor: int,
    other_earnings_minor: int,
    annual_rent_paid_minor: int,
    periods_elapsed_this_year: int,
    frequency: PayFrequency,
    cumulative_gross_before_minor: int,
    cumulative_pension_employee_before_minor: int,
    cumulative_nhf_before_minor: int,
    cumulative_paye_withheld_before_minor: int,
    rules: RuleVersion,
    loan_deduction_minor: int = 0,
) -> RegularPackageGrossUpResult:
    """The minimal basic/housing/transport package — scaled from the
    employee's current ratio via scale_components_to_total — whose net pay
    is at least target_net_minor. For "pay this employee X net every
    period" negotiations, unlike solve_lump_sum_gross_for_net_minor's
    one-off use: here PAYE, pension and NHF all move together as the whole
    package changes, not just PAYE.
    """
    current_total_minor = current_basic_minor + current_housing_minor + current_transport_minor
    if current_total_minor <= 0:
        raise ValueError("cannot gross up a package whose current total is zero or negative")

    def _computation_for_total(total_minor: int) -> PayslipComputation:
        basic_minor, housing_minor, transport_minor = scale_components_to_total(
            basic_minor=current_basic_minor,
            housing_minor=current_housing_minor,
            transport_minor=current_transport_minor,
            new_total_minor=total_minor,
        )
        return compute_payslip(
            basic_minor=basic_minor,
            housing_minor=housing_minor,
            transport_minor=transport_minor,
            other_earnings_minor=other_earnings_minor,
            annual_rent_paid_minor=annual_rent_paid_minor,
            periods_elapsed_this_year=periods_elapsed_this_year,
            frequency=frequency,
            cumulative_gross_before_minor=cumulative_gross_before_minor,
            cumulative_pension_employee_before_minor=cumulative_pension_employee_before_minor,
            cumulative_nhf_before_minor=cumulative_nhf_before_minor,
            cumulative_paye_withheld_before_minor=cumulative_paye_withheld_before_minor,
            rules=rules,
            loan_deduction_minor=loan_deduction_minor,
        )

    solved_total_minor = _bisect_minimal_input_for_target_output(
        target_minor=target_net_minor,
        upper_bound_seed_minor=max(current_total_minor, target_net_minor),
        output_for_input=lambda total_minor: _computation_for_total(total_minor).net_pay_minor,
    )

    basic_minor, housing_minor, transport_minor = scale_components_to_total(
        basic_minor=current_basic_minor,
        housing_minor=current_housing_minor,
        transport_minor=current_transport_minor,
        new_total_minor=solved_total_minor,
    )
    return RegularPackageGrossUpResult(
        basic_minor=basic_minor,
        housing_minor=housing_minor,
        transport_minor=transport_minor,
        computation=_computation_for_total(solved_total_minor),
    )
