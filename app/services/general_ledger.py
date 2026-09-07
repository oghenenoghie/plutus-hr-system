import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chart_account import ChartAccount
from app.models.ledger import LedgerEntry
from app.schemas.general_ledger import JournalEntryLineCreate, LedgerEntryOut, TrialBalanceLine


def _chart_accounts_by_code(db: Session, *, org_id: uuid.UUID) -> dict[str, ChartAccount]:
    accounts = db.scalars(select(ChartAccount).where(ChartAccount.org_id == org_id))
    return {account.code: account for account in accounts}


def list_ledger_entries(
    db: Session,
    *,
    org_id: uuid.UUID,
    account: str | None = None,
    pay_run_id: uuid.UUID | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[LedgerEntryOut]:
    stmt = select(LedgerEntry).order_by(LedgerEntry.created_at.desc())
    if account is not None:
        stmt = stmt.where(LedgerEntry.account == account)
    if pay_run_id is not None:
        stmt = stmt.where(LedgerEntry.pay_run_id == pay_run_id)
    if from_date is not None:
        stmt = stmt.where(LedgerEntry.created_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(LedgerEntry.created_at < to_date)

    accounts_by_code = _chart_accounts_by_code(db, org_id=org_id)
    entries = []
    for entry in db.scalars(stmt):
        chart_account = accounts_by_code.get(entry.account)
        entries.append(
            LedgerEntryOut(
                **{
                    field: getattr(entry, field)
                    for field in (
                        "id",
                        "org_id",
                        "journal_entry_id",
                        "pay_run_id",
                        "employee_id",
                        "account",
                        "debit_minor",
                        "credit_minor",
                        "description",
                        "created_at",
                    )
                },
                account_name=chart_account.name if chart_account else None,
            )
        )
    return entries


def trial_balance(db: Session, *, org_id: uuid.UUID) -> list[TrialBalanceLine]:
    totals: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for entry in db.scalars(select(LedgerEntry)):
        debit, credit = totals[entry.account]
        totals[entry.account] = (debit + entry.debit_minor, credit + entry.credit_minor)

    accounts_by_code = _chart_accounts_by_code(db, org_id=org_id)
    lines = []
    for code, (total_debit, total_credit) in sorted(totals.items()):
        chart_account = accounts_by_code.get(code)
        lines.append(
            TrialBalanceLine(
                account=code,
                account_name=chart_account.name if chart_account else None,
                account_type=chart_account.type if chart_account else None,
                total_debit_minor=total_debit,
                total_credit_minor=total_credit,
                balance_minor=total_debit - total_credit,
            )
        )
    return lines


def post_manual_journal_entry(
    db: Session,
    *,
    org_id: uuid.UUID,
    description: str,
    lines: list[JournalEntryLineCreate],
) -> list[LedgerEntryOut]:
    if len(lines) < 2:
        raise ValueError("a journal entry needs at least two lines")

    accounts_by_code = _chart_accounts_by_code(db, org_id=org_id)
    total_debit = 0
    total_credit = 0
    for line in lines:
        if line.account_code not in accounts_by_code:
            raise ValueError(f"unknown account code: {line.account_code}")
        if line.debit_minor < 0 or line.credit_minor < 0:
            raise ValueError("amounts cannot be negative")
        if (line.debit_minor > 0) == (line.credit_minor > 0):
            raise ValueError(
                f"line for {line.account_code} must be either a debit or a credit, not both/neither"
            )
        total_debit += line.debit_minor
        total_credit += line.credit_minor

    if total_debit != total_credit:
        raise ValueError(f"entry does not balance: debits {total_debit} != credits {total_credit}")

    journal_entry_id = uuid.uuid4()
    entries = []
    for line in lines:
        entry = LedgerEntry(
            org_id=org_id,
            journal_entry_id=journal_entry_id,
            account=line.account_code,
            debit_minor=line.debit_minor,
            credit_minor=line.credit_minor,
            description=line.description or description,
        )
        db.add(entry)
        entries.append(entry)
    db.flush()

    return [
        LedgerEntryOut(
            id=entry.id,
            org_id=entry.org_id,
            journal_entry_id=entry.journal_entry_id,
            pay_run_id=entry.pay_run_id,
            employee_id=entry.employee_id,
            account=entry.account,
            account_name=accounts_by_code[entry.account].name,
            debit_minor=entry.debit_minor,
            credit_minor=entry.credit_minor,
            description=entry.description,
            created_at=entry.created_at,
        )
        for entry in entries
    ]
