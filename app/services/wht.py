import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.compliance.models import RuleVersion
from app.domain.payroll.deadlines import wht_deadline
from app.domain.payroll.wht import compute_wht
from app.models.contractor import Contractor
from app.models.ledger import LedgerEntry
from app.models.statutory_liability import LiabilityScheme, StatutoryLiability
from app.models.wht_payment import WhtPayment


class MissingContractorTinError(Exception):
    """A contractor payment must not proceed without a valid TIN — the
    same pre-payment gate employees get before a payroll run
    (nigeria-statutory-compliance.md §8: 'validate vendor TIN too')."""


def record_contractor_payment(
    db: Session,
    *,
    org_id: uuid.UUID,
    contractor: Contractor,
    category: str,
    gross_amount_minor: int,
    payment_date: date,
    rules: RuleVersion,
) -> WhtPayment:
    """Withhold tax at source on one contractor/vendor payment, resolved by
    service category (§8 — never a flat rate), post the balanced ledger
    entries, and raise the corresponding statutory liability the same way
    a pay run would for PAYE/pension/NHF/NSITF.

    Postings: Dr contractor_expense (gross) / Cr cash (net) + Cr
    wht_payable (withheld) — the employer's full cost is the gross amount,
    of which only the net actually leaves the bank; the withheld portion
    becomes a liability owed to the NRS, not company cash.
    """
    if not contractor.tin or not contractor.tin.strip():
        raise MissingContractorTinError("contractor has no valid TIN; payment must not proceed")
    if gross_amount_minor <= 0:
        raise ValueError("gross_amount_minor must be positive")

    wht_amount_minor = compute_wht(gross_amount_minor, category, rules.wht)
    net_amount_minor = gross_amount_minor - wht_amount_minor
    due_date = wht_deadline(payment_date, rules.wht)

    # Generated client-side (not a DB default) so the certificate number
    # can be derived from it at construction time — wht_payments is
    # append-only, so there is no later UPDATE to set it after the fact.
    payment_id = uuid.uuid4()
    payment = WhtPayment(
        id=payment_id,
        org_id=org_id,
        contractor_id=contractor.id,
        category=category,
        gross_amount_minor=gross_amount_minor,
        wht_amount_minor=wht_amount_minor,
        net_amount_minor=net_amount_minor,
        payment_date=payment_date,
        due_date=due_date,
        certificate_number=f"WHT-{payment_id}",
        rule_version_id=rules.id,
    )
    db.add(payment)

    # Ledger entries must be single-sided and nonzero (DB check constraint),
    # so a payment small enough that the withheld amount rounds to zero
    # gets no wht_payable line and no liability — same guard NSITF's
    # pay-run-level posting uses for the same reason.
    journal_entry_id = uuid.uuid4()
    description = f"Contractor payment to {contractor.name}, {payment_date}"
    db.add(
        LedgerEntry(
            org_id=org_id,
            journal_entry_id=journal_entry_id,
            account="contractor_expense",
            debit_minor=gross_amount_minor,
            credit_minor=0,
            description=description,
        )
    )
    db.add(
        LedgerEntry(
            org_id=org_id,
            journal_entry_id=journal_entry_id,
            account="cash",
            debit_minor=0,
            credit_minor=net_amount_minor,
            description=description,
        )
    )
    if wht_amount_minor > 0:
        db.add(
            LedgerEntry(
                org_id=org_id,
                journal_entry_id=journal_entry_id,
                account="wht_payable",
                debit_minor=0,
                credit_minor=wht_amount_minor,
                description=description,
            )
        )
        db.add(
            StatutoryLiability(
                org_id=org_id,
                pay_run_id=None,
                scheme=LiabilityScheme.WHT,
                authority=rules.wht.authority,
                base_minor=gross_amount_minor,
                amount_minor=wht_amount_minor,
                period_start=payment_date,
                period_end=payment_date,
                due_date=due_date,
            )
        )

    db.flush()
    return payment
