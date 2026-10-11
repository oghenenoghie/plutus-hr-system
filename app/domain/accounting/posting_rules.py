"""Pure double-entry posting rules — no ORM, no FastAPI, same discipline as
app/domain/payroll/postings.py. Each builder turns one business event into
balanced PostingLines; app/services/posting.py is the only thing that
persists them.

Account codes here are the same literal slugs every existing posting site
already writes (app/services/chart_accounts.py DEFAULT_ACCOUNTS). Mapping
them through configurable posting *roles* is a later phase
(ACCOUNTING_IMPLEMENTATION_AUDIT.md §20.4); keeping every literal in this
one module is what makes that a one-file change.
"""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# Where cash leaves the business. A single hard-coded account today (audit
# P11) — bank selection arrives with the bank-account work.
CASH_ACCOUNT = "cash"

# The liability each statutory scheme's accrual credits, i.e. the account a
# remittance to the authority must clear. ITF is deliberately absent: its
# annual liability is tracked in statutory_liabilities but never accrued to
# the ledger (audit §6.2), so there is no payable to clear — posting a
# remittance would debit an account that was never credited.
SCHEME_PAYABLE_ACCOUNT: Mapping[str, str] = {
    "paye": "paye_payable",
    "pension": "pension_payable",
    "nhf": "nhf_payable",
    "nsitf": "nsitf_payable",
    "wht": "wht_payable",
}


@dataclass(frozen=True)
class PostingLine:
    """One side of one account. Exactly one of debit_minor/credit_minor is
    positive; the other is zero (mirrors the ledger_entries CHECK)."""

    account: str
    debit_minor: int = 0
    credit_minor: int = 0
    description: str | None = None
    employee_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    pay_run_id: uuid.UUID | None = None


def assert_balanced(lines: Iterable[PostingLine]) -> None:
    """Raises ValueError unless the lines are individually well-formed and
    total debits equal total credits. The database repeats this check in a
    deferred trigger; this one exists so a bad posting is rejected with a
    readable message before anything is written."""
    materialised = list(lines)
    if len(materialised) < 2:
        raise ValueError("a journal entry needs at least two lines")
    total_debit = 0
    total_credit = 0
    for line in materialised:
        if line.debit_minor < 0 or line.credit_minor < 0:
            raise ValueError("amounts cannot be negative")
        if (line.debit_minor > 0) == (line.credit_minor > 0):
            raise ValueError(
                f"line for {line.account} must be either a debit or a credit, not both/neither"
            )
        total_debit += line.debit_minor
        total_credit += line.credit_minor
    if total_debit != total_credit:
        raise ValueError(f"entry does not balance: debits {total_debit} != credits {total_credit}")


def mirror_postings(
    lines: Iterable[PostingLine], *, description: str | None = None
) -> tuple[PostingLine, ...]:
    """The correcting entry for `lines`: every line with debit and credit
    swapped, same account, same amount, same dimensions. Applying it after
    the original nets every account back to where it started.

    `description`, when given, replaces each line's description; otherwise
    the original's is kept."""
    return tuple(
        PostingLine(
            account=line.account,
            debit_minor=line.credit_minor,
            credit_minor=line.debit_minor,
            description=description if description is not None else line.description,
            employee_id=line.employee_id,
            department_id=line.department_id,
            pay_run_id=line.pay_run_id,
        )
        for line in lines
    )


def build_statutory_remittance_postings(
    scheme: str, amount_minor: int, *, description: str | None = None
) -> tuple[PostingLine, ...] | None:
    """Paying a statutory authority clears the liability that payroll
    accrued: Dr <scheme>_payable / Cr cash.

    Returns None for a scheme with no accrued payable (ITF) — the caller
    records the remittance on the liability but posts nothing.

    The lines deliberately carry no pay_run_id. Reversing a pay run mirrors
    every ledger line tagged with that run; money that has already left the
    business to an authority must not be mirrored back by it.
    """
    if amount_minor <= 0:
        raise ValueError("a remittance amount must be positive")
    payable = SCHEME_PAYABLE_ACCOUNT.get(scheme)
    if payable is None:
        return None
    return (
        PostingLine(payable, debit_minor=amount_minor, description=description),
        PostingLine(CASH_ACCOUNT, credit_minor=amount_minor, description=description),
    )
