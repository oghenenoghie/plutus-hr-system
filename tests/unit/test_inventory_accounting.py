"""Pure inventory posting rules (app/domain/inventory/accounting.py)."""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.accounting.posting_rules import assert_balanced
from app.domain.inventory.accounting import (
    ADJUSTMENT_ACCOUNT,
    GRNI_ACCOUNT,
    INVENTORY_ACCOUNT,
    Leg,
    bill_legs,
    counter_legs,
    journal_lines,
    reversal_variance_legs,
)


def _net(legs: list[Leg]) -> dict[str, int]:
    return {line.account: line.debit_minor - line.credit_minor for line in journal_lines(legs)}


def test_legs_net_per_account_and_drop_zeros() -> None:
    legs = [
        Leg(INVENTORY_ACCOUNT, -400),
        Leg("office", 400),
        Leg(INVENTORY_ACCOUNT, -50),
        Leg("consumption", 50),
        Leg("office", 0),
    ]
    lines = journal_lines(legs, description="ISS-1")
    assert [(l.account, l.debit_minor, l.credit_minor) for l in lines] == [
        (INVENTORY_ACCOUNT, 0, 450),
        ("office", 400, 0),
        ("consumption", 50, 0),
    ]
    assert all(line.description == "ISS-1" for line in lines)
    assert_balanced(lines)


def test_nothing_to_post_when_everything_nets_to_zero() -> None:
    # A transfer pair, or zero-cost stock.
    assert journal_lines([Leg(INVENTORY_ACCOUNT, 500), Leg(INVENTORY_ACCOUNT, -500)]) == []
    assert journal_lines(counter_legs(0, GRNI_ACCOUNT)) == []


def test_unbalanced_legs_are_refused() -> None:
    with pytest.raises(ValueError, match="does not balance"):
        journal_lines([Leg(INVENTORY_ACCOUNT, 100), Leg(GRNI_ACCOUNT, -99)])


def test_reversal_variance() -> None:
    # Stock received at 10,000 leaves at today's average of 15,000.
    assert _net(reversal_variance_legs(-15_000, -10_000)) == {
        INVENTORY_ACCOUNT: -5_000,
        ADJUSTMENT_ACCOUNT: 5_000,
    }
    assert journal_lines(reversal_variance_legs(-10_000, -10_000)) == []


def test_bill_without_a_receipt_is_unchanged() -> None:
    assert _net(
        bill_legs(
            amount_minor=10_000,
            vat_minor=750,
            wht_minor=500,
            expense_account="fees",
            grni_cleared_minor=0,
        )
    ) == {"fees": 10_000, "vat_receivable": 750, "wht_payable": -500, "accounts_payable": -10_250}


def test_bill_clears_grni_and_books_the_price_difference() -> None:
    over = _net(
        bill_legs(
            amount_minor=10_300,
            vat_minor=0,
            wht_minor=0,
            expense_account="ppv",
            grni_cleared_minor=10_000,
        )
    )
    assert over == {GRNI_ACCOUNT: 10_000, "ppv": 300, "accounts_payable": -10_300}
    under = _net(
        bill_legs(
            amount_minor=9_800,
            vat_minor=0,
            wht_minor=0,
            expense_account="ppv",
            grni_cleared_minor=10_000,
        )
    )
    assert under == {GRNI_ACCOUNT: 10_000, "ppv": -200, "accounts_payable": -9_800}
    exact = _net(
        bill_legs(
            amount_minor=10_000,
            vat_minor=0,
            wht_minor=0,
            expense_account="ppv",
            grni_cleared_minor=10_000,
        )
    )
    assert exact == {GRNI_ACCOUNT: 10_000, "accounts_payable": -10_000}


def test_bill_amounts_are_validated() -> None:
    with pytest.raises(ValueError):
        bill_legs(
            amount_minor=0, vat_minor=0, wht_minor=0, expense_account="x", grni_cleared_minor=0
        )
    with pytest.raises(ValueError):
        bill_legs(
            amount_minor=10, vat_minor=-1, wht_minor=0, expense_account="x", grni_cleared_minor=0
        )


@given(
    amount=st.integers(min_value=1, max_value=10**12),
    vat=st.integers(min_value=0, max_value=10**11),
    accrued=st.integers(min_value=0, max_value=10**12),
    wht_share=st.integers(min_value=0, max_value=100),
)
@example(amount=1, vat=0, accrued=0, wht_share=100)  # nothing left payable
def test_bill_journals_always_balance(amount: int, vat: int, accrued: int, wht_share: int) -> None:
    wht = amount * wht_share // 100
    lines = journal_lines(
        bill_legs(
            amount_minor=amount,
            vat_minor=vat,
            wht_minor=wht,
            expense_account="ppv",
            grni_cleared_minor=accrued,
        )
    )
    assert_balanced(lines)
    net = {line.account: line.debit_minor - line.credit_minor for line in lines}
    assert net.get(GRNI_ACCOUNT, 0) == accrued
    # A zero payable (everything withheld) has no line at all.
    assert net.get("accounts_payable", 0) == -(amount + vat - wht)
