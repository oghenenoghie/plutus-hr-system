import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bill import Bill, BillStatus
from app.models.chart_account import AccountType, ChartAccount
from app.schemas.general_ledger import JournalEntryLineCreate
from app.services.general_ledger import post_manual_journal_entry


def _expense_account_or_raise(db: Session, *, org_id: uuid.UUID, code: str) -> ChartAccount:
    account = db.scalar(
        select(ChartAccount).where(ChartAccount.org_id == org_id, ChartAccount.code == code)
    )
    if account is None or account.type != AccountType.EXPENSE:
        raise ValueError(f"{code!r} is not a known expense account")
    return account


def register_bill(
    db: Session,
    *,
    org_id: uuid.UUID,
    vendor_id: uuid.UUID,
    bill_number: str,
    bill_date: date,
    due_date: date,
    expense_account_code: str,
    amount_minor: int,
    description: str | None = None,
) -> Bill:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    if due_date < bill_date:
        raise ValueError("due_date cannot be before bill_date")
    _expense_account_or_raise(db, org_id=org_id, code=expense_account_code)

    bill = Bill(
        org_id=org_id,
        vendor_id=vendor_id,
        bill_number=bill_number,
        bill_date=bill_date,
        due_date=due_date,
        expense_account_code=expense_account_code,
        amount_minor=amount_minor,
        description=description,
    )
    db.add(bill)
    db.flush()
    return bill


def approve_bill(db: Session, bill: Bill) -> Bill:
    if bill.status != BillStatus.DRAFT:
        raise ValueError(f"only a draft bill can be approved (this bill is {bill.status.value})")

    post_manual_journal_entry(
        db,
        org_id=bill.org_id,
        description=f"Bill {bill.bill_number} approved",
        lines=[
            JournalEntryLineCreate(
                account_code=bill.expense_account_code, debit_minor=bill.amount_minor
            ),
            JournalEntryLineCreate(account_code="accounts_payable", credit_minor=bill.amount_minor),
        ],
    )
    bill.status = BillStatus.APPROVED
    db.add(bill)
    db.flush()
    return bill


def pay_bill(db: Session, bill: Bill, *, cash_account_code: str = "cash") -> Bill:
    if bill.status != BillStatus.APPROVED:
        raise ValueError(f"only an approved bill can be paid (this bill is {bill.status.value})")

    post_manual_journal_entry(
        db,
        org_id=bill.org_id,
        description=f"Bill {bill.bill_number} paid",
        lines=[
            JournalEntryLineCreate(account_code="accounts_payable", debit_minor=bill.amount_minor),
            JournalEntryLineCreate(account_code=cash_account_code, credit_minor=bill.amount_minor),
        ],
    )
    bill.status = BillStatus.PAID
    bill.paid_at = datetime.now(UTC)
    db.add(bill)
    db.flush()
    return bill


def void_bill(db: Session, bill: Bill) -> Bill:
    if bill.status != BillStatus.DRAFT:
        raise ValueError(f"only a draft bill can be voided (this bill is {bill.status.value})")
    bill.status = BillStatus.VOID
    db.add(bill)
    db.flush()
    return bill
