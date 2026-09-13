import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bank_statement_line import BankStatementLine
from app.models.ledger import LedgerEntry


@dataclass(frozen=True)
class BankStatementLineImport:
    transaction_date: date
    description: str
    amount_minor: int
    external_reference: str | None = None


def import_statement_lines(
    db: Session, *, org_id: uuid.UUID, account_code: str, lines: list[BankStatementLineImport]
) -> list[BankStatementLine]:
    rows = [
        BankStatementLine(
            org_id=org_id,
            account_code=account_code,
            transaction_date=line.transaction_date,
            description=line.description,
            amount_minor=line.amount_minor,
            external_reference=line.external_reference,
        )
        for line in lines
    ]
    db.add_all(rows)
    db.flush()
    return rows


def match_statement_line(
    db: Session,
    line: BankStatementLine,
    *,
    ledger_entry_id: uuid.UUID,
    matched_by: uuid.UUID | None,
) -> BankStatementLine:
    if line.matched_ledger_entry_id is not None:
        raise ValueError("this statement line is already matched")

    ledger_entry = db.get(LedgerEntry, ledger_entry_id)
    if ledger_entry is None or ledger_entry.org_id != line.org_id:
        raise ValueError("ledger entry not found")
    if ledger_entry.account != line.account_code:
        raise ValueError(
            f"ledger entry is on account {ledger_entry.account!r}, not {line.account_code!r}"
        )
    already_matched = db.scalar(
        select(BankStatementLine).where(
            BankStatementLine.matched_ledger_entry_id == ledger_entry_id
        )
    )
    if already_matched is not None:
        raise ValueError("this ledger entry is already matched to another statement line")

    ledger_contribution = ledger_entry.debit_minor - ledger_entry.credit_minor
    if ledger_contribution != line.amount_minor:
        raise ValueError(
            f"amount mismatch: statement line is {line.amount_minor}, "
            f"ledger entry is {ledger_contribution}"
        )

    line.matched_ledger_entry_id = ledger_entry_id
    line.matched_at = datetime.now(UTC)
    line.matched_by = matched_by
    db.add(line)
    db.flush()
    return line


def unmatch_statement_line(db: Session, line: BankStatementLine) -> BankStatementLine:
    if line.matched_ledger_entry_id is None:
        raise ValueError("this statement line is not matched")
    line.matched_ledger_entry_id = None
    line.matched_at = None
    line.matched_by = None
    db.add(line)
    db.flush()
    return line


@dataclass(frozen=True)
class ReconciliationStatus:
    unmatched_statement_lines: list[BankStatementLine]
    unmatched_ledger_entries: list[LedgerEntry]


def reconciliation_status(
    db: Session, org_id: uuid.UUID, account_code: str
) -> ReconciliationStatus:
    unmatched_statement_lines = list(
        db.scalars(
            select(BankStatementLine)
            .where(
                BankStatementLine.org_id == org_id,
                BankStatementLine.account_code == account_code,
                BankStatementLine.matched_ledger_entry_id.is_(None),
            )
            .order_by(BankStatementLine.transaction_date)
        )
    )
    matched_ledger_entry_ids = select(BankStatementLine.matched_ledger_entry_id).where(
        BankStatementLine.matched_ledger_entry_id.is_not(None)
    )
    unmatched_ledger_entries = list(
        db.scalars(
            select(LedgerEntry)
            .where(
                LedgerEntry.org_id == org_id,
                LedgerEntry.account == account_code,
                LedgerEntry.id.not_in(matched_ledger_entry_ids),
            )
            .order_by(LedgerEntry.created_at)
        )
    )
    return ReconciliationStatus(
        unmatched_statement_lines=unmatched_statement_lines,
        unmatched_ledger_entries=unmatched_ledger_entries,
    )
