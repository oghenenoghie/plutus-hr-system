import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bank_statement_line import BankStatementLine
from app.models.chart_account import ChartAccount
from app.models.company_bank_account import CompanyBankAccount
from app.models.ledger import LedgerEntry
from app.schemas.bank_reconciliation import (
    BankStatementLineCreate,
    BankStatementLineOut,
    ReconciliationSummaryOut,
)
from app.schemas.general_ledger import LedgerEntryOut


def create_statement_line(
    db: Session, bank_account: CompanyBankAccount, body: BankStatementLineCreate
) -> BankStatementLine:
    if body.amount_minor == 0:
        raise ValueError("amount_minor cannot be zero")

    line = BankStatementLine(
        org_id=bank_account.org_id,
        bank_account_id=bank_account.id,
        statement_date=body.statement_date,
        description=body.description,
        amount_minor=body.amount_minor,
    )
    db.add(line)
    db.flush()
    return line


def list_statement_lines(db: Session, bank_account: CompanyBankAccount) -> list[BankStatementLine]:
    return list(
        db.scalars(
            select(BankStatementLine)
            .where(BankStatementLine.bank_account_id == bank_account.id)
            .order_by(BankStatementLine.statement_date.desc())
        )
    )


def match_line(
    db: Session,
    line: BankStatementLine,
    bank_account: CompanyBankAccount,
    *,
    ledger_entry_id: uuid.UUID,
) -> BankStatementLine:
    if line.matched_ledger_entry_id is not None:
        raise ValueError("this statement line is already matched")

    entry = db.get(LedgerEntry, ledger_entry_id)
    if entry is None or entry.org_id != bank_account.org_id:
        raise ValueError("ledger entry not found")
    if entry.account != bank_account.chart_account_code:
        raise ValueError(
            f"ledger entry is on {entry.account!r}, not this account's {bank_account.chart_account_code!r}"
        )

    already_matched = db.scalar(
        select(BankStatementLine.id).where(
            BankStatementLine.matched_ledger_entry_id == ledger_entry_id
        )
    )
    if already_matched is not None:
        raise ValueError("this ledger entry is already matched to another statement line")

    expected = entry.debit_minor - entry.credit_minor
    if expected != line.amount_minor:
        raise ValueError(
            f"amount mismatch: statement line is {line.amount_minor}, ledger entry is {expected}"
        )

    line.matched_ledger_entry_id = ledger_entry_id
    db.add(line)
    db.flush()
    return line


def unmatch_line(db: Session, line: BankStatementLine) -> BankStatementLine:
    line.matched_ledger_entry_id = None
    db.add(line)
    db.flush()
    return line


def reconciliation_summary(
    db: Session, bank_account: CompanyBankAccount
) -> ReconciliationSummaryOut:
    statement_lines = list_statement_lines(db, bank_account)
    bank_balance_minor = sum(line.amount_minor for line in statement_lines)
    unmatched_statement_lines = [
        BankStatementLineOut.model_validate(line)
        for line in statement_lines
        if line.matched_ledger_entry_id is None
    ]

    ledger_entries = list(
        db.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.org_id == bank_account.org_id)
            .where(LedgerEntry.account == bank_account.chart_account_code)
            .order_by(LedgerEntry.created_at.desc())
        )
    )
    ledger_balance_minor = sum(entry.debit_minor - entry.credit_minor for entry in ledger_entries)

    matched_entry_ids = {
        line.matched_ledger_entry_id
        for line in statement_lines
        if line.matched_ledger_entry_id is not None
    }
    chart_account = db.scalar(
        select(ChartAccount).where(
            ChartAccount.org_id == bank_account.org_id,
            ChartAccount.code == bank_account.chart_account_code,
        )
    )
    unmatched_ledger_entries = [
        LedgerEntryOut(
            id=entry.id,
            org_id=entry.org_id,
            journal_entry_id=entry.journal_entry_id,
            pay_run_id=entry.pay_run_id,
            employee_id=entry.employee_id,
            account=entry.account,
            account_name=chart_account.name if chart_account else None,
            debit_minor=entry.debit_minor,
            credit_minor=entry.credit_minor,
            description=entry.description,
            created_at=entry.created_at,
        )
        for entry in ledger_entries
        if entry.id not in matched_entry_ids
    ]

    return ReconciliationSummaryOut(
        bank_account_id=bank_account.id,
        bank_balance_minor=bank_balance_minor,
        ledger_balance_minor=ledger_balance_minor,
        difference_minor=bank_balance_minor - ledger_balance_minor,
        unmatched_statement_lines=unmatched_statement_lines,
        unmatched_ledger_entries=unmatched_ledger_entries,
    )
