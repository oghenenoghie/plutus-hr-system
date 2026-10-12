"""Pure posting rules for inventory (Phase 3, docs/architecture/
inventory-integration.md §15). No ORM: app/services/inventory_accounting.py
gathers the figures and app/services/posting.py persists the result.

Every inventory journal is built from *legs*: an account and a signed
amount, debit positive and credit negative. Legs on the same account net
off, so a document's journal has one line per account however many stock
lines it had.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.accounting.posting_rules import PostingLine

# The accounts inventory posts to, seeded into the chart when inventory
# accounting starts (app/services/inventory_accounting.py).
INVENTORY_ACCOUNT = "inventory"
GRNI_ACCOUNT = "grni"  # goods received not invoiced (D2)
CONSUMPTION_ACCOUNT = "inventory_consumption"  # default issue expense (D18)
ADJUSTMENT_ACCOUNT = "inventory_adjustment"  # write-offs, gains, transit losses, cost variances
OPENING_BALANCE_ACCOUNT = "inventory_opening_balance"  # equity: opening stock


@dataclass(frozen=True)
class Leg:
    account: str
    amount_minor: int  # debit positive, credit negative


def journal_lines(legs: Iterable[Leg], *, description: str | None = None) -> list[PostingLine]:
    """Nets the legs per account (first-seen order) and drops accounts that
    net to zero. Raises ValueError if the legs don't balance. Returns an
    empty list when everything nets to zero: there is nothing to post."""
    totals: dict[str, int] = {}
    for leg in legs:
        totals[leg.account] = totals.get(leg.account, 0) + leg.amount_minor
    if sum(totals.values()) != 0:
        raise ValueError(f"inventory journal does not balance by {sum(totals.values())}")
    return [
        PostingLine(
            account=account,
            debit_minor=max(0, amount),
            credit_minor=max(0, -amount),
            description=description,
        )
        for account, amount in totals.items()
        if amount != 0
    ]


def counter_legs(inventory_delta_minor: int, counter_account: str) -> list[Leg]:
    """The common shape: stock value moves by `inventory_delta_minor` and
    one other account takes the opposite side."""
    return [
        Leg(INVENTORY_ACCOUNT, inventory_delta_minor),
        Leg(counter_account, -inventory_delta_minor),
    ]


def reversal_variance_legs(actual_delta_minor: int, mirrored_delta_minor: int) -> list[Leg]:
    """A reversal mirrors the original journal exactly, but the stock it
    moves is valued by the cost pool *now*: stock the original added leaves
    at today's average. The difference between what the stock ledger moved
    and what the mirror moved is a cost variance, booked to the adjustment
    account so the inventory account keeps matching stock value."""
    return counter_legs(actual_delta_minor - mirrored_delta_minor, ADJUSTMENT_ACCOUNT)


def bill_legs(
    *,
    amount_minor: int,
    vat_minor: int,
    wht_minor: int,
    expense_account: str,
    grni_cleared_minor: int,
) -> list[Leg]:
    """A vendor bill's journal (D2, D14). `grni_cleared_minor` is what the
    linked goods receipt accrued to goods-received-not-invoiced (0 for a
    bill with no receipt). That much of the bill clears GRNI; the rest of
    the amount (price differences, non-stock lines, delivery charges) goes
    to the bill's expense account, and is a credit there when the bill
    comes in under the accrual. VAT stays recoverable input VAT; WHT is
    withheld from the payable."""
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    if vat_minor < 0 or wht_minor < 0 or grni_cleared_minor < 0:
        raise ValueError("amounts cannot be negative")
    legs = [
        Leg(GRNI_ACCOUNT, grni_cleared_minor),
        Leg(expense_account, amount_minor - grni_cleared_minor),
        Leg("vat_receivable", vat_minor),
        Leg("wht_payable", -wht_minor),
        Leg("accounts_payable", -(amount_minor + vat_minor - wht_minor)),
    ]
    return [leg for leg in legs if leg.amount_minor != 0]
