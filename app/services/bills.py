import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.models import RuleVersion
from app.domain.inventory.accounting import bill_legs
from app.domain.payroll.wht import compute_wht
from app.models.bill import Bill, BillStatus
from app.models.chart_account import AccountType, ChartAccount
from app.schemas.general_ledger import JournalEntryLineCreate
from app.services.general_ledger import post_manual_journal_entry
from app.services.inventory_accounting import billable_receipt


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
    vat_minor: int = 0,
    wht_category: str | None = None,
    description: str | None = None,
    goods_receipt_id: uuid.UUID | None = None,
) -> Bill:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    if vat_minor < 0:
        raise ValueError("vat_minor cannot be negative")
    if due_date < bill_date:
        raise ValueError("due_date cannot be before bill_date")
    _expense_account_or_raise(db, org_id=org_id, code=expense_account_code)
    if goods_receipt_id is not None:
        # D2: checked again at approval, which is when the accrual clears.
        billable_receipt(db, org_id=org_id, receipt_id=goods_receipt_id, vendor_id=vendor_id)

    bill = Bill(
        org_id=org_id,
        vendor_id=vendor_id,
        bill_number=bill_number,
        bill_date=bill_date,
        due_date=due_date,
        expense_account_code=expense_account_code,
        amount_minor=amount_minor,
        vat_minor=vat_minor,
        wht_category=wht_category,
        description=description,
        goods_receipt_id=goods_receipt_id,
    )
    db.add(bill)
    db.flush()
    return bill


def approve_bill(db: Session, bill: Bill, *, rules: RuleVersion | None = None) -> Bill:
    if bill.status != BillStatus.DRAFT:
        raise ValueError(f"only a draft bill can be approved (this bill is {bill.status.value})")
    if bill.wht_category is not None and rules is None:
        raise ValueError("rules is required to approve a bill with a wht_category")

    wht_amount_minor = (
        compute_wht(bill.amount_minor, bill.wht_category, rules.wht)
        if bill.wht_category is not None and rules is not None
        else 0
    )

    # D2: a bill for a goods receipt clears what the receipt accrued to
    # goods-received-not-invoiced; only the rest of the amount is expensed.
    grni_cleared_minor = 0
    if bill.goods_receipt_id is not None:
        _, grni_cleared_minor = billable_receipt(
            db,
            org_id=bill.org_id,
            receipt_id=bill.goods_receipt_id,
            vendor_id=bill.vendor_id,
            bill_id=bill.id,
        )
    lines = [
        JournalEntryLineCreate(
            account_code=leg.account,
            debit_minor=max(0, leg.amount_minor),
            credit_minor=max(0, -leg.amount_minor),
        )
        for leg in bill_legs(
            amount_minor=bill.amount_minor,
            vat_minor=bill.vat_minor,
            wht_minor=wht_amount_minor,
            expense_account=bill.expense_account_code,
            grni_cleared_minor=grni_cleared_minor,
        )
    ]
    post_manual_journal_entry(
        db, org_id=bill.org_id, description=f"Bill {bill.bill_number} approved", lines=lines
    )
    bill.wht_amount_minor = wht_amount_minor
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
            JournalEntryLineCreate(
                account_code="accounts_payable", debit_minor=bill.net_payable_minor
            ),
            JournalEntryLineCreate(
                account_code=cash_account_code, credit_minor=bill.net_payable_minor
            ),
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
