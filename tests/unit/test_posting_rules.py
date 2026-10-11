import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.accounting.posting_rules import (
    CASH_ACCOUNT,
    SCHEME_PAYABLE_ACCOUNT,
    PostingLine,
    assert_balanced,
    build_statutory_remittance_postings,
    mirror_postings,
)
from app.domain.payroll.payslip import PayslipComputation
from app.domain.payroll.postings import build_payslip_postings
from app.services.chart_accounts import DEFAULT_ACCOUNTS

_AMOUNTS = st.integers(min_value=1, max_value=10**15)
_SCHEMES = st.sampled_from(sorted(SCHEME_PAYABLE_ACCOUNT))


@given(scheme=_SCHEMES, amount=_AMOUNTS)
def test_remittance_postings_always_balance_and_clear_the_payable(scheme: str, amount: int) -> None:
    lines = build_statutory_remittance_postings(scheme, amount)

    assert lines is not None
    assert_balanced(lines)
    debit, credit = lines
    assert debit.account == SCHEME_PAYABLE_ACCOUNT[scheme]
    assert debit.debit_minor == amount
    assert credit.account == CASH_ACCOUNT
    assert credit.credit_minor == amount


@given(scheme=_SCHEMES, amount=_AMOUNTS)
def test_remittance_postings_carry_no_pay_run_id(scheme: str, amount: int) -> None:
    """A pay-run reversal mirrors every line tagged with that run. A
    remittance is money already paid to an authority and must stay out of
    that mirror."""
    lines = build_statutory_remittance_postings(scheme, amount)

    assert lines is not None
    assert all(line.pay_run_id is None for line in lines)


def test_itf_has_no_accrued_payable_so_posts_nothing() -> None:
    assert build_statutory_remittance_postings("itf", 1_000_00) is None


@pytest.mark.parametrize("amount", [0, -1])
def test_remittance_rejects_a_non_positive_amount(amount: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        build_statutory_remittance_postings("paye", amount)


def test_every_account_a_remittance_can_touch_is_in_the_default_chart() -> None:
    """The audit's D7: a posting builder must never emit a code the default
    chart lacks. (The payroll builder does — see the xfail below.)"""
    default_codes = {code for code, _name, _type in DEFAULT_ACCOUNTS}

    assert {CASH_ACCOUNT, *SCHEME_PAYABLE_ACCOUNT.values()} <= default_codes


@pytest.mark.xfail(
    strict=True,
    reason=(
        "audit P1: build_payslip_postings emits benefit_deductions_recovered and "
        "union_dues_payable, which DEFAULT_ACCOUNTS does not seed. This is why the "
        "payroll posting sites still pass validate_chart=False. Remove this marker "
        "(and those flags) when the chart is completed."
    ),
)
def test_every_account_payroll_posts_to_is_in_the_default_chart() -> None:
    default_codes = {code for code, _name, _type in DEFAULT_ACCOUNTS}
    computation = PayslipComputation(
        gross_minor=500_000_00,
        pensionable_pay_minor=500_000_00,
        pension_employee_minor=40_000_00,
        pension_employer_minor=50_000_00,
        nhf_minor=7_500_00,
        cumulative_rent_relief_minor=0,
        cumulative_chargeable_income_minor=400_000_00,
        paye_minor=30_000_00,
        loan_deduction_minor=10_000_00,
        benefit_deduction_minor=5_000_00,
        union_dues_deduction_minor=2_000_00,
        net_pay_minor=405_500_00,
    )

    emitted = {posting.account for posting in build_payslip_postings(computation)}

    assert emitted <= default_codes, emitted - default_codes


@given(
    amounts=st.lists(_AMOUNTS, min_size=1, max_size=6),
)
def test_mirror_of_a_balanced_entry_is_balanced_and_nets_to_zero(amounts: list[int]) -> None:
    employee_id = uuid.uuid4()
    original = tuple(
        line
        for amount in amounts
        for line in (
            PostingLine("expense", debit_minor=amount, employee_id=employee_id),
            PostingLine("payable", credit_minor=amount, employee_id=employee_id),
        )
    )

    mirrored = mirror_postings(original)

    assert_balanced(mirrored)
    # Same accounts and dimensions, sides swapped.
    for before, after in zip(original, mirrored, strict=True):
        assert (after.account, after.employee_id) == (before.account, before.employee_id)
        assert (after.debit_minor, after.credit_minor) == (before.credit_minor, before.debit_minor)
    # Applying original then mirror leaves every account at zero.
    net: dict[str, int] = {}
    for line in (*original, *mirrored):
        net[line.account] = net.get(line.account, 0) + line.debit_minor - line.credit_minor
    assert set(net.values()) == {0}


def test_mirroring_twice_restores_the_original() -> None:
    original = (
        PostingLine("a", debit_minor=5, description="x", pay_run_id=uuid.uuid4()),
        PostingLine("b", credit_minor=5, description="x"),
    )

    assert mirror_postings(mirror_postings(original)) == original


def test_mirror_description_override_replaces_every_line() -> None:
    original = (PostingLine("a", debit_minor=5, description="x"), PostingLine("b", credit_minor=5))

    mirrored = mirror_postings(original, description="reversal of run")

    assert {line.description for line in mirrored} == {"reversal of run"}


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        ((PostingLine("a", debit_minor=5),), "at least two lines"),
        (
            (PostingLine("a", debit_minor=5), PostingLine("b", credit_minor=4)),
            "does not balance",
        ),
        (
            (PostingLine("a", debit_minor=5, credit_minor=5), PostingLine("b", credit_minor=5)),
            "not both/neither",
        ),
        (
            (PostingLine("a"), PostingLine("b", credit_minor=5)),
            "not both/neither",
        ),
        (
            (PostingLine("a", debit_minor=-5), PostingLine("b", credit_minor=-5)),
            "cannot be negative",
        ),
    ],
)
def test_assert_balanced_rejects_malformed_entries(
    lines: tuple[PostingLine, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        assert_balanced(lines)
